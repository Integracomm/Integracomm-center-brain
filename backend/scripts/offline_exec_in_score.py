"""Mede o impacto de incluir a EXECUÇÃO (bloco 15%) no score, na coorte:
AUC cancelado-vs-controle SEM e COM o sinal de execução (direct_risk = 1-exec/100,
as-of correto, porte fiel). Sinais WhatsApp do cache (zero custo); execução do
mirror (leitura rápida). Decide o default da flag EXECUTION_IN_SCORE.

    backend/.venv/Scripts/python -m scripts.offline_exec_in_score
"""
from __future__ import annotations

import csv
import datetime as dt
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

from app.agents.growth.execution_collector import execution_asof
from app.agents.growth.scoring import SignalInput, score_account
from app.sources.mirror import MirrorReader
from scripts.offline_abs_vs_rel import build_series, norm, exid, rows, DATA, TODAY, MAX_CONTROL
from scripts.offline_score_account_check import make_signals, auc


def _mirror_creds():
    ps1 = (Path(__file__).resolve().parents[1] / "scripts" / "exec_signals.ps1").read_text(encoding="utf-8")
    return (re.search(r'base="([^"]+)"', ps1).group(1), re.search(r'anon="([^"]+)"', ps1).group(1))


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

    def resolve(n):
        return by_id.get(exid(n) or "") or by_name.get(norm(n))

    an = defaultdict(list)
    with (DATA / "wa_analyses.csv").open(encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            an[r["group_id"]].append((r["analysis_date"], r["classification"]))

    cohort = []  # (label, nome, gid, asof)
    for r in rows(DATA / "cases_expanded.csv"):
        g = resolve(r["cliente"])
        if g and r.get("date"):
            cohort.append(("cancelado", r["cliente"], g, dt.date.fromisoformat(r["date"])))
    for r in [r for r in rows(DATA / "controls_active_bundles.csv") if resolve(r["cliente"])][:MAX_CONTROL]:
        cohort.append(("controle", r["cliente"], resolve(r["cliente"]), TODAY))

    # execução as-of pelo mirror
    base, anon = _mirror_creds()
    reader = MirrorReader(base, anon)
    cli_by_name = {}
    for c in reader.clientes():
        n = norm(c.nome_cliente)
        if n:
            cli_by_name.setdefault(n, c)
    matched = {name: cli_by_name.get(norm(name)) for _, name, _, _ in cohort}
    ids = [c.id for c in matched.values() if c]
    subs = reader.subtarefas_by_cliente(ids)
    reader.close()

    res = {"sem": {"cancelado": [], "controle": []}, "com": {"cancelado": [], "controle": []}}
    n_exec = 0
    for label, name, gid, asof in cohort:
        sil_s, neg_s, crit = build_series(an.get(gid, []), asof)
        if not sil_s and not neg_s:
            continue
        sigs = make_signals(sil_s, neg_s, crit, asof)
        now = dt.datetime.combine(asof, dt.time.max, tzinfo=dt.timezone.utc)
        s0 = score_account("x", name, sigs, now=now)
        if not s0.evaluable:
            continue
        res["sem"][label].append(s0.score)
        # com execução (quando o mirror tem o cliente e o score é avaliável)
        sigs2 = list(sigs)
        cli = matched.get(name)
        if cli:
            er = execution_asof(cli, subs.get(cli.id, []), now)
            if er.score is not None:
                sigs2 = sigs2 + [SignalInput("execucao", "execution", [], higher_is_worse=True,
                                             source="clickup", direct_risk=1 - er.score / 100.0)]
                n_exec += 1
        s1 = score_account("x", name, sigs2, now=now)
        res["com"][label].append(s1.score)

    print(f"coorte avaliável: canc={len(res['sem']['cancelado'])} ctrl={len(res['sem']['controle'])}"
          f" | contas com execução no mirror: {n_exec}")
    for tag in ("sem", "com"):
        c, t = res[tag]["cancelado"], res[tag]["controle"]
        print(f"AUC {tag.upper()} execução (15%): {auc(c, t):.3f}"
              f"  canc μ={statistics.mean(c):.1f}  ctrl μ={statistics.mean(t):.1f}")


if __name__ == "__main__":
    main()
