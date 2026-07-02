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

NOTA (correção do Otávio): os cards de quem cancelou NÃO somem do ClickUp — são
movidos p/ a lista CS/Cancelados (900700953811), LEVANDO a árvore de atividades
(44/61 da coorte casam lá; mediana 17 subtarefas; cobertura de vencimento 77%,
simétrica aos 80% da Assessoria). Então o teste completo é: cancelados com
subtarefas do CS/Cancelados, controles com subtarefas da Assessoria — mesma API,
mesmos campos. A 1ª versão deste script errou ao buscar cancelados só na lista
Assessoria (casava ~4) e concluir que o ClickUp não retinha o histórico.

RESULTADO FINAL (2026-07-02, ver docs/reavaliacao-execucao-churn.md): com dados
COMPLETOS, AUC 0,529 (churn−30) e 0,455 (churn−60) — moeda ao ar. O paradoxo do
mirror (cancelados c/ execução "melhor", μ~82-84) some (μ~69-72 ≈ controles):
a suspeita de dados era procedente, mas a conclusão não muda — execução segue
CONFIRMADOR (bloco 15%), não preditor. Sinal líder continua sendo a conversa.
"""
from __future__ import annotations

import datetime as dt
import os
import statistics
import sys
from pathlib import Path

from app.agents.growth.execution_collector import execution_asof
from app.sources.clickup_activities import _clickup_list_tasks
from app.sources.mirror import ClienteRow, MirrorReader
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


CS_CANCELADOS_LIST = "900700953811"  # registro vivo do churn 2025→ (cards movidos COM a árvore)


def clickup_subs_by_card(list_id: str) -> tuple[dict[str, list[dict]], dict[str, str]]:
    """{root_card_id: [subtarefa-dict no formato do mirror]} — TODOS os
    descendentes (qualquer profundidade) de cada card da lista."""
    s = get_settings()
    tasks = _clickup_list_tasks(s.clickup_api_token, list_id)
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
    # controles = lista Assessoria (ativos); cancelados = lista CS/Cancelados
    # (o card é MOVIDO p/ lá com a árvore quando o contrato encerra)
    s = get_settings()
    def name_map(list_id: str) -> dict[str, list[dict]]:
        by_card, name_by_root = clickup_subs_by_card(list_id)
        out: dict[str, list[dict]] = {}
        for rid, subs in by_card.items():
            n = norm_account(name_by_root.get(rid, ""))
            if n:
                out.setdefault(n, subs)
        return out
    cu_ativos = name_map(s.clickup_list_assessoria)
    cu_cancelados = name_map(CS_CANCELADOS_LIST)

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
            # mirror (exige o cliente no mirror — fonte antiga)
            if cli:
                ms = mir_subs.get(cli.id, [])
                if ms:
                    er = execution_asof(cli, ms, now)
                    if er.score is not None:
                        res["mirror"][label].append(er.score)
                        matched["mirror"] += 1
            else:
                # sem metadados do mirror: cliente sintético (servico/venda
                # desconhecidos -> caminho normal do score, sem penal. onboarding)
                cli = ClienteRow(id="", nome_cliente=nome, servico=None, data_venda=None,
                                 data_onboarding=None, status=None, valor_assessoria=None)
            # clickup completo: cancelado busca no CS/Cancelados (fallback
            # Assessoria); controle, na Assessoria
            key_cli = norm_account(cli.nome_cliente)
            key_nm = norm_account(nome)
            if label == "cancelado":
                cs = (cu_cancelados.get(key_cli) or cu_cancelados.get(key_nm)
                      or cu_ativos.get(key_cli) or cu_ativos.get(key_nm))
            else:
                cs = cu_ativos.get(key_cli) or cu_ativos.get(key_nm)
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
