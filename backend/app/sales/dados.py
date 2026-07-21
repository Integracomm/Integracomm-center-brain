"""Dados PUROS de Pré-vendas e Vendas (redesenho, Lote 2 — 21/07/2026).

Regra do redesenho (aprovada): endpoint EMBRULHA o cálculo existente, nunca
reimplementa. Este módulo extrai as MESMAS queries/fórmulas das telas HTML
de sales/ui.py para funções JSON-able; o check de paridade compara os dois
lados antes de qualquer validação. Réguas oficiais preservadas:
  - Funil = _funil_oficial do Marketing (bate com o dashboard do Pipedrive);
  - Speed = sales_first_touch (1º contato), coorte do período;
  - Win/Loss = perdidos com stage IN (6,5,7) por lost_time.
"""
from __future__ import annotations

import datetime as dt
import statistics as st
from typing import Any

from .ui import _brt, _ST_REUNIAO


def _f(v):
    return float(v) if v is not None else None


# ---------------------------------------------------------------------------
# PRÉ-VENDAS (funil + speed numa página — desenho aprovado do redesenho)
# ---------------------------------------------------------------------------
def pv_dados(conn: Any, ini: dt.date, fim: dt.date) -> dict:
    from ..marketing.ui import _funil_oficial
    from .. import team_config as TC
    a, b = _brt(ini, fim)

    # ---- funil oficial Lead→Booking (mesma régua do dashboard do time) ----
    passou, booked, leads, receita = _funil_oficial(conn, ini, fim)
    rotulos = ["Lead", "MQL", "SAL", "SQL", "Oportunidade", "Booking"]
    vols = [*passou[:5], booked]
    etapas = []
    for i, (rot, v) in enumerate(zip(rotulos, vols)):
        ant = vols[i - 1] if i else None
        etapas.append({"key": rot.lower(), "label": rot, "volume": int(v),
                       "conversao_da_anterior_pct":
                           round(v / ant * 100, 1) if ant else None})
    conv_total = round(booked / leads * 100, 1) if leads else None

    with conn.cursor() as cur:
        # ---- qualidade por origem (lead→reunião) — MESMA query da tela ----
        cur.execute("""
            SELECT COALESCE(d.origem, '(vazio)') AS o, count(DISTINCT d.deal_id) AS leads,
                   count(DISTINCT e.deal_id) AS reunioes
              FROM mkt_deals_attribution d
              LEFT JOIN mkt_stage_events e ON e.deal_id = d.deal_id
                   AND e.stage_id = ANY(%s) AND e.entered_at >= %s AND e.entered_at < %s
             WHERE d.add_time >= %s AND d.add_time < %s
             GROUP BY 1 HAVING count(DISTINCT d.deal_id) >= 5 ORDER BY 2 DESC LIMIT 14""",
            (list(_ST_REUNIAO), a, b, a, b))
        origens = [{"origem": o, "leads": l, "reunioes": r,
                    "taxa_pct": round(r / l * 100, 1) if l else 0.0,
                    "amostra_pequena": l < 8}
                   for o, l, r in cur.fetchall()]

        # ---- dia da semana de chegada × conversão (coorte) ----
        cur.execute("""
            SELECT extract(dow FROM d.add_time AT TIME ZONE 'America/Sao_Paulo')::int,
                   count(*),
                   count(*) FILTER (WHERE EXISTS (SELECT 1 FROM mkt_stage_events e
                                     WHERE e.deal_id = d.deal_id AND e.stage_id = 6))
              FROM mkt_deals_attribution d
             WHERE d.add_time >= %s AND d.add_time < %s GROUP BY 1 ORDER BY 1""", (a, b))
        _dn = {1: "Seg", 2: "Ter", 3: "Qua", 4: "Qui", 5: "Sex", 6: "Sáb", 0: "Dom"}
        ddados = {dow: (n, ag) for dow, n, ag in cur.fetchall()}
        taxas = [(d0, ag / n) for d0, (n, ag) in ddados.items() if n]
        best = max(taxas, key=lambda x: x[1])[0] if taxas else None
        worst = min(taxas, key=lambda x: x[1])[0] if taxas else None
        dias = [{"dia": d0, "dia_label": _dn[d0], "leads": n, "agendaram": ag,
                 "taxa_pct": round(ag / n * 100, 1) if n else None,
                 "best": d0 == best, "worst": d0 == worst}
                for d0 in (1, 2, 3, 4, 5, 6, 0)
                for n, ag in [ddados.get(d0, (0, 0))] if n]

        # ---- motivos de desqualificação (pré-handoff) ----
        cur.execute("""SELECT COALESCE(lost_reason, '(sem motivo)'), count(*)
                         FROM mkt_deals_attribution
                        WHERE add_time >= %s AND add_time < %s AND status='lost'
                          AND stage_id NOT IN (6, 5, 7)
                        GROUP BY 1 ORDER BY 2 DESC LIMIT 10""", (a, b))
        desq = [{"motivo": str(m), "deals": n} for m, n in cur.fetchall()]

        # ---- speed-to-lead (1º contato) ----
        cur.execute("""SELECT d.deal_id, d.add_time, t.first_at, t.quem, d.origem
                         FROM mkt_deals_attribution d
                         LEFT JOIN sales_first_touch t ON t.deal_id = d.deal_id
                        WHERE d.add_time >= %s AND d.add_time < %s""", (a, b))
        rows = cur.fetchall()

        # velocidade × conversão por faixa — MESMA query/faixas da tela
        cur.execute("""
            WITH base AS (
                SELECT d.deal_id,
                       EXTRACT(epoch FROM (t.first_at - d.add_time)) / 60 AS mins,
                       EXISTS (SELECT 1 FROM mkt_stage_events e
                                WHERE e.deal_id = d.deal_id AND e.stage_id = 6) AS agendou
                  FROM mkt_deals_attribution d
                  LEFT JOIN sales_first_touch t ON t.deal_id = d.deal_id
                 WHERE d.add_time >= %s AND d.add_time < %s)
            SELECT CASE WHEN mins IS NULL THEN '6. sem contato registrado'
                        WHEN mins <= 15 THEN '1. até 15 min'
                        WHEN mins <= 60 THEN '2. 15-60 min'
                        WHEN mins <= 240 THEN '3. 1-4 horas'
                        WHEN mins <= 1440 THEN '4. 4-24 horas'
                        ELSE '5. mais de 24 horas' END AS faixa,
                   count(*), count(*) FILTER (WHERE agendou)
              FROM base GROUP BY 1 ORDER BY 1""", (a, b))
        faixas = [{"faixa": f0[3:], "ordem": f0[0], "leads": n, "agendaram": ag,
                   "taxa_pct": round(ag / n * 100, 1) if n else None}
                  for f0, n, ag in cur.fetchall()]

        # tipo de 1º contato × conversão (mín. 5 leads — mesma régua)
        cur.execute("""
            SELECT COALESCE(t.tipo, '(sem registro)'), count(*),
                   count(*) FILTER (WHERE EXISTS (SELECT 1 FROM mkt_stage_events e
                                     WHERE e.deal_id = d.deal_id AND e.stage_id = 6))
              FROM mkt_deals_attribution d
              LEFT JOIN sales_first_touch t ON t.deal_id = d.deal_id
             WHERE d.add_time >= %s AND d.add_time < %s
             GROUP BY 1 HAVING count(*) >= 5 ORDER BY 2 DESC""", (a, b))
        tipos = [{"tipo": str(tp), "leads": n, "agendaram": ag,
                  "taxa_pct": round(ag / n * 100, 1) if n else None}
                 for tp, n, ag in cur.fetchall()]

    mins, por_quem, por_origem_sp = [], {}, {}
    sem_toque = 0
    for _did, add, first, quem, origem in rows:
        if not first:
            sem_toque += 1
            continue
        m = max(0.0, (first - add).total_seconds() / 60)
        mins.append(m)
        if not TC.eh_desligado(conn, "prevendas", quem):
            por_quem.setdefault((quem or "—").strip()[:30], []).append(m)
        por_origem_sp.setdefault((origem or "(vazio)")[:30], []).append(m)

    def _bloco(d):
        return [{"nome": k, "leads": len(v), "mediana_min": round(st.median(v), 1),
                 "pct_15min": round(sum(1 for m in v if m <= 15) / len(v) * 100)}
                for k, v in sorted(d.items(), key=lambda x: st.median(x[1])) if len(v) >= 3]

    razao_15x24 = None
    tx1 = next((x["taxa_pct"] for x in faixas if x["ordem"] == "1"), None)
    tx5 = next((x["taxa_pct"] for x in faixas if x["ordem"] == "5"), None)
    if tx1 and tx5:
        razao_15x24 = round(tx1 / tx5, 1)

    return {
        "periodo": {"ini": ini.isoformat(), "fim": fim.isoformat()},
        "funil": {"etapas": etapas, "conversao_total_pct": conv_total,
                  "receita_bookings": _f(receita)},
        "kpis": {
            "leads": int(leads), "sql": int(passou[3]),
            "taxa_lead_sql_pct": round(passou[3] / leads * 100, 1) if leads else None,
            "speed_mediano_min": round(st.median(mins), 1) if mins else None,
            "pct_15min": round(sum(1 for m in mins if m <= 15) / len(mins) * 100) if mins else None,
            "p75_min": round(st.quantiles(mins, n=4)[2], 1) if len(mins) >= 4 else None,
            "sem_contato": sem_toque,
        },
        "dias": dias, "origens": origens, "desq": desq,
        "sem_motivo_desq": sum(x["deals"] for x in desq if x["motivo"] == "(sem motivo)"),
        "velocidade": {"faixas": faixas, "razao_15min_vs_24h": razao_15x24},
        "tipos_contato": tipos,
        "por_responsavel": _bloco(por_quem), "por_origem_speed": _bloco(por_origem_sp),
        "tem_first_touch": bool(mins),
    }


# ---------------------------------------------------------------------------
# VENDAS · WIN/LOSS (+ heatmaps motivo×bundle e motivo×closer — pedido do
# plano; célula = % das perdas do MOTIVO concentrada na coluna, n junto,
# amostra pequena marcada AQUI — frontend não recalcula)
# ---------------------------------------------------------------------------
def winloss_dados(conn: Any, ini: dt.date, fim: dt.date) -> dict:
    a, b = _brt(ini, fim)
    with conn.cursor() as cur:
        cur.execute("""SELECT COALESCE(lost_reason, '(sem motivo)'), count(*),
                              COALESCE(sum(COALESCE(valor_custom, valor)), 0)
                         FROM mkt_deals_attribution
                        WHERE status='lost' AND lost_time >= %s AND lost_time < %s
                          AND stage_id IN (6, 5, 7)
                        GROUP BY 1 ORDER BY 2 DESC LIMIT 14""", (a, b))
        perdas = [{"motivo": str(m), "deals": n, "mrr_perdido": _f(v)} for m, n, v in cur.fetchall()]

        cur.execute("""SELECT COALESCE(substring(produto FROM 'B[1-5]'),
                              CASE WHEN produto IS NULL OR produto = '' THEN '(sem plano)' ELSE 'outros' END),
                              COALESCE(lost_reason, '(sem motivo)'), count(*),
                              COALESCE(sum(COALESCE(valor_custom, valor)), 0)
                         FROM mkt_deals_attribution
                        WHERE status='lost' AND lost_time >= %s AND lost_time < %s
                          AND stage_id IN (6, 5, 7)
                        GROUP BY 1, 2""", (a, b))
        bundle_rows = cur.fetchall()

        cur.execute("""SELECT COALESCE(lost_reason, '(sem motivo)'), COALESCE(origem, '(vazio)'),
                              COALESCE(owner_name, '—'), count(*)
                         FROM mkt_deals_attribution
                        WHERE status='lost' AND lost_time >= %s AND lost_time < %s
                          AND stage_id IN (6, 5, 7) GROUP BY 1, 2, 3""", (a, b))
        cruz = cur.fetchall()

        cur.execute("""SELECT to_char(date_trunc('month', lost_time - interval '3 hours'), 'MM/YY'),
                              COALESCE(lost_reason, '(sem motivo)'), count(*)
                         FROM mkt_deals_attribution
                        WHERE status='lost' AND lost_time >= date_trunc('month', now()) - interval '5 months'
                          AND stage_id IN (6, 5, 7)
                        GROUP BY date_trunc('month', lost_time - interval '3 hours'), 2
                        ORDER BY date_trunc('month', lost_time - interval '3 hours')""")
        evo = cur.fetchall()

    # win rate NÃO entra aqui de propósito: a tela HTML de Win/Loss não o
    # calcula e inventar uma régua nova violaria a regra do redesenho — a
    # taxa de fechamento oficial vive no Funil de Fechamento (Lote 3).
    tot_perdas = sum(p["deals"] for p in perdas)

    por_bundle: dict[str, list] = {}
    for bnd, m, n, v in bundle_rows:
        por_bundle.setdefault(bnd, []).append({"motivo": str(m), "deals": n, "mrr": _f(v)})
    ordem = ["B1", "B2", "B3", "B4", "B5", "outros", "(sem plano)"]
    cards_bundle = []
    for bnd in [x for x in ordem if x in por_bundle] + sorted(set(por_bundle) - set(ordem)):
        ms = sorted(por_bundle[bnd], key=lambda x: -x["deals"])
        tot_n = sum(x["deals"] for x in ms)
        cards_bundle.append({"bundle": bnd, "perdas": tot_n,
                             "mrr_perdido": sum(x["mrr"] or 0 for x in ms),
                             "motivos": [{**x, "pct": round(x["deals"] / tot_n * 100) if tot_n else 0}
                                         for x in ms[:5]],
                             "outros_motivos": max(0, len(ms) - 5)})

    top_motivos = [p["motivo"] for p in perdas if p["motivo"] != "(sem motivo)"][:5]

    def _heat(dim_idx: int, top_dim: int = 6) -> dict:
        """HeatmapMatrix: célula = % das perdas do MOTIVO (linha) na coluna."""
        agg: dict[str, dict[str, int]] = {}
        tot_dim: dict[str, int] = {}
        tot_motivo: dict[str, int] = {}
        for m, og, ow, n in cruz:
            k = (og, ow)[dim_idx - 1][:24]
            tot_dim[k] = tot_dim.get(k, 0) + n
            if m in top_motivos:
                agg.setdefault(m, {})[k] = agg.setdefault(m, {}).get(k, 0) + n
                tot_motivo[m] = tot_motivo.get(m, 0) + n
        cols = [k for k, _ in sorted(tot_dim.items(), key=lambda x: -x[1])[:top_dim]]
        cells = []
        for m in top_motivos:
            for c in cols:
                n = agg.get(m, {}).get(c)
                if n is None:
                    continue
                tm = tot_motivo.get(m, 0)
                cells.append({"row": m[:36], "col": c, "n": n,
                              "value": round(n / tm * 100) if tm else None,
                              "amostra_pequena": n < 3})
        return {"rows": [m[:36] for m in top_motivos], "cols": cols,
                "cells": cells, "unit": "pct"}

    # evolução 6m por motivo (top 5) — mês corrente é parcial
    meses_evo = list(dict.fromkeys(m for m, _r, _n in evo))
    series = []
    for m in top_motivos:
        vals = {mes: 0 for mes in meses_evo}
        for mes, mm, n in evo:
            if mm == m:
                vals[mes] = n
        series.append({"motivo": m[:36], "valores": [vals[mes] for mes in meses_evo]})

    # diagnóstico dominante — MESMA heurística da tela (determinística, rotulada)
    diag = None
    top = next((p for p in perdas if p["motivo"] != "(sem motivo)"), None)
    if top:
        ml = top["motivo"].lower()
        if any(x in ml for x in ("preço", "preco", "valor", "investimento", "caro")):
            tipo = "ANCORAGEM/PREÇO — revisar apresentação de valor e proposta em Vendas."
        elif any(x in ml for x in ("timing", "futur", "momento", "budget", "verba", "retorno")):
            tipo = "QUALIFICAÇÃO — lead sem prontidão chegando à reunião; devolver critérios à Pré-vendas."
        else:
            tipo = "específico — leia a distribuição por bundle/closer."
        conc = None
        por_closer: dict[str, int] = {}
        for m, _og, ow, n in cruz:
            if m == top["motivo"]:
                por_closer[ow] = por_closer.get(ow, 0) + n
        if por_closer:
            cw, cn = max(por_closer.items(), key=lambda x: x[1])
            if top["deals"] >= 8 and cn / top["deals"] >= 0.5:
                conc = f"{cn} de {top['deals']} casos concentrados em {cw} — componente de treino individual."
        diag = {"motivo": top["motivo"], "deals": top["deals"], "leitura": tipo,
                "concentracao": conc, "fonte": "regras determinísticas"}

    return {
        "periodo": {"ini": ini.isoformat(), "fim": fim.isoformat()},
        "kpis": {"deals_perdidos": tot_perdas,
                 "mrr_perdido": sum(p["mrr_perdido"] or 0 for p in perdas),
                 "motivo_top": (perdas[0]["motivo"] if perdas else None)},
        "motivos_perda": perdas,
        "sem_motivo": sum(p["deals"] for p in perdas if p["motivo"] == "(sem motivo)"),
        "por_bundle": cards_bundle,
        "heatmap_motivo_x_origem": _heat(1),
        "heatmap_motivo_x_closer": _heat(2),
        "evolucao": {"meses": meses_evo, "series": series},
        "diagnostico": diag,
    }
