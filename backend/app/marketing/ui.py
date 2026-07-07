"""Área de MARKETING no painel — /marketing?view=... (7 abas).

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

_VIEWS = [("visao", "Visão Geral"), ("canais", "Ranking de Canais"),
          ("origens", "Origem de Leads"), ("lag", "Tempo até Resultado"),
          ("planejador", "Planejador"), ("criativos", "Criativos e Públicos"),
          ("q3", "Canais Q3")]


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


def _shell(A, role: str, view: str, content: str) -> str:
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
   <div class=rail-foot>papel: <b>__ROLE__</b> · <a href="/logout" style="color:var(--text-muted);text-decoration:underline">sair</a><br>dados via cache local (coleta 06h)</div>
 </aside>
 <main>__CONTENT__</main>
</div></body></html>"""
    return (head.replace("__TOKENS__", A._tokens_css()).replace("__NAV__", nav)
            .replace("__ROLE__", escape(role)).replace("__CONTENT__", content))


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
        gap = (f"<section><h2>Gap para a meta (B3-B5)</h2><p class=secsub>quantos leads ainda são "
               f"necessários no ritmo de conversão do mês</p><div class=card><ul class=note style='margin:0;padding-left:18px'>{itens}</ul></div></section>")

    return (f"<h1>Visão Geral</h1><div class=sub>mês atual ({ini.strftime('%d-%m-%Y')} → hoje) vs mês anterior</div>"
            f"<div class=kpis>{kpis}</div>"
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


def _origens(conn, request: Request) -> str:
    ini, fim, form = _periodo(request)
    origem = request.query_params.get("origem") or None
    if origem:
        rows = ""
        for r in AN.funil_por_origem(conn, ini, fim, origem):
            rows += (f"<tr><td>{escape(str(r['utm_campaign'] or '—')[:48])}</td><td>{escape(str(r['utm_content'] or '—')[:40])}</td>"
                     f"<td class=num>{r['leads']}</td><td class=num>{r['oport']}</td><td class=num>{r['bookings']}</td>"
                     f"<td class=num>{_fmt(float(r['receita']), 'brl')}</td></tr>")
        return (f"<h1>Origem: {escape(origem)}</h1><div class=sub><a href='/marketing?view=origens&ini={ini}&fim={fim}' style='color:var(--brand)'>← todas as origens</a></div>"
                f"<section><div class=card><table><tr><th>Campanha</th><th>Criativo</th><th class=num>Leads</th>"
                f"<th class=num>Oport</th><th class=num>Bookings</th><th class=num>Receita</th></tr>{rows}</table></div></section>")
    rows = ""
    dados = AN.funil_por_origem(conn, ini, fim)
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
        rows += (f"<tr><td><a href='/marketing?view=origens&origem={o}&ini={ini}&fim={fim}' style='color:var(--brand)'>{o}</a>{tag}</td>"
                 f"<td class=num>{r['leads']}</td><td class=num>{r['oport']} ({_fmt(oport_pct, 'pct')})</td>"
                 f"<td class=num>{r['bookings']} ({_fmt(conv, 'pct')})</td><td class=num>{_fmt(float(r['receita']), 'brl')}</td></tr>")
    return (f"<h1>Análise por Origem de Leads</h1><div class=sub>funil lead → oportunidade → booking; clique na origem para ver campanhas e criativos</div>"
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
    qtde = request.query_params.get("qtde")
    alvo_s = request.query_params.get("alvo")
    canal_ui = request.query_params.get("canal") or "Meta Ads"
    canal_db = _CANAL_DB.get(canal_ui, "meta")
    form = (f"<form method=get action=/marketing><input type=hidden name=view value=planejador>"
            f"<div class=filters>"
            f"<div><label>bookings desejados</label><input type=number name=qtde min=1 value='{escape(qtde or '5')}' style='width:90px'></div>"
            f"<div><label>resultado até</label><input type=date name=alvo value='{escape(alvo_s or (dt.date.today() + dt.timedelta(days=60)).isoformat())}'></div>"
            f"<div><label>canal</label><select name=canal>" +
            "".join(f"<option {'selected' if canal_ui == c else ''}>{c}</option>" for c in ("Meta Ads", "Google Ads")) +
            f"</select></div><button type=submit>Planejar</button></div></form>")
    resultado = ""
    if qtde and alvo_s:
        try:
            n_book, alvo = int(qtde), dt.date.fromisoformat(alvo_s)
        except ValueError:
            n_book, alvo = 0, None
        with conn.cursor() as cur:
            cur.execute("""SELECT marco, p25_dias, mediana_dias, p75_dias FROM mkt_campaign_lag_stats
                            WHERE canal=%s""", (canal_db,))
            lag = {m: (p25, med, p75) for m, p25, med, p75 in cur.fetchall()}
        ini90 = dt.date.today() - dt.timedelta(days=90)
        rk = {r["canal"]: r for r in AN.ranking_canais(conn, ini90, dt.date.today())}
        r = rk.get(canal_ui, {})
        conv, cpl = r.get("conv_lead_book"), r.get("cpl")
        if alvo and lag.get("primeiro_booking") and conv and cpl:
            p25, med, p75 = (float(x) for x in lag["primeiro_booking"])
            d_med = alvo - dt.timedelta(days=int(med))
            d_cons = alvo - dt.timedelta(days=int(p75))
            leads_nec = n_book / conv
            orc = leads_nec * cpl
            atraso = "<div class=warn style='margin-top:10px'>⚠ A data-limite mediana já passou — o cenário conservador é inviável; considere canais com lag menor ou reduzir a meta.</div>" if d_med < dt.date.today() else ""
            resultado = (
                f"<section><h2>Plano para {n_book} bookings via {escape(canal_ui)} até {alvo.strftime('%d-%m-%Y')}</h2>"
                f"<div class=card><table>"
                f"<tr><th>Item</th><th class=num>Cenário mediano</th><th class=num>Intervalo (p25–p75)</th></tr>"
                f"<tr><td><b>Lançar a campanha até</b></td><td class=num><b>{d_med.strftime('%d-%m-%Y')}</b></td>"
                f"<td class=num>{(alvo - dt.timedelta(days=int(p25))).strftime('%d-%m')} (otimista) — {d_cons.strftime('%d-%m')} (conservador)</td></tr>"
                f"<tr><td>Leads necessários</td><td class=num>{leads_nec:,.0f}</td><td class=num>conversão lead→booking 90d: {_fmt(conv, 'pct')}</td></tr>".replace(",", ".") +
                f"<tr><td>Orçamento estimado</td><td class=num>{_fmt(orc, 'brl')}</td><td class=num>CPL 90d: {_fmt(cpl, 'brl')}</td></tr>"
                f"<tr><td>Lag até 1º booking</td><td class=num>{med:.0f} dias</td><td class=num>{p25:.0f}–{p75:.0f} dias</td></tr>"
                f"</table>{atraso}"
                f"<p class='note' style='margin:10px 0 0'>Intervalos vêm do histórico real de campanhas ({escape(canal_ui)}) — o p75 é o cenário de risco, não use só a mediana para prometer data.</p></div></section>")
        else:
            resultado = "<section><div class=warn>Sem base histórica suficiente neste canal (lag ou conversão indisponíveis) — o planejador precisa de campanhas com resultados atribuídos.</div></section>"
    return (f"<h1>Planejador de Lançamento</h1><div class=sub>informe a meta e a data — o planejador inverte o lag histórico e responde quando lançar, com quantos leads e que orçamento</div>"
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
# Aba 7 — Canais Q3
# ---------------------------------------------------------------------------
def _q3(conn) -> str:
    with conn.cursor() as cur:
        cur.execute("""SELECT date_trunc('month', add_time)::date AS mes, count(*),
                              count(*) FILTER (WHERE status='won'),
                              COALESCE(sum(valor) FILTER (WHERE status='won'),0)
                         FROM mkt_deals_attribution WHERE origem ILIKE '%%indica%%'
                        GROUP BY 1 ORDER BY 1 DESC LIMIT 12""")
        ind = cur.fetchall()
        cur.execute("SELECT count(*) FROM mkt_deals_attribution WHERE origem ILIKE '%%linkedin%%'")
        n_li = cur.fetchone()[0]
    irows = "".join(
        f"<tr><td>{m.strftime('%m-%Y')}</td><td class=num>{n}</td><td class=num>{b}</td>"
        f"<td class=num>{_fmt(b / n if n else None, 'pct')}</td><td class=num>{_fmt(float(r), 'brl')}</td></tr>"
        for m, n, b, r in ind)
    li_aviso = ("" if n_li else
                "<div class=warn>Nenhum deal com origem LinkedIn ainda. <b>Antes dos lançamentos Q3</b>, padronizar com o "
                "time o valor <code>utm_source=linkedin</code> nos formulários/links — o canal já está estruturado no "
                "ranking e nas análises e passa a preencher sozinho.</div>")
    return (f"<h1>Canais Q3 — LinkedIn e Indicações</h1><div class=sub>estruturados desde já; preenchem conforme os lançamentos acontecem</div>"
            f"<section><h2>LinkedIn</h2><p class=secsub>rastreio via origem/UTM no Pipedrive (sem Ads API nesta fase) · deals até agora: {n_li}</p>"
            f"<div class=card>{li_aviso or '<p class=note>Canal ativo no ranking — acompanhe pela aba Ranking de Canais.</p>'}</div></section>"
            f"<section><h2>Programa de Indicações</h2><p class=secsub>volume, conversão e receita por mês (origem contém “indica”)</p>"
            f"<div class=card><table><tr><th>Mês</th><th class=num>Leads</th><th class=num>Bookings</th><th class=num>Conversão</th><th class=num>Receita</th></tr>{irows or '<tr><td colspan=5 class=note>sem deals ainda</td></tr>'}</table></div></section>")


# ---------------------------------------------------------------------------
@router.get("/marketing", response_class=HTMLResponse)
def marketing(request: Request, view: str = Query("visao")):
    A = _deps()
    s = A._session(request)
    if not s:
        return RedirectResponse("/login", status_code=302)
    user, role = s
    if view not in {v for v, _ in _VIEWS}:
        view = "visao"
    with A._conn() as c:
        with c.cursor() as cur:
            cur.execute("INSERT INTO audit_log (actor, action, scope) VALUES (%s,'view',%s)",
                        (user, f"marketing/{view}"))
        fn = {"visao": lambda: _visao(c), "canais": lambda: _canais(c, request),
              "origens": lambda: _origens(c, request), "lag": lambda: _lag(c),
              "planejador": lambda: _planejador(c, request),
              "criativos": lambda: _criativos(c, request), "q3": lambda: _q3(c)}[view]
        content = fn() + "<p class=foot>Cache local das fontes (Meta, Google, Pipedrive, planilha de metas, ad-insightify) — coleta diária 06h. A decisão é sempre do gestor.</p>"
    return HTMLResponse(_shell(A, role, view, content))
