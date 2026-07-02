"""OFFLINE (zero rede): compara, para os dois sinais validados pelo caso-controle
(silêncio e tom_negativo, ambos vindos SÓ das analyses já cacheadas em
data/wa_analyses.csv), três formas de virar risco -> AUC cancelado vs controle:

  1) RELATIVO  (modelo atual): desvio do baseline da conta + velocidade.
  2) ABSOLUTO  : nível médio do sinal na janela (o que o caso-control validou).
  3) BLEND     : beta*absoluto + (1-beta)*relativo no risco de cada sinal.

Objetivo: confirmar a DIREÇÃO do fix antes de mexer em scoring.py. Não chama o
WhatsApp ao vivo — replica o anchoring dos collectors usando o cache de analyses.

    backend/.venv/Scripts/python -m scripts.offline_abs_vs_rel
"""
from __future__ import annotations

import csv
import datetime as dt
import os
import re
import statistics
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

from app.agents.growth.scoring import _squash
from app.agents.growth.trajectory import analyze_series

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
TODAY = dt.date.today()
MAX_CONTROL = 45
WINDOW = 90
W_SIL, W_NEG = 45.0, 25.0  # pesos engagement(silencio) / tone(tom_negativo)


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


def _monday(d):
    return d - dt.timedelta(days=d.weekday())


def build_series(analyses, asof):
    """Replica os collectors p/ silencio e tom_negativo a partir das analyses cacheadas."""
    start_default = asof - dt.timedelta(days=WINDOW)
    sem, conv, neg = defaultdict(int), defaultdict(int), defaultdict(int)
    crit_dates = []
    first_data = None
    for date_str, classif in analyses:
        try:
            d = dt.date.fromisoformat(date_str)
        except ValueError:
            continue
        if d < start_default or d > asof:
            continue
        first_data = d if first_data is None else min(first_data, d)
        wk = _monday(d)
        c = classif.upper()
        if "SEM CONVERSA" in c or "SEM DADO" in c:
            sem[wk] += 1
        else:
            conv[wk] += 1
            if c.startswith("CR") or "ATEN" in c:
                neg[wk] += 1
            if c.startswith("CR"):
                crit_dates.append(d)
    anchor = max(start_default, first_data) if first_data else start_default
    weeks = sorted({w for w in (set(sem) | set(conv)) if w >= _monday(anchor)})
    sil_s, neg_s = [], []
    for wk in weeks:
        days = sem[wk] + conv[wk]
        sil_s.append((wk, sem[wk] / days if days else 0.0))
        neg_s.append((wk, neg[wk] / conv[wk] if conv[wk] else 0.0))
    return sil_s, neg_s, crit_dates


def rel_risk(points, higher_is_worse=True):
    tr = analyze_series(points)
    dev = tr.deviation if higher_is_worse else -tr.deviation
    vel = tr.velocity if higher_is_worse else -tr.velocity
    return max(0.0, min(1.0, 0.6 * _squash(dev) + 0.4 * _squash(vel * 30)))


def abs_risk(points):
    """Nível absoluto = média do sinal na janela (já 0-1, alto=pior)."""
    return statistics.fmean([v for _, v in points]) if points else 0.0


def compose(rs, rn):
    """Score 0-100 a partir dos riscos de silencio(rs) e tom_negativo(rn), pesos 45/25."""
    risk = (W_SIL * rs + W_NEG * rn) / (W_SIL + W_NEG)
    return round(100 * (1 - risk), 1)


def auc(a, b):
    prs = [(x, y) for x in a for y in b]
    return sum((x < y) + 0.5 * (x == y) for x, y in prs) / len(prs)


def stats(xs):
    xs = sorted(xs)
    return (len(xs), round(statistics.mean(xs), 1), round(statistics.median(xs), 1))


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
            cohort.append(("cancelado", r["cliente"], g, dt.date.fromisoformat(r["date"])))
    ctrl = [r for r in rows(DATA / "controls_active_bundles.csv") if resolve(r["cliente"])][:MAX_CONTROL]
    for r in ctrl:
        cohort.append(("controle", r["cliente"], resolve(r["cliente"]), TODAY))

    # acumula, por coorte, os scores de cada variante
    res = {v: {"cancelado": [], "controle": []} for v in ("rel", "abs", "blend")}
    abs_levels = {"cancelado": {"sil": [], "neg": []}, "controle": {"sil": [], "neg": []}}
    skipped = 0
    BETA = 0.6  # peso do nível absoluto no blend

    for label, name, gid, asof in cohort:
        sil_s, neg_s, _crit = build_series(an.get(gid, []), asof)
        if not sil_s and not neg_s:
            skipped += 1
            continue
        rs_rel, rn_rel = rel_risk(sil_s), rel_risk(neg_s)
        rs_abs, rn_abs = abs_risk(sil_s), abs_risk(neg_s)
        rs_bl = BETA * rs_abs + (1 - BETA) * rs_rel
        rn_bl = BETA * rn_abs + (1 - BETA) * rn_rel
        res["rel"][label].append(compose(rs_rel, rn_rel))
        res["abs"][label].append(compose(rs_abs, rn_abs))
        res["blend"][label].append(compose(rs_bl, rn_bl))
        abs_levels[label]["sil"].append(rs_abs)
        abs_levels[label]["neg"].append(rn_abs)

    print(f"coorte: {sum(len(res['rel'][l]) for l in ('cancelado','controle'))} avaliadas, {skipped} sem analyses na janela\n")
    print("=== NÍVEL ABSOLUTO MÉDIO (sanity vs caso-controle: silêncio ~65% vs 51%, neg ~44% vs 20%) ===")
    for lbl in ("cancelado", "controle"):
        sil = statistics.fmean(abs_levels[lbl]["sil"]) if abs_levels[lbl]["sil"] else 0
        neg = statistics.fmean(abs_levels[lbl]["neg"]) if abs_levels[lbl]["neg"] else 0
        print(f"  {lbl:<10} silêncio={sil*100:.1f}%  tom_negativo={neg*100:.1f}%")

    print("\n=== AUC por variante (1=perfeito, 0,5=aleatório; cancelado deve < controle) ===")
    print(f"{'variante':<10}{'AUC':>7}   {'canc(n,μ,md)':>18}   {'ctrl(n,μ,md)':>18}")
    for v, lab in (("rel", "RELATIVO"), ("abs", "ABSOLUTO"), ("blend", f"BLEND β={BETA}")):
        c, t = res[v]["cancelado"], res[v]["controle"]
        print(f"{lab:<14}{auc(c, t):>5.3f}   {str(stats(c)):>18}   {str(stats(t)):>18}")

    # varredura de beta (recomputa risco por sinal por conta — barato, offline)
    print("\n=== VARREDURA β (peso do nível absoluto no blend) ===")
    per = []  # (label, rs_rel, rn_rel, rs_abs, rn_abs)
    for label, name, gid, asof in cohort:
        sil_s, neg_s, _c = build_series(an.get(gid, []), asof)
        if not sil_s and not neg_s:
            continue
        per.append((label, rel_risk(sil_s), rel_risk(neg_s), abs_risk(sil_s), abs_risk(neg_s)))
    for b in (0.0, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0):
        c, t = [], []
        for label, rsr, rnr, rsa, rna in per:
            sc = compose(b * rsa + (1 - b) * rsr, b * rna + (1 - b) * rnr)
            (c if label == "cancelado" else t).append(sc)
        print(f"  β={b:.1f}  AUC={auc(c, t):.3f}")


if __name__ == "__main__":
    main()
