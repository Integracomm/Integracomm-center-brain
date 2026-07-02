"""Revalidação da EXECUÇÃO na coorte, medindo em churn−30 e churn−60 (o erro da
1ª tentativa foi medir NA data do churn — tarde demais). Porte fiel
(compute_execution_score) + guarda anti-vazamento. Pergunta: 30/60 dias ANTES do
churn, os cancelados têm execução PIOR que os ativos?

    backend/.venv/Scripts/python -m scripts.validate_execution
"""
from __future__ import annotations

import csv
import datetime as dt
import re
import statistics
import sys
import unicodedata
from pathlib import Path

from app.agents.growth.execution_collector import execution_asof
from app.sources.mirror import MirrorReader

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
TODAY = dt.date(2026, 6, 26)  # ref dos controles (fim do dado estável)
UTCMAX = dt.time.max


def norm(s):
    if not s:
        return ""
    x = unicodedata.normalize("NFD", s.lower())
    x = "".join(c for c in x if unicodedata.category(c) != "Mn")
    x = re.sub(r"^\s*\[[^\]]*\]\s*", "", x).split("|")[0].replace("integracomm", "")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", x)).strip()


def rows(p):
    with p.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def asof_dt(d: dt.date) -> dt.datetime:
    return dt.datetime.combine(d, UTCMAX, tzinfo=dt.timezone.utc)


def auc(a, b):  # P(score_cancelado < score_controle): 1=perfeito, .5=aleatório
    prs = [(x, y) for x in a for y in b]
    return sum((x < y) + 0.5 * (x == y) for x, y in prs) / len(prs) if prs else 0.0


def st(xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return "(0)"
    xs = sorted(xs)
    return f"(n={len(xs)} μ={statistics.mean(xs):.1f} md={statistics.median(xs):.1f})"


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ps1 = (Path(__file__).resolve().parents[1] / "scripts" / "exec_signals.ps1").read_text(encoding="utf-8")
    base = re.search(r'base="([^"]+)"', ps1).group(1)
    anon = re.search(r'anon="([^"]+)"', ps1).group(1)
    reader = MirrorReader(base, anon)

    print("carregando clientes do mirror...", file=sys.stderr)
    name_to = {}
    for c in reader.clientes():
        n = norm(c.nome_cliente)
        if n:
            name_to.setdefault(n, c)

    # coorte -> ClienteRow
    cases, controls = [], []
    for r in rows(DATA / "cases_expanded.csv"):
        c = name_to.get(norm(r["cliente"]))
        if c and r.get("date"):
            cases.append((c, dt.date.fromisoformat(r["date"])))
    for r in rows(DATA / "controls_active_bundles.csv"):
        c = name_to.get(norm(r["cliente"]))
        if c:
            controls.append(c)

    ids = [c.id for c, _ in cases] + [c.id for c in controls]
    print(f"resolvidos: casos={len(cases)} controles={len(controls)}; puxando subtarefas...", file=sys.stderr)
    subs = reader.subtarefas_by_cliente(ids)
    reader.close()

    def score_at(cli, asof):
        res = execution_asof(cli, subs.get(cli.id, []), asof_dt(asof))
        return res.score  # None = não avaliado (ADS/implantação sem venda)

    c30 = [score_at(c, ch - dt.timedelta(days=30)) for c, ch in cases]
    c60 = [score_at(c, ch - dt.timedelta(days=60)) for c, ch in cases]
    ctl = [score_at(c, TODAY - dt.timedelta(days=30)) for c in controls]

    def ev(xs):  # avaliáveis com subtarefas
        return [x for x in xs if x is not None]

    print("\n=== EXECUÇÃO as-of (0-100; MENOR = pior) ===")
    print(f"casos churn−30  {st(c30)}")
    print(f"casos churn−60  {st(c60)}")
    print(f"controles t−30  {st(ctl)}")
    print("\ncobertura (score avaliável / resolvidos):")
    print(f"  casos: {len(ev(c30))}/{len(cases)}   controles: {len(ev(ctl))}/{len(controls)}")
    with_subs = sum(1 for c, _ in cases if subs.get(c.id))
    print(f"  casos com subtarefas no mirror: {with_subs}/{len(cases)}")

    print("\n=== DISCRIMINA? AUC (cancelado com execução PIOR que controle) ===")
    print(f"  churn−30 vs controle:  AUC = {auc(ev(c30), ev(ctl)):.3f}")
    print(f"  churn−60 vs controle:  AUC = {auc(ev(c60), ev(ctl)):.3f}")
    print("  (>0,60 sugere sinal útil; ~0,50 = não discrimina)")


if __name__ == "__main__":
    main()
