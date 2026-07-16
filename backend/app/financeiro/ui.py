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

_VIEWS = [("visao", "Planejamento x Realizado"),
          ("receita", "Receita Recorrente")]


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


def _fmt_k(v) -> str:
    if v is None:
        return "—"
    if abs(v) >= 1_000_000:
        return f"{v / 1_000_000:.2f}M".replace(".", ",")
    if abs(v) >= 1_000:
        return f"{v / 1_000:.0f}k"
    return f"{v:.0f}"


def _svg_meses(labels: list[str], barras: list[dict], i_atual: int,
               marcas: list[float | None] | None = None,
               sublabels: list[str] | None = None, H: int = 200) -> str:
    """Gráfico de BARRAS por mês (SVG, mesma linguagem do _grafico_kpi de
    Operações). barras = [{vals, cor, rotulo, frente?}] — a série 'frente'
    desenha mais estreita por cima (ex.: recorrente dentro do total). Meses
    após i_atual = projeção (barra vazada tracejada). marcas = tique de meta
    por mês; sublabels = linha extra sob o rótulo do mês."""
    n = len(labels)
    W, PAD, BASE = max(720, 66 * n), 30, H - 34
    todos = [v for b in barras for v in b["vals"] if v is not None] + [m for m in (marcas or []) if m is not None]
    vmax = (max(todos) if todos else 1) * 1.18 or 1
    slot = (W - 2 * PAD) / n

    def x0(i):
        return PAD + i * slot

    svg = []
    for b in barras:
        largura = slot * (0.34 if b.get("frente") else 0.58)
        for i, v in enumerate(b["vals"]):
            if v is None:
                continue
            h = max(2, v / vmax * (BASE - 26))
            x = x0(i) + (slot - largura) / 2
            futuro = i > i_atual
            estilo = (f"fill:none;stroke:{b['cor']};stroke-width:1.6;stroke-dasharray:4 3;opacity:.75"
                      if futuro else f"fill:{b['cor']};opacity:{.95 if b.get('frente') else .82}")
            titulo = f"{labels[i]} — {b['rotulo']}: {_fmt_k(v)}" + (" (projeção)" if futuro else "")
            svg.append(f"<rect x='{x:.1f}' y='{BASE - h:.1f}' width='{largura:.1f}' height='{h:.1f}' "
                       f"rx='3' style='{estilo}'><title>{escape(titulo)}</title></rect>")
            if not b.get("frente"):
                svg.append(f"<text x='{x0(i) + slot / 2:.1f}' y='{BASE - h - 5:.1f}' text-anchor='middle' "
                           f"font-size='10' fill='var(--text-2)'>{_fmt_k(v)}</text>")
    if marcas:
        for i, m in enumerate(marcas):
            if m is None:
                continue
            y = BASE - max(2, m / vmax * (BASE - 26))
            svg.append(f"<line x1='{x0(i) + slot * 0.12:.1f}' x2='{x0(i) + slot * 0.88:.1f}' y1='{y:.1f}' y2='{y:.1f}' "
                       f"stroke='var(--text-muted)' stroke-width='1.6' stroke-dasharray='3 2'>"
                       f"<title>{escape(labels[i])} — meta: {_fmt_k(m)}</title></line>")
    for i, lb in enumerate(labels):
        peso = "700" if i == i_atual else "400"
        svg.append(f"<text x='{x0(i) + slot / 2:.1f}' y='{BASE + 14}' text-anchor='middle' font-size='10' "
                   f"font-weight='{peso}' fill='var(--text-muted)'>{escape(lb)}</text>")
        if sublabels and sublabels[i]:
            svg.append(f"<text x='{x0(i) + slot / 2:.1f}' y='{BASE + 27}' text-anchor='middle' font-size='9' "
                       f"fill='var(--text-faint)'>{escape(sublabels[i])}</text>")
    return (f"<div style='overflow-x:auto'><svg viewBox='0 0 {W} {H}' "
            f"style='width:100%;min-width:{W * 0.75:.0f}px'>" + "".join(svg) + "</svg></div>")


def _chips_meses(labels: list[str], vals: list[float | None], i_atual: int,
                 verde: float, medio: float, invertido: bool = False) -> str:
    """Faixa de chips mensais p/ percentuais (inadimplência/churn): cor por
    limiar (verde ≤ verde, amarelo ≤ medio, senão vermelho)."""
    out = []
    for i, v in enumerate(vals):
        if v is None:
            cor, txt = "--status-semdados", "—"
        else:
            cor = ("--status-baixo" if v <= verde else
                   "--status-medio" if v <= medio else "--status-critico")
            txt = f"{v * 100:.0f}%"
        fut = "opacity:.55" if i > i_atual else ""
        out.append(f"<div style='text-align:center;{fut}'>"
                   f"<span class=chip style='--c:var({cor})'>{txt}</span>"
                   f"<div style='font-size:9px;color:var(--text-faint);margin-top:3px'>{escape(labels[i])}</div></div>")
    return ("<div style='display:flex;gap:8px;flex-wrap:wrap;justify-content:space-between'>"
            + "".join(out) + "</div>")


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
    # coluna "(Parcial)" da planilha: IGNORADA por ora (Otávio 15/07 — ele a criou
    # só p/ validar nossas fontes; bateu ao centavo: bookings 17/R$139.890 e todas
    # as taxas). Recebimento/inadimplência do mês corrente ficam sem tempo real
    # até o Omie abrir — acompanhados no histórico mensal.
    mes_nome = _mes_lbl(mes_iso)
    html = (
        "<div class=page-head><h1>Financeiro</h1>"
        "<span class=role-chip>planejamento × realizado — fonte: planilha de planejamento + Pipedrive</span></div>"
        f"<p class=sub>histórico realizado, metas dos próximos meses e o mês corrente em tempo real. "
        f"Hoje é dia {hoje.day} — {frac * 100:.0f}% de {mes_nome} decorrido (o verde/vermelho dos cards compara com esse ritmo).</p>"
        f"<section><h2>{mes_nome} em tempo real × meta</h2>"
        "<p class=secsub>funil e bookings ao vivo do espelho do Pipedrive (regra oficial do funil, defasagem ≤10 min); "
        "recebimento e inadimplência não têm fonte em tempo real até o Omie entrar — ver histórico abaixo</p>"
        f"<div class=kpis>{cards}</div>"
        "</section>"
    )

    # --- visão rápida: gráficos (percepção antes das tabelas — pedido 15/07) ---
    lbls = [_mes_lbl(m) for m in meses]
    todos_idx = list(range(len(meses)))
    receb = PF.linha(dados, "Recebimento TOTAL [R$]")
    recor = PF.linha(dados, "Recebimento RECORRENTE [R$]")
    html += ("<section><h2>Recebimento mês a mês</h2>"
             "<p class=secsub>barra clara = recebimento total · barra escura = parte recorrente · "
             "tracejado = projeção da planilha (mês em negrito = atual)</p><div class=card>"
             + _svg_meses(lbls, [
                 {"vals": receb, "cor": "var(--brand)", "rotulo": "recebimento total"},
                 {"vals": recor, "cor": "var(--status-baixo)", "rotulo": "recorrente", "frente": True},
             ], i_atual,
                 sublabels=[(f"{v * 100:.0f}% rec." if v is not None else "")
                            for v in PF.linha(dados, "Recebimento RECORRENTE [%]")])
             + "</div></section>")

    rb_real = PF.linha(dados, "Receita Bookings [R$]")
    rb_meta = PF.linha(dados, "Meta Bookings [R$]")
    rb_qtd = PF.linha(dados, "Bookings [Qtde]")
    cores_rb = []
    for i in todos_idx:
        if i > i_atual or rb_real[i] is None or rb_meta[i] is None:
            cores_rb.append(None)
        else:
            cores_rb.append(rb_real[i] >= rb_meta[i])
    # uma série por cor (bateu/não bateu) p/ o SVG pintar barra a barra
    ok_vals = [rb_real[i] if cores_rb[i] else None for i in todos_idx]
    ruim_vals = [rb_real[i] if cores_rb[i] is False else None for i in todos_idx]
    proj_vals = [rb_meta[i] if i > i_atual else None for i in todos_idx]
    html += ("<section><h2>Bookings × meta mês a mês</h2>"
             "<p class=secsub>verde = meta batida · vermelho = abaixo · tique = meta do mês · "
             "tracejado = meta futura · nº de bookings sob o mês</p><div class=card>"
             + _svg_meses(lbls, [
                 {"vals": ok_vals, "cor": "var(--status-baixo)", "rotulo": "receita de bookings"},
                 {"vals": ruim_vals, "cor": "var(--status-critico)", "rotulo": "receita de bookings"},
                 {"vals": proj_vals, "cor": "var(--text-muted)", "rotulo": "meta"},
             ], i_atual, marcas=[rb_meta[i] if i <= i_atual else None for i in todos_idx],
                 sublabels=[(f"{v:.0f} bk" if v is not None else "") for v in rb_qtd])
             + "</div></section>")

    inad = PF.linha(dados, "Inadimplência [%]")
    churn = PF.linha(dados, "Taxa de cancelamento - TOTAL")
    html += ("<section><h2>Inadimplência e churn</h2>"
             "<p class=secsub>inadimplência: verde ≤4% · amarelo ≤8% — churn: verde ≤5% · amarelo ≤9% "
             "(meses após o atual = alvo, esmaecidos)</p>"
             "<div class=card><div style='font-size:var(--fs-2xs);color:var(--text-muted);text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px'>Inadimplência [%]</div>"
             + _chips_meses(lbls, inad, i_atual, 0.04, 0.08)
             + "<div style='font-size:var(--fs-2xs);color:var(--text-muted);text-transform:uppercase;letter-spacing:.05em;margin:14px 0 6px'>Taxa de cancelamento [%]</div>"
             + _chips_meses(lbls, churn, i_atual, 0.05, 0.09)
             + "</div></section>")

    # --- histórico realizado (detalhe em tabela) ---
    html += ("<section><h2>Histórico realizado — detalhe</h2>"
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

    # saúde da receita recorrente MUDOU p/ aba própria (pedido 15/07)
    html += ("<p class=note style='margin-top:14px'>A <b>Saúde da Receita Recorrente</b> (ISR, Quick Ratio, "
             "crossover B2-B5 × antigos) tem aba própria: "
             "<a href='/financeiro?view=receita' style='color:var(--brand)'>Receita Recorrente</a>.</p>")

    html += ("<p class=foot>Fonte: planilha Planejamento_Receita_2026 (cache 10 min) + espelho do Pipedrive "
             "(re-sincroniza ao abrir, defasagem ≤10 min). Recebimento/inadimplência em tempo real entram "
             "quando os dados do Omie abrirem — por ora, acompanhados no histórico mensal.</p>")
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
        if view == "receita":
            # bloco que morava na Visão central (mudou de casa 15/07)
            content = ("<div class=page-head><h1>Receita Recorrente</h1>"
                       "<span class=role-chip>ISR · Quick Ratio · crossover B2-B5 × antigos</span></div>"
                       + (A._receita_recorrente_html()
                          or "<section><div class=warn>Planilha de planejamento indisponível — recarregue em instantes.</div></section>"))
        else:
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
