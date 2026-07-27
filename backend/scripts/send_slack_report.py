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
    ap.add_argument("--force", action="store_true",
                    help="envia mesmo que já tenha havido um envio hoje (ignora a guarda diária)")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    load_env()

    if args.dry_run:
        from app.api import _conn, _latest_scores, _open_alerts, _report_from, _report_text
        with _conn() as c:
            text = _report_text(_report_from(_latest_scores(c), _open_alerts(c)))
        print("--- DRY-RUN (nada enviado) ---")
        print(text)
        return

    # Envio de BACKUP das 10h15: a rodada das 06h pode ter travado e nunca
    # enviado. A guarda diária (dentro de enviar_relatorio_diario) evita duplicar
    # quando a rodada JÁ enviou — este script então imprime 'ja-enviado-hoje'.
    from app.slack import enviar_relatorio_diario
    r = enviar_relatorio_diario(actor="script:send_slack_report", force=args.force)
    print(f"relatório ao Slack: {r}")


if __name__ == "__main__":
    main()
