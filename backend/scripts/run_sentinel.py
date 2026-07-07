"""Roda a sentinela de cancelamento UMA vez (teste/manual).

    python -m scripts.run_sentinel --dry   # mostra o que enviaria, sem Slack
    python -m scripts.run_sentinel         # envia de verdade
"""
import argparse
import os
import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.sentinel import run_once  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
    n = run_once(lambda: psycopg.connect(os.environ["APP_DATABASE_URL"]), dry=args.dry)
    print(f"avisos: {n}")


if __name__ == "__main__":
    main()
