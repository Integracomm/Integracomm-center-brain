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
