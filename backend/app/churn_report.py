"""Relatório de CHURN POR BUNDLE — aba Relatórios do Growth (Otávio 20/07/26).

Produtização da análise do caso B3: para um bundle e uma janela de meses,
monta o dossiê apresentável (imprimível/PDF) com:
  1. o número em contexto (série mensal, taxa da janela vs média histórica);
  2. padrão de RELACIONAMENTO conduzido pela equipe no WhatsApp (janela de
     45d antes do pedido de cada conta vs controle saudável do bundle);
  3. padrão de ENTREGA (espelho ClickUp: 30d pré-pedido vs média da conta);
  4. casos um a um (planilha + score/drivers/alertas/notas + métricas);
  5. aquisição por canal (reuso do Raio-X — nada recalculado);
  6. lacunas de dado e recomendações (regras determinísticas, rotuladas).

Regras de plataforma: gateway WhatsApp oscila → TODO acesso tem orçamento de
tempo; o que não coube vira "análise parcial" marcada (nunca trava a página).
Cache de 20h por (bundle, meses) — primeira geração é lenta, repetição é
instantânea; botão Regerar força. ZERO chamadas ao Pipedrive.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import statistics as stats
import threading
import time
from collections import Counter
from html import escape

import httpx
from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

router = APIRouter()

_JANELA_ZAP_D = 45      # dias de mensagens antes do pedido
_PRE_ENTREGA_D = 30     # janela de entregas pré-pedido
_ZAP_CONTA_S = 25       # orçamento por conta no gateway
_ZAP_TOTAL_S = 75       # orçamento global da parte de mensagens
_CONTROLE_N = 8

_DDL = """
CREATE TABLE IF NOT EXISTS churn_reports (
    bundle     TEXT NOT NULL,
    meses      INT  NOT NULL,
    payload    JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (bundle, meses)
);
"""


def _deps():
    from . import api as A
    return A


def _brl(v) -> str:
    if v is None:
        return "—"
    return ("R$ " + f"{float(v):,.0f}").replace(",", ".")


def _med(vals, nd=1):
    vs = [v for v in vals if v is not None]
    return round(stats.median(vs), nd) if vs else None


# ---------------------------------------------------------------------------
# coleta
# ---------------------------------------------------------------------------
def _grupos_por_norm() -> dict[str, str]:
    """nome normalizado -> id interno do grupo (cache local wa_groups.csv)."""
    import csv
    from pathlib import Path

    from .sources.nps_sheets import norm_account
    out: dict[str, str] = {}
    p = Path(__file__).resolve().parents[2] / "data" / "wa_groups.csv"
    if p.exists():
        with p.open(encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                out[norm_account(r.get("name") or "")] = r["id"]
    return out


_tl = threading.local()


def _reader():
    from .sources.whatsapp import WhatsAppReader
    if not hasattr(_tl, "rd"):
        _tl.rd = WhatsAppReader(os.environ["WHATSAPP_READ_API_URL"],
                                os.environ["WHATSAPP_READ_API_KEY"],
                                client=httpx.Client(timeout=20.0))
    return _tl.rd


def _zap(gid: str, pedido: dt.date, orcamento_s: float) -> dict | None:
    """Métricas do relacionamento na janela pré-pedido. None = sem base."""
    from .agents.growth.collectors import _is_team
    t0 = time.monotonic()
    fim = dt.datetime.combine(pedido, dt.time(0), tzinfo=dt.timezone.utc)
    ini = fim - dt.timedelta(days=_JANELA_ZAP_D)
    msgs = []
    for m in _reader().iter_messages(group_id=gid, window_start=ini, order="desc"):
        if time.monotonic() - t0 > orcamento_s:
            break
        if m.received_at and ini <= m.received_at < fim:
            msgs.append(m)
    msgs.sort(key=lambda m: m.received_at)
    if not msgs:
        return None
    eq = [m for m in msgs if _is_team(m.sender_name)]
    cl = [m for m in msgs if not _is_team(m.sender_name)]
    resp_h, sem24 = [], 0
    for m in cl:
        nxt = next((e for e in eq if e.received_at > m.received_at), None)
        if nxt:
            h = (nxt.received_at - m.received_at).total_seconds() / 3600
            if h <= 72:
                resp_h.append(h)
            if h > 24:
                sem24 += 1
        else:
            sem24 += 1
    por_dia: dict[dt.date, bool] = {}
    for m in msgs:
        por_dia.setdefault(m.received_at.date(), _is_team(m.sender_name))
    eq_ts = [ini] + [m.received_at for m in eq] + [fim]
    return {"eq_sem": round(len(eq) / (_JANELA_ZAP_D / 7), 1),
            "cl_sem": round(len(cl) / (_JANELA_ZAP_D / 7), 1),
            "resp_med_h": _med(resp_h),
            "pct_sem24": round(sem24 / len(cl) * 100) if cl else None,
            "pct_eq_inicia": round(sum(por_dia.values()) / len(por_dia) * 100) if por_dia else None,
            "max_gap_eq_d": max((y - x).days for x, y in zip(eq_ts, eq_ts[1:]))}


def _entregas(nome_conta: str, pedido: dt.date) -> dict | None:
    """Entregas do espelho: 30d pré-pedido vs média histórica DA conta."""
    from .sources.clickup_activities import _mirror_clientes, _mirror_creds
    from .sources.nps_sheets import norm_account
    cli = _mirror_clientes().get(norm_account(nome_conta))
    if not cli:
        return None
    base, anon = _mirror_creds()
    with httpx.Client(timeout=45.0) as http:
        r = http.get(f"{base}/subtarefas",
                     params={"select": "data_conclusao", "cliente_id": f"eq.{cli['id']}",
                             "data_conclusao": "not.is.null", "limit": "2000"},
                     headers={"apikey": anon, "Authorization": f"Bearer {anon}"})
        r.raise_for_status()
        datas = sorted(x["data_conclusao"][:10] for x in r.json() if x.get("data_conclusao"))
    ped = pedido.isoformat()
    corte30 = (pedido - dt.timedelta(days=_PRE_ENTREGA_D)).isoformat()
    e30 = sum(1 for d0 in datas if corte30 <= d0 < ped)
    hist = [d0 for d0 in datas if d0 < corte30]
    media = None
    if hist:
        span_m = max(1.0, (pedido - dt.date.fromisoformat(hist[0])).days / 30 - 1)
        media = round(len(hist) / span_m, 1)
    antes = [d0 for d0 in datas if d0 < ped]
    return {"e30": e30, "media_mes": media, "total": len(datas),
            "dias_ult": (pedido - dt.date.fromisoformat(antes[-1])).days if antes else None}


def build_churn_report(conn, bundle: str, meses: int = 3) -> dict:
    """Payload completo do relatório (JSON-able). Lento na 1ª vez (gateway)."""
    A = _deps()
    from .sources.nps_sheets import norm_account
    hoje = dt.date.today()
    ini_janela = (hoje.replace(day=1) - dt.timedelta(days=31 * (meses - 1))).replace(day=1)

    with conn.cursor() as cur:
        cur.execute("""SELECT tipo, mes, cliente, meses, valor, plano, equipe, situacao, motivo
                         FROM grw_cancelamentos WHERE tipo IN ('cancelamento','tratativa')
                        ORDER BY mes""")
        cols = [d[0] for d in cur.description]
        todos = [dict(zip(cols, r)) for r in cur.fetchall()]
        cur.execute("SELECT count(*) FROM accounts WHERE name LIKE %s", (f"%{bundle}%",))
        base_atual = cur.fetchone()[0]
        cur.execute("SELECT id, name FROM accounts WHERE name LIKE %s", (f"%{bundle}%",))
        contas_b = [{"id": str(i), "name": n} for i, n in cur.fetchall()]

    do_b = [r for r in todos if A._canc_bundle(r) == bundle]
    canc_hist = [r for r in do_b if r["tipo"] == "cancelamento"]
    serie = Counter(r["mes"].strftime("%m/%Y") for r in canc_hist)
    n_meses_hist = max(1, len({r["mes"] for r in canc_hist}))
    tx_hist = (len(canc_hist) / n_meses_hist / base_atual * 100) if base_atual else None

    janela = [r for r in do_b if r["mes"] >= ini_janela]
    canc_jan = [r for r in janela if r["tipo"] == "cancelamento"]
    n_meses_jan = max(1, len({r["mes"] for r in canc_jan})) if canc_jan else 1
    tx_jan = (len(canc_jan) / n_meses_jan / base_atual * 100) if base_atual else None
    mrr_perdido = sum(float(r["valor"] or 0) for r in canc_jan)

    # ---- casos: 1 por cliente (registro mais recente ganha) ----
    por_cliente: dict[str, dict] = {}
    for r in janela:
        k = norm_account(r["cliente"])
        cur_r = por_cliente.get(k)
        if cur_r is None or r["tipo"] == "cancelamento" or r["mes"] > cur_r["mes"]:
            por_cliente[k] = r
    conta_por_norm = {norm_account(a["name"]): a for a in contas_b}
    grupos = _grupos_por_norm()

    casos: list[dict] = []
    with conn.cursor() as cur:
        for k, r in por_cliente.items():
            acc = conta_por_norm.get(k) or next(
                (a for kk, a in conta_por_norm.items() if len(k) >= 6 and (k in kk or kk in k)), None)
            caso = {"cliente": r["cliente"], "tipo": r["tipo"], "mes": r["mes"].strftime("%m/%Y"),
                    "meses_casa": float(r["meses"]) if r["meses"] is not None else None,
                    "valor": float(r["valor"]) if r["valor"] is not None else None,
                    "plano": r["plano"], "equipe": r["equipe"], "situacao": r["situacao"],
                    "motivo": r["motivo"], "pedido": None, "score": None, "band": None,
                    "stage": None, "drivers": [], "alertas": 0, "notas": [],
                    "zap": None, "entregas": None, "sem_conta": acc is None}
            if acc:
                cur.execute("""SELECT score, risk_band, stage FROM scores
                                WHERE account_id=%s ORDER BY computed_at DESC LIMIT 1""", (acc["id"],))
                s = cur.fetchone()
                if s:
                    caso["score"], caso["band"], caso["stage"] = float(s[0]), s[1], s[2]
                cur.execute("""SELECT sr.text FROM scores sc JOIN score_reasons sr ON sr.score_id=sc.id
                                WHERE sc.account_id=%s ORDER BY sc.computed_at DESC, sr.weight DESC LIMIT 3""",
                            (acc["id"],))
                caso["drivers"] = [x[0] for x in cur.fetchall()]
                cur.execute("SELECT count(*) FROM alerts WHERE account_id=%s", (acc["id"],))
                caso["alertas"] = cur.fetchone()[0]
                cur.execute("""SELECT created_at::date, left(text,160) FROM case_updates
                                WHERE account_id=%s ORDER BY created_at""", (acc["id"],))
                caso["notas"] = [f"{d0}: {t}" for d0, t in cur.fetchall()]
                m = next((re.search(r"em (\d{2})-(\d{2})-(\d{4})", n) for n in caso["notas"]
                          if "verbalizou pedido" in n and re.search(r"em (\d{2})-(\d{2})-(\d{4})", n)), None)
                caso["pedido"] = (dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
                                  if m else r["mes"].isoformat())
                caso["_gid"] = grupos.get(norm_account(acc["name"]))
                caso["_nome_conta"] = acc["name"]
            casos.append(caso)
    casos.sort(key=lambda x: (x["tipo"] != "cancelamento", x["mes"]))

    # ---- WhatsApp + entregas (orçamento global; o que não coube = parcial) ----
    from concurrent.futures import ThreadPoolExecutor
    t0 = time.monotonic()
    zap_pulados = 0

    def coleta(caso):
        nonlocal zap_pulados
        ped = dt.date.fromisoformat(caso["pedido"]) if caso["pedido"] else hoje
        if caso.get("_nome_conta"):
            try:
                caso["entregas"] = _entregas(caso["_nome_conta"], ped)
            except Exception:  # noqa: BLE001 — espelho fora não derruba o relatório
                pass
        if caso.get("_gid") and time.monotonic() - t0 < _ZAP_TOTAL_S:
            try:
                caso["zap"] = _zap(caso["_gid"], ped, _ZAP_CONTA_S)
            except Exception:  # noqa: BLE001 — gateway oscilando = análise parcial
                caso["zap"] = None
        elif caso.get("_gid"):
            zap_pulados += 1
        caso.pop("_gid", None)
        caso.pop("_nome_conta", None)

    with ThreadPoolExecutor(max_workers=3) as ex:
        list(ex.map(coleta, casos))

    # ---- controle: contas saudáveis do bundle (sem caso na janela) ----
    coorte_norms = set(por_cliente)
    ctl = [a for a in contas_b
           if norm_account(a["name"]) not in coorte_norms and grupos.get(norm_account(a["name"]))]
    controle: list[dict] = []
    for a in ctl[:_CONTROLE_N]:
        item = {"zap": None, "entregas": None}
        if time.monotonic() - t0 < _ZAP_TOTAL_S * 2:  # controle tem orçamento próprio
            try:
                item["zap"] = _zap(grupos[norm_account(a["name"])], hoje, _ZAP_CONTA_S)
            except Exception:  # noqa: BLE001
                pass
        try:
            item["entregas"] = _entregas(a["name"], hoje)
        except Exception:  # noqa: BLE001
            pass
        controle.append(item)

    def agg(itens):
        zs = [i["zap"] for i in itens if i.get("zap")]
        return {"n": len(zs),
                "eq_sem": _med([z["eq_sem"] for z in zs]), "cl_sem": _med([z["cl_sem"] for z in zs]),
                "resp_med_h": _med([z["resp_med_h"] for z in zs]),
                "pct_sem24": _med([z["pct_sem24"] for z in zs], 0),
                "pct_eq_inicia": _med([z["pct_eq_inicia"] for z in zs], 0),
                "max_gap_eq_d": _med([z["max_gap_eq_d"] for z in zs], 0)}

    # ---- aquisição por canal: reuso direto do Raio-X (nada recalculado) ----
    canal = []
    try:
        from .raiox import _dados_bundle
        dd = _dados_bundle(conn, bundle)
        canal = [{"canal": c, "n": x["n"], "prec": round(x["prec"] * 100),
                  "cac": x.get("cac"), "cac_aj": x.get("cac_aj")}
                 for c, x in dd["por_canal"].items() if x["n"] >= 5]
    except Exception:  # noqa: BLE001 — seção opcional
        pass

    sem_motivo = sum(1 for r in canc_jan if not (r["motivo"] or "").strip())
    return {"bundle": bundle, "meses": meses, "gerado_em": dt.datetime.now().isoformat(),
            "base_atual": base_atual, "serie_mensal": dict(serie),
            "janela": {"ini": ini_janela.isoformat(), "cancelados": len(canc_jan),
                       "tratativas": len(janela) - len(canc_jan), "mrr_perdido": mrr_perdido,
                       "taxa_mes_pct": round(tx_jan, 1) if tx_jan is not None else None},
            "taxa_hist_pct": round(tx_hist, 1) if tx_hist is not None else None,
            "casos": casos, "comparativo": {"coorte": agg(casos), "controle": agg(controle)},
            "controle_entregas": _med([i["entregas"]["e30"] for i in controle if i.get("entregas")], 0),
            "canal": canal, "lacunas": {"sem_motivo": sem_motivo},
            "zap_pulados": zap_pulados}


# ---------------------------------------------------------------------------
# cache + endpoints
# ---------------------------------------------------------------------------
def _cached_report(conn, bundle: str, meses: int, regen: bool) -> dict:
    with conn.cursor() as cur:
        cur.execute(_DDL)
        if not regen:
            cur.execute("""SELECT payload, created_at FROM churn_reports
                            WHERE bundle=%s AND meses=%s
                              AND created_at > now() - interval '20 hours'""", (bundle, meses))
            hit = cur.fetchone()
            if hit:
                p = hit[0]
                p["_cache_de"] = hit[1].isoformat()
                return p
    payload = build_churn_report(conn, bundle, meses)
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO churn_reports (bundle, meses, payload) VALUES (%s,%s,%s)
                       ON CONFLICT (bundle, meses) DO UPDATE SET payload=EXCLUDED.payload,
                           created_at=now()""", (bundle, meses, json.dumps(payload, ensure_ascii=False)))
    return payload


_STAGE_PT = {"saudavel": "saudável", "desengajamento_inicial": "desengajamento inicial",
             "insatisfacao_latente": "insatisfação latente", "insatisfacao_ativa": "insatisfação ATIVA",
             "intencao_de_saida": "intenção de saída"}


def _render_fragment(p: dict) -> str:
    """Corpo imprimível do relatório (o shell injeta e imprime)."""
    b = p["bundle"]
    j = p["janela"]
    comp_c, comp_k = p["comparativo"]["coorte"], p["comparativo"]["controle"]

    kpis = (f"<div class='kpis'>"
            f"<div class='kpi'><div class='n'>{j['cancelados']}</div><div class='l'>cancelamentos na janela</div></div>"
            f"<div class='kpi'><div class='n'>{j['tratativas']}</div><div class='l'>tratativas na janela</div></div>"
            f"<div class='kpi'><div class='n'>{j['taxa_mes_pct'] if j['taxa_mes_pct'] is not None else '—'}%/mês</div>"
            f"<div class='l'>taxa da janela (base {p['base_atual']})</div></div>"
            f"<div class='kpi'><div class='n'>{p['taxa_hist_pct'] if p['taxa_hist_pct'] is not None else '—'}%/mês</div>"
            f"<div class='l'>média histórica do {b}</div></div>"
            f"<div class='kpi'><div class='n'>{_brl(j['mrr_perdido'])}</div><div class='l'>MRR perdido (janela)</div></div>"
            f"</div>")

    serie = "".join(f"<tr><td>{m}</td><td class='num'>{n}</td></tr>"
                    for m, n in sorted(p["serie_mensal"].items(),
                                       key=lambda kv: (kv[0][3:], kv[0][:2])))

    def linha_cmp(rot, kc, kk, suf="", pior_maior=True):
        vc, vk = comp_c.get(kc), comp_k.get(kc)
        destaque = ""
        if vc is not None and vk is not None and vc != vk:
            ruim = vc > vk if pior_maior else vc < vk
            destaque = " class='bad'" if ruim else ""
        return (f"<tr><td>{rot}</td><td class='num'{destaque}>{vc if vc is not None else '—'}{suf}</td>"
                f"<td class='num'>{vk if vk is not None else '—'}{suf}</td></tr>")

    cmp_html = ""
    if comp_c["n"] >= 3 and comp_k["n"] >= 3:
        cmp_html = ("<h2>Relacionamento — equipe no WhatsApp (janela pré-pedido vs controle)</h2>"
                    f"<p class='meta'>medianas · coorte n={comp_c['n']} · controle n={comp_k['n']} "
                    f"(contas saudáveis do {b}, últimos {_JANELA_ZAP_D}d)</p><table>"
                    "<tr><th>Métrica</th><th class='num'>Coorte</th><th class='num'>Controle</th></tr>"
                    + linha_cmp("Msgs do cliente sem resposta da equipe em 24h", "pct_sem24", "pct_sem24", "%")
                    + linha_cmp("Dias em que a equipe inicia a conversa", "pct_eq_inicia", "pct_eq_inicia", "%", pior_maior=False)
                    + linha_cmp("Maior período sem mensagem da equipe (dias)", "max_gap_eq_d", "max_gap_eq_d")
                    + linha_cmp("Mensagens do cliente/semana", "cl_sem", "cl_sem")
                    + linha_cmp("Tempo de resposta quando responde (h)", "resp_med_h", "resp_med_h")
                    + "</table>")
    else:
        cmp_html = ("<h2>Relacionamento — equipe no WhatsApp</h2>"
                    "<div class='warn'>Base insuficiente para o comparativo nesta geração "
                    f"(coorte com mensagens: {comp_c['n']} conta(s); controle: {comp_k['n']}). "
                    "Pedidos antigos podem estar fora da cobertura do gateway; clique em Regerar "
                    "fora de horário de pico para tentar de novo.</div>")

    cards = ""
    for c in p["casos"]:
        pill = ("<span class='pill pR'>cancelou</span>" if c["tipo"] == "cancelamento" else
                ("<span class='pill pG'>tratativa revertida</span>" if "revert" in (c["situacao"] or "").lower()
                 else "<span class='pill pA'>tratativa</span>"))
        z, e = c.get("zap"), c.get("entregas")
        li = ""
        if z:
            li += (f"<li><b>Relacionamento (45d pré-pedido):</b> equipe {z['eq_sem']} msg/sem × cliente "
                   f"{z['cl_sem']} · {z['pct_sem24']}% sem resposta em 24h · equipe inicia o dia "
                   f"{z['pct_eq_inicia']}% · maior silêncio da equipe {z['max_gap_eq_d']}d</li>")
        else:
            li += "<li class='meta'>Sem mensagens na janela pré-pedido (cobertura do gateway ou grupo silencioso).</li>"
        if e:
            queda = (e["media_mes"] and e["e30"] < e["media_mes"] * 0.6)
            li += (f"<li><b>Entrega ({_PRE_ENTREGA_D}d pré-pedido):</b> {e['e30']} atividade(s)"
                   + (f" vs média histórica de {e['media_mes']}/mês" if e["media_mes"] else " (conta jovem, sem média)")
                   + (f" · última entrega {e['dias_ult']}d antes do pedido" if e["dias_ult"] is not None else "")
                   + (" <b class='bad'>← queda</b>" if queda else "") + "</li>")
        if c["drivers"]:
            li += f"<li><b>Sinais do agente:</b> {escape(' · '.join(c['drivers']))}</li>"
        for n in c["notas"][:3]:
            li += f"<li class='meta'>{escape(n)}</li>"
        casa = (f"{int(c['meses_casa'])} meses" if c["meses_casa"] is not None else "—")
        grid = (f"<div class='grid2'>"
                f"<div><b>Plano:</b> {escape(str(c['plano'] or '—'))}"
                + (f" · {_brl(c['valor'])}/mês" if c["valor"] else "") + "</div>"
                f"<div><b>Tempo de casa:</b> {casa}</div>")
        grid += (f"<div><b>Registro:</b> {c['tipo']} em {c['mes']}"
                 + (f" · situação: {escape(c['situacao'])}" if c["situacao"] else "") + "</div>")
        if c["score"] is not None:
            grid += (f"<div><b>Score:</b> {c['score']:.1f} ({escape(str(c['band']))} / "
                     f"{escape(_STAGE_PT.get(c['stage'], str(c['stage'])))}) · {c['alertas']} alerta(s)</div>")
        grid += "</div>"
        aviso_conta = ("<div class='warn'>Conta não localizada no painel — métricas de score/zap indisponíveis.</div>"
                       if c["sem_conta"] else "")
        mot = (f"<div class='meta'>Motivo declarado: {escape(c['motivo'])}</div>" if (c["motivo"] or "").strip()
               else "<div class='meta bad'>Motivo NÃO preenchido na planilha.</div>")
        cards += (f"<div class='card'><h3>{escape(c['cliente'][:70])} · {pill}</h3>"
                  f"{grid}{aviso_conta}<ul>{li}</ul>{mot}</div>")

    canal_html = ""
    if p["canal"]:
        linhas = "".join(
            f"<tr><td>{escape(x['canal'])}</td><td class='num'>{x['n']}</td>"
            f"<td class='num'>{x['prec']}%</td><td class='num'>{_brl(x.get('cac'))}</td>"
            f"<td class='num'>{_brl(x.get('cac_aj'))}</td></tr>" for x in p["canal"])
        canal_html = ("<h2>Aquisição — churn precoce por canal (mesma régua do Raio-X)</h2>"
                      "<table><tr><th>Canal</th><th class='num'>Clientes rastreados</th>"
                      "<th class='num'>Churn precoce (≤3m)</th><th class='num'>CAC</th>"
                      "<th class='num'>CAC ajustado pela retenção</th></tr>" + linhas + "</table>")

    recs = []
    if (comp_c.get("pct_sem24") or 0) > (comp_k.get("pct_sem24") or 0) * 1.5 and comp_c["n"] >= 3:
        recs.append("Cobertura de resposta: toda mensagem de cliente respondida em &lt;24h nos grupos "
                    f"do {b} em risco — é a métrica com maior diferença entre quem saiu e quem ficou.")
    if any((c.get("zap") or {}).get("max_gap_eq_d", 0) >= 10 for c in p["casos"]):
        recs.append("Alarme de silêncio: grupo sem mensagem da equipe há 7+ dias deveria virar alerta.")
    if any(c.get("entregas") and c["entregas"]["media_mes"] and
           c["entregas"]["e30"] < c["entregas"]["media_mes"] * 0.6 for c in p["casos"]):
        recs.append("Queda de ritmo de entrega vs a média da própria conta antecedeu pedidos — "
                    "candidata a sinal novo no score (a régua atual mede atraso, não ritmo relativo).")
    if p["lacunas"]["sem_motivo"]:
        recs.append(f"{p['lacunas']['sem_motivo']} cancelamento(s) da janela sem motivo preenchido — "
                    "motivo obrigatório no ato de formalizar.")
    pior_canal = max(p["canal"], key=lambda x: x["prec"], default=None)
    if pior_canal and pior_canal["prec"] >= 40:
        recs.append(f"Endurecer a qualificação de {escape(pior_canal['canal'])} para o {b} "
                    f"({pior_canal['prec']}% de churn precoce) e tratar os primeiros 90 dias como programa.")
    rec_html = ("<h2>Recomendações (regras determinísticas)</h2><ul>"
                + "".join(f"<li>{r}</li>" for r in recs) + "</ul>") if recs else ""

    aviso_parcial = (f"<div class='warn'>Análise de mensagens PARCIAL nesta geração: {p['zap_pulados']} "
                     "conta(s) ficaram fora por orçamento de tempo do gateway — use Regerar fora de pico."
                     "</div>") if p.get("zap_pulados") else ""

    cache_meta = (f" · cache de {p['_cache_de'][:16].replace('T', ' ')}" if p.get("_cache_de") else "")
    return (
        f"<h1>Churn do {b} — dossiê dos casos ({j['ini'][:7]} em diante)</h1>"
        f"<div class='sub'>Integracomm IA · gerado em {p['gerado_em'][:16].replace('T', ' ')}{cache_meta} · "
        "fontes: planilhas de saídas, score/sinais do agente, WhatsApp (gateway), espelho ClickUp, coorte de "
        "aquisição · <b>uso interno — contém nomes de clientes</b></div>"
        + aviso_parcial + kpis
        + "<h2>Série mensal de cancelamentos do " + b + "</h2><table>"
          "<tr><th>Mês</th><th class='num'>Cancelamentos</th></tr>" + serie + "</table>"
        + cmp_html
        + "<h2>Os casos, um a um</h2>" + cards
        + canal_html + rec_html
        + "<h2>Metodologia e ressalvas</h2><p class='meta'>"
          "Coorte = clientes do bundle com cancelamento ou tratativa na janela; controle = contas saudáveis do "
          "mesmo bundle. Relacionamento: mensagens do grupo nos 45 dias ANTES do pedido de cada conta (equipe = "
          "remetente Integracomm). Entrega: atividades concluídas no espelho do ClickUp, 30 dias pré-pedido vs "
          "média histórica da própria conta. Amostras pequenas: padrões são indício para investigar e agir, não "
          "prova estatística — associação não é causa comprovada. Pedidos antigos podem estar fora da cobertura "
          "de mensagens do gateway (o relatório marca). Análises derivadas de dados; a decisão é sempre da "
          "gestão.</p>")


@router.get("/api/growth/churn-report")
def api_churn_report(request: Request, b: str = Query("B3"), m: int = Query(3),
                     regen: int = Query(0)):
    A = _deps()
    user, _role = A._require_api(request)
    if b not in ("B1", "B2", "B3", "B4", "B5"):
        return JSONResponse({"error": "bundle deve ser B1..B5"}, status_code=400)
    m = min(max(m, 1), 12)
    with A._conn() as c:
        with c.cursor() as cur:
            cur.execute("INSERT INTO audit_log (actor, action, scope) VALUES (%s,%s,%s)",
                        (user, "churn_report", f"growth/churn/{b}/{m}m{'/regen' if regen else ''}"))
        payload = _cached_report(c, b, m, bool(regen))
    return HTMLResponse(_render_fragment(payload))


@router.get("/growth/churn-report", response_class=HTMLResponse)
def churn_report_page(request: Request, b: str = Query("B3"), m: int = Query(3)):
    A = _deps()
    if not A._session(request):
        return RedirectResponse("/login", status_code=302)
    if b not in ("B1", "B2", "B3", "B4", "B5"):
        b = "B3"
    src = f"/api/growth/churn-report?b={b}&m={int(m)}"
    return HTMLResponse(_SHELL.replace("__SRC__", src).replace("__B__", b))


_SHELL = r"""<!doctype html><html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Relatório de Churn __B__ — Integracomm IA</title>
<style>
:root{--ink:#111827;--mut:#6b7280;--line:#e5e7eb;--brand:#2563eb;--red:#dc2626;--green:#059669;--soft:#f9fafb}
*{box-sizing:border-box}
body{margin:0;background:#fff;color:var(--ink);font:14px/1.6 "Segoe UI",system-ui,sans-serif}
.wrap{max-width:900px;margin:0 auto;padding:30px 40px 60px}
h1{font-size:22px;margin:0 0 2px} h2{font-size:15px;margin:30px 0 8px;border-bottom:2px solid var(--brand);padding-bottom:4px}
h3{font-size:14px;margin:0 0 6px} .sub{color:var(--mut);font-size:12.5px}
table{width:100%;border-collapse:collapse;font-size:13px;margin:8px 0}
th{text-align:left;color:var(--mut);font-size:11px;text-transform:uppercase;letter-spacing:.05em;padding:6px 8px;border-bottom:2px solid var(--line)}
td{padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top;font-variant-numeric:tabular-nums}
th.num,td.num{text-align:right}
.kpis{display:flex;gap:10px;flex-wrap:wrap;margin:14px 0}
.kpi{flex:1 1 140px;border:1px solid var(--line);border-radius:10px;padding:10px 12px;background:var(--soft)}
.kpi .n{font-size:20px;font-weight:700}.kpi .l{font-size:10.5px;color:var(--mut);text-transform:uppercase;letter-spacing:.04em}
.card{border:1px solid var(--line);border-radius:10px;padding:12px 15px;margin:10px 0;break-inside:avoid}
.warn{background:#fffbeb;border:1px solid #fcd34d;border-radius:8px;padding:8px 12px;font-size:13px;margin:8px 0}
.pill{display:inline-block;border-radius:999px;font-size:11px;font-weight:600;padding:1px 10px}
.pR{background:#fee2e2;color:#991b1b}.pA{background:#fef3c7;color:#92400e}.pG{background:#d1fae5;color:#065f46}
.bad{color:var(--red);font-weight:700} .meta{color:var(--mut);font-size:12px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:6px 20px;font-size:13px;margin:6px 0}
ul{margin:6px 0;padding-left:20px} li{margin:3px 0}
.topbar{display:flex;gap:10px;align-items:center;margin-bottom:18px}
.btn{cursor:pointer;background:var(--brand);color:#fff;border:none;border-radius:7px;font-weight:600;font-size:13px;padding:8px 14px}
.btn.g{background:#e5e7eb;color:#111}
#loading{display:flex;flex-direction:column;align-items:center;gap:14px;padding:80px 0;color:var(--mut)}
.spin{width:26px;height:26px;border-radius:50%;border:3px solid var(--line);border-top-color:var(--brand);animation:sp .9s linear infinite}
@keyframes sp{to{transform:rotate(360deg)}}
@media print{.topbar{display:none!important}.wrap{padding:0}.card{page-break-inside:avoid}h2{page-break-after:avoid}}
</style></head><body><div class="wrap">
<div class="topbar no-print">
  <a href="/growth?view=relatorios" style="font-size:13px;color:var(--mut);text-decoration:none">← voltar</a>
  <span style="flex:1"></span>
  <button class="btn g" onclick="carrega(1)" title="ignora o cache e refaz a análise (leva alguns minutos)">Regerar</button>
  <button class="btn" onclick="window.print()">Exportar / Imprimir</button>
</div>
<div id="loading"><div class="spin"></div>
<div>Montando o dossiê de churn — planilhas, score, mensagens e entregas.<br>
A primeira geração leva alguns minutos (o gateway de mensagens é lento); as próximas são instantâneas (cache de 20h).</div></div>
<div id="rep" style="display:none"></div>
</div>
<script>
function carrega(regen){
  var l=document.getElementById('loading'), r=document.getElementById('rep');
  l.style.display='';r.style.display='none';
  fetch('__SRC__'+(regen?'&regen=1':'')).then(function(x){
    if(!x.ok) throw new Error('HTTP '+x.status);
    return x.text();
  }).then(function(html){
    r.innerHTML=html; l.style.display='none'; r.style.display='';
  }).catch(function(e){
    l.innerHTML='<div class="warn">Falha ao gerar: '+e.message+' — tente Regerar; se persistir, o gateway de mensagens pode estar fora.</div>';
  });
}
carrega(0);
</script></body></html>"""
