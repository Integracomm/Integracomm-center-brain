"""Área FINANCEIRO no painel — /financeiro (pedido Otávio 15/07/26).

Fonte: planilha de Planejamento_Receita_2026 (aba 2026) via
sources.planejamento_financeiro — histórico realizado, metas dos próximos
meses e o acompanhamento EM TEMPO REAL do mês corrente:
  - bookings (qtde/receita) e funil AO VIVO do espelho do Pipedrive (mesma
    régua oficial do funil de Marketing, serve-stale ≤10min);
  - recebimento/inadimplência da coluna "(Parcial)" da planilha (fonte manual
    do time — sem sistema live até o Omie entrar).
Mesma casca do Marketing (shell reaproveitado, padrão da área de Vendas).
"""
from __future__ import annotations

import datetime as dt
import re
from html import escape

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from ..sources import planejamento_financeiro as PF

router = APIRouter()

_VIEWS = [("visao", "Planejamento x Realizado")]


def _deps():
    from .. import api as A
    return A


def _fmt(v, kind="num") -> str:
    if v is None:
        return "<span style='color:var(--text-faint)'>—</span>"
    if kind == "brl":
        return f"R$ {v:,.0f}".replace(",", ".")
    if kind == "pct":
        return f"{v * 100:.1f}%"
    if kind == "x":
        return f"{v:.1f}x"
    if kind == "num1":
        return f"{v:,.1f}".replace(",", ".")
    return f"{v:,.0f}".replace(",", ".")


_TH = ("<th style='text-align:{al};padding:7px 9px;border-bottom:1px solid var(--border-strong);"
       "color:var(--text-muted);font-size:var(--fs-2xs);text-transform:uppercase;"
       "letter-spacing:.05em;white-space:nowrap'>{h}</th>")
_TD = ("padding:7px 9px;border-bottom:1px solid var(--border);"
       "font-variant-numeric:tabular-nums;font-size:var(--fs-sm);white-space:nowrap")
_MESES_PT = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def _mes_lbl(iso: str) -> str:
    y, m = iso.split("-")
    return f"{_MESES_PT[int(m) - 1]}/{y[2:]}"


def _tabela(dados: dict, metricas: list[tuple[str, str, str]], idxs: list[int],
            destaque: set[str] | None = None) -> str:
    """Tabela métrica × meses. metricas = [(rótulo exibido, prefixo na planilha,
    kind)]; idxs = índices dos meses a mostrar."""
    ths = _TH.format(al="left", h="Métrica") + "".join(
        _TH.format(al="right", h=_mes_lbl(dados["meses"][i])) for i in idxs)
    linhas = ""
    for rot, prefixo, kind in metricas:
        vals = PF.linha(dados, prefixo)
        b = "font-weight:600" if destaque and rot in destaque else ""
        tds = "".join(f"<td style='{_TD};text-align:right'>{_fmt(vals[i], kind)}</td>" for i in idxs)
        linhas += f"<tr><td style='{_TD};text-align:left;{b}'>{escape(rot)}</td>{tds}</tr>"
    return ("<div class=central style='padding:6px 14px 12px;overflow-x:auto'>"
            f"<table style='width:100%;border-collapse:collapse'><tr>{ths}</tr>{linhas}</table></div>")


def _card_meta(rotulo: str, real, meta, frac: float, kind: str = "num",
               fonte: str = "") -> str:
    """Card realizado × meta do mês, colorido pelo RITMO (fração decorrida)."""
    if meta:
        pct = (real or 0) / meta
        cor = "var(--status-baixo)" if pct >= frac else "var(--status-critico)"
        pct_txt = f"{pct * 100:.0f}% da meta"
    else:
        cor, pct_txt = "var(--text)", "sem meta"
    fonte_html = f"<div style='font-size:var(--fs-2xs);color:var(--text-faint)'>{escape(fonte)}</div>" if fonte else ""
    return (f"<div class=kpi><div class=n style='color:{cor}'>{_fmt(real, kind)}"
            f"<span style='font-size:14px;color:var(--text-faint)'> / {_fmt(meta, kind)}</span></div>"
            f"<div class=l>{escape(rotulo)}</div><div class=s>{pct_txt}</div>{fonte_html}</div>")


def _visao(conn, request: Request) -> str:
    dados = PF.carrega()
    if not dados:
        return ("<div class=page-head><h1>Financeiro</h1></div>"
                "<section><div class=warn>Planilha de planejamento indisponível no momento — "
                "recarregue em instantes (cache de 10 min).</div></section>")

    hoje = dt.date.today()
    mes_iso = f"{hoje.year:04d}-{hoje.month:02d}"
    meses = dados["meses"]
    i_atual = meses.index(mes_iso) if mes_iso in meses else len(meses) - 1
    idx_hist = list(range(max(0, i_atual - 12), i_atual))
    idx_metas = list(range(i_atual, len(meses)))
    import calendar
    frac = hoje.day / calendar.monthrange(hoje.year, hoje.month)[1]

    def meta(prefixo):
        return PF.linha(dados, prefixo)[i_atual]

    # --- tempo real: funil/bookings AO VIVO (mesma régua do Marketing) ---
    from ..marketing.ui import _funil_oficial
    passou, booked, _tot, receita = _funil_oficial(conn, hoje.replace(day=1), hoje)
    cards = (
        _card_meta("Receita de bookings", receita, meta("Meta Bookings [R$]"), frac, "brl", "Pipedrive ao vivo")
        + _card_meta("Bookings (qtde)", booked, meta("Bookings [Qtde]"), frac, "num", "Pipedrive ao vivo")
        + _card_meta("Leads", passou[0], meta("Leads [Qtde]"), frac, "num", "Pipedrive ao vivo")
        + _card_meta("MQLs", passou[1], meta("MQLs [Qtde]"), frac, "num", "Pipedrive ao vivo")
        + _card_meta("SALs", passou[2], meta("SALs [Qtde]"), frac, "num", "Pipedrive ao vivo")
        + _card_meta("SQLs", passou[3], meta("SQLs [Qtde]"), frac, "num", "Pipedrive ao vivo")
        + _card_meta("Oportunidades", passou[4], meta("Oportunidades [Qtde]"), frac, "num", "Pipedrive ao vivo")
    )
    # recebimento/inadimplência: coluna (Parcial) da planilha — manual até o Omie
    parc = ""
    if dados["parcial_mes"] == mes_iso:
        parc = (
            _card_meta("Recebimento total", PF.parcial(dados, "Recebimento TOTAL [R$]"),
                       meta("Recebimento TOTAL [R$]"), frac, "brl", "planilha (parcial, manual)")
            + _card_meta("Recebimento recorrente", PF.parcial(dados, "Recebimento RECORRENTE [R$]"),
                         meta("Recebimento RECORRENTE [R$]"), frac, "brl", "planilha (parcial, manual)")
            + _card_meta("Inadimplência", PF.parcial(dados, "Inadimplência [R$]"),
                         meta("Inadimplência [R$]"), frac, "brl", "planilha (parcial, manual)")
        )

    mes_nome = _mes_lbl(mes_iso)
    html = (
        "<div class=page-head><h1>Financeiro</h1>"
        "<span class=role-chip>planejamento × realizado — fonte: planilha de planejamento + Pipedrive</span></div>"
        f"<p class=sub>histórico realizado, metas dos próximos meses e o mês corrente em tempo real. "
        f"Hoje é dia {hoje.day} — {frac * 100:.0f}% de {mes_nome} decorrido (o verde/vermelho dos cards compara com esse ritmo).</p>"
        f"<section><h2>{mes_nome} em tempo real × meta</h2>"
        "<p class=secsub>funil e bookings ao vivo do espelho do Pipedrive (regra oficial do funil, defasagem ≤10 min); "
        "recebimento e inadimplência vêm da coluna (Parcial) da planilha — atualização manual do time até o Omie entrar</p>"
        f"<div class=kpis>{cards}</div>"
        + (f"<div class=kpis style='margin-top:10px'>{parc}</div>" if parc else
           "<p class=note>coluna (Parcial) do mês não encontrada na planilha — recebimento/inadimplência parciais indisponíveis.</p>")
        + "</section>"
    )

    # --- histórico realizado ---
    html += ("<section><h2>Histórico realizado</h2>"
             "<p class=secsub>meses fechados, direto da planilha de planejamento</p>"
             + _tabela(dados, [
                 ("Recebimento total", "Recebimento TOTAL [R$]", "brl"),
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
                 ("Parceiros — recebimento", "Parceiros - Recebimento", "brl"),
             ], idx_hist, destaque={"Recebimento total", "Receita de bookings"})
             + "</section>")

    # --- metas dos próximos meses ---
    html += ("<section><h2>Metas — mês corrente e próximos</h2>"
             "<p class=secsub>plano da planilha: bookings por bundle, funil projetado e recebimento</p>"
             + _tabela(dados, [
                 ("Meta de bookings (R$)", "Meta Bookings [R$]", "brl"),
                 ("Bookings (qtde)", "Bookings [Qtde]", "num"),
                 ("B1 — qtde", "B1 - Meta: Booking [Qtde]", "num"),
                 ("B1 — R$", "B1 - Meta: Booking [R$]", "brl"),
                 ("B2 — qtde", "B2 - Meta: Booking [Qtde]", "num"),
                 ("B2 — R$", "B2 - Meta: Booking [R$]", "brl"),
                 ("B3 — qtde", "B3 - Meta: Booking [Qtde]", "num"),
                 ("B3 — R$", "B3 - Meta: Booking [R$]", "brl"),
                 ("B4 — qtde", "B4 - Meta: Booking [Qtde]", "num"),
                 ("B4 — R$", "B4 - Meta: Booking [R$]", "brl"),
                 ("B5 — qtde", "B5 - Meta: Booking [Qtde]", "num"),
                 ("B5 — R$", "B5 - Meta: Booking [R$]", "brl"),
                 ("Leads", "Leads [Qtde]", "num"),
                 ("MQLs", "MQLs [Qtde]", "num"),
                 ("SALs", "SALs [Qtde]", "num"),
                 ("SQLs", "SQLs [Qtde]", "num"),
                 ("Oportunidades", "Oportunidades [Qtde]", "num"),
                 ("Tx. Oportunidade → Booking", "Tx. Oportunidade x Booking", "pct"),
                 ("Recebimento total projetado", "Recebimento TOTAL [R$]", "brl"),
                 ("Recebimento recorrente projetado", "Recebimento RECORRENTE [R$]", "brl"),
                 ("Inadimplência alvo (%)", "Inadimplência [%]", "pct"),
                 ("Churn alvo (%)", "Taxa de cancelamento - TOTAL", "pct"),
             ], idx_metas, destaque={"Meta de bookings (R$)", "Recebimento total projetado"})
             + "</section>")

    # --- saúde da receita recorrente (histórico + projeção) ---
    todos = idx_hist + idx_metas
    html += ("<section><h2>Saúde da receita recorrente</h2>"
             "<p class=secsub>ISR = base ÷ base anterior ×100 · Quick Ratio = nova ÷ perdida · "
             "mesma régua do bloco da Visão central (meses futuros = projeção)</p>"
             + _tabela(dados, [
                 ("Base recorrente B2-B5", "Recebimento Recorrente B2-B5", "brl"),
                 ("Receita nova B2-B5", "Receita Recorrente Nova B2-B5", "brl"),
                 ("Receita perdida (churn) B2-B5", "Receita Recorrente Perdida - Churn B2-B5", "brl"),
                 ("Quick Ratio B2-B5", "Quick Ratio B2-B5", "x"),
                 ("ISR B2-B5", "ÍSR - Índice", "num1"),
                 ("Base Planos Antigos", "Recebimento Recorrente Planos Antigos", "brl"),
                 ("ISR Planos Antigos", "ISR - Planos Antigos", "num1"),
                 ("Base consolidada", "Recebimento Recorrente CONSOLIDADO", "brl"),
                 ("ISR consolidado", "ISR - CONSOLIDADO", "num1"),
                 ("Peso dos antigos no recorrente", "Peso dos Planos Antigos", "pct"),
                 ("Arrasto dos antigos no ISR (pts)", "Arrasto dos Planos Antigos no ISR", "num1"),
             ], todos)
             + "</section>")

    html += ("<p class=foot>Fonte: planilha Planejamento_Receita_2026 (cache 10 min) + espelho do Pipedrive "
             "(re-sincroniza ao abrir, defasagem ≤10 min). Recebimento/inadimplência do mês corrente dependem "
             "da atualização manual da coluna (Parcial) — migram ao Omie quando o Financeiro abrir os dados.</p>")
    return html


@router.get("/financeiro", response_class=HTMLResponse)
def financeiro(request: Request, view: str = Query("visao")):
    A = _deps()
    s, redir = A._require_area(request, "financeiro")
    if redir:
        return redir
    user, _role = s
    if view not in {v for v, _ in _VIEWS}:
        view = "visao"
    # mesmo serve-stale das áreas que leem o funil (Marketing/Vendas/Pré-vendas)
    from ..marketing.ui import _kick_deals_sync
    _kick_deals_sync()
    with A._conn() as c:
        with c.cursor() as cur:
            cur.execute("INSERT INTO audit_log (actor, action, scope) VALUES (%s,'view',%s)",
                        (user, f"financeiro/{view}"))
        content = _visao(c, request)
    from ..marketing.ui import _shell as MS
    html = MS(A, "admin", view, content, usermail=user, help_area="financeiro")
    nav = "<a class='nav-item' href='/'>← Início (central)</a>"
    for v, label in _VIEWS:
        cls = "nav-item active" if v == view else "nav-item"
        nav += f"<a class='{cls}' href='/financeiro?view={v}'>{label}</a>"
    html = (html.replace("Marketing · Tráfego &amp; Leads", "Financeiro · Receita & Metas")
                .replace("Marketing · Tráfego & Leads", "Financeiro · Receita & Metas"))
    html = re.sub(r"<nav>.*?</nav>", "<nav>" + nav + "</nav>", html, count=1, flags=re.S)
    return HTMLResponse(html)
