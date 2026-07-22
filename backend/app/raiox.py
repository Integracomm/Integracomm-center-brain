"""Raio-X por Bundle — /raiox?b=B2 (Integração Causal #1, Otávio 17/07).

A cadeia COMPLETA de um bundle numa tela só, na ordem do ciclo:
aquisição → qualificação/fechamento → meta × realizado → retenção →
carga operacional → resultado recorrente. É uma view de COMPOSIÇÃO:
consome as mesmas fontes que já alimentam cada área (coorte do Ciclo de
Vida, Ponte PV→Vendas, planilha financeira, cancelamentos, squads),
filtradas pelo bundle — não recalcula régua nenhuma.

Leitura do especialista: heurística SEMPRE (determinística, sem custo);
Claude por cima quando houver orçamento (llm_budget, cache 20h por
bundle, fallback silencioso p/ a heurística) — mesmo padrão do plano de
ação do Growth.
"""
from __future__ import annotations

import datetime as dt
from html import escape

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter()

_BUNDLES = ("TODOS", "B1", "B2", "B3", "B4", "B5")
_MODEL = "claude-sonnet-5"


def _rotulo(b: str) -> str:
    return "a empresa (todos os bundles)" if b == "TODOS" else f"o {b}"

_CACHE_DDL = """CREATE TABLE IF NOT EXISTS raiox_cache (
    bundle     TEXT PRIMARY KEY,
    texto      TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)"""


def _deps():
    from . import api as A
    return A


def _brl(v) -> str:
    return "—" if v is None else f"R$ {v:,.0f}".replace(",", ".")


def _pct(v) -> str:
    return "—" if v is None else f"{v * 100:.0f}%"


# ---------------------------------------------------------------------------
# dados — tudo filtrado pelo bundle, reusando as fontes das áreas
# ---------------------------------------------------------------------------
def _dados_bundle(conn, b: str, janela: int = 120) -> dict:
    import calendar
    import statistics as st

    A = _deps()
    hoje = dt.date.today()
    mes = hoje.replace(day=1)
    frac = hoje.day / calendar.monthrange(hoje.year, hoje.month)[1]
    todos = b == "TODOS"  # visão da EMPRESA: mesma cadeia sem filtro de bundle
    like = "%" if todos else f"{b}%"
    d: dict = {"b": b, "todos": todos, "frac": frac, "janela": janela}

    # ---- 1+4. aquisição e retenção: a MESMA coorte do Ciclo de Vida ----
    from .marketing.ui import _ciclo_coorte
    coorte, gasto, cob = _ciclo_coorte(conn)
    cb = coorte if todos else [r for r in coorte if r["bundle"] == b]
    d["coorte_n"] = len(cb)
    por_canal: dict[str, dict] = {}
    for r in cb:
        x = por_canal.setdefault(r["canal"], {"n": 0, "ativo": 0, "precoce": 0,
                                              "tardio": 0, "mrr": 0.0})
        x["n"] += 1
        x[r["desfecho"]] += 1
        x["mrr"] += r["mrr"]
    for canal, x in por_canal.items():
        cac = None
        if canal in gasto:  # CAC do CANAL (gasto não é separável por bundle)
            d0, g = gasto[canal]
            n_per = sum(1 for r in coorte if r["canal"] == canal and r["won"] >= d0)
            cac = g / n_per if n_per else None
        ret = x["ativo"] / x["n"]
        x["ret"] = ret
        x["prec"] = x["precoce"] / x["n"]
        x["cac"] = cac
        x["cac_aj"] = (cac / ret) if (cac and ret) else None
    d["por_canal"] = dict(sorted(por_canal.items(), key=lambda kv: -kv[1]["n"]))
    d["precoce_pct"] = (sum(1 for r in cb if r["desfecho"] == "precoce") / len(cb)) if cb else None
    d["tardio_pct"] = (sum(1 for r in cb if r["desfecho"] == "tardio") / len(cb)) if cb else None
    d["cobertura"] = cob

    # ---- 2. qualificação → fechamento (Ponte, janela ajustável, por bundle) ----
    with conn.cursor() as cur:
        cur.execute("""
            SELECT d.status,
                   EXTRACT(epoch FROM (t.first_at - d.add_time)) / 60,
                   COALESCE(d.origem, '(vazio)'),
                   COALESCE(d.valor_custom, d.valor)
              FROM mkt_deals_attribution d
              LEFT JOIN sales_first_touch t ON t.deal_id = d.deal_id
             WHERE d.oport_time >= now() - make_interval(days => %s)
               AND upper(COALESCE(d.produto, '')) LIKE %s""", (janela, like))
        oports = cur.fetchall()
    dec = [r for r in oports if r[0] in ("won", "lost")]
    won = [r for r in dec if r[0] == "won"]
    d["oports_n"], d["dec_n"], d["won_n"] = len(oports), len(dec), len(won)
    d["taxa"] = len(won) / len(dec) if dec else None
    d["ticket"] = st.mean([float(r[3]) for r in won if r[3]]) if won else None

    def _tx_seg(cond):
        seg_dec = [r for r in dec if r[1] is not None and cond(r[1])]
        seg_won = [r for r in seg_dec if r[0] == "won"]
        return (len(seg_won) / len(seg_dec) if len(seg_dec) >= 10 else None), len(seg_dec)
    d["tx_sla_ok"], d["n_sla_ok"] = _tx_seg(lambda m: m <= 15)
    d["tx_sla_ruim"], d["n_sla_ruim"] = _tx_seg(lambda m: m > 60)
    por_og: dict[str, list[int]] = {}
    for r in dec:
        t = por_og.setdefault(str(r[2])[:24], [0, 0])
        t[1] += 1
        if r[0] == "won":
            t[0] += 1
    d["ponte_origens"] = sorted(por_og.items(), key=lambda kv: -kv[1][1])[:5]

    # ---- 3. meta × realizado do mês (planilha financeira + Pipedrive) ----
    from .sources import planejamento_financeiro as PF
    pf = PF.carrega()
    d["meta_q"] = d["meta_r"] = None
    if pf:
        iso = f"{mes.year:04d}-{mes.month:02d}"
        if iso in pf["meses"]:
            i = pf["meses"].index(iso)
            if todos:  # visão da empresa: metas TOTAIS da planilha
                d["meta_q"] = PF.linha(pf, "Bookings [Qtde]")[i]
                d["meta_r"] = PF.linha(pf, "Meta Bookings [R$]")[i]
            else:
                d["meta_q"] = PF.linha(pf, f"{b} - Meta: Booking [Qtde]")[i]
                d["meta_r"] = PF.linha(pf, f"{b} - Meta: Booking [R$]")[i]
    with conn.cursor() as cur:
        cur.execute("""SELECT count(*), COALESCE(sum(COALESCE(valor_custom, valor)), 0)
                         FROM mkt_deals_attribution
                        WHERE status='won' AND won_time >= %s
                          AND upper(COALESCE(produto, '')) LIKE %s""",
                    (f"{mes} 00:00-03", like))
        q, r_ = cur.fetchone()
        d["real_q"], d["real_r"] = int(q), float(r_)

    # ---- 4. retenção: base, cancelamentos por mês, motivos ----
    with conn.cursor() as cur:
        if todos:
            cur.execute("SELECT count(*) FROM accounts")
        else:
            cur.execute("SELECT count(*) FROM accounts WHERE substring(name FROM 'B[1-5]') = %s", (b,))
        d["base_contas"] = cur.fetchone()[0]
        cur.execute("""SELECT tipo, mes, plano, equipe, motivo, valor FROM grw_cancelamentos
                        WHERE tipo='cancelamento'""")
        cols = ("tipo", "mes", "plano", "equipe", "motivo", "valor")
        cancs = [dict(zip(cols, r)) for r in cur.fetchall()]
    cancs_b = cancs if todos else [r for r in cancs if A._canc_bundle(r) == b]
    d["canc_total"] = len(cancs_b)
    # cobertura do vínculo booking↔cancelamento NESTE escopo (A2, 17/07): as
    # conclusões de retenção por canal carregam essa incerteza — mostrar no
    # ponto da decisão, não só no rodapé
    d["cov_casados"] = sum(1 for r in cb if r.get("saida"))
    d["cov_total"] = len(cancs_b)
    seis = [(mes - dt.timedelta(days=30 * k)).replace(day=1) for k in range(5, -1, -1)]
    d["canc_meses"] = [(m.strftime("%m/%y"), sum(1 for r in cancs_b if r["mes"] == m),
                        sum(float(r["valor"] or 0) for r in cancs_b if r["mes"] == m)) for m in seis]
    from collections import Counter
    motivos = Counter((r["motivo"] or "").strip()[:60] for r in cancs_b if r["motivo"])
    d["motivos"] = motivos.most_common(3)
    d["canc_sem_motivo"] = sum(1 for r in cancs_b if not r["motivo"])

    # ---- 5. carga operacional: squads que atendem o bundle ----
    try:
        from .sources.clickup_activities import _mirror_clientes
        mirror = _mirror_clientes()
    except Exception:  # noqa: BLE001
        mirror = None
    try:
        from .sources.squads_sheet import squad_teams
        times = squad_teams()
    except Exception:  # noqa: BLE001
        times = {}
    with conn.cursor() as cur:
        cur.execute("""
            SELECT a.name, COALESCE(a.recurring_revenue, 0),
                   EXISTS (SELECT 1 FROM alerts al WHERE al.account_id = a.id AND al.status = 'aberto'),
                   EXISTS (SELECT 1 FROM signal_snapshots ss WHERE ss.account_id = a.id
                            AND ss.signal_key = 'exec_score' AND ss.value_num < 40),
                   substring(a.name FROM 'B[1-5]')
              FROM accounts a""")
        contas_all = cur.fetchall()
    contas_b = contas_all if todos else [r for r in contas_all if r[4] == b]
    todas_sq: dict[str, int] = {}
    sq_b: dict[str, dict] = {}
    for nome, mrr, alerta, execrit, bx in contas_all:
        sq = A._resolve_squad(nome, mirror)
        if sq is None:
            continue
        todas_sq[sq] = todas_sq.get(sq, 0) + 1
        if todos or bx == b:
            x = sq_b.setdefault(sq, {"n": 0, "alerta": 0, "exec": 0, "mrr_risco": 0.0})
            x["n"] += 1
            if alerta:
                x["alerta"] += 1
                x["mrr_risco"] += float(mrr)
            if execrit:
                x["exec"] += 1
    for sq, x in sq_b.items():
        p = len(times.get(sq, []))
        x["pessoas"] = p
        x["cp_geral"] = (todas_sq.get(sq, 0) / p) if p else None
    d["squads"] = dict(sorted(sq_b.items(), key=lambda kv: -kv[1]["n"]))
    d["alertas_b"] = sum(1 for r in contas_b if r[2])
    d["exec_b"] = sum(1 for r in contas_b if r[3])
    d["mrr_risco_b"] = sum(float(r[1]) for r in contas_b if r[2])

    # ---- 6. resultado recorrente: base MRR (≈ cobertura) + entra × sai ----
    com_mrr = [float(r[1]) for r in contas_b if float(r[1]) > 0]
    d["mrr_cnt"], d["mrr_soma"] = len(com_mrr), sum(com_mrr)
    d["mrr_est"] = (sum(com_mrr) / len(com_mrr) * len(contas_b)) if com_mrr and contas_b else None
    d["mrr_exato"] = bool(com_mrr) and len(com_mrr) == len(contas_b)
    with conn.cursor() as cur:
        # régua MRR por LINHA (B1 semestral ÷6) — vale p/ bundle único e p/ TODOS
        cur.execute("""SELECT date_trunc('month', won_time)::date, count(*),
                              COALESCE(sum(CASE WHEN substring(upper(COALESCE(produto, '')) FROM 'B[1-5]') = 'B1'
                                                THEN COALESCE(valor_custom, valor) / 6.0
                                                ELSE COALESCE(valor_custom, valor) END), 0)
                         FROM mkt_deals_attribution
                        WHERE status='won' AND won_time >= %s
                          AND upper(COALESCE(produto, '')) LIKE %s
                        GROUP BY 1""", (seis[0], like))
        entra = {m: (int(n), float(v)) for m, n, v in cur.fetchall()}
    d["entra_sai"] = [(lbl,
                       entra.get(m, (0, 0.0))[0], entra.get(m, (0, 0.0))[1], nc, vc)
                      for (lbl, nc, vc), m in zip(d["canc_meses"], seis)]
    return d


# ---------------------------------------------------------------------------
# leitura do especialista — heurística sempre; Claude por cima com orçamento
# ---------------------------------------------------------------------------
def _fatos(d: dict) -> list[str]:
    """Fatos objetivos da cadeia (alimentam a heurística E o Claude)."""
    b, f = d["b"], []
    if d["meta_q"]:
        pace = d["real_q"] / d["meta_q"]
        f.append(f"Meta do mês: {d['real_q']}/{d['meta_q']:.0f} bookings ({pace * 100:.0f}% da meta "
                 f"com {d['frac'] * 100:.0f}% do mês decorrido) — {_brl(d['real_r'])} de {_brl(d['meta_r'])}.")
    if d["taxa"] is not None:
        f.append(f"Fechamento ({d['janela']}d): {d['won_n']} de {d['dec_n']} oportunidades decididas ({_pct(d['taxa'])}).")
    if d["tx_sla_ok"] is not None and d["tx_sla_ruim"] is not None and d["tx_sla_ok"] > d["tx_sla_ruim"]:
        f.append(f"Oportunidade de lead atendido em ≤15min fecha {_pct(d['tx_sla_ok'])} vs "
                 f"{_pct(d['tx_sla_ruim'])} quando o 1º contato passou de 1h — qualificação pesa.")
    canais = [(c, x) for c, x in d["por_canal"].items() if x["n"] >= 5]
    if canais:
        pior = max(canais, key=lambda kv: kv[1]["prec"])
        melhor = min(canais, key=lambda kv: kv[1]["prec"])
        if pior[1]["prec"] - melhor[1]["prec"] >= 0.15:
            f.append(f"Aquisição: {pior[0]} tem {_pct(pior[1]['prec'])} de churn precoce "
                     f"({pior[1]['n']} clientes) vs {_pct(melhor[1]['prec'])} de {melhor[0]} — "
                     "o canal muda o cliente que entra.")
    if d["precoce_pct"] is not None and d["coorte_n"] >= 8:
        f.append(f"Retenção da coorte: {_pct(d['precoce_pct'])} cancelam em ≤3 meses "
                 f"({d['coorte_n']} clientes rastreados).")
    if d["squads"]:
        top_sq, x = next(iter(d["squads"].items()))
        carga = f" (squad com {x['cp_geral']:.1f} contas/pessoa no total)" if x.get("cp_geral") else ""
        f.append(f"Operação: {top_sq} concentra {x['n']} contas {b}{carga}; "
                 f"{d['exec_b']} conta(s) do bundle com execução crítica e {d['alertas_b']} em alerta "
                 f"({_brl(d['mrr_risco_b'])} de MRR em risco).")
    ult = d["entra_sai"][-2] if len(d["entra_sai"]) >= 2 else None  # último mês FECHADO
    if ult:
        saldo = ult[2] - ult[4]
        f.append(f"Recorrente ({ult[0]}): entrou {_brl(ult[2])} em bookings × saiu {_brl(ult[4])} "
                 f"em cancelamentos — saldo {'positivo' if saldo >= 0 else 'NEGATIVO'} de {_brl(abs(saldo))}.")
    return f


def _leitura_heuristica(d: dict) -> str:
    b = d["b"]
    sujeito = "A empresa" if d.get("todos") else f"O {b}"
    partes = []
    if d["meta_q"]:
        atras = d["real_q"] / d["meta_q"] < d["frac"] * 0.85
        partes.append(f"{sujeito} está {'ATRÁS do ritmo da meta' if atras else 'no ritmo da meta'} "
                      f"({d['real_q']}/{d['meta_q']:.0f} bookings)")
    if d["tx_sla_ok"] is not None and d["tx_sla_ruim"] is not None and d["tx_sla_ok"] - d["tx_sla_ruim"] >= 0.05:
        partes.append(f"a taxa de fechamento dobra quando o lead é atendido rápido ({_pct(d['tx_sla_ok'])} vs "
                      f"{_pct(d['tx_sla_ruim'])}) — priorizar o SLA da Pré-vendas para este bundle")
    canais = [(c, x) for c, x in d["por_canal"].items() if x["n"] >= 5]
    if canais:
        pior = max(canais, key=lambda kv: kv[1]["prec"])
        melhor = min(canais, key=lambda kv: kv[1]["prec"])
        if pior[1]["prec"] - melhor[1]["prec"] >= 0.15:
            partes.append(f"a maior alavanca de retenção é a AQUISIÇÃO: {pior[0]} traz cliente que sai cedo "
                          f"({_pct(pior[1]['prec'])} precoce) enquanto {melhor[0]} retém "
                          f"({_pct(melhor[1]['prec'])} precoce) — migrar mix e endurecer a qualificação do canal fraco")
    if d["squads"]:
        top_sq, x = next(iter(d["squads"].items()))
        if x["exec"] >= 3 or (x.get("cp_geral") or 0) >= 10:
            partes.append(f"e a operação aperta em {top_sq} ({x['n']} contas, "
                          f"{x['exec']} com execução crítica)")
    if not partes:
        return (f"Sem sinal forte na cadeia d{_rotulo(b)} agora — acompanhar o ritmo da meta e a coorte "
                "de retenção conforme a amostra cresce.")
    return f"Cadeia d{_rotulo(b)}: " + "; ".join(partes) + "."


def _insights_areas(d: dict) -> list[tuple[str, str, str, list[str]]]:
    """(área, href, rótulo do link, bullets) — o que cada área leva deste
    bundle (Otávio 20/07). COMPÕE os números já calculados nas seções 1-6;
    nada é recalculado. Área sem sinal forte diz isso explicitamente —
    honestidade vale mais que preencher espaço."""
    from html import escape as esc
    b = d["b"]
    quem = "da empresa" if d.get("todos") else f"do {b}"
    out: list[tuple[str, str, str, list[str]]] = []

    # ---- Marketing: mix de canais e custo ajustado pela retenção ----
    mkt: list[str] = []
    canais = [(c, x) for c, x in d["por_canal"].items() if x["n"] >= 5]
    if canais:
        pior = max(canais, key=lambda kv: kv[1]["prec"])
        melhor = min(canais, key=lambda kv: kv[1]["prec"])
        if pior[1]["prec"] - melhor[1]["prec"] >= 0.15:
            mkt.append(f"<b>{esc(pior[0])}</b> traz cliente {quem} que sai cedo ({_pct(pior[1]['prec'])} "
                       f"de churn precoce, {pior[1]['n']} clientes) vs {_pct(melhor[1]['prec'])} de "
                       f"{esc(melhor[0])} — rever o mix e endurecer a qualificação do canal fraco.")
        com_cac = [(c, x) for c, x in canais if x.get("cac_aj") and x.get("cac")]
        if com_cac:
            caro = max(com_cac, key=lambda kv: kv[1]["cac_aj"])
            if caro[1]["cac"] and caro[1]["cac_aj"] >= caro[1]["cac"] * 1.3:
                mkt.append(f"O churn precoce encarece {esc(caro[0])}: CAC ajustado pela retenção "
                           f"{_brl(caro[1]['cac_aj'])} vs {_brl(caro[1]['cac'])} nominal — o custo real "
                           "do canal é o ajustado.")
    out.append(("Marketing", "/marketing?view=ciclo", "Ciclo de Vida",
                mkt or ["Sem sinal forte nos canais deste recorte (amostras pequenas ou canais parecidos)."]))

    # ---- Pré-vendas: SLA do 1º contato ----
    pv: list[str] = []
    if d["tx_sla_ok"] is not None and d["tx_sla_ruim"] is not None and d["tx_sla_ok"] - d["tx_sla_ruim"] >= 0.05:
        n_ok, n_ruim = d.get("n_sla_ok") or 0, d.get("n_sla_ruim") or 0
        peq = " <span class=note>(amostra pequena)</span>" if min(n_ok, n_ruim) < 20 else ""
        pv.append(f"Oportunidade {quem} atendida em ≤15min fecha {_pct(d['tx_sla_ok'])} vs "
                  f"{_pct(d['tx_sla_ruim'])} quando o 1º contato passa de 1h ({n_ok} × {n_ruim} oportunidades){peq} "
                  "— zerar a fila de 1º contato destes leads primeiro.")
    out.append(("Pré-vendas", "/prevendas?view=speed", "Speed-to-Lead",
                pv or ["SLA sem diferença relevante de fechamento neste recorte — manter a rotina atual."]))

    # ---- Vendas: fechamento e ticket ----
    vd: list[str] = []
    if d["taxa"] is not None:
        peq = " <span class=note>(amostra pequena)</span>" if d["dec_n"] < 15 else ""
        tk = f" · ticket médio {_brl(d['ticket'])}" if d.get("ticket") else ""
        vd.append(f"Fechamento {d['janela']}d {quem}: {_pct(d['taxa'])} ({d['won_n']} de {d['dec_n']} "
                  f"decididas){tk}{peq}.")
    if d["meta_q"]:
        atras = d["real_q"] / d["meta_q"] < d["frac"] * 0.85
        if atras:
            vd.append(f"Mês atual ATRÁS do ritmo da meta ({d['real_q']}/{d['meta_q']:.0f} bookings com "
                      f"{d['frac'] * 100:.0f}% do mês decorrido) — priorizar o pipe deste plano.")
    out.append(("Vendas", "/vendas?view=ponte", "Ponte PV → Vendas",
                vd or ["Sem oportunidades decididas suficientes na janela — sem leitura de fechamento."]))

    # ---- Growth/Assessoria: risco da base ----
    gw: list[str] = []
    if d["alertas_b"]:
        gw.append(f"{d['alertas_b']} conta(s) {quem} em alerta aberto — {_brl(d['mrr_risco_b'])} de MRR "
                  "em risco; a fila com dor dominante está em Contas/Alertas.")
    if d["precoce_pct"] is not None and d["coorte_n"] >= 8:
        gw.append(f"Churn precoce da coorte: {_pct(d['precoce_pct'])} saem em ≤3 meses "
                  f"({d['coorte_n']} clientes rastreados) — onboarding/primeiros 90 dias é o campo de batalha.")
    if d.get("canc_sem_motivo"):
        gw.append(f"{d['canc_sem_motivo']} cancelamento(s) sem motivo preenchido na planilha — sem motivo "
                  "não há aprendizado; cobrar o registro no formalizar.")
    out.append(("Growth / Assessoria", "/growth?view=contas", "Contas",
                gw or ["Base sem alerta aberto neste recorte."]))

    # ---- Operação (squads): concentração e execução ----
    op: list[str] = []
    if d["squads"]:
        top_sq, x = next(iter(d["squads"].items()))
        carga = f", {x['cp_geral']:.1f} contas/pessoa no total" if x.get("cp_geral") else ""
        op.append(f"{esc(top_sq)} concentra {x['n']} conta(s) {quem}{carga}"
                  + (f" — {x['exec']} com execução crítica" if x.get("exec") else "") + ".")
    if d["exec_b"]:
        op.append(f"{d['exec_b']} conta(s) do recorte com execução crítica no ClickUp — fila e prazos "
                  "antes de promessa nova.")
    out.append(("Operação (squads)", "/growth?view=carga", "Análise dos Squads",
                op or ["Sem concentração nem execução crítica relevante no recorte."]))

    # ---- Financeiro: entra × sai ----
    fin: list[str] = []
    ult = d["entra_sai"][-2] if len(d["entra_sai"]) >= 2 else None  # último mês FECHADO
    if ult:
        saldo = ult[2] - ult[4]
        fin.append(f"Último mês fechado ({ult[0]}): entrou {_brl(ult[2])} em bookings × saiu "
                   f"{_brl(ult[4])} em cancelamentos — saldo {'positivo' if saldo >= 0 else '<b>NEGATIVO</b>'} "
                   f"de {_brl(abs(saldo))}.")
    out.append(("Financeiro", "/financeiro?view=receita", "Receita Recorrente",
                fin or ["Sem série de entra×sai fechada para este recorte."]))
    return out


def _leitura_llm(conn, b: str, fatos: list[str]) -> str | None:
    """Claude com guarda de orçamento + cache 20h; None = usar heurística."""
    from .config import get_settings
    s = get_settings()
    if not (s.growth_llm_plans and s.anthropic_api_key):
        return None
    try:
        import anthropic

        from .llm_budget import ensure_budget, record_usage
        with conn.cursor() as cur:
            cur.execute(_CACHE_DDL)
            cur.execute("SELECT texto FROM raiox_cache WHERE bundle=%s "
                        "AND created_at > now() - interval '20 hours'", (b,))
            hit = cur.fetchone()
        if hit:
            return hit[0]
        ensure_budget(conn)
        cli = anthropic.Anthropic(api_key=s.anthropic_api_key, max_retries=0, timeout=25.0)
        msg = cli.messages.create(
            model=_MODEL, max_tokens=500,
            thinking={"type": "disabled"},
            system=("Você é o analista-chefe de operações de uma assessoria de marketplaces. "
                    "Receberá FATOS medidos da cadeia completa de um plano (aquisição→fechamento→"
                    "retenção→operação→receita). Escreva UM parágrafo (máx. 110 palavras, pt-BR, "
                    "tom direto de gestor) que AMARRE a cadeia num diagnóstico causal único e aponte "
                    "A alavanca principal. Use SÓ os números dados; não invente nada; se os fatos "
                    "forem fracos, diga que não há sinal forte."),
            messages=[{"role": "user",
                       "content": (("ESCOPO: EMPRESA TODA (todos os planos)" if b == "TODOS" else f"BUNDLE {b}")
                                   + "\n" + "\n".join(f"- {x}" for x in fatos))}],
        )
        tin = (msg.usage.input_tokens + (msg.usage.cache_read_input_tokens or 0)
               + (msg.usage.cache_creation_input_tokens or 0))
        record_usage(conn, "central:raiox", _MODEL, tin, msg.usage.output_tokens)
        texto = next(bk.text for bk in msg.content if bk.type == "text").strip()
        if texto:
            with conn.cursor() as cur:
                cur.execute("""INSERT INTO raiox_cache (bundle, texto) VALUES (%s, %s)
                               ON CONFLICT (bundle) DO UPDATE SET texto=EXCLUDED.texto,
                                   created_at=now()""", (b, texto))
            conn.commit()
        return texto or None
    except Exception:  # noqa: BLE001 — orçamento/rede/qualquer falha -> heurística
        return None


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------
def _render(d: dict, leitura: str, via_llm: bool, alt_leitura: str = "") -> str:
    from .help_texts import _hint
    b = d["b"]
    _td = ("padding:6px 9px;border-bottom:1px solid var(--border);font-size:var(--fs-sm);"
           "font-variant-numeric:tabular-nums")

    def tbl(ths, linhas):
        h = "".join(f"<th style='text-align:{al};padding:6px 9px;font-size:var(--fs-2xs);"
                    f"color:var(--text-muted);text-transform:uppercase'>{t}</th>" for t, al in ths)
        return (f"<div class=central style='padding:6px 14px 10px;overflow-x:auto'>"
                f"<table style='width:100%;border-collapse:collapse'><tr>{h}</tr>{linhas}</table></div>")

    j = d.get("janela", 120)
    sel = "".join(
        f"<a href='/raiox?b={x}&j={j}' style=\"display:inline-block;padding:7px 16px;border-radius:999px;"
        f"font-weight:600;font-size:var(--fs-sm);margin-right:8px;"
        + ("background:var(--brand);color:var(--brand-ink)" if x == b else
           "background:var(--surface-2);color:var(--text-2);border:1px solid var(--border-strong)")
        + f"\">{'Todos (empresa)' if x == 'TODOS' else x}</a>" for x in _BUNDLES)
    # A1 (17/07): janela do fechamento AJUSTÁVEL — p/ comparar maçã com maçã
    # com a Ponte (que usa o período selecionado lá)
    sel += ("<span style='margin-left:14px;font-size:var(--fs-2xs);color:var(--text-muted)'>janela do fechamento:</span> "
            + " ".join(
                f"<a href='/raiox?b={b}&j={x}' style=\"font-size:var(--fs-xs);padding:4px 10px;border-radius:999px;"
                + ("background:var(--surface-3);color:var(--text);border:1px solid var(--brand)" if x == j else
                   "color:var(--text-muted);border:1px solid var(--border)")
                + f"\">{x}d</a>" for x in (30, 90, 120)))

    ritmo = None
    if d["meta_q"]:
        ritmo = d["real_q"] / d["meta_q"] >= d["frac"] * 0.85
    if d["meta_q"]:
        kpi_meta = (f"<div class=kpi><div class=n style='color:var({'--status-baixo' if ritmo else '--status-critico'})'>"
                    f"{d['real_q']}/{d['meta_q']:.0f}</div><div class=l>bookings × meta do mês</div></div>")
    else:
        kpi_meta = f"<div class=kpi><div class=n>{d['real_q']}</div><div class=l>bookings no mês (sem meta)</div></div>"
    kpis = (
        "<div class=kpis>"
        f"<div class=kpi><div class=n>{d['base_contas']}</div><div class=l>contas ativas monitoradas</div></div>"
        f"<div class=kpi><div class=n>{'≈ ' if not d['mrr_exato'] and d['mrr_est'] else ''}{_brl(d['mrr_est'])}</div>"
        f"<div class=l>MRR da base ({d['mrr_cnt']}/{d['base_contas']} c/ valor)</div></div>"
        + kpi_meta +
        f"<div class=kpi><div class=n>{_pct(d['taxa'])}</div><div class=l>fechamento {d['janela']}d "
        f"({d['won_n']}/{d['dec_n']} decididas)</div>"
        f"<div class=s>oportunidades (Dia Oportunidade) dos últimos {d['janela']} dias, TODAS as origens, "
        "taxa sobre decididas — a Ponte usa o período selecionado lá</div></div>"
        f"<div class=kpi><div class=n style='color:var(--status-critico)'>{_pct(d['precoce_pct'])}</div>"
        f"<div class=l>churn precoce da coorte</div></div>"
        "</div>")

    # 1. aquisição
    rows = ""
    for canal, x in d["por_canal"].items():
        peq = x["n"] < 5
        rows += (f"<tr><td style='{_td}'><b>{escape(canal)}</b></td>"
                 f"<td style='{_td};text-align:right'>{x['n']}</td>"
                 f"<td style='{_td};text-align:right'>{_pct(x['ret'])}</td>"
                 f"<td style='{_td};text-align:right;color:var(--status-critico)'>{_pct(x['prec'])}</td>"
                 f"<td style='{_td};text-align:right'>{_brl(x['cac'])}</td>"
                 f"<td style='{_td};text-align:right'><b>{_brl(x['cac_aj'])}</b></td>"
                 f"<td style='{_td}'>{'<span class=note>amostra pequena</span>' if peq else ''}</td></tr>")
    # A2: incerteza da cobertura JUNTO da conclusão (não só no rodapé)
    cov_c, cov_t = d.get("cov_casados", 0), d.get("cov_total", 0)
    cov_pct = (cov_c / cov_t) if cov_t else None
    cov_grave = cov_pct is not None and cov_pct < 0.4
    cov_nota = ""
    if cov_t:
        cov_nota = (f"<div class='{'warn' if cov_grave else 'note'}' style='margin:6px 0 10px;font-size:var(--fs-xs);"
                    f"{'padding:8px 12px' if cov_grave else ''}'>"
                    f"{'⚠ ' if cov_grave else ''}As conclusões de retenção abaixo se baseiam em <b>{cov_c} de {cov_t}</b> "
                    f"cancelamentos deste escopo vinculados a um booking rastreado ({cov_pct * 100:.0f}%) — os sem "
                    "vínculo (clientes pré-2025) podem alterar o quadro."
                    + (" Cobertura BAIXA: trate como indício, não conclusão." if cov_grave else "")
                    + "</div>")
    s1 = ("<section><h2>1 · Aquisição — de onde vem o cliente deste bundle</h2>"
          "<p class=secsub>coorte completa de clientes fechados (Ciclo de Vida) filtrada pelo bundle · "
          "CAC é do CANAL (o gasto de mídia não separa por plano); CAC ajustado divide pela retenção DO BUNDLE no canal · "
          f"<a href='/marketing?view=ciclo' style='color:var(--brand)'>ver Ciclo de Vida completo →</a></p>"
          + cov_nota
          + _hint("Aquisição do bundle",
                  "O que mostra: por qual canal os clientes DESTE plano chegaram, e o que aconteceu com eles depois.\n"
                  "Como ler: Retidos = seguem ativos. Precoce = cancelaram em até 3 meses. CAC = custo por cliente do canal "
                  "(geral). CAC ajustado = o custo real por cliente que FICA, na retenção deste bundle.\n"
                  "Fique de olho: canal com CAC baixo e churn precoce alto é a ilusão do canal barato — a alavanca de "
                  "retenção deste plano pode estar na porta de ENTRADA, não na entrega.")
          + tbl([("Canal", "left"), ("Clientes", "right"), ("Retidos", "right"), ("Precoce", "right"),
                 ("CAC canal", "right"), ("CAC ajustado", "right"), ("", "left")], rows or "")
          + "</section>")

    # 2. ponte
    rows = ""
    for og, (g, n) in d["ponte_origens"]:
        tx = g / n if n else None
        rows += (f"<tr><td style='{_td}'>{escape(og)}</td>"
                 f"<td style='{_td};text-align:right'>{n}</td>"
                 f"<td style='{_td};text-align:right'>{g}</td>"
                 f"<td style='{_td};text-align:right'><b>{_pct(tx)}</b></td>"
                 f"<td style='{_td}'>{'<span class=note>amostra pequena</span>' if n < 10 else ''}</td></tr>")
    sla_txt = ""
    if d["tx_sla_ok"] is not None or d["tx_sla_ruim"] is not None:
        sla_txt = (f"<div class=sug-item>→ 1º contato em ≤15min fecha <b>{_pct(d['tx_sla_ok'])}</b> "
                   f"({d['n_sla_ok']} decididas) · acima de 1h fecha <b>{_pct(d['tx_sla_ruim'])}</b> "
                   f"({d['n_sla_ruim']} decididas)</div>")
    s2 = (f"<section><h2>2 · Qualificação → Fechamento <span style='font-size:var(--fs-2xs);"
          f"color:var(--text-faint);font-weight:400'>(fechamento {j}d)</span></h2>"
          f"<p class=secsub>oportunidades deste escopo nos últimos {j} dias — TODAS as origens, campo Dia "
          "Oportunidade, taxa sobre decididas (ganhas+perdidas) · a Ponte mostra o 'fechamento no período' "
          "selecionado lá: janelas/universos diferentes dão números diferentes · "
          f"ticket médio dos fechados: <b>{_brl(d['ticket'])}</b> · "
          f"<a href='/vendas?view=ponte' style='color:var(--brand)'>ver Ponte completa →</a></p>"
          + _hint("Qualificação e fechamento do bundle",
                  "O que mostra: das oportunidades deste plano nos últimos 120 dias, quantas viraram contrato — no total, "
                  "por velocidade do 1º contato e por origem do lead.\n"
                  "Como ler: a taxa considera só as já DECIDIDAS (ganhas + perdidas). Se a taxa com atendimento rápido é "
                  "bem maior que com atendimento lento, o gargalo é herdado da fila de Pré-vendas, não do closer.\n"
                  "Fique de olho: origem com muitas oportunidades e taxa baixa consome agenda de closer com lead errado "
                  "para este plano — endurecer o filtro daquela origem.")
          + (f"<div class=card style='margin-bottom:10px'>{sla_txt}"
             "<style>.sug-item{padding:6px 0;font-size:var(--fs-sm);line-height:1.6;color:var(--text-2)}</style></div>"
             if sla_txt else "")
          + tbl([("Origem", "left"), ("Decididas", "right"), ("Fechadas", "right"), ("Taxa", "right"), ("", "left")],
                rows or "")
          + "</section>")

    # 3. meta × realizado
    pace_txt = "—"
    if d["meta_q"]:
        pace_txt = (f"{d['real_q']}/{d['meta_q']:.0f} bookings ({d['real_q'] / d['meta_q'] * 100:.0f}% da meta, "
                    f"{d['frac'] * 100:.0f}% do mês decorrido) · {_brl(d['real_r'])} de {_brl(d['meta_r'])}")
    s3 = ("<section><h2>3 · Meta × realizado do mês</h2>"
          "<p class=secsub>meta da planilha financeira · realizado ao vivo do Pipedrive · "
          f"<a href='/financeiro' style='color:var(--brand)'>ver Financeiro →</a></p>"
          + f"<div class=card><div class=sug-item>→ <b>{pace_txt}</b></div></div></section>")

    # 4. retenção
    rows = ""
    for lbl, n, v in d["canc_meses"]:
        rows += (f"<tr><td style='{_td}'>{lbl}</td><td style='{_td};text-align:right'>{n or ''}</td>"
                 f"<td style='{_td};text-align:right'>{_brl(v) if v else ''}</td></tr>")
    mot = "".join(f"<div class=sug-item>→ <b>{n}×</b> {escape(m)}</div>" for m, n in d["motivos"]) or \
        "<div class=sug-item>→ nenhum motivo registrado para este bundle</div>"
    s4 = ("<section><h2>4 · Retenção — quem sai e por quê</h2>"
          f"<p class=secsub>cancelamentos do bundle (planilhas oficiais) · churn precoce da coorte: <b>{_pct(d['precoce_pct'])}</b> · "
          f"tardio: {_pct(d['tardio_pct'])} · "
          f"<a href='/growth?view=cancelamentos' style='color:var(--brand)'>ver Cancelamentos →</a></p>"
          + _hint("Retenção do bundle",
                  "O que mostra: quantos clientes deste plano cancelaram nos últimos 6 meses (e a receita que saiu junto), "
                  "e os motivos mais registrados.\n"
                  "Como ler: precoce = saiu em até 3 meses (problema de expectativa/onboarding); tardio = saiu depois "
                  "(problema de valor contínuo). O remédio é diferente em cada caso.\n"
                  "Fique de olho: motivo dominante = o playbook prioritário deste plano; cruzar com a seção 1 — se quem "
                  "sai cedo vem de um canal específico, a correção é na aquisição.")
          + tbl([("Mês", "left"), ("Saídas", "right"), ("MRR perdido", "right")], rows)
          + f"<div class=card style='margin-top:10px'>{mot}"
          + (f"<div class=sug-item style='color:var(--text-muted)'>+ {d['canc_sem_motivo']} saída(s) sem motivo registrado</div>"
             if d["canc_sem_motivo"] else "") + "</div></section>")

    # 5. carga
    import re as _re
    rows = ""
    for sq, x in d["squads"].items():
        cp_txt = f"{x['cp_geral']:.1f}" if x.get("cp_geral") else "—"
        chip_div = ""
        if not d["todos"]:
            m_sq = _re.match(r"B[1-5]", sq)
            if m_sq and m_sq.group(0) != b:
                # bundle da CONTA = tag do nome do grupo; squad = espelho da
                # Operação (fonte da verdade) — divergência = realocação real
                # OU tag desatualizada; nos dois casos vale conferir
                chip_div = (" <span class=chip style='--c:var(--status-medio)' "
                            "title='o squad real (espelho da Operação) é de outro bundle — conta realocada "
                            "ou tag do grupo desatualizada; conferir no ClickUp/WhatsApp'>realocada/tag?</span>")
        rows += (f"<tr><td style='{_td}'><b>{escape(sq)}</b>{chip_div}</td>"
                 f"<td style='{_td};text-align:right'>{x['n']}</td>"
                 f"<td style='{_td};text-align:right'>{x['pessoas'] or '—'}</td>"
                 f"<td style='{_td};text-align:right'>{cp_txt}</td>"
                 f"<td style='{_td};text-align:right;color:var(--status-critico)'>{x['exec'] or ''}</td>"
                 f"<td style='{_td};text-align:right'>{x['alerta'] or ''}</td>"
                 f"<td style='{_td};text-align:right'>{_brl(x['mrr_risco']) if x['mrr_risco'] else ''}</td></tr>")
    col_contas = "Contas" if d["todos"] else f"Contas {b}"
    s5 = (f"<section><h2>5 · Carga operacional — quem atende {'a carteira' if d['todos'] else 'este bundle'}</h2>"
          "<p class=secsub>contas por squad REAL (espelho da Operação — quem atende de fato) · o bundle da conta vem da "
          "tag do nome; squad de outro bundle atendendo = conta realocada ou tag desatualizada (selo amarelo) · "
          "contas/pessoa é a carteira TOTAL do squad · "
          f"<a href='/growth?view=carga' style='color:var(--brand)'>ver Análise dos Squads →</a></p>"
          + _hint("Carga operacional do bundle",
                  "O que mostra: em quais squads as contas deste plano estão DE FATO, e como esses times estão de carga "
                  "e de execução.\n"
                  "Como ler: o plano da conta vem da TAG no nome do grupo; o squad que atende vem do ESPELHO da "
                  "Operação, que é a fonte da verdade (tags ficam desatualizadas). Por isso pode aparecer um squad de "
                  "outro bundle atendendo contas deste plano — o selo 'realocada/tag?' marca esses casos: ou a conta "
                  "foi realocada de verdade, ou a tag do grupo precisa de atualização. Contas/pessoa é a carteira TOTAL "
                  "do squad (todos os planos) — contexto de folga/sobrecarga. Exec. crítica e Alertas são só das contas "
                  "deste plano.\n"
                  "Fique de olho: (1) bundle concentrado num squad sobrecarregado é risco composto; (2) muitos selos "
                  "amarelos = higiene de dados — renomear os grupos ou revisar o espelho.")
          + tbl([("Squad", "left"), (col_contas, "right"), ("Pessoas", "right"), ("Contas/pessoa (geral)", "right"),
                 ("Exec. crítica", "right"), ("Em alerta", "right"), ("MRR em risco", "right")], rows or "")
          + "</section>")

    # 6. recorrente
    rows = ""
    for lbl, n_in, v_in, n_out, v_out in d["entra_sai"]:
        saldo = v_in - v_out
        cor = "var(--status-baixo)" if saldo >= 0 else "var(--status-critico)"
        rows += (f"<tr><td style='{_td}'>{lbl}</td>"
                 f"<td style='{_td};text-align:right'>{n_in or ''}</td>"
                 f"<td style='{_td};text-align:right'>{_brl(v_in) if v_in else ''}</td>"
                 f"<td style='{_td};text-align:right'>{n_out or ''}</td>"
                 f"<td style='{_td};text-align:right'>{_brl(v_out) if v_out else ''}</td>"
                 f"<td style='{_td};text-align:right;color:{cor}'><b>{_brl(saldo)}</b></td></tr>")
    s6 = ("<section><h2>6 · Resultado recorrente — o bundle se paga?</h2>"
          "<p class=secsub>receita nova (bookings, régua MRR: B1÷6) × receita perdida (cancelamentos) mês a mês · "
          f"<a href='/financeiro?view=receita' style='color:var(--brand)'>ver Receita Recorrente →</a></p>"
          + _hint("Resultado recorrente do bundle",
                  "O que mostra: o que ENTRA de receita nova deste plano contra o que SAI por cancelamento, mês a mês.\n"
                  "Como ler: saldo verde = o plano cresce a base recorrente; vermelho = a torneira enche menos do que o "
                  "ralo esvazia. O mês corrente ainda está em andamento.\n"
                  "Fique de olho: saldo negativo recorrente com meta de vendas batida = o problema não é vender, é "
                  "reter — a alavanca está nas seções 1 e 4, não em mais verba de mídia.")
          + tbl([("Mês", "left"), ("Bookings", "right"), ("Entra (MRR)", "right"),
                 ("Saídas", "right"), ("Sai (MRR)", "right"), ("Saldo", "right")], rows)
          + "</section>")

    # 7. o que cada área leva (Otávio 20/07): os MESMOS elos das seções 1-6,
    # recortados pela ÁREA que age sobre eles — cada card com link rotulado
    area_cards = ""
    for titulo_a, href, rot_link, bullets in _insights_areas(d):
        bl = "".join(f"<div class=sug-item>→ {t}</div>" for t in bullets)
        area_cards += (f"<div class=card style='flex:1 1 320px;min-width:290px'>"
                       f"<div style='display:flex;align-items:baseline;gap:10px;margin-bottom:4px'>"
                       f"<span style='font-weight:700;font-size:var(--fs-md)'>{titulo_a}</span>"
                       f"<a href='{href}' style='font-size:var(--fs-2xs);color:var(--brand);"
                       f"font-weight:600;text-decoration:none'>{rot_link} →</a></div>{bl}</div>")
    s7 = ("<section><h2>7 · O que cada área leva deste raio-x</h2>"
          "<p class=secsub>os mesmos elos das seções acima, recortados pela área que age sobre eles — "
          "nada novo é calculado; é o insight de cada time para a rotina da semana</p>"
          + _hint("Insights por área",
                  "O que mostra: a cadeia deste plano fatiada pela ÁREA responsável — o que Marketing, "
                  "Pré-vendas, Vendas, Growth, Operação e Financeiro levam deste raio-x.\n"
                  "Como ler: cada card traz 1-3 achados COM número e um link rotulado para a tela da área "
                  "onde o detalhe mora. Área sem sinal forte diz isso explicitamente — é informação, "
                  "não espaço vazio.\n"
                  "Fique de olho: os achados são os mesmos das seções 1-6 (nada é recalculado); se um "
                  "número parecer diferente do da tela da área, confira o filtro de bundle e a janela — "
                  "o raio-x recorta pelo plano selecionado.")
          + f"<div style='display:flex;gap:12px;flex-wrap:wrap;align-items:stretch'>{area_cards}</div></section>")

    # A3 (17/07): a leitura é HIPÓTESE bem-informada, não veredito — título
    # explícito, nota de correlação≠causa, hipótese alternativa e aviso com peso
    titulo_l = ("Hipótese principal (gerada por IA)" if via_llm
                else "Hipótese principal (regras determinísticas)")
    alt_html = ""
    if via_llm and alt_leitura:
        alt_html = (f"<div class=sug-item style='margin-top:8px;color:var(--text-muted)'>"
                    f"<b>Outra leitura possível</b> (heurística, das mesmas evidências): {escape(alt_leitura)}</div>")
    aviso = ("<div class=warn style='margin-top:10px;font-size:var(--fs-sm)'>"
             "⚠ <b>Associação observada, não causa comprovada</b> — os elos (ex.: SLA×fechamento, canal×churn) são "
             "correlações do histórico. Confira os números das seções abaixo e teste em pequena escala antes de "
             "realocar orçamento grande.</div>")
    return (
        f"<h1>Raio-X por Bundle</h1>"
        "<p class=sub>a cadeia completa do plano numa tela só: aquisição → qualificação → meta → retenção → "
        "operação → receita recorrente. Compõe as mesmas réguas das áreas, filtradas pelo bundle — nada é recalculado.</p>"
        f"<div style='margin:16px 0 4px'>{sel}</div>"
        + kpis +
        f"<section><h2>{titulo_l}</h2>"
        "<p class=secsub>síntese dos elos medidos acima — hipótese para investigar, não conclusão fechada</p>"
        f"<div class=central><div class=sug-item style='font-size:var(--fs-md);line-height:1.65'>→ {escape(leitura)}</div>"
        + alt_html + aviso + "</div></section>"
        + s1 + s2 + s3 + s4 + s5 + s6 + s7 +
        f"<p class=note style='margin-top:14px'>Cobertura do vínculo aquisição↔retenção: "
        f"{d['cobertura']['canc_casados']}/{d['cobertura']['n_cancs']} cancelamentos casados com um booking rastreado. "
        "Onde a amostra do bundle é pequena, a tabela avisa — não conclua por meia dúzia de casos.</p>")


def mini_cards_dados(conn, coorte: list[dict]) -> list[dict]:
    """Raio-X COMPACTO p/ a Visão Central (Cockpit, 17/07) em DADOS: um item por
    bundle com bookings×meta do mês e churn precoce da coorte — MESMAS fontes e
    janelas das seções 3 e 4 do Raio-X completo (nada recalculado com outra
    régua). O bundle mais fora do ritmo vem com `pior=True`.

    Separado do HTML em 22/07 para a Central do SPA, que não tinha este bloco."""
    import calendar
    from .sources import planejamento_financeiro as PF
    hoje = dt.date.today()
    mes = hoje.replace(day=1)
    frac = hoje.day / calendar.monthrange(hoje.year, hoje.month)[1]
    pf = PF.carrega()
    iso = f"{mes.year:04d}-{mes.month:02d}"
    i_pf = pf["meses"].index(iso) if pf and iso in pf["meses"] else None
    with conn.cursor() as cur:
        cur.execute("""SELECT substring(upper(COALESCE(produto, '')) FROM 'B[1-5]'), count(*)
                         FROM mkt_deals_attribution
                        WHERE status='won' AND won_time >= %s GROUP BY 1""", (f"{mes} 00:00-03",))
        reais = {b_: int(n) for b_, n in cur.fetchall() if b_}
    cards, ratios = [], {}
    for b_ in ("B1", "B2", "B3", "B4", "B5"):
        meta_q = PF.linha(pf, f"{b_} - Meta: Booking [Qtde]")[i_pf] if i_pf is not None else None
        real = reais.get(b_, 0)
        cb = [r for r in coorte if r["bundle"] == b_]
        # coorte pequena (<8) NÃO vira número: churn de 3 clientes é ruído
        prec = (sum(1 for r in cb if r["desfecho"] == "precoce") / len(cb)) if len(cb) >= 8 else None
        ratio = (real / meta_q / frac) if (meta_q and frac) else None
        if ratio is not None:
            ratios[b_] = ratio
        cards.append({"bundle": b_, "meta": (float(meta_q) if meta_q else None),
                      "bookings": real, "churn_precoce": prec, "ratio": ratio,
                      "nivel": ("semdados" if ratio is None else
                                "baixo" if ratio >= 0.85 else
                                "medio" if ratio >= 0.6 else "critico")})
    pior = min(ratios, key=ratios.get) if ratios else None
    for c in cards:
        c["pior"] = (c["bundle"] == pior)
    return cards


def mini_cards_html(conn, coorte: list[dict]) -> str:
    """A seção do Raio-X compacto na Central HTML — formata `mini_cards_dados`."""
    from .help_texts import _hint
    out = ""
    for c in mini_cards_dados(conn, coorte):
        b_, meta_q, real, prec = c["bundle"], c["meta"], c["bookings"], c["churn_precoce"]
        cor = f"--status-{c['nivel']}"
        borda = ("border:1px solid var(--status-critico);box-shadow:inset 3px 0 0 var(--status-critico)"
                 if c["pior"] else "border:1px solid var(--border-mid)")
        selo_pior = ("<span class=chip style='--c:var(--status-critico)'>mais fora da meta</span>"
                     if c["pior"] else "")
        bk_txt = f"{real}/{meta_q:.0f}" if meta_q else f"{real}"
        prec_txt = (f"{prec * 100:.0f}% churn precoce" if prec is not None
                    else "coorte pequena p/ churn")
        out += (
            f"<a href='/raiox?b={b_}' style=\"display:block;background:var(--surface-1);{borda};"
            f"border-radius:var(--radius-md);padding:13px 15px;text-decoration:none;color:inherit\">"
            f"<div style='display:flex;justify-content:space-between;align-items:baseline'>"
            f"<b style='font-family:var(--font-display);font-size:15px'>{b_}</b>{selo_pior}</div>"
            f"<div style='font-family:var(--font-display);font-weight:700;font-size:21px;margin-top:6px;"
            f"color:var({cor})'>{bk_txt}</div>"
            f"<div style='font-size:var(--fs-2xs);color:var(--text-muted);text-transform:uppercase;"
            f"letter-spacing:var(--tracking-label)'>bookings × meta</div>"
            f"<div style='font-size:var(--fs-xs);color:var(--text-muted);margin-top:5px'>{prec_txt}</div></a>")
    return (
        "<section><h2>Raio-X compacto por bundle</h2>"
        "<p class=secsub>o resumo do resumo: bookings × meta do mês (cor pelo ritmo) e churn precoce da coorte — "
        "clique num bundle para abrir a cadeia completa · "
        "<a href='/raiox' style='color:var(--brand)'>visão da empresa toda →</a></p>"
        + _hint("Raio-X compacto por bundle",
                "O que mostra: de relance, qual plano está sangrando — bookings contra a meta do mês (a cor segue o "
                "ritmo: verde = no ritmo, amarelo = atrás, vermelho = bem atrás) e o churn precoce da coorte de cada "
                "bundle.\n"
                "Como ler: são os MESMOS números do Raio-X completo (mesma fonte, mesma janela) — o card é só a "
                "porta de entrada. O bundle mais fora do ritmo vem destacado em vermelho.\n"
                "Fique de olho: bookings no ritmo com churn precoce alto = vender mais não resolve — a alavanca está "
                "na aquisição/retenção daquele plano (abra o Raio-X e leia a seção 1 e 4).")
        + "<div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px'>"
        + out + "</div></section>")


# ---------------------------------------------------------------------------
# Endpoint JSON do redesenho (Lote 5, 22/07) — EMBRULHA _dados_bundle (que já
# era puro) + a mesma leitura/insights da tela. Nenhuma régua recalculada.
# ---------------------------------------------------------------------------
def _json_safe(v):
    """dict/list/tupla com date/Decimal -> JSON. Mantém a ESTRUTURA do compute."""
    import decimal
    if isinstance(v, dict):
        return {str(k): _json_safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_json_safe(x) for x in v]
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    if isinstance(v, decimal.Decimal):
        return float(v)
    return v


def _sem_tags(s: str) -> str:
    """Os bullets de _insights_areas trazem <b>/<span class=note> (nasceram p/
    HTML). O SPA recebe TEXTO — o conteúdo é o mesmo, só sem ênfase visual."""
    import re as _re
    return _re.sub(r"<[^>]+>", "", s).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


@router.get("/api/raiox")
def api_raiox(request: Request, b: str = Query("TODOS"), j: int = Query(120)):
    A = _deps()
    A._require_api(request)
    if b not in _BUNDLES:
        b = "TODOS"
    if j not in (30, 90, 120):
        j = 120
    with A._conn() as c:
        d = _dados_bundle(c, b, j)
        fatos = _fatos(d)
        heur = _leitura_heuristica(d)
        llm = _leitura_llm(c, b, fatos)
        areas = [{"area": a, "href": href, "link": lbl, "bullets": [_sem_tags(x) for x in bl]}
                 for a, href, lbl, bl in _insights_areas(d)]
    return {"bundle": b, "rotulo": _rotulo(b), "janela": j,
            "bundles": list(_BUNDLES), "janelas": [30, 90, 120],
            "dados": _json_safe(d), "fatos": fatos,
            "leitura": {"texto": llm or heur, "via_llm": bool(llm),
                        "alternativa": heur if llm else None,
                        "fonte": "Claude (cache 20h)" if llm else "regras determinísticas"},
            "areas": areas}


@router.get("/raiox", response_class=HTMLResponse)
def raiox(request: Request, b: str = Query("TODOS"), j: int = Query(120)):
    A = _deps()
    s = A._session(request)
    if not s:
        return RedirectResponse("/login", status_code=302)
    user, _role = s
    b = b.upper()
    if b not in _BUNDLES:
        b = "TODOS"
    if j not in (30, 90, 120):
        j = 120
    # redesenho: /raiox é rota própria (sem ?view=) — usa o MESMO chaveamento
    # das áreas, com a view sintética "visao" (env SPA_RAIOX_VIEWS=visao)
    from . import spa as _spa_mod
    _r = _spa_mod.view_response(request, "raiox", "visao")
    if _r is not None:
        return _r
    with A._conn() as c:
        with c.cursor() as cur:
            cur.execute("INSERT INTO audit_log (actor, action, scope) VALUES (%s,'view',%s)",
                        (user, f"raiox/{b}"))
        d = _dados_bundle(c, b, janela=j)
        fatos = _fatos(d)
        # leitura via IA só na janela padrão (cache por bundle; janelas curtas
        # usam a heurística p/ não multiplicar chamadas)
        llm = _leitura_llm(c, b, fatos) if (fatos and j == 120) else None
    heur = _leitura_heuristica(d)
    leitura = llm or heur
    return HTMLResponse(A._render_hub_page(
        user, _render(d, leitura, via_llm=bool(llm), alt_leitura=heur if llm else ""), active="raiox"))
