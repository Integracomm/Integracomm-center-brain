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

_VIEWS = [("visao", "Visão Geral"), ("funil", "Funil de Prospecção"),
          ("canais", "Ranking de Canais"), ("origens", "Origem de Leads"),
          ("midia", "Mídia Paga"), ("lag", "Tempo até Resultado"),
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
    out = [f"<svg viewBox='0 0 {W} {H + 14}' style='width:100%;max-width:840px'>"]
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
        out.append(f"<text x='{L + 4 + si * 130}' y='14' fill='{cor}' font-size='11' font-weight='600'>{escape(nome)}</text>")
    out.append("</svg>")
    return "".join(out)


# ---------------------------------------------------------------------------
# Aba — Funil de Prospecção
# ---------------------------------------------------------------------------
# Etapas do Pipedrive (inspecionado 2026-07-07). Funil de COORTE: deals criados
# no período; "passou da etapa X" = etapa atual (ou desfecho) com ordem >= X —
# won passa por todas. Reagendamento (loop) equivale à Reunião agendada.
# Pipeline 2 (prospecção ativa) mapeia para as ordens equivalentes.
_STAGE_ORDER = {1: 0, 2: 1, 3: 2, 4: 3, 6: 4, 5: 4, 7: 5,
                14: 0, 13: 1, 12: 2, 15: 3}
_FUNIL_ETAPAS = [("Leads", 0), ("Primeiro contato", 1), ("Conectado", 2),
                 ("Qualificação", 3), ("Reunião agendada", 4), ("Negociação", 5)]
_FUNIL_SUGESTOES = {
    "Primeiro contato": "Gargalo na VELOCIDADE de resposta: lead sem contato esfria em horas — revisar o SLA do primeiro toque (referência: <15 min em horário comercial) e a automação de disparo.",
    "Conectado": "Muitos contatos sem conexão: variar canal (WhatsApp + ligação + e-mail), horários alternados e cadência de 5-7 tentativas antes de descartar.",
    "Qualificação": "Perda alta na qualificação: filtrar curiosos ainda na LP/formulário e revisar o roteiro — campanhas com taxa baixa aqui pedem ajuste de público, não de verba.",
    "Reunião agendada": "Qualificado que não agenda: link de agenda self-service, menos fricção de horários e confirmação por WhatsApp na véspera (no-show é o vilão típico).",
    "Negociação": "Reunião que não vira booking: revisar proposta/ancoragem e follow-up estruturado — a maioria fecha entre o 2º e o 4º contato pós-reunião.",
}


def _funil(conn, request: Request) -> str:
    ini, fim, form = _periodo(request)
    dias = (fim - ini).days + 1
    ini_p, fim_p = ini - dt.timedelta(days=dias), ini - dt.timedelta(days=1)

    def coorte(a, b):
        with conn.cursor() as cur:
            cur.execute("""SELECT stage_id, status, count(*) FROM mkt_deals_attribution
                            WHERE add_time >= %s AND add_time < %s GROUP BY 1, 2""",
                        (a, b + dt.timedelta(days=1)))
            passou = [0] * 6
            booked = total = 0
            for stage_id, status, n in cur.fetchall():
                total += n
                nivel = 5 if status == "won" else _STAGE_ORDER.get(stage_id, 0)
                for k in range(0, min(nivel, 5) + 1):
                    passou[k] += n
                if status == "won":
                    booked += n
            passou[0] = total
            return passou, booked, total

    passou, booked, total = coorte(ini, fim)
    passou_p, booked_p, total_p = coorte(ini_p, fim_p)

    with conn.cursor() as cur:
        cur.execute("SELECT COALESCE(sum(meta_qtde),0) FROM mkt_goals WHERE mes=%s AND plano<>'total'",
                    (fim.replace(day=1),))
        meta_book = float(cur.fetchone()[0] or 0)
    conv_atual = booked / total if total else 0
    conv_nec = (meta_book / total) if total and meta_book else None

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
        if taxa is not None and taxa < pior_taxa and passou[i - 1] >= 20:
            pior, pior_taxa = nome, taxa
        pct_total = n / total if total else 0
        barras += ("<div style='display:grid;grid-template-columns:150px 1fr 120px;gap:10px;align-items:center;padding:4px 0'>"
                   f"<div style='font-size:var(--fs-sm)'>{nome}</div>"
                   f"<div class=bar style='height:22px;border-radius:6px'><div style='width:{pct_total * 100:.1f}%'></div></div>"
                   f"<div style='font-size:var(--fs-sm);text-align:right'><b>{n}</b> ({_fmt(pct_total, 'pct')})</div></div>")
        linhas += (f"<tr><td>{nome}</td><td class=num>{n}</td>"
                   f"<td class=num>{_fmt(taxa, 'pct') if taxa is not None else '—'}{delta}</td></tr>")
    pct_book = booked / total if total else 0
    barras += ("<div style='display:grid;grid-template-columns:150px 1fr 120px;gap:10px;align-items:center;padding:4px 0'>"
               "<div style='font-size:var(--fs-sm)'><b>Booking</b></div>"
               f"<div class=bar style='height:22px;border-radius:6px'><div style='width:{pct_book * 100:.1f}%;background:var(--status-baixo)'></div></div>"
               f"<div style='font-size:var(--fs-sm);text-align:right'><b>{booked}</b> ({_fmt(pct_book, 'pct')})</div></div>")
    taxa_final = booked / passou[5] if passou[5] else None
    linhas += (f"<tr><td><b>Booking (won)</b></td><td class=num><b>{booked}</b></td>"
               f"<td class=num><b>{_fmt(taxa_final, 'pct')}</b></td></tr>")

    meta_html = ""
    if conv_nec is not None:
        ok = conv_atual >= conv_nec
        cor = "var(--status-baixo)" if ok else "var(--status-critico)"
        meta_html = ("<div class=kpis>"
                     f"<div class=kpi><div class=n>{_fmt(conv_atual, 'pct')}</div><div class=l>conversão lead→booking</div></div>"
                     f"<div class=kpi><div class=n style='color:{cor}'>{_fmt(conv_nec, 'pct')}</div><div class=l>necessária p/ a meta ({meta_book:.0f} book/mês)</div></div>"
                     f"<div class=kpi><div class=n>{booked}</div><div class=l>bookings da coorte</div></div>"
                     f"<div class=kpi><div class=n>{total}</div><div class=l>leads no período</div></div></div>")
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

    return (f"<h1>Funil de Prospecção</h1><div class=sub>coorte: deals criados no período · “passou da etapa” = alcançou etapa igual/posterior (won passa por todas)</div>"
            f"<form method=get action=/marketing><input type=hidden name=view value=funil>{form}</form>"
            + meta_html +
            f"<section><h2>Funil</h2><div class=card>{barras}</div></section>"
            f"<section><h2>Taxas por etapa</h2><p class=secsub>vs período anterior equivalente ({ini_p.strftime('%d-%m')} a {fim_p.strftime('%d-%m')})</p>"
            f"<div class=card><table><tr><th>Etapa</th><th class=num>Deals</th><th class=num>Conversão da etapa</th></tr>{linhas}</table></div></section>"
            + sugestoes)


# ---------------------------------------------------------------------------
# Aba — Mídia Paga (visões do dashboard Paid media performance)
# ---------------------------------------------------------------------------
def _midia(conn, request: Request) -> str:
    ini, fim, form = _periodo(request)
    with conn.cursor() as cur:
        cur.execute("""SELECT date, sum(spend), sum(leads), sum(clicks), sum(impressions)
                         FROM mkt_insights_daily WHERE date >= %s AND date <= %s
                        GROUP BY 1 ORDER BY 1""", (ini, fim))
        rows = cur.fetchall()
    labels = [r[0].strftime("%d-%m") for r in rows]
    spend = [float(r[1]) for r in rows]
    leads = [float(r[2]) for r in rows]
    cpl = [(s / l if l else 0) for s, l in zip(spend, leads)]
    tot_s, tot_l = sum(spend), sum(leads)
    tot_c = sum(float(r[3]) for r in rows)
    tot_i = sum(float(r[4]) for r in rows)
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

    return (f"<h1>Mídia Paga</h1><div class=sub>evolução diária de gasto, leads, CPL e CTR — Meta + Google somados · galeria de criativos do período</div>"
            f"<form method=get action=/marketing><input type=hidden name=view value=midia>{form}</form>"
            + kpis +
            f"<section><h2>Gasto por dia</h2><div class=card>{g1}</div></section>"
            f"<section><h2>Leads por dia</h2><div class=card>{g2}</div></section>"
            f"<section><h2>CPL por dia</h2><div class=card>{g3}</div></section>"
            f"<section><h2>Criativos do período</h2><p class=secsub>top 12 por gasto, com métricas do ad-insightify</p>"
            f"<div style='display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px'>{cards}</div></section>")


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
        fn = {"visao": lambda: _visao(c), "funil": lambda: _funil(c, request),
              "canais": lambda: _canais(c, request),
              "origens": lambda: _origens(c, request), "midia": lambda: _midia(c, request),
              "lag": lambda: _lag(c), "planejador": lambda: _planejador(c, request),
              "criativos": lambda: _criativos(c, request), "q3": lambda: _q3(c)}[view]
        content = fn() + "<p class=foot>Cache local das fontes (Meta, Google, Pipedrive, planilha de metas, ad-insightify) — coleta diária 06h. A decisão é sempre do gestor.</p>"
    return HTMLResponse(_shell(A, role, view, content))
