# -*- coding: utf-8 -*-
"""Sync RÁPIDO horário (horário comercial): deals do cache do Lovable (0 req
Pipedrive) + /flow só dos deals que mudaram (teto 30/run). Mantém o funil do
painel a ≤1h do Pipedrive sem ameaçar o orçamento compartilhado da API.

    cron (servidor): 15 8-21 * * *  → pior caso 14×30 = 420 req/dia; típico <100
"""
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
except Exception:  # noqa: BLE001
    pass


def main() -> None:
    conn = psycopg.connect(os.environ["APP_DATABASE_URL"])
    conn.autocommit = True
    try:
        try:
            n = P.sync_deals_smart(conn)
            print(f"[rapido] deals: {n} tocados", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[rapido] deals ERRO: {type(e).__name__}: {str(e)[:100]}", flush=True)
        try:
            n = P.sync_stage_events(conn, max_deals=30)
            print(f"[rapido] flow: {n} eventos | req: {P._REQS['n']}", flush=True)
        except P.DailyBudgetExceeded as e:
            print(f"[rapido] orçamento diário: {e}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[rapido] flow ERRO: {type(e).__name__}: {str(e)[:100]}", flush=True)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
