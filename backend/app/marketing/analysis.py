"""Análises da área de Marketing sobre o cache mkt_* (só lê Postgres).

Canal a partir do utm_source (versionado no histórico: meta_ads, _v2, _v3 —
agrupamos por PREFIXO). Marcos do funil v1: lead = deal criado (add_time);
booking = won. "Oportunidade" usa PROXY: deal que avançou do estágio inicial
(stage_id >= 3) ou fechou — o tempo exato de avanço entra quando o
enriquecimento via /flow for ligado (documentado no coletor).

Lag (aba Tempo até Resultado): por campanha Meta/Google casada por NOME
(mkt_campaigns.nome == utm_campaign do deal), medimos dias do lançamento
(data_inicio) até 1º lead, 1º booking e até 50% dos leads da campanha;
agregamos mediana/p25/p75 por canal em mkt_campaign_lag_stats (recalc semanal).
"""
from __future__ import annotations

import datetime as dt
import statistics
from typing import Any


def canal_de(origem: str | None) -> str:
    o = (origem or "").lower()
    if o.startswith("meta_ads") or o in ("facebook", "instagram_ads"):
        return "Meta Ads"
    if o.startswith("google"):
        return "Google Ads"
    if "linkedin" in o:
        return "LinkedIn"
    if "indica" in o:
        return "Indicações"
    if o in ("prospeccao", "prospecção"):
        return "Prospecção"
    if o in ("", "(vazio)"):
        return "Sem origem"
    return "Orgânico/Outros"  # shopee, calculadora, blog, website, instagram_org, youtube…


_CANAIS_PAGOS = {"Meta Ads": "meta", "Google Ads": "google"}


def ranking_canais(conn: Any, ini: dt.date, fim: dt.date) -> list[dict]:
    """Por canal no período: gasto, leads, CPL, oportunidades, bookings,
    receita, conversões, CAC e ROAS. Canais sem mídia: custo zero, eficiência
    relativa preservada."""
    with conn.cursor() as cur:
        cur.execute("""SELECT origem, count(*) AS leads,
                              count(*) FILTER (WHERE stage_id >= 3 OR status IN ('won','lost')) AS oport,
                              count(*) FILTER (WHERE status='won') AS bookings,
                              COALESCE(sum(valor) FILTER (WHERE status='won'), 0) AS receita
                         FROM mkt_deals_attribution
                        WHERE add_time >= %s AND add_time < %s
                        GROUP BY origem""", (ini, fim + dt.timedelta(days=1)))
        por_canal: dict[str, dict] = {}
        for origem, leads, oport, book, receita in cur.fetchall():
            c = por_canal.setdefault(canal_de(origem), {"leads": 0, "oport": 0,
                                                        "bookings": 0, "receita": 0.0})
            c["leads"] += leads
            c["oport"] += oport
            c["bookings"] += book
            c["receita"] += float(receita)
        cur.execute("""SELECT canal, COALESCE(sum(spend),0) FROM mkt_insights_daily
                        WHERE date >= %s AND date <= %s GROUP BY canal""", (ini, fim))
        gasto = {("Meta Ads" if c == "meta" else "Google Ads"): float(s) for c, s in cur.fetchall()}
    out = []
    for canal, d in por_canal.items():
        g = gasto.get(canal, 0.0)
        out.append({
            "canal": canal, "gasto": g, "leads": d["leads"],
            "cpl": (g / d["leads"]) if d["leads"] and g else None,
            "oportunidades": d["oport"], "bookings": d["bookings"], "receita": d["receita"],
            "conv_lead_oport": d["oport"] / d["leads"] if d["leads"] else None,
            "conv_oport_book": d["bookings"] / d["oport"] if d["oport"] else None,
            "conv_lead_book": d["bookings"] / d["leads"] if d["leads"] else None,
            "cac": (g / d["bookings"]) if d["bookings"] and g else None,
            "roas": (d["receita"] / g) if g else None,
        })
    out.sort(key=lambda x: (-x["bookings"], -x["leads"]))
    return out


def funil_por_origem(conn: Any, ini: dt.date, fim: dt.date, origem: str | None = None) -> list[dict]:
    """Funil por origem crua; com `origem`, detalha por campanha e criativo."""
    grp = "utm_campaign, utm_content" if origem else "origem"
    filtro = "AND origem = %s" if origem else ""
    args = [ini, fim + dt.timedelta(days=1)] + ([origem] if origem else [])
    with conn.cursor() as cur:
        cur.execute(f"""SELECT {grp}, count(*) AS leads,
                              count(*) FILTER (WHERE stage_id >= 3 OR status IN ('won','lost')) AS oport,
                              count(*) FILTER (WHERE status='won') AS bookings,
                              COALESCE(sum(valor) FILTER (WHERE status='won'),0) AS receita
                         FROM mkt_deals_attribution
                        WHERE add_time >= %s AND add_time < %s {filtro}
                        GROUP BY {grp} ORDER BY leads DESC""", args)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Lag campanha -> resultado
# ---------------------------------------------------------------------------
def _percentis(vals: list[float]) -> tuple[float, float, float] | None:
    if len(vals) < 3:
        return None
    q = statistics.quantiles(vals, n=4)
    return q[0], statistics.median(vals), q[2]


def lag_por_campanha(conn: Any) -> list[dict]:
    """Lag POR CAMPANHA (base da agregação e da validação com o Rafael)."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT c.canal, c.nome, c.data_inicio,
                   min(d.add_time)::date  AS lead1,
                   min(d.won_time)::date  AS book1,
                   count(*) AS leads,
                   to_timestamp(percentile_cont(0.5) WITHIN GROUP
                       (ORDER BY extract(epoch FROM d.add_time)))::date AS lead_p50
              FROM mkt_campaigns c
              JOIN mkt_deals_attribution d ON d.utm_campaign = c.nome
             WHERE c.data_inicio IS NOT NULL
             GROUP BY c.canal, c.nome, c.data_inicio
            HAVING count(*) >= 3""")
        out = []
        for canal, nome, inicio, lead1, book1, leads, lead_p50 in cur.fetchall():
            def dias(x):
                return (x - inicio).days if x and inicio else None
            out.append({"canal": canal, "campanha": nome, "inicio": inicio, "leads": leads,
                        "d_primeiro_lead": dias(lead1), "d_primeiro_booking": dias(book1),
                        "d_50pct_leads": dias(lead_p50)})
        return out


def recompute_lag_stats(conn: Any) -> int:
    """Agrega o lag por canal e grava mkt_campaign_lag_stats (recalc semanal)."""
    base = lag_por_campanha(conn)
    marcos = {"primeiro_lead": "d_primeiro_lead", "primeiro_booking": "d_primeiro_booking",
              "p50_leads": "d_50pct_leads"}
    n = 0
    with conn.cursor() as cur:
        for canal in {b["canal"] for b in base}:
            for marco, k in marcos.items():
                vals = [float(b[k]) for b in base
                        if b["canal"] == canal and b[k] is not None and 0 <= b[k] <= 365]
                p = _percentis(vals)
                if not p:
                    continue
                cur.execute(
                    """INSERT INTO mkt_campaign_lag_stats
                           (canal, tipo, marco, n_campanhas, mediana_dias, p25_dias, p75_dias, computed_at)
                       VALUES (%s,'todas',%s,%s,%s,%s,%s,now())
                       ON CONFLICT (canal, tipo, marco) DO UPDATE SET
                            n_campanhas=EXCLUDED.n_campanhas, mediana_dias=EXCLUDED.mediana_dias,
                            p25_dias=EXCLUDED.p25_dias, p75_dias=EXCLUDED.p75_dias, computed_at=now()""",
                    (canal, marco, len(vals), p[1], p[0], p[2]))
                n += 1
    return n
