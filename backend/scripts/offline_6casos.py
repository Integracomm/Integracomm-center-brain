"""OFFLINE: os 6 casos de validação com o modelo CORRIGIDO (blend absoluto + gate
de cobertura), pelo score_account REAL. Usa só sinais das analyses cacheadas
(silêncio, tom_negativo, lagging) — iniciativa/comprimento precisam de msgs ao
vivo e ficam de fora (são justamente os sinais 'ruidosos' sob investigação).
Zero rede.

    backend/.venv/Scripts/python -m scripts.offline_6casos
"""
from __future__ import annotations

import csv
import datetime as dt
import statistics
import sys
from collections import defaultdict

from app.agents.growth.scoring import SignalInput, score_account
from scripts.offline_abs_vs_rel import build_series, norm, exid, rows, DATA

# (rótulo, id_interno, asof) — cancelados asof=churn; ativos asof=snapshot do controle (26/06)
CASES = [
    ("cancelado", "18197", dt.date(2026, 6, 10), "SAMA IMPORTS"),
    ("cancelado", "18305", dt.date(2026, 6, 11), "LOJA DOS STICKERS"),
    ("cancelado", "16055", dt.date(2026, 6, 8),  "PHL BELEZA E SAUDE"),
    ("ativo",     "17195", dt.date(2026, 6, 26), "NAVALHA AUTO PARTS"),
    ("ativo",     "154",   dt.date(2026, 6, 26), "FAMILIA DE NEGOCIOS"),
    ("ativo",     "17738", dt.date(2026, 6, 26), "ESSENCIAL TRENDS"),
]


def make_signals(sil_s, neg_s, crit_dates, asof):
    recent = any(c >= asof - dt.timedelta(days=14) for c in crit_dates)
    older = any(asof - dt.timedelta(days=30) <= c < asof - dt.timedelta(days=14) for c in crit_dates)
    lag = 0.9 if recent else (0.5 if older else 0.0)
    return [
        SignalInput("silencio", "engagement", sil_s, higher_is_worse=True, absolute_is_risk=True),
        SignalInput("tom_negativo", "tone", neg_s, higher_is_worse=True, absolute_is_risk=True),
        SignalInput("cancelamento_explicito", "lagging", [], higher_is_worse=True, direct_risk=lag),
    ], lag


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    an = defaultdict(list)
    with (DATA / "wa_analyses.csv").open(encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            an[r["group_id"]].append((r["analysis_date"], r["classification"]))

    # resolve id_interno -> group_id pelo cache de grupos
    by_id = {}
    for g in rows(DATA / "wa_groups.csv"):
        if exid(g["name"]):
            by_id[exid(g["name"])] = g["id"]

    print(f"{'caso':<21}{'esperado':<11}{'score':>6}{'faixa':>10}{'estágio':>24}"
          f"{'traj':>9}{'cob':>5}{'aval':>6}  {'sil%':>5}{'neg%':>5}{'lag':>5}")
    for label, iid, asof, nice in CASES:
        gid = by_id.get(iid.lower())
        if not gid:
            print(f"{nice:<21}{label:<11}  (grupo não resolvido p/ id {iid})")
            continue
        sil_s, neg_s, crit = build_series(an.get(gid, []), asof)
        sigs, lag = make_signals(sil_s, neg_s, crit, asof)
        s = score_account(nice, nice, sigs,
                          now=dt.datetime.combine(asof, dt.time.max, tzinfo=dt.timezone.utc))
        sil_abs = statistics.fmean([v for _, v in sil_s]) * 100 if sil_s else 0
        neg_abs = statistics.fmean([v for _, v in neg_s]) * 100 if neg_s else 0
        print(f"{nice:<21}{label:<11}{s.score:>6.1f}{s.risk_band:>10}{s.stage.value:>24}"
              f"{s.trajectory.value:>9}{s.coverage_weeks:>5}{str(s.evaluable):>6}"
              f"  {sil_abs:>4.0f}%{neg_abs:>4.0f}%{lag:>5.1f}")


if __name__ == "__main__":
    main()
