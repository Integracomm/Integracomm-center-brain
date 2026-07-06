"""Coletor Meta Ads (Graph API v23) → cache mkt_campaigns / mkt_insights_daily.

Conta única validada: act_560054575531813 ("Integracomm CA"). Token
META_ADS_CA_TOKEN no .env (a chave tem espaço antes do '=' — o loader do
projeto faz k.strip(), ler SEMPRE via os.environ). Grão do insight: dia × ad
(permite agregar por campanha, público/adset ou criativo). Leads = action
type 'lead' (inclui onsite_conversion.lead_grouped quando presente).
"""
from __future__ import annotations

import datetime as dt
import os
import time
from typing import Any

import httpx

_BASE = "https://graph.facebook.com/v23.0"
_ACCOUNT = "act_560054575531813"


def _token() -> str:
    t = (os.environ.get("META_ADS_CA_TOKEN") or "").strip().strip('"')
    if not t:
        raise RuntimeError("META_ADS_CA_TOKEN ausente no .env")
    return t


def _get(path: str, params: dict) -> dict:
    params = dict(params, access_token=_token())
    for tent in range(5):
        r = httpx.get(f"{_BASE}/{path}", params=params, timeout=120)
        if r.status_code == 400 and "rate" in r.text.lower():
            time.sleep(30)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("Meta API: rate limit persistente")


def _paged(path: str, params: dict):
    j = _get(path, params)
    while True:
        yield from j.get("data", [])
        nxt = (j.get("paging") or {}).get("next")
        if not nxt:
            break
        r = httpx.get(nxt, timeout=120)
        r.raise_for_status()
        j = r.json()


def _leads(actions: list | None) -> int:
    tot = 0
    for a in actions or []:
        if a.get("action_type") in ("lead", "onsite_conversion.lead_grouped",
                                    "offsite_conversion.fb_pixel_lead"):
            tot = max(tot, int(float(a.get("value", 0))))  # tipos se sobrepõem: usa o maior
    return tot


def sync_campaigns(conn: Any) -> int:
    n = 0
    with conn.cursor() as cur:
        for c in _paged(f"{_ACCOUNT}/campaigns",
                        {"fields": "id,name,objective,status,start_time,created_time", "limit": 200}):
            inicio = (c.get("start_time") or c.get("created_time") or "")[:10] or None
            cur.execute(
                """INSERT INTO mkt_campaigns (id, canal, nome, objetivo, status, data_inicio, updated_at)
                   VALUES (%s,'meta',%s,%s,%s,%s,now())
                   ON CONFLICT (id) DO UPDATE SET nome=EXCLUDED.nome, objetivo=EXCLUDED.objetivo,
                        status=EXCLUDED.status, data_inicio=EXCLUDED.data_inicio, updated_at=now()""",
                (c["id"], c.get("name"), c.get("objective"), c.get("status"), inicio))
            n += 1
    return n


def sync_insights(conn: Any, since: dt.date, until: dt.date) -> int:
    """Insights diários nível AD. Janelas longas estouram o limite de dados da
    API (400) — fatiamos em blocos de ~30 dias."""
    if (until - since).days > 32:
        tot, ini = 0, since
        while ini <= until:
            fim = min(ini + dt.timedelta(days=30), until)
            tot += sync_insights(conn, ini, fim)
            ini = fim + dt.timedelta(days=1)
        return tot
    params = {
        "level": "ad", "time_increment": 1, "limit": 400,
        "fields": "campaign_id,adset_id,adset_name,ad_id,ad_name,spend,impressions,clicks,actions",
        "time_range": f'{{"since":"{since.isoformat()}","until":"{until.isoformat()}"}}',
    }
    n = 0
    with conn.cursor() as cur:
        for r in _paged(f"{_ACCOUNT}/insights", params):
            cur.execute(
                """INSERT INTO mkt_insights_daily
                       (canal, date, campaign_id, adset_id, adset_name, ad_id, ad_name,
                        spend, impressions, clicks, leads)
                   VALUES ('meta',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (canal, date, campaign_id, ad_id) DO UPDATE SET
                        spend=EXCLUDED.spend, impressions=EXCLUDED.impressions,
                        clicks=EXCLUDED.clicks, leads=EXCLUDED.leads,
                        adset_id=EXCLUDED.adset_id, adset_name=EXCLUDED.adset_name,
                        ad_name=EXCLUDED.ad_name""",
                (r["date_start"], r.get("campaign_id"), r.get("adset_id"), r.get("adset_name"),
                 r.get("ad_id") or "", r.get("ad_name"), float(r.get("spend") or 0),
                 int(r.get("impressions") or 0), int(r.get("clicks") or 0), _leads(r.get("actions"))))
            n += 1
    return n
