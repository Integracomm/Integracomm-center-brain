"""Envia o relatório do estado atual ao grupo do Slack dos gestores.

    # ver o texto sem enviar:
    backend/.venv/Scripts/python -m scripts.send_slack_report --dry-run
    # enviar de verdade:
    backend/.venv/Scripts/python -m scripts.send_slack_report
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_env() -> None:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="só imprime o texto, não envia")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    load_env()

    from app.api import _conn, _latest_scores, _open_alerts, _report_from, _report_text
    from app.slack import send_text

    with _conn() as c:
        text = _report_text(_report_from(_latest_scores(c), _open_alerts(c)))

    if args.dry_run:
        print("--- DRY-RUN (nada enviado) ---")
        print(text)
        return

    send_text(text)
    with _conn() as c, c.cursor() as cur:  # auditoria do envio
        cur.execute("INSERT INTO audit_log (actor, action, scope) VALUES (%s,%s,%s)",
                    ("script:send_slack_report", "report_slack", "slack:webhook"))
    print("relatório enviado ao Slack ✓")


if __name__ == "__main__":
    main()
