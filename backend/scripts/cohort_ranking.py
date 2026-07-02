"""Teste de RANKING na coorte: cancelados (asof=churn) vs ativos de controle
(asof=hoje), com o score CORRIGIDO (analyses ao vivo + renormalização).

Pergunta: cancelados pontuam sistematicamente PIOR que ativos saudáveis?
Métrica-chave: AUC = P(score_cancelado < score_controle) sobre todos os pares.
AUC=1 separação perfeita; 0,5 = aleatório (sem poder de ranking).

    backend/.venv/Scripts/python -m scripts.cohort_ranking
"""
from __future__ import annotations

import csv
import datetime as dt
import os
import re
import statistics
import sys
import unicodedata
from pathlib import Path

from app.agents.growth import collectors
from app.agents.growth.scoring import score_account
from app.sources.whatsapp import WhatsAppReader

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
TODAY = dt.date.today()
MAX_CONTROL = 45


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
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # console cp1252 não quebra nomes
    except Exception:
        pass
    load_env()
    by_id, by_name = {}, {}
    for g in rows(DATA / "wa_groups.csv"):
        if exid(g["name"]):
            by_id[exid(g["name"])] = g["id"]
        by_name.setdefault(norm(g["name"]), g["id"])

    def resolve(name):
        return by_id.get(exid(name) or "") or by_name.get(norm(name))

    cohort = []  # (label, name, gid, asof)
    for r in rows(DATA / "cases_expanded.csv"):
        g = resolve(r["cliente"])
        if g and r.get("date"):
            cohort.append(("cancelado", r["cliente"], g, dt.date.fromisoformat(r["date"])))
    ctrl = [r for r in rows(DATA / "controls_active_bundles.csv") if resolve(r["cliente"])][:MAX_CONTROL]
    for r in ctrl:
        cohort.append(("controle", r["cliente"], resolve(r["cliente"]), TODAY))

    reader = WhatsAppReader(os.environ["WHATSAPP_READ_API_URL"], os.environ["WHATSAPP_READ_API_KEY"])
    scored = {"cancelado": [], "controle": []}
    scored_abs = {"cancelado": [], "controle": []}  # score baseado em NÍVEL ABSOLUTO
    detail = []

    def _meanv(sigs, key):
        sig = next((s for s in sigs if s.key == key), None)
        return statistics.mean([v for _, v in sig.points]) if sig and sig.points else 0.0

    for i, (label, name, gid, asof) in enumerate(cohort, 1):
        try:
            analyses = {gid: [(a.analysis_date, a.classification) for a in reader.iter_analyses(group_id=gid)]}
            sigs = collectors.build_account_signals(reader, group_internal_id=gid, asof=asof, analyses_by_group=analyses)
            s = score_account(name[:50], name, sigs,
                              now=dt.datetime.combine(asof, dt.time.max, tzinfo=dt.timezone.utc))
            scored[label].append(s.score)
            # score ABSOLUTO: nível médio de silêncio + tom negativo na janela (0-1, alto=pior)
            abs_risk = (_meanv(sigs, "silencio") + _meanv(sigs, "tom_negativo")) / 2
            scored_abs[label].append(round(100 * (1 - abs_risk), 1))
            detail.append((label, round(s.score, 1), s.risk_band, s.stage.value, name[:38]))
        except Exception as e:
            print(f"  skip {name[:30]}: {e}", file=sys.stderr)
        if i % 15 == 0:
            print(f"  ...{i}/{len(cohort)}", file=sys.stderr)
    reader.close()

    canc, ctl = scored["cancelado"], scored["controle"]
    def stats(xs):
        xs = sorted(xs)
        return (len(xs), round(statistics.mean(xs), 1), round(statistics.median(xs), 1),
                round(xs[len(xs)//4], 1), round(xs[3*len(xs)//4], 1))

    print("\n=== DISTRIBUIÇÃO DO SCORE (menor = pior) ===")
    print(f"{'coorte':<12}{'n':>4}{'média':>8}{'mediana':>9}{'p25':>7}{'p75':>7}")
    for lbl, xs in (("cancelado", canc), ("controle", ctl)):
        n, mean, med, p25, p75 = stats(xs)
        print(f"{lbl:<12}{n:>4}{mean:>8}{med:>9}{p25:>7}{p75:>7}")

    # AUC = P(score_cancelado < score_controle) -> 1 ideal, 0,5 aleatório
    def auc(a, b):
        prs = [(x, y) for x in a for y in b]
        return sum((x < y) + 0.5 * (x == y) for x, y in prs) / len(prs)

    ctl_med = statistics.median(ctl)
    below = sum(c < ctl_med for c in canc) / len(canc)
    print(f"\nAUC MODELO ATUAL (baseline-relativo) = {auc(canc, ctl):.3f}")
    print(f"AUC NÍVEL ABSOLUTO (silêncio+tom)    = {auc(scored_abs['cancelado'], scored_abs['controle']):.3f}")
    print("  (1=perfeito, 0,5=aleatório)")
    print(f"% de cancelados abaixo da MEDIANA do controle (modelo) = {below*100:.0f}%")

    # quantos cancelados pegaram override de saída (lagging)
    canc_exit = sum(1 for d in detail if d[0] == "cancelado" and d[3] == "intencao_de_saida")
    print(f"cancelados em 'intenção de saída' (override pegou) = {canc_exit}/{len(canc)}")

    print("\n=== piores INVERSÕES: controles (ativos) com score mais baixo ===")
    for d in sorted([d for d in detail if d[0] == "controle"], key=lambda x: x[1])[:8]:
        print(f"  {d[1]:>5} | {d[2]:<7}| {d[3]:<22}| {d[4]}")
    print("=== cancelados com score MAIS ALTO (deveriam ser baixos) ===")
    for d in sorted([d for d in detail if d[0] == "cancelado"], key=lambda x: -x[1])[:8]:
        print(f"  {d[1]:>5} | {d[2]:<7}| {d[3]:<22}| {d[4]}")


if __name__ == "__main__":
    main()
