# -*- coding: utf-8 -*-
"""One-off 13/07: /flow SÓ dos deals relevantes p/ o funil de JULHO
(criados em julho, ganhos em julho ou abertos em Reunião/Reagendamento/
Negociação) que ainda estão na fila — mínimo de requisições possível.
A API do Pipedrive é compartilhada com apps em tempo real (ordem do Otávio)."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.sources import pipedrive_deals as P  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _conn():
    c = psycopg.connect(os.environ["APP_DATABASE_URL"])
    c.autocommit = True
    return c


with _conn() as c, c.cursor() as cur:
    cur.execute("""
        SELECT d.deal_id FROM mkt_deals_attribution d
          LEFT JOIN mkt_flow_synced f ON f.deal_id = d.deal_id
         WHERE ((f.deal_id IS NULL AND d.add_time >= now() - interval '60 days')
                OR d.updated_at > f.synced_at)
           AND (d.add_time >= '2026-07-01' OR d.won_time >= '2026-07-01'
                OR (d.status = 'open' AND d.stage_id IN (5, 6, 7)))
         ORDER BY GREATEST(d.updated_at, d.add_time) DESC""")
    ids = [r[0] for r in cur.fetchall()]
print(f"deals relevantes p/ julho na fila: {len(ids)} (teto: 500)", flush=True)
ids = ids[:500]

c = _conn()
cur = c.cursor()
n = 0
for i, did in enumerate(ids):
    try:
        evs = P._flow_events(did)
    except P.DailyBudgetExceeded:
        print(f"[orçamento diário: parando limpo em {i}/{len(ids)}]", flush=True)
        break
    except Exception as e:  # noqa: BLE001
        print(f"[deal {did}: {type(e).__name__} — segue]", flush=True)
        continue
    try:
        for sid, quando in evs:
            if quando:
                cur.execute("INSERT INTO mkt_stage_events (deal_id, stage_id, entered_at) "
                            "VALUES (%s,%s,%s) ON CONFLICT DO NOTHING", (did, sid, quando))
                n += 1
        cur.execute("INSERT INTO mkt_flow_synced (deal_id, synced_at) VALUES (%s, now()) "
                    "ON CONFLICT (deal_id) DO UPDATE SET synced_at=now()", (did,))
    except psycopg.OperationalError:
        c = _conn()
        cur = c.cursor()
    time.sleep(0.15)
    if i and i % 100 == 0:
        print(f"  {i}/{len(ids)}...", flush=True)
print(f"eventos gravados: {n} | requisições usadas: {P._REQS['n']}", flush=True)
with _conn() as c2, c2.cursor() as cur2:
    cur2.execute("""SELECT count(DISTINCT deal_id) FROM mkt_stage_events
                     WHERE stage_id IN (6,15) AND entered_at >= '2026-07-01 00:00-03'""")
    print(f"RESULTADO: reuniões (6/15) de julho no banco = {cur2.fetchone()[0]} (Pipedrive: 118)", flush=True)
print("concluído.", flush=True)
