"""Coletor Google Ads (REST searchStream) → mkt_campaigns / mkt_insights_daily.

Credenciais no .env (chaves com espaço antes do '=' — ler via os.environ):
GOOGLE_DEVELOPER_TOKEN, GOOGLE_CLIENT_ID/SECRET, GOOGLE_REFRESH_TOKEN,
GOOGLE_ADS_CUSTOMER_ID (9513419241 — validado). Grão v1: dia × campanha
(ad_id='' no PK); nível de anúncio pode vir depois se o Rafael precisar.
`metrics.conversions` ≈ leads (conversões configuradas na conta).
"""
from __future__ import annotations

import datetime as dt
import os
from typing import Any

import httpx

_VER = "v21"


def _env(k: str) -> str:
    return (os.environ.get(k) or "").strip().strip('"')


def _access_token() -> str:
    r = httpx.post("https://oauth2.googleapis.com/token", data={
        "client_id": _env("GOOGLE_CLIENT_ID"), "client_secret": _env("GOOGLE_CLIENT_SECRET"),
        "refresh_token": _env("GOOGLE_REFRESH_TOKEN"), "grant_type": "refresh_token"}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def _search(gaql: str) -> list[dict]:
    cid = _env("GOOGLE_ADS_CUSTOMER_ID").replace("-", "")
    r = httpx.post(
        f"https://googleads.googleapis.com/{_VER}/customers/{cid}/googleAds:searchStream",
        headers={"Authorization": f"Bearer {_access_token()}",
                 "developer-token": _env("GOOGLE_DEVELOPER_TOKEN")},
        json={"query": gaql}, timeout=120)
    r.raise_for_status()
    out: list[dict] = []
    for batch in r.json():
        out.extend(batch.get("results", []))
    return out


def sync_campaigns(conn: Any) -> int:
    rows = _search("SELECT campaign.id, campaign.name, campaign.status, "
                   "campaign.start_date, campaign.advertising_channel_type FROM campaign")
    n = 0
    with conn.cursor() as cur:
        for r in rows:
            c = r["campaign"]
            cur.execute(
                """INSERT INTO mkt_campaigns (id, canal, nome, objetivo, status, data_inicio, updated_at)
                   VALUES (%s,'google',%s,%s,%s,%s,now())
                   ON CONFLICT (id) DO UPDATE SET nome=EXCLUDED.nome, objetivo=EXCLUDED.objetivo,
                        status=EXCLUDED.status, data_inicio=EXCLUDED.data_inicio, updated_at=now()""",
                (str(c["id"]), c.get("name"), c.get("advertisingChannelType"),
                 c.get("status"), c.get("startDate")))
            n += 1
    return n


def sync_insights(conn: Any, since: dt.date, until: dt.date) -> int:
    rows = _search(
        "SELECT campaign.id, segments.date, metrics.cost_micros, metrics.impressions, "
        "metrics.clicks, metrics.conversions FROM campaign "
        f"WHERE segments.date BETWEEN '{since.isoformat()}' AND '{until.isoformat()}'")
    n = 0
    with conn.cursor() as cur:
        for r in rows:
            m = r.get("metrics", {})
            cur.execute(
                """INSERT INTO mkt_insights_daily
                       (canal, date, campaign_id, ad_id, spend, impressions, clicks, leads)
                   VALUES ('google',%s,%s,'',%s,%s,%s,%s)
                   ON CONFLICT (canal, date, campaign_id, ad_id) DO UPDATE SET
                        spend=EXCLUDED.spend, impressions=EXCLUDED.impressions,
                        clicks=EXCLUDED.clicks, leads=EXCLUDED.leads""",
                (r["segments"]["date"], str(r["campaign"]["id"]),
                 int(m.get("costMicros") or 0) / 1e6, int(m.get("impressions") or 0),
                 int(m.get("clicks") or 0), int(float(m.get("conversions") or 0))))
            n += 1
    return n
