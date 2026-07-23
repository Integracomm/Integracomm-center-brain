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

    # ---- evolução mensal 6m (mesma régua do _pv_speed: funil oficial
    # retroativo + speed mediano; mediana >7 dias = mês sem coleta -> None)
    evolucao = []
    hoje_e = dt.date.today()
    mes_e = (hoje_e.replace(day=1) - dt.timedelta(days=150)).replace(day=1)
    while mes_e <= hoje_e.replace(day=1):
        prox_e = (mes_e.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        fim_e = min(hoje_e, prox_e - dt.timedelta(days=1))
        pe, _bk, tot_e, _rc = _funil_oficial(conn, mes_e, fim_e)
        ae, be = _brt(mes_e, fim_e)
        with conn.cursor() as cur:
            cur.execute("""SELECT percentile_cont(0.5) WITHIN GROUP
                                  (ORDER BY EXTRACT(epoch FROM t.first_at - d.add_time) / 60)
                             FROM sales_first_touch t JOIN mkt_deals_attribution d ON d.deal_id = t.deal_id
                            WHERE d.add_time >= %s AND d.add_time < %s""", (ae, be))
            sp = cur.fetchone()[0]
        sp_v = float(sp) if sp is not None and float(sp) <= 7 * 24 * 60 else None
        evolucao.append({"mes": mes_e.strftime("%m/%y"), "leads": int(tot_e), "sql": int(pe[3]),
                         "taxa_pct": round(pe[3] / tot_e * 100, 1) if tot_e else None,
                         "speed_min": round(sp_v, 1) if sp_v is not None else None})
        mes_e = prox_e

    # ---- diagnóstico do especialista (mesmas entradas da tela; determinístico)
    from .ui import _entradas
    from . import especialista as ESP
    contato = _entradas(conn, (2, 13), a, b)
    desq_top = next(((x["motivo"], x["deals"]) for x in desq if x["motivo"] != "(sem motivo)"), None)
    diagnostico = {"persona": ESP.PERSONA_PREVENDAS,
                   "itens": ESP.insights_prevendas({
                       "taxa_contato": contato / leads if leads else None,
                       "taxa_agend": passou[3] / leads if leads else None,
                       "desq_top": desq_top})}

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
        "evolucao": evolucao, "diagnostico": diagnostico,
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
        """HeatmapMatrix INVERTIDA (Otávio 21/07): linha = origem/closer,
        coluna = motivo; célula = % das perdas DA LINHA naquele motivo —
        responde 'qual closer/origem perde por quê'."""
        agg: dict[str, dict[str, int]] = {}
        tot_dim: dict[str, int] = {}
        for m, og, ow, n in cruz:
            k = (og, ow)[dim_idx - 1][:24]
            tot_dim[k] = tot_dim.get(k, 0) + n
            if m in top_motivos:
                agg.setdefault(k, {})[m] = agg.setdefault(k, {}).get(m, 0) + n
        rows = [k for k, _ in sorted(tot_dim.items(), key=lambda x: -x[1])[:top_dim]]
        col_full = list(top_motivos)
        def _c(m):  # coluna curta (header) — nome completo vai no tooltip da célula
            return m if len(m) <= 18 else m[:17] + "…"
        cells = []
        for k in rows:
            for m in col_full:
                n = agg.get(k, {}).get(m)
                if n is None:
                    continue
                tk = tot_dim.get(k, 0)
                cells.append({"row": k, "col": _c(m), "col_full": m, "n": n,
                              "value": round(n / tk * 100) if tk else None,
                              "amostra_pequena": n < 3})
        return {"rows": rows, "cols": [_c(m) for m in col_full],
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
        "heatmap_origem_x_motivo": _heat(1),
        "heatmap_closer_x_motivo": _heat(2),
        "evolucao": {"meses": meses_evo, "series": series},
        "diagnostico": diag,
    }


# ---------------------------------------------------------------------------
# VENDAS — Funil de Fechamento (Lote 3, 21/07). Win rate OFICIAL da área =
# Oportunidade→Booking (meta 15%) — régua já existente da tela HTML, é ELA
# que o Win/Loss referencia (decisão: não inventar win rate por lá).
# ---------------------------------------------------------------------------
def vd_funil_dados(conn: Any, ini: dt.date, fim: dt.date) -> dict:
    from ..marketing.ui import _funil_oficial
    from . import especialista as ESP
    from .ui import _entradas
    a, b = _brt(ini, fim)
    reunioes = _entradas(conn, _ST_REUNIAO, a, b, coorte=False)
    with conn.cursor() as cur:
        cur.execute("""SELECT count(*) FROM mkt_deals_attribution
                        WHERE oport_time >= %s AND oport_time < %s""", (a, b))
        negoc = cur.fetchone()[0]
        cur.execute("""SELECT count(*), COALESCE(sum(COALESCE(valor_custom, valor)), 0)
                         FROM mkt_deals_attribution
                        WHERE status='won' AND won_time >= %s AND won_time < %s""", (a, b))
        book, receita = cur.fetchone()
        cur.execute("""
            WITH oport AS (SELECT date_trunc('month', oport_time - interval '3 hours') m, count(*) n
                             FROM mkt_deals_attribution WHERE oport_time IS NOT NULL GROUP BY 1),
                 wins AS (SELECT date_trunc('month', won_time - interval '3 hours') m, count(*) n
                            FROM mkt_deals_attribution WHERE status='won' GROUP BY 1)
            SELECT to_char(o.m, 'MM-YYYY'), o.n, COALESCE(w.n, 0)
              FROM oport o LEFT JOIN wins w ON w.m = o.m
             WHERE o.m >= date_trunc('month', now()) - interval '5 months'
             ORDER BY o.m""")
        tend = cur.fetchall()
        cur.execute("""SELECT count(DISTINCT deal_id) FROM mkt_stage_events
                        WHERE stage_id = 5 AND entered_at >= %s AND entered_at < %s""", (a, b))
        reag = cur.fetchone()[0]
        cur.execute("""
            WITH op AS (
                SELECT COALESCE(substring(d.produto FROM 'B[1-5]'),
                                left(COALESCE(d.produto, '(sem plano)'), 30)) AS bnd,
                       count(*) AS n
                  FROM mkt_deals_attribution d
                 WHERE d.oport_time >= %s AND d.oport_time < %s
                 GROUP BY 1),
                 wn AS (
                SELECT COALESCE(substring(produto FROM 'B[1-5]'),
                                left(COALESCE(produto, '(sem plano)'), 30)) AS bnd, count(*) AS n
                  FROM mkt_deals_attribution
                 WHERE status = 'won' AND won_time >= %s AND won_time < %s GROUP BY 1)
            SELECT COALESCE(op.bnd, wn.bnd), COALESCE(op.n, 0), COALESCE(wn.n, 0)
              FROM op FULL JOIN wn ON wn.bnd = op.bnd
             ORDER BY 2 DESC, 3 DESC""", (a, b, a, b))
        bdados = cur.fetchall()
        cur.execute("""
            WITH wins AS (
                SELECT COALESCE(origem, '(vazio)') o,
                       COALESCE(substring(produto FROM 'B[1-5]'), 'outros') p, count(*) n
                  FROM mkt_deals_attribution
                 WHERE status='won' AND won_time >= %s AND won_time < %s GROUP BY 1, 2),
                 leads AS (
                SELECT COALESCE(origem, '(vazio)') o, count(*) n FROM mkt_deals_attribution
                 WHERE add_time >= %s AND add_time < %s GROUP BY 1)
            SELECT w.o, w.p, w.n, COALESCE(l.n, 0)
              FROM wins w LEFT JOIN leads l ON l.o = w.o""", (a, b, a, b))
        mx: dict[str, dict[str, int]] = {}
        leads_por_origem: dict[str, int] = {}
        for o, p_, n, l in cur.fetchall():
            mx.setdefault(o, {})[p_] = n
            leads_por_origem[o] = l
    conv = book / negoc if negoc else None
    ins = ESP.insights_vendas({"conv_oport_book": conv, "meta_conv": 0.15,
                               "no_show": (reag / reunioes if reunioes else None)})

    # funil oficial Lead→Booking — MESMO shape do pv_dados (o SPA reusa o componente)
    passou, book_of, leads_of, receita_of = _funil_oficial(conn, ini, fim)
    rotulos = ["Lead", "MQL", "SAL", "SQL", "Oportunidade", "Booking"]
    vols = [*passou[:5], book_of]
    etapas = []
    for i, (rot, v) in enumerate(zip(rotulos, vols)):
        ant = vols[i - 1] if i else None
        etapas.append({"key": rot.lower(), "label": rot, "volume": int(v),
                       "conversao_da_anterior_pct":
                           round(v / ant * 100, 1) if ant else None})

    tot_op = sum(o for _bn, o, _w in bdados) or 1
    planos_cols = ["B1", "B2", "B3", "B4", "B5", "outros"]
    linhas_ox = []
    for o in sorted(mx, key=lambda x: -sum(mx[x].values()))[:12]:
        tot_o = sum(mx[o].values())
        l_o = leads_por_origem.get(o, 0)
        linhas_ox.append({"origem": o[:30], "por_plano": {p_: mx[o].get(p_, 0) for p_ in planos_cols},
                          "total": tot_o, "leads": l_o,
                          "tx_lead_booking_pct": round(tot_o / l_o * 100, 1) if l_o else None})

    return {
        "periodo": {"ini": ini.isoformat(), "fim": fim.isoformat()},
        "kpis": {"reunioes": reunioes, "oportunidades": negoc, "bookings": book,
                 "receita": _f(receita),
                 "conv_oport_booking_pct": round(conv * 100, 1) if conv is not None else None,
                 "meta_pct": 15.0},
        "funil": {"etapas": etapas, "leads": int(leads_of), "receita": _f(receita_of),
                  "conversao_total_pct": round(book_of / leads_of * 100, 1) if leads_of else None},
        "por_bundle": [{"bundle": bn, "oportunidades": o,
                        "mix_pct": round(o / tot_op * 100, 1),
                        "bookings": w,
                        "conv_pct": round(w / o * 100, 1) if o else None}
                       for bn, o, w in bdados],
        "origem_x_plano": {"planos": planos_cols, "linhas": linhas_ox},
        "tendencia": [{"mes": m, "oportunidades": o, "bookings": w,
                       "conv_pct": round(w / o * 100, 1) if o else None,
                       "na_meta": (w / o if o else 0) >= 0.15}
                      for m, o, w in tend],
        "diagnostico": {"persona": ESP.PERSONA_VENDAS, "itens": ins,
                        "fonte": "regras determinísticas"},
    }


# ---------------------------------------------------------------------------
# VENDAS — Ponte PV → Vendas (Lote 3): conversão fraca é herdada da
# qualificação ou é do fechamento? Taxa SEMPRE sobre decididas.
# ---------------------------------------------------------------------------
def vd_ponte_dados(conn: Any, ini: dt.date, fim: dt.date) -> dict:
    a, b = _brt(ini, fim)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT d.deal_id, d.status, COALESCE(d.origem, '(vazio)'),
                   COALESCE(d.sdr, '(sem SDR)'),
                   COALESCE(d.owner_name, '—'),
                   EXTRACT(epoch FROM (t.first_at - d.add_time)) / 60,
                   EXTRACT(epoch FROM (d.oport_time - d.add_time)) / 86400
              FROM mkt_deals_attribution d
              LEFT JOIN sales_first_touch t ON t.deal_id = d.deal_id
             WHERE d.oport_time >= %s AND d.oport_time < %s""", (a, b))
        rows = cur.fetchall()

    def agrega(chave):
        seg: dict[str, list[int]] = {}
        for r in rows:
            k = chave(r)
            if k is None:
                continue
            t = seg.setdefault(k, [0, 0, 0])  # ganhas, decididas, total
            if r[1] == "won":
                t[0] += 1; t[1] += 1
            elif r[1] == "lost":
                t[1] += 1
            t[2] += 1
        return seg

    def bloco(seg, ordem=None):
        chaves = ordem or sorted(seg, key=lambda k: -seg[k][2])
        return [{"rotulo": str(k)[:30], "oports": seg[k][2], "fechadas": seg[k][0],
                 "perdidas": seg[k][1] - seg[k][0], "em_aberto": seg[k][2] - seg[k][1],
                 "taxa_pct": round(seg[k][0] / seg[k][1] * 100, 1) if seg[k][1] else None,
                 "amostra_pequena": seg[k][1] < 10}
                for k in chaves if k in seg]

    sla = agrega(lambda r: None if r[5] is None else ("dentro do SLA (≤15 min)" if r[5] <= 15
                                                      else ("15-60 min" if r[5] <= 60 else "acima de 1h")))
    tempo = agrega(lambda r: None if r[6] is None else ("qualificou em ≤2 dias" if r[6] <= 2
                                                        else ("3-7 dias" if r[6] <= 7 else "mais de 7 dias")))
    origem = agrega(lambda r: r[2][:26])
    sdr = agrega(lambda r: r[3][:26])
    closer = agrega(lambda r: r[4][:26])
    origem = {k: v for k, v in sorted(origem.items(), key=lambda x: -x[1][2])[:8]}

    def taxas(seg):
        return [g / dec for g, dec, _t in seg.values() if dec >= 10]
    qual_txs = taxas(sla) + taxas(tempo) + taxas(origem) + taxas(sdr)
    clos_txs = taxas(closer)
    amp_q = (max(qual_txs) - min(qual_txs)) if len(qual_txs) >= 2 else None
    amp_c = (max(clos_txs) - min(clos_txs)) if len(clos_txs) >= 2 else None
    if amp_q is None and amp_c is None:
        leitura = "Amostra ainda pequena para diagnóstico — acumule mais um período."
    elif (amp_q or 0) >= 0.15 and (amp_q or 0) >= (amp_c or 0):
        leitura = (f"O gargalo tem cara de HERANÇA DA QUALIFICAÇÃO: a taxa de fechamento varia "
                   f"{amp_q * 100:.0f} p.p. conforme a qualidade da qualificação recebida (SLA/tempo/origem/SDR), "
                   f"mais do que entre closers ({(amp_c or 0) * 100:.0f} p.p.). Caminho: devolver critérios de "
                   "qualificação à Pré-vendas — priorizar os segmentos que fecham e endurecer o filtro nos que não fecham.")
    elif (amp_c or 0) >= 0.15:
        leitura = (f"O gargalo tem cara de FECHAMENTO: a taxa varia pouco com a qualificação recebida "
                   f"({(amp_q or 0) * 100:.0f} p.p.), mas {amp_c * 100:.0f} p.p. entre closers. Caminho: abordagem/"
                   "ancoragem em Vendas — role-play com quem está acima e revisão de proposta.")
    else:
        leitura = (f"Taxas relativamente UNIFORMES ({(amp_q or 0) * 100:.0f} p.p. por qualificação, "
                   f"{(amp_c or 0) * 100:.0f} p.p. por closer) — o gargalo não está na triagem nem em pessoas "
                   "específicas; olhe preço/proposta (Win/Loss) e volume de topo.")
    tot_g = sum(1 for r in rows if r[1] == "won")
    tot_d = sum(1 for r in rows if r[1] in ("won", "lost"))
    return {
        "periodo": {"ini": ini.isoformat(), "fim": fim.isoformat()},
        "kpis": {"oportunidades": len(rows), "fechadas": tot_g, "decididas": tot_d,
                 "em_aberto": len(rows) - tot_d,
                 "fechamento_pct": round(tot_g / tot_d * 100, 1) if tot_d else None},
        "leitura": {"texto": leitura, "fonte": "regras determinísticas"},
        "por_sla": bloco(sla, ["dentro do SLA (≤15 min)", "15-60 min", "acima de 1h"]),
        "por_tempo_qualificacao": bloco(tempo, ["qualificou em ≤2 dias", "3-7 dias", "mais de 7 dias"]),
        "por_origem": bloco(origem),
        "por_sdr": bloco(sdr),
        "por_closer": bloco(closer),
    }


# ---------------------------------------------------------------------------
# VENDAS — Ciclo & Empacados (Lote 3): distribuição do tempo 1ª reunião →
# contrato + deals abertos sem movimento (>2× a mediana, mín. 14 dias).
# ---------------------------------------------------------------------------
def vd_ciclo_dados(conn: Any, ini: dt.date, fim: dt.date) -> dict:
    from .ui import _ST_VENDAS_ABERTO
    a, b = _brt(ini, fim)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT EXTRACT(epoch FROM d.won_time - min(e.entered_at)) / 86400
              FROM mkt_deals_attribution d JOIN mkt_stage_events e ON e.deal_id = d.deal_id
             WHERE d.status='won' AND d.won_time >= %s AND d.won_time < %s
               AND e.stage_id = ANY(%s)
             GROUP BY d.deal_id, d.won_time""", (a, b, list(_ST_VENDAS_ABERTO)))
        ciclos = [float(r[0]) for r in cur.fetchall() if r[0] is not None and r[0] >= 0]
        cur.execute("""
            SELECT d.deal_id, d.stage_id, COALESCE(d.valor_custom, d.valor) AS valor,
                   d.produto, d.owner_name,
                   EXTRACT(epoch FROM now() - max(e.entered_at)) / 86400 AS dias
              FROM mkt_deals_attribution d JOIN mkt_stage_events e ON e.deal_id = d.deal_id
             WHERE d.status='open' AND d.stage_id IN (6, 5, 7)
             GROUP BY d.deal_id, d.stage_id, COALESCE(d.valor_custom, d.valor), d.produto, d.owner_name""")
        abertos = cur.fetchall()
    med = st.median(ciclos) if ciclos else None
    p25, p75 = (st.quantiles(ciclos, n=4)[0], st.quantiles(ciclos, n=4)[2]) if len(ciclos) >= 4 else (None, None)
    dias_ab = [float(x[5]) for x in abertos if x[5] is not None]
    med_ab = st.median(dias_ab) if dias_ab else 0
    limiar = max(2 * med_ab, 14)
    empacados = sorted([x for x in abertos if x[5] and float(x[5]) > limiar],
                       key=lambda x: -float(x[5]))[:20]
    return {
        "periodo": {"ini": ini.isoformat(), "fim": fim.isoformat()},
        "kpis": {"ciclo_mediano_d": round(med, 1) if med is not None else None,
                 "p25_d": round(p25, 1) if p25 is not None else None,
                 "p75_d": round(p75, 1) if p75 is not None else None,
                 "n_ganhos": len(ciclos), "abertos": len(abertos),
                 "empacados": len(empacados), "limiar_dias": round(limiar, 1)},
        "empacados": [{"deal_id": did, "dono": (own or "—")[:22], "plano": (prod or "—")[:20],
                       "valor": _f(val), "dias": round(float(dias), 0)}
                      for did, _sid, val, prod, own, dias in empacados],
    }


def pv_sdrs_dados(conn: Any, ini: dt.date, fim: dt.date) -> dict:
    """Desempenho individual de PRÉ-VENDAS (Lote 6). Extraído de `_pv_sdrs`
    (sales/ui.py) sem mudar régua nenhuma — o HTML e o SPA passam a ler daqui.

    Régua (a mesma dos gráficos do Pipedrive que a gestão acompanha):
      atribuição = campo SDR do deal, SEM fallback; deal sem o campo cai em
      '(sem SDR definido)'. Leads = deals CRIADOS no período; Oportunidades =
      Dia Oportunidade no período (todos os deals, não é coorte); Bookings =
      won no período. Speed = mediana do 1º contato registrado.
    Desligados (detectados no Pipedrive) NÃO aparecem: os números deles vão
    para a linha agregada '(ex-colaboradores)', para o Total continuar fechando.
    """
    from .. import team_config as TC
    a, b = _brt(ini, fim)
    SEM = "(sem SDR definido)"

    with conn.cursor() as cur:
        cur.execute("""SELECT COALESCE(sdr, %s), count(*)
                         FROM mkt_deals_attribution
                        WHERE add_time >= %s AND add_time < %s GROUP BY 1""", (SEM, a, b))
        leads_por = dict(cur.fetchall())
        cur.execute("""SELECT COALESCE(sdr, %s), count(*)
                         FROM mkt_deals_attribution
                        WHERE oport_time >= %s AND oport_time < %s GROUP BY 1""", (SEM, a, b))
        oport_por = dict(cur.fetchall())
        cur.execute("""SELECT COALESCE(sdr, %s), count(*),
                              COALESCE(sum(COALESCE(valor_custom, valor)), 0)
                         FROM mkt_deals_attribution
                        WHERE status='won' AND won_time >= %s AND won_time < %s GROUP BY 1""",
                    (SEM, a, b))
        book_por = {n: (q, float(v)) for n, q, v in cur.fetchall()}
        cur.execute("""
            SELECT t.quem,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY EXTRACT(epoch FROM t.first_at - d.add_time) / 60)
              FROM sales_first_touch t
              JOIN mkt_deals_attribution d ON d.deal_id = t.deal_id
             WHERE d.add_time >= %s AND d.add_time < %s AND t.quem IS NOT NULL AND t.quem <> ''
             GROUP BY 1""", (a, b))
        speed_por = {TC.norm(q): float(s) for q, s in cur.fetchall() if s is not None}

    nomes = sorted(set(leads_por) | set(oport_por),
                   key=lambda n: (n == SEM, -leads_por.get(n, 0), -oport_por.get(n, 0)))
    pessoas, visiveis = [], []
    total = {"leads": 0, "oport": 0, "book": 0}
    ex = {"leads": 0, "oport": 0, "book": 0}
    fora = {"leads": 0, "oport": 0, "book": 0}
    for nome in nomes[:15]:
        l, o = leads_por.get(nome, 0), oport_por.get(nome, 0)
        bq, _bv = book_por.get(nome, (0, 0.0))
        total["leads"] += l; total["oport"] += o; total["book"] += bq
        if nome != SEM and TC.eh_desligado(conn, "prevendas", nome):
            ex["leads"] += l; ex["oport"] += o; ex["book"] += bq
            continue
        papel = None if nome == SEM else TC.papel_de(conn, "prevendas", nome)
        # quem NÃO é de Pré-vendas não vira linha nem coluna desta tela (Otávio
        # 23/07: Giovana F. é do time de VENDAS e aparecia aqui por ter tocado
        # 1 lead). O número não some — vai para a linha agregada '(fora do time
        # de Pré-vendas)', para o Total continuar fechando, como já era feito
        # com os desligados.
        if nome != SEM and papel is None:
            fora["leads"] += l; fora["oport"] += o; fora["book"] += bq
            continue
        if nome != SEM:
            visiveis.append(nome)
        pessoas.append({
            "nome": nome, "sem_sdr": nome == SEM, "papel": papel,
            # o rótulo do chip acompanha a cor (regra da biblioteca)
            "papel_label": {"coordenacao": "coordenação", "gerencia": "gerência"}.get(papel),
            "leads": l, "oport": o, "taxa": (o / l if l else None),
            "bookings": bq, "speed_min": speed_por.get(TC.norm(nome)),
        })
    total["taxa"] = (total["oport"] / total["leads"]) if total["leads"] else None

    cols = visiveis[:5]  # os estudos cruzados cabem em 5 colunas sem rolar

    # (a) motivos de DESQUALIFICAÇÃO por SDR — perdidos antes do handoff
    with conn.cursor() as cur:
        cur.execute("""SELECT COALESCE(sdr, %s), COALESCE(lost_reason, '(sem motivo)'), count(*)
                         FROM mkt_deals_attribution
                        WHERE add_time >= %s AND add_time < %s AND status='lost'
                          AND stage_id NOT IN (6, 5, 7)
                        GROUP BY 1, 2""", (SEM, a, b))
        desq_por: dict = {}
        for nome, m, n in cur.fetchall():
            desq_por.setdefault(nome, []).append((m, int(n)))
    desqualificacao = []
    for nome in cols:
        motivos = sorted(desq_por.get(nome) or [], key=lambda x: -x[1])
        tot_d = sum(n for _m, n in motivos)
        desqualificacao.append({
            "nome": nome, "total": tot_d, "leads": leads_por.get(nome, 0),
            "motivos": [{"motivo": m, "n": n, "pct": (n / tot_d if tot_d else 0),
                         "sem_motivo": m == "(sem motivo)"} for m, n in motivos[:4]],
        })

    # (b) conversão lead→oportunidade por ORIGEM × SDR (coorte do período)
    with conn.cursor() as cur:
        cur.execute("""SELECT COALESCE(sdr, %s), COALESCE(origem, '(vazio)'), count(*),
                              count(*) FILTER (WHERE oport_time IS NOT NULL)
                         FROM mkt_deals_attribution
                        WHERE add_time >= %s AND add_time < %s GROUP BY 1, 2""", (SEM, a, b))
        ori: dict = {}
        ori_tot: dict = {}
        for nome, og, n, op in cur.fetchall():
            ori.setdefault(og, {})[nome] = (int(n), int(op))
            t = ori_tot.setdefault(og, [0, 0])
            t[0] += int(n); t[1] += int(op)
    origens_top = sorted((og for og, t in ori_tot.items() if t[0] >= 10),
                         key=lambda og: -ori_tot[og][0])[:8]
    origens = []
    for og in origens_top:
        tl_o, to_o = ori_tot[og]
        tx_time = to_o / tl_o if tl_o else 0
        celulas = []
        for nome in cols:
            n, op = ori.get(og, {}).get(nome, (0, 0))
            tx = (op / n) if n else None
            # destaque só com amostra: <8 leads não vira diagnóstico
            tom = None
            if n >= 8 and tx_time:
                tom = "ok" if tx >= tx_time * 1.15 else ("ruim" if tx <= tx_time * 0.7 else None)
            celulas.append({"nome": nome, "n": n, "oport": op, "taxa": tx, "tom": tom,
                            "amostra_pequena": 0 < n < 8})
        origens.append({"origem": og, "leads": tl_o, "oport": to_o,
                        "taxa_time": tx_time, "celulas": celulas})

    # (c) oportunidades por PLANO × SDR
    with conn.cursor() as cur:
        cur.execute("""SELECT COALESCE(sdr, %s),
                              COALESCE(substring(produto FROM 'B[1-5]'),
                                       CASE WHEN produto IS NULL OR produto = '' THEN '(sem plano)' ELSE 'outros' END),
                              count(*)
                         FROM mkt_deals_attribution
                        WHERE oport_time >= %s AND oport_time < %s GROUP BY 1, 2""", (SEM, a, b))
        bnd: dict = {}
        for nome, bd, n in cur.fetchall():
            bnd.setdefault(bd, {})[nome] = int(n)
    ordem_b = [x for x in ("B1", "B2", "B3", "B4", "B5", "outros", "(sem plano)") if x in bnd] \
        + sorted(set(bnd) - {"B1", "B2", "B3", "B4", "B5", "outros", "(sem plano)"})
    tot_sdr_b = {nome: sum(bnd[bd].get(nome, 0) for bd in bnd) for nome in cols}
    planos = [{"plano": bd,
               "celulas": [{"nome": nome, "n": bnd[bd].get(nome, 0),
                            "pct": (bnd[bd].get(nome, 0) / tot_sdr_b[nome]) if tot_sdr_b.get(nome) else 0}
                           for nome in cols]}
              for bd in ordem_b]

    # planos de ação individuais — DETERMINÍSTICOS (especialista.plano_sdr
    # compara com a mediana do time; não é texto de LLM), então entram no
    # payload em vez de ficarem só no HTML. Ordem: maior taxa primeiro.
    from .especialista import plano_sdr, PERSONA_PREVENDAS, COORD_PREVENDAS
    time_stats = [{"nome": x["nome"], "leads": x["leads"], "agendadas": x["oport"],
                   "taxa_agend": x["taxa"], "speed_min": x["speed_min"], "ativo": True}
                  for x in pessoas if x["papel"] == "membro"]
    _desq = {x["nome"]: x["motivos"] for x in desqualificacao}
    acoes_individuais = []
    for pes in sorted(time_stats, key=lambda x: -(x["taxa_agend"] or 0)):
        mot = [m for m in (_desq.get(pes["nome"]) or []) if not m["sem_motivo"]]
        if mot:
            top = max(mot, key=lambda x: x["n"])
            if top["n"] >= 5:
                pes["desq_top"] = (top["motivo"], top["n"])
        pl = plano_sdr(pes, time_stats)
        acoes_individuais.append({"nome": pes["nome"], "fortes": pl["fortes"],
                                  "fracos": pl["fracos"], "acoes": pl["acoes"]})

    return {"ini": ini.isoformat(), "fim": fim.isoformat(),
            "pessoas": pessoas, "total": total,
            "ex_colaboradores": (ex if any(ex.values()) else None),
            "fora_do_time": (fora if any(fora.values()) else None),
            "colunas": cols, "desqualificacao": desqualificacao,
            "origens": origens, "planos": planos,
            "acoes_individuais": acoes_individuais,
            "persona": PERSONA_PREVENDAS, "coordenacao": COORD_PREVENDAS}


def vd_closers_dados(conn: Any, ini: dt.date, fim: dt.date) -> dict:
    """Desempenho individual de VENDAS (Lote 6). Extraído de `_vd_closers`
    (sales/ui.py) sem mudar régua — HTML e SPA leem daqui.

    Régua: atribuição pelo DONO do deal (owner_name). Ticket em MRR — B1 é
    contrato SEMESTRAL pago à vista, então divide por 6 para comparar com os
    mensais (regra do Otávio, reafirmada 14/07); sem isso quem fecha muito B1
    aparecia com "ticket alto" indevidamente. Ciclo = mediana 1ª reunião → won.
    Quem não está na lista do time (ou está desligado) NÃO aparece.
    """
    from .. import team_config as TC
    from .especialista import plano_closer, PERSONA_VENDAS, COORD_VENDAS
    a, b = _brt(ini, fim)

    with conn.cursor() as cur:
        cur.execute("""
            SELECT d.owner_name,
                   count(*) FILTER (WHERE d.oport_time >= %s AND d.oport_time < %s) AS oports,
                   count(*) FILTER (WHERE d.status='won' AND d.won_time >= %s AND d.won_time < %s) AS wins,
                   avg(CASE WHEN substring(d.produto FROM 'B[1-5]') = 'B1'
                            THEN COALESCE(d.valor_custom, d.valor) / 6.0
                            ELSE COALESCE(d.valor_custom, d.valor) END)
                       FILTER (WHERE d.status='won' AND d.won_time >= %s AND d.won_time < %s) AS ticket
              FROM mkt_deals_attribution d
             WHERE d.owner_name IS NOT NULL
             GROUP BY 1""", (a, b, a, b, a, b))
        dados = cur.fetchall()
        cur.execute("""
            SELECT d.owner_name,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY EXTRACT(epoch FROM d.won_time - m.primeiro) / 86400)
              FROM mkt_deals_attribution d
              JOIN (SELECT deal_id, min(entered_at) AS primeiro FROM mkt_stage_events
                     WHERE stage_id IN (6, 5, 7) GROUP BY 1) m ON m.deal_id = d.deal_id
             WHERE d.status='won' AND d.won_time >= %s AND d.won_time < %s
               AND d.won_time > m.primeiro
             GROUP BY 1""", (a, b))
        ciclo_por = {n: float(v) for n, v in cur.fetchall() if v is not None}

    time_stats = []
    for nome, oports, wins, ticket in dados:
        papel = TC.papel_de(conn, "vendas", nome)
        if papel is None or TC.eh_desligado(conn, "vendas", nome):
            continue
        time_stats.append({"nome": nome, "oports": oports or 0, "bookings": wins or 0,
                           "taxa_conv": (wins / oports if oports else None),
                           "ticket": float(ticket) if ticket else None,
                           "ciclo_dias": ciclo_por.get(nome), "perdas_top": None,
                           "papel": papel})
    if not time_stats:
        return {"ini": ini.isoformat(), "fim": fim.isoformat(), "sem_dados": True,
                "pessoas": [], "planos_bundle": [], "horas": [], "colunas": [],
                "acoes_individuais": [], "persona": PERSONA_VENDAS,
                "coordenacao": COORD_VENDAS}

    with conn.cursor() as cur:
        cur.execute("""SELECT owner_name, lost_reason, count(*) FROM mkt_deals_attribution
                        WHERE status='lost' AND lost_time >= %s AND lost_time < %s
                          AND lost_reason IS NOT NULL AND stage_id IN (6, 5, 7)
                        GROUP BY 1, 2 ORDER BY 3 DESC""", (a, b))
        for own, motivo, _n in cur.fetchall():
            for p in time_stats:
                if p["nome"] == own and p["perdas_top"] is None:
                    p["perdas_top"] = motivo

    _LBL = {"coordenacao": "coordenação", "gerencia": "gerência"}
    # ordem: membros primeiro, depois por conversão desc
    pessoas = [dict(p, papel_label=_LBL.get(p["papel"]))
               for p in sorted(time_stats,
                               key=lambda x: (x["papel"] != "membro", -(x["taxa_conv"] or 0)))]
    membros = [p for p in time_stats if p["papel"] == "membro"]
    acoes_individuais = []
    for p in pessoas:
        if p["papel"] != "membro":
            continue
        pl = plano_closer(p, membros)
        acoes_individuais.append({"nome": p["nome"], "fortes": pl["fortes"],
                                  "fracos": pl["fracos"], "acoes": pl["acoes"]})

    cols = [p["nome"] for p in sorted(time_stats,
                                      key=lambda x: (x["papel"] != "membro", -(x["bookings"] or 0)))][:6]

    def _casa(nome_pd: str, col: str) -> bool:
        return TC.norm(col) in TC.norm(nome_pd) or TC.norm(nome_pd) in TC.norm(col)

    # (a) fechamentos por bundle × closer
    with conn.cursor() as cur:
        cur.execute("""SELECT COALESCE(owner_name, '—'),
                              COALESCE(substring(produto FROM 'B[1-5]'),
                                       CASE WHEN produto IS NULL OR produto = '' THEN '(sem plano)' ELSE 'outros' END),
                              count(*)
                         FROM mkt_deals_attribution
                        WHERE status='won' AND won_time >= %s AND won_time < %s GROUP BY 1, 2""",
                    (a, b))
        wb: dict = {}
        for nome, bd, n in cur.fetchall():
            wb.setdefault(bd, {})[nome] = int(n)
    ordem_b = [x for x in ("B1", "B2", "B3", "B4", "B5", "outros", "(sem plano)") if x in wb] \
        + sorted(set(wb) - {"B1", "B2", "B3", "B4", "B5", "outros", "(sem plano)"})
    planos_bundle = [{"plano": bd,
                      "celulas": [{"nome": col,
                                   "n": sum(v for nm, v in wb[bd].items() if _casa(nm, col))}
                                  for col in cols]}
                     for bd in ordem_b]

    # (b) reuniões por closer × hora — 1ª entrada em Negociação (proxy da
    # reunião realizada; o carimbo é a movimentação do card)
    with conn.cursor() as cur:
        cur.execute("""
            WITH primeira AS (
                SELECT e.deal_id, min(e.entered_at) AS entered_at
                  FROM mkt_stage_events e
                 WHERE e.stage_id = 7 AND e.entered_at >= %s AND e.entered_at < %s
                 GROUP BY e.deal_id)
            SELECT COALESCE(d.owner_name, '—'),
                   extract(hour FROM p.entered_at AT TIME ZONE 'America/Sao_Paulo')::int, count(*)
              FROM primeira p JOIN mkt_deals_attribution d ON d.deal_id = p.deal_id
             GROUP BY 1, 2""", (a, b))
        rh: dict = {}
        for nome, h, n in cur.fetchall():
            rh.setdefault(nome, {})[int(h)] = int(n)
    horas_c = list(range(7, 21))
    horas = []
    for col in cols:
        cel: dict = {}
        for nm, hs in rh.items():
            if _casa(nm, col):
                for h, n in hs.items():
                    cel[h] = cel.get(h, 0) + n
        if not cel:
            continue
        tot_c = sum(cel.values())
        pico_h = max(cel.items(), key=lambda x: x[1])[0]
        horas.append({
            "nome": col, "total": tot_c, "pico_hora": pico_h,
            # a escala é da PRÓPRIA linha (compara o padrão, não o volume)
            "celulas": [{"hora": h, "n": cel.get(h, 0),
                         "intensidade": (cel.get(h, 0) / max(cel.values())) if cel else 0,
                         "pico": h == pico_h and cel.get(h, 0) > 0}
                        for h in horas_c],
            "fora": sum(n for h, n in cel.items() if h < 7 or h > 20),
            "amostra_pequena": tot_c < 30,
        })

    return {"ini": ini.isoformat(), "fim": fim.isoformat(), "sem_dados": False,
            "pessoas": pessoas, "colunas": cols, "planos_bundle": planos_bundle,
            "horas": horas, "horas_eixo": horas_c,
            "acoes_individuais": acoes_individuais,
            "persona": PERSONA_VENDAS, "coordenacao": COORD_VENDAS}


def vd_forecast_dados(conn: Any, mes: dt.date) -> dict:
    """Performance & Meta do mês (Lote 6). Extraído de `_vd_forecast`.

    Meta por plano (qtde e R$) × fechado × pacing × o que FALTA FAZER
    (bookings → oportunidades → leads, no ritmo de conversão dos últimos 90d).
    Mês corrente compara contra a fração decorrida; mês passado é meta ×
    realizado fechado. Nenhuma régua nova."""
    import calendar
    hoje = dt.date.today()
    mes = mes.replace(day=1)
    corrente = (mes == hoje.replace(day=1))
    prox = (mes.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    fim_mes = min(hoje, prox - dt.timedelta(days=1)) if corrente else (prox - dt.timedelta(days=1))
    a, b = _brt(mes, fim_mes)
    a90, _b90 = _brt(hoje - dt.timedelta(days=90), hoje)
    frac = min(1.0, hoje.day / calendar.monthrange(mes.year, mes.month)[1]) if corrente else 1.0

    with conn.cursor() as cur:
        cur.execute("SELECT plano, meta_qtde, meta_valor FROM mkt_goals WHERE mes=%s AND plano <> 'total'", (mes,))
        metas = {p_: (float(q or 0), float(v or 0)) for p_, q, v in cur.fetchall()}
        cur.execute("""SELECT COALESCE(substring(produto FROM 'B[1-5]'), 'outros'),
                              count(*), COALESCE(sum(COALESCE(valor_custom, valor)), 0)
                         FROM mkt_deals_attribution
                        WHERE status='won' AND won_time >= %s AND won_time < %s GROUP BY 1""", (a, b))
        feito = {p_: (int(n), float(v)) for p_, n, v in cur.fetchall()}
        cur.execute("""SELECT COALESCE(substring(produto FROM 'B[1-5]'), 'outros'), count(*)
                         FROM mkt_deals_attribution WHERE status='open' AND stage_id IN (6, 5, 7)
                        GROUP BY 1""")
        pipe = {k: int(v) for k, v in cur.fetchall()}
        cur.execute("SELECT count(*) FROM mkt_deals_attribution WHERE oport_time >= %s", (a90,))
        oport90 = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM mkt_deals_attribution WHERE status='won' AND won_time >= %s", (a90,))
        win90 = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM mkt_deals_attribution WHERE add_time >= %s", (a90,))
        leads90 = cur.fetchone()[0]
        cur.execute("SELECT DISTINCT mes FROM mkt_goals ORDER BY mes")
        meses_opts = [m.isoformat() for (m,) in cur.fetchall()]
    conv90 = win90 / oport90 if oport90 else 0
    conv_lead90 = win90 / leads90 if leads90 else 0

    linhas, faltantes = [], []
    tot = {"meta_q": 0.0, "meta_v": 0.0, "real_q": 0, "real_v": 0.0,
           "gap": 0.0, "oport": 0.0, "leads": 0.0}
    for plano in ("B1", "B2", "B3", "B4", "B5"):
        meta_q, meta_v = metas.get(plano, (0.0, 0.0))
        real_q, real_v = feito.get(plano, (0, 0.0))
        aberto = pipe.get(plano, 0)
        pct = (real_q / meta_q) if meta_q else None
        gap = max(0.0, meta_q - real_q)
        oport_nec = (gap / conv90) if conv90 else None
        leads_nec = (gap / conv_lead90) if conv_lead90 else None
        tot["meta_q"] += meta_q; tot["meta_v"] += meta_v
        tot["real_q"] += real_q; tot["real_v"] += real_v; tot["gap"] += gap
        if oport_nec:
            tot["oport"] += oport_nec
        if leads_nec:
            tot["leads"] += leads_nec
        if gap and meta_q:
            faltantes.append({"plano": plano, "gap": gap, "oport_nec": oport_nec,
                              "pipeline": aberto,
                              # o pipeline atual cobre o gap se converter no ritmo?
                              "suficiente": (aberto >= oport_nec) if oport_nec is not None else None})
        linhas.append({"plano": plano, "meta_q": meta_q, "meta_v": meta_v,
                       "real_q": real_q, "real_v": real_v, "pct": pct, "gap": gap,
                       "pipeline": aberto, "oport_nec": oport_nec,
                       "no_ritmo": (pct is not None and pct >= frac),
                       # B3-B5 = prioridade da empresa, destacados na tabela
                       "prioritario": plano in ("B3", "B4", "B5")})
    tot["pct"] = (tot["real_q"] / tot["meta_q"]) if tot["meta_q"] else None
    tot["pipeline"] = sum(pipe.get(p_, 0) for p_ in ("B1", "B2", "B3", "B4", "B5"))
    tot["no_ritmo"] = (tot["pct"] is not None and tot["pct"] >= frac)

    return {"mes": mes.isoformat(), "corrente": corrente, "frac": frac,
            "conv90": conv90, "conv_lead90": conv_lead90,
            "linhas": linhas, "total": tot,
            "faltantes": sorted(faltantes, key=lambda x: -x["gap"]),
            "meses_disponiveis": meses_opts}


def vd_horarios_dados(conn: Any, ini: dt.date, fim: dt.date, bundle: str = "todos") -> dict:
    """Melhor Horário de VENDAS (Lote 6). Extraído de `_vd_horarios`.

    Base: 1ª entrada do deal em Negociação (stage 7) — o card é movido depois
    da reunião, então o carimbo é o PROXY de quando ela aconteceu.

    TAXA = ganhas ÷ DECIDIDAS (won+lost) da PRÓPRIA coorte: deal ainda aberto
    não derruba a taxa. É por isso que ela difere da taxa do funil, que divide
    bookings do mês por oportunidades do mês misturando coortes (14/07 — o
    9,1% sobre o total confundia com os 15,2% do funil)."""
    a, b = _brt(ini, fim)
    filtro_b, args = "", [a, b]
    if bundle in ("B1", "B2", "B3", "B4", "B5"):
        filtro_b = " AND substring(d.produto FROM 'B[1-5]') = %s"
        args.append(bundle)
    with conn.cursor() as cur:
        cur.execute(f"""
            WITH primeira AS (
                SELECT e.deal_id, min(e.entered_at) AS entered_at
                  FROM mkt_stage_events e
                  JOIN mkt_deals_attribution d ON d.deal_id = e.deal_id
                 WHERE e.stage_id = 7 AND e.entered_at >= %s AND e.entered_at < %s{filtro_b}
                 GROUP BY e.deal_id)
            SELECT extract(dow  FROM p.entered_at AT TIME ZONE 'America/Sao_Paulo')::int,
                   extract(hour FROM p.entered_at AT TIME ZONE 'America/Sao_Paulo')::int,
                   count(*), count(*) FILTER (WHERE d.status = 'won'),
                   count(*) FILTER (WHERE d.status = 'lost')
              FROM primeira p JOIN mkt_deals_attribution d ON d.deal_id = p.deal_id
             GROUP BY 1, 2""", args)
        celulas = {(int(dow), int(h)): (int(n), int(w), int(lo))
                   for dow, h, n, w, lo in cur.fetchall()}
    total = sum(n for n, _w, _lo in celulas.values())
    if not total:
        return {"ini": ini.isoformat(), "fim": fim.isoformat(), "bundle": bundle,
                "sem_dados": True, "celulas": [], "dows": [], "horas": [],
                "por_hora": [], "kpis": {}}

    total_w = sum(w for _n, w, _lo in celulas.values())
    total_lo = sum(lo for _n, _w, lo in celulas.values())
    dows = [1, 2, 3, 4, 5] + ([6] if any(d == 6 for d, _ in celulas) else []) \
        + ([0] if any(d == 0 for d, _ in celulas) else [])
    hs = sorted({h for _, h in celulas})
    horas = list(range(min(hs), max(hs) + 1))

    grade = []
    for (d_, h), (n, w, lo) in celulas.items():
        if d_ not in dows:
            continue
        dec = w + lo
        grade.append({"dow": d_, "hora": h, "n": n, "won": w, "lost": lo,
                      "abertas": n - dec,
                      "taxa": (w / dec) if dec else None})

    por_hora_map: dict = {}
    for (_d, h), (n, w, lo) in celulas.items():
        t = por_hora_map.setdefault(h, [0, 0, 0])
        t[0] += n; t[1] += w; t[2] += lo
    por_hora, melhores = [], []
    for h in sorted(por_hora_map):
        n, w, lo = por_hora_map[h]
        dec = w + lo
        tx = (w / dec) if dec else None
        # só hora com 15+ DECIDIDAS concorre a "melhor" — abaixo disso é ruído
        if dec >= 15:
            melhores.append((tx or 0, h, dec))
        por_hora.append({"hora": h, "reunioes": n, "won": w, "lost": lo,
                         "abertas": n - dec, "taxa": tx,
                         "amostra_pequena": dec < 15})
    melhores.sort(key=lambda x: -x[0])
    decididas = total_w + total_lo

    return {"ini": ini.isoformat(), "fim": fim.isoformat(), "bundle": bundle,
            "sem_dados": False, "celulas": grade, "dows": dows, "horas": horas,
            "por_hora": por_hora,
            "kpis": {"reunioes": total, "won": total_w, "lost": total_lo,
                     "decididas": decididas, "abertas": total - decididas,
                     "taxa": (total_w / decididas) if decididas else None,
                     "melhor_hora": (melhores[0][1] if melhores else None),
                     "melhor_taxa": (melhores[0][0] if melhores else None),
                     "melhor_dec": (melhores[0][2] if melhores else None)}}
