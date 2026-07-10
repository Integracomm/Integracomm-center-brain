"""Áreas de PRÉ-VENDAS (/prevendas) e VENDAS (/vendas) — mesma casca do painel.

Corte validado pelo Otávio (08/07/26): Pré-vendas atua ATÉ O AGENDAMENTO da
reunião (stages 1-4 do Comercial + pipeline 2 de Prospecção); Vendas assume da
Reunião Agendada (6) em diante (5 Reagendamento, 7 Negociação, won/lost).
Fontes: mkt_deals_attribution (deal+dono+motivo), mkt_stage_events (/flow) e
sales_first_touch (1º contato). Réguas de contagem = as validadas no funil de
Marketing (evento no período, corte em horário de Brasília).
Atribuição: SDR = quem fez o 1º contato (first_touch.quem — o dono do deal
muda no handoff); closer = dono atual do deal da Reunião em diante.
"""
from __future__ import annotations

import datetime as dt
import statistics as st
from html import escape

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from . import especialista as ESP

router = APIRouter()

_PV_VIEWS = [("funil", "Funil de Qualificação"), ("speed", "Speed-to-Lead"),
             ("horarios", "Melhor Horário"), ("sdrs", "Time & Planos")]
_VD_VIEWS = [("funil", "Funil de Fechamento"), ("winloss", "Win/Loss"),
             ("ciclo", "Ciclo & Empacados"), ("closers", "Time & Planos"),
             ("forecast", "Performance & Meta")]

# etapas (validadas na inspeção do Pipedrive 08/07)
_ST_CONTATO = (2, 13)     # Primeiro contato (p1/p2)
_ST_CONECT = (3, 12)
_ST_QUALIF = (4, 15)
_ST_REUNIAO = (6,)        # handoff Pré-vendas → Vendas
_ST_NEGOC = (7,)
_ST_VENDAS_ABERTO = (6, 5, 7)


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
    if kind == "min":
        return f"{v:.0f} min" if v < 120 else f"{v / 60:.1f} h"
    if kind == "dias":
        return f"{v:.0f} d"
    return f"{v:,.0f}".replace(",", ".")


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


def _brt(a: dt.date, b: dt.date) -> tuple[str, str]:
    return f"{a} 00:00-03", f"{b + dt.timedelta(days=1)} 00:00-03"


def _shell(A, area: str, views, view: str, content: str, usermail: str) -> str:
    titulo = "Pré-vendas · Qualificação" if area == "prevendas" else "Vendas · Fechamento"
    nav = "<a class='nav-item' href='/'>← Início (central)</a>"
    for v, label in views:
        cls = "nav-item active" if v == view else "nav-item"
        nav += f"<a class='{cls}' href='/{area}?view={v}'>{label}</a>"
    from ..marketing.ui import _shell as MS  # reaproveita o shell do Marketing
    html = MS(A, usermail, view, content, usermail=usermail)
    # troca marca e navegação pela desta área
    html = html.replace("Marketing · Tráfego &amp; Leads", titulo).replace("Marketing · Tráfego & Leads", titulo)
    import re
    html = re.sub(r"<nav>.*?</nav>", "<nav>" + nav + "</nav>", html, count=1, flags=re.S)
    return html


def _card(inner: str) -> str:
    return f"<div class=card>{inner}</div>"


_TH = ("<th style='text-align:{al};padding:8px;border-bottom:1px solid var(--border-strong);"
       "color:var(--text-muted);font-size:var(--fs-2xs);text-transform:uppercase;"
       "letter-spacing:var(--tracking-label)'>{h}</th>")
_TD = "padding:8px;border-bottom:1px solid var(--border);font-variant-numeric:tabular-nums"


def _tbl(headers: list[tuple[str, str]], rows: str) -> str:
    ths = "".join(_TH.format(al=al, h=h) for h, al in headers)
    return f"<table style='width:100%;border-collapse:collapse'><tr>{ths}</tr>{rows}</table>"


def _aviso_coleta(oque: str) -> str:
    return (f"<div class=warn>Dados de {oque} chegam na próxima rodada de coleta "
            "(o orçamento diário da API do Pipedrive renovou de madrugada). Esta visão "
            "acende sozinha — nada a configurar.</div>")


# ---------------------------------------------------------------------------
# consultas compartilhadas
# ---------------------------------------------------------------------------
def _entradas(conn, stages, a, b, coorte=True) -> int:
    q = """SELECT count(DISTINCT e.deal_id) FROM mkt_stage_events e
             JOIN mkt_deals_attribution d ON d.deal_id = e.deal_id
            WHERE e.entered_at >= %s AND e.entered_at < %s AND e.stage_id = ANY(%s)"""
    args = [a, b, list(stages)]
    if coorte:
        q += " AND d.add_time >= %s AND d.add_time < %s"
        args += [a, b]
    with conn.cursor() as cur:
        cur.execute(q, args)
        return cur.fetchone()[0]


# ---------------------------------------------------------------------------
# PRÉ-VENDAS
# ---------------------------------------------------------------------------
def _pv_funil(conn, request: Request) -> str:
    ini, fim, form = _periodo(request)
    a, b = _brt(ini, fim)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM mkt_deals_attribution WHERE add_time >= %s AND add_time < %s", (a, b))
        leads = cur.fetchone()[0]
    contato = _entradas(conn, _ST_CONTATO, a, b)
    conect = _entradas(conn, _ST_CONECT, a, b)
    qualif = _entradas(conn, _ST_QUALIF, a, b)
    reuniao = _entradas(conn, _ST_REUNIAO, a, b)
    seq = [("Leads recebidos", leads), ("1º contato", contato), ("Conectado", conect),
           ("Qualificação", qualif), ("Reunião agendada (handoff)", reuniao)]
    rows = ""
    for i, (nome, n) in enumerate(seq):
        taxa = (n / seq[i - 1][1]) if i and seq[i - 1][1] else None
        vs_lead = n / leads if leads and i else None
        rows += (f"<tr><td style='{_TD}'><b>{nome}</b></td><td style='{_TD};text-align:right'>{n}</td>"
                 f"<td style='{_TD};text-align:right'>{_fmt(taxa, 'pct') if taxa is not None else '—'}</td>"
                 f"<td style='{_TD};text-align:right'>{_fmt(vs_lead, 'pct') if vs_lead is not None else '—'}</td></tr>")
    # por origem: qualidade do lead (lead → reunião) por canal
    with conn.cursor() as cur:
        cur.execute("""
            SELECT COALESCE(d.origem, '(vazio)') AS o, count(DISTINCT d.deal_id) AS leads,
                   count(DISTINCT e.deal_id) AS reunioes
              FROM mkt_deals_attribution d
              LEFT JOIN mkt_stage_events e ON e.deal_id = d.deal_id
                   AND e.stage_id = ANY(%s) AND e.entered_at >= %s AND e.entered_at < %s
             WHERE d.add_time >= %s AND d.add_time < %s
             GROUP BY 1 HAVING count(DISTINCT d.deal_id) >= 5 ORDER BY 2 DESC LIMIT 14""",
            (list(_ST_REUNIAO), a, b, a, b))
        orows = ""
        for o, l, r in cur.fetchall():
            tx = r / l if l else 0
            orows += (f"<tr><td style='{_TD}'>{escape(o[:34])}</td><td style='{_TD};text-align:right'>{l}</td>"
                      f"<td style='{_TD};text-align:right'>{r}</td><td style='{_TD};text-align:right'>{_fmt(tx, 'pct')}</td></tr>")
    # motivos de desqualificação (perdidos criados no período, etapa pré-handoff)
    with conn.cursor() as cur:
        cur.execute("""SELECT COALESCE(lost_reason, '(sem motivo)'), count(*)
                         FROM mkt_deals_attribution
                        WHERE add_time >= %s AND add_time < %s AND status='lost'
                          AND stage_id NOT IN (6, 5, 7)
                        GROUP BY 1 ORDER BY 2 DESC LIMIT 10""", (a, b))
        desq = cur.fetchall()
    drows = "".join(f"<tr><td style='{_TD}'>{escape(str(m)[:60])}</td>"
                    f"<td style='{_TD};text-align:right'>{n}</td></tr>" for m, n in desq)
    tem_motivo = any(m != "(sem motivo)" for m, _ in desq)
    ins = ESP.insights_prevendas({
        "taxa_contato": contato / leads if leads else None,
        "taxa_agend": reuniao / leads if leads else None,
        "desq_top": (desq[0] if desq and desq[0][0] != "(sem motivo)" else None)})
    ins_html = "".join(f"<div class=sug-item>→ {escape(i)}</div>" for i in ins)
    return (f"<h1>Funil de Qualificação</h1><div class=sub>do lead recebido à reunião agendada (handoff p/ Vendas) · régua por evento no período, horário de Brasília</div>"
            f"<form method=get action=/prevendas><input type=hidden name=view value=funil>{form}</form>"
            f"<section><h2>Funil</h2>" + _card(_tbl([("Etapa", "left"), ("Deals", "right"), ("TX", "right"), ("TX Lead", "right")], rows)) + "</section>"
            f"<section><h2>Qualidade do lead por origem</h2><p class=secsub>taxa lead→reunião por canal — realimenta a segmentação do Marketing</p>"
            + _card(_tbl([("Origem", "left"), ("Leads", "right"), ("Reuniões", "right"), ("Lead→Reunião", "right")], orows)) + "</section>"
            f"<section><h2>Motivos de desqualificação</h2><p class=secsub>perdidos antes do handoff</p>"
            + _card((_tbl([("Motivo", "left"), ("Deals", "right")], drows) if drows else "<span class=note>sem perdas no período</span>")
                    + ("" if tem_motivo else _aviso_coleta("motivo de perda"))) + "</section>"
            f"<section><h2>Diagnóstico do especialista</h2><p class=secsub>{ESP.PERSONA_PREVENDAS}</p>"
            + _card(ins_html + "<style>.sug-item{padding:7px 0;border-top:1px solid var(--border);font-size:var(--fs-sm);line-height:1.55;color:var(--text-2)}.sug-item:first-child{border-top:none}</style>") + "</section>")


def _ensure_touch(conn):
    from ..sources.pipedrive_deals import _TOUCH_DDL
    with conn.cursor() as cur:
        cur.execute(_TOUCH_DDL)


def _pv_speed(conn, request: Request) -> str:
    _ensure_touch(conn)
    ini, fim, form = _periodo(request)
    a, b = _brt(ini, fim)
    with conn.cursor() as cur:
        cur.execute("""SELECT d.deal_id, d.add_time, t.first_at, t.quem, d.origem
                         FROM mkt_deals_attribution d
                         LEFT JOIN sales_first_touch t ON t.deal_id = d.deal_id
                        WHERE d.add_time >= %s AND d.add_time < %s""", (a, b))
        rows = cur.fetchall()
    if not any(r[2] for r in rows):
        return (f"<h1>Speed-to-Lead</h1><div class=sub>tempo entre o lead entrar e o 1º contato registrado</div>"
                f"<section>{_aviso_coleta('atividades (1º contato)')}</section>")
    mins, por_quem, por_origem, sem_toque = [], {}, {}, 0
    for _did, add, first, quem, origem in rows:
        if not first:
            sem_toque += 1
            continue
        m = max(0.0, (first - add).total_seconds() / 60)
        mins.append(m)
        por_quem.setdefault((quem or "—").strip()[:30], []).append(m)
        por_origem.setdefault((origem or "(vazio)")[:30], []).append(m)
    med = st.median(mins) if mins else None
    p75 = st.quantiles(mins, n=4)[2] if len(mins) >= 4 else None
    dentro15 = sum(1 for m in mins if m <= 15) / len(mins) if mins else None
    kpis = ("<div class=kpis>"
            f"<div class=kpi><div class=n>{_fmt(med, 'min')}</div><div class=l>1º contato mediano</div><div class=s>referência de mercado: &lt;15 min</div></div>"
            f"<div class=kpi><div class=n>{_fmt(dentro15, 'pct')}</div><div class=l>dentro de 15 min</div></div>"
            f"<div class=kpi><div class=n>{_fmt(p75, 'min')}</div><div class=l>p75</div></div>"
            f"<div class=kpi><div class=n style='color:var(--status-critico)'>{sem_toque}</div><div class=l>sem contato registrado</div><div class=s>fila a zerar — lead não tocado esfria</div></div></div>")

    def bloco(d):
        out = ""
        for k, v in sorted(d.items(), key=lambda x: st.median(x[1])):
            if len(v) < 3:
                continue
            out += (f"<tr><td style='{_TD}'>{escape(k)}</td><td style='{_TD};text-align:right'>{len(v)}</td>"
                    f"<td style='{_TD};text-align:right'>{_fmt(st.median(v), 'min')}</td>"
                    f"<td style='{_TD};text-align:right'>{_fmt(sum(1 for m in v if m <= 15) / len(v), 'pct')}</td></tr>")
        return _tbl([("", "left"), ("Leads", "right"), ("Mediana", "right"), ("≤15 min", "right")], out)
    return (f"<h1>Speed-to-Lead</h1><div class=sub>tempo entre o lead entrar e o 1º contato registrado no Pipedrive · SLA-alvo a confirmar com o Marcos</div>"
            f"<form method=get action=/prevendas><input type=hidden name=view value=speed>{form}</form>"
            + kpis +
            f"<section><h2>Por responsável do 1º contato</h2>{_card(bloco(por_quem))}</section>"
            f"<section><h2>Por origem</h2>{_card(bloco(por_origem))}</section>")


def _pv_sdrs(conn, request: Request) -> str:
    _ensure_touch(conn)
    ini, fim, form = _periodo(request)
    a, b = _brt(ini, fim)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT t.quem, count(DISTINCT d.deal_id) AS leads,
                   count(DISTINCT e.deal_id) AS agendadas,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY EXTRACT(epoch FROM t.first_at - d.add_time) / 60) AS speed
              FROM sales_first_touch t
              JOIN mkt_deals_attribution d ON d.deal_id = t.deal_id
              LEFT JOIN mkt_stage_events e ON e.deal_id = d.deal_id AND e.stage_id = ANY(%s)
                   AND e.entered_at >= %s AND e.entered_at < %s
             WHERE d.add_time >= %s AND d.add_time < %s AND t.quem IS NOT NULL AND t.quem <> ''
             GROUP BY 1""", (list(_ST_REUNIAO), a, b, a, b))
        dados = cur.fetchall()
    time_stats = [{"nome": q, "leads": l, "agendadas": g,
                   "taxa_agend": (g / l if l else None),
                   "speed_min": float(s) if s is not None else None,
                   "ativo": q not in ESP.DESLIGADOS}
                  for q, l, g, s in dados if ESP.time_de(q, "sdr")]
    if not time_stats:
        return (f"<h1>Time de Pré-vendas</h1><div class=sub>coordenação: {ESP.COORD_PREVENDAS}</div>"
                f"<section>{_aviso_coleta('atividades (atribuição por SDR)')}</section>")
    rows, planos = "", ""
    for p in sorted(time_stats, key=lambda x: -(x["taxa_agend"] or 0)):
        tag = " <span class=chip style='--c:var(--status-semdados)'>desligada</span>" if not p["ativo"] else ""
        rows += (f"<tr><td style='{_TD}'><b>{escape(p['nome'])}</b>{tag}</td>"
                 f"<td style='{_TD};text-align:right'>{p['leads']}</td>"
                 f"<td style='{_TD};text-align:right'>{p['agendadas']}</td>"
                 f"<td style='{_TD};text-align:right'>{_fmt(p['taxa_agend'], 'pct')}</td>"
                 f"<td style='{_TD};text-align:right'>{_fmt(p['speed_min'], 'min')}</td></tr>")
        if p["ativo"]:
            pl = ESP.plano_sdr(p, time_stats)
            itens = ("".join(f"<li style='color:var(--status-baixo)'>{escape(f)}</li>" for f in pl["fortes"])
                     + "".join(f"<li style='color:var(--status-alto)'>{escape(f)}</li>" for f in pl["fracos"])
                     + "".join(f"<li>→ {escape(acao)}</li>" for acao in pl["acoes"]))
            planos += (f"<div style='margin-top:12px'><b>{escape(p['nome'])}</b>"
                       f"<ul class=note style='margin:4px 0 0;padding-left:18px'>{itens}</ul></div>")
    return (f"<h1>Time de Pré-vendas</h1><div class=sub>coordenação: {ESP.COORD_PREVENDAS} · atribuição pelo 1º contato · comparação com a mediana do time, tom construtivo</div>"
            f"<form method=get action=/prevendas><input type=hidden name=view value=sdrs>{form}</form>"
            f"<section><h2>Produtividade por SDR</h2>"
            + _card(_tbl([("SDR", "left"), ("Leads", "right"), ("Reuniões", "right"), ("Lead→Reunião", "right"), ("Speed (med.)", "right")], rows)) + "</section>"
            f"<section><h2>Planos de ação individuais</h2><p class=secsub>{ESP.PERSONA_PREVENDAS}</p>{_card(planos or '<span class=note>—</span>')}</section>")


# --- Melhor Horário (pedido do time de Pré-vendas, 10/07/26) ----------------
_DOW_NOME = ["dom", "seg", "ter", "qua", "qui", "sex", "sáb"]
_ST_AGENDA = (6, 15)  # entrada em Reunião Agendada (p1) / equivalente da Prospecção (p2)


def _pv_horarios(conn, request: Request) -> str:
    """Estudo de dias/horários em que reuniões são AGENDADAS (entrada do deal na
    etapa Reunião Agendada, horário de Brasília) — melhor janela p/ o SDR ligar,
    geral e por bundle. Base: mkt_stage_events (o carimbo é o momento em que o
    card foi movido — proxy da ligação que converteu)."""
    hoje = dt.date.today()
    qp = request.query_params
    ini_s = qp.get("ini") or (hoje - dt.timedelta(days=180)).isoformat()
    fim_s = qp.get("fim") or hoje.isoformat()
    try:
        ini, fim = dt.date.fromisoformat(ini_s), dt.date.fromisoformat(fim_s)
    except ValueError:
        ini, fim = hoje - dt.timedelta(days=180), hoje
    a, b = _brt(ini, fim)
    bundle = qp.get("bundle") or "todos"

    filtro_b = ""
    args: list = [a, b]
    if bundle in ("B1", "B2", "B3", "B4", "B5"):
        filtro_b = " AND substring(d.produto FROM 'B[1-5]') = %s"
        args.append(bundle)
    with conn.cursor() as cur:
        cur.execute(f"""
            SELECT extract(dow  FROM e.entered_at AT TIME ZONE 'America/Sao_Paulo')::int,
                   extract(hour FROM e.entered_at AT TIME ZONE 'America/Sao_Paulo')::int,
                   count(*)
              FROM mkt_stage_events e
              JOIN mkt_deals_attribution d ON d.deal_id = e.deal_id
             WHERE e.stage_id = ANY(%s) AND e.entered_at >= %s AND e.entered_at < %s{filtro_b}
             GROUP BY 1, 2""", [list(_ST_AGENDA)] + args)
        celulas = {(dow, h): n for dow, h, n in cur.fetchall()}
        # melhores janelas POR BUNDLE (independe do filtro acima)
        cur.execute("""
            SELECT COALESCE(substring(d.produto FROM 'B[1-5]'), 'sem produto'),
                   extract(dow  FROM e.entered_at AT TIME ZONE 'America/Sao_Paulo')::int,
                   extract(hour FROM e.entered_at AT TIME ZONE 'America/Sao_Paulo')::int,
                   count(*)
              FROM mkt_stage_events e
              JOIN mkt_deals_attribution d ON d.deal_id = e.deal_id
             WHERE e.stage_id = ANY(%s) AND e.entered_at >= %s AND e.entered_at < %s
             GROUP BY 1, 2, 3""", (list(_ST_AGENDA), a, b))
        por_bundle: dict[str, dict[tuple[int, int], int]] = {}
        for p, dow, h, n in cur.fetchall():
            por_bundle.setdefault(p, {})[(dow, h)] = n

    total = sum(celulas.values())
    if not total:
        return ("<h1>Melhor Horário</h1><div class=sub>quando as reuniões são agendadas</div>"
                "<section><div class=warn>sem agendamentos no período/filtro selecionado</div></section>")

    # --- heatmap dia da semana × hora ---
    dows = [1, 2, 3, 4, 5] + ([6] if any(d == 6 for d, _ in celulas) else []) \
        + ([0] if any(d == 0 for d, _ in celulas) else [])
    horas = sorted({h for _, h in celulas})
    horas = list(range(min(horas), max(horas) + 1))
    vmax = max(celulas.values())
    linhas = ""
    for h in horas:
        tds = ""
        for d in dows:
            n = celulas.get((d, h), 0)
            pct = n / total
            alpha = int(8 + 62 * (n / vmax)) if n else 0
            bg = f"background:color-mix(in srgb,var(--brand) {alpha}%,transparent);" if n else ""
            tds += (f"<td title='{_DOW_NOME[d]} {h:02d}h — {n} agendamento(s) ({pct * 100:.1f}%)' "
                    f"style='{_TD};text-align:center;{bg}'>{n or ''}</td>")
        linhas += f"<tr><td style='{_TD};color:var(--text-muted)'>{h:02d}h</td>{tds}</tr>"
    heat = _tbl([("", "left")] + [(_DOW_NOME[d], "left") for d in dows], linhas)

    # --- top janelas e leitura de expediente ---
    top = sorted(celulas.items(), key=lambda x: -x[1])[:5]
    top_html = "".join(
        f"<div class=sug-item><b>{i}º</b> — {_DOW_NOME[d]} às {h:02d}h: <b>{n}</b> agendamentos ({n / total * 100:.1f}%)</div>"
        for i, ((d, h), n) in enumerate(top, 1))
    antes9 = sum(n for (d, h), n in celulas.items() if h < 9)
    almoco = sum(n for (d, h), n in celulas.items() if 12 <= h < 14)
    depois18 = sum(n for (d, h), n in celulas.items() if h >= 18)
    fds = sum(n for (d, h), n in celulas.items() if d in (0, 6))
    kpis = ("<div class=kpis>"
            f"<div class=kpi><div class=n>{total}</div><div class=l>agendamentos no período</div></div>"
            f"<div class=kpi><div class=n>{_fmt(antes9 / total, 'pct')}</div><div class=l>antes das 9h</div></div>"
            f"<div class=kpi><div class=n>{_fmt(almoco / total, 'pct')}</div><div class=l>12h-14h (almoço)</div></div>"
            f"<div class=kpi><div class=n>{_fmt(depois18 / total, 'pct')}</div><div class=l>após as 18h</div></div>"
            f"<div class=kpi><div class=n>{_fmt(fds / total, 'pct')}</div><div class=l>fim de semana</div></div></div>")

    # --- melhores janelas por bundle ---
    brows = ""
    for p in ("B1", "B2", "B3", "B4", "B5", "sem produto"):
        cel = por_bundle.get(p)
        if not cel:
            continue
        tot_p = sum(cel.values())
        melhores = [f"{_DOW_NOME[d]} {h:02d}h ({n})"
                    for (d, h), n in sorted(cel.items(), key=lambda x: -x[1])[:3] if n >= 2]
        brows += (f"<tr><td style='{_TD}'><b>{escape(p)}</b></td>"
                  f"<td style='{_TD};text-align:right'>{tot_p}</td>"
                  f"<td style='{_TD}'>{escape(' · '.join(melhores) or '—')}</td>"
                  f"<td style='{_TD};text-align:right'>{'<span class=note>amostra pequena</span>' if tot_p < 30 else ''}</td></tr>")

    opts_b = "".join(f"<option value='{v}' {'selected' if bundle == v else ''}>{lbl}</option>"
                     for v, lbl in [("todos", "todos os bundles"), ("B1", "B1"), ("B2", "B2"),
                                    ("B3", "B3"), ("B4", "B4"), ("B5", "B5")])
    form = (f"<form method=get action=/prevendas><input type=hidden name=view value=horarios>"
            f"<div class=filters><div><label>de</label><input type=date name=ini value='{ini}'></div>"
            f"<div><label>até</label><input type=date name=fim value='{fim}'></div>"
            f"<div><label>bundle</label><select name=bundle>{opts_b}</select></div>"
            f"<button type=submit>Aplicar</button></div></form>")
    estilo = ("<style>.sug-item{padding:7px 0;border-top:1px solid var(--border);font-size:var(--fs-sm);"
              "line-height:1.55;color:var(--text-2)}.sug-item:first-child{border-top:none}</style>")
    return (f"<h1>Melhor Horário — agendamentos de reunião</h1>"
            "<div class=sub>momento em que o deal ENTROU em Reunião Agendada (horário de Brasília) — proxy da "
            "ligação que converteu; o carimbo é a movimentação do card pelo SDR · pedido do time de Pré-vendas</div>"
            + form + kpis +
            "<section><h2>Mapa de calor — dia da semana × hora</h2>"
            f"<p class=secsub>período {ini.strftime('%d-%m-%Y')} a {fim.strftime('%d-%m-%Y')}"
            f"{' · bundle ' + bundle if bundle != 'todos' else ''} · quanto mais escuro, mais agendamentos</p>"
            + _card(heat) + "</section>"
            "<section><h2>Top 5 janelas</h2>" + _card(top_html + estilo) + "</section>"
            "<section><h2>Melhores janelas por bundle</h2>"
            "<p class=secsub>até 3 janelas com mais agendamentos por bundle no período — bundles com poucas "
            "amostras merecem cautela antes de mudar escala de time</p>"
            + _card(_tbl([("Bundle", "left"), ("Agendamentos", "right"), ("Melhores janelas", "left"), ("", "right")], brows)) + "</section>")


# ---------------------------------------------------------------------------
# VENDAS
# ---------------------------------------------------------------------------
def _vd_funil(conn, request: Request) -> str:
    ini, fim, form = _periodo(request)
    a, b = _brt(ini, fim)
    reunioes = _entradas(conn, _ST_REUNIAO, a, b, coorte=False)
    negoc = _entradas(conn, _ST_NEGOC, a, b, coorte=False)
    with conn.cursor() as cur:
        cur.execute("""SELECT count(*), COALESCE(sum(valor), 0) FROM mkt_deals_attribution
                        WHERE status='won' AND won_time >= %s AND won_time < %s""", (a, b))
        book, receita = cur.fetchone()
        # tendência mensal Oport→Booking (6 meses)
        cur.execute("""
            WITH oport AS (SELECT date_trunc('month', entered_at - interval '3 hours') m,
                                  count(DISTINCT deal_id) n
                             FROM mkt_stage_events WHERE stage_id = ANY(%s) GROUP BY 1),
                 wins AS (SELECT date_trunc('month', won_time - interval '3 hours') m, count(*) n
                            FROM mkt_deals_attribution WHERE status='won' GROUP BY 1)
            SELECT to_char(o.m, 'MM-YYYY'), o.n, COALESCE(w.n, 0)
              FROM oport o LEFT JOIN wins w ON w.m = o.m
             WHERE o.m >= date_trunc('month', now()) - interval '5 months'
             ORDER BY o.m""", (list(_ST_NEGOC),))
        tend = cur.fetchall()
    conv = book / negoc if negoc else None
    kpis = ("<div class=kpis>"
            f"<div class=kpi><div class=n>{reunioes}</div><div class=l>reuniões agendadas</div><div class=s>recebidas da Pré-vendas</div></div>"
            f"<div class=kpi><div class=n>{negoc}</div><div class=l>oportunidades</div><div class=s>compareceu (Negociação)</div></div>"
            f"<div class=kpi><div class=n>{book}</div><div class=l>bookings</div><div class=s>{_fmt(float(receita), 'brl')}</div></div>"
            f"<div class=kpi><div class=n style='color:var({'--status-baixo' if (conv or 0) >= 0.15 else '--status-critico'})'>{_fmt(conv, 'pct')}</div>"
            f"<div class=l>Oportunidade → Booking</div><div class=s>métrica central · meta 15%</div></div></div>")
    trows = ""
    for mes, o, w in tend:
        c = w / o if o else None
        cor = "pos" if (c or 0) >= 0.15 else "neg"
        trows += (f"<tr><td style='{_TD}'><b>{mes}</b></td><td style='{_TD};text-align:right'>{o}</td>"
                  f"<td style='{_TD};text-align:right'>{w}</td>"
                  f"<td style='{_TD};text-align:right' class={cor}>{_fmt(c, 'pct')}</td></tr>")
    with conn.cursor() as cur:  # no-show proxy: reagendamentos / reuniões
        cur.execute("""SELECT count(DISTINCT deal_id) FROM mkt_stage_events
                        WHERE stage_id = 5 AND entered_at >= %s AND entered_at < %s""", (a, b))
        reag = cur.fetchone()[0]
    ins = ESP.insights_vendas({"conv_oport_book": conv, "meta_conv": 0.15,
                               "no_show": (reag / reunioes if reunioes else None)})
    ins_html = "".join(f"<div class=sug-item>→ {escape(i)}</div>" for i in ins)
    return (f"<h1>Funil de Fechamento</h1><div class=sub>da reunião agendada ao contrato · régua por evento no período (BRT)</div>"
            f"<form method=get action=/vendas><input type=hidden name=view value=funil>{form}</form>"
            + kpis +
            f"<section><h2>Tendência Oportunidade → Booking</h2><p class=secsub>6 meses · o ponto de underperformance apontado no Q3</p>"
            + _card(_tbl([("Mês", "left"), ("Oportunidades", "right"), ("Bookings", "right"), ("Conversão", "right")], trows)) + "</section>"
            f"<section><h2>Diagnóstico do especialista</h2><p class=secsub>{ESP.PERSONA_VENDAS}</p>"
            + _card(ins_html + "<style>.sug-item{padding:7px 0;border-top:1px solid var(--border);font-size:var(--fs-sm);line-height:1.55;color:var(--text-2)}.sug-item:first-child{border-top:none}</style>") + "</section>")


def _vd_winloss(conn, request: Request) -> str:
    ini, fim, form = _periodo(request)
    a, b = _brt(ini, fim)
    with conn.cursor() as cur:
        cur.execute("""SELECT COALESCE(lost_reason, '(sem motivo)'), count(*), COALESCE(sum(valor), 0)
                         FROM mkt_deals_attribution
                        WHERE status='lost' AND lost_time >= %s AND lost_time < %s
                          AND stage_id IN (6, 5, 7)
                        GROUP BY 1 ORDER BY 2 DESC LIMIT 14""", (a, b))
        perdas = cur.fetchall()
        cur.execute("""SELECT COALESCE(lost_reason, '(sem motivo)'),
                              COALESCE(substring(produto FROM 'B[1-5]'), 'outros'), count(*)
                         FROM mkt_deals_attribution
                        WHERE status='lost' AND lost_time >= %s AND lost_time < %s
                          AND stage_id IN (6, 5, 7) AND lost_reason IS NOT NULL
                        GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 20""", (a, b))
        por_plano = cur.fetchall()
    tem_motivo = any(m != "(sem motivo)" for m, _, _ in perdas)
    rows = "".join(f"<tr><td style='{_TD}'>{escape(str(m)[:56])}</td><td style='{_TD};text-align:right'>{n}</td>"
                   f"<td style='{_TD};text-align:right'>{_fmt(float(v), 'brl')}</td></tr>" for m, n, v in perdas)
    prow = "".join(f"<tr><td style='{_TD}'>{escape(str(m)[:44])}</td><td style='{_TD}'>{escape(p)}</td>"
                   f"<td style='{_TD};text-align:right'>{n}</td></tr>" for m, p, n in por_plano)
    return (f"<h1>Win/Loss — Análise de Perdas</h1><div class=sub>perdas na fase de Vendas (da reunião em diante), por motivo e valor</div>"
            f"<form method=get action=/vendas><input type=hidden name=view value=winloss>{form}</form>"
            f"<section><h2>Motivos de perda</h2>"
            + _card((_tbl([("Motivo", "left"), ("Deals", "right"), ("MRR perdido", "right")], rows) if rows else "<span class=note>sem perdas no período</span>")
                    + ("" if tem_motivo else _aviso_coleta("motivo de perda"))) + "</section>"
            f"<section><h2>Motivo × plano</h2><p class=secsub>identifica se é preço/produto (concentrado num bundle) ou abordagem (espalhado)</p>"
            + _card(_tbl([("Motivo", "left"), ("Plano", "left"), ("Deals", "right")], prow) if prow else _card("<span class=note>—</span>")) + "</section>")


def _vd_ciclo(conn, request: Request) -> str:
    ini, fim, form = _periodo(request)
    a, b = _brt(ini, fim)
    with conn.cursor() as cur:
        # ciclo dos ganhos no período: 1ª reunião → won
        cur.execute("""
            SELECT EXTRACT(epoch FROM d.won_time - min(e.entered_at)) / 86400
              FROM mkt_deals_attribution d JOIN mkt_stage_events e ON e.deal_id = d.deal_id
             WHERE d.status='won' AND d.won_time >= %s AND d.won_time < %s
               AND e.stage_id = ANY(%s)
             GROUP BY d.deal_id, d.won_time""", (a, b, list(_ST_VENDAS_ABERTO)))
        ciclos = [float(r[0]) for r in cur.fetchall() if r[0] is not None and r[0] >= 0]
        # deals abertos na fase de Vendas + dias desde o último movimento
        cur.execute("""
            SELECT d.deal_id, d.stage_id, d.valor, d.produto, d.owner_name,
                   EXTRACT(epoch FROM now() - max(e.entered_at)) / 86400 AS dias
              FROM mkt_deals_attribution d JOIN mkt_stage_events e ON e.deal_id = d.deal_id
             WHERE d.status='open' AND d.stage_id IN (6, 5, 7)
             GROUP BY d.deal_id, d.stage_id, d.valor, d.produto, d.owner_name""")
        abertos = cur.fetchall()
    med = st.median(ciclos) if ciclos else None
    p25, p75 = (st.quantiles(ciclos, n=4)[0], st.quantiles(ciclos, n=4)[2]) if len(ciclos) >= 4 else (None, None)
    dias_ab = [float(x[5]) for x in abertos if x[5] is not None]
    med_ab = st.median(dias_ab) if dias_ab else 0
    empacados = sorted([x for x in abertos if x[5] and float(x[5]) > max(2 * med_ab, 14)],
                       key=lambda x: -float(x[5]))[:20]
    kpis = ("<div class=kpis>"
            f"<div class=kpi><div class=n>{_fmt(med, 'dias')}</div><div class=l>ciclo mediano</div><div class=s>1ª reunião → contrato ({len(ciclos)} ganhos)</div></div>"
            f"<div class=kpi><div class=n>{_fmt(p25, 'dias')} – {_fmt(p75, 'dias')}</div><div class=l>p25 – p75</div></div>"
            f"<div class=kpi><div class=n>{len(abertos)}</div><div class=l>deals abertos em Vendas</div></div>"
            f"<div class=kpi><div class=n style='color:var(--status-alto)'>{len(empacados)}</div><div class=l>empacados</div><div class=s>&gt;2× a mediana sem movimento</div></div></div>")
    erows = "".join(
        f"<tr><td style='{_TD}'>#{did}</td><td style='{_TD}'>{escape((own or '—')[:22])}</td>"
        f"<td style='{_TD}'>{escape((prod or '—')[:20])}</td>"
        f"<td style='{_TD};text-align:right'>{_fmt(float(val) if val else None, 'brl')}</td>"
        f"<td style='{_TD};text-align:right'><b>{float(dias):.0f} d</b></td></tr>"
        for did, _sid, val, prod, own, dias in empacados)
    return (f"<h1>Ciclo de Vendas</h1><div class=sub>tempo da 1ª reunião ao fechamento · distribuição, não só média</div>"
            f"<form method=get action=/vendas><input type=hidden name=view value=ciclo>{form}</form>"
            + kpis +
            f"<section><h2>Deals empacados — lista de atenção</h2><p class=secsub>sem movimento há mais de 2× a mediana (mín. 14 dias) — reativar com urgência ou limpar</p>"
            + _card(_tbl([("Deal", "left"), ("Dono", "left"), ("Plano", "left"), ("Valor", "right"), ("Parado há", "right")], erows) if erows else _card("<span class=note>nenhum deal empacado 🎉</span>")) + "</section>")


def _vd_closers(conn, request: Request) -> str:
    ini, fim, form = _periodo(request)
    a, b = _brt(ini, fim)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT d.owner_name,
                   count(DISTINCT e.deal_id) FILTER (WHERE e.stage_id = ANY(%s)) AS oports,
                   count(DISTINCT d.deal_id) FILTER (WHERE d.status='won' AND d.won_time >= %s AND d.won_time < %s) AS wins,
                   avg(d.valor) FILTER (WHERE d.status='won' AND d.won_time >= %s AND d.won_time < %s) AS ticket
              FROM mkt_deals_attribution d
              LEFT JOIN mkt_stage_events e ON e.deal_id = d.deal_id
                   AND e.entered_at >= %s AND e.entered_at < %s
             WHERE d.owner_name IS NOT NULL
             GROUP BY 1""", (list(_ST_NEGOC), a, b, a, b, a, b))
        dados = cur.fetchall()
    time_stats = []
    for nome, oports, wins, ticket in dados:
        if not ESP.time_de(nome, "closer"):
            continue
        time_stats.append({"nome": nome, "oports": oports or 0, "bookings": wins or 0,
                           "taxa_conv": (wins / oports if oports else None),
                           "ticket": float(ticket) if ticket else None,
                           "ciclo_dias": None, "perdas_top": None,
                           "ativo": not any(nome.lower().startswith(dd.split()[0].lower()) for dd in ESP.DESLIGADOS)})
    if not time_stats:
        return (f"<h1>Time de Vendas</h1><div class=sub>coordenação: {ESP.COORD_VENDAS}</div>"
                f"<section>{_aviso_coleta('dono dos deals (atribuição por closer)')}</section>")
    # motivo de perda dominante por closer
    with conn.cursor() as cur:
        cur.execute("""SELECT owner_name, lost_reason, count(*) FROM mkt_deals_attribution
                        WHERE status='lost' AND lost_time >= %s AND lost_time < %s
                          AND lost_reason IS NOT NULL AND stage_id IN (6, 5, 7)
                        GROUP BY 1, 2 ORDER BY 3 DESC""", (a, b))
        for own, motivo, _n in cur.fetchall():
            for p in time_stats:
                if p["nome"] == own and p["perdas_top"] is None:
                    p["perdas_top"] = motivo
    rows, planos = "", ""
    for p in sorted(time_stats, key=lambda x: -(x["taxa_conv"] or 0)):
        tag = "" if p["ativo"] else " <span class=chip style='--c:var(--status-semdados)'>desligado</span>"
        rows += (f"<tr><td style='{_TD}'><b>{escape(p['nome'][:26])}</b>{tag}</td>"
                 f"<td style='{_TD};text-align:right'>{p['oports']}</td>"
                 f"<td style='{_TD};text-align:right'>{p['bookings']}</td>"
                 f"<td style='{_TD};text-align:right'>{_fmt(p['taxa_conv'], 'pct')}</td>"
                 f"<td style='{_TD};text-align:right'>{_fmt(p['ticket'], 'brl')}</td>"
                 f"<td style='{_TD}'>{escape((p['perdas_top'] or '—')[:30])}</td></tr>")
        if p["ativo"]:
            pl = ESP.plano_closer(p, time_stats)
            itens = ("".join(f"<li style='color:var(--status-baixo)'>{escape(f)}</li>" for f in pl["fortes"])
                     + "".join(f"<li style='color:var(--status-alto)'>{escape(f)}</li>" for f in pl["fracos"])
                     + "".join(f"<li>→ {escape(acao)}</li>" for acao in pl["acoes"]))
            planos += (f"<div style='margin-top:12px'><b>{escape(p['nome'])}</b>"
                       f"<ul class=note style='margin:4px 0 0;padding-left:18px'>{itens}</ul></div>")
    return (f"<h1>Time de Vendas</h1><div class=sub>coordenação: {ESP.COORD_VENDAS} · dono do deal = atribuição · comparação com a mediana, tom construtivo</div>"
            f"<form method=get action=/vendas><input type=hidden name=view value=closers>{form}</form>"
            f"<section><h2>Performance por closer</h2>"
            + _card(_tbl([("Closer", "left"), ("Oports", "right"), ("Bookings", "right"), ("Conversão", "right"), ("Ticket", "right"), ("Perda nº1", "left")], rows)) + "</section>"
            f"<section><h2>Planos de ação individuais</h2><p class=secsub>{ESP.PERSONA_VENDAS}</p>{_card(planos or '<span class=note>—</span>')}</section>")


def _vd_forecast(conn, request: Request) -> str:
    """Performance mensal detalhada: meta por plano (qtde e R$) x fechado x
    pacing x o que FALTA FAZER (bookings -> oportunidades -> leads no ritmo
    atual). Mes selecionavel (?mes=YYYY-MM); meses passados = meta x realizado."""
    hoje = dt.date.today()
    qp = request.query_params
    try:
        mes = dt.date.fromisoformat((qp.get("mes") or hoje.strftime("%Y-%m")) + "-01")
    except ValueError:
        mes = hoje.replace(day=1)
    mes_atual = hoje.replace(day=1)
    corrente = (mes == mes_atual)
    prox = (mes.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    fim_mes = min(hoje, prox - dt.timedelta(days=1)) if corrente else (prox - dt.timedelta(days=1))
    a, b = _brt(mes, fim_mes)
    a90, _b90 = _brt(hoje - dt.timedelta(days=90), hoje)
    import calendar
    frac = min(1.0, hoje.day / calendar.monthrange(mes.year, mes.month)[1]) if corrente else 1.0

    with conn.cursor() as cur:
        cur.execute("SELECT plano, meta_qtde, meta_valor FROM mkt_goals WHERE mes=%s AND plano <> 'total'", (mes,))
        metas = {p_: (float(q or 0), float(v or 0)) for p_, q, v in cur.fetchall()}
        cur.execute("""SELECT COALESCE(substring(produto FROM 'B[1-5]'), 'outros'),
                              count(*), COALESCE(sum(valor), 0)
                         FROM mkt_deals_attribution
                        WHERE status='won' AND won_time >= %s AND won_time < %s GROUP BY 1""", (a, b))
        feito = {p_: (n, float(v)) for p_, n, v in cur.fetchall()}
        cur.execute("""SELECT COALESCE(substring(produto FROM 'B[1-5]'), 'outros'), count(*)
                         FROM mkt_deals_attribution WHERE status='open' AND stage_id IN (6, 5, 7)
                        GROUP BY 1""")
        pipe = dict(cur.fetchall())
        cur.execute("""SELECT count(DISTINCT deal_id) FROM mkt_stage_events
                        WHERE stage_id = ANY(%s) AND entered_at >= %s""", (list(_ST_NEGOC), a90))
        oport90 = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM mkt_deals_attribution WHERE status='won' AND won_time >= %s", (a90,))
        win90 = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM mkt_deals_attribution WHERE add_time >= %s", (a90,))
        leads90 = cur.fetchone()[0]
    conv90 = win90 / oport90 if oport90 else 0
    conv_lead90 = win90 / leads90 if leads90 else 0

    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT mes FROM mkt_goals ORDER BY mes")
        meses_opts = [m for (m,) in cur.fetchall()]
    opts = "".join(
        f"<option value='{m.strftime('%Y-%m')}' {'selected' if m == mes else ''}>{m.strftime('%m/%Y')}</option>"
        for m in meses_opts)
    form = (f"<form method=get action=/vendas><input type=hidden name=view value=forecast>"
            f"<div class=filters><div><label>mes</label><select name=mes>{opts}</select></div>"
            f"<button type=submit>Ver</button></div></form>")

    rows = ""
    tot = {"meta_q": 0.0, "meta_v": 0.0, "real_q": 0, "real_v": 0.0, "gap": 0.0, "oport": 0.0, "leads": 0.0}
    faltantes = []
    for plano in ("B1", "B2", "B3", "B4", "B5"):
        meta_q, meta_v = metas.get(plano, (0.0, 0.0))
        real_q, real_v = feito.get(plano, (0, 0.0))
        aberto = pipe.get(plano, 0)
        pct = real_q / meta_q if meta_q else None
        gap = max(0.0, meta_q - real_q)
        oport_nec = gap / conv90 if conv90 else None
        leads_nec = gap / conv_lead90 if conv_lead90 else None
        tot["meta_q"] += meta_q
        tot["meta_v"] += meta_v
        tot["real_q"] += real_q
        tot["real_v"] += real_v
        tot["gap"] += gap
        if oport_nec:
            tot["oport"] += oport_nec
        if leads_nec:
            tot["leads"] += leads_nec
        if gap and meta_q:
            faltantes.append((plano, gap, oport_nec, aberto))
        cor = "pos" if pct is not None and pct >= frac else ("neg" if meta_q else "")
        marcador = (f"<div style='position:absolute;left:{frac * 100:.0f}%;top:-2px;bottom:-2px;width:2px;background:var(--text-muted)'></div>"
                    if corrente else "")
        cor_barra = "status-baixo" if (pct or 0) >= frac else "status-critico"
        barra = (f"<div style='height:7px;background:var(--surface-3);border-radius:4px;overflow:visible;position:relative'>"
                 f"<div style='height:100%;width:{min(100, (pct or 0) * 100):.0f}%;background:var(--{cor_barra});border-radius:4px'></div>{marcador}</div>")
        destaque = " style='background:color-mix(in srgb,var(--brand) 5%,transparent)'" if plano in ("B3", "B4", "B5") else ""
        rows += (f"<tr{destaque}><td style='{_TD}'><b>{plano}</b></td>"
                 f"<td style='{_TD};text-align:right'>{meta_q:.0f}</td>"
                 f"<td style='{_TD};text-align:right'>{_fmt(meta_v, 'brl')}</td>"
                 f"<td style='{_TD};text-align:right'><b>{real_q}</b></td>"
                 f"<td style='{_TD};text-align:right'>{_fmt(real_v, 'brl')}</td>"
                 f"<td style='{_TD};text-align:right' class='{cor}'>{_fmt(pct, 'pct') if pct is not None else chr(8212)}</td>"
                 f"<td style='{_TD};min-width:110px'>{barra}</td>"
                 f"<td style='{_TD};text-align:right'>{gap:.0f}</td>"
                 f"<td style='{_TD};text-align:right'>{aberto}</td>"
                 f"<td style='{_TD};text-align:right'>{_fmt(oport_nec) if gap else chr(10003)}</td></tr>")
    pct_t = tot["real_q"] / tot["meta_q"] if tot["meta_q"] else None
    cor_t = "pos" if pct_t is not None and pct_t >= frac else "neg"
    pipe_tot = sum(pipe.get(p_, 0) for p_ in ("B1", "B2", "B3", "B4", "B5"))
    rows += (f"<tr style='border-top:2px solid var(--border-strong)'><td style='{_TD}'><b>TOTAL</b></td>"
             f"<td style='{_TD};text-align:right'><b>{tot['meta_q']:.0f}</b></td>"
             f"<td style='{_TD};text-align:right'><b>{_fmt(tot['meta_v'], 'brl')}</b></td>"
             f"<td style='{_TD};text-align:right'><b>{tot['real_q']}</b></td>"
             f"<td style='{_TD};text-align:right'><b>{_fmt(tot['real_v'], 'brl')}</b></td>"
             f"<td style='{_TD};text-align:right' class='{cor_t}'><b>{_fmt(pct_t, 'pct') if pct_t is not None else chr(8212)}</b></td>"
             f"<td style='{_TD}'></td>"
             f"<td style='{_TD};text-align:right'><b>{tot['gap']:.0f}</b></td>"
             f"<td style='{_TD};text-align:right'><b>{pipe_tot}</b></td>"
             f"<td style='{_TD};text-align:right'><b>{_fmt(tot['oport']) if tot['gap'] else chr(10003)}</b></td></tr>")

    plano_gap = ""
    if corrente and faltantes:
        itens = ""
        for plano, gap, oport_nec, aberto in sorted(faltantes, key=lambda x: -x[1]):
            if oport_nec is not None:
                sufic = " — INSUFICIENTE" if aberto < oport_nec else " — suficiente se converter no ritmo"
                cobre = f" (pipeline atual: {aberto} abertas{sufic})"
            else:
                cobre = ""
            itens += (f"<div class=sug-item><b>{plano}</b>: faltam <b>{gap:.0f} bookings</b> "
                      f"&rarr; &asymp; <b>{_fmt(oport_nec)} oportunidades</b> no ritmo de conversao 90d ({_fmt(conv90, 'pct')}){cobre}</div>")
        itens += (f"<div class=sug-item><b>Total</b>: {tot['gap']:.0f} bookings &asymp; {_fmt(tot['oport'])} oportunidades "
                  f"&asymp; <b>{_fmt(tot['leads'])} leads novos</b> (conversao lead&rarr;booking 90d: {_fmt(conv_lead90, 'pct')}) "
                  "&mdash; e o pedido concreto a Pre-vendas e ao Marketing para fechar o mes.</div>")
        estilo = ("<style>.sug-item{padding:8px 0;border-top:1px solid var(--border);font-size:var(--fs-sm);"
                  "line-height:1.6;color:var(--text-2)}.sug-item:first-child{border-top:none}</style>")
        plano_gap = ("<section><h2>O que falta para bater as metas</h2>"
                     "<p class=secsub>gap por plano traduzido em oportunidades e leads necessarios no ritmo atual</p>"
                     + _card(itens + estilo) + "</section>")

    ritmo = f" &middot; ritmo esperado: {frac * 100:.0f}% do mes" if corrente else " (mes encerrado)"
    return (f"<h1>Performance & Meta &mdash; {mes.strftime('%m/%Y')}</h1>"
            f"<div class=sub>metas da planilha financeira por plano &middot; fechado no mes &middot; pacing{ritmo} &middot; conversao 90d: {_fmt(conv90, 'pct')} (oport&rarr;booking)</div>"
            + form +
            "<section><h2>Meta &times; realizado por plano</h2><p class=secsub>B3-B5 em destaque (prioridade da empresa) &middot; traco vertical = ritmo esperado</p>"
            + _card(_tbl([("Plano", "left"), ("Meta", "right"), ("Meta R$", "right"), ("Fechado", "right"),
                          ("Receita", "right"), ("% meta", "right"), ("", "left"), ("Gap", "right"),
                          ("Pipeline", "right"), ("Oport. nec.", "right")], rows)) + "</section>"
            + plano_gap)


# ---------------------------------------------------------------------------
@router.get("/prevendas", response_class=HTMLResponse)
def prevendas(request: Request, view: str = Query("funil")):
    A = _deps()
    s, redir = A._require_area(request, "prevendas")
    if redir:
        return redir
    user, _role = s
    if view not in {v for v, _ in _PV_VIEWS}:
        view = "funil"
    with A._conn() as c:
        with c.cursor() as cur:
            cur.execute("INSERT INTO audit_log (actor, action, scope) VALUES (%s,'view',%s)",
                        (user, f"prevendas/{view}"))
        fn = {"funil": _pv_funil, "speed": _pv_speed, "horarios": _pv_horarios,
              "sdrs": _pv_sdrs}[view]
        content = fn(c, request) + "<p class=foot>Fonte: Pipedrive (cache local, coleta diária). A decisão é sempre do gestor — o especialista sinaliza.</p>"
    return HTMLResponse(_shell(A, "prevendas", _PV_VIEWS, view, content, user))


@router.get("/vendas", response_class=HTMLResponse)
def vendas(request: Request, view: str = Query("funil")):
    A = _deps()
    s, redir = A._require_area(request, "vendas")
    if redir:
        return redir
    user, _role = s
    if view not in {v for v, _ in _VD_VIEWS}:
        view = "funil"
    with A._conn() as c:
        with c.cursor() as cur:
            cur.execute("INSERT INTO audit_log (actor, action, scope) VALUES (%s,'view',%s)",
                        (user, f"vendas/{view}"))
        fn = {"funil": _vd_funil, "winloss": _vd_winloss, "ciclo": _vd_ciclo,
              "closers": _vd_closers, "forecast": _vd_forecast}[view]
        content = fn(c, request) + "<p class=foot>Fonte: Pipedrive (cache local, coleta diária). A decisão é sempre do gestor — o especialista sinaliza.</p>"
    return HTMLResponse(_shell(A, "vendas", _VD_VIEWS, view, content, user))
