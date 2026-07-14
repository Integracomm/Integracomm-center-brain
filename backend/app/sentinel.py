"""Sentinela de cancelamento — avisos IMEDIATOS, sem esperar a rodada diária.

Motivação (caso real BENE TU, 2026-07-07): a solicitação de cancelamento foi
01/07, o agente marcou CRÍTICO e abriu alerta ALTO em 02/07 — mas o aviso ficou
parado no painel, e o time só olha o resumo diário. A sentinela cobre o vão:

Roda numa THREAD do próprio servidor (a cada 30 min, começa ~1 min após o boot):
  1. Vereditos CRÍTICO das analyses do WhatsApp (janela 48h) — cliente falando
     em sair/atrito grave detectado pelo verificador diário;
  2. Cards NOVOS no funil CS/Cancelados do ClickUp (janela 48h) — solicitação
     de cancelamento formalizada pela equipe.

Achado novo → post INDIVIDUAL no Slack (mesmo grupo dos relatórios) + alerta
CRÍTICO no painel (se não houver um aberto) + nota no caso da conta. Dedup na
tabela sentinel_seen (nunca avisa duas vezes o mesmo evento).
"""
from __future__ import annotations

import datetime as dt
import os
import re
import threading
import time
from typing import Any

_DDL = """
CREATE TABLE IF NOT EXISTS sentinel_seen (
    key     TEXT PRIMARY KEY,          -- 'wa:<group>:<data>' | 'cs:<card_id>'
    seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""
_JANELA_H = 48
_CS_LIST = "900700953811"  # funil CS/Cancelados (registro vivo do churn)
_ID_RE = re.compile(r"id\s*:\s*([a-z0-9_-]+)", re.I)


def _ensure(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute(_DDL)


def _visto(conn: Any, key: str, dry: bool = False) -> bool:
    """True se o evento já foi tratado. Em modo dry NÃO marca (não consome)."""
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM sentinel_seen WHERE key=%s", (key,))
        if cur.fetchone():
            return True
        if not dry:
            cur.execute("INSERT INTO sentinel_seen (key) VALUES (%s)", (key,))
        return False


def _contas(conn: Any) -> list[dict]:
    from .sources.nps_sheets import norm_account
    with conn.cursor() as cur:
        cur.execute("SELECT id, name, id_interno, whatsapp_group_id FROM accounts")
        return [{"id": str(i), "name": n, "idi": (x or "").lower(), "gid": g or "",
                 "norm": norm_account(n)} for i, n, x, g in cur.fetchall()]


def _abre_alerta(conn: Any, account_id: str, detalhe: str) -> None:
    """Alerta CRÍTICO no painel (se a conta não tiver um crítico aberto) + nota."""
    with conn.cursor() as cur:
        cur.execute("""SELECT 1 FROM alerts WHERE account_id=%s AND status='aberto'
                        AND severity='critico'""", (account_id,))
        if not cur.fetchone():
            cur.execute("""SELECT risk_band, stage FROM scores WHERE account_id=%s
                           ORDER BY computed_at DESC LIMIT 1""", (account_id,))
            row = cur.fetchone()
            band, stage = (row if row else ("critico", "intencao_de_saida"))
            cur.execute("""INSERT INTO alerts (account_id, risk_band, stage, severity, status)
                           VALUES (%s,%s,%s,'critico','aberto')""", (account_id, band, stage))
    try:
        from .reports import add_case_update
        add_case_update(conn, account_id, "sentinela", detalhe)
    except Exception:  # noqa: BLE001 — nota é acessória
        pass


def _avisar(texto: str, dry: bool) -> None:
    if dry:
        print("[dry] " + texto)
        return
    from .slack import send_text, webhook_configured
    if webhook_configured():
        send_text(texto)


def check_whatsapp(conn: Any, contas: list[dict], dry: bool = False) -> int:
    """Analyses CRÍTICO das últimas 48h → aviso imediato."""
    from .sources.whatsapp import WhatsAppReader
    url, key = os.environ.get("WHATSAPP_READ_API_URL"), os.environ.get("WHATSAPP_READ_API_KEY")
    if not (url and key):
        return 0
    corte = (dt.date.today() - dt.timedelta(hours=_JANELA_H) if False else
             dt.date.today() - dt.timedelta(days=_JANELA_H // 24))
    por_chave = {}
    for c in contas:
        if c["idi"]:
            por_chave[c["idi"]] = c
        if c["gid"]:
            por_chave[c["gid"]] = c
    n = 0
    rd = WhatsAppReader(url, key)
    try:
        for a in rd.iter_analyses():
            if (a.analysis_date or "9999")[:10] < corte.isoformat():
                break  # desc: passou da janela
            if "CR" not in (a.classification or "").upper():  # CRÍTICO
                continue
            resumo_low = (a.summary or "").lower()
            if resumo_low.startswith("sem novas mensagens") or "mantido do dia" in resumo_low[:120]:
                continue  # status apenas MANTIDO, sem evento novo — não re-alertar
            conta = por_chave.get((a.group_id or "").lower())
            if not conta:
                continue
            # dedup por conta em blocos de 7 dias: crítico contínuo avisa 1x/semana
            bloco = dt.date.fromisoformat(a.analysis_date[:10]).toordinal() // 7
            k = f"wa:{a.group_id}:{bloco}"
            if _visto(conn, k, dry):
                continue
            resumo = (a.summary or "").strip()[:220]
            _abre_alerta(conn, conta["id"],
                         f"[sentinela] Conversa CRÍTICA no WhatsApp em {a.analysis_date[:10]}: {resumo}")
            _avisar(f":rotating_light: *Sentinela — conversa CRÍTICA no WhatsApp*\n"
                    f"• Conta: *{conta['name'][:60]}*\n• Dia: {a.analysis_date[:10]}\n"
                    f"• Resumo: {resumo or '(sem resumo)'}\n"
                    f"_Alerta crítico aberto no painel — agir hoje._", dry)
            n += 1
    finally:
        rd.close()
    return n


def check_cs_funnel(conn: Any, contas: list[dict], dry: bool = False) -> int:
    """Cards criados no CS/Cancelados nas últimas 48h → solicitação de cancelamento."""
    import httpx
    tok = (os.environ.get("CLICKUP_API_TOKEN") or "").strip()
    if not tok:
        return 0
    from .sources.nps_sheets import norm_account
    corte_ms = (time.time() - _JANELA_H * 3600) * 1000
    por_norm = {c["norm"]: c for c in contas if c["norm"]}
    por_idi = {c["idi"]: c for c in contas if c["idi"]}
    n, page = 0, 0
    with httpx.Client(timeout=60.0) as cli:
        while page < 10:
            r = cli.get(f"https://api.clickup.com/api/v2/list/{_CS_LIST}/task",
                        params={"page": page, "subtasks": "false", "include_closed": "true",
                                "order_by": "created", "reverse": "true"},
                        headers={"Authorization": tok})
            if r.status_code != 200:
                break
            j = r.json()
            tasks = j.get("tasks", [])
            recentes = [t for t in tasks if float(t.get("date_created") or 0) >= corte_ms]
            for t in recentes:
                nome = t.get("name") or ""
                m = _ID_RE.search(nome)
                conta = (por_idi.get(m.group(1).lower()) if m else None) or por_norm.get(norm_account(nome))
                k = f"cs:{t['id']}"
                if _visto(conn, k, dry):
                    continue
                if conta:
                    _abre_alerta(conn, conta["id"],
                                 "[sentinela] Cliente entrou no funil CS/Cancelados (solicitação de cancelamento).")
                alvo = conta["name"][:60] if conta else nome[:60]
                _avisar(f":rotating_light: *Sentinela — SOLICITAÇÃO DE CANCELAMENTO*\n"
                        f"• Cliente: *{alvo}* entrou no funil CS/Cancelados agora.\n"
                        f"_{'Alerta crítico aberto no painel — ' if conta else ''}retenção é hoje, não amanhã._", dry)
                n += 1
            if len(recentes) < len(tasks) or j.get("last_page") or not tasks:
                break  # já passou da janela de 48h
            page += 1
    return n


def run_once(conn_factory, dry: bool = False) -> int:
    conn = conn_factory()
    try:
        conn.autocommit = True
        _ensure(conn)
        # série temporal do risco (1 linha/dia, upsert) — carona na sentinela
        from .api import grava_snapshot_risco
        grava_snapshot_risco(conn)
        contas = _contas(conn)
        total = 0
        for fn in (check_cs_funnel, check_whatsapp):
            try:
                total += fn(conn, contas, dry)
            except Exception as e:  # noqa: BLE001 — uma fonte fora não para a outra
                print(f"[sentinela] {fn.__name__} falhou: {type(e).__name__}")
        if total:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO audit_log (actor, action, scope) VALUES "
                            "('sentinela','alert', %s)", (f"avisos:{total}",))
        return total
    finally:
        conn.close()


def start_sentinel(conn_factory) -> None:
    """Thread daemon: 1ª varredura ~1 min após o boot, depois a cada 30 min."""
    def loop():
        time.sleep(60)
        while True:
            try:
                run_once(conn_factory)
            except Exception:  # noqa: BLE001 — nunca derrubar o servidor
                pass
            time.sleep(1800)
    threading.Thread(target=loop, name="sentinela-cancelamento", daemon=True).start()
