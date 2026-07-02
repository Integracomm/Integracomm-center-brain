"""Mostra a COMPOSIÇÃO do score de uma conta: risco por sinal, por bloco, e a
contribuição ponderada ao risco_total. Para entender amortecimentos.

    backend/.venv/Scripts/python -m scripts.diag_composition "LOJA DOS STICKERS"
"""
from __future__ import annotations

import csv
import datetime as dt
import os
import re
import sys
import unicodedata
from pathlib import Path

from app.agents.growth import collectors
from app.agents.growth.scoring import WEIGHTS, score_account, signal_risk
from app.sources.whatsapp import WhatsAppReader

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"


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
    x = re.sub(r"^\s*\[[^\]]*\]\s*", "", x).split("|")[0].replace("integracomm", "")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", x)).strip()


def exid(s):
    m = re.search(r"id\s*:\s*([a-z0-9_-]+)", s or "", re.I)
    return m.group(1).lower() if m else None


def rows(p):
    with p.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def main():
    load_env()
    query = sys.argv[1] if len(sys.argv) > 1 else "LOJA DOS STICKERS"

    by_id, by_name = {}, {}
    for g in rows(DATA / "wa_groups.csv"):
        if exid(g["name"]):
            by_id[exid(g["name"])] = g["id"]
        by_name.setdefault(norm(g["name"]), g["id"])

    # acha a conta na coorte de cancelados (asof = churn) ou usa hoje
    asof, name, gid = dt.date.today(), query, None
    for r in rows(DATA / "cases_expanded.csv"):
        if query.lower() in r["cliente"].lower():
            name = r["cliente"]
            asof = dt.date.fromisoformat(r["date"]) if r.get("date") else dt.date.today()
            gid = by_id.get(exid(r["cliente"]) or "") or by_name.get(norm(r["cliente"]))
            break
    if not gid:
        gid = by_id.get(exid(query) or "") or by_name.get(norm(query))
    if not gid:
        sys.exit(f"Não resolvi o grupo de '{query}'")

    reader = WhatsAppReader(os.environ["WHATSAPP_READ_API_URL"], os.environ["WHATSAPP_READ_API_KEY"])
    analyses = {gid: [(a.analysis_date, a.classification) for a in reader.iter_analyses(group_id=gid)]}
    signals = collectors.build_account_signals(reader, group_internal_id=gid, asof=asof, analyses_by_group=analyses)
    reader.close()

    print(f"=== {name}  (asof={asof}) ===\n")
    print(f"{'sinal':<22}{'bloco':<12}{'risco':>7}   série (nº pts)")
    by_block = {}
    for sig in signals:
        r, _ = signal_risk(sig)
        by_block.setdefault(sig.block, []).append(r)
        print(f"{sig.key:<22}{sig.block:<12}{r:>7.3f}   {len(sig.points)} pts"
              + (f"  direct_risk={sig.direct_risk}" if sig.direct_risk is not None else ""))

    print(f"\n{'bloco':<14}{'peso':>5}{'risco_bloco':>13}{'contribuição':>14}")
    total_w = sum(WEIGHTS.values())
    risk_total = 0.0
    for block, weight in WEIGHTS.items():
        risks = by_block.get(block)
        br = (sum(risks) / len(risks)) if risks else 0.0
        contrib = (weight / total_w) * br
        risk_total += contrib
        print(f"{block:<14}{weight:>5}{br:>13.3f}{contrib:>14.3f}"
              + ("" if risks else "   (sem sinal)"))
    print(f"\nrisco_total = {risk_total:.3f}   ->   score = {round(100*(1-risk_total),1)}")

    s = score_account("diag", name, signals, now=dt.datetime.combine(asof, dt.time.max, tzinfo=dt.timezone.utc))
    print(f"faixa={s.risk_band} | trajetória={s.trajectory.value} | estágio={s.stage.value}")


if __name__ == "__main__":
    main()
