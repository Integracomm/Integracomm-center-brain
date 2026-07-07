"""Sincroniza as planilhas de cancelamento → grw_cancelamentos.

    python -m scripts.sync_cancelamentos

Tenta o export público dos dois arquivos (precisa de "qualquer pessoa com o
link – leitor"); sem acesso, usa a cópia local em data/ (canc_*.xlsx).
Entra na rodada diária depois do sync de marketing.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.sources import cancel_sheets  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
    conn = psycopg.connect(os.environ["APP_DATABASE_URL"])
    conn.autocommit = True
    try:
        print(f"[cancelamentos] ok: {cancel_sheets.sync(conn)} registros", flush=True)
    except Exception as e:  # noqa: BLE001 — loga e sai com erro p/ o runner
        print(f"[cancelamentos] ERRO: {type(e).__name__}: {str(e)[:160]}", flush=True)
        raise SystemExit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
