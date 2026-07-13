"""Área de OPERAÇÕES (/operacoes) — controle de iniciativas por área (Notion).

Réplica fiel do app Lovable "Metas e Iniciativas": agrupamento gestor →
iniciativa (ordenada pelo nº no nome) → detalhamento (por menor prazo) →
ações (por prazo), semáforo por prazo/status e badge de dependência
sequencial. Fonte: Notion (somente leitura) → cache notion_initiatives_cache.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from html import escape

from fastapi import APIRouter, Body, Request
from fastapi.responses import HTMLResponse, JSONResponse

router = APIRouter()

_AREAS_OP = [("financeiro", "Financeiro"), ("comercial", "Comercial (Pré-vendas + Vendas)"),
             ("assessoria", "Assessoria"), ("marketing", "Marketing"), ("rh", "RH"),
             ("growth", "Growth")]
_SEM = {"verde": ("--status-baixo", "concluída"), "amarelo": ("--status-medio", "em andamento"),
        "vermelho": ("--status-critico", "atrasada"), "cinza": ("--status-semdados", "")}


def _deps():
    from .. import api as A
    return A


def _semaforo(status: str, prazo, hoje: dt.date) -> tuple[str, str]:
    """(cor, rótulo) — regra exata da referência."""
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


def _render_grupos(rows: list[dict], hoje: dt.date) -> str:
    """4 níveis de agrupamento + semáforo + badge de dependência."""
    if not rows:
        return "<div class=warn>nenhuma iniciativa sincronizada para esta seleção — configure a URL do Notion abaixo e clique em Sincronizar.</div>"
    gestores: dict[str, list[dict]] = {}
    for r in rows:
        gestores.setdefault(r["gestor"] or "Outros", []).append(r)
    um_gestor = len(gestores) == 1
    html = ""
    for gestor in sorted(gestores, key=str.casefold):
        grows = gestores[gestor]
        inics: dict[str, list[dict]] = {}
        for r in grows:
            inics.setdefault(r["iniciativa"] or r["titulo"] or "(sem iniciativa)", []).append(r)
        bloco = ""
        for inic in sorted(inics, key=_ord_iniciativa):
            irows = inics[inic]
            subs: dict[str, list[dict]] = {}
            for r in irows:
                subs.setdefault(r["detalhamento"] or "", []).append(r)

            def _min_prazo(rs):
                ps = [r["prazo"] for r in rs if r["prazo"]]
                return (0, min(ps)) if ps else (1, dt.date.max)
            linhas = ""
            for sub in sorted(subs, key=lambda s: _min_prazo(subs[s])):
                srows = sorted(subs[sub], key=lambda r: ((0, r["prazo"]) if r["prazo"] else (1, dt.date.max),
                                                         (r["acao"] or r["titulo"] or "").casefold()))
                # dependência sequencial: 1ª pendente atrasada trava as pendentes seguintes
                bloqueia = False
                for r in srows:
                    if r["status"] == "concluida":
                        r["_dep"] = False
                        continue
                    cor, _ = _semaforo(r["status"], r["prazo"], hoje)
                    r["_dep"] = bloqueia
                    if cor == "vermelho" and not bloqueia:
                        bloqueia = True
                if sub:
                    linhas += (f"<div style='margin:10px 0 4px;font-size:var(--fs-2xs);color:var(--text-muted);"
                               f"text-transform:uppercase;letter-spacing:var(--tracking-label)'>{escape(sub)}</div>")
                for r in srows:
                    cor, rotulo = _semaforo(r["status"], r["prazo"], hoje)
                    var, _lbl = _SEM[cor]
                    prazo_html = ""
                    if r["prazo"]:
                        prazo_html = (f"<span class=chip style='--c:var({var})'>"
                                      f"{r['prazo'].strftime('%d/%m/%Y')}</span>")
                    dep = ("<span class=chip style='--c:var(--status-alto)'>aguardando ação anterior atrasada</span>"
                           if r.get("_dep") else "")
                    prog = ""
                    if r["progresso"] is not None:
                        p = max(0, min(100, float(r["progresso"])))
                        prog = (f"<span style='display:inline-block;width:70px;height:6px;background:var(--surface-3);"
                                f"border-radius:3px;vertical-align:middle;overflow:hidden'>"
                                f"<span style='display:block;height:100%;width:{p:.0f}%;background:var({var})'></span></span>"
                                f"<span style='font-size:var(--fs-2xs);color:var(--text-muted)'> {p:.0f}%</span>")
                    link = (f" <a href='{escape(r['notion_url'])}' target=_blank title='abrir no Notion' "
                            f"style='color:var(--text-faint)'>↗</a>" if r["notion_url"] else "")
                    resp = ", ".join(r["responsaveis"]) if r["responsaveis"] else ""
                    resp_html = f"<span style='color:var(--text-muted);font-size:var(--fs-2xs)'> · {escape(resp)}</span>" if resp else ""
                    linhas += (f"<div style='display:flex;gap:9px;align-items:center;flex-wrap:wrap;padding:7px 0;"
                               f"border-top:1px solid var(--border)'>"
                               f"<span class=sdot style='--c:var({var})'></span>"
                               f"<span style='flex:1;min-width:200px;font-size:var(--fs-sm)'>"
                               f"{escape(r['acao'] or r['titulo'] or '(sem ação)')}{link}{resp_html}</span>"
                               f"{prog}{prazo_html}{dep}"
                               f"<span class=chip style='--c:var({var})'>{rotulo}</span></div>")
                    for s in r["subitems"]:
                        sc = "--status-baixo" if s.get("status") == "concluida" else "--status-semdados"
                        linhas += (f"<div style='padding:3px 0 3px 28px;font-size:var(--fs-xs);color:var(--text-muted)'>"
                                   f"<span class=sdot style='--c:var({sc})'></span> {escape(s.get('titulo') or '')}</div>")
            feitos = sum(1 for r in irows if r["status"] == "concluida")
            bloco += (f"<div class=card style='margin-bottom:12px'><div style='display:flex;justify-content:space-between;"
                      f"align-items:baseline;gap:10px'><b style='font-size:var(--fs-md)'>{escape(inic)}</b>"
                      f"<span style='color:var(--text-muted);font-size:var(--fs-xs);white-space:nowrap'>"
                      f"{feitos}/{len(irows)} concluídas</span></div>{linhas}</div>")
        if um_gestor:
            html += bloco
        else:
            html += f"<section><h2>{escape(gestor)}</h2>{bloco}</section>"
    return html


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
    area = qp.get("area") or "todas"

    from ..sources.notion_initiatives import DDL
    with A._conn() as c:
        with c.cursor() as cur:
            cur.execute("INSERT INTO audit_log (actor, action, scope) VALUES (%s,'view',%s)",
                        (user, f"operacoes/iniciativas {year}Q{quarter} {area}"))
            cur.execute(DDL)
            q = """SELECT notion_id, area, titulo, responsaveis_json, prazo, status, progresso,
                          notion_url, subitems_json, iniciativa, acao, detalhamento, gestor
                     FROM notion_initiatives_cache WHERE year=%s AND quarter=%s"""
            args: list = [year, quarter]
            if area != "todas":
                q += " AND area=%s"
                args.append(area)
            cur.execute(q, args)
            rows = [{"notion_id": r[0], "area": r[1], "titulo": r[2],
                     "responsaveis": (r[3] if isinstance(r[3], list) else json.loads(r[3] or "[]")),
                     "prazo": r[4], "status": r[5],
                     "progresso": float(r[6]) if r[6] is not None else None,
                     "notion_url": r[7],
                     "subitems": (r[8] if isinstance(r[8], list) else json.loads(r[8] or "[]")),
                     "iniciativa": r[9], "acao": r[10], "detalhamento": r[11], "gestor": r[12]}
                    for r in cur.fetchall()]
            cur.execute("SELECT area, database_id, database_name FROM notion_config WHERE year=%s AND quarter=%s",
                        (year, quarter))
            cfg = {a: (d, n) for a, d, n in cur.fetchall()}
            cur.execute("""SELECT area, ok, items_count, message, created_at FROM notion_sync_log
                            WHERE year=%s AND quarter=%s ORDER BY created_at DESC LIMIT 8""", (year, quarter))
            synclog = cur.fetchall()

    # por área ou todas juntas (com cabeçalho por área)
    if area == "todas":
        corpo = ""
        for slug, nome in _AREAS_OP:
            arows = [r for r in rows if r["area"] == slug]
            if arows:
                corpo += f"<section><h2 style='color:var(--brand)'>{escape(nome)}</h2>{_render_grupos(arows, hoje)}</section>"
        if not corpo:
            corpo = _render_grupos([], hoje)
    else:
        corpo = _render_grupos(rows, hoje)

    opts_a = "".join(f"<option value='{v}' {'selected' if area == v else ''}>{lbl}</option>"
                     for v, lbl in [("todas", "todas as áreas")] + _AREAS_OP)
    opts_q = "".join(f"<option value='{q_}' {'selected' if quarter == q_ else ''}>Q{q_}</option>" for q_ in (1, 2, 3, 4))
    opts_y = "".join(f"<option value='{y}' {'selected' if year == y else ''}>{y}</option>" for y in (2025, 2026, 2027))
    form = (f"<form method=get action=/operacoes><div class=filters>"
            f"<div><label>área</label><select name=area>{opts_a}</select></div>"
            f"<div><label>trimestre</label><select name=quarter>{opts_q}</select></div>"
            f"<div><label>ano</label><select name=year>{opts_y}</select></div>"
            f"<button type=submit>Aplicar</button>"
            f"<button type=button onclick=\"syncNotion('{'' if area == 'todas' else area}')\" "
            f"style='background:var(--brand);color:#111'>Sincronizar Notion</button></div></form>")

    cfg_rows = ""
    for slug, nome in _AREAS_OP:
        did, dname = cfg.get(slug, (None, None))
        st = f"<span class=note>{escape(dname or '')}</span>" if did else "<span class=note style='color:var(--text-faint)'>não configurado</span>"
        cfg_rows += (f"<div style='display:flex;gap:8px;align-items:center;padding:7px 0;border-top:1px solid var(--border);flex-wrap:wrap'>"
                     f"<b style='width:230px;font-size:var(--fs-sm)'>{escape(nome)}</b>"
                     f"<input id='cfg-{slug}' placeholder='cole a URL da página do trimestre no Notion…' value='{escape(did or '')}' "
                     f"style='flex:1;min-width:260px;background:var(--bg-panel);border:1px solid var(--border-strong);"
                     f"border-radius:var(--radius-sm);color:var(--text);font-size:var(--fs-xs);padding:7px 9px'>"
                     f"<button class=abtn2 onclick=\"salvarCfg('{slug}')\">salvar</button>{st}</div>")

    log_html = "".join(
        f"<div class=note style='padding:3px 0'>{'✅' if ok else '⚠️'} {escape(a or '')} — "
        f"{escape(msg or '')} <span style='color:var(--text-faint)'>({ts.strftime('%d/%m %H:%M')})</span></div>"
        for a, ok, n, msg, ts in synclog) or "<div class=note>nenhuma sincronização registrada ainda</div>"

    js = ("<script>"
          f"var Y={year},Q={quarter};"
          "function syncNotion(a){var b=event.target;b.disabled=true;b.textContent='sincronizando…';"
          "fetch('/api/operacoes/initiatives/sync',{method:'POST',headers:{'Content-Type':'application/json'},"
          "body:JSON.stringify({year:Y,quarter:Q,area:a||null})}).then(function(r){return r.json();})"
          ".then(function(j){if(j.errors&&j.errors.length)alert(j.errors.join('\\n'));location.reload();})"
          ".catch(function(){alert('falha de rede');b.disabled=false;});}"
          "function salvarCfg(slug){var v=document.getElementById('cfg-'+slug).value;"
          "fetch('/api/operacoes/notion-config',{method:'POST',headers:{'Content-Type':'application/json'},"
          "body:JSON.stringify({area:slug,year:Y,quarter:Q,url:v||null})}).then(function(r){return r.json();})"
          ".then(function(j){if(!j.ok)alert(j.message||'erro');else location.reload();})"
          ".catch(function(){alert('falha de rede');});}"
          "</script><style>.abtn2{cursor:pointer;background:var(--surface-3);border:1px solid var(--border-strong);"
          "border-radius:var(--radius-sm);color:var(--text-2);font-family:var(--font-body);font-size:var(--fs-2xs);"
          "padding:6px 11px}.abtn2:hover{border-color:var(--brand);color:var(--brand)}</style>")

    content = (f"<h1>Iniciativas — Q{quarter}/{year}</h1>"
               "<div class=sub>controle das iniciativas de cada área da empresa · fonte: Notion (somente leitura, "
               "sincronizado diariamente às 06:00 e sob demanda) · semáforo por prazo e dependência sequencial</div>"
               + form + corpo +
               "<section><h2>Configuração (URL do Notion por área)</h2>"
               f"<p class=secsub>vale para Q{quarter}/{year} · cole a URL da página do trimestre (a busca encontra as "
               "databases 'Iniciativas' até 3 níveis, inclusive subpáginas por gestor) · a página precisa estar "
               "compartilhada com a integração no Notion</p>"
               + f"<div class=card>{cfg_rows}</div></section>"
               "<section><h2>Últimas sincronizações</h2>" + f"<div class=card>{log_html}</div></section>"
               + js)

    from ..sales.ui import _shell
    html = _shell(A, "operacoes", [("iniciativas", "Iniciativas")], "iniciativas", content, user)
    return HTMLResponse(html.replace("Pré-vendas · Qualificação", "Operações · Iniciativas")
                        .replace("Vendas · Fechamento", "Operações · Iniciativas"))


@router.post("/api/operacoes/notion-config")
def api_notion_config(request: Request, payload: dict = Body(...)):
    A = _deps()
    actor, role = A._require_api(request)
    if role != "admin":
        return JSONResponse({"error": "só o administrador configura o Notion"}, status_code=403)
    from ..sources.notion_initiatives import set_config
    with A._conn() as c:
        out = set_config(c, str(payload.get("area")), int(payload.get("year")),
                         int(payload.get("quarter")), payload.get("url"))
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
