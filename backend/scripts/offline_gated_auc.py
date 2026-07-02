"""OFFLINE: AUC do blend (silêncio+tom) com GATE de cobertura — quantas semanas
mínimas de analyses na janela p/ a conta ser 'avaliável'. Mostra como o AUC
sobe quando contas sem cobertura saem do ranking (em vez de virar score 100).
Zero rede.

    backend/.venv/Scripts/python -m scripts.offline_gated_auc
"""
from __future__ import annotations

import csv
import datetime as dt
import statistics
import sys
from collections import defaultdict

from scripts.offline_abs_vs_rel import (
    build_series, norm, exid, rows, DATA, TODAY, MAX_CONTROL,
    abs_risk, rel_risk, compose,
)


def auc(a, b):
    prs = [(x, y) for x in a for y in b]
    return sum((x < y) + 0.5 * (x == y) for x, y in prs) / len(prs) if prs else 0.0


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

    # pré-computa por conta: (label, n_weeks, score_blend)
    data = []
    for label, gid, asof in cohort:
        sil_s, neg_s, _c = build_series(an.get(gid, []), asof)
        nw = max(len(sil_s), len(neg_s))
        rs = 0.6 * abs_risk(sil_s) + 0.4 * rel_risk(sil_s)
        rn = 0.6 * abs_risk(neg_s) + 0.4 * rel_risk(neg_s)
        sc = compose(rs, rn) if (sil_s or neg_s) else 100.0
        data.append((label, nw, sc))

    print(f"{'gate (min sem)':<16}{'n_canc':>7}{'n_ctrl':>7}{'AUC':>8}{'excl_canc':>11}{'excl_ctrl':>11}")
    total_c = sum(1 for d in data if d[0] == "cancelado")
    total_t = sum(1 for d in data if d[0] == "controle")
    for gate in (0, 1, 2, 3, 4):
        c = [sc for lbl, nw, sc in data if lbl == "cancelado" and nw >= gate]
        t = [sc for lbl, nw, sc in data if lbl == "controle" and nw >= gate]
        print(f"{gate:<16}{len(c):>7}{len(t):>7}{auc(c, t):>8.3f}"
              f"{total_c-len(c):>11}{total_t-len(t):>11}")

    print("\n(gate=0 inclui tudo, igual à rodada ao vivo; subir o gate remove contas"
          "\n sem cobertura que viram 'saudável 100' por ausência de dado)")


if __name__ == "__main__":
    main()
