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
