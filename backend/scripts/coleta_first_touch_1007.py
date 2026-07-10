# -*- coding: utf-8 -*-
"""One-off 10/07: backfill do 1º contato (atividades 2026) + /flow incremental.

    backend/.venv/Scripts/python -m scripts.coleta_first_touch_1007

Liga Speed-to-Lead e a atribuição por SDR em Pré-vendas (sales_first_touch
estava vazia — backfills anteriores foram interrompidos). Resiliente a queda
de conexão do RDS (reconecta por etapa) e ao orçamento diário do Pipedrive
(DailyBudgetExceeded para limpo; re-rodar amanhã retoma).
"""
from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.sources import pipedrive_deals as P  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def load_env() -> None:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def _conn():
    c = psycopg.connect(os.environ["APP_DATABASE_URL"])
    c.autocommit = True
    return c


def step(nome, fn):
    for tent in (1, 2):
        try:
            print(f"[{nome}] ...", flush=True)
            c = _conn()
            try:
                print(f"[{nome}] ok: {fn(c)} registros | req Pipedrive acumuladas: {P._REQS['n']}",
                      flush=True)
            finally:
                c.close()
            return
        except psycopg.OperationalError as e:
            print(f"[{nome}] conexão caiu ({str(e)[:80]}) — tentativa {tent}", flush=True)
        except P.DailyBudgetExceeded as e:
            print(f"[{nome}] orçamento diário do Pipedrive esgotou: {e} — retomar amanhã", flush=True)
            return
        except Exception as e:  # noqa: BLE001
            print(f"[{nome}] ERRO: {type(e).__name__}: {str(e)[:160]}", flush=True)
            return


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    load_env()
    step("1º contato 2026 (backfill)",
         lambda c: P.sync_first_touch(c, since=dt.date(2026, 1, 1), max_pages=400))
    step("etapas /flow (incremental)", lambda c: P.sync_stage_events(c, max_deals=800))
    print("concluído.", flush=True)


if __name__ == "__main__":
    main()
