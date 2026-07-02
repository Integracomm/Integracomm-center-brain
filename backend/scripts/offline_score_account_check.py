"""OFFLINE: valida o fix pelo caminho REAL (score_account), não por réplica.
Constrói SignalInput de silêncio+tom_negativo (flag absolute_is_risk) + lagging a
partir do cache de analyses, e compara o AUC com o blend LIGADO vs DESLIGADO
(forçando scoring._ABSOLUTE_BLEND = 0). Zero rede.

    backend/.venv/Scripts/python -m scripts.offline_score_account_check
"""
from __future__ import annotations

import csv
import datetime as dt
import statistics
import sys
from collections import defaultdict
from pathlib import Path

from app.agents.growth import scoring
from app.agents.growth.scoring import SignalInput, score_account
from scripts.offline_abs_vs_rel import build_series, norm, exid, rows, DATA, TODAY, MAX_CONTROL


def make_signals(sil_s, neg_s, crit_dates, asof):
    recent = any(c >= asof - dt.timedelta(days=14) for c in crit_dates)
    older = any(asof - dt.timedelta(days=30) <= c < asof - dt.timedelta(days=14) for c in crit_dates)
    lag = 0.9 if recent else (0.5 if older else 0.0)
    return [
        SignalInput("silencio", "engagement", sil_s, higher_is_worse=True, absolute_is_risk=True),
        SignalInput("tom_negativo", "tone", neg_s, higher_is_worse=True, absolute_is_risk=True),
        SignalInput("cancelamento_explicito", "lagging", [], higher_is_worse=True, direct_risk=lag),
    ]


def auc(a, b):
    prs = [(x, y) for x in a for y in b]
    return sum((x < y) + 0.5 * (x == y) for x, y in prs) / len(prs)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    by_id, by_name = {}, {}
    for g in rows(DATA / "wa_groups.csv"):
        if exid(g["name"]):
            by_id[exid(g["name"])] = g["id"]
        by_name.setdefault(norm(g["name"]), g["id"])

    def resolve(name):
        return by_id.get(exid(name) or "") or by_name.get(norm(name))

    an = defaultdict(list)
    with (DATA / "wa_analyses.csv").open(encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            an[r["group_id"]].append((r["analysis_date"], r["classification"]))

    cohort = []
    for r in rows(DATA / "cases_expanded.csv"):
        g = resolve(r["cliente"])
        if g and r.get("date"):
            cohort.append(("cancelado", g, dt.date.fromisoformat(r["date"])))
    for r in [r for r in rows(DATA / "controls_active_bundles.csv") if resolve(r["cliente"])][:MAX_CONTROL]:
        cohort.append(("controle", resolve(r["cliente"]), TODAY))

    built = []
    for label, gid, asof in cohort:
        sil_s, neg_s, crit = build_series(an.get(gid, []), asof)
        if not sil_s and not neg_s:
            continue
        built.append((label, sil_s, neg_s, crit, asof))

    def run():
        res = {"cancelado": [], "controle": []}      # só avaliáveis (gate de cobertura)
        nonev = {"cancelado": 0, "controle": 0}      # caem na lista "revisar manual"
        for label, sil_s, neg_s, crit, asof in built:
            sigs = make_signals(sil_s, neg_s, crit, asof)
            now = dt.datetime.combine(asof, dt.time.max, tzinfo=dt.timezone.utc)
            s = score_account("x", "x", sigs, now=now)
            if s.evaluable:
                res[label].append(s.score)
            else:
                nonev[label] += 1
        return res, nonev

    print(f"coorte: {len(built)} contas (cache de analyses)\n")
    res, nonev = run()
    c, t = res["cancelado"], res["controle"]
    print(f"NÃO avaliáveis (gate cobertura < {scoring.MIN_COVERAGE_WEEKS} sem) -> lista revisar manual:"
          f"  cancelados={nonev['cancelado']}  controles={nonev['controle']}")
    print(f"AVALIÁVEIS (entram no ranking de saúde):  cancelados={len(c)}  controles={len(t)}\n")
    print(f"AUC (blend β={scoring._ABSOLUTE_BLEND}, só avaliáveis) = {auc(c,t):.3f}  "
          f"canc μ={statistics.mean(c):.1f}/md={statistics.median(c):.1f}  "
          f"ctrl μ={statistics.mean(t):.1f}/md={statistics.median(t):.1f}")


if __name__ == "__main__":
    main()
