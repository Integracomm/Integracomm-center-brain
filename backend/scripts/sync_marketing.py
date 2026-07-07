"""Sincroniza as fontes da área de Marketing → tabelas mkt_*.

    python -m scripts.sync_marketing --backfill   # 1ª carga (desde 2025-01-01)
    python -m scripts.sync_marketing              # incremental diário (D-7..hoje)
    python -m scripts.sync_marketing --weekly     # + metas (planilha muda pouco)

Entra no daily_run (06h): incremental todo dia; --weekly às segundas.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.marketing.schema import ensure_mkt_tables  # noqa: E402
from app.sources import google_ads_src, meta_ads, mkt_goals_sheet, mkt_plan_sheet, pipedrive_deals  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def load_env() -> None:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true", help="1ª carga desde 2025-01-01")
    ap.add_argument("--weekly", action="store_true", help="inclui releitura das metas")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    load_env()
    hoje = dt.date.today()
    since = dt.date(2025, 1, 1) if args.backfill else hoje - dt.timedelta(days=7)

    conn = psycopg.connect(os.environ["APP_DATABASE_URL"])
    conn.autocommit = True
    ensure_mkt_tables(conn)

    def step(nome, fn):
        try:
            print(f"[{nome}] ...", flush=True)
            print(f"[{nome}] ok: {fn()} registros", flush=True)
        except Exception as e:  # noqa: BLE001 — uma fonte fora não derruba as demais
            print(f"[{nome}] ERRO: {type(e).__name__}: {str(e)[:160]}", flush=True)

    step("meta campanhas", lambda: meta_ads.sync_campaigns(conn))
    step("meta insights", lambda: meta_ads.sync_insights(conn, since, hoje))
    step("google campanhas", lambda: google_ads_src.sync_campaigns(conn))
    step("google insights", lambda: google_ads_src.sync_insights(conn, since, hoje))
    step("pipedrive deals", lambda: pipedrive_deals.sync_deals(
        conn, since=dt.date(2025, 1, 1) if args.backfill else hoje - dt.timedelta(days=60)))
    if args.weekly or args.backfill:
        step("metas (planilha)", lambda: mkt_goals_sheet.sync_goals(conn))
        step("plano mkt (planilha de metas)", lambda: mkt_plan_sheet.sync_plan(conn))
        from app.marketing.analysis import recompute_lag_stats
        step("lag stats (recalc)", lambda: recompute_lag_stats(conn))
    conn.close()


if __name__ == "__main__":
    main()
