"""Dados PUROS de Marketing (redesenho, Lote 3 — 21/07/2026).

Regra do redesenho (aprovada): endpoint EMBRULHA o cálculo existente, nunca
reimplementa. Canais/Origens já tinham compute puro em analysis.py
(ranking_canais / funil_por_origem) — aqui só se acrescenta o que a tela HTML
calcula inline (variação vs período anterior, evolução mensal da mídia paga,
mediana e chips escalar?/revisar) com as MESMAS queries/regras.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from . import analysis as AN


def _f(v):
    return float(v) if v is not None else None


def mkt_canais_dados(conn: Any, ini: dt.date, fim: dt.date) -> dict:
    dias = (fim - ini).days + 1
    prev = AN.ranking_canais(conn, ini - dt.timedelta(days=dias), ini - dt.timedelta(days=1))
    prev_map = {r["canal"]: r for r in prev}
    rk = AN.ranking_canais(conn, ini, fim)
    canais = []
    for r in rk:
        p = prev_map.get(r["canal"], {})
        var = (round((r["leads"] - p["leads"]) / p["leads"] * 100, 0)
               if p.get("leads") else None)
        canais.append({"canal": r["canal"], "gasto": _f(r["gasto"]), "leads": r["leads"],
                       "var_leads_pct": var, "cpl": _f(r["cpl"]),
                       "conv_lead_oport_pct": round(r["conv_lead_oport"] * 100, 1) if r["conv_lead_oport"] is not None else None,
                       "bookings": r["bookings"],
                       "conv_lead_book_pct": round(r["conv_lead_book"] * 100, 1) if r["conv_lead_book"] is not None else None,
                       "receita": _f(r["receita"]), "cac": _f(r["cac"]),
                       "roas": _f(r["roas"])})

    # evolução mensal (6m) dos canais PAGOS: leads, CPL, CAC — MESMAS queries da tela
    with conn.cursor() as cur:
        cur.execute("""SELECT to_char(date_trunc('month', add_time - interval '3 hours'), 'MM/YY'),
                              origem, count(*), count(*) FILTER (WHERE status='won')
                         FROM mkt_deals_attribution
                        WHERE add_time >= date_trunc('month', now()) - interval '5 months'
                        GROUP BY date_trunc('month', add_time - interval '3 hours'), origem
                        ORDER BY date_trunc('month', add_time - interval '3 hours')""")
        ml: dict[str, dict[str, list[int]]] = {}
        meses_seq: list[str] = []
        for mes, og, n, w in cur.fetchall():
            if mes not in meses_seq:
                meses_seq.append(mes)
            c = AN.canal_de(og)
            t = ml.setdefault(c, {}).setdefault(mes, [0, 0])
            t[0] += n; t[1] += w
        cur.execute("""SELECT to_char(date_trunc('month', date), 'MM/YY'), canal, sum(spend)
                         FROM mkt_insights_daily
                        WHERE date >= date_trunc('month', now()) - interval '5 months'
                        GROUP BY 1, 2""")
        gasto_m = {(("Meta Ads" if cn == "meta" else "Google Ads"), mes): float(s)
                   for mes, cn, s in cur.fetchall()}
    evolucao = []
    for canal in ("Meta Ads", "Google Ads"):
        meses = []
        for mes in meses_seq:
            n, w = (ml.get(canal, {}).get(mes) or [0, 0])
            g = gasto_m.get((canal, mes))
            meses.append({"mes": mes, "leads": n,
                          "cpl": round(g / n, 0) if g and n else None,
                          "cac": round(g / w, 0) if g and w else None})
        evolucao.append({"canal": canal, "meses": meses})

    return {"periodo": {"ini": ini.isoformat(), "fim": fim.isoformat(),
                        "dias": dias},
            "canais": canais, "meses": meses_seq, "evolucao": evolucao}


def _origem_paga(origem) -> bool:
    return AN.canal_de(origem) in ("Meta Ads", "Google Ads")


def mkt_origens_dados(conn: Any, ini: dt.date, fim: dt.date,
                      midia: str = "todas", origem: str | None = None) -> dict:
    if midia not in ("todas", "pagas", "organicas"):
        midia = "todas"
    if origem:
        detalhe = [{"campanha": str(r["utm_campaign"] or "—")[:48],
                    "criativo": str(r["utm_content"] or "—")[:40],
                    "leads": r["leads"], "oport": r["oport"], "bookings": r["bookings"],
                    "receita": _f(r["receita"])}
                   for r in AN.funil_por_origem(conn, ini, fim, origem)]
        return {"periodo": {"ini": ini.isoformat(), "fim": fim.isoformat()},
                "origem": origem, "midia": midia, "detalhe": detalhe}
    dados = AN.funil_por_origem(conn, ini, fim)
    if midia == "pagas":
        dados = [r for r in dados if _origem_paga(r["origem"])]
    elif midia == "organicas":
        dados = [r for r in dados if not _origem_paga(r["origem"])]
    # chips escalar?/revisar — MESMAS regras da tela (mediana das origens 20+)
    med_conv = [(r["bookings"] / r["leads"]) for r in dados if r["leads"] >= 20]
    med = sorted(med_conv)[len(med_conv) // 2] if med_conv else 0
    linhas = []
    for r in dados:
        conv = r["bookings"] / r["leads"] if r["leads"] else 0
        oport_pct = r["oport"] / r["leads"] if r["leads"] else 0
        tag = None
        if r["leads"] >= 20 and conv > med * 1.5 and r["leads"] < 200:
            tag = "escalar?"
        elif r["leads"] >= 200 and conv < med * 0.5:
            tag = "revisar"
        linhas.append({"origem": str(r["origem"] or "(vazio)"), "tag": tag,
                       "leads": r["leads"], "oport": r["oport"],
                       "oport_pct": round(oport_pct * 100, 1),
                       "bookings": r["bookings"], "conv_pct": round(conv * 100, 1),
                       "receita": _f(r["receita"])})
    return {"periodo": {"ini": ini.isoformat(), "fim": fim.isoformat()},
            "origem": None, "midia": midia,
            "totais": {"leads": sum(r["leads"] for r in dados),
                       "bookings": sum(r["bookings"] for r in dados)},
            "linhas": linhas}


# ---------------------------------------------------------------------------
# LOTE 4 (22/07) — as 8 views pesadas. Mesmas queries/réguas das telas HTML;
# blocos compartilhados REUSADOS (_funil_oficial, _plan_funil, _ciclo_coorte,
# ranking_canais, lag_por_campanha) — nada recalculado por fora.
# ---------------------------------------------------------------------------
def _pct(v, nd=1):
    return round(v * 100, nd) if v is not None else None


def mkt_visao_dados(conn: Any) -> dict:
    from .ui import (_ETAPAS_PLANO, _dias_mes, _funil_oficial, _mes_anterior,
                     _mes_atual, _plan_funil)
    ini, fim = _mes_atual()
    ini_p, fim_p = _mes_anterior()
    atual = AN.ranking_canais(conn, ini, fim)
    prev = AN.ranking_canais(conn, ini_p, fim_p)

    def tot(rows, k):
        return sum(r[k] or 0 for r in rows)

    def kpi(label, a, p, kind="num", inverso=False):
        var = round((a - p) / p * 100, 0) if p else None
        return {"label": label, "valor": _f(a), "kind": kind, "var_pct": var,
                "inverso": inverso}
    g_a, g_p = tot(atual, "gasto"), tot(prev, "gasto")
    l_a, l_p = tot(atual, "leads"), tot(prev, "leads")
    b_a, b_p = tot(atual, "bookings"), tot(prev, "bookings")
    o_a, o_p = tot(atual, "oportunidades"), tot(prev, "oportunidades")
    kpis = [kpi("Gasto (mídia)", g_a, g_p, "brl", True), kpi("Leads", l_a, l_p),
            kpi("CPL", g_a / l_a if l_a else None, g_p / l_p if l_p else None, "brl", True),
            kpi("Oportunidades", o_a, o_p), kpi("Bookings", b_a, b_p),
            kpi("CAC", g_a / b_a if b_a else None, g_p / b_p if b_p else None, "brl", True)]

    # funil do mês vs meta (mesma régua de _funil_vs_meta)
    mes_ref = ini.replace(day=1)
    plan = _plan_funil(conn, [mes_ref]).get(mes_ref) or {}
    funil_meta = None
    if any((v.get("qtde") is not None) for v in plan.values()):
        passou, booked, _t, _r = _funil_oficial(conn, ini, fim)
        reais = passou + [booked]
        frac = min(1.0, ((fim - ini).days + 1) / _dias_mes(mes_ref))
        etapas = [{"etapa": e, "real": reais[i], "meta": (plan.get(e) or {}).get("qtde"),
                   "pct_meta": _pct(reais[i] / (plan.get(e) or {}).get("qtde"))
                   if (plan.get(e) or {}).get("qtde") else None}
                  for i, e in enumerate(_ETAPAS_PLANO)
                  if (plan.get(e) or {}).get("qtde") is not None]
        if etapas:
            funil_meta = {"mes": mes_ref.strftime("%m-%Y"), "ritmo_pct": _pct(frac, 0),
                          "etapas": etapas}

    with conn.cursor() as cur:
        cur.execute("SELECT plano, meta_qtde, meta_valor FROM mkt_goals WHERE mes=%s", (mes_ref,))
        metas = {p: (q, v) for p, q, v in cur.fetchall()}
        cur.execute("""SELECT COALESCE(substring(produto FROM 'B[1-5]'), 'outros') AS plano, count(*)
                         FROM mkt_deals_attribution
                        WHERE status='won' AND won_time >= %s GROUP BY 1""", (mes_ref,))
        feito = dict(cur.fetchall())
    conv = (b_a / l_a) if l_a else None
    progresso, gap = [], []
    for plano in ("B1", "B2", "B3", "B4", "B5"):
        meta_q = metas.get(plano, (None, None))[0]
        if meta_q is None:
            continue
        real = feito.get(plano, 0)
        progresso.append({"plano": plano, "real": real, "meta": float(meta_q),
                          "pct": _pct(real / meta_q) if meta_q else None,
                          "destaque": plano in ("B3", "B4", "B5")})
        falta = max(0, (meta_q or 0) - real)
        if falta and plano in ("B3", "B4", "B5") and conv:
            gap.append({"plano": plano, "faltam_bookings": float(falta),
                        "leads_necessarios": round(falta / conv)})
    return {"periodo": {"ini": ini.isoformat(), "fim": fim.isoformat()},
            "kpis": kpis, "funil_vs_meta": funil_meta, "progresso": progresso,
            "gap": gap, "conv_lead_booking_pct": _pct(conv)}


def mkt_metas_dados(conn: Any) -> dict:
    from ..sources.mkt_plan_sheet import ANO
    from .ui import (_CANAIS_LBL, _CANAIS_PLANO, _CANAIS_SQL, _ETAPAS_PLANO,
                     _MES_ABREV, _dias_mes, _funil_oficial, _plan_funil)
    hoje = dt.date.today()
    meses = [dt.date(ANO, m, 1) for m in range(7, 13)]
    plan = _plan_funil(conn, meses)
    if not plan:
        return {"sem_plano": True, "ano": ANO}
    mes_atual = hoje.replace(day=1)
    with conn.cursor() as cur:
        cur.execute("""SELECT date_trunc('month', date)::date, sum(spend)
                         FROM mkt_insights_daily WHERE date >= %s GROUP BY 1""", (meses[0],))
        gasto_mes = {m: float(s) for m, s in cur.fetchall()}
        cur.execute("SELECT mes, canal, meta_oport, verba FROM mkt_plan_channels WHERE mes = ANY(%s)", (meses,))
        plan_canais = {(m, c): (float(q) if q is not None else None,
                                float(v) if v is not None else None)
                       for m, c, q, v in cur.fetchall()}
    reais: dict[dt.date, list[int]] = {}
    for mes in meses:
        if mes > mes_atual:
            continue
        fim_m = min(hoje, mes.replace(day=_dias_mes(mes)))
        passou, booked, _t, _r = _funil_oficial(conn, mes, fim_m)
        reais[mes] = passou + [booked]

    frac_atual = min(1.0, hoje.day / _dias_mes(mes_atual))
    kpis = []
    if mes_atual in plan and mes_atual in reais:
        p, r = plan[mes_atual], reais[mes_atual]

        def kpi_meta(label, real, meta, kind="num", inverso=False):
            if meta is None or real is None:
                return
            kpis.append({"label": label, "real": _f(real), "meta": _f(meta), "kind": kind,
                         "pct": _pct(real / meta) if meta else None, "inverso": inverso})
        kpi_meta("Leads no mês", r[0], (p.get("Lead") or {}).get("qtde"))
        kpi_meta("SQLs", r[3], (p.get("SQL") or {}).get("qtde"))
        kpi_meta("Oportunidades", r[4], (p.get("Oportunidade") or {}).get("qtde"))
        kpi_meta("Bookings", r[5], (p.get("Booking") or {}).get("qtde"))
        g = gasto_mes.get(mes_atual)
        if g and r[0]:
            kpi_meta("CPL do mês", g / r[0], (p.get("Lead") or {}).get("custo"), "brl", True)
        verba_meta = (plan_canais.get((mes_atual, "META")) or (None, None))[1]
        if g is not None and verba_meta:
            kpi_meta("Gasto mídia", g, verba_meta, "brl", True)

    grade = []
    for mes in meses:
        cels = []
        for i, e in enumerate(_ETAPAS_PLANO):
            meta = (plan.get(mes, {}).get(e) or {}).get("qtde")
            real = reais[mes][i] if mes in reais else None
            frac_m = (min(1.0, ((min(hoje, mes.replace(day=_dias_mes(mes))) - mes).days + 1)
                          / _dias_mes(mes)) if mes in reais else None)
            cels.append({"etapa": e, "real": real, "meta": _f(meta),
                         "pct": _pct(real / meta) if (real is not None and meta) else None,
                         "ritmo_pct": _pct(frac_m, 0) if frac_m is not None else None})
        grade.append({"mes": _MES_ABREV[mes.month], "atual": mes == mes_atual, "cels": cels})
    h2 = {"real": sum(r[5] for r in reais.values()),
          "meta": sum((plan.get(m, {}).get("Booking") or {}).get("qtde") or 0 for m in meses)}

    custos = []
    if mes_atual in plan and mes_atual in reais and gasto_mes.get(mes_atual):
        g = gasto_mes[mes_atual]
        for i, etapa in enumerate(_ETAPAS_PLANO[:5]):
            alvo = (plan[mes_atual].get(etapa) or {}).get("custo")
            vol = reais[mes_atual][i]
            if alvo is None:
                continue
            real_c = g / vol if vol else None
            custos.append({"etapa": etapa, "volume": vol, "alvo": _f(alvo), "real": _f(real_c),
                           "var_pct": round((real_c - alvo) / alvo * 100, 0) if real_c is not None else None})

    invest = []
    for mes in meses:
        p = plan.get(mes, {})
        inv = (p.get("Lead") or {}).get("inv")
        invest.append({"mes": _MES_ABREV[mes.month],
                       "meta_leads": _f((p.get("Lead") or {}).get("qtde")),
                       "investimento": _f(inv),
                       "verba": (plan_canais.get((mes, "META")) or (None, None))[1],
                       "gasto": gasto_mes.get(mes),
                       "cobertura_pct": _pct(gasto_mes[mes] / inv) if gasto_mes.get(mes) is not None and inv else None})

    reais_canal = {}
    if mes_atual in reais:
        with conn.cursor() as cur:
            for canal, cond in _CANAIS_SQL.items():
                cur.execute(f"""SELECT count(*) FROM mkt_deals_attribution
                                 WHERE oport_time >= %s AND oport_time < %s AND {cond}""",
                            (f"{mes_atual} 00:00-03", f"{hoje + dt.timedelta(days=1)} 00:00-03"))
                reais_canal[canal] = cur.fetchone()[0] or 0
    canais = []
    for canal in _CANAIS_PLANO:
        metas_m = [{"mes": _MES_ABREV[m.month],
                    "meta": (plan_canais.get((m, canal)) or (None, None))[0],
                    "verba": (plan_canais.get((m, canal)) or (None, None))[1]} for m in meses]
        meta_m = (plan_canais.get((mes_atual, canal)) or (None, None))[0]
        real = reais_canal.get(canal)
        canais.append({"canal": _CANAIS_LBL[canal], "total": canal == "TOTAL", "meses": metas_m,
                       "real_mes": real,
                       "no_ritmo": (real / meta_m >= frac_atual) if (real is not None and meta_m) else None})
    return {"ano": ANO, "sem_plano": False, "mes_atual": _MES_ABREV[mes_atual.month],
            "ritmo_pct": _pct(frac_atual, 0), "kpis": kpis,
            "meses": [_MES_ABREV[m.month] for m in meses], "grade": grade, "h2": h2,
            "custos": custos, "investimento": invest, "canais": canais}


def mkt_funil_dados(conn: Any, ini: dt.date, fim: dt.date) -> dict:
    from .ui import (_FUNIL_DEFS, _FUNIL_ETAPAS, _FUNIL_SUGESTOES,
                     _funil_oficial, _plan_funil)
    dias = (fim - ini).days + 1
    ini_p, fim_p = ini - dt.timedelta(days=dias), ini - dt.timedelta(days=1)
    passou, booked, total, receita_book = _funil_oficial(conn, ini, fim)
    passou_p, booked_p, _tp, _rp = _funil_oficial(conn, ini_p, fim_p)
    mes_ref = fim.replace(day=1)
    with conn.cursor() as cur:
        cur.execute("SELECT COALESCE(sum(meta_qtde),0) FROM mkt_goals WHERE mes=%s AND plano<>'total'",
                    (mes_ref,))
        meta_book = float(cur.fetchone()[0] or 0)
        cur.execute("SELECT etapa, taxa_meta FROM mkt_funnel_goals WHERE mes=%s", (mes_ref,))
        metas_taxa = {e: float(t) for e, t in cur.fetchall()}
    plan_mes = _plan_funil(conn, [mes_ref]).get(mes_ref) or {}
    conv_atual = booked / total if total else 0
    conv_nec = (meta_book / total) if total and meta_book else None
    mql_n = passou[1]
    taxa_mb = booked / mql_n if mql_n else None
    meta_mb = metas_taxa.get("MQL→Booking")

    etapas, pior, pior_taxa = [], None, 1.0
    for i, (nome, _) in enumerate(_FUNIL_ETAPAS):
        n = passou[i]
        taxa = n / passou[i - 1] if i and passou[i - 1] else None
        taxa_p = (passou_p[i] / passou_p[i - 1]) if i and passou_p[i - 1] else None
        meta_e = metas_taxa.get(nome)
        if taxa is not None and meta_e is not None and taxa < meta_e and passou[i - 1] >= 20 and (taxa / meta_e) < pior_taxa:
            pior, pior_taxa = nome, taxa
        elif taxa is not None and not metas_taxa and taxa < pior_taxa and passou[i - 1] >= 20:
            pior, pior_taxa = nome, taxa
        etapas.append({"etapa": nome, "definicao": _FUNIL_DEFS.get(nome, ""), "n": n,
                       "meta_qtde": _f((plan_mes.get(nome) or {}).get("qtde")),
                       "taxa_pct": _pct(taxa), "delta_pp": round((taxa - taxa_p) * 100, 1)
                       if (taxa is not None and taxa_p) else None,
                       "meta_taxa_pct": _pct(meta_e),
                       "conversao_da_anterior_pct": _pct(taxa)})
    taxa_final = booked / passou[4] if passou[4] else None
    etapas.append({"etapa": "Booking (won)", "definicao": _FUNIL_DEFS.get("Booking", ""),
                   "n": booked, "meta_qtde": _f((plan_mes.get("Booking") or {}).get("qtde")),
                   "taxa_pct": _pct(taxa_final), "delta_pp": None,
                   "meta_taxa_pct": _pct(metas_taxa.get("Booking")),
                   "conversao_da_anterior_pct": _pct(taxa_final)})

    sugestoes = []
    if conv_nec is not None and conv_atual < conv_nec:
        if pior and pior in _FUNIL_SUGESTOES:
            sugestoes.append(f"Maior perda: {pior} ({pior_taxa * 100:.1f}%) — {_FUNIL_SUGESTOES[pior]}")
        if conv_atual:
            deficit = (conv_nec / conv_atual - 1) * 100
            sugestoes.append(
                f"Para a meta no volume atual, a conversão precisa subir {deficit:.0f}%. Alternativa: manter a "
                f"conversão e crescer o topo — {meta_book / conv_atual:,.0f} leads/mês (use o Planejador, que já "
                "considera lag e CPL).".replace(",", "."))
        sugestoes.append("Priorize origens com conversão acima da mediana (aba Origem de Leads, chip "
                         "“escalar?”) — mudar o mix é mais barato que consertar etapa.")

    return {"periodo": {"ini": ini.isoformat(), "fim": fim.isoformat(),
                        "prev_ini": ini_p.isoformat(), "prev_fim": fim_p.isoformat()},
            "mes_ref": mes_ref.strftime("%m-%Y"), "mes_ref_iso": mes_ref.isoformat(),
            "funil": {"etapas": [{"key": e["etapa"].lower(), "label": e["etapa"], "volume": e["n"],
                                  "conversao_da_anterior_pct": e["conversao_da_anterior_pct"] if i else None}
                                 for i, e in enumerate(etapas[:6])],
                      "receita_bookings": _f(receita_book),
                      "conversao_total_pct": _pct(booked / total) if total else None},
            "etapas": etapas, "leads": total, "bookings": booked,
            "kpis": {"conv_lead_booking_pct": _pct(conv_atual),
                     "conv_necessaria_pct": _pct(conv_nec), "meta_bookings_mes": meta_book,
                     "taxa_mql_booking_pct": _pct(taxa_mb), "meta_mql_booking_pct": _pct(meta_mb),
                     "mql": mql_n},
            "metas_taxa_pct": {e: _pct(t) for e, t in metas_taxa.items()},
            "sugestoes": sugestoes}


def mkt_midia_dados(conn: Any, ini: dt.date, fim: dt.date) -> dict:
    with conn.cursor() as cur:
        cur.execute("""SELECT date, sum(spend), sum(clicks), sum(impressions)
                         FROM mkt_insights_daily WHERE date >= %s AND date <= %s
                        GROUP BY 1 ORDER BY 1""", (ini, fim))
        rows = cur.fetchall()
        cur.execute("""SELECT add_time::date, count(*) FROM mkt_deals_attribution
                        WHERE add_time::date >= %s AND add_time::date <= %s
                          AND (origem LIKE 'meta%%' OR origem LIKE 'google%%'
                               OR origem IN ('facebook', 'instagram_ads'))
                        GROUP BY 1""", (ini, fim))
        leads_dia = dict(cur.fetchall())
    dias = [{"dia": r[0].strftime("%d-%m"), "gasto": float(r[1]),
             "leads": int(leads_dia.get(r[0], 0)),
             "cpl": round(float(r[1]) / leads_dia[r[0]], 2) if leads_dia.get(r[0]) else None}
            for r in rows]
    tot_s = sum(float(r[1]) for r in rows)
    tot_l = sum(leads_dia.get(r[0], 0) for r in rows)
    tot_c = sum(float(r[2]) for r in rows)
    tot_i = sum(float(r[3]) for r in rows)
    criativos, aviso = [], None
    try:
        from ..sources import creative_history as CH
        agg: dict = {}
        for r in CH.daily():
            d0 = str(r.get("date") or "")[:10]
            if not d0 or not (ini.isoformat() <= d0 <= fim.isoformat()):
                continue
            a = agg.setdefault(r.get("ad_id"), {"nome": r.get("ad_name"), "thumb": r.get("thumbnail_url"),
                                                "tipo": r.get("creative_type"), "spend": 0.0, "leads": 0,
                                                "clicks": 0, "impr": 0, "book": 0})
            a["spend"] += float(r.get("spend") or 0)
            a["leads"] += int(r.get("leads") or 0)
            a["clicks"] += int(r.get("clicks") or 0)
            a["impr"] += int(r.get("impressions") or 0)
            a["book"] += int(r.get("bookings") or 0)
            if r.get("thumbnail_url"):
                a["thumb"] = r.get("thumbnail_url")
        for a in sorted(agg.values(), key=lambda x: -x["spend"])[:12]:
            criativos.append({"nome": (a["nome"] or "")[:48], "thumb": a.get("thumb"),
                              "tipo": a.get("tipo"), "gasto": round(a["spend"], 2),
                              "leads": a["leads"],
                              "cpl": round(a["spend"] / a["leads"], 2) if a["leads"] else None,
                              "ctr_pct": round(a["clicks"] / a["impr"] * 100, 2) if a["impr"] else None,
                              "bookings": a["book"]})
    except Exception:  # noqa: BLE001
        aviso = "Histórico de criativos (ad-insightify) indisponível no momento."
    return {"periodo": {"ini": ini.isoformat(), "fim": fim.isoformat()},
            "kpis": {"gasto": round(tot_s, 2), "leads": tot_l,
                     "cpl": round(tot_s / tot_l, 2) if tot_l else None,
                     "ctr_pct": round(tot_c / tot_i * 100, 2) if tot_i else None},
            "dias": dias, "criativos": criativos, "criativos_aviso": aviso}


def mkt_lag_dados(conn: Any) -> dict:
    marcos_lbl = {"primeiro_lead": "1º lead", "primeiro_booking": "1º booking", "p50_leads": "50% dos leads"}
    with conn.cursor() as cur:
        cur.execute("""SELECT canal, marco, n_campanhas, p25_dias, mediana_dias, p75_dias, computed_at
                         FROM mkt_campaign_lag_stats ORDER BY canal, marco""")
        stats = [{"canal": "Meta Ads" if c == "meta" else "Google Ads",
                  "marco": marcos_lbl.get(m, m), "campanhas": n,
                  "p25": round(float(p25)), "mediana": round(float(med)), "p75": round(float(p75))}
                 for c, m, n, p25, med, p75, _ in cur.fetchall()]
        cur.execute("""SELECT c.canal, (d.add_time::date - c.data_inicio) AS dias, count(*)
                         FROM mkt_campaigns c JOIN mkt_deals_attribution d ON d.utm_campaign = c.nome
                        WHERE c.data_inicio IS NOT NULL AND d.add_time::date >= c.data_inicio
                          AND (d.add_time::date - c.data_inicio) <= 120
                        GROUP BY 1, 2 ORDER BY 1, 2""", ())
        curvas_raw: dict[str, dict[int, int]] = {}
        for canal, dias, n in cur.fetchall():
            curvas_raw.setdefault(canal, {})[int(dias)] = n
    curvas = []
    for canal, hist in curvas_raw.items():
        total = sum(hist.values())
        if total < 30:
            continue
        acc, pts = 0, []
        for d0 in range(0, 121):
            acc += hist.get(d0, 0)
            pts.append(round(acc / total * 100, 1))
        curvas.append({"canal": "Meta Ads" if canal == "meta" else "Google Ads",
                       "total_leads": total, "pct_acumulado": pts})
    base = sorted(AN.lag_por_campanha(conn), key=lambda x: -x["leads"])[:20]
    campanhas = [{"campanha": b["campanha"][:52], "leads": b["leads"],
                  "d_primeiro_lead": _f(b["d_primeiro_lead"]),
                  "d_primeiro_booking": _f(b["d_primeiro_booking"]),
                  "d_50pct_leads": _f(b["d_50pct_leads"])} for b in base]
    return {"stats": stats, "curvas": curvas, "campanhas": campanhas}


def mkt_planejador_dados(conn: Any, pedidos: dict[str, int], alvo: dt.date | None,
                         canal_ui: str) -> dict:
    from .ui import _CANAL_DB
    canal_db = _CANAL_DB.get(canal_ui, "meta")
    bundles = ["B1", "B2", "B3", "B4", "B5"]
    total_pedido = sum(pedidos.get(b, 0) for b in bundles)
    out: dict = {"canal": canal_ui, "alvo": alvo.isoformat() if alvo else None,
                 "total_pedido": total_pedido, "plano": None, "sem_base": False}
    if not (alvo and total_pedido):
        return out
    with conn.cursor() as cur:
        cur.execute("SELECT marco, p25_dias, mediana_dias, p75_dias FROM mkt_campaign_lag_stats WHERE canal=%s",
                    (canal_db,))
        lag = {mm: (p25, med, p75) for mm, p25, med, p75 in cur.fetchall()}
    hoje = dt.date.today()
    rk = {r["canal"]: r for r in AN.ranking_canais(conn, hoje - dt.timedelta(days=90), hoje)}
    cpl = (rk.get(canal_ui) or {}).get("cpl")
    pref = "meta" if canal_db == "meta" else "google"
    with conn.cursor() as cur:
        cur.execute("""SELECT count(*) FROM mkt_deals_attribution
                        WHERE add_time >= %s AND origem LIKE %s""",
                    (hoje - dt.timedelta(days=180), pref + "%"))
        leads_base = cur.fetchone()[0] or 0
        cur.execute("""SELECT substring(produto FROM 'B[1-5]') AS b, count(*)
                         FROM mkt_deals_attribution
                        WHERE add_time >= %s AND origem LIKE %s AND status='won'
                          AND produto ~ 'B[1-5]' GROUP BY 1""",
                    (hoje - dt.timedelta(days=180), pref + "%"))
        book_bundle = dict(cur.fetchall())
    if not (lag.get("primeiro_booking") and cpl and leads_base):
        out["sem_base"] = True
        return out
    p25, med, p75 = (float(x) for x in lag["primeiro_booking"])
    d_med = alvo - dt.timedelta(days=int(med))
    linhas, recs = [], []
    tot_leads = tot_orc = 0.0
    for b in bundles:
        q = pedidos.get(b, 0)
        if not q:
            continue
        taxa_b = (book_bundle.get(b, 0) / leads_base) if leads_base else 0
        if taxa_b <= 0:
            linhas.append({"bundle": b, "bookings": q, "sem_historico": True})
            continue
        leads_nec = q / taxa_b
        orc = leads_nec * float(cpl)
        tot_leads += leads_nec
        tot_orc += orc
        linhas.append({"bundle": b, "bookings": q, "taxa_pct": _pct(taxa_b),
                       "leads_necessarios": round(leads_nec), "orcamento": round(orc, 2),
                       "sem_historico": False})
        with conn.cursor() as cur:
            cur.execute("""SELECT utm_campaign, count(*) FROM mkt_deals_attribution
                            WHERE status='won' AND produto ~ %s AND origem LIKE %s
                              AND utm_campaign IS NOT NULL
                            GROUP BY 1 ORDER BY 2 DESC LIMIT 3""", (b, pref + "%"))
            camps = [{"tipo": "campanha", "nome": cc[:52], "bookings": n} for cc, n in cur.fetchall()]
            cur.execute("""SELECT utm_content, count(*) FROM mkt_deals_attribution
                            WHERE status='won' AND produto ~ %s AND origem LIKE %s
                              AND utm_content IS NOT NULL
                            GROUP BY 1 ORDER BY 2 DESC LIMIT 3""", (b, pref + "%"))
            ads = [{"tipo": "criativo", "nome": aa[:52], "bookings": n} for aa, n in cur.fetchall()]
        if camps or ads:
            recs.append({"bundle": b, "itens": camps + ads})
    out["plano"] = {"linhas": linhas, "total_leads": round(tot_leads),
                    "total_orcamento": round(tot_orc, 2), "cpl_90d": _f(cpl),
                    "lancar_ate": d_med.isoformat(),
                    "janela_p25": (alvo - dt.timedelta(days=int(p25))).isoformat(),
                    "janela_p75": (alvo - dt.timedelta(days=int(p75))).isoformat(),
                    "lag_mediana_d": round(med), "lag_p25_d": round(p25), "lag_p75_d": round(p75),
                    "atrasado": d_med < hoje, "recomendacoes": recs}
    return out


def mkt_criativos_dados(conn: Any, publico: str = "") -> dict:
    import re as _re
    import statistics as _st
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT adset_name FROM mkt_insights_daily WHERE canal='meta' AND adset_name IS NOT NULL ORDER BY 1")
        publicos = [r[0] for r in cur.fetchall()][:80]
        filtro = "AND i.adset_name = %s" if publico else ""
        args = [publico] if publico else []
        cur.execute(f"""
            SELECT i.ad_name, max(i.adset_name) AS pub, sum(i.spend) AS gasto, sum(i.leads) AS leads,
                   count(DISTINCT d.deal_id) FILTER (WHERE d.oport_time IS NOT NULL) AS oport,
                   count(DISTINCT d.deal_id) FILTER (WHERE d.status='won') AS books
              FROM mkt_insights_daily i
              LEFT JOIN mkt_deals_attribution d ON d.utm_content = i.ad_name
             WHERE i.canal='meta' AND i.ad_name IS NOT NULL {filtro}
             GROUP BY i.ad_name HAVING sum(i.leads) >= 5
             ORDER BY (sum(i.spend) / NULLIF(sum(i.leads),0)) ASC NULLS LAST LIMIT 30""", args)
        rows = cur.fetchall()
    cpls = [float(g) / l for _a, _p, g, l, _o, _b in rows if l]
    convs = [o / l for _a, _p, _g, l, o, _b in rows if l]
    med_cpl = _st.median(cpls) if cpls else None
    med_conv = _st.median(convs) if convs else None

    def veredito(cpl, conv, books, gasto):
        if cpl is None or med_cpl is None:
            return None
        if books and conv is not None and med_conv and conv >= med_conv:
            return "escalar"
        if cpl <= med_cpl and conv is not None and med_conv and conv >= med_conv:
            return "escalar"
        if cpl > med_cpl * 1.5 and (conv or 0) < (med_conv or 0) * 0.7:
            return "pausar"
        if (conv or 0) < (med_conv or 0) * 0.7 and float(gasto) > 500:
            return "revisar"
        return "manter"
    criativos = []
    for ad, pub, gasto, leads, oport, books in rows:
        cpl = float(gasto) / leads if leads else None
        conv = oport / leads if leads else None
        criativos.append({"criativo": (ad or "")[:42], "publico": (pub or "")[:30],
                          "gasto": round(float(gasto), 2), "leads": leads,
                          "cpl": round(cpl, 2) if cpl is not None else None,
                          "conv_pct": _pct(conv), "bookings": books,
                          "veredito": veredito(cpl, conv, books, gasto)})

    tok_agg: dict[str, list[float]] = {}
    for ad, _p, g, l, o, _b in rows:
        for tk in {t for t in _re.split(r"[^a-zà-ú0-9]+", (ad or "").lower())
                   if len(t) >= 4 and not any(ch.isdigit() for ch in t)}:
            d0 = tok_agg.setdefault(tk, [0.0, 0, 0, 0])
            d0[0] += float(g); d0[1] += l; d0[2] += o; d0[3] += 1
    elems_raw = [(tk, g / l, o / l, n, l) for tk, (g, l, o, n) in tok_agg.items() if n >= 2 and l >= 30]
    elementos = [{"elemento": tk, "criativos": n, "leads": l,
                  "cpl": round(cpl_t, 2), "conv_pct": _pct(conv_t),
                  "destaque": ("pos" if med_conv and conv_t >= med_conv * 1.2
                               else ("neg" if med_conv and conv_t <= med_conv * 0.6 else None))}
                 for tk, cpl_t, conv_t, n, l in sorted(elems_raw, key=lambda x: -x[2])[:10]]

    with conn.cursor() as cur:
        cur.execute("""SELECT utm_content, COALESCE(substring(produto FROM 'B[1-5]'), 'outros'), count(*)
                         FROM mkt_deals_attribution
                        WHERE status='won' AND utm_content IS NOT NULL GROUP BY 1, 2""")
        cb: dict[str, dict[str, int]] = {}
        for cr, bd, n in cur.fetchall():
            cb.setdefault(cr[:42], {})[bd] = n
    bundles_c = ["B1", "B2", "B3", "B4", "B5", "outros"]
    criativo_x_plano = []
    for cr, d0 in sorted(cb.items(), key=lambda x: -sum(x[1].values()))[:10]:
        tot_cr = sum(d0.values())
        b25 = sum(v for k, v in d0.items() if k in ("B2", "B3", "B4", "B5"))
        criativo_x_plano.append({"criativo": cr, "por_plano": {b: d0.get(b, 0) for b in bundles_c},
                                 "total": tot_cr, "traz_b2_b5": tot_cr >= 3 and b25 / tot_cr >= 0.5})

    leitura = []
    escalaveis = [(ad, o / l) for ad, _p, g, l, o, b in rows if l >= 20 and med_conv and o / l >= med_conv * 1.3]
    if escalaveis:
        top = max(escalaveis, key=lambda x: x[1])
        leitura.append(f"Melhor criativo com volume: “{top[0][:40]}” converte {top[1] * 100:.1f}% "
                       f"(mediana {med_conv * 100:.1f}%) — candidato a mais verba.")
    ralos = [(ad, float(g)) for ad, _p, g, l, o, _b in rows if l >= 20 and med_conv and (o / l) <= med_conv * 0.5 and float(g) > 800]
    if ralos:
        pior = max(ralos, key=lambda x: x[1])
        leitura.append(f"Maior ralo: “{pior[0][:40]}” já gastou R$ {pior[1]:,.0f} convertendo metade da "
                       "mediana — pausar ou trocar a promessa.".replace(",", "."))
    if elems_raw:
        melhor_el = max(elems_raw, key=lambda x: x[2])
        leitura.append(f"Elemento vencedor nos nomes: “{melhor_el[0]}” ({melhor_el[2] * 100:.1f}% de "
                       f"conversão em {melhor_el[3]} criativos) — leve para o próximo brief.")

    testes, ideias, testes_aviso = [], [], None
    try:
        from ..sources import creative_history as CH
        runs = CH.runs()
        testes = [{"anuncio": (r.get("ad_name") or "")[:44], "publico": (r.get("adset_name") or "")[:28],
                   "formato": r.get("creative_type") or "—", "inicio": str(r.get("started_at") or "")[:10],
                   "dias_ativo": r.get("days_active")}
                  for r in sorted(runs, key=lambda x: str(x.get("started_at") or ""), reverse=True)[:15]]
        vistos = {(r.get("creative_type"), r.get("adset_name")) for r in runs}
        formatos = {r.get("creative_type") for r in runs if r.get("creative_type")}
        pubs_top = [pub for _, pub, *_r in rows[:8] if pub][:6]
        ideias = [f"Formato {f} ainda não testado no público {p[:34]} — vizinhos testados performam bem"
                  for f in formatos for p in pubs_top if (f, p) not in vistos][:6]
        n_runs = len(runs)
    except Exception:  # noqa: BLE001
        testes_aviso = "Histórico do ad-insightify indisponível no momento."
        n_runs = 0
    return {"publico": publico or None, "publicos": publicos,
            "medianas": {"cpl": round(med_cpl, 2) if med_cpl is not None else None,
                         "conv_pct": _pct(med_conv)},
            "criativos": criativos, "elementos": elementos,
            "criativo_x_plano": {"planos": bundles_c, "linhas": criativo_x_plano},
            "leitura": leitura, "testes": testes, "n_testes": n_runs,
            "testes_aviso": testes_aviso, "ideias": ideias}


def mkt_ciclo_vida_dados(conn: Any) -> dict:
    from .ui import _ciclo_coorte
    coorte, gasto, meta_cob = _ciclo_coorte(conn)
    tot = len(coorte)
    if not tot:
        return {"vazio": True}

    def seg(chave):
        m: dict[str, dict] = {}
        for r in coorte:
            k = chave(r)
            if k is None:
                continue
            d0 = m.setdefault(k, {"n": 0, "ativo": 0, "precoce": 0, "tardio": 0,
                                  "mrr_ret": 0.0, "mrr_perd": 0.0})
            d0["n"] += 1
            d0[r["desfecho"]] = d0.get(r["desfecho"], 0) + 1
            if r["desfecho"] == "ativo":
                d0["mrr_ret"] += r["mrr"]
            else:
                d0["mrr_perd"] += r["mrr"]
        return m

    por_canal = seg(lambda r: r["canal"])
    canais = []
    for canal, d0 in sorted(por_canal.items(), key=lambda x: -x[1]["n"]):
        ret = d0["ativo"] / d0["n"]
        cac = cac_aj = None
        if canal in gasto:
            dt0, g = gasto[canal]
            n_per = sum(1 for r in coorte if r["canal"] == canal and r["won"] >= dt0)
            if n_per:
                cac = g / n_per
                cac_aj = cac / ret if ret else None
        canais.append({"canal": canal, "clientes": d0["n"], "ativos_pct": _pct(ret),
                       "precoce_pct": _pct(d0["precoce"] / d0["n"]),
                       "tardio_pct": _pct(d0["tardio"] / d0["n"]),
                       "mrr_retido": round(d0["mrr_ret"], 2), "mrr_perdido": round(d0["mrr_perd"], 2),
                       "cac": round(cac, 2) if cac is not None else None,
                       "cac_ajustado": round(cac_aj, 2) if cac_aj is not None else None})

    por_cria = seg(lambda r: r["criativo"][:40] if r["canal"] in ("Meta Ads", "Google Ads") and r["criativo"] else None)
    criativos = [{"criativo": k, "clientes": d0["n"], "ativos_pct": _pct(d0["ativo"] / d0["n"]),
                  "precoce_pct": _pct(d0["precoce"] / d0["n"]), "amostra_pequena": d0["n"] < 8}
                 for k, d0 in sorted(por_cria.items(), key=lambda x: (-(x[1]["precoce"] / x[1]["n"]), -x[1]["n"]))[:10]]

    bundles = ["B1", "B2", "B3", "B4", "B5", "outros"]
    canal_x_bundle = []
    for canal, _d in sorted(por_canal.items(), key=lambda x: -x[1]["n"])[:7]:
        cels = []
        for b in bundles:
            grupo = [r for r in coorte if r["canal"] == canal and r["bundle"] == b]
            if grupo:
                pc = sum(1 for r in grupo if r["desfecho"] == "precoce") / len(grupo)
                cels.append({"bundle": b, "precoce_pct": _pct(pc), "n": len(grupo),
                             "alerta": pc >= 0.4 and len(grupo) >= 5})
            else:
                cels.append({"bundle": b, "precoce_pct": None, "n": 0, "alerta": False})
        canal_x_bundle.append({"canal": canal, "cels": cels})

    por_safra = seg(lambda r: r["won"].strftime("%m/%y"))
    ordem_s = sorted(por_safra, key=lambda k: (k[3:], k[:2]))[-8:]
    safras = [{"safra": s, "clientes": por_safra[s]["n"],
               "ativos_pct": _pct(por_safra[s]["ativo"] / por_safra[s]["n"]),
               "precoce_pct": _pct(por_safra[s]["precoce"] / por_safra[s]["n"]),
               "tardio_pct": _pct(por_safra[s]["tardio"] / por_safra[s]["n"]),
               "em_maturacao": any(r["parcial"] for r in coorte if r["won"].strftime("%m/%y") == s)}
              for s in ordem_s]

    elegiveis = {k: d0 for k, d0 in por_canal.items() if d0["n"] >= 8}
    leitura = "Amostra ainda pequena por canal para leitura automática."
    if elegiveis:
        pior = max(elegiveis.items(), key=lambda x: x[1]["precoce"] / x[1]["n"])
        melhor = max(elegiveis.items(), key=lambda x: x[1]["ativo"] / x[1]["n"])
        cria_ruim = next((k for k, d0 in sorted(por_cria.items(), key=lambda x: -(x[1]["precoce"] / x[1]["n"]))
                          if d0["n"] >= 8 and d0["precoce"] / d0["n"] >= 0.4), None)
        leitura = (f"Pior relação aquisição→retenção: {pior[0]} ({pior[1]['precoce'] / pior[1]['n'] * 100:.1f}% de "
                   f"churn precoce em {pior[1]['n']} clientes). Melhor: {melhor[0]} "
                   f"({melhor[1]['ativo'] / melhor[1]['n'] * 100:.1f}% ainda ativos). "
                   + (f"Criativo candidato a revisão de PROMESSA: “{cria_ruim}”." if cria_ruim
                      else "Nenhum criativo com amostra suficiente concentra churn precoce ≥40%."))
    return {"vazio": False,
            "kpis": {"clientes": tot,
                     "ativos_pct": _pct(sum(1 for r in coorte if r["desfecho"] == "ativo") / tot),
                     "precoce_pct": _pct(sum(1 for r in coorte if r["desfecho"] == "precoce") / tot)},
            "leitura": leitura,
            "cobertura": {"canc_casados": meta_cob["canc_casados"], "n_cancs": meta_cob["n_cancs"],
                          "sem_origem": meta_cob["sem_origem"]},
            "canais": canais, "criativos": criativos,
            "canal_x_bundle": {"bundles": bundles, "linhas": canal_x_bundle},
            "safras": safras}
