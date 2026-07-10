"""One-off 09/07: popula owner/lost_reason (histórico), 1º contato 2026 e flow residual."""
import datetime as dt
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
ROOT = Path(__file__).resolve().parents[2]
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())
import psycopg
from app.sources import pipedrive_deals as PD

conn = psycopg.connect(os.environ["APP_DATABASE_URL"])
conn.autocommit = True
for nome, fn in [
    ("deals c/ owner (2025+)", lambda: PD.sync_deals(conn, since=dt.date(2025, 1, 1))),
    ("1º contato 2026", lambda: PD.sync_first_touch(conn, since=dt.date(2026, 1, 1), max_pages=300)),
    ("flow incremental", lambda: PD.sync_stage_events(conn, max_deals=1200)),
]:
    try:
        print(f"[{nome}] ok: {fn()}", flush=True)
    except PD.DailyBudgetExceeded:
        print(f"[{nome}] orçamento diário esgotou — retoma amanhã", flush=True)
        break
    except Exception as e:
        print(f"[{nome}] ERRO: {type(e).__name__}: {str(e)[:140]}", flush=True)
print(f"FIM ({PD._REQS['n']} requisições usadas)", flush=True)
conn.close()
