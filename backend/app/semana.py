"""Ações da Semana — /semana (spec completo 17/07; substitui o rascunho week_focus).

A camada que ORQUESTRA os times em torno dos objetivos da EMPRESA na semana:
  Camada 1 — o SISTEMA propõe 2-4 objetivos quantificados a partir dos gaps já
    medidos (bookings por bundle × meta, MRR em risco, ritmo de leads); o admin
    edita/confirma — nada vira foco de time sem confirmação humana.
  Camada 2 — decomposição por time: para cada objetivo confirmado, o foco de
    cada time que tem ALAVANCA REAL sobre ele, citando dados nominais (deals,
    contas, canais) com link para a tela de execução e a defasagem esperada.
    Máx. 2 ações por time; determinístico (a IA não inventa dado nenhum).
  Camada 3 — fechamento da semana ANTERIOR: o que era o objetivo × o que mexeu
    no número, respeitando as defasagens (churn ~60d nunca 'falha' numa semana).

Tudo compõe fontes existentes (PF, mkt_deals_attribution, accounts/alerts,
coorte do Ciclo, Ponte, lags) — nada recalculado com régua nova."""
from __future__ import annotations

import datetime as dt
import json
import math
import re
from html import escape

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

router = APIRouter()

_DDL = """
CREATE TABLE IF NOT EXISTS weekly_objectives (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    week_start DATE NOT NULL,
    title TEXT NOT NULL,
    metric TEXT,
    target_value NUMERIC,
    rationale TEXT,
    source TEXT,
    confirmed_by TEXT,
    confirmed_at TIMESTAMPTZ,
    status TEXT DEFAULT 'proposto',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS weekly_team_actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    objective_id UUID REFERENCES weekly_objectives(id) ON DELETE CASCADE,
    week_start DATE NOT NULL,
    team TEXT NOT NULL,
    action_text TEXT NOT NULL,
    data_refs JSONB,
    lag_note TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS weekly_review (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    objective_id UUID REFERENCES weekly_objectives(id) ON DELETE CASCADE,
    week_start DATE NOT NULL,
    result_value NUMERIC,
    result_note TEXT,
    maturation_pending BOOLEAN,
    created_at TIMESTAMPTZ DEFAULT NOW()
)"""

_TEAM_LBL = {"marketing": "Marketing", "prevendas": "Pré-vendas",
             "vendas": "Vendas", "growth": "Growth/Assessoria"}
_TEAM_HOME = {"marketing": "/marketing", "prevendas": "/prevendas",
              "vendas": "/vendas", "growth": "/growth"}


def _deps():
    from . import api as A
    return A


def _seg(hoje: dt.date | None = None) -> dt.date:
    """Segunda-feira da semana DE TRABALHO: no DOMINGO já vira para a semana
    seguinte (Otávio 17/07) — a proposta nova nasce no domingo e na segunda a
    equipe só confirma; o fechamento da semana que terminou aparece junto."""
    hoje = hoje or dt.date.today()
    if hoje.weekday() == 6:  # domingo → semana que começa amanhã
        return hoje + dt.timedelta(days=1)
    return hoje - dt.timedelta(days=hoje.weekday())


def _brl(v) -> str:
    return "—" if v is None else f"R$ {v:,.0f}".replace(",", ".")


def _link_html(lk) -> str:
    """Link de ação COM RÓTULO ('Metas do Semestre →', não dois 'abrir →' —
    Otávio 17/07). Aceita o formato antigo (string) por compatibilidade."""
    url, lbl = (lk[0], lk[1]) if isinstance(lk, (list, tuple)) else (lk, "abrir")
    return f"<a href='{url}' style='color:var(--brand);font-size:var(--fs-2xs)'>{escape(str(lbl))} →</a>"


def _acao_split(texto: str) -> tuple[str, str]:
    """Divide a ação em MANCHETE (o que fazer) + detalhe (os dados) — pedido
    20/07: a linha corrida era difícil de absorver; o título curto em destaque
    e o dado embaixo tornam o foco escaneável."""
    if ": " in texto[:90]:
        cab, resto = texto.split(": ", 1)
        return cab, resto
    for sep in (" — ", ". "):
        if sep in texto:
            a, b = texto.split(sep, 1)
            if len(a) <= 95:
                return a, b
    return texto, ""


def _ddl(conn):
    with conn.cursor() as cur:
        cur.execute(_DDL)


def _objetivos(conn, week: dt.date) -> list[dict]:
    _ddl(conn)
    with conn.cursor() as cur:
        cur.execute("""SELECT id::text, title, metric, target_value, rationale, source, status
                         FROM weekly_objectives WHERE week_start=%s
                        ORDER BY created_at, id""", (week,))
        return [{"id": i, "title": t, "metric": m, "target": (float(tv) if tv is not None else None),
                 "rationale": r, "source": s, "status": st}
                for i, t, m, tv, r, s, st in cur.fetchall()]


def _acoes(conn, week: dt.date) -> list[dict]:
    _ddl(conn)
    with conn.cursor() as cur:
        cur.execute("""SELECT a.id::text, a.team, a.action_text, a.data_refs, a.lag_note, o.title
                         FROM weekly_team_actions a JOIN weekly_objectives o ON o.id = a.objective_id
                        WHERE a.week_start=%s ORDER BY a.created_at""", (week,))
        return [{"id": i, "team": tm, "texto": tx, "refs": (rf or {}), "lag": lg, "objetivo": ot}
                for i, tm, tx, rf, lg, ot in cur.fetchall()]


# ---------------------------------------------------------------------------
# Camada 1 — proposta automática (gaps já medidos; humano confirma)
# ---------------------------------------------------------------------------
def _propor(conn, week: dt.date, force: bool = False) -> int:
    """Propõe 2-4 objetivos p/ a semana a partir dos gaps. Não repropõe se já
    houver objetivos (force=True descarta os PROPOSTOS e regenera)."""
    import calendar
    _ddl(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FILTER (WHERE status='confirmado'), count(*) "
                    "FROM weekly_objectives WHERE week_start=%s", (week,))
        n_conf, n_tot = cur.fetchone()
    if n_conf or (n_tot and not force):
        return 0
    with conn.cursor() as cur:
        # repropor NUNCA apaga objetivo adicionado manualmente pela gestão —
        # só as propostas do sistema são regeneradas (20/07)
        cur.execute("DELETE FROM weekly_objectives WHERE week_start=%s AND status='proposto' "
                    "AND source='sistema'", (week,))
    A = _deps()
    hoje = dt.date.today()
    mes = hoje.replace(day=1)
    dias_mes = calendar.monthrange(hoje.year, hoje.month)[1]
    frac = hoje.day / dias_mes
    dias_rest = max(1, dias_mes - hoje.day)
    semanas_rest = max(1.0, dias_rest / 7.0)
    cand: list[tuple[float, dict]] = []  # (score R$, objetivo)

    # (a) bundles atrás do ritmo — MESMA fonte do mini raio-x/financeiro
    from .sources import planejamento_financeiro as PF
    pf = PF.carrega()
    iso = f"{mes.year:04d}-{mes.month:02d}"
    i_pf = pf["meses"].index(iso) if pf and iso in pf["meses"] else None
    with conn.cursor() as cur:
        cur.execute("""SELECT substring(upper(COALESCE(produto,'')) FROM 'B[1-5]'), count(*)
                         FROM mkt_deals_attribution
                        WHERE status='won' AND won_time >= %s GROUP BY 1""", (f"{mes} 00:00-03",))
        reais = {b: int(n) for b, n in cur.fetchall() if b}
    if i_pf is not None:
        for b in ("B1", "B2", "B3", "B4", "B5"):
            meta_q = PF.linha(pf, f"{b} - Meta: Booking [Qtde]")[i_pf]
            meta_r = PF.linha(pf, f"{b} - Meta: Booking [R$]")[i_pf]
            real = reais.get(b, 0)
            if not meta_q or real / meta_q >= frac * 0.9:
                continue
            gap = meta_q - real
            alvo = max(1, math.ceil(gap / semanas_rest))
            ticket = (meta_r / meta_q) if meta_r else 0
            cand.append((gap * ticket, {
                "title": f"Fechar +{alvo} {b}", "metric": f"{b}:bookings", "target": alvo,
                "rationale": (f"meta mensal {meta_q:.0f}, fechados {real} ({real / meta_q * 100:.0f}% da meta com "
                              f"{frac * 100:.0f}% do mês) — faltam {gap:.0f} em {dias_rest} dias "
                              f"(~{alvo}/semana no ritmo necessário)")}))

    # (b) churn/risco: bundle com mais MRR em alerta crítico/alto
    with conn.cursor() as cur:
        cur.execute("""
            SELECT substring(a.name FROM 'B[1-5]') b, count(*), COALESCE(sum(a.recurring_revenue),0)
              FROM accounts a
             WHERE EXISTS (SELECT 1 FROM alerts al WHERE al.account_id=a.id AND al.status='aberto'
                             AND al.severity IN ('critico','alto'))
               AND substring(a.name FROM 'B[1-5]') IS NOT NULL
             GROUP BY 1 ORDER BY 3 DESC LIMIT 1""")
        r = cur.fetchone()
    if r and r[1] >= 3:
        b, k, mrr = r[0], int(r[1]), float(r[2])
        cand.append((mrr, {
            "title": f"Reduzir o churn do {b}", "metric": f"{b}:churn", "target": float(k),
            "rationale": f"{k} contas {b} em risco crítico/alto — {_brl(mrr)} de MRR em jogo"}))

    # (c) leads atrás do ritmo (mesma régua do hub)
    mkt = A._hub_mkt_stats(conn)
    sales = A._hub_sales_stats(conn)
    if mkt and mkt.get("leads_meta") and mkt["leads"] / mkt["leads_meta"] < mkt["frac"] * 0.75:
        gap_l = mkt["leads_meta"] * mkt["frac"] - mkt["leads"]
        conv = (mkt["book"] / mkt["leads"]) if mkt.get("leads") else 0
        ticket = (sales["receita"] / sales["book"]) if (sales and sales.get("book")) else 0
        cand.append((gap_l * conv * ticket, {
            "title": "Recuperar o ritmo de leads", "metric": "leads", "target": round(gap_l),
            "rationale": (f"{mkt['leads']:.0f} de {mkt['leads_meta']:.0f} leads da meta com "
                          f"{mkt['frac'] * 100:.0f}% do mês — {gap_l:.0f} leads atrás do ritmo")}))

    # continuidade (Otávio 17/07): a proposta da semana carrega o resultado da
    # anterior — objetivo de mesma métrica mostra o que foi alcançado (além
    # disso os gaps já são mês-a-data: o que a semana atual entregou reduz o
    # gap proposto automaticamente)
    prev = week - dt.timedelta(days=7)
    prev_notas: dict[str, str] = {}
    try:
        for r in _revisar(conn, prev):
            if r.get("metric"):
                prev_notas[r["metric"]] = r["nota"]
    except Exception:  # noqa: BLE001 — sem revisão anterior, proposta segue
        pass
    cand.sort(key=lambda x: -x[0])
    with conn.cursor() as cur:
        for _s, o in cand[:4]:
            rat = o["rationale"]
            if o["metric"] in prev_notas:
                rat += f" · semana anterior: {prev_notas[o['metric']]}"
            cur.execute("""INSERT INTO weekly_objectives (week_start, title, metric, target_value,
                               rationale, source, status) VALUES (%s,%s,%s,%s,%s,'sistema','proposto')""",
                        (week, o["title"], o["metric"], o["target"], rat))
    return len(cand[:4])


# ---------------------------------------------------------------------------
# Camada 2 — decomposição por time (alavanca real; dados nominais; máx 2/time)
# _gerar_acoes calcula SEM persistir — usada também como PRÉVIA na proposta
# (Otávio 17/07: revisar o quadro inteiro por área ANTES de confirmar)
# ---------------------------------------------------------------------------
def _decompor(conn, week: dt.date) -> int:
    """Gera e PERSISTE o foco por time dos objetivos CONFIRMADOS."""
    _ddl(conn)
    objs = [o for o in _objetivos(conn, week) if o["status"] == "confirmado"]
    with conn.cursor() as cur:
        cur.execute("DELETE FROM weekly_team_actions WHERE week_start=%s", (week,))
    if not objs:
        return 0
    final = _gerar_acoes(conn, objs)
    with conn.cursor() as cur:
        for oid, team, texto, refs, lag in final:
            cur.execute("""INSERT INTO weekly_team_actions
                               (objective_id, week_start, team, action_text, data_refs, lag_note)
                           VALUES (%s,%s,%s,%s,%s,%s)""",
                        (oid, week, team, texto, json.dumps(refs, ensure_ascii=False), lag))
    return len(final)


def _gerar_acoes(conn, objs: list[dict]) -> list[tuple]:
    """Decomposição em memória: [(obj_id, team, texto, refs, lag_note)] para os
    objetivos dados, na ordem de prioridade deles. Regras: alavanca real, dados
    nominais das tabelas, máx. 2 ações por time."""
    A = _deps()
    try:
        from .marketing.ui import _ciclo_coorte
        coorte, _g, _c = _ciclo_coorte(conn)
    except Exception:  # noqa: BLE001
        coorte = []
    lags = A._hub_lags(conn, coorte=coorte)

    def lag_txt(chave, rotulo):
        v = lags.get(chave)
        if v is None:
            return "sem base histórica para estimar a defasagem"
        return f"{rotulo} ~{max(1, round(v))} dia(s) (mediana histórica)"

    acoes: list[tuple[str, str, str, dict, str]] = []  # (obj_id, team, texto, refs, lag)

    for o in objs:
        m = re.match(r"(B[1-5]):(bookings|churn)", o["metric"] or "")
        b = m.group(1) if m else None
        tipo = m.group(2) if m else (o["metric"] or "")

        if tipo == "bookings" and b:
            with conn.cursor() as cur:
                cur.execute("""SELECT titulo, COALESCE(valor_custom, valor)
                                 FROM mkt_deals_attribution
                                WHERE status NOT IN ('won','lost') AND oport_time IS NOT NULL
                                  AND upper(COALESCE(produto,'')) LIKE %s
                                ORDER BY oport_time DESC LIMIT 8""", (f"{b}%",))
                pipe = [(t or "?", float(v or 0)) for t, v in cur.fetchall()]
            if pipe:  # Vendas: deals nominais no pipe
                soma = sum(v for _, v in pipe)
                nomes = ", ".join(escape(t[:28]) for t, _ in pipe[:3])
                acoes.append((o["id"], "vendas",
                              f"Feche nas oportunidades {b} JÁ abertas: {len(pipe)} no pipe (~{_brl(soma)}) — "
                              f"ex.: {nomes}. Fechar {o['target']:.0f} destas cumpre o objetivo.",
                              {"links": [["/vendas?view=forecast", "Forecast de Vendas"]],
                               "deals": [t for t, _ in pipe]},
                              lag_txt("oport_book", "oportunidade→contrato")))
            with conn.cursor() as cur:  # Pré-vendas: SLA do bundle (Ponte 120d)
                cur.execute("""
                    SELECT count(*) FILTER (WHERE status='won' AND sla<=15), count(*) FILTER (WHERE sla<=15),
                           count(*) FILTER (WHERE status='won' AND sla>60), count(*) FILTER (WHERE sla>60)
                      FROM (SELECT d.status, EXTRACT(epoch FROM (t.first_at-d.add_time))/60 sla
                              FROM mkt_deals_attribution d
                              LEFT JOIN sales_first_touch t ON t.deal_id=d.deal_id
                             WHERE d.oport_time >= now() - interval '120 days'
                               AND d.status IN ('won','lost')
                               AND upper(COALESCE(d.produto,'')) LIKE %s) x""", (f"{b}%",))
                w15, d15, w60, d60 = cur.fetchone()
            if d15 and d60 and d15 >= 8 and d60 >= 8 and (w15 / d15) > (w60 / d60):
                acoes.append((o["id"], "prevendas",
                              f"Priorize o 1º contato em ≤15min: oportunidade {b} atendida rápido fechou "
                              f"{w15 / d15 * 100:.0f}% vs {w60 / d60 * 100:.0f}% acima de 1h (120d) — zere a fila sem contato.",
                              {"links": [["/prevendas?view=speed", "Speed-to-Lead"]]},
                              lag_txt("oport_book", "efeito no fechamento")))
            cb = [r for r in coorte if r["bundle"] == b]
            canais = {}
            for r in cb:
                canais.setdefault(r["canal"], []).append(r)
            fortes = {c: rs for c, rs in canais.items() if len(rs) >= 5}
            if fortes:  # Marketing: canal que melhor retém o bundle
                melhor = max(fortes, key=lambda c: sum(1 for r in fortes[c] if r["desfecho"] == "ativo") / len(fortes[c]))
                ret = sum(1 for r in fortes[melhor] if r["desfecho"] == "ativo") / len(fortes[melhor])
                acoes.append((o["id"], "marketing",
                              f"Priorize a geração para {b} no canal com melhor retenção: {melhor} "
                              f"({ret * 100:.0f}% dos {len(fortes[melhor])} clientes {b} seguem ativos). "
                              "Atenção: parte do efeito cai nas próximas semanas.",
                              {"links": [["/marketing?view=ciclo", "Ciclo de Vida"],
                                         [f"/raiox?b={b}", f"Raio-X {b}"]]},
                              lag_txt("lead_book", "lead novo→contrato")))
            with conn.cursor() as cur:  # Growth: proteger os ativos do bundle em risco
                cur.execute("""SELECT a.id::text, a.name FROM accounts a
                                WHERE substring(a.name FROM 'B[1-5]')=%s
                                  AND EXISTS (SELECT 1 FROM alerts al WHERE al.account_id=a.id
                                                AND al.status='aberto')
                                ORDER BY a.recurring_revenue DESC NULLS LAST LIMIT 6""", (b,))
                risco = cur.fetchall()
            if risco:
                ids = ",".join(i for i, _ in risco)
                nomes = ", ".join(escape(n[:24]) for _, n in risco[:3])
                acoes.append((o["id"], "growth",
                              f"Proteja os {b} ativos em risco ({len(risco)} contas — ex.: {nomes}): perder pelo "
                              "outro lado anula o esforço de aquisição da semana.",
                              {"links": [[f"/growth?view=contas&ids={ids}", "contas em risco"]],
                               "contas": [n for _, n in risco]},
                              "efeito imediato (retenção)"))

        elif tipo == "churn" and b:
            with conn.cursor() as cur:  # Growth: intervir nas contas nominais
                cur.execute("""SELECT a.id::text, a.name FROM accounts a
                                WHERE substring(a.name FROM 'B[1-5]')=%s
                                  AND EXISTS (SELECT 1 FROM alerts al WHERE al.account_id=a.id
                                                AND al.status='aberto' AND al.severity IN ('critico','alto'))
                                ORDER BY a.recurring_revenue DESC NULLS LAST LIMIT 8""", (b,))
                risco = cur.fetchall()
            if risco:
                ids = ",".join(i for i, _ in risco)
                nomes = ", ".join(escape(n[:24]) for _, n in risco[:4])
                acoes.append((o["id"], "growth",
                              f"Intervenha esta semana nas {len(risco)} contas {b} em risco crítico/alto — "
                              f"ex.: {nomes}. A fila com dor dominante e plano de ação está na aba Contas/Alertas.",
                              {"links": [[f"/growth?view=contas&ids={ids}", "contas em risco"]],
                               "contas": [n for _, n in risco]},
                              "efeito imediato (retenção)"))
            cb = [r for r in coorte if r["bundle"] == b]
            canais = {c: rs for c, rs in
                      ((c, [r for r in cb if r["canal"] == c]) for c in {r["canal"] for r in cb})
                      if len(rs) >= 5}
            if len(canais) >= 2:  # Marketing: migrar aquisição do canal ruim
                prec = {c: sum(1 for r in rs if r["desfecho"] == "precoce") / len(rs) for c, rs in canais.items()}
                pior, melhor = max(prec, key=prec.get), min(prec, key=prec.get)
                if prec[pior] - prec[melhor] >= 0.15:
                    acoes.append((o["id"], "marketing",
                                  f"Reduza a aquisição de {b} via {pior} ({prec[pior] * 100:.0f}% de churn precoce) "
                                  f"e realoque para {melhor} ({prec[melhor] * 100:.0f}%) — cada {b} mal adquirido "
                                  "volta como churn em ~60 dias.",
                                  {"links": [["/marketing?view=ciclo", "Ciclo de Vida"],
                                             [f"/raiox?b={b}", f"Raio-X {b}"]]},
                                  lag_txt("book_churn", "efeito no churn precoce")))
            with conn.cursor() as cur:  # Vendas/PV: alinhar expectativa no motivo dominante
                # bundle pelo PLANO via _canc_bundle (correção 20/07 — o LIKE na
                # equipe classificava cliente ADS do squad Bx como churn do Bx)
                cur.execute("""SELECT motivo, plano, equipe FROM grw_cancelamentos
                                WHERE tipo='cancelamento' AND motivo IS NOT NULL AND meses <= 3""")
                from collections import Counter
                cont_m = Counter(
                    str(mo).strip()[:60] for mo, pl, eq in cur.fetchall()
                    if A._canc_bundle({"plano": pl, "equipe": eq}) == b)
                mot = cont_m.most_common(1)[0] if cont_m else None
            if mot and mot[1] >= 3:
                acoes.append((o["id"], "vendas",
                              f"Ao fechar {b}, alinhe a expectativa sobre “{escape(str(mot[0])[:60])}” — motivo "
                              f"nº1 de saída precoce do {b} ({mot[1]} casos). Desalinhamento na venda vira churn.",
                              {"links": [["/vendas?view=winloss", "Win/Loss"],
                                         ["/growth?view=cancelamentos", "Cancelamentos"]]},
                              lag_txt("book_churn", "efeito no churn precoce")))

        elif tipo == "leads":
            acoes.append((o["id"], "marketing",
                          f"Destrave a geração: {o['rationale']}. Revise verba/campanhas nas Metas do Semestre "
                          "e o CPL diário na aba Mídia.",
                          {"links": [["/marketing?view=metas", "Metas do Semestre"],
                                     ["/marketing?view=midia", "Mídia diária"]]},
                          lag_txt("lead_book", "lead novo→contrato")))
            if (s := A._hub_sales_stats(conn)) and s.get("tem_touch") and s.get("sem_toque"):
                acoes.append((o["id"], "prevendas",
                              f"Não desperdice o que já entrou: {s['sem_toque']} leads do mês sem 1º contato — "
                              "lead parado esfria e anula o esforço de geração.",
                              {"links": [["/prevendas?view=speed", "Speed-to-Lead"]]},
                              lag_txt("lead_book", "efeito em contratos")))

    # regra do FOCO: máx. 2 ações por time (ordem = prioridade dos objetivos)
    por_time: dict[str, int] = {}
    final = []
    for oid, team, texto, refs, lag in acoes:
        if por_time.get(team, 0) >= 2:
            continue
        por_time[team] = por_time.get(team, 0) + 1
        final.append((oid, team, texto, refs, lag))
    return final


# ---------------------------------------------------------------------------
# Camada 3 — fechamento da semana (respeitando defasagens)
# ---------------------------------------------------------------------------
def _revisar(conn, week: dt.date) -> list[dict]:
    _ddl(conn)
    objs = [o for o in _objetivos(conn, week) if o["status"] == "confirmado"]
    if not objs:
        return []
    fim = week + dt.timedelta(days=7)
    out = []
    with conn.cursor() as cur:
        for o in objs:
            m = re.match(r"(B[1-5]):(bookings|churn)", o["metric"] or "")
            b = m.group(1) if m else None
            tipo = m.group(2) if m else (o["metric"] or "")
            val, nota, matur = None, "", False
            if tipo == "bookings" and b:
                cur.execute("""SELECT count(*) FROM mkt_deals_attribution
                                WHERE status='won' AND won_time >= %s AND won_time < %s
                                  AND upper(COALESCE(produto,'')) LIKE %s""",
                            (f"{week} 00:00-03", f"{fim} 00:00-03", f"{b}%"))
                val = float(cur.fetchone()[0])
                alvo = f" de {o['target']:.0f}" if o["target"] else ""
                nota = f"{val:.0f}{alvo} {b} fechados na semana"
            elif tipo == "churn" and b:
                cur.execute("""SELECT o2.outcome, count(*) FROM outcomes o2
                                JOIN accounts a ON a.id = o2.account_id
                               WHERE o2.outcome_date >= %s AND o2.outcome_date < %s
                                 AND substring(a.name FROM 'B[1-5]') = %s
                               GROUP BY 1""", (week, fim, b))
                res = dict(cur.fetchall())
                ret, canc = int(res.get("retida", 0)), int(res.get("cancelada", 0))
                val = float(ret)
                nota = (f"{ret} conta(s) {b} retida(s), {canc} cancelada(s) na semana (desfechos registrados)"
                        if (ret or canc) else "nenhum desfecho registrado na semana")
                matur = True  # lag de churn (~60d) >> 1 semana
                nota += " — resultado ainda em maturação (defasagem ~60 dias); não leia como falha da semana"
            elif tipo == "leads":
                cur.execute("""SELECT count(*) FROM mkt_deals_attribution
                                WHERE add_time >= %s AND add_time < %s""",
                            (f"{week} 00:00-03", f"{fim} 00:00-03"))
                val = float(cur.fetchone()[0])
                nota = f"{val:.0f} leads entraram na semana" + (f" (alvo: +{o['target']:.0f})" if o["target"] else "")
            cur.execute("DELETE FROM weekly_review WHERE objective_id=%s", (o["id"],))
            cur.execute("""INSERT INTO weekly_review (objective_id, week_start, result_value,
                               result_note, maturation_pending) VALUES (%s,%s,%s,%s,%s)""",
                        (o["id"], week, val, nota, matur))
            out.append({"objetivo": o["title"], "metric": o["metric"], "valor": val,
                        "nota": nota, "maturacao": matur})
    return out


# ---------------------------------------------------------------------------
# integrações: 'Prioridades da Semana' na central (fusão Foco+Iniciativas,
# 17/07 noite) + banner por área
# ---------------------------------------------------------------------------
def _impacto_objetivo(conn, obj: dict, impactos: dict) -> dict | None:
    """Impacto em R$/mês do objetivo — MESMO cálculo/premissas das Iniciativas
    (a fusão só muda ONDE o número aparece). None = sem estimativa (manual)."""
    import calendar
    m = re.match(r"(B[1-5]):(bookings|churn)", obj.get("metric") or "")
    if obj.get("metric") == "leads":
        e = (impactos or {}).get("leads")
        return dict(e, janela="lead_book") if e else None
    if not m:
        return None
    b, tipo = m.group(1), m.group(2)
    hoje = dt.date.today()
    mes = hoje.replace(day=1)
    frac = hoje.day / calendar.monthrange(hoje.year, hoje.month)[1]
    try:
        if tipo == "bookings":
            from .sources import planejamento_financeiro as PF
            pf = PF.carrega()
            iso = f"{mes.year:04d}-{mes.month:02d}"
            if not pf or iso not in pf["meses"]:
                return None
            meta_r = PF.linha(pf, f"{b} - Meta: Booking [R$]")[pf["meses"].index(iso)]
            if not meta_r:
                return None
            with conn.cursor() as cur:
                cur.execute("""SELECT COALESCE(sum(COALESCE(valor_custom, valor)), 0)
                                 FROM mkt_deals_attribution
                                WHERE status='won' AND won_time >= %s
                                  AND upper(COALESCE(produto,'')) LIKE %s""",
                            (f"{mes} 00:00-03", f"{b}%"))
                real_r = float(cur.fetchone()[0])
            cons = max(0.0, meta_r * frac - real_r)
            otim = max(cons, meta_r - (real_r / frac if frac else real_r))
            if cons <= 0:
                return None
            return {"faixa": (cons, otim), "janela": "oport_book",
                    "premissa": (f"gap de receita do {b} vs o ritmo da meta (conservador) e o gap projetado "
                                 "p/ o fim do mês (otimista) — mesmo cálculo do Financeiro")}
        if tipo == "churn":
            with conn.cursor() as cur:
                cur.execute("""SELECT COALESCE(sum(a.recurring_revenue), 0) FROM accounts a
                                WHERE substring(a.name FROM 'B[1-5]') = %s
                                  AND EXISTS (SELECT 1 FROM alerts al WHERE al.account_id=a.id
                                                AND al.status='aberto' AND al.severity IN ('critico','alto'))""", (b,))
                mrr = float(cur.fetchone()[0] or 0)
                cur.execute("""SELECT count(*) FROM grw_cancelamentos
                                WHERE tipo='cancelamento'
                                  AND mes >= date_trunc('month', now()) - interval '3 months'
                                  AND mes < date_trunc('month', now())
                                  AND upper(COALESCE(plano, '')) NOT LIKE '%%START%%'""")
                canc3 = int(cur.fetchone()[0])
                cur.execute("SELECT count(*) FROM accounts WHERE substring(name FROM 'B[1-5]') IS DISTINCT FROM 'B1'")
                base_rec = int(cur.fetchone()[0])
            if mrr <= 0:
                return None
            tx = (canc3 / 3.0 / base_rec) if base_rec else 0.10
            return {"faixa": (mrr * tx, mrr), "janela": None,
                    "premissa": (f"EXPOSIÇÃO: {_brl(mrr)} de MRR do {b} em risco crítico/alto — conservador aplica "
                                 f"o churn mensal médio dos recorrentes ({tx * 100:.1f}%), otimista = exposição total; "
                                 "risco, não perda certa")}
    except Exception:  # noqa: BLE001 — sem estimativa, o card sai sem chip de R$
        return None
    return None


def prioridades_hub_html(conn, impactos: dict | None, lags: dict | None) -> tuple[str, list[str]]:
    """Seção 'Prioridades da Semana' da central: os objetivos CONFIRMADOS como
    cards ordenados por impacto em R$, com o foco por time legível dentro de
    cada card. Retorna (html, foco_kw p/ absorver iniciativas equivalentes)."""
    from .help_texts import _hint
    lg = lags or {}
    try:
        week = _seg()
        objs = [o for o in _objetivos(conn, week) if o["status"] == "confirmado"]
        acs = _acoes(conn, week) if objs else []
    except Exception:  # noqa: BLE001 — a seção nunca derruba a central
        return "", []
    hint = _hint("Prioridades da Semana",
                 "O que mostra: os objetivos confirmados da semana ORDENADOS pelo impacto estimado em R$/mês — a "
                 "lógica de dinheiro das antigas 'Iniciativas sugeridas' agora organiza e justifica o foco da semana "
                 "(uma lista só, não duas).\n"
                 "Como ler: cada card é um objetivo, com a faixa de R$ em jogo (conservador–otimista, premissa por "
                 "extenso), a defasagem esperada e a origem (proposto pelo sistema × adicionado pela gestão). Dentro, "
                 "o foco de cada time com o link de execução. Gargalos que não cabem na semana ficam no bloco "
                 "'Iniciativas de maior horizonte', mais abaixo.\n"
                 "Fique de olho: (1) as faixas são potencial estimado, não promessa — valide premissas com o gestor "
                 "da área; (2) não reavalie antes da defasagem; (3) a definição e o fechamento moram na Ações da "
                 "Semana — aqui é o resumo executivo.")
    if not objs:
        html = ("<section><h2>Prioridades da Semana</h2>" + hint +
                "<div class=warn style='margin-top:4px'>⚠ Objetivos da semana pendentes de confirmação — "
                "<a href='/semana' style='color:var(--brand);font-weight:600'>revisar a proposta e confirmar →</a> "
                "<span style='color:var(--text-muted)'>· enquanto isso, os gargalos seguem listados em "
                "'Iniciativas de maior horizonte' abaixo</span></div></section>")
        return html, []

    def _janela_chip(e):
        ch = (e or {}).get("janela")
        if e and ch is None and "EXPOSIÇÃO" in (e.get("premissa") or ""):
            return "efeito imediato (retenção)"
        v = lg.get(ch) if ch else None
        if v is None:
            return "defasagem sem base histórica"
        return f"efeito em ~{max(1, round(v))} dia(s)"

    por_obj: dict[str, list[dict]] = {}
    for a in acs:
        por_obj.setdefault(a["objetivo"], []).append(a)
    decorados = []
    for o in objs:
        e = _impacto_objetivo(conn, o, impactos or {})
        decorados.append((e["faixa"][1] if e else -1.0, o, e))
    decorados.sort(key=lambda x: -x[0])

    cards = ""
    for idx, (_s, o, e) in enumerate(decorados, 1):
        chip_rs = (f"<span class=chip style='--c:var(--brand)'>"
                   f"≈ {_brl(e['faixa'][0])}–{_brl(e['faixa'][1])}/mês em jogo</span>" if e else
                   "<span class=chip style='--c:var(--status-semdados)'>impacto não estimado</span>")
        meta_l = (f"<span style='font-size:var(--fs-2xs);color:var(--text-muted)'>{escape(_janela_chip(e))} · "
                  + ("proposto pelo sistema, confirmado pela gestão" if o["source"] == "sistema"
                     else "adicionado pela gestão") + "</span>")
        times = ""
        for a in por_obj.get(o["title"], []):
            links = " · ".join(_link_html(lk) for lk in (a["refs"].get("links") or [])[:2])
            manchete, detalhe = _acao_split(a["texto"])
            times += (
                "<div style='display:flex;gap:12px;align-items:flex-start;padding:9px 0;"
                "border-top:1px solid var(--border)'>"
                f"<span style='flex-shrink:0;min-width:118px;background:var(--surface-3);"
                f"border:1px solid var(--border-strong);border-radius:var(--radius-sm);padding:4px 9px;"
                f"font-size:var(--fs-2xs);font-weight:600;text-align:center;margin-top:1px'>"
                f"{_TEAM_LBL.get(a['team'], a['team'])}</span>"
                f"<span style='flex:1'>"
                f"<span style='display:block;font-size:var(--fs-sm);font-weight:600;line-height:1.4'>"
                f"{manchete}</span>"
                + (f"<span style='display:block;font-size:var(--fs-xs);color:var(--text-muted);"
                   f"line-height:1.55;margin-top:2px'>{detalhe} {links}</span>" if detalhe else
                   f"<span style='display:block;margin-top:2px'>{links}</span>")
                + "</span></div>")
        prem = (f"<details style='margin-top:6px'><summary style='cursor:pointer;font-size:var(--fs-2xs);"
                f"color:var(--text-muted)'>▸ como estimamos o valor (premissa)</summary>"
                f"<div style='font-size:var(--fs-xs);color:var(--text-muted);margin-top:4px;line-height:1.55'>"
                f"{escape(e['premissa'])} · potencial estimado, não promessa</div></details>" if e else "")
        cards += (
            "<div class=central style='margin-top:12px'>"
            "<div style='display:flex;gap:12px;flex-wrap:wrap;align-items:baseline'>"
            f"<span style='font-family:var(--font-display);font-weight:700;font-size:var(--fs-lg);"
            f"color:var(--text-faint)'>{idx}º</span>"
            f"<span style='font-family:var(--font-display);font-weight:700;font-size:var(--fs-lg)'>"
            f"{escape(o['title'])}</span>{chip_rs}{meta_l}</div>"
            + prem
            + (f"<div style='margin-top:8px'>{times}</div>" if times else
               "<div style='margin-top:8px;font-size:var(--fs-sm);color:var(--text-muted)'>"
               "sem área com alavanca direta — objetivo estratégico</div>")
            + "</div>")

    resumo = " · ".join(escape(o["title"]) for _s, o, _e in decorados[:4])
    week_lbl = week.strftime("%d/%m")
    html = (
        f"<section><h2>Prioridades da Semana "
        f"<span style='font-size:var(--fs-2xs);color:var(--text-faint);font-weight:400'>"
        f"(semana de {week_lbl} · confirmada)</span></h2>"
        + hint +
        f"<p class=secsub>Esta semana, em ordem de impacto: <b>{resumo}</b> · "
        "<a href='/semana' style='color:var(--brand)'>abrir Ações da Semana →</a></p>"
        + cards + "</section>")
    return html, [o["title"].lower() for o in objs]


def foco_hub_html(conn) -> tuple[str, list[str]]:
    from .help_texts import _hint
    try:
        week = _seg()
        objs = [o for o in _objetivos(conn, week) if o["status"] == "confirmado"]
        acs = _acoes(conn, week) if objs else []
    except Exception:  # noqa: BLE001 — camada 0 nunca derruba a central
        return "", []
    hint = _hint("Foco da semana",
                 "O que mostra: os objetivos que a GESTÃO confirmou para a semana (o sistema propõe a partir dos "
                 "gaps; o admin confirma na Ações da Semana) e o foco de cada time derivado deles.\n"
                 "Como ler: a linha de cima são os objetivos da empresa; os cartões, a 1ª ação de cada time. "
                 "Tudo clica para a Ações da Semana completa (ações com dados nominais e defasagens).\n"
                 "Fique de olho: iniciativa lá embaixo com o selo 'foco desta semana' é onde o combinado e o dado "
                 "apontam para o mesmo lugar — comece por ela.")
    if not objs:
        html = ("<section><h2>Foco da semana</h2>" + hint +
                "<div class=warn style='margin-top:4px'>⚠ Objetivos da semana pendentes de confirmação — "
                "<a href='/semana' style='color:var(--brand);font-weight:600'>revisar a proposta e confirmar →</a>"
                "</div></section>")
        return html, []
    primeira: dict[str, dict] = {}
    for a in acs:
        primeira.setdefault(a["team"], a)
    minis = "".join(
        f"<a href='/semana' style='display:inline-block;background:var(--surface-2);"
        f"border:1px solid var(--border-strong);border-radius:var(--radius-sm);padding:6px 11px;"
        f"margin:4px 6px 0 0;font-size:var(--fs-xs);color:var(--text-2);text-decoration:none'>"
        f"<b>{_TEAM_LBL.get(t, t)}</b>: {escape(a['texto'][:64])}…</a>"
        for t, a in primeira.items())
    obj_txt = " · ".join(escape(o["title"]) for o in objs[:4])
    html = (
        "<section><h2>Foco da semana"
        f" <span style='font-size:var(--fs-2xs);color:var(--text-faint);font-weight:400'>"
        f"(semana de {week.strftime('%d/%m')})</span></h2>" + hint +
        f"<div class=central><a href='/semana' style='text-decoration:none;color:inherit'>"
        f"<div style='font-family:var(--font-display);font-weight:600;font-size:var(--fs-md);line-height:1.5'>"
        f"Esta semana: {obj_txt}</div></a>"
        + (f"<div style='margin-top:6px'>{minis}</div>" if minis else "")
        + "<div style='margin-top:8px;font-size:var(--fs-2xs)'>"
          "<a href='/semana' style='color:var(--brand)'>abrir Ações da Semana →</a></div></div></section>")
    return html, [o["title"].lower() for o in objs]


def foco_time_html(conn, team: str) -> str:
    """Banner 'seu foco desta semana' no topo da ÁREA correspondente."""
    if team not in _TEAM_LBL:
        return ""
    try:
        acs = [a for a in _acoes(conn, _seg()) if a["team"] == team]
    except Exception:  # noqa: BLE001
        return ""
    if not acs:
        return ""
    def _item_banner(a):
        manchete, detalhe = _acao_split(a["texto"])
        return ("<div style='padding:5px 0;font-size:var(--fs-sm);line-height:1.55;color:var(--text-2)'>"
                f"→ <b>{manchete}</b>"
                + (f"<span style='color:var(--text-muted);font-size:var(--fs-xs)'> — {detalhe}</span>"
                   if detalhe else "")
                + (f" <span style='color:var(--text-faint);font-size:var(--fs-2xs)'>({escape(a['lag'])})</span>"
                   if a.get("lag") else "") + "</div>")

    itens = "".join(_item_banner(a) for a in acs[:2])
    return ("<div class=central style='margin:14px 0'>"
            "<div style='font-size:var(--fs-2xs);font-weight:600;text-transform:uppercase;"
            "letter-spacing:var(--tracking-label);color:var(--brand)'>Seu foco desta semana"
            " <a href='/semana' style='color:var(--text-muted);font-weight:400;text-transform:none;"
            "letter-spacing:0'>· ver Ações da Semana →</a></div>"
            + itens + "</div>")


# ---------------------------------------------------------------------------
# página /semana + endpoints
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Endpoint JSON do redesenho (Lote 5, 22/07) — o ESTADO INTEIRO da tela numa
# chamada, com a MESMA orquestração do handler HTML (inclusive a prévia da
# decomposição antes de confirmar). As AÇÕES de escrita seguem no POST
# /semana/salvar já existente — o SPA posta lá e refaz o fetch.
# ---------------------------------------------------------------------------
@router.get("/api/semana/painel")
def api_semana_painel(request: Request):
    A = _deps()
    s = A._session(request)
    if not s:
        from fastapi.responses import JSONResponse as _J
        return _J({"error": "sessao"}, status_code=401)
    _user, role = s
    edita = role == "admin"
    week = _seg()
    with A._conn() as c:
        if edita:
            _propor(c, week)  # segunda de manhã: proposta pronta ao abrir
        objs = _objetivos(c, week)
        acs = _acoes(c, week)
        rev = _revisar(c, week - dt.timedelta(days=7))
        confirmada = any(o["status"] == "confirmado" for o in objs)
        # PRÉVIA da decomposição antes de confirmar (mesma regra do HTML)
        if not confirmada and objs:
            titulo_por_id = {o["id"]: o["title"] for o in objs}
            acs = [{"team": t, "texto": tx, "refs": rf, "lag": lg,
                    "objetivo": titulo_por_id.get(oid, "")}
                   for oid, t, tx, rf, lg in _gerar_acoes(c, objs)]

    times_por_obj: dict[str, list[str]] = {}
    for a in acs:
        times_por_obj.setdefault(a["objetivo"], [])
        lbl = _TEAM_LBL.get(a["team"], a["team"])
        if lbl not in times_por_obj[a["objetivo"]]:
            times_por_obj[a["objetivo"]].append(lbl)

    def _links(refs):
        out = []
        for lk in (refs.get("links") or []):
            url, lbl = (lk[0], lk[1]) if isinstance(lk, (list, tuple)) else (lk, "abrir")
            out.append({"url": url, "label": str(lbl)})
        return out

    acoes = []
    for a in acs:
        manchete, detalhe = _acao_split(a["texto"])
        acoes.append({"team": a["team"], "team_label": _TEAM_LBL.get(a["team"], a["team"]),
                      "objetivo": a["objetivo"], "manchete": manchete, "detalhe": detalhe,
                      "links": _links(a.get("refs") or {}), "lag": a.get("lag")})
    return {
        "week": week.isoformat(), "week_label": week.strftime("%d/%m"),
        "week_anterior_label": (week - dt.timedelta(days=7)).strftime("%d/%m"),
        "edita": edita, "confirmada": confirmada,
        "objetivos": [dict(o, times=times_por_obj.get(o["title"], [])) for o in objs],
        "acoes": acoes,
        "times_ordem": ["marketing", "prevendas", "vendas", "growth"],
        "revisao": [{"objetivo": r["objetivo"], "nota": r["nota"], "maturacao": r["maturacao"]}
                    for r in rev],
        "metricas": ([{"v": "", "lbl": "— livre —"}]
                     + [{"v": f"{b}:{k}", "lbl": f"{b} {k}"}
                        for b in ("B1", "B2", "B3", "B4", "B5") for k in ("bookings", "churn")]
                     + [{"v": "leads", "lbl": "leads"}]),
    }


@router.get("/semana", response_class=HTMLResponse)
def semana_page(request: Request):
    A = _deps()
    s = A._session(request)
    if not s:
        return RedirectResponse("/login", status_code=302)
    user, role = s
    from .help_texts import _hint
    edita = role == "admin"
    # redesenho: rota própria (sem ?view=) — mesmo chaveamento, view sintética
    from . import spa as _spa_mod
    _r = _spa_mod.view_response(request, "semana", "visao")
    if _r is not None:
        return _r
    week = _seg()
    with A._conn() as c:
        with c.cursor() as cur:
            cur.execute("INSERT INTO audit_log (actor, action, scope) VALUES (%s,'view','semana')", (user,))
        if edita:
            _propor(c, week)  # segunda de manhã: proposta pronta ao abrir
        objs = _objetivos(c, week)
        acs = _acoes(c, week)
        rev = _revisar(c, week - dt.timedelta(days=7))
        confirmada = any(o["status"] == "confirmado" for o in objs)
        # PRÉVIA da decomposição por área já na PROPOSTA (Otávio 17/07): o
        # quadro inteiro — objetivo da empresa + o que cada área faria por ele —
        # é revisado ANTES de confirmar; a confirmação só efetiva
        if not confirmada and objs:
            titulo_por_id = {o["id"]: o["title"] for o in objs}
            acs = [{"team": t, "texto": tx, "refs": rf, "lag": lg,
                    "objetivo": titulo_por_id.get(oid, "")}
                   for oid, t, tx, rf, lg in _gerar_acoes(c, objs)]

    # times que servem cada objetivo (mostra a AMARRAÇÃO objetivo↔áreas)
    times_por_obj: dict[str, list[str]] = {}
    for a in acs:
        times_por_obj.setdefault(a["objetivo"], [])
        if _TEAM_LBL.get(a["team"], a["team"]) not in times_por_obj[a["objetivo"]]:
            times_por_obj[a["objetivo"]].append(_TEAM_LBL.get(a["team"], a["team"]))

    def obj_row(o):
        chip = ("<span class=chip style='--c:var(--status-baixo)'>confirmado</span>" if o["status"] == "confirmado"
                else "<span class=chip style='--c:var(--status-medio)'>proposto</span>")
        origem = {"sistema": "proposto pelo sistema", "manual": "adicionado manualmente"}.get(o["source"], o["source"])
        del_btn = ""
        if edita and not confirmada:
            del_btn = (f"<form method=post action='/semana/salvar' style='display:inline'>"
                       f"<input type=hidden name=acao value=del><input type=hidden name=obj_id value='{o['id']}'>"
                       f"<button style='border:none;background:none;color:var(--status-critico);cursor:pointer'>✕</button></form>")
        times_chips = "".join(
            f"<span class=chip style='--c:var(--status-semdados)'>{escape(t)}</span> "
            for t in times_por_obj.get(o["title"], []))
        return (f"<div style='padding:9px 0;border-top:1px solid var(--border)'>"
                f"<div style='display:flex;gap:10px;align-items:center;flex-wrap:wrap'>"
                f"<b style='font-size:var(--fs-md)'>{escape(o['title'])}</b>{chip}{del_btn}</div>"
                f"<div style='font-size:var(--fs-sm);color:var(--text-muted);margin-top:2px'>"
                f"{escape(o['rationale'] or '')} <span style='color:var(--text-faint)'>· {origem}</span></div>"
                + (f"<div style='margin-top:5px;font-size:var(--fs-2xs)'>"
                   f"<span style='color:var(--text-faint)'>áreas que puxam este objetivo:</span> {times_chips}</div>"
                   if times_chips else
                   "<div style='margin-top:5px;font-size:var(--fs-2xs);color:var(--text-faint)'>"
                   "nenhuma área com alavanca direta detectada — objetivo estratégico/manual</div>")
                + "</div>")

    objs_html = "".join(obj_row(o) for o in objs) or \
        "<div style='padding:10px 0;color:var(--text-muted)'>sem gaps relevantes detectados — adicione um objetivo manual se necessário.</div>"

    controles = ""
    if edita:
        if not confirmada:
            controles = (
                "<div style='display:flex;gap:10px;flex-wrap:wrap;margin-top:12px'>"
                "<form method=post action='/semana/salvar'><input type=hidden name=acao value=confirmar>"
                "<button style='background:var(--brand);color:var(--brand-ink);font-weight:700;border:none;"
                "padding:9px 16px;border-radius:var(--radius-sm);cursor:pointer'>✓ Confirmar objetivos e gerar o foco dos times</button></form>"
                "<form method=post action='/semana/salvar'><input type=hidden name=acao value=repropor>"
                "<button class=abtn style='cursor:pointer'>↻ repropor do zero</button></form></div>"
                "<form method=post action='/semana/salvar' style='display:flex;gap:10px;flex-wrap:wrap;align-items:end;margin-top:12px'>"
                "<input type=hidden name=acao value=add>"
                "<div style='flex:1;min-width:260px'><label style='display:block;font-size:var(--fs-2xs);"
                "color:var(--text-muted);text-transform:uppercase;margin-bottom:3px'>objetivo manual (curto e mensurável)</label>"
                "<input name=titulo maxlength=90 placeholder='ex.: Fechar +2 B4' style='width:100%;background:var(--bg-panel);"
                "border:1px solid var(--border-strong);border-radius:var(--radius-sm);color:var(--text);padding:7px 9px'></div>"
                "<div><label style='display:block;font-size:var(--fs-2xs);color:var(--text-muted);"
                "text-transform:uppercase;margin-bottom:3px'>métrica</label>"
                "<select name=metric style='background:var(--bg-panel);border:1px solid var(--border-strong);"
                "border-radius:var(--radius-sm);color:var(--text);padding:7px 9px'>"
                "<option value=''>— livre —</option>"
                + "".join(f"<option value='{b}:bookings'>{b} bookings</option><option value='{b}:churn'>{b} churn</option>"
                          for b in ("B1", "B2", "B3", "B4", "B5"))
                + "<option value='leads'>leads</option></select></div>"
                "<button class=abtn style='cursor:pointer;padding:8px 14px'>+ adicionar</button></form>")
        else:
            controles = ("<div style='margin-top:12px;display:flex;gap:10px'>"
                         "<form method=post action='/semana/salvar'><input type=hidden name=acao value=decompor>"
                         "<button class=abtn style='cursor:pointer'>↻ regenerar o foco dos times</button></form>"
                         "<form method=post action='/semana/salvar'><input type=hidden name=acao value=reabrir>"
                         "<button class=abtn style='cursor:pointer'>reabrir objetivos</button></form></div>")

    por_time: dict[str, list[dict]] = {}
    for a in acs:
        por_time.setdefault(a["team"], []).append(a)
    times_html = ""
    for t in ("marketing", "prevendas", "vendas", "growth"):
        if t not in por_time:
            continue
        def _linha_acao(a):
            manchete, detalhe = _acao_split(a["texto"])
            links = " · ".join(_link_html(lk) for lk in (a["refs"].get("links") or [])[:2])
            return (
                "<div style='padding:9px 0;border-top:1px solid var(--border)'>"
                f"<div style='font-size:var(--fs-2xs);color:var(--brand);text-transform:uppercase;"
                f"letter-spacing:var(--tracking-label)'>contribui para: {escape(a['objetivo'])}</div>"
                f"<div style='font-size:var(--fs-sm);font-weight:600;line-height:1.45;margin-top:2px'>{manchete}</div>"
                + (f"<div style='font-size:var(--fs-xs);color:var(--text-muted);line-height:1.55;margin-top:2px'>"
                   f"{detalhe} {links}</div>" if detalhe else f"<div style='margin-top:2px'>{links}</div>")
                + (f"<div style='color:var(--text-faint);font-size:var(--fs-2xs);margin-top:3px'>defasagem: "
                   f"{escape(a['lag'])}</div>" if a.get("lag") else "")
                + "</div>")

        linhas = "".join(_linha_acao(a) for a in por_time[t])
        times_html += (f"<div class=central style='margin-top:10px'>"
                       f"<b style='font-family:var(--font-display)'>{_TEAM_LBL[t]}</b>{linhas}</div>")
    if not times_html and objs:
        times_html = "<p class=note>nenhum time com alavanca real sobre os objetivos atuais — revise os objetivos.</p>"

    rev_html = ""
    if rev:
        rev_rows = "".join(
            f"<div style='padding:7px 0;border-top:1px solid var(--border);font-size:var(--fs-sm)'>"
            f"<b>{escape(r['objetivo'])}</b> — {escape(r['nota'])}"
            + (" <span class=chip style='--c:var(--status-semdados)'>em maturação</span>" if r["maturacao"] else "")
            + "</div>" for r in rev)
        rev_html = (f"<section><h2>Fechamento da semana anterior "
                    f"<span style='font-size:var(--fs-2xs);color:var(--text-faint);font-weight:400'>"
                    f"({(week - dt.timedelta(days=7)).strftime('%d/%m')})</span></h2>"
                    "<p class=secsub>o que era o objetivo × o que mexeu no número — leitura de aprendizado, não "
                    "auditoria; defasagens respeitadas (churn não 'falha' numa semana)</p>"
                    f"<div class=central>{rev_rows}</div></section>")

    status = ("<span class=chip style='--c:var(--status-baixo)'>semana CONFIRMADA</span>" if confirmada
              else "<span class=chip style='--c:var(--status-medio)'>proposta — pendente de confirmação</span>")
    body = (
        "<h1>Ações da Semana</h1>"
        "<p class=sub>os objetivos da EMPRESA na semana e o foco de cada time derivado deles. O sistema propõe a "
        "partir dos gaps já medidos; o admin edita e CONFIRMA — nada vira foco de time sem confirmação humana. "
        "As ações citam dados reais (deals, contas, canais) e a defasagem esperada de cada correção.</p>"
        + _hint("Ações da Semana",
                "O que mostra: a semana da empresa em 3 camadas — objetivos (propostos pelo sistema a partir dos gaps "
                "de bookings por bundle, MRR em risco e ritmo de leads; confirmados por você), o foco de cada time "
                "derivado dos objetivos, e o fechamento da semana anterior.\n"
                "Como usar: revise a proposta de segunda-feira já com a PRÉVIA do foco por área embaixo — cada "
                "objetivo mostra quais áreas o puxam, e cada ação de área diz para qual objetivo contribui (os focos "
                "conversam entre si para chegar no objetivo central). Edite, remova, adicione e confirme — a "
                "confirmação efetiva a decomposição, só para áreas com ALAVANCA REAL (máx. 2 ações/área: o valor é "
                "foco, não lista de tarefas). Cada ação cita os dados que a fundamentam e linka a tela de execução; "
                "a defasagem diz quando cobrar resultado.\n"
                "Fique de olho: (1) objetivo com defasagem longa (churn ~60d) aparece 'em maturação' no fechamento — "
                "não é falha da semana; (2) objetivo recorrente que nunca avança sinaliza gargalo ESTRUTURAL, não "
                "falta de foco; (3) cada gestor vê o próprio foco no topo da sua área; (4) a semana VIRA no domingo: "
                "a proposta nova nasce no domingo (já considerando o que a semana atual entregou — os gaps são "
                "mês-a-data) e traz o resultado da semana anterior no racional do objetivo de mesma métrica.")
        + f"<section><h2>Objetivos da semana de {week.strftime('%d/%m')} {status}</h2>"
        "<p class=secsub>o objetivo central da empresa em cima; abaixo de cada um, as áreas que o puxam — os focos "
        "por área CONVERSAM entre si para chegar no objetivo comum</p>"
        + f"<div class=central>{objs_html}{controles}</div></section>"
        + (f"<section><h2>Foco por área{'' if confirmada else ' — prévia'}</h2>"
           "<p class=secsub>"
           + ("derivado dos objetivos confirmados — " if confirmada else
              "PRÉVIA calculada da proposta acima (será efetivada na confirmação; muda se você editar os objetivos) — ")
           + "só áreas com alavanca real; máx. 2 ações por área; cada ação diz para QUAL objetivo da empresa "
             "contribui, com o dado que a fundamenta, o link de execução e a defasagem esperada</p>"
           + times_html + "</section>" if (objs and times_html) else "")
        + rev_html)
    return HTMLResponse(A._render_hub_page(user, body, active="semana"))


@router.post("/semana/salvar")
def semana_salvar(request: Request, acao: str = Form(...), titulo: str = Form(""),
                  metric: str = Form(""), obj_id: str = Form("")):
    A = _deps()
    s = A._session(request)
    if not s:
        return RedirectResponse("/login", status_code=302)
    user, role = s
    if role != "admin":
        return RedirectResponse("/semana", status_code=302)
    week = _seg()
    with A._conn() as c:
        _ddl(c)
        with c.cursor() as cur:
            if acao == "add" and titulo.strip():
                mb = re.match(r"(B[1-5]):", metric or "")
                tgt = None
                m_num = re.search(r"\+?(\d+)", titulo)
                if m_num and (mb or metric == "leads"):
                    tgt = float(m_num.group(1))
                cur.execute("""INSERT INTO weekly_objectives (week_start, title, metric, target_value,
                                   rationale, source, status)
                               VALUES (%s,%s,%s,%s,'objetivo estratégico adicionado pela gestão','manual','proposto')""",
                            (week, titulo.strip()[:90], metric or None, tgt))
            elif acao == "del" and obj_id:
                cur.execute("DELETE FROM weekly_objectives WHERE id=%s::uuid AND week_start=%s "
                            "AND status='proposto'", (obj_id, week))
            elif acao == "confirmar":
                cur.execute("""UPDATE weekly_objectives SET status='confirmado', confirmed_by=%s,
                                   confirmed_at=now() WHERE week_start=%s AND status='proposto'""", (user, week))
            elif acao == "reabrir":
                cur.execute("UPDATE weekly_objectives SET status='proposto', confirmed_by=NULL, "
                            "confirmed_at=NULL WHERE week_start=%s", (week,))
                cur.execute("DELETE FROM weekly_team_actions WHERE week_start=%s", (week,))
            cur.execute("INSERT INTO audit_log (actor, action, scope) VALUES (%s,%s,%s)",
                        (user, f"semana:{acao}", f"semana/{week}"))
        if acao == "repropor":
            _propor(c, week, force=True)
        if acao in ("confirmar", "decompor"):
            _decompor(c, week)
    return RedirectResponse("/semana", status_code=303)


# ---- endpoints JSON (mesmas funções; integração/automação) ----
def _api_guard(request: Request):
    A = _deps()
    s = A._session(request)
    return s


@router.post("/api/semana/propor")
def api_propor(request: Request):
    s = _api_guard(request)
    if not s or s[1] != "admin":
        return JSONResponse({"error": "não autorizado"}, status_code=403)
    A = _deps()
    with A._conn() as c:
        n = _propor(c, _seg(), force=True)
    return JSONResponse({"propostos": n})


@router.get("/api/semana/objetivos")
def api_objetivos(request: Request, week: str = Query("")):
    s = _api_guard(request)
    if not s:
        return JSONResponse({"error": "não autorizado"}, status_code=403)
    A = _deps()
    w = dt.date.fromisoformat(week) if week else _seg()
    with A._conn() as c:
        return JSONResponse({"week": w.isoformat(), "objetivos": _objetivos(c, w)})


@router.post("/api/semana/objetivos/confirmar")
def api_confirmar(request: Request):
    s = _api_guard(request)
    if not s or s[1] != "admin":
        return JSONResponse({"error": "não autorizado"}, status_code=403)
    A = _deps()
    with A._conn() as c:
        with c.cursor() as cur:
            cur.execute("""UPDATE weekly_objectives SET status='confirmado', confirmed_by=%s,
                               confirmed_at=now() WHERE week_start=%s AND status='proposto'""", (s[0], _seg()))
        n = _decompor(c, _seg())
    return JSONResponse({"acoes_geradas": n})


@router.post("/api/semana/decompor")
def api_decompor(request: Request):
    s = _api_guard(request)
    if not s or s[1] != "admin":
        return JSONResponse({"error": "não autorizado"}, status_code=403)
    A = _deps()
    with A._conn() as c:
        n = _decompor(c, _seg())
    return JSONResponse({"acoes_geradas": n})


@router.get("/api/semana/acoes")
def api_acoes(request: Request, team: str = Query(""), week: str = Query("")):
    s = _api_guard(request)
    if not s:
        return JSONResponse({"error": "não autorizado"}, status_code=403)
    A = _deps()
    w = dt.date.fromisoformat(week) if week else _seg()
    with A._conn() as c:
        acs = _acoes(c, w)
    if team:
        acs = [a for a in acs if a["team"] == team]
    return JSONResponse({"week": w.isoformat(), "acoes": acs})


@router.get("/api/semana/revisao")
def api_revisao(request: Request, week: str = Query("")):
    s = _api_guard(request)
    if not s:
        return JSONResponse({"error": "não autorizado"}, status_code=403)
    A = _deps()
    w = dt.date.fromisoformat(week) if week else _seg() - dt.timedelta(days=7)
    with A._conn() as c:
        return JSONResponse({"week": w.isoformat(), "revisao": _revisar(c, w)})
