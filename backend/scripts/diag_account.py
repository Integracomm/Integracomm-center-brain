"""Diagnóstico AO VIVO de UMA conta (sem cache). Uso:
    backend/.venv/Scripts/python -m scripts.diag_account "solution store"
Acha o(s) grupo(s) que casam o termo, mostra is_active + se passa no filtro de
carteira, lista as analyses AO VIVO recentes (foco no evento), e pontua a conta
como o agente (asof da rodada 30/06 e hoje).
"""
from __future__ import annotations

import datetime as dt
import os
import re
import sys
import unicodedata
from pathlib import Path

from app.agents.growth import collectors
from app.agents.growth.scoring import score_account, alert_severity
from app.sources.whatsapp import WhatsAppReader

ROOT = Path(__file__).resolve().parents[2]
_FINALIZED = re.compile(r"finaliz", re.I)
_HAS_ID = re.compile(r"id\s*:\s*[a-z0-9_-]+", re.I)


def load_env():
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def norm(s):
    if not s:
        return ""
    x = unicodedata.normalize("NFD", s.lower())
    x = "".join(c for c in x if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", x)).strip()


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    term = norm(sys.argv[1] if len(sys.argv) > 1 else "solution store")
    load_env()
    reader = WhatsAppReader(os.environ["WHATSAPP_READ_API_URL"], os.environ["WHATSAPP_READ_API_KEY"])

    matches = [g for g in reader.iter_groups() if term in norm(g.name)]
    print(f"grupos que casam '{term}': {len(matches)}\n")
    for g in matches:
        passa = bool(g.is_active and not _FINALIZED.search(g.name) and _HAS_ID.search(g.name))
        print(f"=== {g.name}")
        print(f"    group_id={g.id}  is_active={g.is_active}  passa_no_filtro_carteira={passa}")

        an = [(a.analysis_date, a.classification) for a in reader.iter_analyses(group_id=g.id)]
        an.sort()
        print(f"    analyses AO VIVO: {len(an)} no total")
        recent = [(d, c) for d, c in an if d >= "2026-06-10"]
        print("    veredictos desde 10/06:")
        for d, c in recent:
            marca = "  <<< 25/06" if d == "2026-06-25" else ""
            print(f"       {d}  {c}{marca}")
        crit_2506 = [c for d, c in an if d == "2026-06-25" and c.upper().startswith("CR")]
        print(f"    -> 25/06 é CRÍTICO ao vivo? {'SIM' if crit_2506 else 'NAO'}")

        for asof in (dt.date(2026, 6, 30), dt.date(2026, 7, 1)):
            sigs = collectors.build_account_signals(
                reader, group_internal_id=g.id, asof=asof, analyses_by_group={g.id: an})
            s = score_account(g.name[:50], g.name, sigs,
                              now=dt.datetime.combine(asof, dt.time.max, tzinfo=dt.timezone.utc))
            lag = next((sg.direct_risk for sg in sigs if sg.block == "lagging"), None)
            print(f"    [asof={asof}] score={s.score} band={s.risk_band} stage={s.stage.value} "
                  f"coverage_weeks={s.coverage_weeks} evaluable={s.evaluable} lagging={lag} "
                  f"alerta={alert_severity(s)}")
        print()
    reader.close()


if __name__ == "__main__":
    main()
