"""Roda a análise de TOM via Claude (Sonnet) e persiste no Postgres.

    # teste de validação (3 contas: saudável, em alerta, cancelada):
    backend/.venv/Scripts/python -m scripts.run_tone_analysis --test
    # base inteira (todas as contas avaliáveis do banco):
    backend/.venv/Scripts/python -m scripts.run_tone_analysis
    # amostra:
    backend/.venv/Scripts/python -m scripts.run_tone_analysis --limit 10

Persiste a série semanal como signal_snapshots (signal_key='tom_claude',
value_num=risco 0-1; o último ponto carrega o JSON completo em value_text) e
AUDITA cada análise (conta, janela, resultado resumido, tokens) no audit_log.
Requer ANTHROPIC_API_KEY no .env da raiz.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

import anthropic
import psycopg

from app.agents.growth.tone_claude import MODEL, analyze_tone, build_transcript
from app.llm_budget import (LlmBudgetExceeded, budget_cap, ensure_budget,
                            month_spend, record_usage)
from app.sources.whatsapp import WhatsAppReader

ROOT = Path(__file__).resolve().parents[2]
TODAY = dt.date.today()

# --test: 1 saudável conhecida, 1 em alerta (WMA), 1 cancelada (SAMA, asof=churn)
_TEST_CASES = [
    ("saudavel (validada)", "17195", None, TODAY),        # NAVALHA AUTO PARTS
    ("em alerta (WMA)", None, "wma autopecas", TODAY),    # WMA — insatisfação ativa
    ("cancelada (SAMA)", "18197", None, dt.date(2026, 6, 10)),  # SAMA — asof = churn
]


def load_env():
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def norm(s):
    if not s:
        return ""
    x = unicodedata.normalize("NFD", s.lower())
    x = "".join(c for c in x if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", x)).strip()


def exid(s):
    m = re.search(r"id\s*:\s*([a-z0-9_-]+)", s or "", re.I)
    return m.group(1).lower() if m else None


def persist(conn, account_uuid: str, analysis, run_tag: str) -> None:
    """Upsert da série semanal + JSON no último ponto (re-análise atualiza)."""
    pts = analysis.series()
    with conn.cursor() as cur:
        for i, (wk, risk) in enumerate(pts):
            value_text = None
            if i == len(pts) - 1:  # último ponto carrega o resumo completo
                value_text = json.dumps({
                    "iniciativa": analysis.iniciativa, "temas": analysis.temas,
                    "janela": f"{analysis.window_start}..{analysis.window_end}",
                    "modelo": "claude-sonnet-5",
                }, ensure_ascii=False)[:800]
            cur.execute(
                """INSERT INTO signal_snapshots
                       (account_id, captured_at, source, signal_key, value_num, value_text, is_leading, run_id)
                   VALUES (%s,%s,'claude','tom_claude',%s,%s,TRUE,NULL)
                   ON CONFLICT (account_id, signal_key, captured_at)
                   DO UPDATE SET value_num=EXCLUDED.value_num, value_text=EXCLUDED.value_text""",
                (account_uuid, dt.datetime.combine(wk, dt.time.min, tzinfo=dt.timezone.utc), risk, value_text),
            )
        # auditoria: conta, janela, resultado, tokens
        scope = (f"janela={analysis.window_start}..{analysis.window_end}; semanas={len(pts)}; "
                 f"iniciativa={analysis.iniciativa}; temas={len(analysis.temas)}; msgs={analysis.n_msgs}; "
                 f"tokens_in={analysis.tokens_in}; tokens_out={analysis.tokens_out}")
        cur.execute(
            "INSERT INTO audit_log (actor, action, source, scope, account_id) VALUES (%s,%s,%s,%s,%s)",
            (f"script:tone_{run_tag}", "tone_analysis", "anthropic:claude-sonnet-5", scope, account_uuid),
        )
    conn.commit()


def _print_result(label: str, name: str, analysis) -> None:
    toms = " ".join(f"{wk.strftime('%d/%m')}:{tom[:4]}" for wk, tom in sorted(analysis.weeks))
    print(f"\n=== {label} — {name[:52]}")
    print(f"  janela {analysis.window_start}..{analysis.window_end} | {analysis.n_msgs} msgs | "
          f"tokens {analysis.tokens_in}/{analysis.tokens_out}")
    print(f"  tom por semana: {toms}")
    print(f"  iniciativa: {analysis.iniciativa}")
    print(f"  temas de insatisfação: {analysis.temas or '—'}")
    risks = [r for _, r in analysis.series()]
    print(f"  risco médio do tom: {sum(risks)/len(risks):.2f}" if risks else "  (sem semanas)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true", help="3 contas de validação (não persiste com --dry)")
    ap.add_argument("--limit", type=int, default=0, help="máx. de contas (0 = todas avaliáveis)")
    ap.add_argument("--dry", action="store_true", help="não persiste nem audita (só imprime)")
    ap.add_argument("--page-limit", type=int, default=100,
                    help="mensagens por página do conector (reduza p/ grupos que dão HTTP 546)")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    load_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY não encontrada no .env da raiz — adicione e rode de novo.")

    claude = anthropic.Anthropic()
    # page_limit menor: grupos com mensagens longas estouram o payload do gateway
    # (HTTP 546) com 200/página — 100 é seguro e o custo é só mais paginação.
    reader = WhatsAppReader(os.environ["WHATSAPP_READ_API_URL"], os.environ["WHATSAPP_READ_API_KEY"],
                            page_limit=args.page_limit)
    conn = psycopg.connect(os.environ["APP_DATABASE_URL"]) if not args.dry else None
    # orçamento: mesmo em --dry o gasto na API é real — registra sempre
    budget_conn = conn or psycopg.connect(os.environ["APP_DATABASE_URL"])

    # índice de grupos ao vivo (INCLUI finalizados — necessário p/ canceladas do --test)
    groups = list(reader.iter_groups())
    by_id = {}
    for g in groups:
        gid_tok = exid(g.name)
        if gid_tok:
            by_id.setdefault(gid_tok, g)

    def account_uuid_for(g) -> str | None:
        nonlocal conn
        if conn is None:
            return None
        key = exid(g.name) or g.id
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM accounts WHERE id_interno=%s", (key,))
                row = cur.fetchone()
        except psycopg.OperationalError:
            conn = psycopg.connect(os.environ["APP_DATABASE_URL"])
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM accounts WHERE id_interno=%s", (key,))
                row = cur.fetchone()
        return str(row[0]) if row else None

    targets: list[tuple[str, object, dt.date]] = []  # (label, group, asof)
    if args.test:
        for label, idtok, nameterm, asof in _TEST_CASES:
            g = by_id.get(idtok) if idtok else next(
                (x for x in groups if nameterm in norm(x.name)), None)
            if g:
                targets.append((label, g, asof))
            else:
                print(f"  [skip] não achei grupo p/ {label}", file=sys.stderr)
    else:
        # todas as contas AVALIÁVEIS do banco, casadas ao grupo ao vivo;
        # pula quem já foi analisada nas últimas 20h (retomada sem custo duplo)
        with psycopg.connect(os.environ["APP_DATABASE_URL"]) as c, c.cursor() as cur:
            cur.execute("""SELECT DISTINCT ON (s.account_id) a.id_interno, a.name, a.id::text
                             FROM scores s JOIN accounts a ON a.id=s.account_id
                            ORDER BY s.account_id, s.computed_at DESC""")
            rows = [r for r in cur.fetchall()]
            cur.execute("""SELECT DISTINCT account_id::text FROM audit_log
                            WHERE action='tone_analysis' AND account_id IS NOT NULL
                              AND at > now() - interval '20 hours'""")
            feitas = {r[0] for r in cur.fetchall()}
        live = { (exid(g.name) or g.id): g for g in groups }
        puladas = 0
        for id_interno, name, auid in rows:
            g = live.get(id_interno)
            if not g:
                continue
            if auid in feitas:
                puladas += 1
                continue
            targets.append(("conta", g, TODAY))
        if puladas:
            print(f"({puladas} contas já analisadas nas últimas 20h — puladas, sem custo)")
        if args.limit:
            targets = targets[: args.limit]

    def _fresh():
        return psycopg.connect(os.environ["APP_DATABASE_URL"])

    print(f"analisando tom de {len(targets)} conta(s) com {anthropic.__name__} / {MODEL} "
          f"(orçamento mensal: US$ {budget_cap():.2f}) …")
    tot_in = tot_out = ok = 0
    custo_lote = 0.0
    for label, g, asof in targets:
        try:  # RDS derruba conexões longas — reconecta e segue
            try:
                ensure_budget(budget_conn)  # para o lote LIMPO se o teto do mês chegar
            except psycopg.OperationalError:
                budget_conn = _fresh()
                ensure_budget(budget_conn)
        except LlmBudgetExceeded as e:
            print(f"\n[orçamento] {e}\nlote interrompido — o que já foi analisado está persistido.",
                  file=sys.stderr)
            break
        try:
            try:
                built = build_transcript(reader, g.id, asof)
            except Exception as e:  # noqa: BLE001
                if "546" not in str(e):
                    raise
                # payload grande demais p/ o gateway: repete com páginas menores
                slow = WhatsAppReader(os.environ["WHATSAPP_READ_API_URL"],
                                      os.environ["WHATSAPP_READ_API_KEY"], page_limit=30)
                try:
                    built = build_transcript(slow, g.id, asof)
                finally:
                    slow.close()
            if not built:
                print(f"  [skip] {g.name[:40]}: sem mensagens na janela", file=sys.stderr)
                continue
            transcript, weeks, wstart, n_msgs = built
            analysis = analyze_tone(claude, transcript, weeks, wstart, asof, n_msgs)
            try:
                custo_lote += record_usage(budget_conn, "growth:tom_claude", MODEL,
                                           analysis.tokens_in, analysis.tokens_out)
            except psycopg.OperationalError:
                budget_conn = _fresh()
                custo_lote += record_usage(budget_conn, "growth:tom_claude", MODEL,
                                           analysis.tokens_in, analysis.tokens_out)
            _print_result(label, g.name, analysis)
            tot_in += analysis.tokens_in
            tot_out += analysis.tokens_out
            ok += 1
            if conn is not None:
                uid = account_uuid_for(g)
                if uid:
                    try:
                        persist(conn, uid, analysis, "test" if args.test else "batch")
                    except psycopg.OperationalError:
                        conn = _fresh()
                        persist(conn, uid, analysis, "test" if args.test else "batch")
                else:
                    print(f"  (conta não está no banco — resultado não persistido)")
        except Exception as e:  # noqa: BLE001 — uma conta não derruba o lote
            print(f"  [erro] {g.name[:40]}: {type(e).__name__}: {e}", file=sys.stderr)
    print(f"\nconcluído: {ok}/{len(targets)} contas | tokens totais in={tot_in} out={tot_out} | "
          f"custo do lote: US$ {custo_lote:.4f} | gasto do mês: US$ {month_spend(budget_conn):.2f} "
          f"de US$ {budget_cap():.2f}")
    reader.close()
    if budget_conn is not conn:
        budget_conn.close()
    if conn is not None:
        conn.close()


if __name__ == "__main__":
    main()
