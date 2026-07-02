"""OFFLINE diag: por que cancelados pontuam 100? Dados ralos vs genuinamente limpos.
Para cada cancelado, mostra nº de semanas com analyses na janela, nível médio de
silêncio/negativo, e o score 2-sinais. Zero rede.

    backend/.venv/Scripts/python -m scripts.offline_diag_density
"""
from __future__ import annotations

import csv
import datetime as dt
import statistics
import sys
from collections import defaultdict

from scripts.offline_abs_vs_rel import (
    build_series, norm, exid, rows, DATA, abs_risk, rel_risk, compose,
)


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

    rowsout = []
    n_weeks_all = []
    for r in rows(DATA / "cases_expanded.csv"):
        g = resolve(r["cliente"])
        if not (g and r.get("date")):
            continue
        asof = dt.date.fromisoformat(r["date"])
        sil_s, neg_s, _c = build_series(an.get(g, []), asof)
        nw = max(len(sil_s), len(neg_s))
        n_weeks_all.append(nw)
        sil_abs = abs_risk(sil_s)
        neg_abs = abs_risk(neg_s)
        # score blend (mesma fórmula do fix: 0.6 abs + 0.4 rel)
        rs = 0.6 * sil_abs + 0.4 * rel_risk(sil_s)
        rn = 0.6 * neg_abs + 0.4 * rel_risk(neg_s)
        sc = compose(rs, rn) if (sil_s or neg_s) else 100.0
        rowsout.append((sc, nw, sil_abs, neg_abs, r["cliente"][:34]))

    rowsout.sort(key=lambda x: -x[0])
    print(f"cancelados: {len(rowsout)}  | semanas de dados (analyses) na janela:")
    print(f"  0 sem={sum(1 for w in n_weeks_all if w==0)}  1-2 sem={sum(1 for w in n_weeks_all if 1<=w<=2)}"
          f"  3-5={sum(1 for w in n_weeks_all if 3<=w<=5)}  6+={sum(1 for w in n_weeks_all if w>=6)}")
    print(f"  mediana semanas = {statistics.median(n_weeks_all)}\n")
    print(f"{'score':>6} {'sem':>4} {'sil%':>6} {'neg%':>6}  cliente")
    for sc, nw, sa, na, name in rowsout:
        flag = "  <-- 100 sem sinal" if sc >= 99.9 else ("  <-- ralo" if nw <= 2 else "")
        print(f"{sc:>6.1f} {nw:>4} {sa*100:>5.0f}% {na*100:>5.0f}%  {name}{flag}")

    # correlação grosseira: score alto vem de poucas semanas?
    high = [w for sc, w, *_ in rowsout if sc >= 80]
    low = [w for sc, w, *_ in rowsout if sc < 80]
    print(f"\nsemanas médias: cancelados score>=80 -> {statistics.mean(high) if high else 0:.1f}"
          f"  | score<80 -> {statistics.mean(low) if low else 0:.1f}")


if __name__ == "__main__":
    main()
