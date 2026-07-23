"""Análise dos Squads — o CÁLCULO (Lote 6, 23/07).

Extraído de `api._carga_content`, que misturava cálculo e HTML em 411 linhas.
A tela HTML e o `/api/growth/carga` passam a ler daqui: uma régua só.

As três perguntas da tela:
  1. RANKING  — onde está o risco por time (MRR em risco, alertas, faixas);
  2. CAPACIDADE — o time dá conta? contas/pessoa E tarefas/pessoa, porque
     tarefa recorrente faz a carga REAL divergir do tamanho da carteira;
  3. ATRASOS — as atividades vencidas por squad e por pessoa, cruzadas com a
     capacidade para separar SOBRECARGA de RITMO/processo.

Regras que vieram junto (não são detalhe — cada uma nasceu de um caso real):
  - cliente pausado por inadimplência/concluído fica FORA das contagens de
    tarefas: serviço suspenso não é carga nem cobrança do squad (20/07);
  - dedupe por ID de tarefa: cliente com 2+ contas no painel (bundle + ADS)
    casa com o MESMO card do ClickUp e a tarefa contava 2× (caso LUFRAN, 20/07);
  - a conta principal (não-ADS) entra primeiro e fica com a atribuição.
"""
from __future__ import annotations

import datetime as dt
from collections import Counter
from typing import Any


def _deps():
    from . import api as A
    return A


def _pearson(pares: list[tuple[float, float]]) -> float | None:
    """Correlação de Pearson. Menos de 3 pontos NÃO vira número — com 2 squads
    qualquer r dá ±1 e sugeriria uma relação que não existe."""
    n = len(pares)
    if n < 3:
        return None
    mx = sum(x for x, _ in pares) / n
    my = sum(y for _, y in pares) / n
    sx = sum((x - mx) ** 2 for x, _ in pares) ** 0.5
    sy = sum((y - my) ** 2 for _, y in pares) ** 0.5
    if not sx or not sy:
        return None
    return sum((x - mx) * (y - my) for x, y in pares) / (sx * sy)


def carga_dados(conn: Any, scores: list[dict], mirror: dict | None) -> dict:
    A = _deps()

    # ---- 1. agregação por squad -------------------------------------------
    por_squad: dict[str, dict] = {}
    for s in scores:
        k = A._resolve_squad(s["name"], mirror) or "(sem squad na planilha)"
        d = por_squad.setdefault(k, {"n": 0, "mrr": 0.0, "mrr_risco": 0.0, "crit": 0,
                                     "alto": 0, "atencao": 0, "exec_atr": 0,
                                     "bandas": {"baixo": 0, "medio": 0, "alto": 0,
                                                "critico": 0, "sem": 0}})
        d["n"] += 1
        mrr = max(0.0, A._mrr_val(s))
        d["mrr"] += mrr
        band = s["risk_band"] if s["evaluable"] else "sem"
        d["bandas"][band if band in d["bandas"] else "sem"] += 1
        if band in ("alto", "critico"):
            d["mrr_risco"] += mrr
        sev = s.get("alert_sev")
        if sev in ("critico", "alto", "atencao"):
            ch = "crit" if sev == "critico" else sev
            d[ch] = d.get(ch, 0) + 1
        if (s.get("exec_score") or 100) < 40:
            d["exec_atr"] += 1

    tot_risco = sum(d["mrr_risco"] for d in por_squad.values()) or 1.0
    ranking = []
    # DESEMPATE pelo NOME no fim (23/07): squads sem MRR em risco e sem
    # críticos empatam em (0, 0), e aí a ordem caía na ordem de inserção do
    # dict — que depende de como a lista de scores chegou. O handler HTML passa
    # `ordered` (avaliáveis primeiro) e o endpoint passava a lista crua, então
    # B2-S1 e B2-S2 trocavam de lugar entre as duas telas com os MESMOS
    # números. Com o nome na chave, as duas ficam iguais e estáveis.
    for k, d in sorted(por_squad.items(),
                       key=lambda x: (x[0].startswith("(sem"), -x[1]["mrr_risco"],
                                      -x[1]["crit"], x[0])):
        conc = d["mrr_risco"] / tot_risco
        ranking.append({
            "squad": k, "sem_squad": k.startswith("(sem"),
            "contas": d["n"], "mrr": d["mrr"], "mrr_risco": d["mrr_risco"],
            "concentracao": conc,
            # o selo é do backend: a régua de "concentração" mora aqui
            "concentra_risco": (d["crit"] >= 3 or conc >= 0.3) and not k.startswith("(sem"),
            "criticos": d["crit"], "altos": d["alto"], "atencao": d["atencao"],
            "exec_critica": d["exec_atr"], "bandas": d["bandas"],
        })

    # ---- 2. capacidade -----------------------------------------------------
    try:
        from .sources.squads_sheet import squad_teams
        times = squad_teams()
    except Exception:  # noqa: BLE001 — planilha fora não derruba a aba
        times = {}
    cap_rows = [(k, len(times.get(k, [])), d) for k, d in por_squad.items()
                if not k.startswith("(sem")]

    try:
        from .sources.clickup_activities import open_task_ids as _open_fn
    except Exception:  # noqa: BLE001
        _open_fn = None
    try:
        from .sources.clickup_activities import client_inactive_status as _inat_fn
    except Exception:  # noqa: BLE001
        _inat_fn = None

    def _inativo(nm: str):
        return _inat_fn(nm) if _inat_fn else None

    def _ordem_dedup(s):
        return (s["name"].upper().lstrip("[ ").startswith("ADS"), s["name"])

    tarefas_sq: dict[str, int] = {}
    _vistas: set[str] = set()
    if _open_fn is not None:
        for s in sorted(scores, key=_ordem_dedup):
            k_sq = A._resolve_squad(s["name"], mirror)
            if k_sq is None or _inativo(s["name"]):
                continue
            try:
                ids = _open_fn(s["name"]) or set()
            except Exception:  # noqa: BLE001 — conta sem match não derruba a aba
                continue
            novas = ids - _vistas
            _vistas |= novas
            tarefas_sq[k_sq] = tarefas_sq.get(k_sq, 0) + len(novas)

    medias = [d["n"] / p for _k, p, d in cap_rows if p]
    med_cp = (sum(medias) / len(medias)) if medias else None
    _tps = [tarefas_sq.get(k, 0) / p for k, p, _d in cap_rows if p] if tarefas_sq else []
    med_tp = (sum(_tps) / len(_tps)) if _tps else None

    # ORDEM: por tarefas/pessoa desc — a carga REAL de trabalho, que é o que a
    # seção existe para mostrar (Otávio 23/07). Ordenar por contas/pessoa
    # escondia o squad afogado: B2-S1 tinha 88 tarefas/pessoa (2× o segundo) e
    # caía em 3º só porque a carteira dele era média. Sem ClickUp, `med_tp` é
    # None e a chave cai para contas/pessoa — a tabela nunca perde a ordem.
    def _ord(x):
        k, p, d = x
        tp = (tarefas_sq.get(k, 0) / p) if (p and tarefas_sq) else None
        cp = (d["n"] / p) if p else 0
        return (-(tp if tp is not None else -1), -cp, k)

    capacidade, sobre, folga = [], [], []
    for k, p, d in sorted(cap_rows, key=_ord):
        cp = (d["n"] / p) if p else None
        graves = d["crit"] + d["alto"]
        tar = tarefas_sq.get(k, 0)
        tp = (tar / p) if p else None
        # SELO pelas DUAS cargas (Otávio 23/07): sobrecarga se contas/pessoa OU
        # tarefas/pessoa está bem acima da média — B2-S1, afogado em tarefas mas
        # com carteira média, não podia ficar sem sinal. Folga só quando AS DUAS
        # estão baixas: B2-S2 tinha 6 contas/pessoa mas 32 tarefas/pessoa (na
        # média), então deixa de ser "folga".
        cp_alta = cp is not None and med_cp and cp >= med_cp * 1.3
        tp_alta = tp is not None and med_tp and tp >= med_tp * 1.3
        cp_baixa = cp is not None and med_cp and cp <= med_cp * 0.7
        tp_baixa = (tp is None) or (med_tp and tp <= med_tp * 0.7)
        estado = None
        if cp_alta or tp_alta:
            estado = "sobrecarga"
            sobre.append((k, cp or 0, graves))
        elif cp_baixa and tp_baixa:
            estado = "folga"
            folga.append((k, cp or 0))
        avaliadas = d["n"] - d["bandas"]["sem"]
        tom_tp = None
        if tp is not None and med_tp:
            tom_tp = "critico" if tp >= med_tp * 1.3 else ("ok" if tp <= med_tp * 0.7 else None)
        # tom de CONTAS/pessoa na mesma régua (Otávio 23/07): quando o selo de
        # sobrecarga dispara pela carteira, a coluna que o causou fica em
        # vermelho — o leitor vê de onde veio a tag, sem adivinhar
        tom_cp = None
        if cp is not None and med_cp:
            tom_cp = "critico" if cp >= med_cp * 1.3 else ("ok" if cp <= med_cp * 0.7 else None)
        capacidade.append({
            "squad": k, "pessoas": p, "contas": d["n"], "contas_pessoa": cp,
            "estado": estado, "tom_contas": tom_cp,
            "tarefas_abertas": (tar if tarefas_sq else None),
            "tarefas_pessoa": (tp if tarefas_sq else None), "tom_tarefas": tom_tp,
            "mrr_pessoa": (d["mrr"] / p) if p else None,
            "graves_pessoa": (graves / p) if p else None,
            "pct_saudavel": (d["bandas"]["baixo"] / avaliadas) if avaliadas else None,
        })

    leitura_cap = ("Cargas relativamente equilibradas entre os squads — sem caso claro de "
                   "redistribuição agora.")
    if sobre:
        # o "pior" é o mais sobrecarregado pela carga que DISPAROU o selo: se há
        # tarefas, a carga real (tarefas/pessoa) manda; senão, contas/pessoa.
        # (pess_by só nasce na seção de atrasos, adiante — aqui vai um local.)
        _pess = {k: p for k, p, _d in cap_rows}

        def _peso(k):
            p = _pess.get(k) or 0
            return (tarefas_sq.get(k, 0) / p) if (p and tarefas_sq and med_tp) \
                else ((por_squad[k]["n"] / p) if p else 0)
        pk = max((k for k, _cp, _g in sobre), key=_peso)
        pd = por_squad[pk]
        pp = _pess.get(pk) or 0
        cp_p = (pd["n"] / pp) if pp else 0
        tp_p = (tarefas_sq.get(pk, 0) / pp) if pp else 0
        graves_p = pd["crit"] + pd["alto"]
        motivo = (f"{tp_p:.0f} tarefas abertas por pessoa (média: {med_tp:.0f})"
                  if (med_tp and tp_p >= med_tp * 1.3)
                  else f"{cp_p:.1f} contas por pessoa (média: {med_cp:.1f})")
        alvo = (f" O squad {folga[0][0]} tem folga ({folga[0][1]:.1f} contas/pessoa) e é o "
                "candidato natural a absorver contas do mesmo bundle." if folga else "")
        leitura_cap = (f"{pk} está com {motivo} e {graves_p} alerta(s) grave(s) — candidato a "
                       f"redistribuição de clientes ou reforço.{alvo}")
    if tarefas_sq and med_tp:
        _rank_tp = sorted(((k, tarefas_sq.get(k, 0) / p) for k, p, _d in cap_rows if p),
                          key=lambda x: -x[1])
        _rank_cp = sorted(((k, d["n"] / p) for k, p, d in cap_rows if p), key=lambda x: -x[1])
        if _rank_tp and _rank_cp and _rank_tp[0][0] != _rank_cp[0][0]:
            leitura_cap += (f" Atenção à carga REAL de trabalho: {_rank_tp[0][0]} lidera em tarefas "
                            f"abertas/pessoa ({_rank_tp[0][1]:.0f}) embora {_rank_cp[0][0]} tenha "
                            f"mais contas/pessoa ({_rank_cp[0][1]:.1f}) — tarefas recorrentes fazem "
                            "a carga diferir do tamanho da carteira; use as duas colunas juntas.")

    # ---- 3. atividades em atraso -------------------------------------------
    try:
        from .sources.clickup_activities import _overdue_from_clickup as _atr_fn
    except Exception:  # noqa: BLE001 — sem ClickUp, a seção reporta indisponível
        _atr_fn = None
    atr_sq: dict[str, dict] = {}
    atr_resp: dict[str, dict] = {}
    atr_sem_squad = atr_inativos = atr_inativos_contas = atr_dup = 0
    _atr_vistas: set[str] = set()
    if _atr_fn is not None:
        agora = dt.datetime.now(dt.timezone.utc)
        for s in sorted(scores, key=_ordem_dedup):
            try:
                tasks = _atr_fn(s["name"], agora) or []
            except Exception:  # noqa: BLE001 — conta sem match não derruba a seção
                tasks = []
            if not tasks:
                continue
            if _inativo(s["name"]):
                atr_inativos += len(tasks)
                atr_inativos_contas += 1
                continue
            ineditas = [t for t in tasks if t["url"] not in _atr_vistas]
            atr_dup += len(tasks) - len(ineditas)
            _atr_vistas.update(t["url"] for t in ineditas)
            tasks = ineditas
            if not tasks:
                continue
            sq = A._resolve_squad(s["name"], mirror)
            if sq is None:
                atr_sem_squad += len(tasks)
            else:
                d = atr_sq.setdefault(sq, {"tarefas": 0, "contas": 0, "pior": 0, "itens": []})
                d["tarefas"] += len(tasks)
                d["contas"] += 1
                d["pior"] = max(d["pior"], max(t["dias_atraso"] for t in tasks))
                d["itens"].extend((s["name"], t) for t in tasks)
            for t in tasks:
                for nome in (t.get("responsavel") or "(sem responsável)").split(", "):
                    r = atr_resp.setdefault(nome, {"tarefas": 0, "contas": set(),
                                                   "squads": Counter(), "pior": 0, "itens": []})
                    r["tarefas"] += 1
                    r["contas"].add(s["name"])
                    r["itens"].append((s["name"], t))
                    if sq:
                        r["squads"][sq] += 1
                    r["pior"] = max(r["pior"], t["dias_atraso"])

    cp_by = {k: ((d["n"] / p) if p else None) for k, p, d in cap_rows}
    pess_by = {k: p for k, p, _d in cap_rows}
    apps = [atr_sq.get(k, {}).get("tarefas", 0) / p for k, p, _d in cap_rows if p]
    med_app = (sum(apps) / len(apps)) if apps else None
    r_atr = _pearson([(cp_by[k], atr_sq.get(k, {}).get("tarefas", 0) / p)
                      for k, p, _d in cap_rows if p and cp_by.get(k) is not None])

    def _item(conta, t):
        return {"conta": conta, "tarefa": t.get("nome"), "url": t.get("url"),
                "dias_atraso": t["dias_atraso"], "vence_em": t.get("vence_em"),
                "responsavel": t.get("responsavel")}

    # DIAGNÓSTICO por squad: atraso alto COM carga alta = sobrecarga (falta
    # gente); atraso alto SEM carga alta = ritmo/processo. É a pergunta que a
    # seção existe para responder, e a régua mora aqui, não no HTML.
    # itera TODOS os squads da capacidade (não só os que têm atraso): squad
    # com zero atrasos precisa aparecer na tabela — é informação, não ausência
    atrasos_squad, top_atr = [], None
    n_por_squad = {k: d["n"] for k, d in por_squad.items()}
    for k, _p, _d0 in sorted(cap_rows,
                            key=lambda x: (-atr_sq.get(x[0], {}).get("tarefas", 0), x[0])):
        d = atr_sq.get(k, {"tarefas": 0, "contas": 0, "pior": 0, "itens": []})
        pess = pess_by.get(k) or 0
        app_ = (d["tarefas"] / pess) if pess else None
        cp = cp_by.get(k)
        diag = None
        if app_ is not None and med_app and d["tarefas"] and app_ >= med_app * 1.3:
            diag = ("capacidade" if (cp is not None and med_cp and cp >= med_cp * 1.3)
                    else "ritmo")
        item = {
            "squad": k, "tarefas": d["tarefas"], "contas": d["contas"], "pior": d["pior"],
            "pessoas": pess, "contas_pessoa": cp, "tarefas_pessoa": app_,
            "pct_carteira": (d["contas"] / n_por_squad[k]) if n_por_squad.get(k) else None,
            "diagnostico": diag,
            "itens": [_item(c, t) for c, t in sorted(d["itens"], key=lambda x: -x[1]["dias_atraso"])],
        }
        if top_atr is None and d["tarefas"]:
            top_atr = item
        atrasos_squad.append(item)

    atrasos_resp = [{
        "responsavel": nome, "tarefas": r["tarefas"], "contas": len(r["contas"]),
        "pior": r["pior"],
        "squads": [s for s, _n in r["squads"].most_common(3)],
        # com a CONTAGEM: "B2-S1 (12)" diz de onde vem o atraso da pessoa
        "squads_txt": [f"{s} ({n})" for s, n in r["squads"].most_common(3)],
        "itens": [_item(c, t) for c, t in sorted(r["itens"], key=lambda x: -x[1]["dias_atraso"])],
    } for nome, r in sorted(atr_resp.items(), key=lambda x: -x[1]["tarefas"])]

    # leitura automática dos atrasos: a correlação responde no AGREGADO; o
    # diagnóstico por squad responde caso a caso
    tot_atr = sum(a["tarefas"] for a in atr_sq.values())
    if _atr_fn is None:
        leitura_atr = "ClickUp não configurado — sem dados de atraso nesta visão."
    elif not tot_atr:
        leitura_atr = ("Nenhuma tarefa aberta com vencimento estourado nos squads da planilha — "
                       "carteira em dia.")
    else:
        partes = []
        if top_atr:
            causa = (" — e a carga dele também está acima da média: atraso coerente com SOBRECARGA"
                     if top_atr["diagnostico"] == "capacidade" else
                     " — SEM carga acima da média: aponta para ritmo/processo, não falta de gente"
                     if top_atr["diagnostico"] == "ritmo" else "")
            partes.append(f"{top_atr['squad']} concentra mais atrasos ({top_atr['tarefas']} tarefas "
                          f"em {top_atr['contas']} conta(s)){causa}.")
        if r_atr is not None:
            if r_atr >= 0.5:
                partes.append(f"No agregado, atrasos ACOMPANHAM a carga (correlação {r_atr:.2f} entre "
                              "contas/pessoa e atrasos/pessoa): o quadro geral é de capacidade — "
                              "redistribuição/reforço tende a resolver.")
            elif r_atr <= 0.1:
                partes.append(f"No agregado, atrasos NÃO acompanham a carga (correlação {r_atr:.2f}): "
                              "squads mais carregados não são os que mais atrasam — o problema é de "
                              "ritmo/processo em squads específicos, não de falta de gente.")
            else:
                partes.append(f"Correlação carga × atraso moderada ({r_atr:.2f}): capacidade explica "
                              "parte dos atrasos, mas há squads fora do padrão — olhar o "
                              "diagnóstico de cada linha.")
        sem_resp = atr_resp.get("(sem responsável)", {}).get("tarefas", 0)
        if sem_resp:
            partes.append(f"{sem_resp} tarefa(s) vencida(s) SEM responsável atribuído no ClickUp — "
                          "atraso órfão, ninguém está sendo cobrado por elas.")
        leitura_atr = " ".join(partes)

    return {
        "ranking": ranking, "mrr_risco_total": tot_risco,
        "leitura_atrasos": leitura_atr, "total_atrasos": tot_atr,
        "capacidade": capacidade, "media_contas_pessoa": med_cp,
        "media_tarefas_pessoa": med_tp, "leitura_capacidade": leitura_cap,
        "tem_tarefas": bool(tarefas_sq),
        "atrasos_disponiveis": _atr_fn is not None,
        "atrasos_squad": atrasos_squad, "atrasos_responsavel": atrasos_resp,
        "atrasos_sem_squad": atr_sem_squad,
        "atrasos_inativos": atr_inativos, "atrasos_inativos_contas": atr_inativos_contas,
        "atrasos_duplicados": atr_dup,
        "media_atrasos_pessoa": med_app,
        # correlação carga × atraso: separa SOBRECARGA de RITMO/processo
        "correlacao_carga_atraso": r_atr,
    }
