# -*- coding: utf-8 -*-
"""One-off 13/07: drena a fila do /flow (mais recentes primeiro) p/ o funil
corrente bater com o Pipedrive. Resiliente a RDS e ao orçamento diário."""
from __future__ import annotations

import os
import sys
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


restam = 3000
while restam > 0:
    try:
        c = _conn()
        try:
            n = P.sync_stage_events(c, max_deals=min(600, restam))
        finally:
            c.close()
        print(f"[lote] {n} eventos gravados | req acumuladas: {P._REQS['n']}", flush=True)
        restam -= 600
        if n == 0:
            print("fila drenada.", flush=True)
            break
    except psycopg.OperationalError as e:
        print(f"[conexão caiu: {str(e)[:80]} — reconectando]", flush=True)
    except P.DailyBudgetExceeded as e:
        print(f"[orçamento diário esgotou: {e} — retoma amanhã 06h]", flush=True)
        break
with _conn() as c, c.cursor() as cur:
    cur.execute("""SELECT count(DISTINCT deal_id) FROM mkt_stage_events
                    WHERE stage_id IN (6,15) AND entered_at >= '2026-07-01 00:00-03'""")
    print(f"RESULTADO: deals em Reunião (6/15) em julho = {cur.fetchone()[0]} (Pipedrive: 118)", flush=True)
print("concluído.", flush=True)
