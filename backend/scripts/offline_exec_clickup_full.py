"""Reavaliação: a EXECUÇÃO prediz churn quando os dados são COMPLETOS?

A conclusão original ("execução não prediz, AUC ~0,49/0,44 em churn−30/−60") saiu
do MIRROR Supabase, que descobrimos cobrir só ~51% das subtarefas reais (e alguns
clientes com 0). Aqui repetimos o MESMO experimento — mesma coorte, mesmos
metadados de cliente do mirror (servico/venda/onboarding), mesma lógica
`execution_asof` (as-of, sem vazamento) — trocando SÓ a fonte das subtarefas:
lista "Assessoria" completa via API oficial do ClickUp.

    backend/.venv/Scripts/python -m scripts.offline_exec_clickup_full

Saída: AUC(cancelado, controle) do exec_score puro, as-of churn−30 e churn−60
(controles as-of 2026-06-26). AUC>0,5 = cancelados com execução PIOR = prediz.
Compara mirror vs ClickUp lado a lado para medir o efeito da cobertura.

RESULTADO (2026-07-02): o ClickUp ao vivo casa só ~4 cancelados — os cards de
quem CANCELOU são removidos/arquivados fora desta lista (a lista Assessoria tem
só 76 tasks arquivadas, 1 card raiz). Logo o ClickUp NÃO serve p/ reconstruir a
execução histórica da coorte de churn; o mirror é a única fonte histórica. Com a
paginação do mirror já corrigida, execução segue NÃO-preditiva (AUC 0,42/0,36 em
churn−30/−60 — cancelados até com score de execução um pouco MELHOR que controles,
μ~82 vs ~76). Provável causa: cliente desengajando gera MENOS tarefas, então as
penalidades relativas ("últimas 2 semanas") caem e o score sobe — execução
confirma insatisfação, não a antecede. Decisão mantida: execução = confirmador
(peso 15), não preditor. A correção de cobertura vale p/ o RELATÓRIO (clientes
ativos), não muda o modelo de churn.
"""
from __future__ import annotations

import datetime as dt
import os
import statistics
import sys
from pathlib import Path

from app.agents.growth.execution_collector import execution_asof
from app.sources.clickup_activities import _clickup_list_tasks
from app.sources.mirror import MirrorReader
from app.sources.nps_sheets import norm_account
from app.config import get_settings
from scripts.offline_abs_vs_rel import DATA, rows, norm
from scripts.offline_score_account_check import auc
from scripts.run_portfolio import load_env


def _mirror_creds():
    import re
    ps1 = (Path(__file__).resolve().parents[1] / "scripts" / "exec_signals.ps1").read_text(encoding="utf-8")
    return (re.search(r'base="([^"]+)"', ps1).group(1), re.search(r'anon="([^"]+)"', ps1).group(1))


def _epoch_iso(ms) -> str | None:
    if not ms:
        return None
    try:
        return dt.datetime.fromtimestamp(int(ms) / 1000, tz=dt.timezone.utc).isoformat()
    except (ValueError, TypeError):
        return None


def clickup_subs_by_card() -> dict[str, list[dict]]:
    """{root_card_id: [subtarefa-dict no formato do mirror]} — TODOS os
    descendentes (qualquer profundidade) de cada card da lista Assessoria."""
    s = get_settings()
    tasks = _clickup_list_tasks(s.clickup_api_token, s.clickup_list_assessoria)
    by_id = {t["id"]: t for t in tasks}

    def root_of(t: dict) -> str:
        seen: set[str] = set()
        cur = t
        while cur.get("parent") and cur["parent"] not in seen:
            seen.add(cur["parent"])
            nxt = by_id.get(cur["parent"])
            if not nxt:
                return cur["parent"]
            cur = nxt
        return cur["id"]

    out: dict[str, list[dict]] = {}
    name_by_root: dict[str, str] = {}
    for t in tasks:
        if not t.get("parent"):
            name_by_root[t["id"]] = t.get("name") or ""
            out.setdefault(t["id"], [])
            continue
        r = root_of(t)
        out.setdefault(r, []).append({
            "data_criacao": _epoch_iso(t.get("date_created")),
            "data_conclusao": _epoch_iso(t.get("date_done") or t.get("date_closed")),
            "data_vencimento": _epoch_iso(t.get("due_date")),
            "status": (t.get("status") or {}).get("status"),
            "recorrente": False,           # a lista não expõe recorrência; igual p/ as 2 coortes
            "proximo_vencimento": None,
        })
    return out, name_by_root


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    load_env()

    # --- coorte ---
    cohort = []  # (label, nome, asof)
    for r in rows(DATA / "cases_expanded.csv"):
        if r.get("date"):
            cohort.append(("cancelado", r["cliente"], dt.date.fromisoformat(r["date"])))
    ctrl_asof = dt.date(2026, 6, 26)
    for r in rows(DATA / "controls_active_bundles.csv"):
        cohort.append(("controle", r["cliente"], ctrl_asof))
    n_canc = sum(1 for c in cohort if c[0] == "cancelado")
    print(f"coorte: {n_canc} cancelados + {len(cohort)-n_canc} controles")

    # --- metadados de cliente (mirror clientes = completo) ---
    base, anon = _mirror_creds()
    reader = MirrorReader(base, anon)
    cli_by_name = {}
    for c in reader.clientes():
        n = norm(c.nome_cliente)
        if n:
            cli_by_name.setdefault(n, c)
    # subtarefas do mirror (fonte ANTIGA, p/ comparação) — agora paginada correto
    mir_ids = [cli_by_name[norm(nm)].id for _, nm, _ in cohort if cli_by_name.get(norm(nm))]
    mir_subs = reader.subtarefas_by_cliente(list(set(mir_ids)))
    reader.close()

    # --- subtarefas COMPLETAS do ClickUp, por card, casadas por nome ---
    cu_by_card, name_by_root = clickup_subs_by_card()
    cu_by_name: dict[str, list[dict]] = {}
    for rid, subs in cu_by_card.items():
        n = norm_account(name_by_root.get(rid, ""))
        if n:
            cu_by_name.setdefault(n, subs)

    def asof_dt(d: dt.date) -> dt.datetime:
        return dt.datetime.combine(d, dt.time.max, tzinfo=dt.timezone.utc)

    # --- AUC do exec_score puro, por fonte e por horizonte ---
    for lag_label, lag in (("churn−30", 30), ("churn−60", 60)):
        res = {"mirror": {"cancelado": [], "controle": []},
               "clickup": {"cancelado": [], "controle": []}}
        matched = {"mirror": 0, "clickup": 0}
        for label, nome, asof in cohort:
            asof_eff = asof - dt.timedelta(days=lag) if label == "cancelado" else asof
            now = asof_dt(asof_eff)
            cli = cli_by_name.get(norm(nome))
            if not cli:
                continue
            # mirror
            ms = mir_subs.get(cli.id, [])
            if ms:
                er = execution_asof(cli, ms, now)
                if er.score is not None:
                    res["mirror"][label].append(er.score)
                    matched["mirror"] += 1
            # clickup completo
            cs = cu_by_name.get(norm_account(cli.nome_cliente))
            if cs:
                er = execution_asof(cli, cs, now)
                if er.score is not None:
                    res["clickup"][label].append(er.score)
                    matched["clickup"] += 1

        print(f"\n=== horizonte {lag_label} (execução {lag}d antes do churn) ===")
        for src in ("mirror", "clickup"):
            c, t = res[src]["cancelado"], res[src]["controle"]
            if not c or not t:
                print(f"  {src:8s}: coorte insuficiente (canc={len(c)} ctrl={len(t)})")
                continue
            a = auc(c, t)
            print(f"  {src:8s}: AUC={a:.3f}  canc n={len(c)} μ={statistics.mean(c):.1f}  "
                  f"ctrl n={len(t)} μ={statistics.mean(t):.1f}")


if __name__ == "__main__":
    main()
