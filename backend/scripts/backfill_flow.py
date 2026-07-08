"""Backfill do histórico de etapas (/flow) — deals 2026, mais recentes primeiro.

    python -m scripts.backfill_flow

Roda uma vez (idempotente: mkt_flow_synced pula o que já foi); o incremental
diário do sync_marketing mantém depois. Ordem DESC = funil dos meses atuais
fica utilizável logo nos primeiros minutos.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import httpx
import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.sources.pipedrive_deals import _EVENTS_DDL, _flow_events  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

conn = psycopg.connect(os.environ["APP_DATABASE_URL"])
conn.autocommit = True
with conn.cursor() as cur:
    cur.execute(_EVENTS_DDL)
    cur.execute("""SELECT d.deal_id FROM mkt_deals_attribution d
                     LEFT JOIN mkt_flow_synced f ON f.deal_id = d.deal_id
                    WHERE f.deal_id IS NULL AND d.add_time >= '2026-01-01'
                    ORDER BY d.add_time DESC""")
    ids = [r[0] for r in cur.fetchall()]
print(f"pendentes: {len(ids)}", flush=True)
n = 0
with conn.cursor() as cur:
    for i, did in enumerate(ids, 1):
        try:
            evs = _flow_events(did)
        except httpx.HTTPError as e:
            print(f"  [skip] deal {did}: {type(e).__name__}", flush=True)
            continue
        for sid, quando in evs:
            if quando:
                cur.execute("""INSERT INTO mkt_stage_events (deal_id, stage_id, entered_at)
                               VALUES (%s,%s,%s) ON CONFLICT DO NOTHING""", (did, sid, quando))
                n += 1
        cur.execute("""INSERT INTO mkt_flow_synced (deal_id, synced_at) VALUES (%s, now())
                       ON CONFLICT (deal_id) DO UPDATE SET synced_at=now()""", (did,))
        time.sleep(0.12)
        if i % 250 == 0:
            print(f"  {i}/{len(ids)} deals ({n} eventos)...", flush=True)
print(f"FIM: {len(ids)} deals, {n} eventos", flush=True)
conn.close()
