"""Áreas de PRÉ-VENDAS (/prevendas) e VENDAS (/vendas) — mesma casca do painel.

Corte validado pelo Otávio (08/07/26): Pré-vendas atua ATÉ O AGENDAMENTO da
reunião (stages 1-4 do Comercial + pipeline 2 de Prospecção); Vendas assume da
Reunião Agendada (6) em diante (5 Reagendamento, 7 Negociação, won/lost).
Fontes: mkt_deals_attribution (deal+dono+motivo), mkt_stage_events (/flow) e
sales_first_touch (1º contato). Funil = régua OFICIAL do dashboard do time
(ver _funil_oficial no marketing/ui.py; corte em horário de Brasília).
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

# "Time & Planos" virou "Desempenho Individual" (14/07 — feedback do Otávio:
# o foco é o desempenho de cada membro, não os planos/bundles)
_PV_VIEWS = [("funil", "Funil de Qualificação"), ("speed", "Speed-to-Lead"),
             ("horarios", "Melhor Horário"), ("sdrs", "Desempenho Individual")]
_VD_VIEWS = [("funil", "Funil de Fechamento"), ("ponte", "Ponte PV → Vendas"),
             ("winloss", "Win/Loss"), ("ciclo", "Ciclo & Empacados"),
             ("horarios", "Melhor Horário"), ("closers", "Desempenho Individual"),
             ("forecast", "Performance & Meta")]

# etapas (validadas na inspeção do Pipedrive 08/07)
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
    html = MS(A, usermail, view, content, usermail=usermail, help_area=area)
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
    # Funil = MESMA taxonomia e régua OFICIAL do Funil de Prospecção do
    # Marketing (_funil_oficial = a régua do dashboard do time no Pipedrive):
    # Lead = criados no período · MQL/SAL = descontam desqualificados por
    # motivo · SQL = dono atual é closer (agendou = handoff p/ Vendas).
    # Oportunidade/Booking ficam no Funil de Fechamento (/vendas).
    from ..marketing.ui import _funil_oficial, funil_visual_html
    passou, booked, leads, receita = _funil_oficial(conn, ini, fim)
    sql_n = passou[3]
    # funil COMPLETO Lead→Booking (14/07: "interessante todos terem a visão
    # completa") — o trabalho de PV termina no SQL, o resto é contexto
    funil_visual = funil_visual_html(
        [("Lead", passou[0]), ("MQL", passou[1]), ("SAL", passou[2]),
         ("SQL", passou[3]), ("Oportunidade", passou[4]), ("Booking", booked)],
        leads, receita)
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
    # DIA DA SEMANA de chegada do lead × conversão (13/07): lead que chega
    # perto do fim de semana esfria? Coorte; reunião conta a qualquer tempo.
    with conn.cursor() as cur:
        cur.execute("""
            SELECT extract(dow FROM d.add_time AT TIME ZONE 'America/Sao_Paulo')::int,
                   count(*),
                   count(*) FILTER (WHERE EXISTS (SELECT 1 FROM mkt_stage_events e
                                     WHERE e.deal_id = d.deal_id AND e.stage_id = 6))
              FROM mkt_deals_attribution d
             WHERE d.add_time >= %s AND d.add_time < %s GROUP BY 1 ORDER BY 1""", (a, b))
        ddados = {dow: (n, ag) for dow, n, ag in cur.fetchall()}
    drows_sem = ""
    for dow in (1, 2, 3, 4, 5, 6, 0):
        n, ag = ddados.get(dow, (0, 0))
        if not n:
            continue
        drows_sem += (f"<tr><td style='{_TD}'><b>{_DOW_NOME[dow]}</b></td>"
                      f"<td style='{_TD};text-align:right'>{n}</td>"
                      f"<td style='{_TD};text-align:right'>{ag}</td>"
                      f"<td style='{_TD};text-align:right'>{_fmt(ag / n, 'pct')}</td></tr>")

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
    # p/ o especialista, "recebeu 1º contato" continua sendo o EVENTO de etapa
    # (2/13, coorte) — o SAL oficial desconta desqualificados, é outra medida
    contato = _entradas(conn, (2, 13), a, b)
    ins = ESP.insights_prevendas({
        "taxa_contato": contato / leads if leads else None,
        "taxa_agend": sql_n / leads if leads else None,
        "desq_top": (desq[0] if desq and desq[0][0] != "(sem motivo)" else None)})
    ins_html = "".join(f"<div class=sug-item>→ {escape(i)}</div>" for i in ins)
    return (f"<h1>Funil de Qualificação</h1><div class=sub>régua OFICIAL do dashboard do time — os números batem com o Pipedrive/Lovable · o trabalho de Pré-vendas vai do Lead ao SQL (agendou = deal na mão de closer); Oportunidade e Booking mostram o destino final</div>"
            f"<form method=get action=/prevendas><input type=hidden name=view value=funil>{form}</form>"
            f"<section><h2>Funil completo (Lead → Booking)</h2><p class=secsub>largura proporcional ao volume · pílula = conversão sobre a etapa anterior · os mesmos números das abas de Marketing e Vendas</p>{funil_visual}</section>"
            f"<section><h2>Conversão por dia de chegada do lead</h2><p class=secsub>taxa de agendamento pelo dia da semana em que o lead entrou — a reunião conta a qualquer tempo (coorte)</p>"
            + _card(_tbl([("Dia de chegada", "left"), ("Leads", "right"), ("Agendaram", "right"),
                          ("Taxa", "right")], drows_sem)) + "</section>"
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
    from .. import team_config as TC
    mins, por_quem, por_origem, sem_toque = [], {}, {}, 0
    for _did, add, first, quem, origem in rows:
        if not first:
            sem_toque += 1
            continue
        m = max(0.0, (first - add).total_seconds() / 60)
        mins.append(m)
        # desligados não aparecem no recorte por pessoa (os agregados os incluem)
        if not TC.eh_desligado(conn, "prevendas", quem):
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

    # VELOCIDADE × CONVERSÃO (movida do Funil 13/07 — é assunto desta aba):
    # prova com dado próprio quanto custa lead esperando. Coorte do período.
    with conn.cursor() as cur:
        cur.execute("""
            WITH base AS (
                SELECT d.deal_id,
                       EXTRACT(epoch FROM (t.first_at - d.add_time)) / 60 AS mins,
                       COALESCE(t.tipo, '(sem registro)') AS tipo,
                       EXISTS (SELECT 1 FROM mkt_stage_events e
                                WHERE e.deal_id = d.deal_id AND e.stage_id = 6) AS agendou
                  FROM mkt_deals_attribution d
                  LEFT JOIN sales_first_touch t ON t.deal_id = d.deal_id
                 WHERE d.add_time >= %s AND d.add_time < %s)
            SELECT CASE WHEN mins IS NULL THEN '6. sem contato registrado'
                        WHEN mins <= 15 THEN '1. até 15 min'
                        WHEN mins <= 60 THEN '2. 15-60 min'
                        WHEN mins <= 240 THEN '3. 1-4 horas'
                        WHEN mins <= 1440 THEN '4. 4-24 horas'
                        ELSE '5. mais de 24 horas' END AS faixa,
                   count(*), count(*) FILTER (WHERE agendou)
              FROM base GROUP BY 1 ORDER BY 1""", (a, b))
        vdados = cur.fetchall()
        cur.execute("""
            SELECT COALESCE(t.tipo, '(sem registro)'), count(*),
                   count(*) FILTER (WHERE EXISTS (SELECT 1 FROM mkt_stage_events e
                                     WHERE e.deal_id = d.deal_id AND e.stage_id = 6))
              FROM mkt_deals_attribution d
              LEFT JOIN sales_first_touch t ON t.deal_id = d.deal_id
             WHERE d.add_time >= %s AND d.add_time < %s
             GROUP BY 1 HAVING count(*) >= 5 ORDER BY 2 DESC""", (a, b))
        tdados = cur.fetchall()
    vrows, taxas_v = "", {}
    for faixa, n, ag in vdados:
        tx = ag / n if n else None
        taxas_v[faixa[0]] = tx
        vrows += (f"<tr><td style='{_TD}'><b>{escape(faixa[3:])}</b></td>"
                  f"<td style='{_TD};text-align:right'>{n}</td>"
                  f"<td style='{_TD};text-align:right'>{ag}</td>"
                  f"<td style='{_TD};text-align:right'>{_fmt(tx, 'pct')}</td></tr>")
    destaque_v = ""
    if taxas_v.get("1") and taxas_v.get("5"):
        razao = taxas_v["1"] / taxas_v["5"] if taxas_v["5"] else None
        if razao and razao > 1.2:
            destaque_v = (f"<div class=note style='margin-top:8px'>lead contatado em até 15 min agenda "
                          f"<b>{razao:.1f}x mais</b> que lead que esperou 24h+ — a fila sem contato é a "
                          "maior alavanca da área.</div>")
    trows_tipo = "".join(
        f"<tr><td style='{_TD}'><b>{escape(str(tp)[:34])}</b></td>"
        f"<td style='{_TD};text-align:right'>{n}</td>"
        f"<td style='{_TD};text-align:right'>{ag}</td>"
        f"<td style='{_TD};text-align:right'>{_fmt(ag / n if n else None, 'pct')}</td></tr>"
        for tp, n, ag in tdados)

    return (f"<h1>Speed-to-Lead</h1><div class=sub>tempo entre o lead entrar e o 1º contato registrado no Pipedrive · SLA-alvo a confirmar com o Marcos</div>"
            f"<form method=get action=/prevendas><input type=hidden name=view value=speed>{form}</form>"
            + kpis +
            f"<section><h2>Velocidade do 1º contato × conversão</h2><p class=secsub>leads do período por faixa de tempo até o 1º contato — a reunião conta a qualquer tempo (coorte); períodos recentes ainda amadurecem</p>"
            + _card(_tbl([("1º contato em", "left"), ("Leads", "right"), ("Agendaram", "right"),
                          ("Taxa", "right")], vrows) + destaque_v) + "</section>"
            f"<section><h2>Taxa de agendamento por tipo de 1º contato</h2><p class=secsub>ligação, WhatsApp, cadência… — qual abordagem inicial converte mais (mín. 5 leads)</p>"
            + _card(_tbl([("Tipo", "left"), ("Leads", "right"), ("Agendaram", "right"),
                          ("Taxa", "right")], trows_tipo)) + "</section>"
            f"<section><h2>Por responsável do 1º contato</h2>{_card(bloco(por_quem))}</section>"
            f"<section><h2>Por origem</h2>{_card(bloco(por_origem))}</section>")


def _pv_sdrs(conn, request: Request) -> str:
    _ensure_touch(conn)
    ini, fim, form = _periodo(request)
    a, b = _brt(ini, fim)
    from .. import team_config as TC

    # ---- números OFICIAIS por colaborador (régua dos gráficos do Pipedrive/
    # Insights que a gestão acompanha): atribuição = campo SDR do deal, SEM
    # fallback — deal sem o campo entra em '(sem SDR definido)'. Leads = deals
    # CRIADOS no período; Oportunidades = campo Dia Oportunidade no período
    # (TODOS os deals, não é coorte); Bookings = won no período
    _SEM = "(sem SDR definido)"
    with conn.cursor() as cur:
        cur.execute("""SELECT COALESCE(sdr, %s), count(*)
                         FROM mkt_deals_attribution
                        WHERE add_time >= %s AND add_time < %s GROUP BY 1""", (_SEM, a, b))
        leads_por = dict(cur.fetchall())
        cur.execute("""SELECT COALESCE(sdr, %s), count(*)
                         FROM mkt_deals_attribution
                        WHERE oport_time >= %s AND oport_time < %s GROUP BY 1""", (_SEM, a, b))
        oport_por = dict(cur.fetchall())
        cur.execute("""SELECT COALESCE(sdr, %s), count(*),
                              COALESCE(sum(COALESCE(valor_custom, valor)), 0)
                         FROM mkt_deals_attribution
                        WHERE status='won' AND won_time >= %s AND won_time < %s GROUP BY 1""", (_SEM, a, b))
        book_por = {n: (q, float(v)) for n, q, v in cur.fetchall()}
    # speed do 1º contato por pessoa (sales_first_touch) — entra como COLUNA
    # da mesma tabela, casada por nome; os volumes são sempre os oficiais acima
    with conn.cursor() as cur:
        cur.execute("""
            SELECT t.quem,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY EXTRACT(epoch FROM t.first_at - d.add_time) / 60)
              FROM sales_first_touch t
              JOIN mkt_deals_attribution d ON d.deal_id = t.deal_id
             WHERE d.add_time >= %s AND d.add_time < %s AND t.quem IS NOT NULL AND t.quem <> ''
             GROUP BY 1""", (a, b))
        speed_por = {TC.norm(q): float(s) for q, s in cur.fetchall() if s is not None}

    colaboradores = sorted(set(leads_por) | set(oport_por),
                           key=lambda n: (n == _SEM, -leads_por.get(n, 0), -oport_por.get(n, 0)))
    orows, tl, ex = "", [0, 0, 0], [0, 0, 0]
    time_stats, planos, visiveis = [], "", []
    for nome in colaboradores[:15]:
        l, o = leads_por.get(nome, 0), oport_por.get(nome, 0)
        bq, _bv = book_por.get(nome, (0, 0.0))
        tl[0] += l; tl[1] += o; tl[2] += bq
        # desligados (detecção automática no Pipedrive) NÃO aparecem — os
        # números vão p/ a linha agregada '(ex-colaboradores)' p/ o Total fechar
        if nome != _SEM and TC.eh_desligado(conn, "prevendas", nome):
            ex[0] += l; ex[1] += o; ex[2] += bq
            continue
        if nome != _SEM:
            visiveis.append(nome)
        speed = speed_por.get(TC.norm(nome))
        papel = TC.papel_de(conn, "prevendas", nome)
        if nome == _SEM:
            chip = ""
        elif papel == "coordenacao":
            # coordenação trabalha leads mas não entra em planos/mediana do time
            chip = " <span class=chip style='--c:var(--brand)'>coordenação</span>"
        elif papel == "gerencia":
            chip = " <span class=chip style='--c:var(--brand)'>gerência</span>"
        elif papel == "membro":
            chip = ""
        else:
            chip = " <span class=chip style='--c:var(--status-semdados)'>fora do time de PV</span>"
        orows += (f"<tr><td style='{_TD}'><b>{escape(nome[:30])}</b>{chip}</td>"
                  f"<td style='{_TD};text-align:right'>{l}</td>"
                  f"<td style='{_TD};text-align:right'>{o}</td>"
                  f"<td style='{_TD};text-align:right'>{_fmt(o / l if l else None, 'pct')}</td>"
                  f"<td style='{_TD};text-align:right'>{bq or ''}</td>"
                  f"<td style='{_TD};text-align:right'>{_fmt(speed, 'min')}</td></tr>")
        if papel == "membro":
            time_stats.append({"nome": nome, "leads": l, "agendadas": o,
                               "taxa_agend": (o / l if l else None), "speed_min": speed,
                               "ativo": True})
    if any(ex):
        orows += (f"<tr><td style='{_TD};color:var(--text-faint)'>(ex-colaboradores)</td>"
                  f"<td style='{_TD};text-align:right;color:var(--text-faint)'>{ex[0] or ''}</td>"
                  f"<td style='{_TD};text-align:right;color:var(--text-faint)'>{ex[1] or ''}</td>"
                  f"<td style='{_TD}'></td>"
                  f"<td style='{_TD};text-align:right;color:var(--text-faint)'>{ex[2] or ''}</td>"
                  f"<td style='{_TD}'></td></tr>")
    orows += (f"<tr><td style='{_TD};border-top:2px solid var(--border-strong)'><b>Total</b></td>"
              f"<td style='{_TD};text-align:right;border-top:2px solid var(--border-strong)'><b>{tl[0]}</b></td>"
              f"<td style='{_TD};text-align:right;border-top:2px solid var(--border-strong)'><b>{tl[1]}</b></td>"
              f"<td style='{_TD};text-align:right;border-top:2px solid var(--border-strong)'>{_fmt(tl[1] / tl[0] if tl[0] else None, 'pct')}</td>"
              f"<td style='{_TD};text-align:right;border-top:2px solid var(--border-strong)'><b>{tl[2]}</b></td>"
              f"<td style='{_TD};border-top:2px solid var(--border-strong)'></td></tr>")
    oficial = ("<section><h2>Leads e oportunidades por colaborador</h2>"
               "<p class=secsub>volumes na régua dos gráficos do Pipedrive (atribuição pelo campo SDR do deal; "
               "leads = criados no período · oportunidades = Dia Oportunidade no período) · Speed = mediana do 1º contato registrado (atividades) · "
               "lead ainda sem SDR entra em '(sem SDR definido)' · desligados (detectados no Pipedrive) ficam agregados em '(ex-colaboradores)'</p>"
               + _card(_tbl([("Colaborador", "left"), ("Leads", "right"), ("Oportunidades", "right"),
                             ("Lead→Oport", "right"), ("Bookings", "right"), ("Speed 1º contato", "right")], orows)) + "</section>")

    # ---- estudos por SDR (pedidos 14/07): desqualificação, origem e plano ---
    cols = visiveis[:5]
    _nc = "padding:6px 7px;border-bottom:1px solid var(--border);font-variant-numeric:tabular-nums;font-size:var(--fs-xs)"

    def _abrev(n: str) -> str:
        ps = n.split()
        return n if len(ps) < 2 else f"{ps[0]} {ps[1][0]}."

    # (a) motivos de DESQUALIFICAÇÃO por SDR (perdidos pré-handoff da coorte)
    with conn.cursor() as cur:
        cur.execute("""SELECT COALESCE(sdr, %s), COALESCE(lost_reason, '(sem motivo)'), count(*)
                         FROM mkt_deals_attribution
                        WHERE add_time >= %s AND add_time < %s AND status='lost'
                          AND stage_id NOT IN (6, 5, 7)
                        GROUP BY 1, 2""", (_SEM, a, b))
        desq_por: dict[str, list[tuple[str, int]]] = {}
        for nome, m, n in cur.fetchall():
            desq_por.setdefault(nome, []).append((m, n))
    dcards = ""
    for nome in cols:
        motivos = desq_por.get(nome) or []
        tot_d = sum(n for _m, n in motivos)
        l_tot = leads_por.get(nome, 0)
        linhas_m = ""
        for m, n in sorted(motivos, key=lambda x: -x[1])[:4]:
            pct = n / tot_d if tot_d else 0
            cor_txt = "var(--text-faint)" if m == "(sem motivo)" else "var(--text-2)"
            linhas_m += (
                f"<div style='margin-top:7px'><div style='display:flex;justify-content:space-between;gap:8px;"
                f"font-size:var(--fs-xs);color:{cor_txt}'><span>{escape(str(m)[:38])}</span>"
                f"<span style='white-space:nowrap;font-variant-numeric:tabular-nums'><b>{n}</b> · {_fmt(pct, 'pct')}</span></div>"
                f"<div style='height:4px;background:var(--surface-3);border-radius:2px;overflow:hidden;margin-top:2px'>"
                f"<div style='height:100%;width:{pct * 100:.0f}%;background:var(--status-alto);border-radius:2px'></div></div></div>")
        dcards += (f"<div class=card><div style='display:flex;justify-content:space-between;align-items:baseline'>"
                   f"<b>{escape(_abrev(nome))}</b><span style='color:var(--text-muted);font-size:var(--fs-xs)'>"
                   f"{tot_d} desq. · {_fmt(tot_d / l_tot if l_tot else None, 'pct')} dos leads</span></div>"
                   + (linhas_m or "<div class=note style='margin-top:7px'>sem desqualificações no período</div>") + "</div>")
    sec_desq = ("<section><h2>Motivos de desqualificação por SDR</h2>"
                "<p class=secsub>perdidos antes do handoff, dentre os leads do período de cada uma — motivo dominante em UMA pessoa = dificuldade específica (roteiro/abordagem); igual em todas = qualidade do lead</p>"
                f"<div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px;align-items:start'>{dcards}</div></section>") if dcards else ""

    # (b) conversão por ORIGEM × SDR (coorte: lead do período que virou oportunidade)
    with conn.cursor() as cur:
        cur.execute("""SELECT COALESCE(sdr, %s), COALESCE(origem, '(vazio)'), count(*),
                              count(*) FILTER (WHERE oport_time IS NOT NULL)
                         FROM mkt_deals_attribution
                        WHERE add_time >= %s AND add_time < %s GROUP BY 1, 2""", (_SEM, a, b))
        ori: dict[str, dict[str, tuple[int, int]]] = {}
        ori_tot: dict[str, list[int]] = {}
        for nome, og, n, op in cur.fetchall():
            ori.setdefault(og, {})[nome] = (n, op)
            t = ori_tot.setdefault(og, [0, 0])
            t[0] += n; t[1] += op
    origens_top = sorted((og for og, t in ori_tot.items() if t[0] >= 10),
                         key=lambda og: -ori_tot[og][0])[:8]
    xrows = ""
    for og in origens_top:
        tl_o, to_o = ori_tot[og]
        tx_time = to_o / tl_o if tl_o else 0
        tds = ""
        for nome in cols:
            n, op = ori.get(og, {}).get(nome, (0, 0))
            if not n:
                tds += f"<td style='{_nc};text-align:center;color:var(--text-faint)'>—</td>"
                continue
            tx = op / n
            cls = ""
            if n >= 8 and tx_time:
                cls = (" class=pos" if tx >= tx_time * 1.15 else (" class=neg" if tx <= tx_time * 0.7 else ""))
            tds += (f"<td style='{_nc};text-align:center'{cls} title='{op} oportunidade(s) de {n} leads'>"
                    f"{_fmt(tx, 'pct')}<span style='color:var(--text-faint);font-size:var(--fs-2xs)'> ({n})</span></td>")
        xrows += (f"<tr><td style='{_nc}'>{escape(og[:26])}</td>"
                  f"<td style='{_nc};text-align:center'><b>{_fmt(tx_time, 'pct')}</b>"
                  f"<span style='color:var(--text-faint);font-size:var(--fs-2xs)'> ({tl_o})</span></td>{tds}</tr>")
    sec_ori = ("<section><h2>Conversão por origem × SDR</h2>"
               "<p class=secsub>taxa lead→oportunidade (coorte do período; a oportunidade conta a qualquer tempo) · verde = bem acima do time naquela origem, vermelho = bem abaixo (mín. 8 leads) — mostra quem trata melhor cada tipo de lead</p>"
               + _card(_tbl([("Origem", "left"), ("Time", "center")] + [(_abrev(n), "center") for n in cols], xrows))
               + "</section>") if xrows else ""

    # (c) AGENDAMENTOS (oportunidades) por PLANO × SDR
    with conn.cursor() as cur:
        cur.execute("""SELECT COALESCE(sdr, %s),
                              COALESCE(substring(produto FROM 'B[1-5]'),
                                       CASE WHEN produto IS NULL OR produto = '' THEN '(sem plano)' ELSE 'outros' END),
                              count(*)
                         FROM mkt_deals_attribution
                        WHERE oport_time >= %s AND oport_time < %s GROUP BY 1, 2""", (_SEM, a, b))
        bnd: dict[str, dict[str, int]] = {}
        for nome, bd, n in cur.fetchall():
            bnd.setdefault(bd, {})[nome] = n
    ordem_b = [x for x in ("B1", "B2", "B3", "B4", "B5", "outros", "(sem plano)") if x in bnd] \
        + sorted(set(bnd) - {"B1", "B2", "B3", "B4", "B5", "outros", "(sem plano)"})
    tot_sdr_b = {nome: sum(bnd[bd].get(nome, 0) for bd in bnd) for nome in cols}
    brws = ""
    for bd in ordem_b:
        tds = ""
        for nome in cols:
            n = bnd[bd].get(nome, 0)
            pct = n / tot_sdr_b[nome] if tot_sdr_b.get(nome) else 0
            tds += (f"<td style='{_nc};text-align:center'>{n or '—'}"
                    + (f"<span style='color:var(--text-faint);font-size:var(--fs-2xs)'> ({pct * 100:.0f}%)</span>" if n else "")
                    + "</td>")
        brws += f"<tr><td style='{_nc}'><b>{escape(bd)}</b></td>{tds}</tr>"
    sec_bnd = ("<section><h2>Oportunidades por plano × SDR</h2>"
               "<p class=secsub>oportunidades geradas no período por bundle (% = participação no total da própria SDR) · mix concentrado em B1 numa pessoa com o time mirando B3-B5 = qualificação a puxar para cima</p>"
               + _card(_tbl([("Plano", "left")] + [(_abrev(n), "center") for n in cols], brws))
               + "</section>") if brws else ""

    # planos de ação individuais sobre os MESMOS números da tabela (só time ativo)
    for p in sorted(time_stats, key=lambda x: -(x["taxa_agend"] or 0)):
        if not p["ativo"]:
            continue
        # motivo de desqualificação dominante da pessoa entra no plano (14/07)
        motivos_p = [x for x in (desq_por.get(p["nome"]) or []) if x[0] != "(sem motivo)"]
        if motivos_p:
            top_m = max(motivos_p, key=lambda x: x[1])
            if top_m[1] >= 5:
                p["desq_top"] = top_m
        pl = ESP.plano_sdr(p, time_stats)
        itens = ("".join(f"<li style='color:var(--status-baixo)'>{escape(f)}</li>" for f in pl["fortes"])
                 + "".join(f"<li style='color:var(--status-alto)'>{escape(f)}</li>" for f in pl["fracos"])
                 + "".join(f"<li>→ {escape(acao)}</li>" for acao in pl["acoes"]))
        planos += (f"<div style='margin-top:12px'><b>{escape(p['nome'])}</b>"
                   f"<ul class=note style='margin:4px 0 0;padding-left:18px'>{itens}</ul></div>")
    return (f"<h1>Desempenho Individual — Pré-vendas</h1><div class=sub>coordenação: {ESP.COORD_PREVENDAS} · lista do time editável no Painel Administrativo · comparação com a mediana, tom construtivo</div>"
            f"<form method=get action=/prevendas><input type=hidden name=view value=sdrs>{form}</form>"
            + oficial + sec_desq + sec_ori + sec_bnd +
            f"<section><h2>Planos de ação individuais</h2><p class=secsub>{ESP.PERSONA_PREVENDAS} · derivados dos números da primeira tabela</p>{_card(planos or '<span class=note>—</span>')}</section>")


# --- Melhor Horário (pedido do time de Pré-vendas, 10/07/26) ----------------
_DOW_NOME = ["dom", "seg", "ter", "qua", "qui", "sex", "sáb"]
# SÓ a etapa 6 (Reunião Agendada do Comercial): a 15 é Qualificação da
# Prospecção e inflava a contagem (mai: 461 vs 444 do Pipedrive — 13/07)
_ST_AGENDA = (6,)


def _horarios_periodo(request: Request) -> tuple[dt.date, dt.date, str]:
    # padrão = início do mês atual → hoje (regra do Otávio 14/07 p/ TODOS os
    # filtros de data; era 180d aqui — p/ estudo longo, é só ajustar o "de")
    hoje = dt.date.today()
    qp = request.query_params
    ini_s = qp.get("ini") or hoje.replace(day=1).isoformat()
    fim_s = qp.get("fim") or hoje.isoformat()
    try:
        ini, fim = dt.date.fromisoformat(ini_s), dt.date.fromisoformat(fim_s)
    except ValueError:
        ini, fim = hoje.replace(day=1), hoje
    bundle = qp.get("bundle") or "todos"
    if bundle not in ("B1", "B2", "B3", "B4", "B5"):
        bundle = "todos"
    return ini, fim, bundle


def _horarios_calc(conn, ini: dt.date, fim: dt.date, bundle: str) -> dict:
    """Agregados do estudo (célula dia×hora, por bundle, total) — usados pela
    aba do painel e pelo relatório imprimível."""
    a, b = _brt(ini, fim)
    filtro_b = ""
    args: list = [a, b]
    if bundle in ("B1", "B2", "B3", "B4", "B5"):
        filtro_b = " AND substring(d.produto FROM 'B[1-5]') = %s"
        args.append(bundle)
    # régua do Pipedrive: cada DEAL conta UMA vez no período (1ª entrada na
    # etapa) — reagendamento não duplica (13/07: 134 eventos vs 120 deals)
    with conn.cursor() as cur:
        cur.execute(f"""
            WITH primeira AS (
                SELECT e.deal_id, min(e.entered_at) AS entered_at
                  FROM mkt_stage_events e
                  JOIN mkt_deals_attribution d ON d.deal_id = e.deal_id
                 WHERE e.stage_id = ANY(%s) AND e.entered_at >= %s AND e.entered_at < %s{filtro_b}
                 GROUP BY e.deal_id)
            SELECT extract(dow  FROM entered_at AT TIME ZONE 'America/Sao_Paulo')::int,
                   extract(hour FROM entered_at AT TIME ZONE 'America/Sao_Paulo')::int,
                   count(*)
              FROM primeira GROUP BY 1, 2""", [list(_ST_AGENDA)] + args)
        celulas = {(dow, h): n for dow, h, n in cur.fetchall()}
        # melhores janelas POR BUNDLE (independe do filtro acima)
        cur.execute("""
            WITH primeira AS (
                SELECT e.deal_id, min(e.entered_at) AS entered_at,
                       COALESCE(substring(min(d.produto) FROM 'B[1-5]'), 'sem produto') AS p
                  FROM mkt_stage_events e
                  JOIN mkt_deals_attribution d ON d.deal_id = e.deal_id
                 WHERE e.stage_id = ANY(%s) AND e.entered_at >= %s AND e.entered_at < %s
                 GROUP BY e.deal_id)
            SELECT p, extract(dow  FROM entered_at AT TIME ZONE 'America/Sao_Paulo')::int,
                   extract(hour FROM entered_at AT TIME ZONE 'America/Sao_Paulo')::int, count(*)
              FROM primeira GROUP BY 1, 2, 3""", (list(_ST_AGENDA), a, b))
        por_bundle: dict[str, dict[tuple[int, int], int]] = {}
        for p, dow, h, n in cur.fetchall():
            por_bundle.setdefault(p, {})[(dow, h)] = n
        # por COLABORADOR × hora (pedido 14/07: alguém rende mais/menos em
        # determinado horário?) — atribuição oficial pelo campo SDR do deal;
        # respeita o filtro de bundle da tela
        cur.execute(f"""
            WITH primeira AS (
                SELECT e.deal_id, min(e.entered_at) AS entered_at
                  FROM mkt_stage_events e
                  JOIN mkt_deals_attribution d ON d.deal_id = e.deal_id
                 WHERE e.stage_id = ANY(%s) AND e.entered_at >= %s AND e.entered_at < %s{filtro_b}
                 GROUP BY e.deal_id)
            SELECT COALESCE(d.sdr, '(sem SDR)'),
                   extract(hour FROM p.entered_at AT TIME ZONE 'America/Sao_Paulo')::int,
                   count(*)
              FROM primeira p JOIN mkt_deals_attribution d ON d.deal_id = p.deal_id
             GROUP BY 1, 2""", [list(_ST_AGENDA)] + args)
        por_colab: dict[str, dict[int, int]] = {}
        for nome, h, n in cur.fetchall():
            por_colab.setdefault(nome, {})[h] = n
    return {"celulas": celulas, "por_bundle": por_bundle, "por_colab": por_colab,
            "total": sum(celulas.values())}


def _pv_horarios(conn, request: Request) -> str:
    """Estudo de dias/horários em que reuniões são AGENDADAS (entrada do deal na
    etapa Reunião Agendada, horário de Brasília) — melhor janela p/ o SDR ligar,
    geral e por bundle. Base: mkt_stage_events (o carimbo é o momento em que o
    card foi movido — proxy da ligação que converteu)."""
    ini, fim, bundle = _horarios_periodo(request)
    dados = _horarios_calc(conn, ini, fim, bundle)
    celulas, por_bundle, total = dados["celulas"], dados["por_bundle"], dados["total"]
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

    # --- colaborador × hora: cada linha na PRÓPRIA escala (o forte de cada um,
    # independente do volume); pico da pessoa = célula CONTORNADA. Compacto de
    # propósito (14/07): cabe numa página sem scroll lateral — layout fixo,
    # nome abreviado (tooltip tem o completo), células mínimas.
    from .. import team_config as TC
    por_colab = {n: cel for n, cel in (dados.get("por_colab") or {}).items()
                 if n == "(sem SDR)" or not TC.eh_desligado(conn, "prevendas", n)}
    # grade fixa 7h-20h (horário comercial); o que cai fora vira a coluna
    # "outros" — madrugadas raras não podem esticar a tabela
    horas_c = [h for h in range(7, 21)]
    tem_fora = any(h < 7 or h > 20 for cel in por_colab.values() for h in cel)
    _tdc = "padding:3px 2px;border-bottom:1px solid var(--border);text-align:center;font-variant-numeric:tabular-nums;font-size:var(--fs-2xs)"
    crows = ""
    for nome in sorted(por_colab, key=lambda x: (x == "(sem SDR)", -sum(por_colab[x].values()))):
        cel = por_colab[nome]
        tot_c = sum(cel.values())
        vmax_c = max(cel.values())
        pico_h = max(cel.items(), key=lambda x: x[1])[0]
        partes = nome.split()
        curto = nome if len(partes) < 2 else f"{partes[0]} {partes[1][0]}."
        tds = ""
        for h in horas_c:
            n = cel.get(h, 0)
            alpha = int(8 + 62 * (n / vmax_c)) if n else 0
            bg = f"background:color-mix(in srgb,var(--brand) {alpha}%,transparent);" if n else ""
            pico = "box-shadow:inset 0 0 0 1.5px var(--brand);border-radius:3px;" if n and h == pico_h else ""
            tds += (f"<td title='{escape(nome)} {h:02d}h — {n} agendamento(s) ({n / tot_c * 100:.0f}% do total dela)' "
                    f"style='{_tdc};{bg}{pico}'>{n or ''}</td>")
        if tem_fora:
            fora = sum(n for h, n in cel.items() if h < 7 or h > 20)
            tds += (f"<td title='{escape(nome)} — {fora} agendamento(s) antes das 7h ou depois das 20h' "
                    f"style='{_tdc};color:var(--text-muted)'>{fora or ''}</td>")
        aviso = "*" if tot_c < 30 else ""
        crows += (f"<tr><td title='{escape(nome)}' style='{_tdc};text-align:left;white-space:nowrap;"
                  f"overflow:hidden;text-overflow:ellipsis'><b>{escape(curto)}</b>{aviso}</td>"
                  f"<td style='{_tdc};text-align:right'>{tot_c}</td>{tds}</tr>")
    _thc = ("<th style='padding:3px 2px;border-bottom:1px solid var(--border-strong);color:var(--text-muted);"
            "font-size:var(--fs-2xs);text-align:{al};font-weight:600'>{h}</th>")
    ths_c = (_thc.format(al="left", h="Colaborador") + _thc.format(al="right", h="Tot.")
             + "".join(_thc.format(al="center", h=str(h)) for h in horas_c)
             + (_thc.format(al="center", h="outros") if tem_fora else ""))
    n_cols = len(horas_c) + (1 if tem_fora else 0)
    heat_colab = (f"<table style='width:100%;border-collapse:collapse;table-layout:fixed'>"
                  f"<colgroup><col style='width:104px'><col style='width:38px'>"
                  + f"<col span={n_cols}></colgroup>"
                  f"<tr>{ths_c}</tr>{crows}</table>")

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
            f"<button type=submit>Aplicar</button>"
            # botão no MESMO form: leva sempre os filtros que estão na tela
            # (antes era link estático — datas editadas sem 'Aplicar' saíam erradas)
            f"<button type=submit formaction='/prevendas/horarios/relatorio' formtarget='_blank' "
            "style='margin-left:6px;background:var(--brand);color:#111;font-weight:600'>"
            "Gerar relatório (validação)</button>"
            "</div></form>")
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
            "<section><h2>Agendamentos por colaborador × hora</h2>"
            "<p class=secsub>atribuição pelo campo SDR do deal · cada linha sombreada na PRÓPRIA escala — o horário forte de cada pessoa, independente do volume · célula contornada = pico da pessoa · * = amostra pequena (&lt;30)</p>"
            + _card(heat_colab) + "</section>"
            "<section><h2>Top 5 janelas</h2>" + _card(top_html + estilo) + "</section>"
            "<section><h2>Melhores janelas por bundle</h2>"
            "<p class=secsub>até 3 janelas com mais agendamentos por bundle no período — bundles com poucas "
            "amostras merecem cautela antes de mudar escala de time</p>"
            + _card(_tbl([("Bundle", "left"), ("Agendamentos", "right"), ("Melhores janelas", "left"), ("", "right")], brows)) + "</section>")


def _horarios_relatorio_html(dados: dict, ini: dt.date, fim: dt.date,
                             bundle: str, gerado_por: str) -> str:
    """Relatório imprimível (fundo claro, pronto p/ salvar em PDF e enviar à
    gestora de Pré-vendas) do estudo de dias/horários de agendamento."""
    celulas, por_bundle, total = dados["celulas"], dados["por_bundle"], dados["total"]
    per = f"{ini.strftime('%d-%m-%Y')} a {fim.strftime('%d-%m-%Y')}"
    filtro = "todos os bundles" if bundle == "todos" else f"apenas {bundle}"
    hoje = dt.date.today().strftime("%d-%m-%Y")
    if not total:
        corpo = "<p>Sem agendamentos no período/filtro selecionado.</p>"
        return _REL_TPL.format(corpo=corpo, per=per, filtro=filtro, hoje=hoje,
                               gerado_por=escape(gerado_por))

    # agregados p/ o resumo executivo
    por_dow: dict[int, int] = {}
    por_hora: dict[int, int] = {}
    for (d, h), n in celulas.items():
        por_dow[d] = por_dow.get(d, 0) + n
        por_hora[h] = por_hora.get(h, 0) + n
    melhor_dow = max(por_dow, key=por_dow.get)
    melhor_hora = max(por_hora, key=por_hora.get)
    top = sorted(celulas.items(), key=lambda x: -x[1])[:5]
    (td, th), tn = top[0]
    depois18 = sum(n for (d, h), n in celulas.items() if h >= 18)
    antes9 = sum(n for (d, h), n in celulas.items() if h < 9)
    almoco = sum(n for (d, h), n in celulas.items() if 12 <= h < 14)
    fds = sum(n for (d, h), n in celulas.items() if d in (0, 6))
    p18 = depois18 / total
    leitura_18 = (f"há volume relevante fora do expediente comercial ({p18 * 100:.0f}% dos agendamentos "
                  "após as 18h) — estender o horário em dias selecionados tende a compensar"
                  if p18 >= 0.08 else
                  f"o volume após as 18h é baixo ({p18 * 100:.0f}%) — os dados atuais não justificam "
                  "estender o expediente")
    resumo = (f"<ul>"
              f"<li><b>{total} agendamentos</b> de reunião no período analisado ({filtro}).</li>"
              f"<li>Melhor dia: <b>{_DOW_NOME[melhor_dow]}</b> ({por_dow[melhor_dow]} agendamentos; "
              f"{por_dow[melhor_dow] / total * 100:.0f}% do total). Melhor hora: <b>{melhor_hora:02d}h</b>.</li>"
              f"<li>Janela mais forte: <b>{_DOW_NOME[td]} às {th:02d}h</b> ({tn} agendamentos).</li>"
              f"<li>Fora do horário clássico: {antes9 / total * 100:.0f}% antes das 9h · "
              f"{almoco / total * 100:.0f}% no almoço (12h-14h) · <b>{p18 * 100:.0f}% após as 18h</b> · "
              f"{fds / total * 100:.0f}% em fim de semana.</li>"
              f"<li>Leitura sobre estender o expediente: {leitura_18}.</li></ul>")

    # heatmap (escala de azul, cor forçada na impressão)
    dows = [1, 2, 3, 4, 5] + ([6] if any(d == 6 for d, _ in celulas) else []) \
        + ([0] if any(d == 0 for d, _ in celulas) else [])
    horas_l = sorted({h for _, h in celulas})
    horas_l = list(range(min(horas_l), max(horas_l) + 1))
    vmax = max(celulas.values())
    head = "<tr><th></th>" + "".join(f"<th>{_DOW_NOME[d]}</th>" for d in dows) + "</tr>"
    linhas = ""
    for h in horas_l:
        tds = ""
        for d in dows:
            n = celulas.get((d, h), 0)
            alpha = 0.06 + 0.55 * (n / vmax) if n else 0
            bg = f" style='background:rgba(37,99,235,{alpha:.2f})'" if n else ""
            tds += f"<td{bg}>{n or ''}</td>"
        linhas += f"<tr><th>{h:02d}h</th>{tds}</tr>"
    heat = f"<table class=heat>{head}{linhas}</table>"

    top_rows = "".join(f"<tr><td>{i}º</td><td>{_DOW_NOME[d]} às {h:02d}h</td>"
                       f"<td class=num>{n}</td><td class=num>{n / total * 100:.1f}%</td></tr>"
                       for i, ((d, h), n) in enumerate(top, 1))
    top_tbl = ("<table class=plain><tr><th></th><th>Janela</th><th>Agendamentos</th><th>% do total</th></tr>"
               + top_rows + "</table>")

    brows = ""
    for p in ("B1", "B2", "B3", "B4", "B5", "sem produto"):
        cel = por_bundle.get(p)
        if not cel:
            continue
        tot_p = sum(cel.values())
        melhores = " · ".join(f"{_DOW_NOME[d]} {h:02d}h ({n})"
                              for (d, h), n in sorted(cel.items(), key=lambda x: -x[1])[:3] if n >= 2)
        obs = "amostra pequena — usar como indício, não como regra" if tot_p < 30 else ""
        brows += (f"<tr><td><b>{escape(p)}</b></td><td class=num>{tot_p}</td>"
                  f"<td>{escape(melhores) or '—'}</td><td class=obs>{obs}</td></tr>")
    bund_tbl = ("<table class=plain><tr><th>Bundle</th><th>Agend.</th><th>Melhores janelas</th><th></th></tr>"
                + brows + "</table>")

    corpo = ("<h2>Resumo executivo</h2>" + resumo
             + "<h2>Mapa de calor — dia da semana × hora (Brasília)</h2>" + heat
             + "<h2>Top 5 janelas</h2>" + top_tbl
             + "<h2>Melhores janelas por bundle</h2>"
             "<p class=nota>Independe do filtro de bundle — sempre calculado sobre o período.</p>" + bund_tbl)
    return _REL_TPL.format(corpo=corpo, per=per, filtro=filtro, hoje=hoje,
                           gerado_por=escape(gerado_por))


_REL_TPL = """<!doctype html><html lang=pt-BR><head><meta charset=utf-8>
<title>Melhor horário de agendamento — Pré-vendas</title>
<style>
 body{{font-family:'Segoe UI',system-ui,sans-serif;color:#1a1d23;background:#fff;margin:0}}
 .page{{max-width:820px;margin:0 auto;padding:36px 40px}}
 h1{{font-size:22px;margin:0 0 2px}} h2{{font-size:15px;margin:26px 0 8px;border-bottom:2px solid #2563eb;
    padding-bottom:4px;text-transform:uppercase;letter-spacing:.04em;color:#1e3a8a}}
 .meta{{color:#6b7280;font-size:12px;margin-bottom:4px}}
 ul{{margin:8px 0;padding-left:20px;font-size:13.5px;line-height:1.65}}
 table{{border-collapse:collapse;width:100%;font-size:12.5px;margin:8px 0}}
 .heat th,.heat td{{border:1px solid #e5e7eb;padding:4px 6px;text-align:center;min-width:34px;
    font-variant-numeric:tabular-nums}}
 .heat th{{background:#f3f4f6;font-weight:600}}
 .plain th,.plain td{{border-bottom:1px solid #e5e7eb;padding:6px 8px;text-align:left}}
 .plain th{{background:#f3f4f6;font-size:11px;text-transform:uppercase;letter-spacing:.03em}}
 .num{{text-align:right;font-variant-numeric:tabular-nums}}
 .obs{{color:#b45309;font-size:11.5px}}
 .nota{{color:#6b7280;font-size:11.5px;margin:2px 0 6px}}
 .rodape{{margin-top:28px;padding-top:10px;border-top:1px solid #e5e7eb;color:#6b7280;font-size:11px;line-height:1.6}}
 .toolbar{{position:sticky;top:0;background:#fff;padding:10px 0;display:flex;gap:8px}}
 .toolbar button,.toolbar a{{cursor:pointer;background:#2563eb;color:#fff;border:none;border-radius:6px;
    padding:8px 16px;font-size:13px;text-decoration:none;display:inline-block}}
 .toolbar a{{background:#6b7280}}
 *{{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
 @media print{{.toolbar{{display:none}} .page{{padding:0}}}}
</style></head><body><div class=page>
<div class=toolbar><button onclick='window.print()'>Imprimir / salvar PDF</button>
<a href='javascript:history.back()'>Voltar ao painel</a></div>
<h1>Melhor dia e horário de agendamento de reuniões</h1>
<div class=meta>Pré-vendas · Integracomm Central de Inteligência</div>
<div class=meta>Período: <b>{per}</b> · Bundle: <b>{filtro}</b> · Gerado em {hoje} por {gerado_por}</div>
{corpo}
<div class=rodape><b>Metodologia:</b> cada agendamento é o momento (horário de Brasília) em que o deal
entrou na etapa "Reunião Agendada" no Pipedrive — proxy da ligação/conversa que converteu; o carimbo é a
movimentação do card pelo SDR e pode atrasar alguns minutos em relação ao contato em si. Cada deal conta
UMA vez no período (primeira entrada na etapa) — mesma régua do Pipedrive; reagendamentos não duplicam.
Fonte: histórico de mudanças de etapa (Pipedrive /flow), coletado diariamente.
Documento para validação da coordenação de Pré-vendas — a decisão de escala de horário é sempre humana.</div>
</div></body></html>"""


@router.get("/prevendas/horarios/relatorio", response_class=HTMLResponse)
def pv_horarios_relatorio(request: Request):
    """Relatório imprimível do estudo Melhor Horário (respeita ?ini/fim/bundle)."""
    A = _deps()
    s, redir = A._require_area(request, "prevendas")
    if redir:
        return redir
    user, _role = s
    ini, fim, bundle = _horarios_periodo(request)
    with A._conn() as c:
        with c.cursor() as cur:
            cur.execute("INSERT INTO audit_log (actor, action, scope) VALUES (%s,'view',%s)",
                        (user, f"prevendas/horarios_relatorio {ini}..{fim} {bundle}"))
        dados = _horarios_calc(c, ini, fim, bundle)
    return HTMLResponse(_horarios_relatorio_html(dados, ini, fim, bundle, user))


# ---------------------------------------------------------------------------
# VENDAS
# ---------------------------------------------------------------------------
def _vd_funil(conn, request: Request) -> str:
    ini, fim, form = _periodo(request)
    a, b = _brt(ini, fim)
    reunioes = _entradas(conn, _ST_REUNIAO, a, b, coorte=False)
    with conn.cursor() as cur:
        # oportunidade = campo Dia Oportunidade (régua oficial, igual em todas
        # as áreas desde 14/07); receita = VALOR custom c/ fallback no value
        cur.execute("""SELECT count(*) FROM mkt_deals_attribution
                        WHERE oport_time >= %s AND oport_time < %s""", (a, b))
        negoc = cur.fetchone()[0]
        cur.execute("""SELECT count(*), COALESCE(sum(COALESCE(valor_custom, valor)), 0)
                         FROM mkt_deals_attribution
                        WHERE status='won' AND won_time >= %s AND won_time < %s""", (a, b))
        book, receita = cur.fetchone()
        # tendência mensal Oport→Booking (6 meses)
        cur.execute("""
            WITH oport AS (SELECT date_trunc('month', oport_time - interval '3 hours') m, count(*) n
                             FROM mkt_deals_attribution WHERE oport_time IS NOT NULL GROUP BY 1),
                 wins AS (SELECT date_trunc('month', won_time - interval '3 hours') m, count(*) n
                            FROM mkt_deals_attribution WHERE status='won' GROUP BY 1)
            SELECT to_char(o.m, 'MM-YYYY'), o.n, COALESCE(w.n, 0)
              FROM oport o LEFT JOIN wins w ON w.m = o.m
             WHERE o.m >= date_trunc('month', now()) - interval '5 months'
             ORDER BY o.m""")
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

    # OPORTUNIDADES POR BUNDLE (movida de Pré-vendas 13/07: oportunidade e
    # fechamento são território de Vendas): Dia Oportunidade no período ×
    # contratos FECHADOS no período; bookings validados com a gestão (jul: B1 6,
    # B2 4, B3 2, B4 1, Assessoria Smart 1). Produto nasce na Negociação.
    with conn.cursor() as cur:
        cur.execute("""
            WITH op AS (
                SELECT COALESCE(substring(d.produto FROM 'B[1-5]'),
                                left(COALESCE(d.produto, '(sem plano)'), 30)) AS bnd,
                       count(*) AS n
                  FROM mkt_deals_attribution d
                 WHERE d.oport_time >= %s AND d.oport_time < %s
                 GROUP BY 1),
                 wn AS (
                SELECT COALESCE(substring(produto FROM 'B[1-5]'),
                                left(COALESCE(produto, '(sem plano)'), 30)) AS bnd, count(*) AS n
                  FROM mkt_deals_attribution
                 WHERE status = 'won' AND won_time >= %s AND won_time < %s GROUP BY 1)
            SELECT COALESCE(op.bnd, wn.bnd), COALESCE(op.n, 0), COALESCE(wn.n, 0)
              FROM op FULL JOIN wn ON wn.bnd = op.bnd
             ORDER BY 2 DESC, 3 DESC""", (a, b, a, b))
        bdados = cur.fetchall()
    tot_op = sum(o for _b, o, _w in bdados) or 1
    brows = ""
    for bn, o, w in bdados:
        brows += (f"<tr><td style='{_TD}'><b>{escape(bn)}</b></td>"
                  f"<td style='{_TD};text-align:right'>{o}</td>"
                  f"<td style='{_TD};text-align:right'>{_fmt(o / tot_op, 'pct')}</td>"
                  f"<td style='{_TD};text-align:right'>{w}</td>"
                  f"<td style='{_TD};text-align:right'>{_fmt(w / o if o else None, 'pct')}</td></tr>")

    # conversões por ORIGEM × PLANO (pedido 13/07): quais origens fecham quais bundles
    with conn.cursor() as cur:
        cur.execute("""
            WITH wins AS (
                SELECT COALESCE(origem, '(vazio)') o,
                       COALESCE(substring(produto FROM 'B[1-5]'), 'outros') p, count(*) n
                  FROM mkt_deals_attribution
                 WHERE status='won' AND won_time >= %s AND won_time < %s GROUP BY 1, 2),
                 leads AS (
                SELECT COALESCE(origem, '(vazio)') o, count(*) n FROM mkt_deals_attribution
                 WHERE add_time >= %s AND add_time < %s GROUP BY 1)
            SELECT w.o, w.p, w.n, COALESCE(l.n, 0)
              FROM wins w LEFT JOIN leads l ON l.o = w.o""", (a, b, a, b))
        mx: dict[str, dict[str, int]] = {}
        leads_por_origem: dict[str, int] = {}
        for o, p_, n, l in cur.fetchall():
            mx.setdefault(o, {})[p_] = n
            leads_por_origem[o] = l
    planos_cols = ["B1", "B2", "B3", "B4", "B5", "outros"]
    oxrows = ""
    for o in sorted(mx, key=lambda x: -sum(mx[x].values()))[:12]:
        tot_o = sum(mx[o].values())
        l_o = leads_por_origem.get(o, 0)
        tds = "".join(f"<td style='{_TD};text-align:right'>{mx[o].get(p_, '') or ''}</td>" for p_ in planos_cols)
        oxrows += (f"<tr><td style='{_TD}'>{escape(o[:30])}</td>{tds}"
                   f"<td style='{_TD};text-align:right'><b>{tot_o}</b></td>"
                   f"<td style='{_TD};text-align:right'>{_fmt(tot_o / l_o if l_o else None, 'pct')}</td></tr>")

    # funil COMPLETO Lead→Booking (pedido do Otávio 14/07): a mesma régua
    # oficial das abas de Marketing e Pré-vendas, agora também em Vendas
    from ..marketing.ui import _funil_oficial, funil_visual_html
    passou, book_of, leads_of, receita_of = _funil_oficial(conn, ini, fim)
    funil_completo = funil_visual_html(
        [("Lead", passou[0]), ("MQL", passou[1]), ("SAL", passou[2]),
         ("SQL", passou[3]), ("Oportunidade", passou[4]), ("Booking", book_of)],
        leads_of, receita_of)

    return (f"<h1>Funil de Fechamento</h1><div class=sub>da reunião agendada ao contrato · régua por evento no período (BRT) · funil completo = régua OFICIAL do dashboard do time</div>"
            f"<form method=get action=/vendas><input type=hidden name=view value=funil>{form}</form>"
            + kpis +
            f"<section><h2>Funil completo (Lead → Booking)</h2><p class=secsub>régua oficial do dashboard do time — os mesmos números das abas Funil de Marketing e Pré-vendas · Oportunidade não é coorte, pode superar SQL</p>{funil_completo}</section>"
            f"<section><h2>Oportunidades por bundle</h2><p class=secsub>oportunidades novas e contratos fechados no período, por plano — planos antigos/exceções aparecem pelo nome</p>"
            + _card(_tbl([("Bundle", "left"), ("Oportunidades", "right"), ("% do mix", "right"),
                          ("Bookings", "right"), ("Oport→Booking", "right")], brows)) + "</section>"
            f"<section><h2>Conversões por origem × plano</h2><p class=secsub>bookings do período por origem do lead e bundle fechado · TX = bookings ÷ leads da origem criados no período — mostra qual canal fecha qual plano</p>"
            + _card(_tbl([("Origem", "left")] + [(p_, "right") for p_ in planos_cols]
                         + [("Total", "right"), ("TX lead→booking", "right")], oxrows)) + "</section>"
            f"<section><h2>Tendência Oportunidade → Booking</h2><p class=secsub>6 meses · o ponto de underperformance apontado no Q3</p>"
            + _card(_tbl([("Mês", "left"), ("Oportunidades", "right"), ("Bookings", "right"), ("Conversão", "right")], trows)) + "</section>"
            f"<section><h2>Diagnóstico do especialista</h2><p class=secsub>{ESP.PERSONA_VENDAS}</p>"
            + _card(ins_html + "<style>.sug-item{padding:7px 0;border-top:1px solid var(--border);font-size:var(--fs-sm);line-height:1.55;color:var(--text-2)}.sug-item:first-child{border-top:none}</style>") + "</section>")


def _vd_winloss(conn, request: Request) -> str:
    ini, fim, form = _periodo(request)
    a, b = _brt(ini, fim)
    with conn.cursor() as cur:
        cur.execute("""SELECT COALESCE(lost_reason, '(sem motivo)'), count(*),
                              COALESCE(sum(COALESCE(valor_custom, valor)), 0)
                         FROM mkt_deals_attribution
                        WHERE status='lost' AND lost_time >= %s AND lost_time < %s
                          AND stage_id IN (6, 5, 7)
                        GROUP BY 1 ORDER BY 2 DESC LIMIT 14""", (a, b))
        perdas = cur.fetchall()
        # perdas por BUNDLE × motivo (reformulado 14/07 — pedido do Otávio: a
        # tabela achatada motivo×plano era pouco intuitiva; agora é um card
        # por bundle com os principais motivos DELE)
        cur.execute("""SELECT COALESCE(substring(produto FROM 'B[1-5]'),
                              CASE WHEN produto IS NULL OR produto = '' THEN '(sem plano)' ELSE 'outros' END),
                              COALESCE(lost_reason, '(sem motivo)'), count(*),
                              COALESCE(sum(COALESCE(valor_custom, valor)), 0)
                         FROM mkt_deals_attribution
                        WHERE status='lost' AND lost_time >= %s AND lost_time < %s
                          AND stage_id IN (6, 5, 7)
                        GROUP BY 1, 2""", (a, b))
        por_bundle: dict[str, list[tuple[str, int, float]]] = {}
        for bnd, m, n, v in cur.fetchall():
            por_bundle.setdefault(bnd, []).append((m, n, float(v)))
    tem_motivo = any(m != "(sem motivo)" for m, _, _ in perdas)
    rows = "".join(f"<tr><td style='{_TD}'>{escape(str(m)[:56])}</td><td style='{_TD};text-align:right'>{n}</td>"
                   f"<td style='{_TD};text-align:right'>{_fmt(float(v), 'brl')}</td></tr>" for m, n, v in perdas)

    # um card por bundle: total de perdas + top 5 motivos c/ barra de participação
    bcards = ""
    ordem = ["B1", "B2", "B3", "B4", "B5", "outros", "(sem plano)"]
    for bnd in [x for x in ordem if x in por_bundle] + sorted(set(por_bundle) - set(ordem)):
        motivos = por_bundle[bnd]
        tot_n = sum(n for _m, n, _v in motivos)
        tot_v = sum(v for _m, _n, v in motivos)
        linhas_m = ""
        for m, n, _v in sorted(motivos, key=lambda x: -x[1])[:5]:
            pct = n / tot_n if tot_n else 0
            cor_txt = "var(--text-faint)" if m == "(sem motivo)" else "var(--text-2)"
            linhas_m += (
                f"<div style='margin-top:8px'>"
                f"<div style='display:flex;justify-content:space-between;gap:10px;font-size:var(--fs-xs);color:{cor_txt}'>"
                f"<span>{escape(str(m)[:42])}</span><span style='white-space:nowrap;font-variant-numeric:tabular-nums'><b>{n}</b> · {_fmt(pct, 'pct')}</span></div>"
                f"<div style='height:5px;background:var(--surface-3);border-radius:3px;overflow:hidden;margin-top:3px'>"
                f"<div style='height:100%;width:{pct * 100:.0f}%;background:var(--status-alto);border-radius:3px'></div></div></div>")
        sobra = len(motivos) - 5
        if sobra > 0:
            linhas_m += f"<div class=note style='margin-top:7px'>+ {sobra} outro(s) motivo(s)</div>"
        bcards += (f"<div class=card><div style='display:flex;justify-content:space-between;align-items:baseline'>"
                   f"<b style='font-size:var(--fs-md)'>{escape(bnd)}</b>"
                   f"<span style='color:var(--text-muted);font-size:var(--fs-xs)'>{tot_n} perda(s) · {_fmt(tot_v, 'brl')}</span></div>"
                   + linhas_m + "</div>")
    grade_b = (f"<div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:14px;align-items:start'>{bcards}</div>"
               if bcards else _card("<span class=note>sem perdas no período</span>"))

    return (f"<h1>Win/Loss — Análise de Perdas</h1><div class=sub>perdas na fase de Vendas (da reunião em diante), por motivo e valor</div>"
            f"<form method=get action=/vendas><input type=hidden name=view value=winloss>{form}</form>"
            f"<section><h2>Motivos de perda</h2>"
            + _card((_tbl([("Motivo", "left"), ("Deals", "right"), ("MRR perdido", "right")], rows) if rows else "<span class=note>sem perdas no período</span>")
                    + ("" if tem_motivo else _aviso_coleta("motivo de perda"))) + "</section>"
            f"<section><h2>Principais motivos de perda por bundle</h2><p class=secsub>um card por plano: os motivos que mais matam AQUELE bundle, com participação nas perdas dele — concentrado num bundle = preço/produto; espalhado por todos = abordagem</p>"
            + grade_b + "</section>")


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
            SELECT d.deal_id, d.stage_id, COALESCE(d.valor_custom, d.valor) AS valor,
                   d.produto, d.owner_name,
                   EXTRACT(epoch FROM now() - max(e.entered_at)) / 86400 AS dias
              FROM mkt_deals_attribution d JOIN mkt_stage_events e ON e.deal_id = d.deal_id
             WHERE d.status='open' AND d.stage_id IN (6, 5, 7)
             GROUP BY d.deal_id, d.stage_id, COALESCE(d.valor_custom, d.valor), d.produto, d.owner_name""")
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
        # ticket em MRR: B1 é contrato SEMESTRAL pago à vista (regra do Otávio,
        # reafirmada 14/07) — dividir por 6 p/ comparar com os mensais; sem
        # isso quem fecha muito B1 aparecia como "ticket alto" indevidamente
        cur.execute("""
            SELECT d.owner_name,
                   count(*) FILTER (WHERE d.oport_time >= %s AND d.oport_time < %s) AS oports,
                   count(*) FILTER (WHERE d.status='won' AND d.won_time >= %s AND d.won_time < %s) AS wins,
                   avg(CASE WHEN substring(d.produto FROM 'B[1-5]') = 'B1'
                            THEN COALESCE(d.valor_custom, d.valor) / 6.0
                            ELSE COALESCE(d.valor_custom, d.valor) END)
                       FILTER (WHERE d.status='won' AND d.won_time >= %s AND d.won_time < %s) AS ticket
              FROM mkt_deals_attribution d
             WHERE d.owner_name IS NOT NULL
             GROUP BY 1""", (a, b, a, b, a, b))
        dados = cur.fetchall()
        # ciclo mediano por closer (1ª reunião → won, ganhos do período) — era
        # sempre vazio e as regras de ciclo dos planos nunca disparavam (14/07)
        cur.execute("""
            SELECT d.owner_name,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY EXTRACT(epoch FROM d.won_time - m.primeiro) / 86400)
              FROM mkt_deals_attribution d
              JOIN (SELECT deal_id, min(entered_at) AS primeiro FROM mkt_stage_events
                     WHERE stage_id IN (6, 5, 7) GROUP BY 1) m ON m.deal_id = d.deal_id
             WHERE d.status='won' AND d.won_time >= %s AND d.won_time < %s
               AND d.won_time > m.primeiro
             GROUP BY 1""", (a, b))
        ciclo_por = {n: float(v) for n, v in cur.fetchall() if v is not None}
    from .. import team_config as TC
    time_stats = []
    for nome, oports, wins, ticket in dados:
        papel = TC.papel_de(conn, "vendas", nome)
        # fora da lista OU desligado (detecção automática no Pipedrive) não
        # aparece — os números seguem intactos nas réguas do funil
        if papel is None or TC.eh_desligado(conn, "vendas", nome):
            continue
        time_stats.append({"nome": nome, "oports": oports or 0, "bookings": wins or 0,
                           "taxa_conv": (wins / oports if oports else None),
                           "ticket": float(ticket) if ticket else None,
                           "ciclo_dias": ciclo_por.get(nome), "perdas_top": None, "papel": papel})
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
    membros = [p for p in time_stats if p["papel"] == "membro"]
    _CHIP_PAPEL = {"coordenacao": ("coordenação", "var(--brand)"), "gerencia": ("gerência", "var(--brand)")}
    for p in sorted(time_stats, key=lambda x: (x["papel"] != "membro", -(x["taxa_conv"] or 0))):
        if p["papel"] in _CHIP_PAPEL:
            lbl, cor = _CHIP_PAPEL[p["papel"]]
            tag = f" <span class=chip style='--c:{cor}'>{lbl}</span>"
        else:
            tag = ""
        rows += (f"<tr><td style='{_TD}'><b>{escape(p['nome'][:26])}</b>{tag}</td>"
                 f"<td style='{_TD};text-align:right'>{p['oports']}</td>"
                 f"<td style='{_TD};text-align:right'>{p['bookings']}</td>"
                 f"<td style='{_TD};text-align:right'>{_fmt(p['taxa_conv'], 'pct')}</td>"
                 f"<td style='{_TD};text-align:right'>{_fmt(p['ticket'], 'brl')}</td>"
                 f"<td style='{_TD};text-align:right'>{_fmt(p['ciclo_dias'], 'dias')}</td>"
                 f"<td style='{_TD}'>{escape((p['perdas_top'] or '—')[:30])}</td></tr>")
        # plano/mediana: SÓ colaboradores do time (coordenação/gerência ficam fora)
        if p["papel"] == "membro":
            pl = ESP.plano_closer(p, membros)
            itens = ("".join(f"<li style='color:var(--status-baixo)'>{escape(f)}</li>" for f in pl["fortes"])
                     + "".join(f"<li style='color:var(--status-alto)'>{escape(f)}</li>" for f in pl["fracos"])
                     + "".join(f"<li>→ {escape(acao)}</li>" for acao in pl["acoes"]))
            planos += (f"<div style='margin-top:12px'><b>{escape(p['nome'])}</b>"
                       f"<ul class=note style='margin:4px 0 0;padding-left:18px'>{itens}</ul></div>")
    # ---- estudos por closer (pedidos 14/07, espelho dos de PV) -------------
    cols = [p["nome"] for p in sorted(time_stats, key=lambda x: (x["papel"] != "membro",
                                                                 -(x["bookings"] or 0)))][:6]
    _nc = "padding:6px 7px;border-bottom:1px solid var(--border);font-variant-numeric:tabular-nums;font-size:var(--fs-xs)"

    def _abrev(n: str) -> str:
        ps = n.split()
        return n if len(ps) < 2 else f"{ps[0]} {ps[1][0]}."

    # (a) FECHAMENTOS por bundle × closer (won no período, por dono atual)
    with conn.cursor() as cur:
        cur.execute("""SELECT COALESCE(owner_name, '—'),
                              COALESCE(substring(produto FROM 'B[1-5]'),
                                       CASE WHEN produto IS NULL OR produto = '' THEN '(sem plano)' ELSE 'outros' END),
                              count(*)
                         FROM mkt_deals_attribution
                        WHERE status='won' AND won_time >= %s AND won_time < %s GROUP BY 1, 2""", (a, b))
        wb: dict[str, dict[str, int]] = {}
        for nome, bd, n in cur.fetchall():
            wb.setdefault(bd, {})[nome] = n

    def _casa_col(nome_pd: str, col: str) -> bool:
        return TC.norm(col) in TC.norm(nome_pd) or TC.norm(nome_pd) in TC.norm(col)
    ordem_b = [x for x in ("B1", "B2", "B3", "B4", "B5", "outros", "(sem plano)") if x in wb] \
        + sorted(set(wb) - {"B1", "B2", "B3", "B4", "B5", "outros", "(sem plano)"})
    brws = ""
    for bd in ordem_b:
        tds = ""
        for col in cols:
            n = sum(v for nm, v in wb[bd].items() if _casa_col(nm, col))
            tds += f"<td style='{_nc};text-align:center'>{n or '—'}</td>"
        brws += f"<tr><td style='{_nc}'><b>{escape(bd)}</b></td>{tds}</tr>"
    sec_bnd = ("<section><h2>Fechamentos por plano × closer</h2>"
               "<p class=secsub>contratos ganhos no período por bundle — quem fecha o quê; forte em B1 e zerado em B3-B5 = treinar oferta para cima (prioridade da empresa)</p>"
               + _card(_tbl([("Plano", "left")] + [(_abrev(c), "center") for c in cols], brws))
               + "</section>") if brws else ""

    # (b) REUNIÕES por closer × hora (1ª entrada em Negociação, proxy da
    # reunião realizada) — compacta como a de PV: linha na própria escala
    with conn.cursor() as cur:
        cur.execute("""
            WITH primeira AS (
                SELECT e.deal_id, min(e.entered_at) AS entered_at
                  FROM mkt_stage_events e
                 WHERE e.stage_id = 7 AND e.entered_at >= %s AND e.entered_at < %s
                 GROUP BY e.deal_id)
            SELECT COALESCE(d.owner_name, '—'),
                   extract(hour FROM p.entered_at AT TIME ZONE 'America/Sao_Paulo')::int, count(*)
              FROM primeira p JOIN mkt_deals_attribution d ON d.deal_id = p.deal_id
             GROUP BY 1, 2""", (a, b))
        rh: dict[str, dict[int, int]] = {}
        for nome, h, n in cur.fetchall():
            rh.setdefault(nome, {})[h] = n
    horas_c = list(range(7, 21))
    hrws = ""
    for col in cols:
        cel: dict[int, int] = {}
        for nm, hs in rh.items():
            if _casa_col(nm, col):
                for h, n in hs.items():
                    cel[h] = cel.get(h, 0) + n
        if not cel:
            continue
        tot_c, vmax_c = sum(cel.values()), max(cel.values())
        pico_h = max(cel.items(), key=lambda x: x[1])[0]
        tds = ""
        for h in horas_c:
            n = cel.get(h, 0)
            alpha = int(8 + 62 * (n / vmax_c)) if n else 0
            bg = f"background:color-mix(in srgb,var(--brand) {alpha}%,transparent);" if n else ""
            pico = "box-shadow:inset 0 0 0 1.5px var(--brand);border-radius:3px;" if n and h == pico_h else ""
            tds += (f"<td title='{escape(col)} {h:02d}h — {n} reunião(ões)' "
                    f"style='{_nc};text-align:center;{bg}{pico}'>{n or ''}</td>")
        fora = sum(n for h, n in cel.items() if h < 7 or h > 20)
        tds += f"<td style='{_nc};text-align:center;color:var(--text-muted)'>{fora or ''}</td>"
        aviso = "*" if tot_c < 30 else ""
        hrws += (f"<tr><td style='{_nc};white-space:nowrap'><b>{escape(_abrev(col))}</b>{aviso}</td>"
                 f"<td style='{_nc};text-align:right'>{tot_c}</td>{tds}</tr>")
    _thc = ("<th style='padding:3px 2px;border-bottom:1px solid var(--border-strong);color:var(--text-muted);"
            "font-size:var(--fs-2xs);text-align:{al};font-weight:600'>{h}</th>")
    ths_h = (_thc.format(al="left", h="Closer") + _thc.format(al="right", h="Tot.")
             + "".join(_thc.format(al="center", h=str(h)) for h in horas_c) + _thc.format(al="center", h="outros"))
    sec_hora = ("<section><h2>Reuniões por closer × hora</h2>"
                "<p class=secsub>1ª entrada do deal em Negociação (proxy da reunião realizada; o carimbo é a movimentação do card) · "
                "cada linha na PRÓPRIA escala · célula contornada = pico da pessoa · * = amostra pequena (&lt;30)</p>"
                + _card(f"<table style='width:100%;border-collapse:collapse;table-layout:fixed'>"
                        f"<colgroup><col style='width:96px'><col style='width:38px'>"
                        f"<col span={len(horas_c) + 1}></colgroup><tr>{ths_h}</tr>{hrws}</table>")
                + "</section>") if hrws else ""

    return (f"<h1>Desempenho Individual — Vendas</h1><div class=sub>coordenação: {ESP.COORD_VENDAS} · gerência: Marcos (Vendas + Pré-vendas) · dono do deal = atribuição · lista editável no Painel Administrativo</div>"
            f"<form method=get action=/vendas><input type=hidden name=view value=closers>{form}</form>"
            f"<section><h2>Performance por closer</h2>"
            + _card(_tbl([("Closer", "left"), ("Oports", "right"), ("Bookings", "right"), ("Conversão", "right"), ("Ticket (MRR)", "right"), ("Ciclo (med.)", "right"), ("Perda nº1", "left")], rows)) + "</section>"
            + sec_bnd + sec_hora +
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
                              count(*), COALESCE(sum(COALESCE(valor_custom, valor)), 0)
                         FROM mkt_deals_attribution
                        WHERE status='won' AND won_time >= %s AND won_time < %s GROUP BY 1""", (a, b))
        feito = {p_: (n, float(v)) for p_, n, v in cur.fetchall()}
        cur.execute("""SELECT COALESCE(substring(produto FROM 'B[1-5]'), 'outros'), count(*)
                         FROM mkt_deals_attribution WHERE status='open' AND stage_id IN (6, 5, 7)
                        GROUP BY 1""")
        pipe = dict(cur.fetchall())
        cur.execute("SELECT count(*) FROM mkt_deals_attribution WHERE oport_time >= %s", (a90,))
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


def _vd_ponte(conn, request: Request) -> str:
    """Ponte Pré-vendas → Vendas (pedido 14/07): a conversão Oport→Booking
    fraca é HERDADA de qualificação ruim ou é do FECHAMENTO? Cruza, por
    oportunidade do período, características da qualificação (SLA de 1º
    contato, tempo lead→oportunidade, origem, SDR) × desfecho em Vendas.
    Taxa sempre sobre DECIDIDAS (ganhas+perdidas) — em aberto fica fora."""
    ini, fim, form = _periodo(request)
    a, b = _brt(ini, fim)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT d.deal_id, d.status, COALESCE(d.origem, '(vazio)'),
                   COALESCE(d.sdr, '(sem SDR)'),
                   COALESCE(d.owner_name, '—'),
                   EXTRACT(epoch FROM (t.first_at - d.add_time)) / 60,
                   EXTRACT(epoch FROM (d.oport_time - d.add_time)) / 86400
              FROM mkt_deals_attribution d
              LEFT JOIN sales_first_touch t ON t.deal_id = d.deal_id
             WHERE d.oport_time >= %s AND d.oport_time < %s""", (a, b))
        rows = cur.fetchall()
    if not rows:
        return ("<h1>Ponte Pré-vendas → Vendas</h1>"
                "<section><div class=warn>sem oportunidades no período selecionado</div></section>")

    def agrega(chave):
        seg: dict[str, list[int]] = {}
        for r in rows:
            k = chave(r)
            if k is None:
                continue
            t = seg.setdefault(k, [0, 0, 0])  # decididas_ganhas, decididas, total
            if r[1] == "won":
                t[0] += 1; t[1] += 1
            elif r[1] == "lost":
                t[1] += 1
            t[2] += 1
        return seg

    def tabela(seg, rotulo, ordem=None):
        chaves = ordem or sorted(seg, key=lambda k: -seg[k][2])
        linhas = ""
        for k in chaves:
            if k not in seg:
                continue
            g, dec, tot = seg[k]
            tx = g / dec if dec else None
            fraca = dec < 10
            linhas += (f"<tr><td style='{_TD}'><b>{escape(str(k)[:30])}</b></td>"
                       f"<td style='{_TD};text-align:right'>{tot}</td>"
                       f"<td style='{_TD};text-align:right'>{g}</td>"
                       f"<td style='{_TD};text-align:right'>{dec - g}</td>"
                       f"<td style='{_TD};text-align:right'>{tot - dec}</td>"
                       f"<td style='{_TD};text-align:right'><b>{_fmt(tx, 'pct')}</b></td>"
                       f"<td style='{_TD};text-align:right'>{'<span class=note>amostra pequena</span>' if fraca else ''}</td></tr>")
        return (f"<div class=card>{_tbl([(rotulo, 'left'), ('Oports', 'right'), ('Fechadas', 'right'), ('Perdidas', 'right'), ('Em aberto', 'right'), ('Taxa', 'right'), ('', 'right')], linhas)}</div>")

    sla = agrega(lambda r: None if r[5] is None else ("dentro do SLA (≤15 min)" if r[5] <= 15
                                                      else ("15-60 min" if r[5] <= 60 else "acima de 1h")))
    tempo = agrega(lambda r: None if r[6] is None else ("qualificou em ≤2 dias" if r[6] <= 2
                                                        else ("3-7 dias" if r[6] <= 7 else "mais de 7 dias")))
    origem = agrega(lambda r: r[2][:26])
    sdr = agrega(lambda r: r[3][:26])
    closer = agrega(lambda r: r[4][:26])
    origem = {k: v for k, v in sorted(origem.items(), key=lambda x: -x[1][2])[:8]}

    # leitura automática do gargalo: dispersão das taxas nos segmentos de
    # QUALIFICAÇÃO (SLA/tempo/origem/SDR, decididas>=10) vs entre closers
    def taxas(seg):
        return [g / dec for g, dec, _t in seg.values() if dec >= 10]
    qual_txs = taxas(sla) + taxas(tempo) + taxas(origem) + taxas(sdr)
    clos_txs = taxas(closer)
    amp_q = (max(qual_txs) - min(qual_txs)) if len(qual_txs) >= 2 else None
    amp_c = (max(clos_txs) - min(clos_txs)) if len(clos_txs) >= 2 else None
    if amp_q is None and amp_c is None:
        leitura = "Amostra ainda pequena para diagnóstico — acumule mais um período."
    elif (amp_q or 0) >= 0.15 and (amp_q or 0) >= (amp_c or 0):
        leitura = (f"O gargalo tem cara de HERANÇA DA QUALIFICAÇÃO: a taxa de fechamento varia "
                   f"{amp_q * 100:.0f} p.p. conforme a qualidade da qualificação recebida (SLA/tempo/origem/SDR), "
                   f"mais do que entre closers ({(amp_c or 0) * 100:.0f} p.p.). Caminho: devolver critérios de "
                   "qualificação à Pré-vendas — priorizar os segmentos que fecham e endurecer o filtro nos que não fecham.")
    elif (amp_c or 0) >= 0.15:
        leitura = (f"O gargalo tem cara de FECHAMENTO: a taxa varia pouco com a qualificação recebida "
                   f"({(amp_q or 0) * 100:.0f} p.p.), mas {amp_c * 100:.0f} p.p. entre closers. Caminho: abordagem/"
                   "ancoragem em Vendas — role-play com quem está acima e revisão de proposta.")
    else:
        leitura = (f"Taxas relativamente UNIFORMES ({(amp_q or 0) * 100:.0f} p.p. por qualificação, "
                   f"{(amp_c or 0) * 100:.0f} p.p. por closer) — o gargalo não está na triagem nem em pessoas "
                   "específicas; olhe preço/proposta (Win/Loss) e volume de topo.")
    tot_g = sum(1 for r in rows if r[1] == "won")
    tot_d = sum(1 for r in rows if r[1] in ("won", "lost"))
    kpis = ("<div class=kpis>"
            f"<div class=kpi><div class=n>{len(rows)}</div><div class=l>oportunidades no período</div></div>"
            f"<div class=kpi><div class=n>{_fmt(tot_g / tot_d if tot_d else None, 'pct')}</div><div class=l>taxa de fechamento</div><div class=s>{tot_g} ÷ {tot_d} decididas</div></div>"
            f"<div class=kpi><div class=n>{len(rows) - tot_d}</div><div class=l>ainda em aberto</div></div></div>")
    return ("<h1>Ponte Pré-vendas → Vendas</h1>"
            "<div class=sub>a pergunta estratégica: a conversão fraca é herdada da qualificação ou é do fechamento? · "
            "oportunidades do período (Dia Oportunidade) × desfecho · taxa sobre decididas</div>"
            f"<form method=get action=/vendas><input type=hidden name=view value=ponte>{form}</form>"
            + kpis +
            "<section><h2>Leitura do especialista</h2>"
            f"<div class=card><div class=sug-item>→ {escape(leitura)}</div>"
            "<style>.sug-item{padding:7px 0;font-size:var(--fs-sm);line-height:1.6;color:var(--text-2)}</style></div></section>"
            "<section><h2>Por SLA do 1º contato</h2><p class=secsub>a tese do speed-to-lead, agora medida no CAIXA: oportunidade que nasceu de lead atendido rápido fecha mais?</p>"
            + tabela(sla, "1º contato", ["dentro do SLA (≤15 min)", "15-60 min", "acima de 1h"]) + "</section>"
            "<section><h2>Por tempo de qualificação</h2><p class=secsub>dias entre o lead entrar e virar oportunidade</p>"
            + tabela(tempo, "Lead → oportunidade", ["qualificou em ≤2 dias", "3-7 dias", "mais de 7 dias"]) + "</section>"
            "<section><h2>Por origem do lead</h2>" + tabela(origem, "Origem") + "</section>"
            "<section><h2>Por SDR que qualificou</h2><p class=secsub>separa 'quem qualifica mal'…</p>" + tabela(sdr, "SDR") + "</section>"
            "<section><h2>Por closer</h2><p class=secsub>…de 'quem fecha mal'</p>" + tabela(closer, "Closer") + "</section>")


def _vd_horarios(conn, request: Request) -> str:
    """Melhor Horário de VENDAS (pedido 14/07): existe hora melhor p/ a
    REUNIÃO acontecer? Base: 1ª entrada do deal em Negociação (7) — o card é
    movido após a reunião, então o carimbo é o proxy da reunião realizada.
    TAXA = ganhas ÷ DECIDIDAS (won+lost) da própria coorte: deals ainda
    abertos não derrubam a taxa (14/07 — o 9,1% sobre o total confundia com
    os 15,2% do funil, que mistura coortes: bookings do mês ÷ oportunidades
    do mês, incluindo reuniões de meses anteriores)."""
    ini, fim, bundle = _horarios_periodo(request)
    a, b = _brt(ini, fim)
    filtro_b, args = "", [a, b]
    if bundle in ("B1", "B2", "B3", "B4", "B5"):
        filtro_b = " AND substring(d.produto FROM 'B[1-5]') = %s"
        args.append(bundle)
    with conn.cursor() as cur:
        cur.execute(f"""
            WITH primeira AS (
                SELECT e.deal_id, min(e.entered_at) AS entered_at
                  FROM mkt_stage_events e
                  JOIN mkt_deals_attribution d ON d.deal_id = e.deal_id
                 WHERE e.stage_id = 7 AND e.entered_at >= %s AND e.entered_at < %s{filtro_b}
                 GROUP BY e.deal_id)
            SELECT extract(dow  FROM p.entered_at AT TIME ZONE 'America/Sao_Paulo')::int,
                   extract(hour FROM p.entered_at AT TIME ZONE 'America/Sao_Paulo')::int,
                   count(*), count(*) FILTER (WHERE d.status = 'won'),
                   count(*) FILTER (WHERE d.status = 'lost')
              FROM primeira p JOIN mkt_deals_attribution d ON d.deal_id = p.deal_id
             GROUP BY 1, 2""", args)
        celulas = {(dow, h): (n, w, lo) for dow, h, n, w, lo in cur.fetchall()}
    total = sum(n for n, _w, _lo in celulas.values())
    if not total:
        return ("<h1>Melhor Horário — reuniões de Vendas</h1><div class=sub>quando as reuniões acontecem e quanto convertem</div>"
                "<section><div class=warn>sem reuniões no período/filtro selecionado</div></section>")
    total_w = sum(w for _n, w, _lo in celulas.values())
    total_lo = sum(lo for _n, _w, lo in celulas.values())
    abertas = total - total_w - total_lo

    # --- heatmap dia × hora (reuniões; tooltip traz a conversão da célula) ---
    dows = [1, 2, 3, 4, 5] + ([6] if any(d == 6 for d, _ in celulas) else []) \
        + ([0] if any(d == 0 for d, _ in celulas) else [])
    horas = sorted({h for _, h in celulas})
    horas = list(range(min(horas), max(horas) + 1))
    vmax = max(n for n, _w, _lo in celulas.values())
    linhas = ""
    for h in horas:
        tds = ""
        for d in dows:
            n, w, lo = celulas.get((d, h), (0, 0, 0))
            alpha = int(8 + 62 * (n / vmax)) if n else 0
            bg = f"background:color-mix(in srgb,var(--brand) {alpha}%,transparent);" if n else ""
            dec = w + lo
            tds += (f"<td title='{_DOW_NOME[d]} {h:02d}h — {n} reunião(ões): {w} fechada(s), {lo} perdida(s), {n - dec} em aberto"
                    f"{f' · taxa {w / dec * 100:.0f}% das decididas' if dec else ''}' "
                    if n else "<td ") + f"style='{_TD};text-align:center;{bg}'>{n or ''}</td>"
        linhas += f"<tr><td style='{_TD};color:var(--text-muted)'>{h:02d}h</td>{tds}</tr>"
    heat = _tbl([("", "left")] + [(_DOW_NOME[d], "left") for d in dows], linhas)

    # --- por HORA: a pergunta central — taxa = fechadas ÷ DECIDIDAS ---------
    por_hora: dict[int, list[int]] = {}
    for (_d, h), (n, w, lo) in celulas.items():
        t = por_hora.setdefault(h, [0, 0, 0])
        t[0] += n; t[1] += w; t[2] += lo
    hrows, melhores = "", []
    for h in sorted(por_hora):
        n, w, lo = por_hora[h]
        dec = w + lo
        tx = w / dec if dec else None
        if dec >= 15:
            melhores.append((tx or 0, h, dec))
        hrows += (f"<tr><td style='{_TD}'><b>{h:02d}h</b></td>"
                  f"<td style='{_TD};text-align:right'>{n}</td>"
                  f"<td style='{_TD};text-align:right'>{w}</td>"
                  f"<td style='{_TD};text-align:right'>{lo}</td>"
                  f"<td style='{_TD};text-align:right;color:var(--text-muted)'>{n - dec}</td>"
                  f"<td style='{_TD};text-align:right'><b>{_fmt(tx, 'pct')}</b></td>"
                  f"<td style='{_TD};text-align:right'>{'<span class=note>amostra pequena</span>' if dec < 15 else ''}</td></tr>")
    melhores.sort(key=lambda x: -x[0])
    melhor_txt = (f"{melhores[0][1]:02d}h ({_fmt(melhores[0][0], 'pct')} em {melhores[0][2]} decididas)"
                  if melhores else "—")
    decididas = total_w + total_lo
    kpis = ("<div class=kpis>"
            f"<div class=kpi><div class=n>{total}</div><div class=l>reuniões no período</div><div class=s>1ª entrada em Negociação</div></div>"
            f"<div class=kpi><div class=n>{_fmt(total_w / decididas if decididas else None, 'pct')}</div><div class=l>taxa de fechamento</div>"
            f"<div class=s>{total_w} ganhas ÷ {decididas} decididas</div></div>"
            f"<div class=kpi><div class=n>{abertas}</div><div class=l>ainda em aberto</div><div class=s>fora da taxa — a coorte segue amadurecendo</div></div>"
            f"<div class=kpi><div class=n>{escape(melhor_txt)}</div><div class=l>melhor hora (conversão)</div><div class=s>mín. 15 decididas na hora</div></div></div>")

    opts_b = "".join(f"<option value='{v}' {'selected' if bundle == v else ''}>{lbl}</option>"
                     for v, lbl in [("todos", "todos os bundles"), ("B1", "B1"), ("B2", "B2"),
                                    ("B3", "B3"), ("B4", "B4"), ("B5", "B5")])
    form = (f"<form method=get action=/vendas><input type=hidden name=view value=horarios>"
            f"<div class=filters><div><label>de</label><input type=date name=ini value='{ini}'></div>"
            f"<div><label>até</label><input type=date name=fim value='{fim}'></div>"
            f"<div><label>bundle</label><select name=bundle>{opts_b}</select></div>"
            f"<button type=submit>Aplicar</button></div></form>")
    return ("<h1>Melhor Horário — reuniões de Vendas</h1>"
            "<div class=sub>momento em que o deal ENTROU em Negociação (horário de Brasília) — o card é movido após a reunião, "
            "então é o proxy de quando ela aconteceu · taxa = ganhas ÷ DECIDIDAS da própria coorte (as em aberto não contam — "
            "por isso pode diferir da taxa do funil, que divide os bookings do mês pelas oportunidades do mês misturando coortes)</div>"
            + form + kpis +
            "<section><h2>Mapa de calor — dia da semana × hora</h2>"
            f"<p class=secsub>período {ini.strftime('%d-%m-%Y')} a {fim.strftime('%d-%m-%Y')}"
            f"{' · bundle ' + bundle if bundle != 'todos' else ''} · quanto mais escuro, mais reuniões · passe o mouse para ver o desfecho da célula</p>"
            + _card(heat) + "</section>"
            "<section><h2>Conversão por hora da reunião</h2>"
            "<p class=secsub>a pergunta central: reunião em qual horário FECHA mais? · taxa sobre as decididas (ganhas + perdidas) · use janelas com amostra razoável antes de mudar a agenda do time</p>"
            + _card(_tbl([("Hora", "left"), ("Reuniões", "right"), ("Fechadas", "right"), ("Perdidas", "right"),
                          ("Em aberto", "right"), ("Taxa", "right"), ("", "right")], hrows)) + "</section>")


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
        fn = {"funil": _vd_funil, "ponte": _vd_ponte, "winloss": _vd_winloss,
              "ciclo": _vd_ciclo, "horarios": _vd_horarios, "closers": _vd_closers,
              "forecast": _vd_forecast}[view]
        content = fn(c, request) + "<p class=foot>Fonte: Pipedrive (cache local, coleta diária). A decisão é sempre do gestor — o especialista sinaliza.</p>"
    return HTMLResponse(_shell(A, "vendas", _VD_VIEWS, view, content, user))
