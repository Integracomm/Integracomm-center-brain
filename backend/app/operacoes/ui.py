"""Área de OPERAÇÕES (/operacoes) — réplica do app Lovable "Metas e Iniciativas".

Visão Geral (cards por área com contagem de iniciativas + atrasadas), página
por área (KPIs vs meta trimestral, gráficos mensais com META ADAPTATIVA —
redistribui o que faltou/sobrou dos meses fechados — e as iniciativas da
área) e Configurações (URLs do Notion + metas trimestrais + realizado manual).
Iniciativas: Notion (somente leitura). Metas: automáticas do nosso banco
onde há fonte; manuais no resto.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from html import escape

from fastapi import APIRouter, Body, Request
from fastapi.responses import HTMLResponse, JSONResponse

from . import metas as MT

router = APIRouter()

_AREAS_OP = [("financeiro", "Financeiro", "Letícia"), ("comercial", "Comercial", "Marcos"),
             ("assessoria", "Assessoria", "Samantha / Eduardo Luiz"),
             ("marketing", "Marketing", "Rafael"), ("rh", "RH", "Amanda"),
             ("growth", "Growth", "—")]
_MES_LBL = ["", "Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
_SEM = {"verde": ("--status-baixo", "concluída"), "amarelo": ("--status-medio", "em andamento"),
        "vermelho": ("--status-critico", "atrasada"), "cinza": ("--status-semdados", "")}


def _deps():
    from .. import api as A
    return A


def _semaforo(status: str, prazo, hoje: dt.date) -> tuple[str, str]:
    if status == "concluida":
        return "verde", "concluída"
    if not prazo:
        return "cinza", "sem prazo"
    if prazo < hoje:
        return "vermelho", "atrasada"
    if status == "nao_iniciada":
        return "cinza", "não iniciada"
    return "amarelo", "em andamento"


_NUM_RE = re.compile(r"^\s*(\d+)")


def _ord_iniciativa(nome: str) -> tuple:
    m = _NUM_RE.match(nome or "")
    return (0, int(m.group(1)), "") if m else (1, 0, (nome or "").casefold())


def grupos_dados(rows: list[dict], hoje: dt.date) -> dict:
    """Agrupamento PURO das iniciativas (gestor → iniciativa → escopo → ações),
    com TODAS as decisões de exibição já resolvidas (cor/rótulo do semáforo, o
    'aguardando ação anterior atrasada' que depende da ORDEM, progresso normal-
    izado, subitens). Fonte única do HTML (_render_grupos) e do SPA
    (/api/operacoes/area) — extraído para não repetir a régua em dois lugares
    (lição dos Squads no Lote 6: verificar o efeito no caminho real)."""
    gestores: dict[str, list[dict]] = {}
    for r in rows:
        gestores.setdefault(r["gestor"] or "Outros", []).append(r)
    um_gestor = len(gestores) == 1
    out_grupos = []
    for gestor in sorted(gestores, key=str.casefold):
        grows = gestores[gestor]
        inics: dict[str, list[dict]] = {}
        for r in grows:
            inics.setdefault(r["iniciativa"] or r["titulo"] or "(sem iniciativa)", []).append(r)
        inic_out = []
        for inic in sorted(inics, key=_ord_iniciativa):
            irows = inics[inic]
            subs: dict[str, list[dict]] = {}
            for r in irows:
                subs.setdefault(r["detalhamento"] or "", []).append(r)

            def _min_prazo(rs):
                ps = [r["prazo"] for r in rs if r["prazo"]]
                return (0, min(ps)) if ps else (1, dt.date.max)
            subs_out = []
            for sub in sorted(subs, key=lambda s: _min_prazo(subs[s])):
                srows = sorted(subs[sub], key=lambda r: ((0, r["prazo"]) if r["prazo"] else (1, dt.date.max),
                                                         (r["acao"] or r["titulo"] or "").casefold()))
                bloqueia = False
                acoes = []
                for r in srows:
                    concluida = r["status"] == "concluida"
                    cor, rotulo = _semaforo(r["status"], r["prazo"], hoje)
                    dep = False
                    if not concluida:
                        dep = bloqueia
                        if cor == "vermelho" and not bloqueia:
                            bloqueia = True
                    prog = None
                    if r["progresso"] is not None:
                        prog = max(0.0, min(100.0, float(r["progresso"])))
                    acoes.append({
                        "acao": r["acao"] or r["titulo"] or "(sem ação)",
                        "cor": cor, "rotulo": rotulo,
                        "prazo": r["prazo"].isoformat() if r["prazo"] else None,
                        "dep": dep, "progresso": prog,
                        "notion_url": r["notion_url"],
                        "responsaveis": r["responsaveis"] or [],
                        "subitems": [{"titulo": s.get("titulo") or "",
                                      "concluida": s.get("status") == "concluida"}
                                     for s in r["subitems"]],
                    })
                subs_out.append({"detalhamento": sub, "acoes": acoes})
            inic_out.append({"nome": inic, "feitos": sum(1 for r in irows if r["status"] == "concluida"),
                             "total": len(irows), "subs": subs_out})
        out_grupos.append({"gestor": gestor, "iniciativas": inic_out})
    return {"um_gestor": um_gestor, "grupos": out_grupos}


def _render_grupos(rows: list[dict], hoje: dt.date) -> str:
    if not rows:
        return "<div class=warn>nenhuma iniciativa sincronizada — configure a URL do Notion em Configurações e clique em Sincronizar.</div>"
    dados = grupos_dados(rows, hoje)
    um_gestor = dados["um_gestor"]
    html = ""
    for g in dados["grupos"]:
        bloco = ""
        for inic in g["iniciativas"]:
            linhas = ""
            for sub in inic["subs"]:
                if sub["detalhamento"]:
                    linhas += (f"<div style='margin:10px 0 4px;font-size:var(--fs-2xs);color:var(--text-muted);"
                               f"text-transform:uppercase;letter-spacing:var(--tracking-label)'>{escape(sub['detalhamento'])}</div>")
                for a in sub["acoes"]:
                    var, _lbl = _SEM[a["cor"]]
                    prazo_html = (f"<span class=chip style='--c:var({var})'>{dt.date.fromisoformat(a['prazo']).strftime('%d/%m/%Y')}</span>"
                                  if a["prazo"] else "")
                    dep = ("<span class=chip style='--c:var(--status-alto)'>aguardando ação anterior atrasada</span>"
                           if a["dep"] else "")
                    prog = ""
                    if a["progresso"] is not None:
                        p = a["progresso"]
                        prog = (f"<span style='display:inline-block;width:70px;height:6px;background:var(--surface-3);"
                                f"border-radius:3px;vertical-align:middle;overflow:hidden'>"
                                f"<span style='display:block;height:100%;width:{p:.0f}%;background:var({var})'></span></span>"
                                f"<span style='font-size:var(--fs-2xs);color:var(--text-muted)'> {p:.0f}%</span>")
                    link = (f" <a href='{escape(a['notion_url'])}' target=_blank title='abrir no Notion' "
                            f"style='color:var(--text-faint)'>↗</a>" if a["notion_url"] else "")
                    resp = ", ".join(a["responsaveis"]) if a["responsaveis"] else ""
                    resp_html = f"<span style='color:var(--text-muted);font-size:var(--fs-2xs)'> · {escape(resp)}</span>" if resp else ""
                    linhas += (f"<div style='display:flex;gap:9px;align-items:center;flex-wrap:wrap;padding:7px 0;"
                               f"border-top:1px solid var(--border)'>"
                               f"<span class=sdot style='--c:var({var})'></span>"
                               f"<span style='flex:1;min-width:200px;font-size:var(--fs-sm)'>"
                               f"{escape(a['acao'])}{link}{resp_html}</span>"
                               f"{prog}{prazo_html}{dep}"
                               f"<span class=chip style='--c:var({var})'>{a['rotulo']}</span></div>")
                    for s in a["subitems"]:
                        sc = "--status-baixo" if s["concluida"] else "--status-semdados"
                        linhas += (f"<div style='padding:3px 0 3px 28px;font-size:var(--fs-xs);color:var(--text-muted)'>"
                                   f"<span class=sdot style='--c:var({sc})'></span> {escape(s['titulo'])}</div>")
            bloco += (f"<div class=card style='margin-bottom:12px'><div style='display:flex;justify-content:space-between;"
                      f"align-items:baseline;gap:10px'><b style='font-size:var(--fs-md)'>{escape(inic['nome'])}</b>"
                      f"<span style='color:var(--text-muted);font-size:var(--fs-xs);white-space:nowrap'>"
                      f"{inic['feitos']}/{inic['total']} concluídas</span></div>{linhas}</div>")
        if um_gestor:
            html += bloco
        else:
            html += f"<section><h2>{escape(g['gestor'])}</h2>{bloco}</section>"
    return html


# ---------------------------------------------------------------------------
# dados
# ---------------------------------------------------------------------------
def _load_rows(conn, year: int, quarter: int, area: str | None = None) -> list[dict]:
    from ..sources.notion_initiatives import DDL
    with conn.cursor() as cur:
        cur.execute(DDL)
        q = """SELECT notion_id, area, titulo, responsaveis_json, prazo, status, progresso,
                      notion_url, subitems_json, iniciativa, acao, detalhamento, gestor
                 FROM notion_initiatives_cache WHERE year=%s AND quarter=%s"""
        args: list = [year, quarter]
        if area:
            q += " AND area=%s"
            args.append(area)
        cur.execute(q, args)
        return [{"notion_id": r[0], "area": r[1], "titulo": r[2],
                 "responsaveis": (r[3] if isinstance(r[3], list) else json.loads(r[3] or "[]")),
                 "prazo": r[4], "status": r[5],
                 "progresso": float(r[6]) if r[6] is not None else None,
                 "notion_url": r[7],
                 "subitems": (r[8] if isinstance(r[8], list) else json.loads(r[8] or "[]")),
                 "iniciativa": r[9], "acao": r[10], "detalhamento": r[11], "gestor": r[12]}
                for r in cur.fetchall()]


def _contagem(rows: list[dict], hoje: dt.date) -> dict:
    c = {"total": len(rows), "ok": 0, "prog": 0, "atras": 0, "ni": 0}
    for r in rows:
        cor, _ = _semaforo(r["status"], r["prazo"], hoje)
        if cor == "verde":
            c["ok"] += 1
        elif cor == "vermelho":
            c["atras"] += 1
        elif cor == "amarelo":
            c["prog"] += 1
        else:
            c["ni"] += 1
    c["progresso"] = 100.0 * c["ok"] / c["total"] if c["total"] else 0.0
    return c


# ---------------------------------------------------------------------------
# gráfico realizado × meta adaptativa (SVG simples)
# ---------------------------------------------------------------------------
def _grafico_kpi(k: dict) -> str:
    months = k["months"]
    reais = [k["realizado"].get(m) for m in months]
    metas = [k["metas_mes"].get(m) for m in months]
    vals = [v for v in reais + metas if v is not None]
    if not vals:
        return "<div class=note>sem dados no trimestre</div>"
    vmax = max(vals) * 1.15 or 1
    W, H, PAD = 320, 110, 26

    def xy(i, v):
        x = PAD + i * (W - 2 * PAD) / max(1, len(months) - 1)
        y = H - 18 - (v / vmax) * (H - 34)
        return x, y

    def linha(serie, cor, dash=""):
        pts = [(i, v) for i, v in enumerate(serie) if v is not None]
        if not pts:
            return ""
        d = " ".join(f"{xy(i, v)[0]:.0f},{xy(i, v)[1]:.0f}" for i, v in pts)
        dots = "".join(f"<circle cx='{xy(i, v)[0]:.0f}' cy='{xy(i, v)[1]:.0f}' r='3' fill='{cor}'>"
                       f"<title>{_MES_LBL[months[i]]}: {MT.fmt_val(v, k['unit'])}</title></circle>" for i, v in pts)
        return f"<polyline points='{d}' fill='none' stroke='{cor}' stroke-width='2'{dash}/>" + dots

    eixo = "".join(f"<text x='{xy(i, 0)[0]:.0f}' y='{H - 4}' text-anchor='middle' "
                   f"font-size='10' fill='var(--text-muted)'>{_MES_LBL[m]}</text>"
                   for i, m in enumerate(months))
    return (f"<svg viewBox='0 0 {W} {H}' style='width:100%;max-width:420px'>"
            + linha(metas, "var(--status-medio)", " stroke-dasharray='5 4'")
            + linha(reais, "var(--brand)") + eixo
            + f"<text x='{PAD}' y='11' font-size='9' fill='var(--brand)'>— realizado</text>"
            + f"<text x='{PAD + 80}' y='11' font-size='9' fill='var(--status-medio)'>--- meta (adaptativa)</text></svg>")


# ---------------------------------------------------------------------------
# páginas
# ---------------------------------------------------------------------------
def _pg_visao(conn, year: int, quarter: int, hoje: dt.date) -> str:
    rows = _load_rows(conn, year, quarter)
    cards, atrasadas = "", []
    tot = _contagem(rows, hoje)
    for slug, nome, gestor in _AREAS_OP:
        arows = [r for r in rows if r["area"] == slug]
        c = _contagem(arows, hoje)
        for r in arows:
            if _semaforo(r["status"], r["prazo"], hoje)[0] == "vermelho":
                atrasadas.append((r, nome))
        nums = "".join(
            f"<div style='text-align:center'><div style='font-family:var(--font-display);font-weight:700;"
            f"font-size:19px;color:{cor}'>{c[key]}</div><div style='font-size:9px;color:var(--text-muted);"
            f"text-transform:uppercase'>{lbl}</div></div>"
            for key, lbl, cor in (("total", "total", "var(--text)"), ("ok", "ok", "var(--status-baixo)"),
                                  ("prog", "prog.", "var(--status-medio)"), ("atras", "atras.", "var(--status-critico)"),
                                  ("ni", "n/i", "var(--text-muted)")))
        cards += (f"<a class=card href='/operacoes?view={slug}&year={year}&quarter={quarter}' "
                  f"style='display:block'><b style='font-size:var(--fs-md)'>{nome}</b>"
                  f"<div style='font-size:var(--fs-2xs);color:var(--text-muted)'>Gestor(a): {escape(gestor)}</div>"
                  f"<div style='display:flex;justify-content:space-between;gap:6px;margin:10px 0'>{nums}</div>"
                  f"<div style='display:flex;justify-content:space-between;font-size:var(--fs-2xs);"
                  f"color:var(--text-muted)'><span>Progresso</span><span>{c['progresso']:.0f}%</span></div>"
                  f"<div style='height:7px;background:var(--surface-3);border-radius:4px;overflow:hidden'>"
                  f"<div style='height:100%;width:{c['progresso']:.0f}%;background:var(--brand)'></div></div></a>")
    atrasadas.sort(key=lambda x: x[0]["prazo"] or dt.date.max)
    atr_html = "".join(
        f"<div style='display:flex;justify-content:space-between;gap:10px;align-items:center;padding:8px 0;"
        f"border-top:1px solid var(--border)'><div style='min-width:0'>"
        f"<div style='font-size:var(--fs-sm)'>{escape((r['iniciativa'] or r['titulo'] or '')[:90])}</div>"
        f"<div style='font-size:var(--fs-2xs);color:var(--text-muted)'>{nome} · {escape(r['acao'] or '')}</div></div>"
        f"<span class=chip style='--c:var(--status-critico)'>{r['prazo'].strftime('%d/%m/%Y')}</span></div>"
        for r, nome in atrasadas[:12]) or "<div class=note>nenhuma iniciativa atrasada 🎉</div>"
    return (f"<div style='display:flex;justify-content:space-between;align-items:center;gap:12px'>"
            f"<div></div><div style='min-width:230px'><div style='display:flex;justify-content:space-between;"
            f"font-size:var(--fs-2xs);color:var(--text-muted)'><span>Progresso real das iniciativas</span>"
            f"<span>{tot['progresso']:.0f}%</span></div>"
            f"<div style='height:8px;background:var(--surface-3);border-radius:4px;overflow:hidden'>"
            f"<div style='height:100%;width:{tot['progresso']:.0f}%;background:var(--brand)'></div></div></div></div>"
            f"<section><div style='display:grid;grid-template-columns:repeat(auto-fill,minmax(215px,1fr));gap:12px'>"
            f"{cards}</div></section>"
            f"<section><h2>⚠️ Iniciativas atrasadas</h2><div class=card>{atr_html}</div></section>")


def _pg_area(conn, slug: str, nome: str, gestor: str, year: int, quarter: int, hoje: dt.date) -> str:
    kpis = MT.load_metas(conn, slug, year, quarter)
    kcards = ""
    for k in kpis:
        badge = ""
        if k["pct"] is not None:
            cor = "--status-baixo" if k["ok"] else "--status-critico"
            badge = f"<span class=chip style='--c:var({cor});float:right'>{k['pct']:.0f}%</span>"
        auto = "" if k["auto"] else " <span style='font-size:9px;color:var(--text-faint)'>(manual)</span>"
        kcards += (f"<div class=card>{badge}<div style='font-size:var(--fs-2xs);color:var(--text-muted);"
                   f"text-transform:uppercase;letter-spacing:var(--tracking-label)'>{escape(k['label'])}{auto}</div>"
                   f"<div style='font-family:var(--font-display);font-weight:700;font-size:24px;margin:4px 0'>"
                   f"{MT.fmt_val(k['real_tri'], k['unit'])}</div>"
                   f"<div style='font-size:var(--fs-2xs);color:var(--text-muted)'>Meta: {MT.fmt_val(k['meta_tri'], k['unit'])}"
                   f"{' (teto)' if k['direction'] == 'max' else ''}</div></div>")
    graficos = "".join(
        f"<div class=card><b style='font-size:var(--fs-sm)'>{escape(k['label'])} · evolução mensal</b>"
        f"<div style='margin-top:8px'>{_grafico_kpi(k)}</div></div>"
        for k in kpis if k["meta_tri"] is not None or any(v is not None for v in k["realizado"].values()))
    rows = _load_rows(conn, year, quarter, slug)
    return (f"<div style='font-size:var(--fs-sm);color:var(--text-muted)'>Gestor(a): <b>{escape(gestor)}</b> · Q{quarter} {year}</div>"
            + (f"<section><div style='display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px'>{kcards}</div></section>" if kcards else
               "<section><div class=note>área sem KPIs de meta definidos — as iniciativas ficam abaixo</div></section>")
            + (f"<section><div style='display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:12px'>{graficos}</div></section>" if graficos else "")
            + f"<section><h2>Iniciativas</h2>{_render_grupos(rows, hoje)}</section>")


def _pg_config(conn, year: int, quarter: int) -> str:
    with conn.cursor() as cur:
        cur.execute(MT.DDL)
        cur.execute("""SELECT area, database_id, database_name, gestor_filter
                         FROM notion_config WHERE year=%s AND quarter=%s""", (year, quarter))
        cfg = {a: (d, n, g) for a, d, n, g in cur.fetchall()}
        cur.execute("SELECT area, kpi_key, meta FROM op_kpi_targets WHERE year=%s AND quarter=%s", (year, quarter))
        targets = {(a, k): float(v) if v is not None else None for a, k, v in cur.fetchall()}
        cur.execute("""SELECT area, ok, items_count, message, created_at FROM notion_sync_log
                        WHERE year=%s AND quarter=%s ORDER BY created_at DESC LIMIT 8""", (year, quarter))
        synclog = cur.fetchall()
    cfg_rows = ""
    for slug, nome, _g in _AREAS_OP:
        did, dname, gfil = cfg.get(slug, (None, None, None))
        st = f"<span class=note>{escape(dname or '')}</span>" if did else "<span class=note style='color:var(--text-faint)'>não configurado</span>"
        cfg_rows += (f"<div style='display:flex;gap:8px;align-items:center;padding:7px 0;border-top:1px solid var(--border);flex-wrap:wrap'>"
                     f"<b style='width:200px;font-size:var(--fs-sm)'>{nome}</b>"
                     f"<input id='cfg-{slug}' placeholder='cole a URL da página do trimestre…' value='{escape(did or '')}' "
                     f"style='flex:1;min-width:260px;background:var(--bg-panel);border:1px solid var(--border-strong);"
                     f"border-radius:var(--radius-sm);color:var(--text);font-size:var(--fs-xs);padding:7px 9px'>"
                     f"<input id='ges-{slug}' placeholder='gestor (opcional)' value='{escape(gfil or '')}' "
                     f"title='p/ árvore compartilhada entre áreas: importa só as iniciativas da subpágina deste gestor' "
                     f"style='width:150px;background:var(--bg-panel);border:1px solid var(--border-strong);"
                     f"border-radius:var(--radius-sm);color:var(--text);font-size:var(--fs-xs);padding:7px 9px'>"
                     f"<button class=abtn2 onclick=\"salvarCfg('{slug}')\">salvar</button>{st}</div>")
    metas_rows = ""
    for slug, nome, _g in _AREAS_OP:
        defs = MT.AREA_KPIS.get(slug) or []
        if not defs:
            continue
        linhas = ""
        for key, label, unit, direction, _ir, is_auto in defs:
            v = targets.get((slug, key))
            linhas += (f"<div style='display:flex;gap:8px;align-items:center;padding:5px 0;flex-wrap:wrap'>"
                       f"<span style='width:210px;font-size:var(--fs-xs)'>{escape(label)}"
                       f"{'' if is_auto else ' <span style=color:var(--text-faint)>(realizado manual)</span>'}</span>"
                       f"<input id='meta-{slug}-{key}' type=number step=any value='{'' if v is None else v}' "
                       f"placeholder='meta do trimestre ({unit})' style='width:190px;background:var(--bg-panel);"
                       f"border:1px solid var(--border-strong);border-radius:var(--radius-sm);color:var(--text);"
                       f"font-size:var(--fs-xs);padding:6px 8px'>"
                       f"<button class=abtn2 onclick=\"salvarMeta('{slug}','{key}')\">salvar</button>"
                       + ("" if is_auto else "".join(
                           f"<input id='real-{slug}-{key}-{m}' type=number step=any placeholder='{_MES_LBL[m]}' "
                           f"style='width:86px;background:var(--bg-panel);border:1px solid var(--border-strong);"
                           f"border-radius:var(--radius-sm);color:var(--text);font-size:var(--fs-xs);padding:6px 8px' "
                           f"onchange=\"salvarReal('{slug}','{key}',{m})\">"
                           for m in MT.quarter_months(quarter)))
                       + "</div>")
        metas_rows += f"<div style='padding:8px 0;border-top:1px solid var(--border)'><b>{nome}</b>{linhas}</div>"
    log_html = "".join(
        f"<div class=note style='padding:3px 0'>{'✅' if ok else '⚠️'} {escape(a or '')} — "
        f"{escape(msg or '')} <span style='color:var(--text-faint)'>({ts.strftime('%d/%m %H:%M')})</span></div>"
        for a, ok, n, msg, ts in synclog) or "<div class=note>nenhuma sincronização registrada ainda</div>"
    return ("<section><h2>URLs do Notion por área</h2>"
            f"<p class=secsub>vale para Q{quarter}/{year} · a página precisa estar compartilhada com a integração no Notion</p>"
            f"<div class=card>{cfg_rows}</div></section>"
            "<section><h2>Metas do trimestre por KPI</h2>"
            "<p class=secsub>meta trimestral (R$/qtde = soma dos meses; % = média) · KPIs marcados (realizado manual) "
            "ganham campos por mês — os demais preenchem sozinhos do banco</p>"
            f"<div class=card>{metas_rows}</div></section>"
            "<section><h2>Últimas sincronizações</h2>" + f"<div class=card>{log_html}</div></section>")


@router.get("/operacoes", response_class=HTMLResponse)
def operacoes(request: Request):
    A = _deps()
    s, redir = A._require_area(request, "operacoes")
    if redir:
        return redir
    user, _role = s
    qp = request.query_params
    hoje = dt.date.today()
    q_atual = (hoje.month - 1) // 3 + 1
    try:
        year = int(qp.get("year") or hoje.year)
        quarter = int(qp.get("quarter") or q_atual)
    except ValueError:
        year, quarter = hoje.year, q_atual
    view = qp.get("view") or "visao"
    slugs = {s_: (n, g) for s_, n, g in _AREAS_OP}
    if view not in {"visao", "config", *slugs}:
        view = "visao"

    from .. import spa as _spa_mod  # redesenho: view migrada entrega o SPA
    _r = _spa_mod.view_response(request, "operacoes", view)
    if _r is not None:
        return _r

    with A._conn() as c:
        with c.cursor() as cur:
            cur.execute("INSERT INTO audit_log (actor, action, scope) VALUES (%s,'view',%s)",
                        (user, f"operacoes/{view} {year}Q{quarter}"))
        if view == "visao":
            corpo, titulo = _pg_visao(c, year, quarter, hoje), f"Visão Geral · Q{quarter} {year}"
        elif view == "config":
            corpo, titulo = _pg_config(c, year, quarter), "Configurações"
        else:
            nome, gestor = slugs[view]
            corpo, titulo = _pg_area(c, view, nome, gestor, year, quarter, hoje), f"{nome} · Q{quarter} {year}"

    opts_q = "".join(f"<option value='{q_}' {'selected' if quarter == q_ else ''}>Q{q_}</option>" for q_ in (1, 2, 3, 4))
    opts_y = "".join(f"<option value='{y}' {'selected' if year == y else ''}>{y}</option>" for y in (2025, 2026, 2027))
    form = (f"<form method=get action=/operacoes><input type=hidden name=view value='{view}'>"
            f"<div class=filters><div><label>ano</label><select name=year>{opts_y}</select></div>"
            f"<div><label>trimestre</label><select name=quarter>{opts_q}</select></div>"
            f"<button type=submit>Aplicar</button>"
            f"<button type=button onclick=\"syncNotion('{'' if view in ('visao', 'config') else view}')\" "
            f"style='background:var(--brand);color:#111'>Sincronizar Notion</button></div></form>")
    js = ("<script>"
          f"var Y={year},Q={quarter};"
          "function syncNotion(a){var b=event.target;b.disabled=true;b.textContent='sincronizando…';"
          "fetch('/api/operacoes/initiatives/sync',{method:'POST',headers:{'Content-Type':'application/json'},"
          "body:JSON.stringify({year:Y,quarter:Q,area:a||null})}).then(function(r){return r.json();})"
          ".then(function(j){if(j.errors&&j.errors.length)alert(j.errors.join('\\n'));location.reload();})"
          ".catch(function(){alert('falha de rede');b.disabled=false;});}"
          "function salvarCfg(slug){var v=document.getElementById('cfg-'+slug).value;"
          "var ge=document.getElementById('ges-'+slug);var g=ge?ge.value:null;"
          "fetch('/api/operacoes/notion-config',{method:'POST',headers:{'Content-Type':'application/json'},"
          "body:JSON.stringify({area:slug,year:Y,quarter:Q,url:v||null,gestor:g||null})}).then(function(r){return r.json();})"
          ".then(function(j){if(!j.ok)alert(j.message||'erro');else location.reload();})"
          ".catch(function(){alert('falha de rede');});}"
          "function salvarMeta(a,k){var v=document.getElementById('meta-'+a+'-'+k).value;"
          "fetch('/api/operacoes/kpi-target',{method:'POST',headers:{'Content-Type':'application/json'},"
          "body:JSON.stringify({area:a,kpi_key:k,year:Y,quarter:Q,meta:v===''?null:parseFloat(v)})})"
          ".then(function(r){return r.json();}).then(function(j){if(j.error)alert(j.error);else location.reload();});}"
          "function salvarReal(a,k,m){var v=document.getElementById('real-'+a+'-'+k+'-'+m).value;"
          "fetch('/api/operacoes/kpi-monthly',{method:'POST',headers:{'Content-Type':'application/json'},"
          "body:JSON.stringify({area:a,kpi_key:k,year:Y,month:m,realizado:v===''?null:parseFloat(v)})})"
          ".then(function(r){return r.json();}).then(function(j){if(j.error)alert(j.error);});}"
          "</script><style>.abtn2{cursor:pointer;background:var(--surface-3);border:1px solid var(--border-strong);"
          "border-radius:var(--radius-sm);color:var(--text-2);font-family:var(--font-body);font-size:var(--fs-2xs);"
          "padding:6px 11px}.abtn2:hover{border-color:var(--brand);color:var(--brand)}</style>")

    content = (f"<h1>{escape(titulo)}</h1>"
               "<div class=sub>metas e iniciativas estratégicas por área · iniciativas do Notion (somente leitura) · "
               "meta mensal adaptativa: o que faltou/sobrou num mês redistribui nos seguintes</div>"
               + form + corpo + js)
    views = [("visao", "Visão Geral")] + [(s_, n) for s_, n, _ in _AREAS_OP] + [("config", "Configurações")]
    from ..sales.ui import _shell
    html = _shell(A, "operacoes", views, view, content, user)
    return HTMLResponse(html.replace("Pré-vendas · Qualificação", "Operações · Metas & Iniciativas")
                        .replace("Vendas · Fechamento", "Operações · Metas & Iniciativas"))


# ---------------------------------------------------------------------------
# Endpoints JSON do redesenho (Lote 6, tela final) — EMBRULHAM os mesmos
# computes do HTML (_load_rows/_contagem/_semaforo/grupos_dados/MT.load_metas).
# As mutações (config/sync/metas/realizado) reusam os POST já existentes abaixo.
# ---------------------------------------------------------------------------
def _yq(request: Request) -> tuple[int, int]:
    qp = request.query_params
    hoje = dt.date.today()
    q_atual = (hoje.month - 1) // 3 + 1
    try:
        return int(qp.get("year") or hoje.year), int(qp.get("quarter") or q_atual)
    except ValueError:
        return hoje.year, q_atual


@router.get("/api/operacoes/visao")
def api_op_visao(request: Request):
    A = _deps()
    A._require_api(request)
    year, quarter = _yq(request)
    hoje = dt.date.today()
    with A._conn() as c:
        rows = _load_rows(c, year, quarter)
    tot = _contagem(rows, hoje)
    areas, atrasadas = [], []
    for slug, nome, gestor in _AREAS_OP:
        arows = [r for r in rows if r["area"] == slug]
        cc = _contagem(arows, hoje)
        for r in arows:
            if _semaforo(r["status"], r["prazo"], hoje)[0] == "vermelho":
                atrasadas.append((r, nome))
        areas.append({"slug": slug, "nome": nome, "gestor": gestor,
                      "total": cc["total"], "ok": cc["ok"], "prog": cc["prog"],
                      "atras": cc["atras"], "ni": cc["ni"],
                      "progresso": round(cc["progresso"], 1)})
    atrasadas.sort(key=lambda x: x[0]["prazo"] or dt.date.max)
    atr = [{"iniciativa": (r["iniciativa"] or r["titulo"] or "")[:90],
            "area_nome": nome, "acao": r["acao"] or "",
            "prazo": r["prazo"].isoformat() if r["prazo"] else None}
           for r, nome in atrasadas[:12]]
    return {"year": year, "quarter": quarter,
            "progresso_total": round(tot["progresso"], 1),
            "areas": areas, "atrasadas": atr}


@router.get("/api/operacoes/area")
def api_op_area(request: Request):
    A = _deps()
    A._require_api(request)
    year, quarter = _yq(request)
    hoje = dt.date.today()
    slug = request.query_params.get("slug") or ""
    slugs = {s_: (n, g) for s_, n, g in _AREAS_OP}
    if slug not in slugs:
        return JSONResponse({"error": "área inválida"}, status_code=404)
    nome, gestor = slugs[slug]
    with A._conn() as c:
        kpis_raw = MT.load_metas(c, slug, year, quarter)
        rows = _load_rows(c, year, quarter, slug)
    kpis = []
    for k in kpis_raw:
        months = k["months"]
        kpis.append({
            "key": k["key"], "label": k["label"], "unit": k["unit"],
            "direction": k["direction"], "auto": k["auto"],
            "real_tri": k["real_tri"], "meta_tri": k["meta_tri"],
            "pct": round(k["pct"], 1) if k["pct"] is not None else None,
            "ok": k["ok"],
            "meses_lbl": [_MES_LBL[m] for m in months],
            "reais": [k["realizado"].get(m) for m in months],
            "metas": [k["metas_mes"].get(m) for m in months],
        })
    return {"slug": slug, "nome": nome, "gestor": gestor,
            "year": year, "quarter": quarter, "kpis": kpis,
            "iniciativas": grupos_dados(rows, hoje)}


@router.get("/api/operacoes/config")
def api_op_config(request: Request):
    A = _deps()
    _actor, role = A._require_api(request)  # leitura livre a quem tem Operações;
    year, quarter = _yq(request)            # as MUTAÇÕES (POST abaixo) é que exigem admin
    is_admin = role == "admin"
    with A._conn() as c, c.cursor() as cur:
        cur.execute(MT.DDL)
        cur.execute("""SELECT area, database_id, database_name, gestor_filter
                         FROM notion_config WHERE year=%s AND quarter=%s""", (year, quarter))
        cfg = {a: (d, n, g) for a, d, n, g in cur.fetchall()}
        cur.execute("SELECT area, kpi_key, meta FROM op_kpi_targets WHERE year=%s AND quarter=%s", (year, quarter))
        targets = {(a, k): float(v) if v is not None else None for a, k, v in cur.fetchall()}
        cur.execute("""SELECT area, kpi_key, month, realizado FROM op_kpi_monthly
                        WHERE year=%s AND month = ANY(%s)""", (year, MT.quarter_months(quarter)))
        manual: dict[tuple[str, str, int], float | None] = {
            (a, k, m): (float(v) if v is not None else None) for a, k, m, v in cur.fetchall()}
        cur.execute("""SELECT area, ok, items_count, message, created_at FROM notion_sync_log
                        WHERE year=%s AND quarter=%s ORDER BY created_at DESC LIMIT 8""", (year, quarter))
        synclog = cur.fetchall()
    areas_cfg, metas = [], []
    for slug, nome, _g in _AREAS_OP:
        did, dname, gfil = cfg.get(slug, (None, None, None))
        areas_cfg.append({"slug": slug, "nome": nome, "database_id": did,
                          "database_name": dname, "gestor_filter": gfil})
        defs = MT.AREA_KPIS.get(slug) or []
        if not defs:
            continue
        kdefs = []
        for key, label, unit, direction, _ir, is_auto in defs:
            kdefs.append({
                "key": key, "label": label, "unit": unit, "direction": direction,
                "is_auto": is_auto, "meta": targets.get((slug, key)),
                "meses": [{"month": m, "label": _MES_LBL[m],
                           "realizado": manual.get((slug, key, m))}
                          for m in MT.quarter_months(quarter)] if not is_auto else [],
            })
        metas.append({"slug": slug, "nome": nome, "kpis": kdefs})
    log = [{"area": a or "", "ok": bool(ok), "message": msg or "",
            "ts": ts.strftime("%d/%m %H:%M")} for a, ok, _n, msg, ts in synclog]
    return {"year": year, "quarter": quarter, "is_admin": is_admin,
            "areas_cfg": areas_cfg, "metas": metas, "synclog": log}


@router.post("/api/operacoes/notion-config")
def api_notion_config(request: Request, payload: dict = Body(...)):
    A = _deps()
    actor, role = A._require_api(request)
    if role != "admin":
        return JSONResponse({"error": "só o administrador configura o Notion"}, status_code=403)
    from ..sources.notion_initiatives import set_config
    with A._conn() as c:
        out = set_config(c, str(payload.get("area")), int(payload.get("year")),
                         int(payload.get("quarter")), payload.get("url"),
                         gestor_filter=payload.get("gestor"))
        with c.cursor() as cur:
            cur.execute("INSERT INTO audit_log (actor, action, scope) VALUES (%s,%s,%s)",
                        (actor, "notion_config", f"{payload.get('area')} {payload.get('year')}Q{payload.get('quarter')}"))
    return JSONResponse(out)


@router.post("/api/operacoes/initiatives/sync")
def api_initiatives_sync(request: Request, payload: dict = Body(...)):
    A = _deps()
    actor, _role = A._require_api(request)
    from ..sources.notion_initiatives import sync_initiatives
    with A._conn() as c:
        out = sync_initiatives(c, int(payload.get("year")), int(payload.get("quarter")),
                               payload.get("area") or None)
        with c.cursor() as cur:
            cur.execute("INSERT INTO audit_log (actor, action, scope) VALUES (%s,%s,%s)",
                        (actor, "notion_sync", f"{payload.get('year')}Q{payload.get('quarter')} "
                                               f"{payload.get('area') or 'todas'}: {out['synced']} itens"))
    return JSONResponse(out)


@router.post("/api/operacoes/kpi-target")
def api_kpi_target(request: Request, payload: dict = Body(...)):
    A = _deps()
    actor, role = A._require_api(request)
    if role != "admin":
        return JSONResponse({"error": "só o administrador define metas"}, status_code=403)
    with A._conn() as c, c.cursor() as cur:
        cur.execute(MT.DDL)
        cur.execute("""INSERT INTO op_kpi_targets (area, kpi_key, year, quarter, meta)
                       VALUES (%s,%s,%s,%s,%s) ON CONFLICT (area, kpi_key, year, quarter)
                       DO UPDATE SET meta=EXCLUDED.meta""",
                    (payload.get("area"), payload.get("kpi_key"), int(payload.get("year")),
                     int(payload.get("quarter")), payload.get("meta")))
        cur.execute("INSERT INTO audit_log (actor, action, scope) VALUES (%s,%s,%s)",
                    (actor, "kpi_target", f"{payload.get('area')}/{payload.get('kpi_key')}"))
    return JSONResponse({"ok": True})


@router.post("/api/operacoes/kpi-monthly")
def api_kpi_monthly(request: Request, payload: dict = Body(...)):
    A = _deps()
    actor, role = A._require_api(request)
    if role != "admin":
        return JSONResponse({"error": "só o administrador lança realizado"}, status_code=403)
    with A._conn() as c, c.cursor() as cur:
        cur.execute(MT.DDL)
        cur.execute("""INSERT INTO op_kpi_monthly (area, kpi_key, year, month, realizado)
                       VALUES (%s,%s,%s,%s,%s) ON CONFLICT (area, kpi_key, year, month)
                       DO UPDATE SET realizado=EXCLUDED.realizado""",
                    (payload.get("area"), payload.get("kpi_key"), int(payload.get("year")),
                     int(payload.get("month")), payload.get("realizado")))
        cur.execute("INSERT INTO audit_log (actor, action, scope) VALUES (%s,%s,%s)",
                    (actor, "kpi_monthly", f"{payload.get('area')}/{payload.get('kpi_key')}"))
    return JSONResponse({"ok": True})
