"""Roda o GrowthAgent sobre a CARTEIRA ATIVA inteira e persiste (score+alerta+
auditoria+sinais). Universo = grupos de WhatsApp ATIVOS (is_active, não
[FINALIZADO]) que seguem o padrão cliente (têm `ID: XXXX` no nome).

    # teste barato (amostra):
    backend/.venv/Scripts/python -m scripts.run_portfolio --limit 8
    # rodada real (carteira inteira, AO VIVO):
    backend/.venv/Scripts/python -m scripts.run_portfolio
    # universo do cache (sem rede) só p/ inspecionar a lista:
    backend/.venv/Scripts/python -m scripts.run_portfolio --from-cache --dry-list
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import re
import sys
import unicodedata
import uuid
from pathlib import Path

import psycopg

from app.agents.base import AgentContext
from app.agents.growth.agent import GrowthAgent
from app.agents.growth.execution_collector import execution_asof
from app.audit import DbAuditSink
from app.db import persistence as P
from app.sources.mirror import MirrorReader

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
TODAY = dt.date.today()
_FINALIZED = re.compile(r"final\w*z|encerrad", re.I)  # tolera typo (FINALZADO) + finalizado/encerrado
_HAS_ID = re.compile(r"id\s*:\s*[a-z0-9_-]+", re.I)
_CLIENT_TAG = re.compile(r"^\s*\[")  # nome de cliente começa com [tag de plano/serviço]
_BUNDLE = re.compile(r"\bB\d\b", re.I)


def load_env() -> None:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def norm(s: str | None) -> str:
    if not s:
        return ""
    x = unicodedata.normalize("NFD", s.lower())
    x = "".join(c for c in x if unicodedata.category(c) != "Mn")
    x = re.sub(r"^\s*\[[^\]]*\]\s*", "", x).split("|")[0].replace("integracomm", "")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", x)).strip()


def exid(s: str | None) -> str | None:
    m = re.search(r"id\s*:\s*([a-z0-9_-]+)", s or "", re.I)
    return m.group(1).lower() if m else None


def is_client_active(name: str, is_active: bool) -> bool:
    """Grupo é de CLIENTE ativo? Ativo, não-[FINALIZADO], e segue a convenção de
    nome de cliente: tem `ID: XXXX` OU começa com `[tag de plano/serviço]` e tem
    separador `|` (ex.: grupos ADS `[ADS-GU] NOME | GESTOR`, sem ID impresso —
    era o buraco que escondia a SOLUTION STORE e ~80 outros). Grupos internos/de
    equipe não seguem esse padrão."""
    if not (is_active and name and not _FINALIZED.search(name)):
        return False
    return bool(_HAS_ID.search(name) or (_CLIENT_TAG.match(name) and "|" in name))


def mrr_index() -> dict[str, float]:
    idx: dict[str, float] = {}
    path = DATA / "nps_fat.csv"
    if not path.exists():
        return idx
    with path.open(encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            v = re.sub(r"[^\d,]", "", r.get("Assessoria (currency)", "")).replace(",", ".")
            if v:
                try:
                    idx[norm(r.get("Task Name"))] = float(v)
                except ValueError:
                    pass
    return idx


def universe_live():
    """(id_interno_grupo, name) dos grupos ativos-cliente, AO VIVO."""
    from app.sources.whatsapp import WhatsAppReader
    reader = WhatsAppReader(os.environ["WHATSAPP_READ_API_URL"], os.environ["WHATSAPP_READ_API_KEY"])
    try:
        for g in reader.iter_groups():
            if is_client_active(g.name, g.is_active):
                yield g.id, g.name
    finally:
        reader.close()


def universe_cache():
    """Mesmo universo, mas do cache data/wa_groups.csv (sem rede)."""
    with (DATA / "wa_groups.csv").open(encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            # cache não tem is_active confiável -> usa só nome (não-finalizado + ID)
            if is_client_active(r.get("name", ""), True):
                yield r["id"], r["name"]


def _mirror_creds():
    ps1 = (Path(__file__).resolve().parents[1] / "scripts" / "exec_signals.ps1").read_text(encoding="utf-8")
    return (re.search(r'base="([^"]+)"', ps1).group(1), re.search(r'anon="([^"]+)"', ps1).group(1))


def monthly_mrr(valor: float | None, servico: str | None) -> float | None:
    """MRR MENSAL real: plano B1-START é pago em parcela única SEMESTRAL —
    valor registrado / 6 (regra do Otávio, 2026-07-03). Demais planos: valor
    registrado já é mensal."""
    if valor is None:
        return None
    if servico and "start" in servico.lower():
        return round(valor / 6, 2)
    return valor


def mirror_enrich(sample, audit, run_id):
    """Contexto NÃO-pontuador: casa cada conta ao cliente por nome, seta MRR
    (valor_assessoria, mensalizado p/ Start) e devolve (cli_por_conta,
    subs_por_cliente) p/ o score de execução. Subtarefas: preferimos a lista
    Assessoria COMPLETA via API oficial do ClickUp (o mirror cobre só ~51%);
    mirror entra como fallback por conta. Falha graciosa."""
    try:
        base, anon = _mirror_creds()
        reader = MirrorReader(base, anon, audit=audit, run_id=run_id)
    except Exception as e:
        print(f"  [mirror] indisponível ({type(e).__name__}) — segue sem contexto de execução", file=sys.stderr)
        return {}, {}
    try:
        by_name = {}
        for c in reader.clientes():
            n = norm(c.nome_cliente)
            if n:
                by_name.setdefault(n, c)
        cli_por_conta = {}
        for s in sample:
            c = by_name.get(norm(s["name"]))
            if c:
                cli_por_conta[s["account_id"]] = c
                mrr = monthly_mrr(c.valor_assessoria or None, c.servico)
                if mrr:  # MRR mensalizado manda na priorização
                    s["recurring_revenue"] = mrr
        subs = reader.subtarefas_by_cliente([c.id for c in cli_por_conta.values()])
        print(f"  [mirror] {len(cli_por_conta)}/{len(sample)} contas casadas ao cliente", file=sys.stderr)
        # subtarefas completas via API oficial (quando o token permite)
        try:
            from app.sources.clickup_activities import api_subs_by_norm
            api_subs = api_subs_by_norm()
            n_api = 0
            for aid, cli in cli_por_conta.items():
                full = api_subs.get(norm(cli.nome_cliente))
                if full:
                    subs[cli.id] = full
                    n_api += 1
            print(f"  [exec] subtarefas via API ClickUp (lista completa) p/ {n_api} contas; "
                  f"mirror cobre o restante", file=sys.stderr)
        except Exception as e:  # noqa: BLE001 — API fora -> segue 100% mirror
            print(f"  [exec] API ClickUp indisponível ({type(e).__name__}) — usando só o mirror", file=sys.stderr)
        return cli_por_conta, subs
    finally:
        reader.close()


def persist_exec(conn_factory, cli_por_conta, subs, asof, run_id):
    """Grava o score de execução as-of como signal_snapshot NÃO-líder (contexto)."""
    if not cli_por_conta:
        return 0
    conn = conn_factory()
    n = 0
    try:
        with conn.cursor() as cur:
            for acct_id, cli in cli_por_conta.items():
                res = execution_asof(cli, subs.get(cli.id, []), asof)
                if res.score is None:
                    continue
                cur.execute("SELECT id FROM accounts WHERE id_interno=%s", (acct_id,))
                row = cur.fetchone()
                if not row:
                    continue
                mrr = monthly_mrr(cli.valor_assessoria or None, cli.servico)
                if mrr:  # MRR mensalizado (Start = semestral/6) na priorização
                    cur.execute("UPDATE accounts SET recurring_revenue=%s WHERE id=%s",
                                (mrr, row[0]))
                P.record_signal_snapshots(
                    conn, account_id=row[0], run_id=run_id,
                    captured_at=dt.datetime.combine(asof.date() if isinstance(asof, dt.datetime) else asof, dt.time.max, tzinfo=dt.timezone.utc),
                    signals=[{"source": "clickup", "signal_key": "exec_score",
                              "value_num": res.score, "value_text": res.motivo[:300], "leading": False}],
                )
                n += 1
        conn.commit()
    finally:
        conn.close()
    return n


def load_tone_series(conn_factory) -> dict[str, list[tuple[dt.date, float]]]:
    """Série semanal de tom (tom_claude) cacheada pelo run_tone_analysis, por
    id_interno da conta. Vazio se a análise nunca rodou (sinal fica fora do bloco)."""
    out: dict[str, list[tuple[dt.date, float]]] = {}
    conn = conn_factory()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT a.id_interno, s.captured_at, s.value_num
                     FROM signal_snapshots s JOIN accounts a ON a.id = s.account_id
                    WHERE s.signal_key = 'tom_claude' AND a.id_interno IS NOT NULL
                    ORDER BY s.captured_at""")
            for id_interno, ts, risk in cur.fetchall():
                out.setdefault(id_interno, []).append((ts.date(), float(risk)))
    finally:
        conn.close()
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="máx. de contas (0 = todas)")
    ap.add_argument("--from-cache", action="store_true", help="universo do cache CSV (sem rede)")
    ap.add_argument("--dry-list", action="store_true", help="só lista o universo, não roda/persiste")
    ap.add_argument("--no-exec", action="store_true", help="pula o contexto de execução/MRR do mirror")
    ap.add_argument("--exec-only", action="store_true", help="só enriquece exec/MRR nas contas já existentes (sem re-rodar WhatsApp)")
    ap.add_argument("--slack", action="store_true", help="ao final da rodada, envia o relatório ao grupo do Slack")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    load_env()

    mrr = mrr_index()
    src = universe_cache() if args.from_cache else universe_live()
    sample = []
    for gid, name in src:
        sample.append({
            "account_id": (exid(name) or gid),  # id interno estável p/ dedup
            "name": name, "group_id": gid, "asof": TODAY,
            "plan_category": (_BUNDLE.search(name) or [None])[0] if _BUNDLE.search(name) else None,
            "is_legacy": False, "recurring_revenue": mrr.get(norm(name)),
        })
        if args.limit and len(sample) >= args.limit:
            break

    print(f"Universo resolvido: {len(sample)} contas ativas-cliente"
          f" ({'cache' if args.from_cache else 'AO VIVO'})")
    if args.dry_list:
        for s in sample[:60]:
            print(f"  {s['account_id']:<10} {s['name'][:60]}  mrr={s['recurring_revenue']}")
        if len(sample) > 60:
            print(f"  ... +{len(sample)-60}")
        return

    url = os.environ["APP_DATABASE_URL"]
    conn_factory = lambda: psycopg.connect(url)
    run_id = str(uuid.uuid4())
    audit = DbAuditSink(conn_factory, actor="agent:growth")

    # modo enriquecimento: só exec/MRR do mirror nas contas já pontuadas (sem WhatsApp)
    if args.exec_only:
        cli_por_conta, subs = mirror_enrich(sample, audit, run_id)
        audit.close()
        win_end = dt.datetime.combine(TODAY, dt.time.max, tzinfo=dt.timezone.utc)
        n = persist_exec(conn_factory, cli_por_conta, subs, win_end, run_id)
        print(f"exec/MRR gravados para {n} contas (contexto, não-pontuador)")
        return
    win_start = dt.datetime(2026, 4, 1, tzinfo=dt.timezone.utc)
    win_end = dt.datetime.combine(TODAY, dt.time.max, tzinfo=dt.timezone.utc)

    # contexto do mirror (execução + MRR)
    cli_por_conta, subs = ({}, {})
    if not args.no_exec:
        cli_por_conta, subs = mirror_enrich(sample, audit, run_id)

    # EXECUÇÃO NO SCORE (bloco 15%, flag EXECUTION_IN_SCORE, default ligado).
    # Evidência: não prediz churn sozinha (AUC 0,49/0,44 em churn-30/-60), mas a
    # 15% renormalizado NÃO degrada o ranking (AUC coorte 0,822→0,820) e traz
    # atrito de entrega para o score/motivos. Desligar: EXECUTION_IN_SCORE=0.
    # TOM via Claude (3b): anexa a série cacheada (run_tone_analysis) a cada conta.
    # Sem cache -> sinal fora do bloco tone (renormaliza) — comportamento validado.
    tone_map = load_tone_series(conn_factory)
    if tone_map:
        n_tone = 0
        for item in sample:
            series = tone_map.get(item["account_id"])
            if series:
                item["tone_series"] = series
                n_tone += 1
        print(f"  [tone] série de tom (Claude) anexada a {n_tone} contas", file=sys.stderr)

    exec_in_score = os.environ.get("EXECUTION_IN_SCORE", "1").lower() in ("1", "true", "sim")
    if exec_in_score and cli_por_conta:
        win_end_dt = dt.datetime.combine(TODAY, dt.time.max, tzinfo=dt.timezone.utc)
        n_sig = 0
        for item in sample:
            cli = cli_por_conta.get(item["account_id"])
            if not cli:
                continue
            er = execution_asof(cli, subs.get(cli.id, []), win_end_dt)
            if er.score is not None:
                item["execution_risk"] = round(1 - er.score / 100.0, 4)
                n_sig += 1
        print(f"  [exec] sinal de execução no score p/ {n_sig} contas (bloco 15%)", file=sys.stderr)

    # abre agent_run (auditoria da execução)
    rc = conn_factory()
    try:
        rid_db = P.start_run(rc, "growth", win_start, win_end)
        rc.commit()
    finally:
        rc.close()

    agent = GrowthAgent(conn_factory=conn_factory)
    ctx = AgentContext(window_start=win_start, window_end=win_end, run_id=run_id, audit=audit)
    ctx.sample = sample
    status = "ok"
    try:
        scores = agent.run(ctx)
    except Exception:
        status = "erro"
        raise
    finally:
        audit.close()
        rc = conn_factory()
        try:
            P.finish_run(rc, rid_db, status)
            rc.commit()
        finally:
            rc.close()

    # contexto de execução (não-pontuador) gravado após o score
    n_exec = persist_exec(conn_factory, cli_por_conta, subs, win_end, run_id) if cli_por_conta else 0

    ev = [s for s in scores if s.evaluable]
    nev = [s for s in scores if not s.evaluable]
    alerts = [s for s in ev if _alerts(s)]
    skipped = getattr(ctx, "skipped", [])
    print(f"\n=== RODADA {run_id[:8]} ({status}) ===")
    print(f"universo={len(sample)}  pontuadas={len(scores)}  puladas(falha leitura)={len(skipped)}  exec-contexto={n_exec}")
    print(f"avaliáveis={len(ev)}  não-avaliáveis={len(nev)}  com alerta={len(alerts)}")
    if skipped:
        print("puladas:", ", ".join(n[:24] for n, _ in skipped[:10]) + (" ..." if len(skipped) > 10 else ""))
    print("\npiores avaliáveis:")
    for s in sorted(ev, key=lambda x: x.score)[:12]:
        print(f"  {s.score:5.1f} | {s.risk_band:8}| {s.stage.value:22}| {s.account_name[:44]}")

    # --slack: envia o relatório do estado recém-persistido ao grupo dos gestores
    if args.slack:
        from app.api import _conn as _api_conn, _latest_scores, _open_alerts, _report_from, _report_text
        from app.slack import send_text
        try:
            with _api_conn() as c:
                text = _report_text(_report_from(_latest_scores(c), _open_alerts(c)))
            send_text(text)
            with _api_conn() as c, c.cursor() as cur:
                cur.execute("INSERT INTO audit_log (actor, action, scope) VALUES (%s,%s,%s)",
                            ("script:run_portfolio", "report_slack", "slack:webhook"))
            print("relatório enviado ao Slack ✓")
        except Exception as e:  # noqa: BLE001 — envio não pode derrubar a rodada
            print(f"[slack] falha no envio: {type(e).__name__}: {e}", file=sys.stderr)


def _alerts(s) -> bool:
    from app.agents.growth.scoring import should_alert
    return should_alert(s)


if __name__ == "__main__":
    main()
