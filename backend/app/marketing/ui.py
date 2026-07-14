"""Área de MARKETING no painel — /marketing?view=... (9 abas).

Mesmo padrão do painel de Growth: HTML server-rendered com os tokens de design
(fonte única frontend/design-tokens.css via api._tokens_css), sessão por cookie,
tudo lendo APENAS o cache mkt_* no Postgres (coletores é que falam com APIs).
Router incluído por ÚLTIMO no api.py (lição da ordem de rotas do FastAPI).
"""
from __future__ import annotations

import datetime as dt
from html import escape

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from . import analysis as AN

router = APIRouter()

_VIEWS = [("visao", "Visão Geral"), ("metas", "Metas do Semestre"),
          ("funil", "Funil de Prospecção"),
          ("canais", "Ranking de Canais"), ("origens", "Origem de Leads"),
          ("midia", "Mídia Paga"), ("lag", "Tempo até Resultado"),
          ("planejador", "Planejador"), ("criativos", "Criativos e Públicos")]


def _deps():
    from .. import api as A
    return A


def _mes_atual() -> tuple[dt.date, dt.date]:
    hoje = dt.date.today()
    return hoje.replace(day=1), hoje


def _mes_anterior() -> tuple[dt.date, dt.date]:
    fim = dt.date.today().replace(day=1) - dt.timedelta(days=1)
    return fim.replace(day=1), fim


def _fmt(v, kind="num") -> str:
    if v is None:
        return "<span style='color:var(--text-faint)'>—</span>"
    if kind == "brl":
        return f"R$ {v:,.0f}".replace(",", ".")
    if kind == "pct":
        return f"{v * 100:.1f}%"
    if kind == "dias":
        return f"{v:.0f}d"
    return f"{v:,.0f}".replace(",", ".")


def _shell(A, role: str, view: str, content: str, usermail: str = "",
           help_area: str = "marketing") -> str:
    from ..help_texts import inject_help
    content = inject_help(help_area, view, content)
    nav = "<a class='nav-item' href='/'>← Início (central)</a>" if role == "admin" else ""
    for v, label in _VIEWS:
        cls = "nav-item active" if v == view else "nav-item"
        nav += f"<a class='{cls}' href='/marketing?view={v}'>{label}</a>"
    head = """<!doctype html><html lang=pt-br><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Integracomm IA · Marketing</title>
<link rel=preconnect href="https://fonts.googleapis.com"><link rel=preconnect href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Poppins:wght@500;600;700&display=swap" rel=stylesheet>
<style>__TOKENS__
*{box-sizing:border-box}
body{margin:0;background:var(--bg-app);color:var(--text);font-family:var(--font-body);font-size:var(--fs-base);-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}
.app{display:flex;min-height:100vh}
.rail{width:var(--rail-width);flex-shrink:0;background:var(--bg-rail);border-right:1px solid var(--border);position:sticky;top:0;height:100vh;display:flex;flex-direction:column}
.brand{display:flex;align-items:center;gap:10px;padding:18px 16px 14px}
.brand .logo{width:22px;height:22px;border-radius:50%;background:var(--brand);position:relative;flex-shrink:0}
.brand .logo::after{content:"";position:absolute;width:9px;height:9px;border-radius:50%;background:var(--bg-rail);top:6.5px;left:9px}
.brand .bt{font-family:var(--font-display);font-weight:700;font-size:13.5px;line-height:1.15}
.brand .bs{font-size:10.5px;color:var(--text-muted)}
nav{padding:10px 12px;display:flex;flex-direction:column;gap:2px;flex:1}
.nav-item{display:flex;align-items:center;justify-content:space-between;padding:9px 12px;border-radius:var(--radius-sm);color:var(--text-muted);font-size:var(--fs-base);font-weight:var(--fw-medium)}
.nav-item:hover{background:var(--surface-2);color:var(--text-2)}
.nav-item.active{background:var(--surface-2);color:var(--text);box-shadow:inset 2px 0 0 var(--brand)}
.rail-foot{padding:12px 16px;border-top:1px solid var(--border);font-size:var(--fs-2xs);color:var(--text-muted);line-height:1.5}
main{flex:1;min-width:0;padding:26px 32px 48px;max-width:var(--content-max)}
h1{font-family:var(--font-display);font-weight:700;font-size:var(--fs-h1);letter-spacing:var(--tracking-tight);margin:0}
.sub{font-size:var(--fs-sm);color:var(--text-muted);margin-top:6px}
section{margin-top:var(--space-8)}
h2{font-family:var(--font-display);font-weight:600;font-size:var(--fs-lg);margin:0 0 4px}
.secsub{font-size:var(--fs-sm);color:var(--text-muted);margin:0 0 12px}
.card{background:var(--surface-1);border:1px solid var(--border-mid);border-radius:var(--radius-md);padding:16px 18px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-top:20px}
.kpi{background:var(--surface-1);border:1px solid var(--border-mid);border-radius:var(--radius-md);padding:14px 16px}
.kpi .n{font-family:var(--font-display);font-weight:700;font-size:24px;line-height:1.1}
.kpi .l{font-size:var(--fs-2xs);color:var(--text-muted);text-transform:uppercase;letter-spacing:var(--tracking-label);margin-top:7px}
.kpi .d{font-size:var(--fs-xs);margin-top:4px}
.pos{color:var(--status-baixo)}.neg{color:var(--status-critico)}
table{width:100%;border-collapse:collapse;font-size:var(--fs-sm)}
th{text-align:left;color:var(--text-muted);font-size:var(--fs-2xs);text-transform:uppercase;letter-spacing:var(--tracking-label);font-weight:var(--fw-semibold);padding:8px;border-bottom:1px solid var(--border-strong)}
td{padding:8px;border-bottom:1px solid var(--border);font-variant-numeric:tabular-nums}
th.num,td.num{text-align:right}
tr:hover td{background:var(--surface-2)}
.chip{display:inline-flex;align-items:center;gap:6px;background:color-mix(in srgb,var(--c) 14%,transparent);color:var(--c);border:1px solid color-mix(in srgb,var(--c) 40%,transparent);border-radius:999px;font-size:var(--fs-xs);font-weight:var(--fw-semibold);padding:2px 10px;white-space:nowrap}
.note{font-size:var(--fs-sm);color:var(--text-muted);line-height:1.55}
.warn{background:color-mix(in srgb,var(--status-medio) 8%,transparent);border:1px solid color-mix(in srgb,var(--status-medio) 30%,transparent);border-radius:var(--radius-sm);color:var(--text-2);font-size:var(--fs-sm);padding:9px 12px;line-height:1.5}
.filters{display:flex;flex-wrap:wrap;gap:10px;align-items:end;background:var(--surface-1);border:1px solid var(--border-mid);border-radius:var(--radius-md);padding:12px 14px;margin:14px 0 4px}
.filters label{display:block;font-size:var(--fs-2xs);color:var(--text-muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px}
.filters input,.filters select{background:var(--bg-panel);border:1px solid var(--border-strong);border-radius:var(--radius-sm);color:var(--text);font-family:var(--font-body);font-size:var(--fs-sm);padding:7px 9px}
.filters button{cursor:pointer;background:var(--brand);color:var(--brand-ink);border:none;border-radius:var(--radius-sm);font-family:var(--font-body);font-weight:600;font-size:var(--fs-sm);padding:8px 14px}
.bar{height:8px;background:var(--surface-3);border-radius:4px;overflow:hidden}
.bar>div{height:100%;background:var(--brand)}
.foot{font-size:var(--fs-xs);color:var(--text-faint);margin-top:22px}
</style></head><body>
<div class=app>
 <aside class=rail>
   <div class=brand><div class=logo></div><div><div class=bt>Integracomm IA</div><div class=bs>Marketing · Tráfego & Leads</div></div></div>
   <nav>__NAV__</nav>
   <div class=rail-foot><b>__USERMAIL__</b> · <a href="/logout" style="color:var(--text-muted);text-decoration:underline">sair</a><br>dados via cache local (coleta 06h)</div>
 </aside>
 <main>__CONTENT__</main>
</div></body></html>"""
    return (head.replace("__TOKENS__", A._tokens_css()).replace("__NAV__", nav)
            .replace("__USERMAIL__", escape(usermail or role)).replace("__CONTENT__", content))


# ---------------------------------------------------------------------------
# Aba 1 — Visão Geral
# ---------------------------------------------------------------------------
def _visao(conn) -> str:
    ini, fim = _mes_atual()
    ini_p, fim_p = _mes_anterior()
    atual = AN.ranking_canais(conn, ini, fim)
    prev = AN.ranking_canais(conn, ini_p, fim_p)

    def tot(rows, k):
        return sum(r[k] or 0 for r in rows)

    def kpi(label, a, p, kind="num", inverso=False):
        delta = ""
        if p:
            var = (a - p) / p * 100
            cls = ("neg" if (var > 0) == inverso else "pos") if abs(var) >= 1 else ""
            delta = f"<div class='d {cls}'>{'+' if var >= 0 else ''}{var:.0f}% vs mês ant.</div>"
        return (f"<div class=kpi><div class=n>{_fmt(a, kind)}</div>"
                f"<div class=l>{label}</div>{delta}</div>")

    g_a, g_p = tot(atual, "gasto"), tot(prev, "gasto")
    l_a, l_p = tot(atual, "leads"), tot(prev, "leads")
    b_a, b_p = tot(atual, "bookings"), tot(prev, "bookings")
    o_a, o_p = tot(atual, "oportunidades"), tot(prev, "oportunidades")
    cpl_a = g_a / l_a if l_a else None
    cpl_p = g_p / l_p if l_p else None
    cac_a = g_a / b_a if b_a else None
    cac_p = g_p / b_p if b_p else None
    kpis = (kpi("Gasto (mídia)", g_a, g_p, "brl", inverso=True) + kpi("Leads", l_a, l_p)
            + kpi("CPL", cpl_a, cpl_p, "brl", inverso=True) + kpi("Oportunidades", o_a, o_p)
            + kpi("Bookings", b_a, b_p) + kpi("CAC", cac_a, cac_p, "brl", inverso=True))

    # metas do mês (mkt_goals) × realizado (deals won por plano no mês)
    mes1 = ini
    with conn.cursor() as cur:
        cur.execute("SELECT plano, meta_qtde, meta_valor FROM mkt_goals WHERE mes=%s", (mes1,))
        metas = {p: (q, v) for p, q, v in cur.fetchall()}
        cur.execute("""SELECT COALESCE(substring(produto FROM 'B[1-5]'), 'outros') AS plano, count(*)
                         FROM mkt_deals_attribution
                        WHERE status='won' AND won_time >= %s GROUP BY 1""", (mes1,))
        feito = dict(cur.fetchall())
    linhas = ""
    conv = (b_a / l_a) if l_a else None
    gap_rows = []
    for plano in ("B1", "B2", "B3", "B4", "B5"):
        meta_q = metas.get(plano, (None, None))[0]
        real = feito.get(plano, 0)
        if meta_q is None:
            continue
        pct = real / meta_q if meta_q else None
        destaque = " style='background:color-mix(in srgb,var(--brand) 5%,transparent)'" if plano in ("B3", "B4", "B5") else ""
        barra = f"<div class=bar><div style='width:{min(100, (pct or 0) * 100):.0f}%'></div></div>"
        linhas += (f"<tr{destaque}><td><b>{plano}</b></td><td class=num>{real}</td>"
                   f"<td class=num>{meta_q:.0f}</td><td class=num>{_fmt(pct, 'pct')}</td><td style='min-width:120px'>{barra}</td></tr>")
        falta = max(0, (meta_q or 0) - real)
        if falta and plano in ("B3", "B4", "B5"):
            gap_rows.append((plano, falta))
    gap = ""
    if conv and gap_rows:
        itens = "".join(
            f"<li><b>{p}</b>: faltam {f:.0f} bookings ≈ <b>{f / conv:,.0f} leads</b> no ritmo de conversão atual ({_fmt(conv, 'pct')})</li>".replace(",", ".")
            for p, f in gap_rows)
        itens += ("<li style='margin-top:6px'><b>Alavancas Q3</b>: Indicações convertem sem custo de mídia "
                  "(acompanhe na aba Origem de Leads) e o LinkedIn é o canal natural do público B3-B5 — "
                  "padronizar <code>utm_source=linkedin</code> antes de ativar para o rastreio nascer certo.</li>")
        gap = (f"<section><h2>Gap para a meta (B3-B5)</h2><p class=secsub>quantos leads ainda são "
               f"necessários no ritmo de conversão do mês</p><div class=card><ul class=note style='margin:0;padding-left:18px'>{itens}</ul></div></section>")

    return (f"<h1>Visão Geral</h1><div class=sub>mês atual ({ini.strftime('%d-%m-%Y')} → hoje) vs mês anterior</div>"
            f"<div class=kpis>{kpis}</div>"
            + _funil_vs_meta(conn, ini, fim) +
            f"<section><h2>Progresso vs meta do mês</h2><p class=secsub>metas da planilha financeira · bookings fechados no Pipedrive · B3-B5 em destaque</p>"
            f"<div class=card><table><tr><th>Plano</th><th class=num>Realizado</th><th class=num>Meta</th><th class=num>%</th><th></th></tr>{linhas}</table></div></section>"
            + gap)


# ---------------------------------------------------------------------------
# Aba 2 — Ranking de Canais  /  Aba 3 — Origens
# ---------------------------------------------------------------------------
def _periodo(request: Request) -> tuple[dt.date, dt.date, str]:
    hoje = dt.date.today()
    ini_s = request.query_params.get("ini") or hoje.replace(day=1).isoformat()
    fim_s = request.query_params.get("fim") or hoje.isoformat()
    try:
        ini, fim = dt.date.fromisoformat(ini_s), dt.date.fromisoformat(fim_s)
    except ValueError:
        ini, fim = hoje.replace(day=1), hoje
    form = (f"<div class=filters><div><label>de</label><input type=date name=ini value='{ini}'></div>"
            f"<div><label>até</label><input type=date name=fim value='{fim}'></div>"
            f"<button type=submit>Aplicar</button></div>")
    return ini, fim, form


def _canais(conn, request: Request) -> str:
    ini, fim, form = _periodo(request)
    dias = (fim - ini).days + 1
    prev = AN.ranking_canais(conn, ini - dt.timedelta(days=dias), ini - dt.timedelta(days=1))
    prev_map = {r["canal"]: r for r in prev}
    rows = ""
    for r in AN.ranking_canais(conn, ini, fim):
        p = prev_map.get(r["canal"], {})
        d_leads = ""
        if p.get("leads"):
            var = (r["leads"] - p["leads"]) / p["leads"] * 100
            d_leads = f" <span class='{'pos' if var >= 0 else 'neg'}' style='font-size:var(--fs-2xs)'>({'+' if var >= 0 else ''}{var:.0f}%)</span>"
        roas = f"{r['roas']:.1f}x" if r["roas"] else "—"
        rows += (f"<tr><td><b>{escape(r['canal'])}</b></td><td class=num>{_fmt(r['gasto'], 'brl')}</td>"
                 f"<td class=num>{r['leads']}{d_leads}</td><td class=num>{_fmt(r['cpl'], 'brl')}</td>"
                 f"<td class=num>{_fmt(r['conv_lead_oport'], 'pct')}</td><td class=num>{r['bookings']}</td>"
                 f"<td class=num>{_fmt(r['conv_lead_book'], 'pct')}</td><td class=num>{_fmt(r['receita'], 'brl')}</td>"
                 f"<td class=num>{_fmt(r['cac'], 'brl')}</td><td class=num>{roas}</td></tr>")
    return (f"<h1>Ranking de Canais</h1><div class=sub>período selecionável · comparativo de leads vs período anterior equivalente</div>"
            f"<form method=get action=/marketing><input type=hidden name=view value=canais>{form}</form>"
            f"<section><div class=card><table><tr><th>Canal</th><th class=num>Gasto</th><th class=num>Leads</th>"
            f"<th class=num>CPL</th><th class=num>Lead→Oport</th><th class=num>Bookings</th><th class=num>Lead→Book</th>"
            f"<th class=num>Receita</th><th class=num>CAC</th><th class=num>ROAS</th></tr>{rows}</table>"
            f"<p class='note' style='margin:10px 0 0'>Canais sem custo de mídia aparecem com CPL/CAC “—” (custo zero) — a eficiência relativa está nas conversões. "
            f"“Oportunidade” = deal que avançou do estágio inicial (proxy; o marco exato entra com o histórico de etapas).</p></div></section>")


def _origem_paga(origem) -> bool:
    """Mídia paga = canais com investimento (Meta/Google Ads), pela mesma
    convenção de canal_de/analysis."""
    return AN.canal_de(origem) in ("Meta Ads", "Google Ads")


def _origens(conn, request: Request) -> str:
    ini, fim, form = _periodo(request)
    origem = request.query_params.get("origem") or None
    midia = request.query_params.get("midia") or "todas"
    if midia not in ("todas", "pagas", "organicas"):
        midia = "todas"
    if origem:
        rows = ""
        for r in AN.funil_por_origem(conn, ini, fim, origem):
            rows += (f"<tr><td>{escape(str(r['utm_campaign'] or '—')[:48])}</td><td>{escape(str(r['utm_content'] or '—')[:40])}</td>"
                     f"<td class=num>{r['leads']}</td><td class=num>{r['oport']}</td><td class=num>{r['bookings']}</td>"
                     f"<td class=num>{_fmt(float(r['receita']), 'brl')}</td></tr>")
        return (f"<h1>Origem: {escape(origem)}</h1><div class=sub><a href='/marketing?view=origens&ini={ini}&fim={fim}&midia={midia}' style='color:var(--brand)'>← todas as origens</a></div>"
                f"<section><div class=card><table><tr><th>Campanha</th><th>Criativo</th><th class=num>Leads</th>"
                f"<th class=num>Oport</th><th class=num>Bookings</th><th class=num>Receita</th></tr>{rows}</table></div></section>")
    # filtro de mídia dentro do mesmo form de período
    _MIDIA_OPTS = [("todas", "todas"), ("pagas", "mídia paga (Meta/Google)"),
                   ("organicas", "não pagas (orgânico/indicação/outros)")]
    sel = ("<div><label>mídia</label><select name=midia>"
           + "".join(f"<option value='{v}' {'selected' if midia == v else ''}>{lbl}</option>"
                     for v, lbl in _MIDIA_OPTS) + "</select></div>")
    form = form.replace("<button type=submit>", sel + "<button type=submit>")
    rows = ""
    dados = AN.funil_por_origem(conn, ini, fim)
    if midia == "pagas":
        dados = [r for r in dados if _origem_paga(r["origem"])]
    elif midia == "organicas":
        dados = [r for r in dados if not _origem_paga(r["origem"])]
    med_conv = [(r["bookings"] / r["leads"]) for r in dados if r["leads"] >= 20]
    med = sorted(med_conv)[len(med_conv) // 2] if med_conv else 0
    for r in dados:
        conv = r["bookings"] / r["leads"] if r["leads"] else 0
        oport_pct = r["oport"] / r["leads"] if r["leads"] else 0
        tag = ""
        if r["leads"] >= 20 and conv > med * 1.5 and r["leads"] < 200:
            tag = " <span class=chip style='--c:var(--status-baixo)'>escalar?</span>"
        elif r["leads"] >= 200 and conv < med * 0.5:
            tag = " <span class=chip style='--c:var(--status-alto)'>revisar</span>"
        o = escape(str(r["origem"] or "(vazio)"))
        rows += (f"<tr><td><a href='/marketing?view=origens&origem={o}&ini={ini}&fim={fim}&midia={midia}' style='color:var(--brand)'>{o}</a>{tag}</td>"
                 f"<td class=num>{r['leads']}</td><td class=num>{r['oport']} ({_fmt(oport_pct, 'pct')})</td>"
                 f"<td class=num>{r['bookings']} ({_fmt(conv, 'pct')})</td><td class=num>{_fmt(float(r['receita']), 'brl')}</td></tr>")
    lbl_midia = {"todas": "todas as mídias", "pagas": "só mídia paga", "organicas": "só não pagas"}[midia]
    tot_l = sum(r["leads"] for r in dados)
    tot_b = sum(r["bookings"] for r in dados)
    return (f"<h1>Análise por Origem de Leads</h1><div class=sub>funil lead → oportunidade → booking; clique na origem para ver campanhas e criativos · "
            f"exibindo <b>{lbl_midia}</b>: {tot_l} leads, {tot_b} bookings</div>"
            f"<form method=get action=/marketing><input type=hidden name=view value=origens>{form}</form>"
            f"<section><div class=card><table><tr><th>Origem (utm_source)</th><th class=num>Leads</th>"
            f"<th class=num>Oportunidades</th><th class=num>Bookings</th><th class=num>Receita</th></tr>{rows}</table>"
            f"<p class='note' style='margin:10px 0 0'>“escalar?” = conversão &gt;1,5× a mediana com volume ainda baixo · “revisar” = volume alto com conversão &lt;0,5× a mediana.</p></div></section>")


# ---------------------------------------------------------------------------
# Aba 4 — Tempo até Resultado (lag)
# ---------------------------------------------------------------------------
def _lag(conn) -> str:
    with conn.cursor() as cur:
        cur.execute("""SELECT canal, marco, n_campanhas, p25_dias, mediana_dias, p75_dias, computed_at
                         FROM mkt_campaign_lag_stats ORDER BY canal, marco""")
        stats = cur.fetchall()
    marcos_lbl = {"primeiro_lead": "1º lead", "primeiro_booking": "1º booking", "p50_leads": "50% dos leads"}
    srows = "".join(
        f"<tr><td><b>{'Meta Ads' if c == 'meta' else 'Google Ads'}</b></td><td>{marcos_lbl.get(m, m)}</td>"
        f"<td class=num>{n}</td><td class=num>{p25:.0f}d</td><td class=num><b>{med:.0f}d</b></td><td class=num>{p75:.0f}d</td></tr>"
        for c, m, n, p25, med, p75, _ in stats)

    # curva de acúmulo de leads por dias desde o lançamento (por canal)
    with conn.cursor() as cur:
        cur.execute("""SELECT c.canal, (d.add_time::date - c.data_inicio) AS dias, count(*)
                         FROM mkt_campaigns c JOIN mkt_deals_attribution d ON d.utm_campaign = c.nome
                        WHERE c.data_inicio IS NOT NULL AND d.add_time::date >= c.data_inicio
                          AND (d.add_time::date - c.data_inicio) <= 120
                        GROUP BY 1, 2 ORDER BY 1, 2""", ())
        curvas: dict[str, dict[int, int]] = {}
        for canal, dias, n in cur.fetchall():
            curvas.setdefault(canal, {})[int(dias)] = n
    svg = ""
    cores = {"meta": "var(--brand)", "google": "var(--status-baixo)"}
    for canal, hist in curvas.items():
        total = sum(hist.values())
        if total < 30:
            continue
        acc, pts = 0, []
        for d in range(0, 121):
            acc += hist.get(d, 0)
            pts.append(f"{40 + d * 6.0:.0f},{160 - (acc / total) * 140:.0f}")
        svg += f"<polyline points='{' '.join(pts)}' fill='none' stroke='{cores.get(canal, 'var(--text-muted)')}' stroke-width='2'/>"
        svg += f"<text x='700' y='{158 - list(curvas).index(canal) * 16}' fill='{cores.get(canal, 'var(--text-muted)')}' font-size='11'>{'Meta' if canal == 'meta' else 'Google'}</text>"
    eixo = "".join(f"<text x='{40 + d * 6}' y='176' fill='var(--text-faint)' font-size='10' text-anchor='middle'>{d}</text>"
                   for d in (0, 15, 30, 45, 60, 90, 120))
    grafico = (f"<svg viewBox='0 0 780 185' style='width:100%;max-width:820px'>"
               f"<line x1='40' y1='160' x2='760' y2='160' stroke='var(--border-strong)'/>"
               f"<line x1='40' y1='20' x2='40' y2='160' stroke='var(--border-strong)'/>"
               f"<text x='12' y='25' fill='var(--text-faint)' font-size='10'>100%</text>"
               f"<text x='18' y='163' fill='var(--text-faint)' font-size='10'>0%</text>{eixo}{svg}</svg>")

    base = sorted(AN.lag_por_campanha(conn), key=lambda x: -x["leads"])
    crows = "".join(
        f"<tr><td>{escape(b['campanha'][:52])}</td><td class=num>{b['leads']}</td>"
        f"<td class=num>{_fmt(b['d_primeiro_lead'], 'dias')}</td><td class=num>{_fmt(b['d_primeiro_booking'], 'dias')}</td>"
        f"<td class=num>{_fmt(b['d_50pct_leads'], 'dias')}</td></tr>" for b in base[:20])
    return (f"<h1>Tempo até Resultado</h1><div class=sub>dias entre o lançamento da campanha e cada marco — a base do Planejador</div>"
            f"<section><h2>Lag agregado por canal</h2><p class=secsub>mediana com intervalo p25–p75 (recalculado semanalmente)</p>"
            f"<div class=card><table><tr><th>Canal</th><th>Marco</th><th class=num>Campanhas</th><th class=num>p25</th><th class=num>Mediana</th><th class=num>p75</th></tr>{srows}</table></div></section>"
            f"<section><h2>Curva de acúmulo de leads</h2><p class=secsub>% acumulado de leads por dias desde o lançamento (até 120d)</p><div class=card>{grafico}</div></section>"
            f"<section><h2>Por campanha</h2><p class=secsub>as 20 maiores por volume — material de validação com o gestor</p>"
            f"<div class=card><table><tr><th>Campanha</th><th class=num>Leads</th><th class=num>1º lead</th><th class=num>1º booking</th><th class=num>50% leads</th></tr>{crows}</table></div></section>")


# ---------------------------------------------------------------------------
# Aba 5 — Planejador de Lançamento
# ---------------------------------------------------------------------------
def _planejador(conn, request: Request) -> str:
    qp = request.query_params
    alvo_s = qp.get("alvo")
    canal_ui = qp.get("canal") or "Meta Ads"
    canal_db = _CANAL_DB.get(canal_ui, "meta")
    bundles = ["B1", "B2", "B3", "B4", "B5"]
    pedidos = {b: int(qp.get(f"q{b}") or 0) for b in bundles}
    campos_b = "".join(
        f"<div><label>{b}</label><input type=number name='q{b}' min=0 value='{pedidos[b] or ''}' "
        f"placeholder='0' style='width:64px'></div>" for b in bundles)
    form = (f"<form method=get action=/marketing><input type=hidden name=view value=planejador>"
            f"<div class=filters>{campos_b}"
            f"<div><label>resultado até</label><input type=date name=alvo value='{escape(alvo_s or (dt.date.today() + dt.timedelta(days=60)).isoformat())}'></div>"
            f"<div><label>canal</label><select name=canal>" +
            "".join(f"<option {'selected' if canal_ui == c else ''}>{c}</option>" for c in ("Meta Ads", "Google Ads")) +
            f"</select></div><button type=submit>Planejar</button></div>"
            f"<p class=note style='margin:6px 0 0'>informe quantos bookings quer de cada bundle (ex.: 15 em B1 e 20 em B2) e a data-limite do resultado</p></form>")

    resultado = ""
    total_pedido = sum(pedidos.values())
    if alvo_s and total_pedido:
        try:
            alvo = dt.date.fromisoformat(alvo_s)
        except ValueError:
            alvo = None
        with conn.cursor() as cur:
            cur.execute("SELECT marco, p25_dias, mediana_dias, p75_dias FROM mkt_campaign_lag_stats WHERE canal=%s",
                        (canal_db,))
            lag = {mm: (p25, med, p75) for mm, p25, med, p75 in cur.fetchall()}
        hoje = dt.date.today()
        ini90 = hoje - dt.timedelta(days=90)
        rk = {r["canal"]: r for r in AN.ranking_canais(conn, ini90, hoje)}
        cpl = (rk.get(canal_ui) or {}).get("cpl")
        pref = "meta" if canal_db == "meta" else "google"
        with conn.cursor() as cur:
            # base 180d do canal: leads totais e bookings POR BUNDLE
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
        if alvo and lag.get("primeiro_booking") and cpl and leads_base:
            p25, med, p75 = (float(x) for x in lag["primeiro_booking"])
            d_med = alvo - dt.timedelta(days=int(med))
            linhas_b, recs = "", ""
            tot_leads = tot_orc = 0.0
            for b in bundles:
                q = pedidos[b]
                if not q:
                    continue
                taxa_b = (book_bundle.get(b, 0) / leads_base) if leads_base else 0
                if taxa_b <= 0:
                    linhas_b += (f"<tr><td><b>{b}</b></td><td class=num>{q}</td><td colspan=3 class=note>"
                                 f"sem booking histórico deste bundle no canal (180d) — sem base p/ estimar; "
                                 f"considere Indicações/LinkedIn ou outro canal</td></tr>")
                    continue
                leads_nec = q / taxa_b
                orc = leads_nec * float(cpl)
                tot_leads += leads_nec
                tot_orc += orc
                linhas_b += (f"<tr><td><b>{b}</b></td><td class=num>{q}</td>"
                             f"<td class=num>{_fmt(taxa_b, 'pct')}</td>"
                             f"<td class=num>{leads_nec:,.0f}</td>"
                             f"<td class=num>{_fmt(orc, 'brl')}</td></tr>").replace(",", ".")
                # melhores campanhas e criativos históricos do bundle
                with conn.cursor() as cur:
                    cur.execute("""SELECT utm_campaign, count(*) FROM mkt_deals_attribution
                                    WHERE status='won' AND produto ~ %s AND origem LIKE %s
                                      AND utm_campaign IS NOT NULL
                                    GROUP BY 1 ORDER BY 2 DESC LIMIT 3""", (b, pref + "%"))
                    camps = cur.fetchall()
                    cur.execute("""SELECT utm_content, count(*) FROM mkt_deals_attribution
                                    WHERE status='won' AND produto ~ %s AND origem LIKE %s
                                      AND utm_content IS NOT NULL
                                    GROUP BY 1 ORDER BY 2 DESC LIMIT 3""", (b, pref + "%"))
                    ads = cur.fetchall()
                if camps or ads:
                    li_c = "".join(f"<li>campanha <b>{escape(cc[:52])}</b> ({n} bookings)</li>" for cc, n in camps)
                    li_a = "".join(f"<li>criativo <b>{escape(aa[:52])}</b> ({n} bookings)</li>" for aa, n in ads)
                    recs += (f"<div style='margin-top:10px'><b>{b}</b> — o que já FECHOU esse bundle neste canal:"
                             f"<ul class=note style='margin:4px 0 0;padding-left:18px'>{li_c}{li_a}</ul></div>")
            atraso = ("<div class=warn style='margin-top:10px'>⚠ A data-limite mediana já passou — cenário conservador inviável; "
                      "reduza a meta, antecipe por outro canal ou reveja a data.</div>" if d_med < hoje else "")
            resultado = (
                f"<section><h2>Plano: {total_pedido} bookings via {escape(canal_ui)} até {alvo.strftime('%d-%m-%Y')}</h2>"
                f"<div class=card><table><tr><th>Bundle</th><th class=num>Bookings</th><th class=num>Taxa lead→booking (180d)</th>"
                f"<th class=num>Leads necessários</th><th class=num>Orçamento</th></tr>{linhas_b}"
                f"<tr><td><b>Total</b></td><td class=num><b>{total_pedido}</b></td><td></td>"
                f"<td class=num><b>{tot_leads:,.0f}</b></td><td class=num><b>{_fmt(tot_orc, 'brl')}</b></td></tr></table>".replace(",", ".") +
                f"<table style='margin-top:12px'><tr><th>Janela de lançamento</th><th class=num>Mediana</th><th class=num>p25–p75</th></tr>"
                f"<tr><td>Lançar a campanha até</td><td class=num><b>{d_med.strftime('%d-%m-%Y')}</b></td>"
                f"<td class=num>{(alvo - dt.timedelta(days=int(p25))).strftime('%d-%m')} — {(alvo - dt.timedelta(days=int(p75))).strftime('%d-%m')}</td></tr>"
                f"<tr><td>Lag até 1º booking</td><td class=num>{med:.0f} dias</td><td class=num>{p25:.0f}–{p75:.0f} dias</td></tr></table>"
                + atraso +
                f"<p class='note' style='margin:10px 0 0'>Taxa por bundle = bookings do bundle ÷ leads totais do canal (180d) — reflete o mix real. "
                f"CPL 90d do canal: {_fmt(cpl, 'brl')}. Use o p75 como cenário de risco.</p></div></section>"
                + (f"<section><h2>Estratégias e criativos recomendados</h2><p class=secsub>histórico de quem já converteu cada bundle (base p/ replicar/iterar — a versão via Claude entra com os créditos de API)</p><div class=card>{recs}</div></section>" if recs else ""))
        else:
            resultado = "<section><div class=warn>Sem base histórica suficiente neste canal (lag, CPL ou leads indisponíveis).</div></section>"
    return (f"<h1>Planejador de Lançamento</h1><div class=sub>meta por bundle + data — o planejador inverte o lag e responde quando lançar, quantos leads, que orçamento e com quais estratégias</div>"
            + form + resultado)


_CANAL_DB = {"Meta Ads": "meta", "Google Ads": "google"}


# ---------------------------------------------------------------------------
# Aba 6 — Criativos e Públicos
# ---------------------------------------------------------------------------
def _criativos(conn, request: Request) -> str:
    publico = request.query_params.get("publico") or ""
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT adset_name FROM mkt_insights_daily WHERE canal='meta' AND adset_name IS NOT NULL ORDER BY 1")
        publicos = [r[0] for r in cur.fetchall()]
        filtro = "AND i.adset_name = %s" if publico else ""
        args = [publico] if publico else []
        cur.execute(f"""
            SELECT i.ad_name, max(i.adset_name) AS pub, sum(i.spend) AS gasto, sum(i.leads) AS leads,
                   count(DISTINCT d.deal_id) FILTER (WHERE d.stage_id >= 3 OR d.status IN ('won','lost')) AS oport,
                   count(DISTINCT d.deal_id) FILTER (WHERE d.status='won') AS books
              FROM mkt_insights_daily i
              LEFT JOIN mkt_deals_attribution d ON d.utm_content = i.ad_name
             WHERE i.canal='meta' AND i.ad_name IS NOT NULL {filtro}
             GROUP BY i.ad_name HAVING sum(i.leads) >= 5
             ORDER BY (sum(i.spend) / NULLIF(sum(i.leads),0)) ASC NULLS LAST LIMIT 30""", args)
        rows = cur.fetchall()
    sel = "".join(f"<option {'selected' if p == publico else ''}>{escape(p)}</option>" for p in publicos[:80])
    trs = ""
    for ad, pub, gasto, leads, oport, books in rows:
        cpl = float(gasto) / leads if leads else None
        conv = oport / leads if leads else None
        trs += (f"<tr><td>{escape((ad or '')[:46])}</td><td>{escape((pub or '')[:30])}</td>"
                f"<td class=num>{_fmt(float(gasto), 'brl')}</td><td class=num>{leads}</td>"
                f"<td class=num>{_fmt(cpl, 'brl')}</td><td class=num>{_fmt(conv, 'pct')}</td><td class=num>{books}</td></tr>")

    # histórico de testes (ad-insightify) + ideias heurísticas
    testes, ideias = "", ""
    try:
        from ..sources import creative_history as CH
        runs = CH.runs()
        trs2 = "".join(
            f"<tr><td>{escape((r.get('ad_name') or '')[:44])}</td><td>{escape((r.get('adset_name') or '')[:28])}</td>"
            f"<td>{escape(r.get('creative_type') or '—')}</td><td class=num>{escape(str(r.get('started_at') or '')[:10])}</td>"
            f"<td class=num>{r.get('days_active') or '—'}</td></tr>"
            for r in sorted(runs, key=lambda x: str(x.get("started_at") or ""), reverse=True)[:15])
        testes = (f"<section><h2>Histórico de testes (ad-insightify)</h2><p class=secsub>{len(runs)} rodadas registradas · 15 mais recentes</p>"
                  f"<div class=card><table><tr><th>Anúncio</th><th>Público</th><th>Formato</th><th class=num>Início</th><th class=num>Dias ativo</th></tr>{trs2}</table></div></section>")
        # heurística: formato × público testados vs não testados
        vistos = {(r.get("creative_type"), r.get("adset_name")) for r in runs}
        formatos = {r.get("creative_type") for r in runs if r.get("creative_type")}
        pubs_top = [p for p, *_ in [(pub, 1) for _, pub, *_r in rows[:8] if pub]][:6]
        sug = [f"<li>Formato <b>{escape(f)}</b> ainda não testado no público <b>{escape(p[:34])}</b> — vizinhos testados performam bem</li>"
               for f in formatos for p in pubs_top if (f, p) not in vistos][:6]
        if sug:
            ideias = (f"<section><h2>Ideias (v1 heurística)</h2><p class=secsub>combinações formato × público ainda não testadas, "
                      f"priorizadas pelos top performers — a versão via Claude entra quando os créditos de API estiverem disponíveis</p>"
                      f"<div class=card><ul class=note style='margin:0;padding-left:18px'>{''.join(sug)}</ul></div></section>")
    except Exception:  # noqa: BLE001 — histórico fora do ar não derruba a aba
        testes = "<section><div class=warn>Histórico do ad-insightify indisponível no momento.</div></section>"

    return (f"<h1>Criativos e Públicos</h1><div class=sub>ranking por CPL (mín. 5 leads), filtrável por público; conversão via atribuição do Pipedrive (utm_content)</div>"
            f"<form method=get action=/marketing><input type=hidden name=view value=criativos>"
            f"<div class=filters><div><label>público (adset)</label><select name=publico><option value=''>todos</option>{sel}</select></div>"
            f"<button type=submit>Filtrar</button></div></form>"
            f"<section><div class=card><table><tr><th>Criativo</th><th>Público</th><th class=num>Gasto</th>"
            f"<th class=num>Leads</th><th class=num>CPL</th><th class=num>Lead→Oport</th><th class=num>Bookings</th></tr>{trs}</table></div></section>"
            + testes + ideias)


# ---------------------------------------------------------------------------
# Gráficos SVG (helpers)
# ---------------------------------------------------------------------------
def _svg_line(series, labels, fmt_y=None):
    """Linhas sobre eixo comum. series=[(nome, cor, valores)], labels=eixo X."""
    fmt_y = fmt_y or (lambda v: f"{v:,.0f}".replace(",", "."))
    if not labels or not any(vals for _, _, vals in series):
        return "<p class=note>sem dados no período</p>"
    W, H, L, B = 780, 190, 46, 30
    vmax = max((max(v) for _, _, v in series if v), default=1) or 1
    n = max(len(labels) - 1, 1)
    out = [f"<svg viewBox='0 0 {W} {H + 40}' style='width:100%;max-width:840px'>"]
    for fr in (0.5, 1.0):
        y = H - B - (H - B - 16) * fr
        out.append(f"<line x1='{L}' y1='{y:.0f}' x2='{W - 8}' y2='{y:.0f}' stroke='var(--border)' stroke-dasharray='3 4'/>")
        out.append(f"<text x='{L - 6}' y='{y + 4:.0f}' fill='var(--text-faint)' font-size='10' text-anchor='end'>{fmt_y(vmax * fr)}</text>")
    out.append(f"<line x1='{L}' y1='{H - B}' x2='{W - 8}' y2='{H - B}' stroke='var(--border-strong)'/>")
    step = max(1, len(labels) // 8)
    for i, lb in enumerate(labels):
        if i % step == 0:
            x = L + (W - 8 - L) * i / n
            out.append(f"<text x='{x:.0f}' y='{H - B + 15}' fill='var(--text-faint)' font-size='10' text-anchor='middle'>{escape(lb)}</text>")
    for si, (nome, cor, vals) in enumerate(series):
        if not vals:
            continue
        pts = " ".join(f"{L + (W - 8 - L) * i / n:.0f},{H - B - (H - B - 16) * (v / vmax):.0f}"
                       for i, v in enumerate(vals))
        out.append(f"<polyline points='{pts}' fill='none' stroke='{cor}' stroke-width='2'/>")
        for i, v in enumerate(vals):  # tooltip nativo: <circle><title>
            x = L + (W - 8 - L) * i / n
            y = H - B - (H - B - 16) * (v / vmax)
            out.append(f"<circle cx='{x:.0f}' cy='{y:.0f}' r='7' fill='transparent' stroke='none'>"
                       f"<title>{escape(labels[i])}: {fmt_y(v)}</title></circle>"
                       f"<circle cx='{x:.0f}' cy='{y:.0f}' r='2.5' fill='{cor}'/>")
        # legenda ABAIXO do gráfico (no topo chocava com as linhas)
        lx = L + 4 + si * 190
        out.append(f"<circle cx='{lx}' cy='{H + 26}' r='4' fill='{cor}'/>")
        out.append(f"<text x='{lx + 9}' y='{H + 30}' fill='{cor}' font-size='11' font-weight='600'>{escape(nome)}</text>")
    out.append("</svg>")
    return "".join(out)


# ---------------------------------------------------------------------------
# Aba — Funil de Prospecção
# ---------------------------------------------------------------------------
# Taxonomia OFICIAL do time (mesma dos apps Lovable): Lead, MQL, SAL, SQL,
# Oportunidade, Booking — réguas em _funil_oficial (abaixo).
_FUNIL_ETAPAS = [("Lead", 0), ("MQL", 1), ("SAL", 2),
                 ("SQL", 3), ("Oportunidade", 4)]
# definições OFICIAIS do time (copiadas do dashboard Lovable, 14/07/26)
_FUNIL_DEFS = {
    "Lead": "cliente potencial que deixou ao menos 1 informação de contato",
    "MQL": "lead que passou por ao menos um processo de qualificação (desconta os perdidos por lead score baixo)",
    "SAL": "MQL que cumpre os requisitos e foi aceito pelo time de SDR (desconta os desqualificados)",
    "SQL": "MQL que cumpre os requisitos e agendou uma reunião (deal na mão de um closer)",
    "Oportunidade": "MQL que compareceu à reunião de vendas (campo Dia Oportunidade)",
    "Booking": "cliente com contrato de serviços assinado e pago (won no Pipedrive)",
}
_ETAPAS_PLANO = ["Lead", "MQL", "SAL", "SQL", "Oportunidade", "Booking"]


# Régua OFICIAL do funil (14/07/26) = a MESMA do "Dashboard - Comercial
# (Pipedrive)" do time — extraída do código do app Lovable (useFunnelDashboard
# .ts) e validada contra os números que a gestão confere no Pipedrive:
#   Lead = deals CRIADOS no período (add_time, corte BRT)
#   MQL  = Lead menos perdidos c/ motivo em _MQL_EXCLUI
#   SAL  = Lead menos perdidos c/ motivo de desqualificação (_SAL_EXCLUI)
#   SQL  = Lead cujo DONO ATUAL é closer (handoff SDR→closer = agendou reunião)
#   Oportunidade = campo "Dia Oportunidade" no período (compareceu; NÃO é coorte
#                  — por isso pode superar SQL)
#   Booking = won no período + receita
# ATENÇÃO: MQL/SAL/SQL são RETROATIVOS — desqualificar ou trocar o dono de um
# lead move o número do mês em que o lead ENTROU; funil de mês fechado respira.
_MQL_EXCLUI = {"Lead Score Baixo - Não contactamos"}
_SAL_EXCLUI = {"Não tem estoque", "Lead Score Baixo - Não contactamos",
               "Não é empresário", "Tentativas de reagendamentos excedidas",
               "Tentativas de contato excedidas", "Dropshipping", "Sem retorno"}


def _funil_oficial(conn, a: dt.date, b: dt.date) -> tuple[list[int], int, int, float]:
    """Funil com a régua oficial do time (comentário acima). Cortes em HORÁRIO
    DE BRASÍLIA (o dashboard/Insights cortam assim; em UTC os leads de fim de
    noite caíam no dia errado). → (passou[Lead,MQL,SAL,SQL,Oport], bookings,
    total_leads, receita)."""
    from ..team_config import casador
    # régua do SQL usa a lista COMPLETA de closers (ativos + desligados),
    # igual ao SQL_CLOSERS do app do time; edição = Painel Administrativo
    eh_closer = casador(conn, "vendas")
    a, fim = f"{a} 00:00-03", f"{b + dt.timedelta(days=1)} 00:00-03"
    with conn.cursor() as cur:
        cur.execute("""SELECT COALESCE(lost_reason, ''), COALESCE(owner_name, ''), count(*)
                         FROM mkt_deals_attribution
                        WHERE add_time >= %s AND add_time < %s GROUP BY 1, 2""", (a, fim))
        total = mql = sal = sql_n = 0
        for reason, owner, n in cur.fetchall():
            total += n
            r = reason.strip()
            if r not in _MQL_EXCLUI:
                mql += n
            if r not in _SAL_EXCLUI:
                sal += n
            if eh_closer(owner):
                sql_n += n
        cur.execute("""SELECT count(*) FROM mkt_deals_attribution
                        WHERE oport_time >= %s AND oport_time < %s""", (a, fim))
        oport = cur.fetchone()[0]
        if not oport:
            # oport_time ainda não populado (coletor passou a trazer o campo
            # Dia Oportunidade em 14/07) — entrada em Negociação (7) é o proxy
            # que casa na prática até a primeira rodada de sync backfillar
            cur.execute("""SELECT count(DISTINCT deal_id) FROM mkt_stage_events
                            WHERE entered_at >= %s AND entered_at < %s AND stage_id = 7""",
                        (a, fim))
            oport = cur.fetchone()[0]
        passou = [total, mql, sal, sql_n, oport]
        cur.execute("""SELECT count(*), COALESCE(sum(valor), 0) FROM mkt_deals_attribution
                        WHERE status='won' AND won_time >= %s AND won_time < %s""", (a, fim))
        booked, receita = cur.fetchone()
    return passou, booked, total, float(receita)


def _plan_funil(conn, meses: list[dt.date]) -> dict[dt.date, dict[str, dict]]:
    """Plano mensal da planilha de metas (mkt_plan_funnel) para os meses dados."""
    with conn.cursor() as cur:
        cur.execute("""SELECT mes, etapa, qtde, custo_unit, investimento
                         FROM mkt_plan_funnel WHERE mes = ANY(%s)""", (meses,))
        out: dict[dt.date, dict[str, dict]] = {}
        for mes, etapa, q, c, i in cur.fetchall():
            out.setdefault(mes, {})[etapa] = {
                "qtde": float(q) if q is not None else None,
                "custo": float(c) if c is not None else None,
                "inv": float(i) if i is not None else None}
        return out


def _dias_mes(mes: dt.date) -> int:
    import calendar
    return calendar.monthrange(mes.year, mes.month)[1]


def _funil_vs_meta(conn, ini: dt.date, fim: dt.date) -> str:
    """Seção "Funil do mês vs meta": realizado da coorte × meta de volume da
    planilha, com marcador do ritmo esperado (fração do mês decorrida)."""
    mes_ref = ini.replace(day=1)
    plan = _plan_funil(conn, [mes_ref]).get(mes_ref) or {}
    if not any((v.get("qtde") is not None) for v in plan.values()):
        return ""
    passou, booked, _total, _rec = _funil_oficial(conn, ini, fim)
    reais = passou + [booked]
    frac = min(1.0, ((fim - ini).days + 1) / _dias_mes(mes_ref))
    rows = ""
    for i, etapa in enumerate(_ETAPAS_PLANO):
        meta = (plan.get(etapa) or {}).get("qtde")
        if meta is None:
            continue
        real = reais[i]
        pct = real / meta if meta else None
        cls = "" if pct is None else ("pos" if pct >= frac else ("neg" if pct < frac * 0.75 else ""))
        barra = (f"<div class=bar style='position:relative;overflow:visible'>"
                 f"<div style='width:{min(100, (pct or 0) * 100):.0f}%'></div>"
                 f"<div title='ritmo esperado ({frac * 100:.0f}% do mês)' style='position:absolute;left:{frac * 100:.0f}%;top:-3px;bottom:-3px;width:2px;background:var(--text-muted)'></div></div>")
        rows += (f"<tr title='{_FUNIL_DEFS.get(etapa, '')}'><td>{etapa}</td><td class=num>{real}</td>"
                 f"<td class=num>{meta:.0f}</td><td class='num {cls}'>{_fmt(pct, 'pct')}</td>"
                 f"<td style='min-width:140px'>{barra}</td></tr>")
    if not rows:
        return ""
    return (f"<section><h2>Funil do mês vs meta ({mes_ref.strftime('%m-%Y')})</h2>"
            f"<p class=secsub>metas de volume da planilha de metas do Marketing · traço vertical = ritmo esperado ({frac * 100:.0f}% do mês decorrido)</p>"
            f"<div class=card><table><tr><th>Etapa</th><th class=num>Realizado</th><th class=num>Meta do mês</th><th class=num>% da meta</th><th></th></tr>{rows}</table>"
            f"<p class='note' style='margin:10px 0 0'>Realizado = coorte de deals criados no mês (Pipedrive). Detalhe completo do semestre na aba <a href='/marketing?view=metas' style='color:var(--brand)'>Metas do Semestre</a>.</p></div></section>")


# cores do funil = mesma paleta do app Lovable do time (Lead amarelo → Booking verde)
_FUNIL_CORES = {"Lead": "#d9b532", "MQL": "#dd8a3d", "SAL": "#e06060", "SQL": "#b57fdc",
                "Oportunidade": "#5b8def", "Booking": "#3fce8f"}


def funil_visual_html(seq: list[tuple[str, int]], total: int,
                      receita_book: float | None = None) -> str:
    """Funil visual COMPARTILHADO (Marketing, Pré-vendas e Vendas): barras
    centradas com largura proporcional (modelo do app Lovable do time), pílula
    de conversão vs etapa anterior entre elas e, ao lado, o resumo com
    definição oficial, TX e TX Lead. seq = [(etapa, valor), ...]."""
    barras, resumo_rows = "", ""
    for i, (nome, n) in enumerate(seq):
        taxa = (n / seq[i - 1][1]) if i and seq[i - 1][1] else None
        tx_lead = n / total if total and i else None
        if i:
            barras += (f"<div style='text-align:center;margin:7px 0'><span style='background:var(--surface-3);"
                       f"border:1px solid var(--border-strong);border-radius:999px;padding:2px 12px;"
                       f"font-size:var(--fs-xs);color:var(--text-2)'>{_fmt(taxa, 'pct') if taxa is not None else '—'} conv.</span></div>")
        w = min(100.0, max(30.0, (n / total * 100) if total else 30.0))
        extra = (f"<div style='font-size:var(--fs-xs);font-weight:600;opacity:.8'>{_fmt(receita_book, 'brl')}</div>"
                 if nome == "Booking" and receita_book is not None else "")
        barras += (f"<div title='{escape(_FUNIL_DEFS.get(nome, ''))}' style='width:{w:.1f}%;margin:0 auto;"
                   f"background:{_FUNIL_CORES.get(nome, 'var(--surface-3)')};border-radius:10px;padding:11px 16px;display:flex;"
                   f"justify-content:space-between;align-items:center;gap:10px;color:#16181d'>"
                   f"<b style='font-size:var(--fs-md)'>{nome}</b>"
                   f"<div style='text-align:right'><span style='font-family:var(--font-display);"
                   f"font-weight:700;font-size:21px'>{n}</span>{extra}</div></div>")
        td = "padding:9px 8px;border-bottom:1px solid var(--border);font-size:var(--fs-sm)"
        resumo_rows += (f"<tr><td style='{td};white-space:nowrap'><span style='display:inline-block;width:9px;"
                        f"height:9px;border-radius:50%;background:{_FUNIL_CORES.get(nome, 'var(--surface-3)')};margin-right:7px'></span><b>{nome}</b></td>"
                        f"<td style='{td};color:var(--text-muted);line-height:1.4'>{escape(_FUNIL_DEFS.get(nome, ''))}</td>"
                        f"<td style='{td};text-align:right;font-variant-numeric:tabular-nums'><b>{n}</b></td>"
                        f"<td style='{td};text-align:right'>{_fmt(taxa, 'pct') if taxa is not None else '—'}</td>"
                        f"<td style='{td};text-align:right'>{_fmt(tx_lead, 'pct') if tx_lead is not None else '—'}</td></tr>")
    th_r = "".join(f"<th style='text-align:{al};padding:8px;border-bottom:1px solid var(--border-strong);"
                   f"color:var(--text-muted);font-size:var(--fs-2xs);text-transform:uppercase;letter-spacing:var(--tracking-label)'>{h}</th>"
                   for h, al in (("Etapa", "left"), ("Definição", "left"), ("Total", "right"),
                                 ("TX", "right"), ("TX Lead", "right")))
    return (
        "<div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:14px;align-items:start'>"
        f"<div class=card>{barras}</div>"
        f"<div class=card><table style='width:100%;border-collapse:collapse'><tr>{th_r}</tr>{resumo_rows}</table>"
        "<p class='note' style='margin:10px 0 0'>TX = conversão sobre a etapa ANTERIOR · TX Lead = sobre o total de leads.</p></div></div>")

_FUNIL_SUGESTOES = {
    "MQL": "Gargalo na VELOCIDADE de resposta: lead sem contato esfria em horas — revisar o SLA do primeiro toque (referência: <15 min em horário comercial) e a automação de disparo.",
    "SAL": "Muitos contatos sem conexão: variar canal (WhatsApp + ligação + e-mail), horários alternados e cadência de 5-7 tentativas antes de descartar.",
    "SQL": "Perda alta na qualificação: filtrar curiosos ainda na LP/formulário e revisar o roteiro — campanhas com taxa baixa aqui pedem ajuste de público, não de verba.",
    "Oportunidade": "SQL que não vira reunião/proposta: agenda self-service (link direto), menos fricção de horários e confirmação por WhatsApp na véspera (no-show é o vilão típico).",
    "Booking": "Oportunidade que não fecha: revisar proposta/ancoragem e follow-up estruturado — a maioria fecha entre o 2º e o 4º contato pós-reunião.",
}


def _funil(conn, request: Request) -> str:
    ini, fim, form = _periodo(request)
    dias = (fim - ini).days + 1
    ini_p, fim_p = ini - dt.timedelta(days=dias), ini - dt.timedelta(days=1)

    passou, booked, total, receita_book = _funil_oficial(conn, ini, fim)
    passou_p, booked_p, total_p, _rec_p = _funil_oficial(conn, ini_p, fim_p)

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
    # conversão COMPOSTA MQL→Booking (fim a fim; meta = "Tx. MQL x Booking" da planilha)
    mql_n = passou[1]
    taxa_mb = booked / mql_n if mql_n else None
    meta_mb = metas_taxa.get("MQL→Booking")

    linhas, barras = "", ""
    pior, pior_taxa = None, 1.0
    for i, (nome, _) in enumerate(_FUNIL_ETAPAS):
        n = passou[i]
        taxa = n / passou[i - 1] if i and passou[i - 1] else None
        taxa_p = (passou_p[i] / passou_p[i - 1]) if i and passou_p[i - 1] else None
        delta = ""
        if taxa is not None and taxa_p:
            d = (taxa - taxa_p) * 100
            cls = "pos" if d >= 0 else "neg"
            sinal = "+" if d >= 0 else ""
            delta = f"<span class='{cls}' style='font-size:var(--fs-2xs)'> ({sinal}{d:.1f}pp)</span>"
        meta_e = metas_taxa.get(nome)
        meta_td = "—"
        if meta_e is not None and taxa is not None:
            ok_e = taxa >= meta_e
            cls_e = "pos" if ok_e else "neg"
            meta_td = f"<span class='{cls_e}'>{_fmt(meta_e, 'pct')}</span>"
        elif meta_e is not None:
            meta_td = _fmt(meta_e, 'pct')
        if taxa is not None and meta_e is not None and taxa < meta_e and passou[i - 1] >= 20 and (taxa / meta_e) < pior_taxa:
            pior, pior_taxa = nome, taxa  # prioriza a etapa mais LONGE da própria meta
        elif taxa is not None and not metas_taxa and taxa < pior_taxa and passou[i - 1] >= 20:
            pior, pior_taxa = nome, taxa
        meta_q = (plan_mes.get(nome) or {}).get("qtde")
        linhas += (f"<tr title='{_FUNIL_DEFS.get(nome, '')}'><td>{nome}</td><td class=num>{n}</td>"
                   f"<td class=num style='color:var(--text-muted)'>{_fmt(meta_q)}</td>"
                   f"<td class=num>{_fmt(taxa, 'pct') if taxa is not None else '—'}{delta}</td>"
                   f"<td class=num>{meta_td}</td></tr>")
    # ---- funil visual compartilhado (funil_visual_html)
    seq = [(nome, passou[i]) for i, (nome, _) in enumerate(_FUNIL_ETAPAS)] + [("Booking", booked)]
    funil_visual = funil_visual_html(seq, total, receita_book)
    taxa_final = booked / passou[4] if passou[4] else None
    meta_bk = metas_taxa.get("Booking")
    meta_bk_td = "—"
    if meta_bk is not None and taxa_final is not None:
        cls_bk = "pos" if taxa_final >= meta_bk else "neg"
        meta_bk_td = f"<span class='{cls_bk}'>{_fmt(meta_bk, 'pct')}</span>"
    meta_q_bk = (plan_mes.get("Booking") or {}).get("qtde")
    linhas += (f"<tr><td><b>Booking (won)</b></td><td class=num><b>{booked}</b></td>"
               f"<td class=num style='color:var(--text-muted)'>{_fmt(meta_q_bk)}</td>"
               f"<td class=num><b>{_fmt(taxa_final, 'pct')}</b></td><td class=num>{meta_bk_td}</td></tr>")
    mb_meta_td = "—"
    if meta_mb is not None and taxa_mb is not None:
        cls_mb = "pos" if taxa_mb >= meta_mb else "neg"
        mb_meta_td = f"<span class='{cls_mb}'>{_fmt(meta_mb, 'pct')}</span>"
    elif meta_mb is not None:
        mb_meta_td = _fmt(meta_mb, "pct")
    linhas += (f"<tr title='taxa fim a fim: de todo MQL, quantos viram contrato — resume o funil inteiro numa conversão só'>"
               f"<td style='border-top:2px solid var(--border-strong)'><b>MQL → Booking</b> "
               f"<span style='color:var(--text-faint);font-size:var(--fs-2xs)'>(composta)</span></td>"
               f"<td class=num style='border-top:2px solid var(--border-strong)'>{booked}<span style='color:var(--text-faint)'>/{mql_n}</span></td>"
               f"<td class=num style='border-top:2px solid var(--border-strong);color:var(--text-muted)'>—</td>"
               f"<td class=num style='border-top:2px solid var(--border-strong)'><b>{_fmt(taxa_mb, 'pct') if taxa_mb is not None else '—'}</b></td>"
               f"<td class=num style='border-top:2px solid var(--border-strong)'>{mb_meta_td}</td></tr>")

    # formulário de metas de taxa do mês (edição inline pelo gestor)
    etapas_meta = [nome for nome, _ in _FUNIL_ETAPAS[1:]] + ["Booking"]
    campos = "".join(
        f"<div><label>{e}</label><input type=number step=0.1 min=0 max=100 name='meta_{i}' "
        f"value='{metas_taxa.get(e, '') if metas_taxa.get(e) is None else round(metas_taxa[e] * 100, 1)}' "
        f"placeholder='%' style='width:86px'></div>"
        for i, e in enumerate(etapas_meta))
    form_metas = (f"<section><h2>Metas de taxa do mês ({mes_ref.strftime('%m-%Y')})</h2>"
                  f"<p class=secsub>conversão-alvo de cada etapa, em % — pré-preenchidas pela planilha de metas do Marketing; o que você salvar aqui prevalece</p>"
                  f"<form method=post action='/marketing/funil-metas'><div class=filters>"
                  f"<input type=hidden name=mes value='{mes_ref.isoformat()}'>"
                  f"<input type=hidden name=ini value='{ini.isoformat()}'><input type=hidden name=fim value='{fim.isoformat()}'>"
                  + campos + "<button type=submit>Salvar metas</button></div></form></section>")

    kpi_mb = ""
    if taxa_mb is not None:
        cor_mb = ""
        if meta_mb is not None:
            cor_mb = (" style='color:var(--status-baixo)'" if taxa_mb >= meta_mb
                      else " style='color:var(--status-critico)'")
        lbl_mb = "MQL → booking" + (f" (meta {_fmt(meta_mb, 'pct')})" if meta_mb is not None else "")
        kpi_mb = (f"<div class=kpi><div class=n{cor_mb}>{_fmt(taxa_mb, 'pct')}</div>"
                  f"<div class=l>{lbl_mb}</div></div>")
    meta_html = ""
    if conv_nec is not None:
        ok = conv_atual >= conv_nec
        cor = "var(--status-baixo)" if ok else "var(--status-critico)"
        meta_html = ("<div class=kpis>"
                     f"<div class=kpi><div class=n>{_fmt(conv_atual, 'pct')}</div><div class=l>conversão lead→booking</div></div>"
                     f"<div class=kpi><div class=n style='color:{cor}'>{_fmt(conv_nec, 'pct')}</div><div class=l>necessária p/ a meta ({meta_book:.0f} book/mês)</div></div>"
                     + kpi_mb +
                     f"<div class=kpi><div class=n>{booked}</div><div class=l>bookings da coorte</div></div>"
                     f"<div class=kpi><div class=n>{total}</div><div class=l>leads no período</div></div></div>")
    elif kpi_mb:
        meta_html = f"<div class=kpis>{kpi_mb}</div>"
    sugestoes = ""
    if conv_nec is not None and conv_atual < conv_nec:
        itens = ""
        if pior and pior in _FUNIL_SUGESTOES:
            itens += f"<div class='sug-item'><b>Maior perda: {pior} ({_fmt(pior_taxa, 'pct')})</b> — {_FUNIL_SUGESTOES[pior]}</div>"
        if conv_atual:
            deficit = (conv_nec / conv_atual - 1) * 100
            leads_nec = f"{meta_book / conv_atual:,.0f}".replace(",", ".")
            itens += (f"<div class='sug-item'>Para a meta no volume atual, a conversão precisa subir <b>{deficit:.0f}%</b>. "
                      f"Alternativa: manter a conversão e crescer o topo — <b>{leads_nec} leads/mês</b> "
                      "(use o Planejador, que já considera lag e CPL).</div>")
        itens += "<div class='sug-item'>Priorize origens com conversão acima da mediana (aba Origem de Leads, chip “escalar?”) — mudar o mix é mais barato que consertar etapa.</div>"
        sugestoes = ("<section><h2>Como alcançar a meta</h2><p class=secsub>sugestões determinísticas sobre a etapa de maior perda "
                     "(a versão via Claude entra quando os créditos de API estiverem disponíveis)</p><div class=card>" + itens +
                     "<style>.sug-item{padding:8px 0;border-top:1px solid var(--border);font-size:var(--fs-sm);line-height:1.6;color:var(--text-2)}.sug-item:first-child{border-top:none}</style></div></section>")

    return (f"<h1>Funil de Prospecção</h1><div class=sub>régua OFICIAL do dashboard do time (Pipedrive): Lead = criados no período · MQL/SAL = descontam desqualificados · SQL = na mão de closer · Oportunidade = Dia Oportunidade (não é coorte, pode superar SQL) · Booking = ganhos</div>"
            f"<form method=get action=/marketing><input type=hidden name=view value=funil>{form}</form>"
            + meta_html +
            f"<section><h2>Funil</h2><p class=secsub>largura proporcional ao volume · pílula = conversão sobre a etapa anterior</p>{funil_visual}</section>"
            f"<section><h2>Taxas por etapa</h2><p class=secsub>vs período anterior equivalente ({ini_p.strftime('%d-%m')} a {fim_p.strftime('%d-%m')}) · “Meta qtde” = volume planejado do mês ({mes_ref.strftime('%m-%Y')}) na planilha de metas</p>"
            f"<div class=card><table><tr><th>Etapa</th><th class=num>Deals</th><th class=num>Meta qtde (mês)</th><th class=num>Conversão da etapa</th><th class=num>Meta taxa</th></tr>{linhas}</table></div></section>"
            + form_metas + sugestoes)


# ---------------------------------------------------------------------------
# Aba — Metas do Semestre (planilha de metas detalhadas do Marketing, H2)
# ---------------------------------------------------------------------------
_MES_ABREV = {7: "Jul", 8: "Ago", 9: "Set", 10: "Out", 11: "Nov", 12: "Dez"}
_CANAIS_PLANO = ["META", "PROSPECÇÃO", "EVENTOS", "SHOPEE", "LOW TICKET", "INST ORG", "TOTAL"]
_CANAIS_LBL = {"META": "Mídia paga (Meta/Google)", "PROSPECÇÃO": "Prospecção ativa",
               "EVENTOS": "Eventos", "SHOPEE": "Shopee", "LOW TICKET": "Low ticket",
               "INST ORG": "Instagram orgânico", "TOTAL": "Total"}
# realizado por canal via utm_source (mesma convenção de canal_de/analysis)
_CANAIS_SQL = {
    "META": "(origem LIKE 'meta%%' OR origem LIKE 'google%%' OR origem IN ('facebook','instagram_ads'))",
    "PROSPECÇÃO": "origem ILIKE 'prospec%%'",
    "EVENTOS": "origem ILIKE '%%evento%%'",
    "SHOPEE": "origem ILIKE '%%shopee%%'",
    "LOW TICKET": "origem ILIKE '%%low%%'",
    "INST ORG": "(origem ILIKE 'insta%%' AND origem <> 'instagram_ads')",
    "TOTAL": "TRUE",
}


def _metas(conn) -> str:
    from ..sources.mkt_plan_sheet import ANO
    hoje = dt.date.today()
    meses = [dt.date(ANO, m, 1) for m in range(7, 13)]
    plan = _plan_funil(conn, meses)
    if not plan:
        return ("<h1>Metas do Semestre</h1><div class=sub>plano mensal da planilha de metas do Marketing</div>"
                "<section><div class=warn>Plano ainda não importado — rode <code>python -m scripts.sync_marketing --weekly</code> "
                "para ler a planilha de metas.</div></section>")
    mes_atual = hoje.replace(day=1)

    # gasto de mídia por mês + realizado (coorte) dos meses já iniciados
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
        passou, booked, _t, _rec = _funil_oficial(conn, mes, fim_m)
        reais[mes] = passou + [booked]

    # ---- KPIs do mês corrente (com ritmo esperado)
    kpis = ""
    if mes_atual in plan and mes_atual in reais:
        p, r = plan[mes_atual], reais[mes_atual]
        frac = min(1.0, hoje.day / _dias_mes(mes_atual))

        def kpi_meta(label, real, meta, kind="num", inverso=False):
            if meta is None:
                return ""
            pct = real / meta if meta else None
            ok = pct is not None and ((pct <= 1.0) if inverso else (pct >= frac))
            cls = "pos" if ok else "neg"
            alvo = "alvo" if inverso else "meta"
            return (f"<div class=kpi><div class=n>{_fmt(real, kind)}</div><div class=l>{label}</div>"
                    f"<div class='d {cls}'>{_fmt(pct, 'pct')} ({alvo}: {_fmt(meta, kind)})</div></div>")

        kpis += kpi_meta("Leads no mês", r[0], (p.get("Lead") or {}).get("qtde"))
        kpis += kpi_meta("SQLs", r[3], (p.get("SQL") or {}).get("qtde"))
        kpis += kpi_meta("Oportunidades", r[4], (p.get("Oportunidade") or {}).get("qtde"))
        kpis += kpi_meta("Bookings", r[5], (p.get("Booking") or {}).get("qtde"))
        g = gasto_mes.get(mes_atual)
        cpl_alvo = (p.get("Lead") or {}).get("custo")
        if g and r[0]:
            kpis += kpi_meta("CPL do mês", g / r[0], cpl_alvo, "brl", inverso=True)
        verba_meta = (plan_canais.get((mes_atual, "META")) or (None, None))[1]
        if g is not None and verba_meta:
            kpis += kpi_meta("Gasto mídia", g, verba_meta, "brl", inverso=True)
        kpis = (f"<div class=kpis>{kpis}</div>"
                f"<p class='note' style='margin:8px 0 0'>ritmo esperado: {frac * 100:.0f}% do mês decorrido — "
                f"verde = no ritmo da meta (custos: verde = dentro do alvo/verba).</p>") if kpis else ""

    # ---- grade mês × etapa: realizado / meta
    def celula(mes, i, etapa):
        meta = (plan.get(mes, {}).get(etapa) or {}).get("qtde")
        if mes not in reais:  # mês futuro: só a meta
            return f"<td class=num style='color:var(--text-muted)'>{_fmt(meta)}</td>"
        real = reais[mes][i]
        if meta is None:
            return f"<td class=num>{real}</td>"
        pct = real / meta if meta else None
        frac_m = min(1.0, ((min(hoje, mes.replace(day=_dias_mes(mes))) - mes).days + 1) / _dias_mes(mes))
        cls = "pos" if (pct or 0) >= frac_m else ("neg" if (pct or 0) < frac_m * 0.75 else "")
        return (f"<td class=num title='meta {meta:.0f} · realizado {real}'>"
                f"<b>{real}</b><span style='color:var(--text-muted)'>/{meta:.0f}</span> "
                f"<span class='{cls}' style='font-size:var(--fs-2xs)'>{_fmt(pct, 'pct')}</span></td>")

    grade = ""
    for mes in meses:
        marca = " style='background:color-mix(in srgb,var(--brand) 5%,transparent)'" if mes == mes_atual else ""
        grade += f"<tr{marca}><td><b>{_MES_ABREV[mes.month]}</b></td>"
        grade += "".join(celula(mes, i, e) for i, e in enumerate(_ETAPAS_PLANO)) + "</tr>"
    tot_meta_book = sum((plan.get(m, {}).get("Booking") or {}).get("qtde") or 0 for m in meses)
    tot_real_book = sum(r[5] for r in reais.values())
    grade += (f"<tr><td><b>H2</b></td><td colspan=4></td><td></td>"
              f"<td class=num><b>{tot_real_book}</b><span style='color:var(--text-muted)'>/{tot_meta_book:.0f}</span></td></tr>")

    # ---- custo-alvo × custo real por etapa (mês corrente)
    custos = ""
    if mes_atual in plan and mes_atual in reais and gasto_mes.get(mes_atual):
        g = gasto_mes[mes_atual]
        linhas_c = ""
        for i, etapa in enumerate(_ETAPAS_PLANO[:5]):
            alvo = (plan[mes_atual].get(etapa) or {}).get("custo")
            vol = reais[mes_atual][i]
            real_c = g / vol if vol else None
            if alvo is None:
                continue
            d = ""
            if real_c is not None:
                var = (real_c - alvo) / alvo * 100
                cls = "neg" if var > 0 else "pos"
                d = f"<span class='{cls}'>{'+' if var >= 0 else ''}{var:.0f}%</span>"
            linhas_c += (f"<tr><td>{etapa}</td><td class=num>{vol}</td><td class=num>{_fmt(alvo, 'brl')}</td>"
                         f"<td class=num>{_fmt(real_c, 'brl')}</td><td class=num>{d}</td></tr>")
        custos = (f"<section><h2>Custo por etapa vs alvo ({mes_atual.strftime('%m-%Y')})</h2>"
                  f"<p class=secsub>custo real = gasto de mídia do mês ÷ volume da etapa (proxy: inclui volume de canais não pagos) · alvo da planilha</p>"
                  f"<div class=card><table><tr><th>Etapa</th><th class=num>Volume</th><th class=num>Custo-alvo</th>"
                  f"<th class=num>Custo real</th><th class=num>Δ</th></tr>{linhas_c}</table></div></section>")

    # ---- investimento necessário × gasto real
    linhas_i = ""
    for mes in meses:
        p = plan.get(mes, {})
        inv = (p.get("Lead") or {}).get("inv")
        verba = (plan_canais.get((mes, "META")) or (None, None))[1]
        g = gasto_mes.get(mes)
        cob = ""
        if g is not None and inv:
            cob = _fmt(g / inv, "pct")
        linhas_i += (f"<tr><td><b>{_MES_ABREV[mes.month]}</b></td>"
                     f"<td class=num>{_fmt((p.get('Lead') or {}).get('qtde'))}</td>"
                     f"<td class=num>{_fmt(inv, 'brl')}</td><td class=num>{_fmt(verba, 'brl')}</td>"
                     f"<td class=num>{_fmt(g, 'brl') if g is not None else '—'}</td><td class=num>{cob}</td></tr>")

    # ---- oportunidades por canal (metas jul-dez + realizado do mês corrente)
    reais_canal = {}
    if mes_atual in reais:
        with conn.cursor() as cur:
            for canal, cond in _CANAIS_SQL.items():
                cur.execute(f"""SELECT count(*) FILTER (WHERE stage_id >= 3 OR status IN ('won','lost'))
                                  FROM mkt_deals_attribution
                                 WHERE add_time >= %s AND add_time < %s AND {cond}""",
                            (mes_atual, hoje + dt.timedelta(days=1)))
                reais_canal[canal] = cur.fetchone()[0] or 0
    linhas_k = ""
    for canal in _CANAIS_PLANO:
        peso = " style='border-top:2px solid var(--border-strong)'" if canal == "TOTAL" else ""
        cels = ""
        for mes in meses:
            q, v = plan_canais.get((mes, canal)) or (None, None)
            tip = f" title='verba: {_fmt(v, 'brl') if v else 'R$ 0'}'" if v is not None else ""
            cels += f"<td class=num{tip}>{_fmt(q)}</td>"
        real = reais_canal.get(canal)
        meta_m = (plan_canais.get((mes_atual, canal)) or (None, None))[0]
        real_td = "—"
        if real is not None:
            cls = ""
            if meta_m:
                frac = min(1.0, hoje.day / _dias_mes(mes_atual))
                cls = "pos" if real / meta_m >= frac else "neg"
            real_td = f"<span class='{cls}'>{real}</span>"
        linhas_k += (f"<tr{peso}><td><b>{escape(_CANAIS_LBL[canal])}</b></td>{cels}"
                     f"<td class=num>{real_td}</td></tr>")

    hdr_meses = "".join(f"<th class=num>{_MES_ABREV[m.month]}</th>" for m in meses)
    return (f"<h1>Metas do Semestre</h1><div class=sub>plano mensal detalhado da planilha de metas do Marketing (jul-dez {ANO}) × realizado no Pipedrive/mídia — releitura semanal</div>"
            + kpis +
            f"<section><h2>Funil mês a mês — realizado/meta</h2>"
            f"<p class=secsub>realizado = coorte de deals criados no mês (mesma régua da aba Funil) · verde = no ritmo, vermelho = abaixo de 75% do ritmo</p>"
            f"<div class=card><table><tr><th>Mês</th>" + "".join(f"<th class=num>{e}</th>" for e in _ETAPAS_PLANO) + f"</tr>{grade}</table></div></section>"
            + custos +
            f"<section><h2>Investimento planejado × gasto</h2>"
            f"<p class=secsub>investimento necessário = meta de leads × CPL-alvo (planilha) · verba mídia = orçamento disponível do mês · gasto = Meta+Google</p>"
            f"<div class=card><table><tr><th>Mês</th><th class=num>Meta leads</th><th class=num>Investimento necessário</th>"
            f"<th class=num>Verba mídia</th><th class=num>Gasto real</th><th class=num>Gasto ÷ necessário</th></tr>{linhas_i}</table></div></section>"
            f"<section><h2>Oportunidades por canal — metas do semestre</h2>"
            f"<p class=secsub>metas da planilha · “Real {_MES_ABREV[mes_atual.month] if mes_atual in reais else ''}” = oportunidades do mês corrente por utm_source (origens não rastreadas não aparecem)</p>"
            f"<div class=card><table><tr><th>Canal</th>{hdr_meses}<th class=num>Real {_MES_ABREV[mes_atual.month] if mes_atual in reais else '—'}</th></tr>{linhas_k}</table>"
            f"<p class='note' style='margin:10px 0 0'>Passe o mouse na célula para ver a verba do canal no mês. O mapeamento canal→utm_source é aproximado "
            f"(META = Meta+Google Ads); padronizar UTMs de Shopee, eventos e low ticket deixa o realizado fiel.</p></div></section>")


# ---------------------------------------------------------------------------
# Aba — Mídia Paga (visões do dashboard Paid media performance)
# ---------------------------------------------------------------------------
def _midia(conn, request: Request) -> str:
    ini, fim, form = _periodo(request)
    with conn.cursor() as cur:
        cur.execute("""SELECT date, sum(spend), sum(clicks), sum(impressions)
                         FROM mkt_insights_daily WHERE date >= %s AND date <= %s
                        GROUP BY 1 ORDER BY 1""", (ini, fim))
        rows = cur.fetchall()
        # leads = DEALS do Pipedrive atribuídos a canais pagos (fonte da verdade
        # do funil — número bate com o CRM; leads "da plataforma" divergem)
        cur.execute("""SELECT add_time::date, count(*) FROM mkt_deals_attribution
                        WHERE add_time::date >= %s AND add_time::date <= %s
                          AND (origem LIKE 'meta%%' OR origem LIKE 'google%%'
                               OR origem IN ('facebook', 'instagram_ads'))
                        GROUP BY 1""", (ini, fim))
        leads_dia = dict(cur.fetchall())
    labels = [r[0].strftime("%d-%m") for r in rows]
    spend = [float(r[1]) for r in rows]
    leads = [float(leads_dia.get(r[0], 0)) for r in rows]
    cpl = [(s / l if l else 0) for s, l in zip(spend, leads)]
    tot_s, tot_l = sum(spend), sum(leads)
    tot_c = sum(float(r[2]) for r in rows)
    tot_i = sum(float(r[3]) for r in rows)
    ctr_medio = (tot_c / tot_i * 100) if tot_i else 0
    kpis = ("<div class=kpis>"
            f"<div class=kpi><div class=n>{_fmt(tot_s, 'brl')}</div><div class=l>Gasto no período</div></div>"
            f"<div class=kpi><div class=n>{_fmt(tot_l)}</div><div class=l>Leads</div></div>"
            f"<div class=kpi><div class=n>{_fmt(tot_s / tot_l if tot_l else None, 'brl')}</div><div class=l>CPL médio</div></div>"
            f"<div class=kpi><div class=n>{ctr_medio:.2f}%</div><div class=l>CTR médio</div></div></div>")
    g1 = _svg_line([("Gasto/dia (R$)", "var(--brand)", spend)], labels)
    g2 = _svg_line([("Leads/dia", "var(--status-baixo)", leads)], labels)
    g3 = _svg_line([("CPL/dia (R$)", "var(--status-alto)", cpl)], labels)

    cards = ""
    try:
        from ..sources import creative_history as CH
        agg = {}
        for r in CH.daily():
            d = str(r.get("date") or "")[:10]
            if not d or not (ini.isoformat() <= d <= fim.isoformat()):
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
        top = sorted(agg.values(), key=lambda x: -x["spend"])[:12]
        for a in top:
            cpl_a = a["spend"] / a["leads"] if a["leads"] else None
            ctr_a = a["clicks"] / a["impr"] * 100 if a["impr"] else None
            ctr_txt = f"{ctr_a:.2f}%" if ctr_a is not None else "—"
            book_txt = f" · {a['book']} bookings" if a["book"] else ""
            img = (f"<img src='{escape(a['thumb'])}' loading=lazy style='width:100%;height:110px;object-fit:cover;border-radius:var(--radius-sm);background:var(--surface-3)'>"
                   if a.get("thumb") else "<div style='height:110px;border-radius:var(--radius-sm);background:var(--surface-3)'></div>")
            cards += ("<div style='background:var(--surface-1);border:1px solid var(--border-mid);border-radius:var(--radius-md);padding:10px'>"
                      + img +
                      f"<div style='font-size:var(--fs-xs);font-weight:600;margin-top:8px;line-height:1.3'>{escape((a['nome'] or '')[:48])}</div>"
                      f"<div style='font-size:var(--fs-2xs);color:var(--text-muted);margin-top:5px'>"
                      f"{escape(a['tipo'] or '')} · gasto {_fmt(a['spend'], 'brl')} · {a['leads']} leads · CPL {_fmt(cpl_a, 'brl')} · CTR {ctr_txt}{book_txt}</div></div>")
    except Exception:  # noqa: BLE001 — histórico fora do ar não derruba a aba
        cards = "<div class=warn>Histórico de criativos (ad-insightify) indisponível no momento.</div>"

    return (f"<h1>Mídia Paga</h1><div class=sub>gasto/CTR da plataforma · leads e CPL pelos DEALS do Pipedrive (canais pagos) — números batem com o CRM · galeria de criativos</div>"
            f"<form method=get action=/marketing><input type=hidden name=view value=midia>{form}</form>"
            + kpis +
            f"<section><h2>Gasto por dia</h2><div class=card>{g1}</div></section>"
            f"<section><h2>Leads por dia</h2><div class=card>{g2}</div></section>"
            f"<section><h2>CPL por dia</h2><div class=card>{g3}</div></section>"
            f"<section><h2>Criativos do período</h2><p class=secsub>top 12 por gasto, com métricas do ad-insightify</p>"
            f"<div style='display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px'>{cards}</div></section>")


# ---------------------------------------------------------------------------
@router.post("/marketing/funil-metas")
async def salvar_funil_metas(request: Request):
    """Salva as metas de taxa do funil do mês (form da aba Funil)."""
    A = _deps()
    s, redir = A._require_area(request, "marketing")
    if redir:
        return redir
    form = await request.form()
    mes = str(form.get("mes") or "")
    etapas_meta = [nome for nome, _ in _FUNIL_ETAPAS[1:]] + ["Booking"]
    with A._conn() as c:
        from .schema import ensure_mkt_tables
        ensure_mkt_tables(c)
        with c.cursor() as cur:
            for i, e in enumerate(etapas_meta):
                v = str(form.get(f"meta_{i}") or "").replace(",", ".").strip()
                if not v:
                    cur.execute("DELETE FROM mkt_funnel_goals WHERE mes=%s AND etapa=%s", (mes, e))
                    continue
                try:
                    taxa = max(0.0, min(100.0, float(v))) / 100.0
                except ValueError:
                    continue
                cur.execute("""INSERT INTO mkt_funnel_goals (mes, etapa, taxa_meta, updated_at)
                               VALUES (%s,%s,%s,now())
                               ON CONFLICT (mes, etapa) DO UPDATE SET taxa_meta=EXCLUDED.taxa_meta, updated_at=now()""",
                            (mes, e, taxa))
            cur.execute("INSERT INTO audit_log (actor, action, scope) VALUES (%s,'funil_metas',%s)",
                        (s[0], f"marketing:{mes}"))
    ini, fim = str(form.get("ini") or ""), str(form.get("fim") or "")
    return RedirectResponse(f"/marketing?view=funil&ini={ini}&fim={fim}", status_code=303)


# ---------------------------------------------------------------------------
@router.get("/marketing", response_class=HTMLResponse)
def marketing(request: Request, view: str = Query("visao")):
    A = _deps()
    s, redir = A._require_area(request, "marketing")
    if redir:
        return redir
    user, role = s
    if view not in {v for v, _ in _VIEWS}:
        view = "visao"
    with A._conn() as c:
        with c.cursor() as cur:
            cur.execute("INSERT INTO audit_log (actor, action, scope) VALUES (%s,'view',%s)",
                        (user, f"marketing/{view}"))
        fn = {"visao": lambda: _visao(c), "metas": lambda: _metas(c),
              "funil": lambda: _funil(c, request),
              "canais": lambda: _canais(c, request),
              "origens": lambda: _origens(c, request), "midia": lambda: _midia(c, request),
              "lag": lambda: _lag(c), "planejador": lambda: _planejador(c, request),
              "criativos": lambda: _criativos(c, request)}[view]
        content = fn() + "<p class=foot>Cache local das fontes (Meta, Google, Pipedrive, planilha de metas, ad-insightify) — coleta diária 06h. A decisão é sempre do gestor.</p>"
    return HTMLResponse(_shell(A, role, view, content, usermail=user))
