"""Coletor Pipedrive → mkt_deals_attribution (deal com UTM/plano resolvidos).

Campos custom confirmados via /dealFields (2026-07-06): utm_source/medium/
term(público)/content(criativo)/campaign são varchar; `Produto` é enum (o
valor vem como id numérico — resolvemos p/ label via options do /dealFields,
ex. "B1 - NOVO START"). Atribuição: 100% dos deals pagos têm utm_campaign.

Limitação v1 (documentada): `oport_time` fica NULL — o histórico de mudança de
etapa exige 1 chamada /deals/{id}/flow por deal (caro no backfill). O lag usa
lead (add_time) e booking (won_time); o marco "oportunidade" entra depois, via
enriquecimento incremental diário (só deals novos/alterados).
"""
from __future__ import annotations

import datetime as dt
import os
from typing import Any

import httpx

F_SOURCE = "9ed28bb3e67c4336d4375949c87bbe6f306ef749"
F_MEDIUM = "14c742e76612142d336fe3f7c524b19f3f9064f8"
F_TERM = "6988285b5eb437ac88ad90a75c932c9f8f6efa3d"
F_CONTENT = "a4e181536d5f826605a31601bf992f4b50457b98"
F_CAMPAIGN = "9a853495a426a500ce75a58fa52d59a080c7e1ef"
F_PRODUTO = "9ad49f0040b563e8dfef6f58172830f0a115de12"


def _token() -> str:
    t = (os.environ.get("PIPEDRIVE_API_TOKEN") or "").strip().strip('"')
    if not t:
        raise RuntimeError("PIPEDRIVE_API_TOKEN ausente no .env")
    return t


def _get(path: str, params: dict) -> dict:
    r = httpx.get(f"https://api.pipedrive.com/v1/{path}",
                  params=dict(params, api_token=_token()), timeout=90)
    r.raise_for_status()
    return r.json()


def produto_labels() -> dict[str, str]:
    """id da option -> label do enum Produto (ex.: '118' -> 'B1 - NOVO START')."""
    for f in _get("dealFields", {"limit": 500}).get("data") or []:
        if f.get("key") == F_PRODUTO:
            return {str(o["id"]): o["label"] for o in (f.get("options") or [])}
    return {}


def _txt(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, dict):  # enums podem vir como {"id":..,"label":..}
        return v.get("label")
    s = str(v).strip()
    return s or None


def sync_deals(conn: Any, since: dt.date = dt.date(2025, 1, 1)) -> int:
    """Upsert de todos os deals com add_time >= since (paginado, mais recentes
    primeiro; para quando a página inteira é anterior ao corte)."""
    labels = produto_labels()
    n, start = 0, 0
    with conn.cursor() as cur:
        while start is not None:
            j = _get("deals", {"limit": 500, "start": start, "sort": "add_time DESC"})
            data = j.get("data") or []
            page_old = True
            for d in data:
                add = d.get("add_time")
                if not add or add[:10] < since.isoformat():
                    continue
                page_old = False
                prod = _txt(d.get(F_PRODUTO))
                if prod and prod.isdigit():
                    prod = labels.get(prod, prod)
                cur.execute(
                    """INSERT INTO mkt_deals_attribution
                           (deal_id, add_time, won_time, lost_time, status, valor, origem,
                            utm_medium, utm_campaign, utm_term, utm_content, produto,
                            stage_id, updated_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
                       ON CONFLICT (deal_id) DO UPDATE SET
                            won_time=EXCLUDED.won_time, lost_time=EXCLUDED.lost_time,
                            status=EXCLUDED.status, valor=EXCLUDED.valor, origem=EXCLUDED.origem,
                            utm_medium=EXCLUDED.utm_medium, utm_campaign=EXCLUDED.utm_campaign,
                            utm_term=EXCLUDED.utm_term, utm_content=EXCLUDED.utm_content,
                            produto=EXCLUDED.produto, stage_id=EXCLUDED.stage_id, updated_at=now()""",
                    (d["id"], add, d.get("won_time"), d.get("lost_time"), d.get("status"),
                     d.get("value"), (_txt(d.get(F_SOURCE)) or "").lower() or None,
                     _txt(d.get(F_MEDIUM)), _txt(d.get(F_CAMPAIGN)), _txt(d.get(F_TERM)),
                     _txt(d.get(F_CONTENT)), prod, d.get("stage_id")))
                n += 1
            p = (j.get("additional_data") or {}).get("pagination") or {}
            if page_old and data:
                break  # página inteira antes do corte: fim do backfill
            start = p.get("next_start") if p.get("more_items_in_collection") else None
        # higiene: deals APAGADOS no Pipedrive (janela de 30d da API) saem do cache
        j = _get("deals", {"limit": 500, "status": "deleted"})
        apagados = [d["id"] for d in (j.get("data") or [])]
        if apagados:
            cur.execute("DELETE FROM mkt_deals_attribution WHERE deal_id = ANY(%s)", (apagados,))
    return n


# ---------------------------------------------------------------------------
# Histórico de mudanças de etapa (/deals/{id}/flow) → mkt_stage_events.
# É o que permite contar o funil POR EVENTO no período (mesma régua do
# Pipedrive/app Lovable do time: "entrou na etapa X em julho"), em vez de
# coorte. 1 chamada por deal: backfill pesado (~2k deals), incremental leve.
# ---------------------------------------------------------------------------
_EVENTS_DDL = """
CREATE TABLE IF NOT EXISTS mkt_stage_events (
    deal_id    BIGINT NOT NULL,
    stage_id   INTEGER NOT NULL,
    entered_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (deal_id, stage_id, entered_at)
);
CREATE INDEX IF NOT EXISTS idx_mkt_stage_ev_t ON mkt_stage_events(entered_at);
-- deals já enriquecidos (re-buscamos só os que mudaram depois)
CREATE TABLE IF NOT EXISTS mkt_flow_synced (
    deal_id   BIGINT PRIMARY KEY,
    synced_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def _flow_events(deal_id: int) -> list[tuple[int, str]]:
    """(stage_id, log_time) de cada mudança de etapa do deal, via /flow."""
    import time
    out: list[tuple[int, str]] = []
    start = 0
    while True:
        for tent in range(4):
            try:
                j = _get(f"deals/{deal_id}/flow", {"limit": 500, "start": start})
                break
            except httpx.HTTPStatusError as e:  # 429: espera e tenta de novo
                if e.response.status_code == 429 and tent < 3:
                    time.sleep(2.0 * (tent + 1))
                    continue
                raise
        for item in j.get("data") or []:
            if item.get("object") != "dealChange":
                continue
            d = item.get("data") or {}
            if d.get("field_key") == "stage_id" and d.get("new_value") is not None:
                try:
                    out.append((int(d["new_value"]), d.get("log_time")))
                except (TypeError, ValueError):
                    pass
        p = (j.get("additional_data") or {}).get("pagination") or {}
        if not p.get("more_items_in_collection"):
            return out
        start = p.get("next_start")


def sync_stage_events(conn: Any, *, full: bool = False, window_days: int = 60) -> int:
    """Enriquece com o histórico de etapas os deals NOVOS/ALTERADOS desde o
    último enriquecimento (updated_at > synced_at); `full` refaz todos."""
    import time
    with conn.cursor() as cur:
        cur.execute(_EVENTS_DDL)
        if full:
            cur.execute("SELECT deal_id FROM mkt_deals_attribution ORDER BY add_time")
        else:
            cur.execute("""SELECT d.deal_id FROM mkt_deals_attribution d
                             LEFT JOIN mkt_flow_synced f ON f.deal_id = d.deal_id
                            WHERE (f.deal_id IS NULL AND d.add_time >= now() - %s * interval '1 day')
                               OR d.updated_at > f.synced_at ORDER BY d.add_time""",
                        (window_days,))
        ids = [r[0] for r in cur.fetchall()]
    n = 0
    with conn.cursor() as cur:
        for i, did in enumerate(ids):
            try:
                evs = _flow_events(did)
            except httpx.HTTPError:
                continue  # deal problemático não trava o lote; re-tenta amanhã
            for sid, quando in evs:
                if not quando:
                    continue
                cur.execute("""INSERT INTO mkt_stage_events (deal_id, stage_id, entered_at)
                               VALUES (%s,%s,%s) ON CONFLICT DO NOTHING""", (did, sid, quando))
                n += 1
            cur.execute("""INSERT INTO mkt_flow_synced (deal_id, synced_at) VALUES (%s, now())
                           ON CONFLICT (deal_id) DO UPDATE SET synced_at=now()""", (did,))
            time.sleep(0.12)  # folga p/ o rate limit (~80 req/2s no plano)
            if i and i % 200 == 0:
                print(f"  [flow] {i}/{len(ids)} deals...", flush=True)
    return n
