"""Dados PUROS do Financeiro (redesenho, Lote 5 — 22/07/2026).

Regra do redesenho: o endpoint EMBRULHA o cálculo existente, nunca reimplementa.
Aqui se transcreve o compute de `_visao` (financeiro/ui.py) para JSON, reusando
as MESMAS fontes: `planejamento_financeiro.carrega/linha` (planilha, cache 10min)
e `_funil_oficial` do Marketing (régua oficial ao vivo do Pipedrive).

Réguas preservadas:
  - mês corrente = realizado AO VIVO; meses passados = planilha; futuros = meta;
  - o verde/vermelho compara com o RITMO do mês (fração decorrida), não com 100%;
  - recebimento/inadimplência/churn do mês corrente são PROJEÇÃO (sem Omie).
"""
from __future__ import annotations

import calendar
import datetime as dt
from typing import Any

from ..sources import planejamento_financeiro as PF


def _f(v):
    return float(v) if v is not None else None


def _mes_lbl(iso: str) -> str:
    from .ui import _mes_lbl as lbl
    return lbl(iso)


def fin_visao_dados(conn: Any) -> dict:
    from ..marketing.ui import _funil_oficial
    dados = PF.carrega()
    if not dados:
        return {"sem_planilha": True}

    hoje = dt.date.today()
    mes_iso = f"{hoje.year:04d}-{hoje.month:02d}"
    meses = dados["meses"]
    i_atual = meses.index(mes_iso) if mes_iso in meses else len(meses) - 1
    frac = hoje.day / calendar.monthrange(hoje.year, hoje.month)[1]

    def meta(prefixo):
        return PF.linha(dados, prefixo)[i_atual]

    passou, booked, _tot, receita = _funil_oficial(conn, hoje.replace(day=1), hoje)

    # --- cards do mês em tempo real × meta (mesma ordem/régua da tela) ---
    def card(rotulo, real, m, kind):
        pct = (real / m) if (m and real is not None) else None
        return {"rotulo": rotulo, "real": _f(real), "meta": _f(m), "kind": kind,
                "pct": round(pct * 100, 1) if pct is not None else None,
                "no_ritmo": (pct >= frac) if pct is not None else None,
                "fonte": "Pipedrive ao vivo"}
    cards = [
        card("Receita de bookings", receita, meta("Meta Bookings [R$]"), "brl"),
        card("Bookings (qtde)", booked, meta("Bookings [Qtde]"), "num"),
        card("Leads", passou[0], meta("Leads [Qtde]"), "num"),
        card("MQLs", passou[1], meta("MQLs [Qtde]"), "num"),
        card("SALs", passou[2], meta("SALs [Qtde]"), "num"),
        card("SQLs", passou[3], meta("SQLs [Qtde]"), "num"),
        card("Oportunidades", passou[4], meta("Oportunidades [Qtde]"), "num"),
    ]

    # --- 'o que mais afasta da meta': 3 maiores desvios em R$ + causa + link ---
    desvios: list[tuple[float, str, str, str]] = []
    with conn.cursor() as cur:
        cur.execute("""SELECT COALESCE(substring(upper(produto) FROM 'B[1-5]'), 'outros'), count(*)
                         FROM mkt_deals_attribution
                        WHERE oport_time >= %s GROUP BY 1""", (f"{hoje.replace(day=1)} 00:00-03",))
        oport_bund = dict(cur.fetchall())
        cur.execute("""SELECT COALESCE(substring(upper(produto) FROM 'B[1-5]'), 'outros'),
                              count(*), COALESCE(sum(COALESCE(valor_custom, valor)), 0)
                         FROM mkt_deals_attribution
                        WHERE status='won' AND won_time >= %s GROUP BY 1""",
                    (f"{hoje.replace(day=1)} 00:00-03",))
        bund_n: dict[str, int] = {}
        bund_v: dict[str, float] = {}
        for b_, n_, v_ in cur.fetchall():
            bund_n[b_], bund_v[b_] = int(n_), float(v_)
    tx_meta = PF.linha(dados, "Tx. Oportunidade x Booking")[i_atual]
    for b_ in ("B1", "B2", "B3", "B4", "B5"):
        m_r = PF.linha(dados, f"{b_} - Meta: Booking [R$]")[i_atual]
        m_q = PF.linha(dados, f"{b_} - Meta: Booking [Qtde]")[i_atual]
        if not m_r:
            continue
        gap = m_r * frac - bund_v.get(b_, 0.0)
        if gap <= 0:
            continue
        oport_nec = (m_q * frac / tx_meta) if (m_q and tx_meta) else None
        causa = ("faltam oportunidades — geração/qualificação"
                 if oport_nec and oport_bund.get(b_, 0) < oport_nec
                 else "conversão abaixo do plano — fechamento/proposta")
        desvios.append((gap, f"{b_}: {bund_n.get(b_, 0)}/{m_q:.0f} bookings — {gap:,.0f} atrás do ritmo"
                        .replace(",", "."), causa, f"/raiox?b={b_}"))
    tx_atual = (booked / passou[4]) if passou[4] else None
    if tx_meta and tx_atual is not None and tx_atual < tx_meta and passou[4]:
        gap_tx = passou[4] * (tx_meta - tx_atual) * (receita / booked if booked else 0)
        desvios.append((gap_tx, f"Tx. Oportunidade→Booking em {tx_atual * 100:.1f}% vs {tx_meta * 100:.0f}% "
                                "planejado", "qualificação herdada × fechamento — ver a Ponte",
                        "/vendas?view=ponte"))
    m_leads = PF.linha(dados, "Leads [Qtde]")[i_atual]
    if m_leads and passou[0] < m_leads * frac and booked and passou[0]:
        gap_l = (m_leads * frac - passou[0]) * (booked / passou[0]) * (receita / booked)
        desvios.append((gap_l, f"Leads a {passou[0] / m_leads * 100:.0f}% da meta "
                               f"({passou[0]:.0f}/{m_leads:.0f})", "volume de topo — verba/campanhas",
                        "/marketing?view=metas"))
    top3 = [{"gap": round(g, 2), "texto": t, "causa": c, "url": u}
            for g, t, c, u in sorted(desvios, key=lambda x: -x[0])[:3]]

    # --- séries mês a mês (os SVGs viram gráficos da biblioteca) ---
    lbls = [_mes_lbl(m) for m in meses]
    receb = PF.linha(dados, "Recebimento TOTAL [R$]")
    recor = PF.linha(dados, "Recebimento RECORRENTE [R$]")
    rec_pct = PF.linha(dados, "Recebimento RECORRENTE [%]")
    rb_real = PF.linha(dados, "Receita Bookings [R$]")
    rb_meta = PF.linha(dados, "Meta Bookings [R$]")
    rb_qtd = PF.linha(dados, "Bookings [Qtde]")
    inad = PF.linha(dados, "Inadimplência [%]")
    churn = PF.linha(dados, "Taxa de cancelamento - TOTAL")

    recebimento = [{"mes": lbls[i], "total": _f(receb[i]), "recorrente": _f(recor[i]),
                    "pct_recorrente": round(rec_pct[i] * 100, 1) if rec_pct[i] is not None else None,
                    "projecao": i >= i_atual, "atual": i == i_atual}
                   for i in range(len(meses))]

    bookings = []
    for i in range(len(meses)):
        if i == i_atual:
            real_i, no_ritmo = receita, (receita >= rb_meta[i] * frac) if rb_meta[i] else None
            sub = f"{booked} bk até hoje"
        else:
            real_i = _f(rb_real[i]) if i < i_atual else None
            no_ritmo = (rb_real[i] >= rb_meta[i]) if (i < i_atual and rb_real[i] is not None and rb_meta[i]) else None
            sub = f"{rb_qtd[i]:.0f} bk" if rb_qtd[i] is not None else ""
        bookings.append({"mes": lbls[i], "real": _f(real_i), "meta": _f(rb_meta[i]),
                         "no_ritmo": no_ritmo, "sublabel": sub,
                         "futuro": i > i_atual, "atual": i == i_atual})

    saude = [{"mes": lbls[i],
              "inadimplencia_pct": round(inad[i] * 100, 2) if inad[i] is not None else None,
              "churn_pct": round(churn[i] * 100, 2) if churn[i] is not None else None,
              "alvo": i >= i_atual}
             for i in range(len(meses))]

    # --- tabelas (histórico e metas) — mesmas linhas/rótulos da tela HTML ---
    def serie(rotulo, chave, kind, idxs):
        vals = PF.linha(dados, chave)
        return {"rotulo": rotulo, "kind": kind,
                "valores": [_f(vals[i]) for i in idxs]}
    idx_hist = list(range(max(0, i_atual - 12), i_atual))
    idx_metas = list(range(i_atual, len(meses)))
    HIST = [("Recebimento total", "Recebimento TOTAL [R$]", "brl"),
            ("Recebimento recorrente", "Recebimento RECORRENTE [R$]", "brl"),
            ("% recorrente", "Recebimento RECORRENTE [%]", "pct"),
            ("Inadimplência", "Inadimplência [R$]", "brl"),
            ("Inadimplência %", "Inadimplência [%]", "pct"),
            ("Bookings (qtde)", "Bookings [Qtde]", "num"),
            ("Receita de bookings", "Receita Bookings [R$]", "brl"),
            ("% da meta de bookings", "Receita Bookings [%]", "pct"),
            ("Bookings não-recorrentes (B1)", "Receita Bookings [R$] (B1", "brl"),
            ("Bookings recorrentes (B2-B5)", "Receita Bookings [R$] (Recorrente)", "brl"),
            ("Taxa de cancelamento", "Taxa de cancelamento - TOTAL", "pct"),
            ("Parceiros — recebimento", "Parceiros - Recebimento", "brl")]
    METAS = [("Meta de bookings (R$)", "Meta Bookings [R$]", "brl"),
             ("Bookings (qtde)", "Bookings [Qtde]", "num")]
    for b_ in ("B1", "B2", "B3", "B4", "B5"):
        METAS.append((f"{b_} — qtde", f"{b_} - Meta: Booking [Qtde]", "num"))
        METAS.append((f"{b_} — R$", f"{b_} - Meta: Booking [R$]", "brl"))
    METAS += [("Leads", "Leads [Qtde]", "num"), ("MQLs", "MQLs [Qtde]", "num"),
              ("SALs", "SALs [Qtde]", "num"), ("SQLs", "SQLs [Qtde]", "num"),
              ("Oportunidades", "Oportunidades [Qtde]", "num"),
              ("Tx. Oportunidade → Booking", "Tx. Oportunidade x Booking", "pct"),
              ("Recebimento total projetado", "Recebimento TOTAL [R$]", "brl"),
              ("Recebimento recorrente projetado", "Recebimento RECORRENTE [R$]", "brl"),
              ("Inadimplência alvo (%)", "Inadimplência [%]", "pct"),
              ("Churn alvo (%)", "Taxa de cancelamento - TOTAL", "pct")]
    # realizado AO VIVO na frente das metas do mês corrente (Otávio 16/07)
    atual = {"Meta de bookings (R$)": receita, "Bookings (qtde)": booked,
             "Leads": passou[0], "MQLs": passou[1], "SALs": passou[2],
             "SQLs": passou[3], "Oportunidades": passou[4],
             "Tx. Oportunidade → Booking": (booked / passou[4] if passou[4] else None)}
    for b_ in ("B1", "B2", "B3", "B4", "B5"):
        atual[f"{b_} — qtde"] = bund_n.get(b_, 0)
        atual[f"{b_} — R$"] = bund_v.get(b_, 0.0)
    links = {"Tx. Oportunidade → Booking": {"url": "/vendas?view=ponte",
                                            "dica": "a taxa é herdada da qualificação ou é do fechamento? Ver a Ponte"},
             "Churn alvo (%)": {"url": "/growth?view=cancelamentos",
                                "dica": "quem sai e por quê — aba Cancelamentos"}}
    for b_ in ("B1", "B2", "B3", "B4", "B5"):
        links[f"{b_} — qtde"] = {"url": f"/raiox?b={b_}",
                                 "dica": f"Raio-X do {b_}: aquisição → fechamento → retenção → operação"}

    return {
        "sem_planilha": False,
        "hoje": hoje.isoformat(), "dia": hoje.day,
        "mes_label": _mes_lbl(mes_iso), "ritmo_pct": round(frac * 100, 1),
        "cards": cards, "desvios": top3,
        "recebimento": recebimento, "bookings_mes": bookings, "saude": saude,
        "historico": {"meses": [lbls[i] for i in idx_hist],
                      "linhas": [serie(r, k, kd, idx_hist) for r, k, kd in HIST],
                      "destaque": ["Recebimento total", "Receita de bookings"]},
        "metas": {"meses": [lbls[i] for i in idx_metas],
                  "linhas": [dict(serie(r, k, kd, idx_metas),
                                  atual=_f(atual.get(r)), link=links.get(r))
                             for r, k, kd in METAS],
                  "destaque": ["Meta de bookings (R$)", "Recebimento total projetado"]},
    }
