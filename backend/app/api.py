"""Painel mínimo (FastAPI) — camada de SURFACE do agente de Growth.

Lê APENAS derivados do Postgres próprio (scores/alerts/motivos/auditoria); nunca
toca as fontes nem executa ação. Humano no loop: exibe e sinaliza, quem age é o
gestor. RBAC: `role` define o que se vê — admin vê tudo; gestor_growth vê só
Growth (hoje o único agente, então a mesma coisa — o filtro fica pronto p/ quando
houver mais agentes). Toda abertura do painel é auditada.

    backend/.venv/Scripts/python -m uvicorn app.api:app --port 8000
    # abre http://localhost:8000/?role=admin
"""
from __future__ import annotations

import datetime as dt
import os
import re
from html import escape
from pathlib import Path
from typing import Any

import psycopg
from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse

from .agents.growth.scoring import _top_driver, action_guideline
from .auth import (AREA_HOME, AREAS, COOKIE, ROLE_HOME, USERS, authenticate_db,
                   check_login, clear_login_fails, create_user, list_users,
                   login_blocked, make_token, record_login_fail, set_user_areas,
                   set_user_status, user_areas, verify_token)
from .db import persistence as P
from .help_texts import _hint

app = FastAPI(title="Integracomm IA — Growth", docs_url="/api/docs")


@app.on_event("startup")
def _prewarm() -> None:
    """Aquece o cache da lista do ClickUp em background já no boot — a 1ª
    geração de relatório não paga o download (~min) de ~10,8 mil tasks."""
    try:
        from .sources.clickup_activities import prewarm_clickup
        prewarm_clickup()
    except Exception:  # noqa: BLE001 — nunca bloquear o boot por causa disto
        pass
    try:
        from .sentinel import start_sentinel
        start_sentinel(_conn)  # avisos imediatos de cancelamento (30 em 30 min)
    except Exception:  # noqa: BLE001
        pass

_ROLES = {"admin", "gestor_growth"}
_ROOT = Path(__file__).resolve().parents[1].parent  # raiz do projeto (onde vive o .env)


def _load_root_env() -> None:
    """Carrega o .env da RAIZ (o uvicorn roda de backend/, o .env está um nível acima)."""
    envf = _ROOT / ".env"
    if not envf.exists():
        return
    for line in envf.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def _db_url() -> str:
    url = os.environ.get("APP_DATABASE_URL")
    if not url:
        _load_root_env()
        url = os.environ.get("APP_DATABASE_URL")
    if not url:
        raise RuntimeError("APP_DATABASE_URL não configurada")
    return url


def _conn():
    c = psycopg.connect(_db_url())
    c.autocommit = True
    return c


def _visible_agents(role: str) -> list[str]:
    # seam de RBAC: admin vê todos os agentes; papéis específicos, só o seu.
    return ["growth"] if role in ("admin", "gestor_growth") else []


# --- sessão / login ----------------------------------------------------------
_DB_USER_CACHE: dict[str, tuple[float, bool]] = {}  # e-mail -> (ts, ativo?)


def _db_user_active(email: str) -> bool:
    """Usuário do BANCO ainda está aprovado? (cache 60s — bloqueio derruba a
    sessão em até 1 min, sem custo de 1 query por clique)."""
    import time as _t
    hit = _DB_USER_CACHE.get(email)
    if hit and _t.monotonic() - hit[0] < 60:
        return hit[1]
    try:
        with _conn() as c, c.cursor() as cur:
            cur.execute("SELECT status FROM users WHERE email=%s", (email,))
            row = cur.fetchone()
        ok = bool(row and row[0] == "aprovado")
    except Exception:  # noqa: BLE001 — banco fora: não derrubar sessões válidas
        ok = True
    _DB_USER_CACHE[email] = (_t.monotonic(), ok)
    return ok


def _session(request: Request) -> tuple[str, str] | None:
    """(user, role) da sessão, ou None. Usuário do banco bloqueado perde a sessão."""
    s = verify_token(request.cookies.get(COOKIE))
    if s and s[0] not in USERS and not _db_user_active(s[0]):
        return None
    return s


_AREA_CACHE: dict[str, tuple[float, set]] = {}


def _areas_of(user: str, role: str) -> set:
    """Áreas visíveis à conta (cache 60s — mudanças do admin valem em ≤1min)."""
    import time as _t
    hit = _AREA_CACHE.get(user)
    if hit and _t.monotonic() - hit[0] < 60:
        return hit[1]
    try:
        with _conn() as c:
            areas = user_areas(c, user, role)
    except Exception:  # noqa: BLE001 — banco fora: cai no padrão do papel
        from .auth import _ROLE_AREAS
        areas = set(_ROLE_AREAS.get(role, set()))
    _AREA_CACHE[user] = (_t.monotonic(), areas)
    return areas


def _require_area(request: Request, area: str):
    """(sessão, None) com acesso à área, ou (None, redirect) adequado."""
    s = _session(request)
    if not s:
        return None, RedirectResponse("/login", status_code=302)
    user, role = s
    if role == "admin" or area in _areas_of(user, role):
        return s, None
    minhas = sorted(_areas_of(user, role))
    destino = AREA_HOME.get(minhas[0], "/login") if minhas else "/login"
    return None, RedirectResponse(destino, status_code=302)


def _require_api(request: Request) -> tuple[str, str]:
    s = _session(request)
    if not s:
        raise HTTPException(status_code=401, detail="não autenticado — faça login em /login")
    return s


_LOGIN_ERROS = {
    "1": "usuário ou senha inválidos",
    "2": "muitas tentativas — aguarde 1 minuto e tente de novo",
    "3": "sua conta está aguardando aprovação do administrador",
    "4": "conta bloqueada — fale com o administrador",
}


def _login_html(erro: str = "") -> str:
    msg = (f"<div style='color:var(--status-critico);font-size:var(--fs-sm);margin-bottom:12px'>"
           f"{_LOGIN_ERROS.get(erro, _LOGIN_ERROS['1'])}</div>") if erro else ""
    return f"""<!doctype html><html lang=pt-br><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>Integracomm IA — Entrar</title>
<link rel=preconnect href="https://fonts.googleapis.com"><link rel=preconnect href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&family=Poppins:wght@600;700&display=swap" rel=stylesheet>
<style>{_tokens_css()}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg-app);color:var(--text);font-family:var(--font-body);min-height:100vh;display:flex;align-items:center;justify-content:center}}
.card{{width:340px;background:var(--surface-1);border:1px solid var(--border-mid);border-radius:var(--radius-md);padding:28px}}
.logo{{width:26px;height:26px;border-radius:50%;background:var(--brand);position:relative;display:inline-block;vertical-align:middle}}
.logo::after{{content:"";position:absolute;width:11px;height:11px;border-radius:50%;background:var(--surface-1);top:7.5px;left:11px}}
h1{{font-family:var(--font-display);font-size:17px;font-weight:700;display:inline-block;margin:0 0 0 10px;vertical-align:middle}}
label{{display:block;font-size:var(--fs-2xs);color:var(--text-muted);text-transform:uppercase;letter-spacing:.08em;margin:16px 0 5px}}
select,input{{width:100%;background:var(--bg-panel);border:1px solid var(--border-strong);border-radius:var(--radius-sm);color:var(--text);font-family:var(--font-body);font-size:var(--fs-base);padding:9px 10px}}
select:focus,input:focus{{outline:none;border-color:var(--brand)}}
button{{width:100%;margin-top:20px;cursor:pointer;background:var(--brand);color:var(--brand-ink);border:none;border-radius:var(--radius-sm);font-family:var(--font-body);font-weight:600;font-size:var(--fs-md);padding:10px}}
.hint{{font-size:var(--fs-xs);color:var(--text-faint);margin-top:14px;line-height:1.5}}
</style></head><body>
<form class=card method=post action=/login>
  <div style="margin-bottom:18px"><span class=logo></span><h1>Integracomm IA</h1></div>
  {msg}
  <label>usuário / e-mail</label>
  <input type=text name=user placeholder="insira o e-mail..." autofocus autocomplete=username>
  <label>senha</label>
  <input type=password name=password placeholder="insira sua senha..." autocomplete=current-password>
  <button type=submit>Entrar</button>
  <div class=hint style="text-align:center;margin-top:16px">
    Primeiro acesso? <a href="/signup" style="color:var(--brand);font-weight:600;text-decoration:none">Criar sua conta</a>
  </div>
  <div class=hint>Humano no loop — a IA só sinaliza.</div>
</form></body></html>"""


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, erro: str = Query("")):
    s = _session(request)
    if s:
        return RedirectResponse(ROLE_HOME[s[1]], status_code=302)
    return HTMLResponse(_login_html(erro))


def _signup_html(erro: str = "", ok: bool = False) -> str:
    body = ""
    if ok:
        body = ("<div style='color:var(--status-baixo);font-size:var(--fs-md);line-height:1.6'>"
                "<b>Conta criada!</b><br>Ela está aguardando aprovação do administrador — "
                "você receberá o aviso do seu gestor e então poderá entrar normalmente.</div>"
                "<a href='/login' style='display:block;text-align:center;margin-top:20px;"
                "color:var(--brand);font-weight:600;text-decoration:none'>← voltar ao login</a>")
    else:
        msg = (f"<div style='color:var(--status-critico);font-size:var(--fs-sm);margin-bottom:12px'>{escape(erro)}</div>"
               if erro else "")
        body = f"""{msg}
  <label>seu nome</label>
  <input type=text name=name placeholder="Maria Silva" autofocus>
  <label>e-mail</label>
  <input type=email name=email placeholder="maria@integracomm.com.br" autocomplete=username>
  <label>área</label>
  <select name=role style="width:100%;background:var(--bg-panel);border:1px solid var(--border-strong);border-radius:var(--radius-sm);color:var(--text);font-family:var(--font-body);font-size:var(--fs-base);padding:9px 10px">
    <option value=gestor_growth>Growth / Assessoria</option>
    <option value=gestor_marketing>Marketing</option>
    <option value=gestor_prevendas>Pré-vendas</option>
    <option value=gestor_vendas>Vendas</option>
    <option value=gestor_operacoes>Operações</option>
  </select>
  <div class=hint style="margin-top:6px">A área escolhida é a inicial — o administrador pode liberar outras depois, no painel.</div>
  <label>senha (mínimo 8 caracteres)</label>
  <input type=password name=password autocomplete=new-password>
  <label>confirmar senha</label>
  <input type=password name=password2 autocomplete=new-password>
  <button type=submit>Criar conta</button>
  <div class=hint style="text-align:center;margin-top:14px">
    Já tem conta? <a href="/login" style="color:var(--brand);font-weight:600;text-decoration:none">Entrar</a>
  </div>
  <div class=hint>Sua conta entra em análise e é liberada pelo administrador.</div>"""
    return f"""<!doctype html><html lang=pt-br><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>Integracomm IA — Criar conta</title>
<link rel=preconnect href="https://fonts.googleapis.com"><link rel=preconnect href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&family=Poppins:wght@600;700&display=swap" rel=stylesheet>
<style>{_tokens_css()}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg-app);color:var(--text);font-family:var(--font-body);min-height:100vh;display:flex;align-items:center;justify-content:center}}
.card{{width:360px;background:var(--surface-1);border:1px solid var(--border-mid);border-radius:var(--radius-md);padding:28px}}
.logo{{width:26px;height:26px;border-radius:50%;background:var(--brand);position:relative;display:inline-block;vertical-align:middle}}
.logo::after{{content:"";position:absolute;width:11px;height:11px;border-radius:50%;background:var(--surface-1);top:7.5px;left:11px}}
h1{{font-family:var(--font-display);font-size:17px;font-weight:700;display:inline-block;margin:0 0 0 10px;vertical-align:middle}}
label{{display:block;font-size:var(--fs-2xs);color:var(--text-muted);text-transform:uppercase;letter-spacing:.08em;margin:14px 0 5px}}
input{{width:100%;background:var(--bg-panel);border:1px solid var(--border-strong);border-radius:var(--radius-sm);color:var(--text);font-family:var(--font-body);font-size:var(--fs-base);padding:9px 10px}}
input:focus{{outline:none;border-color:var(--brand)}}
button{{width:100%;margin-top:20px;cursor:pointer;background:var(--brand);color:var(--brand-ink);border:none;border-radius:var(--radius-sm);font-family:var(--font-body);font-weight:600;font-size:var(--fs-md);padding:10px}}
.hint{{font-size:var(--fs-xs);color:var(--text-faint);margin-top:14px;line-height:1.5}}
</style></head><body>
<form class=card method=post action=/signup>
  <div style="margin-bottom:18px"><span class=logo></span><h1>Integracomm IA — criar conta</h1></div>
  {body}
</form></body></html>"""


@app.get("/signup", response_class=HTMLResponse)
def signup_page(request: Request):
    s = _session(request)
    if s:
        return RedirectResponse(ROLE_HOME[s[1]], status_code=302)
    return HTMLResponse(_signup_html())


@app.post("/signup", response_class=HTMLResponse)
async def do_signup(request: Request):
    form = await request.form()
    email = str(form.get("email") or "")
    name = str(form.get("name") or "")
    pwd = str(form.get("password") or "")
    if pwd != str(form.get("password2") or ""):
        return HTMLResponse(_signup_html("as senhas não conferem"))
    ip = (request.client.host if request.client else "?")
    if login_blocked(f"signup|{ip}"):  # anti-spam de cadastro por IP
        return HTMLResponse(_signup_html("muitas tentativas — aguarde 1 minuto"))
    with _conn() as c:
        err = create_user(c, email, name, pwd, role=str(form.get('role') or 'gestor_growth'))
        if err:
            record_login_fail(f"signup|{ip}")
            return HTMLResponse(_signup_html(err))
        with c.cursor() as cur:
            cur.execute("INSERT INTO audit_log (actor, action, scope) VALUES (%s,'signup','painel')",
                        (email.strip().lower(),))
    return HTMLResponse(_signup_html(ok=True))


@app.post("/login")
async def do_login(request: Request):
    form = await request.form()
    user = str(form.get("user") or "").strip().lower()  # normaliza (e-mail é case-insensitive)
    pwd = str(form.get("password") or "")
    ip = (request.client.host if request.client else "?")
    key = f"{user}|{ip}"
    if login_blocked(key):  # rate-limit: 5 falhas/5min -> espera 60s
        return RedirectResponse("/login?erro=2", status_code=303)
    role = check_login(user, pwd)  # bootstrap (.env)
    erro_db = None
    if not role:
        with _conn() as c:
            role, erro_db = authenticate_db(c, user, pwd)  # multiusuário (banco)
    if not role:
        record_login_fail(key)
        q = "3" if (erro_db and "aprova" in erro_db) else ("4" if (erro_db and "bloquead" in erro_db) else "1")
        return RedirectResponse(f"/login?erro={q}", status_code=303)
    clear_login_fails(key)
    with _conn() as c, c.cursor() as cur:  # auditoria: quem entrou, quando
        cur.execute("INSERT INTO audit_log (actor, action, scope) VALUES (%s,'login','painel')", (user,))
    if user in USERS:
        home = ROLE_HOME[role]
    else:  # usuário do banco: 1ª área liberada define a home
        minhas = sorted(_areas_of(user, role))
        home = AREA_HOME.get(minhas[0], ROLE_HOME.get(role, "/login")) if minhas else ROLE_HOME.get(role, "/login")
    resp = RedirectResponse(home, status_code=303)
    resp.set_cookie(COOKIE, make_token(user, role), max_age=12 * 3600, httponly=True,
                    samesite="lax", secure=(request.url.scheme == "https"))
    return resp


@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(COOKIE)
    return resp


def _audit_view(conn: Any, role: str, scope: str = "growth/dashboard") -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO audit_log (actor, action, scope) VALUES (%s,%s,%s)",
            (f"painel:{role}", "view", scope),
        )


def _latest_scores(conn: Any) -> list[dict]:
    """Último score por conta (DISTINCT ON), com nome e motivos."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (s.account_id)
                   s.id, s.account_id, a.name, s.score, s.risk_band, s.stage,
                   s.trajectory, s.confidence, s.coverage_weeks, s.evaluable,
                   s.recommendation, s.computed_at, a.recurring_revenue, a.is_legacy
              FROM scores s JOIN accounts a ON a.id = s.account_id
             ORDER BY s.account_id, s.computed_at DESC
            """
        )
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        # contexto de execução (NÃO-pontuador): último exec_score por conta
        cur.execute(
            """SELECT DISTINCT ON (account_id) account_id, value_num, value_text
                 FROM signal_snapshots WHERE signal_key='exec_score'
                ORDER BY account_id, captured_at DESC"""
        )
        execmap = {aid: (float(v) if v is not None else None, t) for aid, v, t in cur.fetchall()}
        # severidade do alerta aberto por conta (p/ o filtro de alerta)
        cur.execute(
            """SELECT DISTINCT ON (account_id) account_id, severity FROM alerts
                WHERE status='aberto' ORDER BY account_id, created_at DESC"""
        )
        sevmap = dict(cur.fetchall())
        for r in rows:
            r["exec_score"], r["exec_motivo"] = execmap.get(r["account_id"], (None, None))
            r["alert_sev"] = sevmap.get(r["account_id"])  # None = sem alerta
        # motivos por score (psycopg3: = ANY(lista), não IN %s)
        reasons: dict[Any, list] = {}
        ids = [r["id"] for r in rows]
        if ids:
            cur.execute(
                "SELECT score_id, text, is_leading, weight FROM score_reasons "
                "WHERE score_id = ANY(%s) ORDER BY weight DESC", (ids,),
            )
            for sid, text, lead, w in cur.fetchall():
                reasons.setdefault(sid, []).append({"text": text, "leading": lead, "weight": float(w)})
    for r in rows:
        r["reasons"] = reasons.get(r["id"], [])
    return rows


def _open_alerts(conn: Any) -> list[dict]:
    from .reports import ensure_reports_table
    ensure_reports_table(conn)  # case_updates pode não existir em banco novo
    with conn.cursor() as cur:
        cur.execute("ALTER TABLE alerts ADD COLUMN IF NOT EXISTS notes TEXT")  # idempotente
        cur.execute(
            """SELECT al.id, a.name, al.severity, al.risk_band, al.stage, al.created_at,
                      al.status, al.notes, cu.text AS case_note, cu.created_at AS case_note_at,
                      cu.author AS case_note_by
                 FROM alerts al JOIN accounts a ON a.id = al.account_id
                 LEFT JOIN LATERAL (
                      SELECT text, created_at, author FROM case_updates c
                       WHERE c.account_id = al.account_id
                       ORDER BY created_at DESC LIMIT 1) cu ON TRUE
                WHERE al.status = 'aberto' ORDER BY
                  CASE al.severity WHEN 'critico' THEN 0 WHEN 'alto' THEN 1 ELSE 2 END,
                  al.created_at DESC"""
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


# --- JSON (para integração / testes) ---------------------------------------
@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/api/scores")
def api_scores(request: Request):
    """Contas monitoradas + KPIs prontos (redesenho 21/07: agregado NUNCA é
    calculado no frontend — os KPIs saem do MESMO _report_from do cockpit/
    Slack, então as telas não divergem). `squad`/`responsavel` por conta:
    mesma resolução da Análise dos Squads (espelho quando o nome não traz)."""
    _user, role = _require_api(request)
    with _conn() as c:
        scores = _latest_scores(c)
        alerts = _open_alerts(c)
    rep = _report_from(scores, alerts)
    try:
        from .sources.clickup_activities import _mirror_clientes
        _mirror = _mirror_clientes()
    except Exception:  # noqa: BLE001 — sem espelho, resolve só pelo nome
        _mirror = None
    from .sources.nps_sheets import norm_account as _norm
    # atrasos por conta: MESMAS regras dos chips da tela HTML (vencidas no
    # ClickUp; cliente pausado/concluído não conta e vem sinalizado)
    try:
        from .sources.clickup_activities import (_overdue_from_clickup as _atr,
                                                 client_inactive_status as _inat)
        _agora = dt.datetime.now(dt.timezone.utc)
    except Exception:  # noqa: BLE001
        _atr = None
    for s in scores:
        s["squad"] = _resolve_squad(s["name"], _mirror)
        gc = ((_mirror or {}).get(_norm(s["name"])) or {}).get("gerente_de_contas")
        s["responsavel"] = (gc or "").strip() or None  # lacuna conhecida: GC vazio no espelho
        s["clickup_inativo"] = None
        s["atrasadas"] = None
        if _atr is not None:
            try:
                s["clickup_inativo"] = _inat(s["name"])
                s["atrasadas"] = 0 if s["clickup_inativo"] else len(_atr(s["name"], _agora) or [])
            except Exception:  # noqa: BLE001 — conta sem match não derruba o payload
                pass
    # base do 'MRR em risco' = contas COM ALERTA ABERTO (mesma régua do
    # _report_from/cockpit — o spec do protótipo usava faixa alto|médio;
    # divergência registrada em PENDENCIAS.md p/ decisão do Otávio)
    em_risco = [s for s in scores if s.get("alert_sev")]
    kpis = {
        "monitoradas": rep["monitoradas"], "avaliaveis": rep["avaliaveis"],
        "criticos": rep["alertas"].get("critico", 0),
        "mrr_em_risco": rep["mrr_risco"],
        "mrr_em_risco_contas": sum(1 for s in em_risco if _mrr_val(s) > 0),
        "mrr_em_risco_sem_dados": sum(1 for s in em_risco if _mrr_val(s) <= 0),
        "sem_cobertura": rep["sem_dados"],
    }
    return {"agents": _visible_agents(role), "scores": _serialize(scores), "kpis": kpis}


@app.get("/api/alerts")
def api_alerts(request: Request):
    _require_api(request)
    with _conn() as c:
        alerts = _open_alerts(c)
    # kpis prontos (redesenho 21/07): frontend não conta severidade
    sev: dict[str, int] = {}
    for a in alerts:
        sev[a["severity"]] = sev.get(a["severity"], 0) + 1
    return {"alerts": _serialize(alerts),
            "kpis": {"total": len(alerts), "critico": sev.get("critico", 0),
                     "alto": sev.get("alto", 0), "atencao": sev.get("atencao", 0)}}


# --- Aprendizado de boas práticas (intervenções × desfecho) -----------------
def _top_practices(conn: Any) -> dict:
    return P.top_practices(conn)


@app.post("/api/interventions")
def api_intervention(request: Request, payload: dict = Body(...)):
    """Registra uma AÇÃO tomada com a conta. payload: {account_name | account_id,
    action_text, driver?, stage?, taken_by?, alert_id?}."""
    user, _role = _require_api(request)
    payload.setdefault("taken_by", user)
    action_text = (payload.get("action_text") or "").strip()
    if not action_text:
        return JSONResponse({"error": "action_text obrigatório"}, status_code=400)
    with _conn() as c:
        acc = payload.get("account_id")
        if not acc and payload.get("account_name"):
            with c.cursor() as cur:
                cur.execute("SELECT id FROM accounts WHERE name ILIKE %s LIMIT 1",
                            (f"%{payload['account_name']}%",))
                row = cur.fetchone()
                acc = row[0] if row else None
        if not acc:
            return JSONResponse({"error": "conta não encontrada"}, status_code=404)
        iid = P.record_intervention(
            c, account_id=str(acc), action_text=action_text,
            driver=payload.get("driver"), stage=payload.get("stage"),
            taken_by=payload.get("taken_by"), alert_id=payload.get("alert_id"),
        )
    return {"id": iid, "status": "registrada"}


@app.post("/api/interventions/{iid}/result")
def api_intervention_result(iid: str, request: Request, payload: dict = Body(...)):
    """Fecha o loop da ação: {result: retido|cancelou|sem_efeito, notes?}.
    'retido' vira boa prática citada em casos futuros com a mesma dor."""
    _require_api(request)
    result = payload.get("result")
    if result not in ("retido", "cancelou", "sem_efeito"):
        return JSONResponse({"error": "result deve ser retido|cancelou|sem_efeito"}, status_code=400)
    with _conn() as c:
        P.set_intervention_result(c, intervention_id=iid, result=result, notes=payload.get("notes"))
    return {"id": iid, "result": result}


@app.get("/api/practices")
def api_practices(request: Request):
    """Boas práticas aprendidas: por dor, a ação que mais reteve."""
    _require_api(request)
    with _conn() as c:
        pr = _top_practices(c)
    return {"practices": [{"driver": d, "action": a, "retencoes": n} for d, (a, n) in pr.items()]}


def _serialize(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        d = {}
        for k, v in r.items():
            d[k] = v.isoformat() if hasattr(v, "isoformat") else (float(v) if _is_dec(v) else v)
        out.append(d)
    return out


def _is_dec(v: Any) -> bool:
    import decimal
    return isinstance(v, decimal.Decimal)


# --- Painéis HTML ------------------------------------------------------------
# `/` = HUB central (inteligência que enxerga todas as áreas; hoje só Growth
# está ativa — as demais são placeholders da casca modular).
# `/growth` = área de Growth/Assessoria (gestor_growth ou admin).
@app.get("/", response_class=HTMLResponse)
def hub(request: Request):
    s = _session(request)
    if not s:
        return RedirectResponse("/login", status_code=302)
    user, role = s
    if role != "admin":  # RBAC: hub central é do admin; gestor vai direto à sua área
        return RedirectResponse(ROLE_HOME.get(role, "/growth"), status_code=302)
    with _conn() as c:
        _audit_view(c, user, scope="hub")
        stats = _hub_stats(c)
        mkt = _hub_mkt_stats(c)
        sales = _hub_sales_stats(c)
        ops = _hub_op_stats(c)
        grava_snapshot_risco(c)
        mudancas = _hub_mudancas(c)
        try:  # aviso discreto quando fonte crítica está VERMELHA (14/07)
            vermelhas = [r["fonte"] for r in _integracoes_status(c) if r["status"] == "vermelho"]
            if vermelhas:
                mudancas = (
                    "<div class=warn style='margin:14px 0'>⚠️ Fonte de dados parada: "
                    f"<b>{escape(' · '.join(vermelhas[:3]))}</b> — diagnósticos podem estar desatualizados. "
                    "<a href='/admin' style='color:var(--brand)'>ver Saúde das integrações</a></div>") + mudancas
        except Exception:  # noqa: BLE001
            pass
        users = list_users(c)
        # coorte do Ciclo computada UMA vez por load (impactos + lags + mini-raio-x)
        try:
            from .marketing.ui import _ciclo_coorte
            coorte = _ciclo_coorte(c)[0]
        except Exception:  # noqa: BLE001
            coorte = None
        impactos = _hub_impactos(c, mkt, sales, coorte=coorte)
        lags = _hub_lags(c, coorte=coorte)
        # 'Prioridades da Semana' (fusão Foco+Iniciativas, 17/07 noite) +
        # Camada 3 (raio-x compacto) do Cockpit
        try:
            from .semana import prioridades_hub_html
            foco_html, foco_kw = prioridades_hub_html(c, impactos, lags)
        except Exception:  # noqa: BLE001
            foco_html, foco_kw = "", []
        try:
            from .raiox import mini_cards_html
            raiox_mini = mini_cards_html(c, coorte or [])
        except Exception:  # noqa: BLE001
            raiox_mini = ""
    return HTMLResponse(_render_hub(user, stats, users, mkt, sales=sales, ops=ops,
                                    mudancas=mudancas, impactos=impactos, lags=lags,
                                    foco_html=foco_html, raiox_mini=raiox_mini,
                                    foco_kw=foco_kw))


@app.get("/admin", response_class=HTMLResponse)
def admin_panel(request: Request):
    """Painel administrativo (só admin): contas e permissões por área."""
    s = _session(request)
    if not s:
        return RedirectResponse("/login", status_code=302)
    user, role = s
    if role != "admin":
        return RedirectResponse("/growth", status_code=302)
    with _conn() as c:
        _audit_view(c, user, scope="admin")
        stats = _hub_stats(c)
        users = list_users(c)
        from .llm_budget import month_summary
        llm = month_summary(c)
        teams = _teams_html(c) + _integracoes_html(_integracoes_status(c))
        with c.cursor() as cur:
            cur.execute("""SELECT actor, count(*), max(at) FROM audit_log
                            WHERE action='view' GROUP BY actor""")
            acessos = {a: (n, ult) for a, n, ult in cur.fetchall()}
    for u in users:
        n, ult = acessos.get(u["email"], (0, None))
        u["views"], u["last_seen"] = n, (ult.strftime("%d/%m/%Y às %H:%M") if ult else None)
    return HTMLResponse(_render_hub(user, stats, users, None, page="admin", llm=llm,
                                    teams_html=teams))


@app.post("/api/admin/times")
def api_admin_times(request: Request, payload: dict = Body(...)):
    """Operações do card Times por área (adicionar / desligar / trocar função).
    Só admin; desligar NUNCA apaga — a régua histórica do funil depende."""
    actor, role = _require_api(request)
    if role != "admin":
        return JSONResponse({"error": "só o administrador gerencia os times"}, status_code=403)
    area = payload.get("area")
    action = payload.get("action")
    nome = (payload.get("nome") or "").strip()[:60]
    if area not in {a for a, _t, _n in _TEAM_AREAS} or not nome:
        return JSONResponse({"error": "área ou nome inválido"}, status_code=400)
    from . import team_config as TC
    with _conn() as c:
        if action == "add":
            TC.adicionar(c, area, nome, payload.get("papel") or "membro", actor)
        elif action == "desligar":
            TC.desligar(c, area, nome, actor)
        elif action == "papel":
            TC.definir_papel(c, area, nome, payload.get("papel") or "", actor)
        else:
            return JSONResponse({"error": "ação inválida"}, status_code=400)
    return {"ok": True}


@app.post("/api/accounts/{account_id}/outcome")
def api_account_outcome(account_id: str, request: Request, payload: dict = Body(...)):
    """Registra o DESFECHO real de uma conta (feedback loop do Growth, 14/07):
    retida | cancelada | em_negociacao. SÓ COLETA — nenhuma recalibração
    automática do modelo (decisão posterior, com volume). Auditado."""
    actor, _role = _require_api(request)
    outcome = payload.get("outcome")
    if outcome not in ("retida", "cancelada", "em_negociacao"):
        return JSONResponse({"error": "desfecho inválido"}, status_code=400)
    notes = (payload.get("notes") or "").strip()[:400] or None
    data = payload.get("date")
    with _conn() as c, c.cursor() as cur:
        cur.execute("""ALTER TABLE outcomes
                        ADD COLUMN IF NOT EXISTS recorded_by TEXT,
                        ADD COLUMN IF NOT EXISTS notes TEXT""")
        cur.execute("SELECT 1 FROM accounts WHERE id=%s", (account_id,))
        if not cur.fetchone():
            return JSONResponse({"error": "conta não encontrada"}, status_code=404)
        cur.execute("""INSERT INTO outcomes (account_id, outcome, outcome_date, source,
                                             recorded_by, notes)
                       VALUES (%s, %s, COALESCE(%s::date, CURRENT_DATE), 'manual_gestor', %s, %s)""",
                    (account_id, outcome, data, actor, notes))
        cur.execute("INSERT INTO audit_log (actor, action, scope) VALUES (%s,'outcome',%s)",
                    (actor, f"conta:{account_id}:{outcome}"))
    return {"ok": True}


def grava_snapshot_risco(conn: Any) -> None:
    """Snapshot DIÁRIO agregado do risco da carteira (série temporal do Growth,
    14/07): 1 linha/dia, upsert idempotente — chamado pela sentinela (30/30min
    no servidor) e no load do hub. A série começa a existir a partir de agora."""
    try:
        with conn.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS grw_risk_snapshot (
                dia DATE PRIMARY KEY, criticos INT, altos INT, atencao INT,
                mrr_risco NUMERIC, avaliaveis INT, gravado_em TIMESTAMPTZ DEFAULT now())""")
            cur.execute("""
                WITH ult AS (
                    SELECT DISTINCT ON (s.account_id) s.*, a.recurring_revenue AS mrr
                      FROM scores s JOIN accounts a ON a.id = s.account_id
                     ORDER BY s.account_id, s.computed_at DESC),
                ab AS (SELECT account_id, severity FROM alerts WHERE status='aberto')
                INSERT INTO grw_risk_snapshot (dia, criticos, altos, atencao, mrr_risco, avaliaveis)
                SELECT CURRENT_DATE,
                       count(*) FILTER (WHERE ab.severity='critico'),
                       count(*) FILTER (WHERE ab.severity='alto'),
                       count(*) FILTER (WHERE ab.severity='atencao'),
                       COALESCE(sum(u.mrr) FILTER (WHERE u.risk_band IN ('alto','critico')), 0),
                       count(*) FILTER (WHERE u.evaluable)
                  FROM ult u LEFT JOIN ab ON ab.account_id = u.account_id
                ON CONFLICT (dia) DO UPDATE SET criticos=EXCLUDED.criticos, altos=EXCLUDED.altos,
                    atencao=EXCLUDED.atencao, mrr_risco=EXCLUDED.mrr_risco,
                    avaliaveis=EXCLUDED.avaliaveis, gravado_em=now()""")
    except Exception:  # noqa: BLE001 — snapshot nunca derruba quem chamou
        pass


def _risco_evolucao_html(conn: Any) -> str:
    """Série do risco da carteira (grw_risk_snapshot) — 'as intervenções estão
    reduzindo o risco?'. Enquanto só houver 1 ponto, mostra a nota de início."""
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT dia, criticos, altos, atencao, mrr_risco
                             FROM grw_risk_snapshot ORDER BY dia DESC LIMIT 14""")
            pts = cur.fetchall()[::-1]
    except Exception:  # noqa: BLE001
        return ""
    if not pts:
        return ""
    _tdr = "padding:6px 8px;border-bottom:1px solid var(--border);text-align:right;font-variant-numeric:tabular-nums"
    linhas = "".join(
        f"<tr><td style='padding:6px 8px;border-bottom:1px solid var(--border)'>{d.strftime('%d/%m')}</td>"
        f"<td style='{_tdr};color:var(--status-critico)'>{c}</td>"
        f"<td style='{_tdr}'>{al}</td>"
        f"<td style='{_tdr}'>{at}</td>"
        f"<td style='{_tdr}'>R$ {float(m or 0):,.0f}</td></tr>".replace(",", ".")
        for d, c, al, at, m in pts)
    nota = ("<p class=note>Série iniciada agora (1 snapshot/dia, gravado pela sentinela) — em poucas semanas "
            "este quadro responde se as intervenções estão reduzindo o risco da carteira.</p>" if len(pts) < 5 else "")
    return ("<section><div class=sec-head><h2>Evolução do risco da carteira</h2>"
            "<span class=sub>1 snapshot por dia — alertas abertos e MRR nas faixas alto/crítico</span></div>"
            "<div class=card style='padding:12px 14px'><table style='width:100%;border-collapse:collapse'>"
            "<tr><th style='text-align:left;padding:6px 8px'>Dia</th><th style='text-align:right;padding:6px 8px'>Críticos</th>"
            "<th style='text-align:right;padding:6px 8px'>Altos</th><th style='text-align:right;padding:6px 8px'>Atenção</th>"
            "<th style='text-align:right;padding:6px 8px'>MRR em risco</th></tr>" + linhas + "</table>" + nota + "</div></section>")


def _modelo_precisao(conn: Any) -> dict | None:
    """Previsões × desfechos registrados — a medição de ROI do modelo.
    Falso positivo provável = alertada, retida SEM intervenção registrada."""
    try:
        with conn.cursor() as cur:
            cur.execute("""ALTER TABLE outcomes
                            ADD COLUMN IF NOT EXISTS recorded_by TEXT,
                            ADD COLUMN IF NOT EXISTS notes TEXT""")
            cur.execute("""
                WITH alertadas AS (
                    SELECT account_id, bool_or(severity='critico') AS critico
                      FROM alerts GROUP BY 1),
                desf AS (
                    SELECT DISTINCT ON (account_id) account_id, outcome
                      FROM outcomes ORDER BY account_id, recorded_at DESC)
                SELECT count(*),
                       count(d.outcome),
                       count(*) FILTER (WHERE d.outcome IN ('cancelou','cancelada')),
                       count(*) FILTER (WHERE d.outcome IN ('renovou','retida')),
                       count(*) FILTER (WHERE d.outcome = 'em_negociacao'),
                       count(*) FILTER (WHERE d.outcome IN ('renovou','retida') AND EXISTS
                             (SELECT 1 FROM interventions i WHERE i.account_id = al.account_id)),
                       count(*) FILTER (WHERE al.critico AND d.outcome IN ('cancelou','cancelada')),
                       count(*) FILTER (WHERE al.critico AND d.outcome IS NOT NULL),
                       COALESCE(sum(ac.recurring_revenue) FILTER (WHERE d.outcome IN ('renovou','retida')), 0)
                  FROM alertadas al
                  LEFT JOIN desf d ON d.account_id = al.account_id
                  LEFT JOIN accounts ac ON ac.id = al.account_id""")
            (alertadas, com_desf, cancel, retidas, negoc, retidas_int,
             crit_cancel, crit_desf, mrr_salvo) = cur.fetchone()
        return {"alertadas": alertadas, "com_desf": com_desf, "cancel": cancel,
                "retidas": retidas, "negoc": negoc, "retidas_int": retidas_int,
                "crit_cancel": crit_cancel, "crit_desf": crit_desf,
                "mrr_salvo": float(mrr_salvo or 0)}
    except Exception:  # noqa: BLE001 — medição nunca derruba a aba
        return None


@app.get("/api/growth/modelo")
def api_growth_modelo(request: Request):
    """Precisão do modelo + série do risco da carteira (redesenho, ajuste do
    Lote 1 — Otávio 21/07: campos de consulta eventual, fora do dia a dia).
    Reusa _modelo_precisao e a MESMA tabela grw_risk_snapshot da tela HTML."""
    _require_api(request)
    with _conn() as c:
        grava_snapshot_risco(c)
        modelo = _modelo_precisao(c)
        with c.cursor() as cur:
            cur.execute("""SELECT dia, criticos, altos, atencao, mrr_risco
                             FROM grw_risk_snapshot ORDER BY dia DESC LIMIT 14""")
            risco = [{"dia": d.strftime("%d/%m"), "criticos": cr, "altos": al,
                      "atencao": at, "mrr_risco": float(m or 0)}
                     for d, cr, al, at, m in cur.fetchall()[::-1]]
    return {"modelo": modelo, "risco": risco}


def _modelo_html(m: dict | None) -> str:
    if m is None:
        return ""
    corpo = (
        f"<div class=kpis>"
        f"<div class=kpi><div class=n>{m['alertadas']}</div><div class=l>contas alertadas (histórico)</div></div>"
        f"<div class=kpi><div class=n>{m['com_desf']}</div><div class=l>com desfecho registrado</div></div>"
        f"<div class=kpi><div class=n>{(m['crit_cancel'] / m['crit_desf'] * 100 if m['crit_desf'] else 0):.0f}%</div>"
        f"<div class=l>acerto em críticas</div><div class=s>cancelaram ÷ críticas c/ desfecho</div></div>"
        f"<div class=kpi><div class=n>{(m['retidas'] / m['com_desf'] * 100 if m['com_desf'] else 0):.0f}%</div>"
        f"<div class=l>retenção pós-alerta</div><div class=s>{m['retidas_int']} com intervenção registrada</div></div>"
        f"<div class=kpi><div class=n>R$ {m['mrr_salvo']:,.0f}</div><div class=l>MRR retido pós-alerta</div>"
        f"<div class=s>o argumento de ROI da ferramenta</div></div></div>".replace(",", "."))
    if not m["com_desf"]:
        corpo += ("<p class=note>Ainda sem desfechos registrados — use o seletor <b>desfecho…</b> na aba Contas "
                  "quando uma conta alertada cancelar, for retida ou entrar em negociação. Com volume, esta seção "
                  "vira a régua de precisão do modelo (nenhuma recalibração automática por enquanto — só medir).</p>")
    else:
        corpo += (f"<p class=note>Retidas SEM intervenção registrada = possível falso positivo "
                  f"({m['retidas'] - m['retidas_int']} caso(s)) — confirme antes de concluir; "
                  f"em negociação: {m['negoc']}.</p>")
    return ("<section><div class=sec-head><h2>Precisão do modelo</h2>"
            "<span class=sub>previsões × desfechos reais — registre desfechos na aba Contas</span></div>"
            + corpo + "</section>")


@app.post("/api/users/{user_id}/status")
def api_user_status(user_id: str, request: Request, payload: dict = Body(...)):
    """Aprova/bloqueia uma conta criada no cadastro. Só admin."""
    actor, role = _require_api(request)
    if role != "admin":
        return JSONResponse({"error": "só o administrador gerencia contas"}, status_code=403)
    status = payload.get("status")
    with _conn() as c:
        ok = set_user_status(c, user_id, status or "", actor)
        if ok:
            with c.cursor() as cur:
                cur.execute("INSERT INTO audit_log (actor, action, scope) VALUES (%s,%s,%s)",
                            (actor, "user_status", f"usuario:{user_id}:{status}"))
    _DB_USER_CACHE.clear()  # bloqueio/aprovação vale imediatamente
    return {"ok": ok} if ok else JSONResponse({"error": "status inválido ou usuário não encontrado"},
                                              status_code=400)


@app.post("/api/users/{user_id}/areas")
def api_user_areas(user_id: str, request: Request, payload: dict = Body(...)):
    """Define as ÁREAS que a conta enxerga (checkboxes do hub). Só admin."""
    actor, role = _require_api(request)
    if role != "admin":
        return JSONResponse({"error": "só o administrador gerencia contas"}, status_code=403)
    areas = payload.get("areas")
    if not isinstance(areas, list):
        return JSONResponse({"error": "areas (lista de slugs) é obrigatório"}, status_code=400)
    with _conn() as c:
        ok = set_user_areas(c, user_id, [str(a) for a in areas])
        if ok:
            with c.cursor() as cur:
                cur.execute("INSERT INTO audit_log (actor, action, scope) VALUES (%s,%s,%s)",
                            (actor, "user_areas", f"usuario:{user_id}:{','.join(sorted(map(str, areas)))}"))
    _AREA_CACHE.clear()  # mudança de acesso vale imediatamente
    return {"ok": ok} if ok else JSONResponse({"error": "usuário não encontrado"}, status_code=400)


@app.get("/growth", response_class=HTMLResponse)
def dashboard(request: Request, view: str = Query("contas")):
    s, redir = _require_area(request, "growth")
    if redir:
        return redir
    user, role = s
    if view not in ("contas", "alertas", "playbooks", "relatorios", "cancelamentos", "carga"):
        view = "contas"
    # redesenho (migração rota a rota): view migrada+habilitada entrega o SPA
    from . import spa as _spa_mod
    _spa_resp = _spa_mod.view_response(request, "growth", view)
    if _spa_resp is not None:
        return _spa_resp
    with _conn() as c:
        _audit_view(c, user, scope=f"growth/{view}")
        scores = _latest_scores(c)
        alerts = _open_alerts(c)
        practices = _top_practices(c)
        interventions = _recent_interventions(c) if view == "playbooks" else None
        cancel = _cancel_rows(c) if view == "cancelamentos" else None
        modelo = _modelo_precisao(c) if view == "alertas" else None
        evolucao = ""
        if view == "alertas":
            grava_snapshot_risco(c)
            evolucao = _risco_evolucao_html(c)
        base_bundle = None
        if view == "cancelamentos":
            with c.cursor() as cur:
                cur.execute("""SELECT COALESCE(substring(name FROM 'B[1-5]'), 'outros'), count(*)
                                 FROM accounts GROUP BY 1""")
                base_bundle = dict(cur.fetchall())
    return HTMLResponse(_render(role, scores, alerts, practices, view=view,
                                interventions=interventions, cancel=cancel, usermail=user,
                                request=request, base_bundle=base_bundle, modelo=modelo,
                                evolucao=evolucao))


def _recent_interventions(conn: Any, limit: int = 20) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT a.name, i.action_text, i.result, i.taken_at, i.driver
                 FROM interventions i JOIN accounts a ON a.id = i.account_id
                ORDER BY i.taken_at DESC LIMIT %s""", (limit,))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


@app.post("/api/reports/send-slack")
def api_report_send_slack(request: Request):
    """Envia o relatório do estado atual ao grupo do Slack (webhook do .env).
    Ação deliberada do usuário logado; auditada."""
    from .slack import send_text, webhook_configured

    user, _role = _require_api(request)
    if not webhook_configured():
        return JSONResponse({"error": "SLACK_WEBHOOK_URL não configurada no .env"}, status_code=503)
    with _conn() as c:
        text = _report_text(_report_from(_latest_scores(c), _open_alerts(c)))
    try:
        send_text(text)
    except Exception as e:  # noqa: BLE001 — reporta falha do webhook ao usuário
        return JSONResponse({"error": f"falha no envio: {type(e).__name__}"}, status_code=502)
    with _conn() as c, c.cursor() as cur:
        cur.execute("INSERT INTO audit_log (actor, action, scope) VALUES (%s,%s,%s)",
                    (user, "report_slack", "slack:webhook"))
    return {"status": "enviado"}


@app.get("/api/reports/summary")
def api_report_summary(request: Request, format: str = Query("json")):
    """Relatório do estado atual. `?format=text` = payload pronto p/ Slack."""
    _require_api(request)
    with _conn() as c:
        scores = _latest_scores(c)
        alerts = _open_alerts(c)
    rep = _report_from(scores, alerts)
    if format == "text":
        return PlainTextResponse(_report_text(rep), media_type="text/plain; charset=utf-8")
    return rep


def _hub_stats(conn: Any) -> dict:
    """Agregados da empresa para o hub (hoje = Growth; cross-área quando houver +áreas)."""
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM (SELECT DISTINCT ON (account_id) evaluable FROM scores ORDER BY account_id, computed_at DESC) t")
        monitored = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM (SELECT DISTINCT ON (account_id) evaluable FROM scores ORDER BY account_id, computed_at DESC) t WHERE evaluable")
        evaluable = cur.fetchone()[0]
        cur.execute("SELECT severity, count(*) FROM alerts WHERE status='aberto' GROUP BY 1")
        sev = dict(cur.fetchall())
        cur.execute("""SELECT COALESCE(sum(a.recurring_revenue),0) FROM accounts a
                       WHERE a.recurring_revenue IS NOT NULL
                         AND EXISTS (SELECT 1 FROM alerts al WHERE al.account_id=a.id AND al.status='aberto')""")
        mrr_risk = float(cur.fetchone()[0] or 0)
        cur.execute("""SELECT COALESCE(sum(a.recurring_revenue),0) FROM accounts a
                       WHERE a.recurring_revenue IS NOT NULL
                         AND EXISTS (SELECT 1 FROM alerts al WHERE al.account_id=a.id
                                     AND al.status='aberto' AND al.severity='critico')""")
        mrr_crit = float(cur.fetchone()[0] or 0)
        cur.execute("""SELECT count(*) FROM (SELECT DISTINCT ON (account_id) evaluable FROM scores
                       ORDER BY account_id, computed_at DESC) t WHERE NOT evaluable""")
        non_eval = cur.fetchone()[0]
        # sem cobertura HÁ MAIS DE 30 DIAS na base = problema real; conta nova
        # ainda em rampa de dados é esperado e não vira iniciativa (Otávio 16/07)
        cur.execute("""SELECT count(*) FROM (SELECT DISTINCT ON (account_id) account_id, evaluable
                         FROM scores ORDER BY account_id, computed_at DESC) t
                        JOIN accounts a ON a.id = t.account_id
                       WHERE NOT t.evaluable AND a.created_at < now() - interval '30 days'""")
        non_eval_antigas = cur.fetchone()[0]
        cur.execute("""SELECT count(DISTINCT s.account_id) FROM signal_snapshots s
                       WHERE s.signal_key='exec_score' AND s.value_num < 70""")
        exec_late = cur.fetchone()[0]
    return {"monitored": monitored, "evaluable": evaluable, "sev": sev,
            "mrr_risk": mrr_risk, "mrr_crit": mrr_crit, "non_eval": non_eval,
            "non_eval_antigas": non_eval_antigas, "exec_late": exec_late}


def _hub_mkt_stats(conn: Any) -> dict | None:
    """Resumo do mês corrente da área de Marketing p/ o hub — realizado (coorte
    Pipedrive + gasto de mídia) × plano da planilha de metas (mkt_plan_*)."""
    try:
        from .marketing.ui import _dias_mes, _funil_oficial, _plan_funil
        hoje = dt.date.today()
        mes = hoje.replace(day=1)
        plan = _plan_funil(conn, [mes]).get(mes) or {}
        passou, booked, total, _rec = _funil_oficial(conn, mes, hoje)
        with conn.cursor() as cur:
            cur.execute("SELECT COALESCE(sum(spend),0) FROM mkt_insights_daily WHERE date >= %s", (mes,))
            gasto = float(cur.fetchone()[0] or 0)
            cur.execute("SELECT verba FROM mkt_plan_channels WHERE mes=%s AND canal='META'", (mes,))
            r = cur.fetchone()
            verba = float(r[0]) if r and r[0] is not None else None
        if not plan and not total:
            return None

        def meta(etapa):
            v = (plan.get(etapa) or {}).get("qtde")
            return float(v) if v else None

        return {"mes": mes, "frac": min(1.0, hoje.day / _dias_mes(mes)),
                "leads": total, "leads_meta": meta("Lead"),
                "oport": passou[4], "oport_meta": meta("Oportunidade"),
                "book": booked, "book_meta": meta("Booking"),
                "gasto": gasto, "verba": verba,
                "cpl": gasto / total if total and gasto else None,
                "cpl_alvo": (plan.get("Lead") or {}).get("custo"),
                # CAC blended do mês: gasto de mídia ÷ contratos fechados (todos
                # os canais) — visão de eficiência p/ o card do hub (16/07)
                "cac": gasto / booked if booked and gasto else None}
    except Exception:  # noqa: BLE001 — marketing sem cache não derruba o hub
        return None


def _hub_sales_stats(conn: Any) -> dict | None:
    """Resumo do mês de PRÉ-VENDAS e VENDAS p/ o hub — mesma régua das áreas
    (evento no período, corte de Brasília; metas de vendas da mkt_goals)."""
    try:
        hoje = dt.date.today()
        mes = hoje.replace(day=1)
        a, b = f"{mes} 00:00-03", f"{hoje + dt.timedelta(days=1)} 00:00-03"
        mes_ant = (mes - dt.timedelta(days=1)).replace(day=1)
        a_ant, b_ant = f"{mes_ant} 00:00-03", f"{mes} 00:00-03"
        # PRÉ-VENDAS: leads e SQL (régua OFICIAL do funil — deal na mão de
        # closer = agendou) vs mês anterior; mesmos números da aba /prevendas
        from .marketing.ui import _funil_oficial
        passou, _bk, leads, _rc = _funil_oficial(conn, mes, hoje)
        passou_ant, _bk2, leads_ant, _rc2 = _funil_oficial(conn, mes_ant, mes - dt.timedelta(days=1))
        reunioes, reunioes_ant = passou[3], passou_ant[3]
        with conn.cursor() as cur:
            # speed-to-lead do mês (mediana) + leads ainda sem 1º contato
            cur.execute("""SELECT percentile_cont(0.5) WITHIN GROUP
                                  (ORDER BY EXTRACT(epoch FROM t.first_at - d.add_time) / 60),
                                  count(*) FILTER (WHERE t.deal_id IS NULL)
                             FROM mkt_deals_attribution d
                             LEFT JOIN sales_first_touch t ON t.deal_id = d.deal_id
                            WHERE d.add_time >= %s AND d.add_time < %s""", (a, b))
            speed_med, sem_toque = cur.fetchone()
            # VENDAS: fechados + receita (VALOR custom, fallback value), pipeline
            cur.execute("""SELECT count(*), COALESCE(sum(COALESCE(valor_custom, valor)), 0)
                             FROM mkt_deals_attribution
                            WHERE status='won' AND won_time >= %s AND won_time < %s""", (a, b))
            book, receita = cur.fetchone()
            cur.execute("SELECT count(*) FROM mkt_deals_attribution WHERE status='open' AND stage_id IN (6, 5, 7)")
            pipeline = cur.fetchone()[0]
            cur.execute("""SELECT COALESCE(sum(meta_qtde), 0), COALESCE(sum(meta_valor), 0)
                             FROM mkt_goals WHERE mes=%s AND plano <> 'total'""", (mes,))
            meta_q, meta_v = cur.fetchone()
        return {"leads": leads, "reunioes": reunioes,
                "taxa": reunioes / leads if leads else None,
                "taxa_ant": reunioes_ant / leads_ant if leads_ant else None,
                "speed_med": float(speed_med) if speed_med is not None else None,
                "sem_toque": sem_toque, "tem_touch": speed_med is not None,
                "book": book, "receita": float(receita or 0), "pipeline": pipeline,
                "book_meta": float(meta_q or 0) or None, "receita_meta": float(meta_v or 0) or None}
    except Exception:  # noqa: BLE001 — tabelas de vendas ausentes não derrubam o hub
        return None


def _growth_help(view: str, content: str) -> str:
    from .help_texts import inject_help
    # 'seu foco desta semana' no topo do Growth (Ações da Semana, 17/07)
    try:
        from .semana import foco_time_html
        with _conn() as c:
            content = foco_time_html(c, "growth") + content
    except Exception:  # noqa: BLE001 — banner nunca derruba a área
        pass
    return inject_help("growth", view, content)


def _fmt_brl(v: float) -> str:
    return f"R$ {v:,.0f}".replace(",", ".")


def _fmt_date_br(v: Any) -> str:
    """Data para EXIBIÇÃO no padrão DD-MM-AAAA (decisão do Otávio, 2026-07-03).
    O dado interno (banco/JSON/API) permanece ISO — ordena e consulta certo."""
    s = str(v)[:10]
    try:
        return dt.date.fromisoformat(s).strftime("%d-%m-%Y")
    except ValueError:
        return s


def _users_html(users: list[dict]) -> str:
    """Seção de contas do painel (hub, admin): pendentes primeiro, com ações."""
    if not users:
        return "<div class='id_'>nenhuma conta criada ainda — os gestores usam “Criar sua conta” na tela de login</div>"
    _UST = {"pendente": "--status-medio", "aprovado": "--status-baixo", "bloqueado": "--status-critico"}
    rows = ""
    for u in users:
        acts = ""
        if u["status"] != "aprovado":
            acts += f"<button class=abtn onclick=\"userSt('{u['id']}','aprovado')\">aprovar</button> "
        if u["status"] != "bloqueado":
            acts += f"<button class=abtn onclick=\"userSt('{u['id']}','bloqueado')\">bloquear</button>"
        chks = "".join(
            f"<label class=uchk><input type=checkbox data-uid='{u['id']}' value='{slug}' "
            f"{'checked' if slug in (u.get('areas') or []) else ''}>{nome.split(' /')[0]}</label>"
            for slug, nome in AREAS.items())
        areas_ui = (f"<div class='uareas'>{chks}"
                    f"<button class=abtn onclick=\"userAreas('{u['id']}')\">salvar áreas</button></div>")
        rows += (f"<div class='urow'><div><b>{escape(u['name'][:30])}</b>"
                 f"<span style='color:var(--text-muted)'> · {escape(u['email'][:36])}</span></div>"
                 f"<div>{_chip(u['status'], _UST.get(u['status'], '--status-semdados'))}</div>"
                 f"<div class='uacts'>{acts}</div>"
                 f"{areas_ui}</div>")
    js = ("<script>function userSt(id,st){if(st==='bloqueado'&&!confirm('Bloquear esta conta?'))return;"
          "fetch('/api/users/'+id+'/status',{method:'POST',headers:{'Content-Type':'application/json'},"
          "body:JSON.stringify({status:st})}).then(function(r){return r.json();})"
          ".then(function(j){if(j.error)alert(j.error);else location.reload();})"
          ".catch(function(){alert('falha de rede');});}"
          "function userAreas(id){var areas=[].slice.call(document.querySelectorAll(\"input[data-uid='\"+id+\"']:checked\")).map(function(c){return c.value;});"
          "fetch('/api/users/'+id+'/areas',{method:'POST',headers:{'Content-Type':'application/json'},"
          "body:JSON.stringify({areas:areas})}).then(function(r){return r.json();})"
          ".then(function(j){if(j.error)alert(j.error);else location.reload();})"
          ".catch(function(){alert('falha de rede');});}</script>"
          "<style>.urow{display:grid;grid-template-columns:minmax(240px,1fr) 110px 170px;gap:6px 10px;"
          ".uareas{grid-column:1/-1;display:flex;gap:12px;align-items:center;flex-wrap:wrap;padding:2px 0 6px;font-size:var(--fs-xs);color:var(--text-2)}"
          ".uchk{display:inline-flex;gap:5px;align-items:center;cursor:pointer}"
          ".uchk input{accent-color:var(--brand)}"
          "align-items:center;padding:8px 0;border-top:1px solid var(--border);font-size:var(--fs-sm)}"
          ".urow:first-child{border-top:none}"
          ".abtn{cursor:pointer;background:var(--surface-3);border:1px solid var(--border-strong);"
          "border-radius:var(--radius-sm);color:var(--text-2);font-family:var(--font-body);"
          "font-size:var(--fs-2xs);padding:4px 9px}.abtn:hover{border-color:var(--brand);color:var(--brand)}</style>")
    return rows + js


_LLM_FEATURE_LABEL = {
    "growth:tom_claude": "Growth · análise de tom das conversas",
    "growth:plano_acao": "Growth · plano de ação individual (relatórios)",
    "marketing:criativos": "Marketing · ideias de criativos",
    "especialista": "Agentes especialistas (todas as áreas)",
}


def _llm_budget_html(llm: dict | None) -> str:
    """Medidor do orçamento mensal de IA (US$ 20 carregados; teto de segurança
    LLM_BUDGET_USD). Fonte: tabela llm_usage — custo REAL por chamada."""
    if llm is None:
        return ""
    spent, cap, pct = llm["spent_usd"], llm["cap_usd"], min(1.0, llm["pct"])
    cor = "--status-baixo" if pct < 0.7 else ("--status-medio" if pct < 0.9 else "--status-critico")
    linhas = ""
    for f in llm["por_funcao"]:
        nome = _LLM_FEATURE_LABEL.get(f["feature"], f["feature"])
        linhas += (f"<div style='display:flex;justify-content:space-between;gap:12px;padding:5px 0;"
                   f"border-top:1px solid var(--border);font-size:var(--fs-xs);color:var(--text-2)'>"
                   f"<span>{escape(nome)} · {f['chamadas']} chamada(s)</span>"
                   f"<span style='font-variant-numeric:tabular-nums'>US$ {f['cost_usd']:.2f}</span></div>")
    if not linhas:
        linhas = ("<div style='padding:5px 0;font-size:var(--fs-xs);color:var(--text-muted)'>"
                  "nenhuma chamada à IA neste mês ainda</div>")
    return (
        "<section><h2>Consumo de IA (Claude) no mês</h2>"
        "<p class=secsub>custo real por chamada, todas as áreas · ao atingir o teto as chamadas são "
        "bloqueadas automaticamente e os recursos caem no modo determinístico</p>"
        "<div class=central style='max-width:560px'>"
        f"<div style='display:flex;justify-content:space-between;align-items:baseline'>"
        f"<b style='font-size:var(--fs-lg)'>US$ {spent:.2f}</b>"
        f"<span style='color:var(--text-muted);font-size:var(--fs-xs)'>teto US$ {cap:.2f} ({pct * 100:.0f}%)</span></div>"
        f"<div style='height:8px;background:var(--surface-3);border-radius:4px;overflow:hidden;margin:8px 0 10px'>"
        f"<div style='height:100%;width:{pct * 100:.1f}%;background:var({cor});border-radius:4px'></div></div>"
        + linhas + "</div></section>")


_TEAM_AREAS = [("prevendas", "Pré-vendas",
                "destaque e planos de ação da aba Desempenho Individual"),
               ("vendas", "Vendas",
                "⚠ a lista (todas as funções) é a RÉGUA do SQL do funil oficial — equivalente ao SQL_CLOSERS do dashboard do time")]
_PAPEL_LBL = {"membro": "Membro do time", "coordenacao": "Coordenação", "gerencia": "Gerência"}


def _integracoes_status(conn: Any) -> list[dict]:
    """Saúde das INTEGRAÇÕES (14/07): última sync por fonte + semáforo.
    Janelas generosas p/ não gritar de madrugada (sync horário roda 8-21h).
    verde = dentro do esperado · amarelo = atrasado · vermelho = parado/falhou."""
    import datetime as _dt
    agora = _dt.datetime.now(_dt.timezone.utc)
    hoje = _dt.date.today()

    def idade_h(ts):
        if ts is None:
            return None
        if isinstance(ts, _dt.date) and not isinstance(ts, _dt.datetime):
            return (hoje - ts).days * 24
        return (agora - ts).total_seconds() / 3600

    def farol(h, verde, vermelho):
        if h is None:
            return "vermelho"
        return "verde" if h <= verde else ("amarelo" if h <= vermelho else "vermelho")
    out: list[dict] = []

    def add(nome, ts, verde, vermelho, detalhe="", forcar=None):
        h = idade_h(ts)
        out.append({"fonte": nome, "ultima": ts, "h": h,
                    "status": forcar or farol(h, verde, vermelho), "detalhe": detalhe})
    with conn.cursor() as cur:
        cur.execute("SELECT max(updated_at) FROM mkt_deals_attribution")
        add("Pipedrive · deals (cache Lovable)", cur.fetchone()[0], 14, 36,
            "sync horário 8-21h via cache do time")
        cur.execute("SELECT max(synced_at) FROM mkt_flow_synced")
        add("Pipedrive · histórico de etapas (/flow)", cur.fetchone()[0], 30, 60,
            "enriquecimento incremental, teto 400/dia")
        for canal, rot in (("meta", "Meta Ads · mídia"), ("google", "Google Ads · mídia")):
            cur.execute("SELECT max(date) FROM mkt_insights_daily WHERE canal=%s", (canal,))
            add(rot, cur.fetchone()[0], 30, 60, "insights diários de gasto/leads")
        cur.execute("SELECT max(computed_at) FROM scores")
        ts = cur.fetchone()[0]
        add("WhatsApp · rodada de análise (Growth)", ts, 30, 60,
            "carimbo = fim da janela analisada; rodada 06h no servidor")
        cur.execute("SELECT max(updated_at) FROM sales_first_touch")
        add("Pipedrive · atividades (1º contato)", cur.fetchone()[0], 36, 72,
            "base do Speed-to-Lead")
        try:
            cur.execute("SELECT max(gravado_em) FROM grw_risk_snapshot")
            add("Sentinela (30/30min no servidor)", cur.fetchone()[0], 2, 26,
                "grava o snapshot diário de risco")
        except Exception:  # noqa: BLE001
            pass
        cur.execute("SELECT created_at, ok, message FROM notion_sync_log ORDER BY created_at DESC LIMIT 1")
        r = cur.fetchone()
        if r:
            add("Notion · iniciativas (Operações)", r[0], 30, 60,
                ("OK" if r[1] else f"ERRO: {str(r[2] or '')[:60]}"),
                forcar=(None if r[1] else "vermelho"))
        else:
            add("Notion · iniciativas (Operações)", None, 30, 60, "nenhum sync registrado")
        cur.execute("SELECT max(mes) FROM grw_cancelamentos")
        mes_c = cur.fetchone()[0]
        st_c = "verde" if (mes_c and mes_c >= hoje.replace(day=1)) else (
            "amarelo" if (mes_c and (hoje.replace(day=1) - mes_c).days <= 62) else "vermelho")
        add("Planilha · cancelamentos", mes_c, 1, 1, "granularidade mensal", forcar=st_c)
        # cobertura (não entram no semáforo — são qualidade, não frescor)
        cur.execute("""SELECT count(*) FILTER (WHERE origem IS NOT NULL AND origem <> ''), count(*)
                         FROM mkt_deals_attribution WHERE add_time >= now() - interval '30 days'""")
        c_org, t_org = cur.fetchone()
        cur.execute("""SELECT count(*) FILTER (WHERE evaluable), count(*) FROM (
                         SELECT DISTINCT ON (account_id) evaluable FROM scores
                          ORDER BY account_id, computed_at DESC) u""")
        c_ev, t_ev = cur.fetchone()
    out.append({"fonte": "_cobertura", "ultima": None, "h": None, "status": "",
                "detalhe": f"{c_org / t_org * 100:.0f}% dos deals (30d) com origem atribuída · "
                           f"{c_ev / t_ev * 100:.0f}% das contas com conversa avaliável" if t_org and t_ev else ""})
    return out


_FAROL_VAR = {"verde": "--status-baixo", "amarelo": "--status-medio", "vermelho": "--status-critico"}


def _integracoes_html(rows: list[dict]) -> str:
    cob = next((r["detalhe"] for r in rows if r["fonte"] == "_cobertura"), "")
    _td = "padding:7px 9px;border-bottom:1px solid var(--border);font-size:var(--fs-sm)"
    linhas = ""
    for r in rows:
        if r["fonte"] == "_cobertura":
            continue
        ts = r["ultima"]
        quando = "—"
        if ts is not None:
            quando = ts.strftime("%d/%m %H:%M") if hasattr(ts, "hour") else ts.strftime("%d/%m/%Y")
            if r["h"] is not None:
                quando += f" <span style='color:var(--text-faint)'>(há {r['h'] / 24:.1f} d)</span>" if r["h"] >= 48 \
                    else f" <span style='color:var(--text-faint)'>(há {r['h']:.0f} h)</span>"
        linhas += (f"<tr><td style='{_td}'><span class=sdot style='--c:var({_FAROL_VAR.get(r['status'], '--status-semdados')})'></span> "
                   f"<b>{escape(r['fonte'])}</b></td>"
                   f"<td style='{_td};text-align:right;white-space:nowrap'>{quando}</td>"
                   f"<td style='{_td};color:var(--text-muted)'>{escape(r['detalhe'])}</td></tr>")
    return ("<section><h2>Saúde das integrações</h2>"
            "<p class=secsub>última sincronização por fonte · verde = dentro do esperado, amarelo = atrasada, vermelho = parada/falhou — "
            "fonte quebrada em silêncio = gestor decidindo com dado velho</p>"
            + _hint("Saúde das integrações",
                    "O que mostra: cada fonte de dados que alimenta o painel, com a última atualização e o prazo esperado dela.\n"
                    "Como ler: cada fonte tem seu ritmo normal — os negócios do Pipedrive atualizam de hora em hora (8h às 21h); mídia e a rodada de scores são diárias; a planilha de cancelamentos é mensal. Verde = atualizou dentro do esperado; amarelo = atrasada; vermelho = parada ou com falha.\n"
                    "Fique de olho: (1) VERMELHO = os números daquela área podem estar velhos — a central mostra um aviso com link para cá; (2) amarelo que persiste = investigar antes que vire vermelho (senha de acesso vencendo, formato dos dados mudou); (3) a cobertura no rodapé mede a QUALIDADE do dado (ex.: % de negócios com origem preenchida) — atualização verde com cobertura baixa ainda é problema, só que de preenchimento na fonte.")
            + "<div class=central style='padding:6px 14px 12px'><table style='width:100%;border-collapse:collapse'>"
            "<tr><th style='text-align:left;padding:7px 9px'>Fonte</th><th style='text-align:right;padding:7px 9px'>Última sync</th>"
            "<th style='text-align:left;padding:7px 9px'>Detalhe</th></tr>"
            + linhas + "</table>"
            + (f"<p class=note style='margin:10px 0 0'>Cobertura: {escape(cob)}.</p>" if cob else "")
            + "</div></section>")


def _teams_html(conn) -> str:
    """Times por área (tabela area_team): visualização com nome + função e
    modo de edição (adicionar, trocar função, desligar com confirmação — que
    avisa se a pessoa ainda está ATIVA no Pipedrive). Desligados não aparecem
    (detecção automática via Pipedrive; manuais idem) mas ficam na régua."""
    from .team_config import eh_desligado, listas, status_pipedrive
    blocos = ""
    for area, titulo, nota in _TEAM_AREAS:
        linhas = ""
        for nome, _ativo, papel in listas(conn, area):
            if eh_desligado(conn, area, nome):
                continue
            pd = status_pipedrive(conn, nome)
            pd_dot = {"ativo": ("var(--status-baixo)", "ativo no Pipedrive"),
                      "desativado": ("var(--status-critico)", "desativado no Pipedrive"),
                      "sem dados": ("var(--text-faint)", "sem deals no nome ainda")}[pd]
            opts = "".join(f"<option value='{v}' {'selected' if v == papel else ''}>{lbl}</option>"
                           for v, lbl in _PAPEL_LBL.items())
            chip_papel = ("" if papel == "membro" else
                          f" <span class=chip style='--c:var(--brand)'>{_PAPEL_LBL[papel].lower()}</span>")
            linhas += (
                f"<tr data-area='{area}'>"
                f"<td><span title='{pd_dot[1]}' style='display:inline-block;width:8px;height:8px;border-radius:50%;"
                f"background:{pd_dot[0]};margin-right:8px'></span><b>{escape(nome)}</b>{chip_papel}</td>"
                f"<td class='tm-view' style='color:var(--text-muted)'>{_PAPEL_LBL[papel]}</td>"
                f"<td class='tm-edit' style='display:none'>"
                f"<select onchange=\"tmPapel('{area}',this)\" data-nome=\"{escape(nome)}\">{opts}</select></td>"
                f"<td class='tm-edit' style='display:none;text-align:right'>"
                f"<button class=abtn style='border-color:var(--status-critico);color:var(--status-critico)' "
                f"onclick=\"tmDesligar('{area}',this)\" data-nome=\"{escape(nome)}\" data-pd='{pd}'>desligar</button></td></tr>")
        blocos += (
            f"<div style='flex:1;min-width:300px'>"
            f"<div style='display:flex;justify-content:space-between;align-items:baseline;gap:10px'>"
            f"<b style='font-size:var(--fs-md)'>{titulo}</b>"
            f"<button class='abtn tm-view' onclick=\"tmEditar(true)\">✎ editar</button>"
            f"<button class='abtn tm-edit' style='display:none' onclick=\"tmEditar(false)\">concluir edição</button></div>"
            f"<p class=secsub style='margin:4px 0 8px'>{nota}</p>"
            f"<table class=tmtbl>{linhas}</table>"
            f"<div class='tm-edit' style='display:none;margin-top:10px'>"
            f"<div class=filters><input id='tm-nome-{area}' placeholder='nome como está no Pipedrive' "
            f"style='flex:1;min-width:170px'>"
            f"<select id='tm-papel-{area}'>" + "".join(f"<option value='{v}'>{lbl}</option>" for v, lbl in _PAPEL_LBL.items())
            + f"</select><button class=abtn onclick=\"tmAdd('{area}')\">+ adicionar</button></div></div></div>")
    return ("<section><h2>Times por área</h2>"
            "<p class=secsub>quem compõe cada time e a função de cada um · o ponto indica a situação do usuário no Pipedrive · "
            "✎ editar libera: trocar função (promoção), desligar (com confirmação; some das telas, números preservados nas réguas) e adicionar colaborador</p>"
            + _hint("Times por área",
                    "O que mostra: quem compõe cada time e a função de cada pessoa.\n"
                    "Como ler: o ponto colorido indica a situação do usuário no Pipedrive (verde = ativo; vermelho = desativado; cinza = ainda sem negócios no nome). O botão ✎ editar libera trocar função, desligar e adicionar.\n"
                    "Fique de olho: (1) a lista de VENDAS define o que conta como SQL no funil — por isso desligar alguém nunca apaga nada: o histórico dos meses em que a pessoa atuou continua batendo com o Pipedrive; (2) re-adicionar um desligado funciona como recontratação; (3) coordenação e gerência ficam fora dos planos de ação e das comparações dos rankings — não são closers a treinar.")
            + "<div class=central>"
            "<div style='display:flex;gap:26px;flex-wrap:wrap'>" + blocos + "</div></div>"
            "<script>"
            "function tmEditar(on){[].slice.call(document.querySelectorAll('.tm-edit')).forEach(function(e){e.style.display=on?'':'none';});"
            "[].slice.call(document.querySelectorAll('.tm-view')).forEach(function(e){e.style.display=on?'none':'';});}"
            "function tmPost(body){fetch('/api/admin/times',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})"
            ".then(function(r){return r.json();}).then(function(j){if(j.error)alert(j.error);else location.reload();})"
            ".catch(function(){alert('falha de rede');});}"
            "function tmDesligar(area,btn){var nome=btn.getAttribute('data-nome');var pd=btn.getAttribute('data-pd');"
            "var msg='Desligar '+nome+' de '+(area==='vendas'?'Vendas':'Pré-vendas')+'?\\n\\nA pessoa some de todas as telas do painel; os números dela permanecem nas réguas históricas do funil.';"
            "if(pd==='ativo')msg+='\\n\\n⚠ ATENÇÃO: este colaborador ainda está ATIVO no Pipedrive — confirme se o desligamento é mesmo agora.';"
            "if(confirm(msg))tmPost({area:area,action:'desligar',nome:nome});}"
            "function tmPapel(area,sel){tmPost({area:area,action:'papel',nome:sel.getAttribute('data-nome'),papel:sel.value});}"
            "function tmAdd(area){var nome=document.getElementById('tm-nome-'+area).value.trim();"
            "if(!nome){alert('informe o nome como está no Pipedrive');return;}"
            "tmPost({area:area,action:'add',nome:nome,papel:document.getElementById('tm-papel-'+area).value});}"
            "</script>"
            "<style>.tmtbl{width:100%;border-collapse:collapse;font-size:var(--fs-sm)}"
            ".tmtbl td{padding:8px 6px;border-bottom:1px solid var(--border);vertical-align:middle}"
            ".tmtbl select,#tm-nome-prevendas,#tm-nome-vendas,#tm-papel-prevendas,#tm-papel-vendas{background:var(--bg-panel);"
            "border:1px solid var(--border-strong);border-radius:var(--radius-sm);color:var(--text);"
            "font-family:var(--font-body);font-size:var(--fs-xs);padding:5px 8px}</style></section>")


def _admin_html(users: list[dict]) -> str:
    """Painel administrativo: linha por conta com interruptor POR ÁREA (aplica
    na hora via /api/users/{id}/areas), nº de acessos e último login (audit_log),
    aprovar/bloquear e busca — modelo do painel da calculadora."""
    if not users:
        return "<div class=central><div class='id_'>nenhuma conta criada ainda — os gestores usam “Criar sua conta” na tela de login</div></div>"
    _UST = {"pendente": "--status-medio", "aprovado": "--status-baixo", "bloqueado": "--status-critico"}
    ths = "".join(f"<th>{nome.split(' /')[0]}</th>" for nome in AREAS.values())
    rows = ""
    for u in users:
        acts = ""
        if u["status"] != "aprovado":
            acts += f"<button class=abtn onclick=\"userSt('{u['id']}','aprovado')\">aprovar</button> "
        if u["status"] != "bloqueado":
            acts += f"<button class=abtn onclick=\"userSt('{u['id']}','bloqueado')\">bloquear</button>"
        tgls = "".join(
            f"<td class=tgl-td><label class=tgl><input type=checkbox data-uid='{u['id']}' value='{slug}' "
            f"{'checked' if slug in (u.get('areas') or []) else ''} onchange=\"tglArea('{u['id']}')\">"
            f"<span></span></label></td>" for slug in AREAS)
        rows += (f"<tr data-busca=\"{escape((u['name'] + ' ' + u['email']).lower())}\">"
                 f"<td><b>{escape(u['name'][:34])}</b><br><span class=amail>{escape(u['email'][:44])}</span></td>"
                 f"<td>{_chip(u['status'], _UST.get(u['status'], '--status-semdados'))}<div style='margin-top:5px'>{acts}</div></td>"
                 f"<td class=anum>{u.get('views', 0)}</td>"
                 f"<td class=anum>{escape(u.get('last_seen') or '—')}</td>"
                 f"{tgls}</tr>")
    return (
        "<div class=central style='padding:0;overflow-x:auto'>"
        "<div style='padding:14px 16px 0'><input id=abusca placeholder='pesquisar por nome ou e-mail…' oninput='aFiltra()' "
        "style='width:100%;max-width:420px;background:var(--bg-panel);border:1px solid var(--border-strong);border-radius:var(--radius-sm);color:var(--text);font-family:var(--font-body);font-size:var(--fs-sm);padding:9px 11px'></div>"
        "<table class=atbl><tr><th>Usuário</th><th>Status</th><th>Acessos</th><th>Último login</th>" + ths + "</tr>"
        + rows + "</table></div>"
        "<script>"
        "function userSt(id,st){if(st==='bloqueado'&&!confirm('Bloquear esta conta?'))return;"
        "fetch('/api/users/'+id+'/status',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({status:st})})"
        ".then(function(r){return r.json();}).then(function(j){if(j.error)alert(j.error);else location.reload();}).catch(function(){alert('falha de rede');});}"
        "function tglArea(id){var areas=[].slice.call(document.querySelectorAll(\"input[data-uid='\"+id+\"']:checked\")).map(function(c){return c.value;});"
        "fetch('/api/users/'+id+'/areas',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({areas:areas})})"
        ".then(function(r){return r.json();}).then(function(j){if(j.error){alert(j.error);location.reload();}}).catch(function(){alert('falha de rede');location.reload();});}"
        "function aFiltra(){var q=document.getElementById('abusca').value.toLowerCase();"
        "[].slice.call(document.querySelectorAll('tr[data-busca]')).forEach(function(tr){tr.style.display=tr.getAttribute('data-busca').indexOf(q)>=0?'':'none';});}"
        "</script>"
        "<style>"
        ".atbl{width:100%;border-collapse:collapse;font-size:var(--fs-sm);margin-top:12px}"
        ".atbl th{text-align:left;color:var(--text-muted);font-size:var(--fs-2xs);text-transform:uppercase;letter-spacing:var(--tracking-label);padding:9px 12px;border-bottom:1px solid var(--border-strong);white-space:nowrap}"
        ".atbl td{padding:10px 12px;border-bottom:1px solid var(--border);vertical-align:middle}"
        ".amail{color:var(--text-muted);font-size:var(--fs-xs)}"
        ".anum{font-variant-numeric:tabular-nums;white-space:nowrap}"
        ".tgl-td{text-align:center}"
        ".tgl{position:relative;display:inline-block;width:38px;height:21px;cursor:pointer}"
        ".tgl input{opacity:0;width:0;height:0}"
        ".tgl span{position:absolute;inset:0;background:var(--surface-3);border:1px solid var(--border-strong);border-radius:999px;transition:background .15s}"
        ".tgl span::after{content:'';position:absolute;width:15px;height:15px;border-radius:50%;background:var(--text-muted);top:2px;left:3px;transition:all .15s}"
        ".tgl input:checked+span{background:var(--brand);border-color:var(--brand)}"
        ".tgl input:checked+span::after{left:18px;background:var(--brand-ink)}"
        ".abtn{cursor:pointer;background:var(--surface-3);border:1px solid var(--border-strong);border-radius:var(--radius-sm);color:var(--text-2);font-family:var(--font-body);font-size:var(--fs-2xs);padding:3px 8px}"
        ".abtn:hover{border-color:var(--brand);color:var(--brand)}"
        "</style>")


_NIVEL = {"verde": ("--status-baixo", "saudável", 0), "medio": ("--status-medio", "atenção", 1),
          "alto": ("--status-alto", "atenção alta", 2), "critico": ("--status-critico", "crítico", 3)}


def _pacing_nivel(real, meta, frac) -> tuple[str, float]:
    """Nível de saúde por ritmo (realizado/meta vs fração do mês decorrida)."""
    if not meta or not frac:
        return "medio", 0.0
    ratio = (real / meta) / frac
    if ratio >= 0.9:
        return "verde", ratio
    if ratio >= 0.75:
        return "medio", ratio
    if ratio >= 0.6:
        return "alto", ratio
    return "critico", ratio


def _hub_op_stats(conn: Any) -> dict | None:
    """Resumo de OPERAÇÕES p/ o card do hub: iniciativas do trimestre corrente
    (fallback: anterior, se o novo ainda não tem sync) — total, atrasadas,
    concluídas e progresso, mesma régua da aba Visão Geral de /operacoes."""
    try:
        from .operacoes.ui import _contagem, _load_rows
        hoje = dt.date.today()
        year, quarter = hoje.year, (hoje.month - 1) // 3 + 1
        rows = _load_rows(conn, year, quarter)
        if not rows:  # virada de trimestre: Notion ainda sem iniciativas novas
            year, quarter = (year - 1, 4) if quarter == 1 else (year, quarter - 1)
            rows = _load_rows(conn, year, quarter)
        if not rows:
            return None
        c = _contagem(rows, hoje)
        return {"year": year, "quarter": quarter, "total": c["total"], "ok": c["ok"],
                "atras": c["atras"], "prog": c["prog"], "progresso": c["progresso"]}
    except Exception:  # noqa: BLE001 — tabela do Notion ausente não derruba o hub
        return None


def _receita_recorrente_html() -> str:
    """Saúde da Receita Recorrente (ISR + Quick Ratio) na central — duas visões
    SEPARADAS (B2-B5 = sinal do modelo novo · Consolidado = caixa, c/ antigos
    em runoff). Fonte: planilha (parser isolado p/ migrar ao Omie depois)."""
    try:
        from .sources.receita_recorrente import carrega
        d = carrega()
    except Exception:  # noqa: BLE001
        d = None
    if not d:
        return ""
    hoje = dt.date.today()
    idx_atual = min(12, (hoje.year - 2025) * 12 + hoje.month - 12)  # dez/25 = 0

    def f_(v, nd=0, suf=""):
        return _DASH if v is None else f"{v:,.{nd}f}{suf}".replace(",", "X").replace(".", ",").replace("X", ".")
    _td = "padding:6px 8px;border-bottom:1px solid var(--border);text-align:right;font-variant-numeric:tabular-nums;font-size:var(--fs-xs)"
    linhas = ""
    for i in range(1, 13):
        base_ant = d["base_b2b5"][i - 1]
        peq = base_ant is not None and base_ant < 100_000
        flag = (" <span class=note>base pequena, alta variância</span>" if peq
                else (" <span class=note>projeção</span>" if i > idx_atual else ""))
        cor_isr = ""
        if d["isr_b2b5"][i] is not None and not peq:
            cor_isr = ";color:var(--status-baixo)" if d["isr_b2b5"][i] >= 100 else ";color:var(--status-critico)"
        cross = " ★" if d["crossover_idx"] == i else ""
        linhas += (f"<tr><td style='{_td};text-align:left'><b>{d['meses'][i]}</b>{cross}{flag}</td>"
                   f"<td style='{_td}'>{f_(d['base_b2b5'][i])}</td>"
                   f"<td style='{_td}{cor_isr}'>{f_(d['isr_b2b5'][i], 0)}</td>"
                   f"<td style='{_td}'>{f_(d['novo'][i])}</td>"
                   f"<td style='{_td}'>{f_(d['perdido'][i])}</td>"
                   f"<td style='{_td}'><b>{f_(d['qr'][i], 1)}</b></td>"
                   f"<td style='{_td};border-left:1px solid var(--border-strong)'>{f_(d['isr_consol'][i], 1)}</td>"
                   f"<td style='{_td}'>{f_(d['qr_consol'][i], 1)}</td></tr>")
    i = min(idx_atual, 12)
    alerta = ""
    if d["alertas"]:
        m, txt = d["alertas"][-1]
        # link causal (17/07): do sinal financeiro direto p/ o diagnóstico
        alerta = (f"<div class=warn style='margin:10px 0'>⚠️ {escape(txt)} (até {m}) — "
                  "o modelo recorrente não está se sustentando. Investigar: "
                  "<a href='/growth?view=cancelamentos' style='color:var(--brand)'>Cancelamentos por bundle</a> · "
                  "<a href='/marketing?view=ciclo' style='color:var(--brand)'>Ciclo de Vida (qual canal traz quem sai)</a> · "
                  "<a href='/raiox' style='color:var(--brand)'>Raio-X por Bundle</a></div>")
    cross_txt = (f"★ Crossover projetado: <b>{d['meses'][d['crossover_idx']]}</b> — mês em que a base B2-B5 "
                 f"supera os planos antigos (o modelo novo passa a sustentar a receita sozinho)."
                 if d["crossover_idx"] is not None else "Crossover B2-B5 × antigos ainda não ocorre em 2026.")
    ths = "".join(f"<th style='text-align:{al};padding:6px 8px;font-size:var(--fs-2xs)'>{h}</th>" for h, al in
                  (("Mês", "left"), ("Base B2-B5", "right"), ("ISR", "right"), ("Nova", "right"),
                   ("Perdida", "right"), ("QR", "right"), ("ISR consol.", "right"), ("QR consol.", "right")))
    return (
        "<section><h2>Saúde da Receita Recorrente</h2>"
        "<p class=secsub>ISR = base recorrente ÷ mês anterior ×100 (≥100 = crescendo) · Quick Ratio = nova ÷ perdida (≥1 = ganha mais do que perde) · "
        "duas visões que NÃO se misturam: <b>B2-B5</b> = o sinal do modelo novo · <b>Consolidado</b> = caixa com antigos em runoff · fonte: planilha de planejamento (migra ao Omie quando o Financeiro abrir)</p>"
        + _hint("Saúde da Receita Recorrente",
                "O que mostra: a saúde da receita recorrente — a parte da receita que se repete todo mês.\n"
                "Como ler: ISR = a base recorrente deste mês dividida pela do mês anterior, vezes 100 — 100 ou mais significa que a base cresceu. Quick Ratio = a receita nova dividida pela perdida — 1 ou mais significa que entrou mais do que saiu por cancelamento. 'B2-B5' mostra só o modelo novo de planos; 'Consolidado' é o caixa total, com os planos antigos em descontinuação.\n"
                "Fique de olho: (1) para julgar o modelo novo, leia SEMPRE a visão B2-B5 — o Consolidado carrega a saída planejada dos planos antigos e esconde o sinal; (2) meses marcados 'base pequena, alta variância' saltam porque a base é baixa, não por crescimento real — não superinterprete; (3) ★ = o mês projetado em que o B2-B5 passa a sustentar a receita sozinho; (4) ISR abaixo de 100 ou Quick Ratio abaixo de 1 por 2 meses seguidos dispara alerta — aí a conversa é cancelamento por plano, não venda nova.")
        + f"<div class=kpis>"
        f"<div class=kpi><div class=n>{f_(d['base_b2b5'][i])}</div><div class=l>base recorrente B2-B5 ({d['meses'][i]})</div></div>"
        f"<div class=kpi><div class=n{' style=color:var(--status-baixo)' if (d['isr_b2b5'][i] or 0) >= 100 else ' style=color:var(--status-critico)'}>{f_(d['isr_b2b5'][i], 0)}</div><div class=l>ISR B2-B5</div><div class=s>≥100 = base crescendo</div></div>"
        f"<div class=kpi><div class=n>{f_(d['qr'][i], 1)}</div><div class=l>Quick Ratio B2-B5</div><div class=s>nova ÷ perdida</div></div>"
        f"<div class=kpi><div class=n>{f_(d['isr_consol'][i], 1)}</div><div class=l>ISR consolidado</div><div class=s>caixa (antigos em runoff)</div></div></div>"
        + alerta +
        f"<div class=central style='padding:8px 14px 12px'><table style='width:100%;border-collapse:collapse'><tr>{ths}</tr>{linhas}</table>"
        f"<p class=note style='margin:10px 0 0'>{cross_txt}</p></div></section>")


def _hub_mudancas(conn: Any) -> str:
    """'O que mudou desde ontem' (14/07): deltas das últimas 24h/última rodada,
    derivados dos dados existentes — a rotina diária de 30 segundos do gestor."""
    itens: list[tuple[str, str]] = []
    try:
        with conn.cursor() as cur:
            # GROWTH: bandas vs run anterior (duas últimas rodadas de score)
            cur.execute("""SELECT run_id FROM scores GROUP BY run_id
                            ORDER BY max(computed_at) DESC LIMIT 2""")
            runs = [r[0] for r in cur.fetchall()]
            if len(runs) == 2:
                # direção da mudança de faixa COM as contas (Otávio 16/07: o
                # link precisa levar EXATAMENTE ao que o item diz — nomes no
                # texto + ?ids= pré-filtrando a aba Contas). rank baixo<...<critico
                cur.execute("""
                    SELECT a.id::text, a.name, n.risk_band, o.risk_band,
                           CASE n.risk_band WHEN 'baixo' THEN 1 WHEN 'medio' THEN 2
                                            WHEN 'alto' THEN 3 WHEN 'critico' THEN 4 END,
                           CASE o.risk_band WHEN 'baixo' THEN 1 WHEN 'medio' THEN 2
                                            WHEN 'alto' THEN 3 WHEN 'critico' THEN 4 END
                      FROM scores n
                      JOIN scores o ON o.account_id = n.account_id
                      JOIN accounts a ON a.id = n.account_id
                     WHERE n.run_id = %s AND o.run_id = %s
                       AND n.risk_band <> o.risk_band""", (runs[0], runs[1]))
                ent_l, sai_l, pior_l, melhor_l = [], [], [], []
                for aid, nome, nb, ob, rn, ro in cur.fetchall():
                    if nb == "critico":
                        ent_l.append((aid, nome))
                    elif ob == "critico":
                        sai_l.append((aid, nome))
                    elif rn is not None and ro is not None and rn > ro:
                        pior_l.append((aid, nome))
                    elif rn is not None and ro is not None and rn < ro:
                        melhor_l.append((aid, nome))

                def _mud_item(lista, texto, cor):
                    nomes = ", ".join(escape((n or "?")[:26]) for _, n in lista[:3])
                    if len(lista) > 3:
                        nomes += f" +{len(lista) - 3}"
                    return (f"<b style='color:var({cor})'>{len(lista)}</b> conta(s) {texto}: "
                            f"<span style='color:var(--text-muted)'>{nomes}</span>",
                            f"/growth?view=contas&ids={','.join(a for a, _ in lista)}")
                if ent_l:
                    itens.append(_mud_item(ent_l, "ENTRARAM em crítico na última rodada", "--status-critico"))
                if sai_l:
                    itens.append(_mud_item(sai_l, "saíram de crítico", "--status-baixo"))
                if pior_l:
                    itens.append(_mud_item(pior_l, "PIORARAM de faixa de risco", "--status-alto"))
                if melhor_l:
                    itens.append(_mud_item(melhor_l, "melhoraram de faixa de risco", "--status-baixo"))
            # VENDAS: bookings e oportunidades nas últimas 24h
            cur.execute("""SELECT count(*), COALESCE(sum(COALESCE(valor_custom, valor)), 0)
                             FROM mkt_deals_attribution
                            WHERE status='won' AND won_time >= now() - interval '24 hours'""")
            bk, rec = cur.fetchone()
            if bk:
                cur.execute("""SELECT titulo FROM mkt_deals_attribution
                                WHERE status='won' AND won_time >= now() - interval '24 hours'
                                ORDER BY won_time DESC LIMIT 3""")
                bk_nm = ", ".join(escape((r[0] or "?")[:26]) for r in cur.fetchall())
                if bk > 3:
                    bk_nm += f" +{bk - 3}"
                itens.append((f"<b style='color:var(--status-baixo)'>{bk}</b> booking(s) nas últimas 24h — "
                              f"R$ {float(rec):,.0f}".replace(",", ".")
                              + f": <span style='color:var(--text-muted)'>{bk_nm}</span>", "/vendas"))
            cur.execute("""SELECT count(*) FROM mkt_deals_attribution
                            WHERE oport_time >= now() - interval '24 hours'""")
            op = cur.fetchone()[0]
            if op:
                cur.execute("""SELECT titulo FROM mkt_deals_attribution
                                WHERE oport_time >= now() - interval '24 hours'
                                ORDER BY oport_time DESC LIMIT 3""")
                op_nm = ", ".join(escape((r[0] or "?")[:26]) for r in cur.fetchall())
                if op > 3:
                    op_nm += f" +{op - 3}"
                itens.append((f"<b>{op}</b> nova(s) oportunidade(s) nas últimas 24h: "
                              f"<span style='color:var(--text-muted)'>{op_nm}</span>", "/vendas?view=funil"))
            # MARKETING: CPL de ontem vs média 7d anterior, por canal pago
            cur.execute("""
                WITH d1 AS (SELECT canal, sum(spend) g, sum(leads) l FROM mkt_insights_daily
                             WHERE date = CURRENT_DATE - 1 GROUP BY 1),
                     d7 AS (SELECT canal, sum(spend) g, sum(leads) l FROM mkt_insights_daily
                             WHERE date >= CURRENT_DATE - 8 AND date < CURRENT_DATE - 1 GROUP BY 1)
                SELECT d1.canal, d1.g / NULLIF(d1.l, 0), d7.g / NULLIF(d7.l, 0)
                  FROM d1 JOIN d7 ON d7.canal = d1.canal""")
            for cn, cpl1, cpl7 in cur.fetchall():
                if cpl1 and cpl7 and (cpl1 / cpl7 > 1.3 or cpl1 / cpl7 < 0.7):
                    dirc = "subiu" if cpl1 > cpl7 else "caiu"
                    cor = "--status-critico" if cpl1 > cpl7 else "--status-baixo"
                    nome = "Meta Ads" if cn == "meta" else "Google Ads"
                    itens.append((f"CPL do {nome} <b style='color:var({cor})'>{dirc}</b> p/ R$ {float(cpl1):,.0f} ontem (média 7d: R$ {float(cpl7):,.0f})".replace(",", "."), "/marketing?view=midia"))
            # OPERAÇÕES: iniciativas que viraram atrasadas desde ontem
            cur.execute("""SELECT count(*) FROM notion_initiatives_cache
                            WHERE prazo = CURRENT_DATE - 1 AND status <> 'concluida'""")
            atr = cur.fetchone()[0]
            if atr:
                itens.append((f"<b style='color:var(--status-critico)'>{atr}</b> iniciativa(s) viraram ATRASADAS desde ontem", "/operacoes"))
    except Exception:  # noqa: BLE001 — resumo nunca derruba o hub
        pass
    if not itens:
        return ""
    lis = "".join(f"<a href='{href}' style='display:flex;gap:9px;align-items:center;padding:7px 0;"
                  f"border-top:1px solid var(--border);color:var(--text-2);font-size:var(--fs-sm);"
                  f"text-decoration:none'><span>→</span><span>{txt}</span></a>" for txt, href in itens)
    return ("<section><h2>O que mudou desde ontem</h2>"
            "<p class=secsub>deltas das últimas 24h / última rodada — clique para abrir a área</p>"
            + _hint("O que mudou desde ontem",
                    "O que mostra: a rotina diária de 30 segundos — só o que mudou desde a última rodada.\n"
                    "Como ler: contas que entraram ou saíram da faixa crítica (comparando as duas últimas rodadas de nota), contratos e oportunidades das últimas 24h, o custo por lead de ontem contra a média dos 7 dias anteriores (só aparece se variar mais de 30%) e iniciativas que viraram atrasadas.\n"
                    "Fique de olho: (1) conta que ENTROU em crítico é a primeira ligação do dia; (2) nada listado = nada relevante mudou — dias sem itens são normais; (3) cada linha leva direto à área para agir.")
            + f"<div class=central>{lis}</div></section>")


def _hub_lags(conn: Any, coorte: list[dict] | None = None) -> dict:
    """Defasagens REAIS do histórico (medianas) — Integração Causal #4: quanto
    tempo uma correção numa área leva p/ aparecer na outra. Onde não há base
    (série de risco começou 14/07), o valor fica None e a tela DIZ isso."""
    out = {"lead_book": None, "oport_book": None, "book_churn": None,
           "n_lead": 0, "n_oport": 0, "n_churn": 0}
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY
                                    EXTRACT(epoch FROM (won_time - add_time)) / 86400), count(*)
                             FROM mkt_deals_attribution
                            WHERE status='won' AND won_time IS NOT NULL AND add_time IS NOT NULL
                              AND won_time >= now() - interval '180 days'""")
            v, n = cur.fetchone()
            if n and n >= 10:
                out["lead_book"], out["n_lead"] = float(v), int(n)
            cur.execute("""SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY
                                    EXTRACT(epoch FROM (won_time - oport_time)) / 86400), count(*)
                             FROM mkt_deals_attribution
                            WHERE status='won' AND won_time IS NOT NULL AND oport_time IS NOT NULL
                              AND won_time >= now() - interval '180 days'""")
            v, n = cur.fetchone()
            if n and n >= 10:
                out["oport_book"], out["n_oport"] = float(v), int(n)
        if coorte is None:
            from .marketing.ui import _ciclo_coorte
            coorte, _g, _c = _ciclo_coorte(conn)
        # deltas <=0 são artefato (data de saída em granularidade de MÊS pode
        # cair antes do fechamento) — ficam fora da mediana
        dias = [(r["saida"] - r["won"]).days for r in coorte
                if r["desfecho"] == "precoce" and r.get("saida")
                and (r["saida"] - r["won"]).days > 0]
        if len(dias) >= 8:
            import statistics as _st
            out["book_churn"], out["n_churn"] = float(_st.median(dias)), len(dias)
    except Exception:  # noqa: BLE001 — defasagem é informativa, nunca derruba o hub
        pass
    return out


def _hub_impactos(conn: Any, mkt: dict | None, sales: dict | None,
                  coorte: list[dict] | None = None) -> dict:
    """Impacto estimado em R$/MÊS por tipo de gargalo (Integração Causal #2) —
    faixa conservador–otimista + PREMISSA explícita. São estimativas de
    potencial p/ PRIORIZAR entre áreas, não promessas."""
    imp: dict[str, dict] = {}
    ticket = (sales["receita"] / sales["book"]) if (sales and sales.get("book")) else None
    conv = (mkt["book"] / mkt["leads"]) if (mkt and mkt.get("leads") and mkt.get("book")) else None
    # gap de LEADS vs meta (Marketing)
    if mkt and mkt.get("leads_meta") and mkt.get("frac") and conv and ticket:
        gap_hoje = max(0.0, mkt["leads_meta"] * mkt["frac"] - mkt["leads"])
        if gap_hoje >= 5:
            base = gap_hoje * conv * ticket
            imp["leads"] = {"faixa": (base * 0.7, base), "janela": "lead_book",
                            "premissa": (f"assumindo que os {gap_hoje:.0f} leads em atraso vs o ritmo da meta "
                                         f"convertam na taxa do mês ({conv * 100:.1f}%) e no ticket atual "
                                         f"({_fmt_brl(ticket)})")}
    # gap de QUALIFICAÇÃO (Ponte, 90d): taxa geral vs oportunidades c/ SLA ≤15min
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT count(*) FILTER (WHERE status = 'won'),
                       count(*),
                       count(*) FILTER (WHERE status = 'won' AND sla <= 15),
                       count(*) FILTER (WHERE sla <= 15),
                       (SELECT count(*) FROM mkt_deals_attribution
                         WHERE oport_time >= now() - interval '90 days')
                  FROM (SELECT d.status, EXTRACT(epoch FROM (t.first_at - d.add_time)) / 60 AS sla
                          FROM mkt_deals_attribution d
                          LEFT JOIN sales_first_touch t ON t.deal_id = d.deal_id
                         WHERE d.oport_time >= now() - interval '90 days'
                           AND d.status IN ('won', 'lost')) x""")
            w, dec, w15, dec15, oports = cur.fetchone()
        if dec and dec15 and dec15 >= 10 and ticket:
            tx, tx15 = w / dec, w15 / dec15
            if tx15 > tx:
                base = (oports / 3.0) * (tx15 - tx) * ticket
                imp["ponte"] = {"faixa": (base * 0.5, base), "janela": "oport_book",
                                "premissa": (f"assumindo que a taxa geral de fechamento ({tx * 100:.1f}%) suba ao "
                                             f"nível das oportunidades atendidas em ≤15min ({tx15 * 100:.1f}%), "
                                             f"sobre ~{oports / 3.0:.0f} oportunidades/mês")}
    except Exception:  # noqa: BLE001
        pass
    # CHURN PRECOCE por canal (Ciclo de Vida)
    try:
        if coorte is None:
            from .marketing.ui import _ciclo_coorte
            coorte, _g, _c = _ciclo_coorte(conn)
        por_canal: dict[str, list] = {}
        for r in coorte:
            por_canal.setdefault(r["canal"], []).append(r)
        cand = {c: rs for c, rs in por_canal.items() if len(rs) >= 8}
        if len(cand) >= 2:
            prec = {c: sum(1 for r in rs if r["desfecho"] == "precoce") / len(rs) for c, rs in cand.items()}
            pior = max(prec, key=prec.get)
            melhor = min(prec, key=prec.get)
            if prec[pior] - prec[melhor] >= 0.15:
                rs = cand[pior]
                span_m = max(1.0, (max(r["won"] for r in rs) - min(r["won"] for r in rs)).days / 30.4)
                cli_mes = len(rs) / span_m
                mrr_med = (sum(r["mrr"] for r in rs) / len(rs)) or 0
                base = cli_mes * (prec[pior] - prec[melhor]) * mrr_med
                if base > 0:
                    imp["ciclo"] = {"faixa": (base * 0.5, base), "janela": "book_churn",
                                    "pior": pior, "melhor": melhor,
                                    "premissa": (f"assumindo que o churn precoce de {pior} "
                                                 f"({prec[pior] * 100:.0f}%) caia ao nível de {melhor} "
                                                 f"({prec[melhor] * 100:.0f}%), sobre ~{cli_mes:.1f} clientes/mês "
                                                 f"e MRR médio de {_fmt_brl(mrr_med)}")}
    except Exception:  # noqa: BLE001
        pass
    # EXECUÇÃO CRÍTICA = EXPOSIÇÃO de MRR (honestidade: no nosso histórico a
    # execução NÃO provou prever churn — é risco exposto, não perda projetada)
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT COALESCE(sum(a.recurring_revenue), 0) FROM accounts a
                            WHERE EXISTS (SELECT 1 FROM signal_snapshots ss
                                           WHERE ss.account_id = a.id AND ss.signal_key = 'exec_score'
                                             AND ss.value_num < 40)""")
            mrr_exec = float(cur.fetchone()[0] or 0)
            cur.execute("""SELECT count(*) FROM grw_cancelamentos
                            WHERE tipo='cancelamento'
                              AND mes >= date_trunc('month', now()) - interval '3 months'
                              AND mes < date_trunc('month', now())
                              AND upper(COALESCE(plano, '')) NOT LIKE '%%START%%'""")
            canc3 = int(cur.fetchone()[0])
            cur.execute("SELECT count(*) FROM accounts WHERE substring(name FROM 'B[1-5]') IS DISTINCT FROM 'B1'")
            base_rec = int(cur.fetchone()[0])
        tx_mes = (canc3 / 3.0 / base_rec) if base_rec else 0.10
        if mrr_exec > 0:
            imp["exec"] = {"faixa": (mrr_exec * tx_mes, mrr_exec * tx_mes * 2), "janela": None,
                           "premissa": (f"EXPOSIÇÃO: {_fmt_brl(mrr_exec)} de MRR em contas com execução crítica × "
                                        f"churn mensal médio dos recorrentes ({tx_mes * 100:.1f}%; otimista assume "
                                        "risco dobrado se o atraso persistir). No histórico, execução crítica NÃO "
                                        "provou prever churn — trate como risco, não como perda certa")}
    except Exception:  # noqa: BLE001
        pass
    return imp


def _render_hub(role: str, st: dict, users: list[dict] | None = None,
                mkt: dict | None = None, page: str = "home",
                llm: dict | None = None, sales: dict | None = None,
                teams_html: str = "", ops: dict | None = None,
                mudancas: str = "", body_override: str | None = None,
                active_page: str = "", impactos: dict | None = None,
                lags: dict | None = None, foco_html: str = "",
                raiox_mini: str = "", foco_kw: list[str] | None = None) -> str:
    n_alerts = sum(st["sev"].values())
    crit = st["sev"].get("critico", 0)

    # ---- saúde por área (determinística; pior área = prioridade de atenção)
    saude: dict[str, tuple[str, str]] = {}  # area -> (nivel, motivo)
    if crit:
        saude["growth"] = ("critico", f"{crit} conta(s) em risco crítico — {_fmt_brl(st['mrr_crit'])} de MRR em jogo")
    elif st["sev"].get("alto", 0):
        saude["growth"] = ("alto", f"{st['sev']['alto']} alerta(s) de risco alto abertos")
    elif st["sev"].get("atencao", 0):
        saude["growth"] = ("medio", f"{st['sev']['atencao']} conta(s) em atenção")
    else:
        saude["growth"] = ("verde", "carteira sem alertas abertos")
    if mkt and mkt.get("leads_meta"):
        nv, ratio = _pacing_nivel(mkt["leads"], mkt["leads_meta"], mkt["frac"])
        saude["marketing"] = (nv, f"leads a {ratio * 100:.0f}% do ritmo esperado "
                                  f"({mkt['leads']:.0f} de {mkt['leads_meta']:.0f} na meta do mês)")
    else:
        saude["marketing"] = ("medio", "sem meta/cache do mês — rodar o sync de marketing")
    if sales:
        pv_nv, pv_motivo = "verde", "conversão lead→reunião estável"
        if sales["taxa"] is not None and sales["taxa_ant"]:
            if sales["taxa"] < sales["taxa_ant"] * 0.8:
                pv_nv, pv_motivo = "alto", (f"conversão lead→reunião caiu de {sales['taxa_ant'] * 100:.1f}% "
                                            f"para {sales['taxa'] * 100:.1f}%")
            elif sales["taxa"] < sales["taxa_ant"] * 0.95:
                pv_nv, pv_motivo = "medio", (f"conversão lead→reunião abaixo do mês anterior "
                                             f"({sales['taxa'] * 100:.1f}% vs {sales['taxa_ant'] * 100:.1f}%)")
        if sales["tem_touch"] and sales["leads"] and sales["sem_toque"] / sales["leads"] > 0.3 \
                and _NIVEL[pv_nv][2] < 2:
            pv_nv, pv_motivo = "alto", f"{sales['sem_toque']} leads do mês ainda sem 1º contato registrado"
        saude["prevendas"] = (pv_nv, pv_motivo)
        if sales.get("book_meta"):
            nv, ratio = _pacing_nivel(sales["book"], sales["book_meta"], mkt["frac"] if mkt else None)
            saude["vendas"] = (nv, f"bookings a {ratio * 100:.0f}% do ritmo esperado "
                                   f"({sales['book']} de {sales['book_meta']:.0f} da meta)")
        else:
            saude["vendas"] = ("medio", "sem meta de bookings cadastrada p/ o mês")
    else:
        saude["prevendas"] = ("medio", "dados do mês indisponíveis")
        saude["vendas"] = ("medio", "dados do mês indisponíveis")
    _AREA_LBL = {"growth": ("Growth / Assessoria", "/growth"), "marketing": ("Marketing", "/marketing"),
                 "prevendas": ("Pré-vendas", "/prevendas"), "vendas": ("Vendas", "/vendas")}
    pior = max(saude, key=lambda k: _NIVEL[saude[k][0]][2])
    pior_nv = saude[pior][0]
    # Iniciativas sugeridas pela inteligência central — derivadas dos dados
    # reais das áreas ativas (Growth + Marketing) = priorização cross-área.
    # cada iniciativa é um LINK para os dados que a sustentam (pedido Otávio
    # 15/07: "vendo isso vou querer saber quais são" — ex.: execução crítica
    # abre a aba Contas já filtrada em execução=crítica)
    initiatives = []  # (título, descrição, cor, link, tipo) — tipo casa c/ impactos/lags
    if crit:
        initiatives.append(("Reter as contas em risco crítico",
                            f"{crit} contas sinalizaram saída ou estão em faixa crítica — "
                            f"{_fmt_brl(st['mrr_crit'])} de MRR em jogo. Fila pronta na área de Growth.",
                            "--status-critico", "/growth?view=alertas", "retencao"))
    if mkt and mkt.get("book_meta") and mkt["book"] / mkt["book_meta"] < mkt["frac"] * 0.75:
        initiatives.append(("Destravar bookings do mês",
                            f"{mkt['book']} de {mkt['book_meta']:.0f} bookings da meta com "
                            f"{mkt['frac'] * 100:.0f}% do mês decorrido — ver etapa de maior perda no "
                            "Funil de Prospecção e o gap por plano.",
                            "--status-critico", "/marketing?view=funil", "bookings"))
    if mkt and mkt.get("leads_meta") and mkt["leads"] / mkt["leads_meta"] < mkt["frac"] * 0.75:
        initiatives.append(("Acelerar a geração de leads",
                            f"{mkt['leads']} de {mkt['leads_meta']:.0f} leads da meta do mês com "
                            f"{mkt['frac'] * 100:.0f}% do mês decorrido — revisar campanhas e verba "
                            "na aba Metas do Semestre.",
                            "--status-alto", "/marketing?view=metas", "leads"))
    if sales and sales["tem_touch"] and sales["leads"] and sales["sem_toque"] / sales["leads"] > 0.3:
        initiatives.append(("Zerar a fila de leads sem 1º contato",
                            f"{sales['sem_toque']} leads do mês ainda sem contato registrado em Pré-vendas — "
                            "lead não tocado esfria; ver Speed-to-Lead.",
                            "--status-alto", "/prevendas?view=speed", "ponte"))
    if sales and sales["taxa"] is not None and sales["taxa_ant"] and sales["taxa"] < sales["taxa_ant"] * 0.8:
        initiatives.append(("Investigar a queda na conversão lead→reunião",
                            f"Taxa caiu de {sales['taxa_ant'] * 100:.1f}% para {sales['taxa'] * 100:.1f}% — "
                            "cruzar com qualidade de lead por origem (Pré-vendas → Funil).",
                            "--status-alto", "/prevendas?view=funil", "conversao"))
    # churn precoce por canal (Ciclo de Vida) — entra como iniciativa quando a
    # diferença entre canais é relevante (impacto calculado em _hub_impactos)
    if impactos and impactos.get("ciclo"):
        ic = impactos["ciclo"]
        initiatives.append(("Migrar aquisição do canal que traz churn precoce",
                            f"{ic['pior']} traz cliente que cancela em ≤3 meses bem acima de {ic['melhor']} — "
                            "migrar mix e endurecer a qualificação do canal fraco (Ciclo de Vida).",
                            "--status-alto", "/marketing?view=ciclo", "ciclo"))
    if st["exec_late"]:
        initiatives.append(("Regularizar execução nas contas em alerta",
                            f"{st['exec_late']} contas monitoradas com execução CRÍTICA no ClickUp "
                            "(entregas vencidas ou implantação além do prazo) — atrito operacional que "
                            "alimenta a insatisfação. Clique para ver as contas (a causa está no hover "
                            "da coluna Execução; responsáveis no relatório).",
                            "--status-alto", "/growth?view=contas&exec=critica", "exec"))
    # só contas ANTIGAS sem cobertura viram iniciativa — cliente novo ainda em
    # rampa de conversa é esperado, não pendência (Otávio 16/07)
    if st.get("non_eval_antigas"):
        initiatives.append(("Recuperar cobertura de dados",
                            f"{st['non_eval_antigas']} conta(s) há mais de 30 dias na base sem conversa "
                            "suficiente no WhatsApp — o agente não as enxerga; revisar e reativar os grupos "
                            "(contas novas em rampa não entram aqui).",
                            "--status-semdados", "/growth?view=contas&faixa=sem_dados", None))

    # ---- impacto em R$ + defasagem por iniciativa (Integração Causal #2/#4):
    # a moeda comum ordena a fila — o gestor sequencia por retorno estimado
    imp = impactos or {}
    lg = lags or {}
    # bookings atrás da meta: o impacto é o próprio gap de receita vs o ritmo
    if (sales and sales.get("receita_meta") and mkt and mkt.get("frac")
            and "bookings" not in imp):
        gap_hoje = max(0.0, sales["receita_meta"] * mkt["frac"] - sales["receita"])
        proj = sales["receita"] / mkt["frac"] if mkt["frac"] else None
        gap_fim = max(0.0, sales["receita_meta"] - proj) if proj else gap_hoje
        if gap_hoje > 0:
            faixa = tuple(sorted((gap_hoje, gap_fim or gap_hoje)))
            imp["bookings"] = {"faixa": faixa, "janela": "oport_book",
                               "premissa": ("distância da receita ao ritmo da meta hoje (conservador) e o gap "
                                            "projetado p/ o fim do mês no ritmo atual (otimista)")}

    def _janela_txt(chave):
        if not chave:
            return "sem base histórica para estimar a defasagem"
        v = lg.get(chave)
        rot = {"lead_book": "efeito visível em bookings em",
               "oport_book": "efeito visível em bookings em",
               "book_churn": "efeito visível na retenção em"}[chave]
        if v is None:
            return "sem base histórica para estimar a defasagem"
        return f"{rot} ~{max(1, round(v)):.0f} dia(s) (mediana histórica) — não avalie antes disso"

    decoradas = []
    for t, d, var, href, tipo in initiatives:
        e = imp.get(tipo) if tipo else None
        chave_j = (e or {}).get("janela") if e else {"retencao": None, "conversao": "lead_book"}.get(tipo)
        decoradas.append((t, d, var, href, e, chave_j, tipo))
    # ordena por impacto estimado (máx. da faixa); sem estimativa vai ao final
    decoradas.sort(key=lambda x: -(x[4]["faixa"][1] if x[4] else -1))

    # selo 'foco desta semana' (Cockpit, 17/07): amarra a priorização por R$ ao
    # combinado da semana — casamento HEURÍSTICO por palavras-chave do tipo do
    # gargalo e por menção ao mesmo bundle nos objetivos CONFIRMADOS
    _FOCO_KW = {"leads": ("lead",), "bookings": ("booking", "fechar", "vender", "meta"),
                "ciclo": ("churn", "cancel", "reten"), "ponte": ("sla", "qualifica", "contato"),
                "exec": ("execu", "atraso", "entrega"), "retencao": ("churn", "reten", "risco", "cancel"),
                "conversao": ("convers", "reuni", "agend")}

    def _eh_foco(tipo, titulo, descr):
        if not foco_kw:
            return False
        alvo = (titulo + " " + descr).lower()
        for txt in foco_kw:
            if any(kw in txt for kw in _FOCO_KW.get(tipo or "", ())):
                return True
            m_b = re.search(r"b[1-5]", txt)
            if m_b and m_b.group(0) in alvo:
                return True
        return False

    def _init_html(t, d, var, href, e, chave_j, tipo):
        extra = ""
        if e:
            lo, hi = e["faixa"]
            extra = (f"<div class='id_' style='margin-top:4px'><b style='color:var(--brand)'>"
                     f"≈ {_fmt_brl(lo)}–{_fmt_brl(hi)}/mês em jogo</b> · potencial estimado, não promessa · "
                     f"premissa: {escape(e['premissa'])} · {escape(_janela_txt(chave_j))}</div>")
        elif chave_j:
            extra = f"<div class='id_' style='margin-top:4px'>{escape(_janela_txt(chave_j))}</div>"
        return (f"<a class='init' href='{href}' title='abrir os dados desta iniciativa'>"
                f"<span class='sdot' style='--c:var({var})'></span>"
                f"<div><div class='it'>{escape(t)}</div><div class='id_'>{escape(d)}</div>{extra}</div>"
                f"<span class='ig'>→</span></a>")

    # fusão (17/07 noite): iniciativa que casa com um objetivo CONFIRMADO da
    # semana foi ABSORVIDA pelos cards de 'Prioridades da Semana' — o que sobra
    # é o horizonte maior que a semana (estrutural), num bloco menor
    restantes = [x for x in decoradas if not _eh_foco(x[6], x[0], x[1])]
    init_html = "".join(_init_html(*x) for x in restantes) \
        or ("<div class='init'><div class='id_'>nenhuma iniciativa além das prioridades da semana — "
            "os gargalos atuais já viraram objetivos confirmados</div></div>")

    # ---- defasagem esperada (Integração Causal #4): protege decisão certa de
    # ser revertida cedo demais — quando cobrar resultado de cada correção
    lag_rows = []
    if lg.get("lead_book") is not None:
        lag_rows.append(("Mudança na geração/qualificação de leads → bookings",
                         f"~{max(1, round(lg['lead_book']))} dia(s) (mediana de {lg['n_lead']} contratos, 180d) — "
                         "metade dos contratos fecha até aí; o efeito PLENO leva mais"))
    if lg.get("oport_book") is not None:
        lag_rows.append(("Oportunidade criada → contrato fechado",
                         f"~{max(1, round(lg['oport_book']))} dia(s) (mediana de {lg['n_oport']} contratos, 180d)"))
    if lg.get("book_churn") is not None:
        lag_rows.append(("Mudança na aquisição → reflexo no churn precoce",
                         f"~{max(1, round(lg['book_churn']))} dia(s) (mediana de {lg['n_churn']} cancelamentos "
                         "precoces; datas de saída em granularidade de mês — leia como ordem de grandeza)"))
    lag_rows.append(("Execução atrasada → piora de faixa de risco",
                     "sem base histórica ainda — a série diária de risco começou em 14/07/26"))
    defasagem_html = ("".join(
        f"<div class='init'><span class='sdot' style='--c:var(--status-semdados)'></span>"
        f"<div><div class='it' style='font-size:var(--fs-sm)'>{escape(a)}</div>"
        f"<div class='id_'>{escape(b)}</div></div></div>" for a, b in lag_rows))

    # ---- cards-resumo por área (mini-painel com os números que importam)
    def _num(v):
        return f"{v:,.0f}".replace(",", ".")

    def am(valor, rotulo, cor=None):
        c = f" style='color:{cor}'" if cor else ""
        return f"<div class=am><div class=av{c}>{valor}</div><div class=al>{rotulo}</div></div>"

    def vs_meta(real, meta_v, frac, pior_menor=True):
        """valor real/meta colorido pelo ritmo do mês (verde = no ritmo)."""
        if not meta_v:
            return _num(real), None
        pct = real / meta_v
        ok = (pct >= frac) if pior_menor else (pct <= 1.0)
        cor = "var(--status-baixo)" if ok else "var(--status-critico)"
        return (f"{_num(real)}<span style='color:var(--text-faint);font-size:14px'>"
                f"/{_num(meta_v)}</span>"), cor

    def chip_area(area):
        var, lbl, _ = _NIVEL[saude[area][0]]
        return _chip(lbl, var, dot=True)

    g_det = (f"{crit} críticos · {st['sev'].get('alto', 0)} altos · "
             f"{st['sev'].get('atencao', 0)} atenção · {st['non_eval']} sem cobertura")
    growth_card = (
        "<a class='area big' href='/growth'><div class=ahead>"
        f"<div class=an>Growth / Assessoria</div>{chip_area('growth')}</div>"
        "<div class=agrid>"
        + am(_num(st["monitored"]), "contas monitoradas")
        + am(_num(n_alerts), "alertas abertos", "var(--status-critico)" if n_alerts else None)
        + am(_fmt_brl(st["mrr_risk"]), "MRR em risco", "var(--status-alto)" if st["mrr_risk"] else None)
        + am(_num(st["exec_late"]), "execução crítica", "var(--status-medio)" if st["exec_late"] else None)
        + f"</div><div class=ad>{escape(g_det)}</div></a>")

    # cards COMPLEMENTARES entre áreas (Otávio 16/07: sem número repetido) —
    # bookings/receita ficam SÓ em Vendas; Marketing = aquisição + eficiência
    # (CAC no lugar de bookings); PV = qualificação + fila; Financeiro = caixa
    if mkt:
        v_leads, c_leads = vs_meta(mkt["leads"], mkt.get("leads_meta"), mkt["frac"])
        v_oport, c_oport = vs_meta(mkt["oport"], mkt.get("oport_meta"), mkt["frac"])
        gasto_txt = _fmt_brl(mkt["gasto"])
        c_gasto = None
        if mkt.get("verba"):
            c_gasto = "var(--status-baixo)" if mkt["gasto"] <= mkt["verba"] else "var(--status-critico)"
            gasto_txt += (f"<span style='color:var(--text-faint);font-size:14px'>"
                          f"/{_fmt_brl(mkt['verba'])}</span>")
        cpl_txt = ""
        if mkt.get("cpl") is not None:
            cpl_txt = f" · CPL {_fmt_brl(mkt['cpl'])}"
            if mkt.get("cpl_alvo"):
                cpl_txt += f" (alvo {_fmt_brl(mkt['cpl_alvo'])})"
        m_det = (f"mês {mkt['mes'].strftime('%m-%Y')} · ritmo esperado {mkt['frac'] * 100:.0f}%"
                 + cpl_txt + " · bookings e receita no card de Vendas")
        cac_txt = _fmt_brl(mkt["cac"]) if mkt.get("cac") is not None else "—"
        mkt_card = (
            "<a class='area big' href='/marketing'><div class=ahead>"
            f"<div class=an>Marketing</div>{chip_area('marketing')}</div>"
            "<div class=agrid>"
            + am(v_leads, "leads no mês", c_leads)
            + am(v_oport, "oportunidades", c_oport)
            + am(gasto_txt, "gasto mídia/verba", c_gasto)
            + am(cac_txt, "CAC do mês (gasto ÷ contratos)")
            + f"</div><div class=ad>{escape(m_det)}</div></a>")
    else:
        mkt_card = ("<a class='area big' href='/marketing'><div class=ahead>"
                    f"<div class=an>Marketing</div>{chip_area('marketing')}</div>"
                    "<div class=ad>tráfego pago, leads, funil e planejador — sem cache do mês "
                    "(rode o sync de marketing)</div></a>")

    if sales:
        taxa_txt = f"{sales['taxa'] * 100:.1f}%" if sales["taxa"] is not None else "—"
        c_taxa = None
        if sales["taxa"] is not None and sales["taxa_ant"]:
            c_taxa = ("var(--status-baixo)" if sales["taxa"] >= sales["taxa_ant"] * 0.95
                      else "var(--status-critico)")
        speed_txt = "—"
        if sales["speed_med"] is not None:
            m = sales["speed_med"]
            speed_txt = f"{m:.0f} min" if m < 120 else f"{m / 60:.1f} h"
        fila_txt = _num(sales["sem_toque"]) if sales["tem_touch"] else "—"
        c_fila = ("var(--status-critico)" if sales["tem_touch"] and sales["leads"]
                  and sales["sem_toque"] / sales["leads"] > 0.3 else None)
        pv_card = (
            "<a class='area big' href='/prevendas'><div class=ahead>"
            f"<div class=an>Pré-vendas</div>{chip_area('prevendas')}</div>"
            "<div class=agrid>"
            + am(_num(sales["reunioes"]), "SQLs (agendaram)")
            + am(taxa_txt, "lead→SQL", c_taxa)
            + am(speed_txt, "1º contato (mediana)",
                 "var(--status-critico)" if (sales["speed_med"] or 0) > 60 else None)
            + am(fila_txt, "leads sem 1º contato", c_fila)
            + f"</div><div class=ad>{escape(saude['prevendas'][1])} · leads do mês no card de Marketing</div></a>")
        v_bk, c_bk = vs_meta(sales["book"], sales.get("book_meta"), mkt["frac"] if mkt else 1.0)
        rec_txt = _fmt_brl(sales["receita"])
        if sales.get("receita_meta"):
            rec_txt += (f"<span style='color:var(--text-faint);font-size:14px'>"
                        f"/{_fmt_brl(sales['receita_meta'])}</span>")
        ticket_txt = _fmt_brl(sales["receita"] / sales["book"]) if sales["book"] else "—"
        vd_card = (
            "<a class='area big' href='/vendas'><div class=ahead>"
            f"<div class=an>Vendas</div>{chip_area('vendas')}</div>"
            "<div class=agrid>"
            + am(v_bk, "bookings no mês", c_bk)
            + am(rec_txt, "receita/meta")
            + am(ticket_txt, "ticket médio do mês")
            + am(_num(sales["pipeline"]), "deals abertos no pipe")
            + f"</div><div class=ad>{escape(saude['vendas'][1])}</div></a>")
    else:
        pv_card = ("<a class='area' href='/prevendas'><div class=ahead>"
                   f"<div class=an>Pré-vendas</div>{chip_area('prevendas')}</div>"
                   "<div class=ad>funil de qualificação, speed-to-lead e planos por SDR — do lead à reunião agendada</div></a>")
        vd_card = ("<a class='area' href='/vendas'><div class=ahead>"
                   f"<div class=an>Vendas</div>{chip_area('vendas')}</div>"
                   "<div class=ad>Oportunidade→Booking, win/loss, ciclo, forecast e planos por closer</div></a>")
    if ops:
        c_atras = "var(--status-critico)" if ops["atras"] else None
        op_card = (
            "<a class='area big' href='/operacoes'><div class=ahead>"
            f"<div class=an>Operações</div>{_chip('ativa', '--status-baixo')}</div>"
            "<div class=agrid>"
            + am(_num(ops["total"]), f"iniciativas no Q{ops['quarter']}")
            + am(_num(ops["atras"]), "atrasadas", c_atras)
            + am(_num(ops["ok"]), "concluídas")
            + am(f"{ops['progresso']:.0f}%", "progresso")
            + "</div><div class=ad>iniciativas por área da empresa (Notion) — semáforo de prazo e KPIs vs meta trimestral</div></a>")
    else:
        op_card = ("<a class='area' href='/operacoes'><div class=ahead>"
                   f"<div class=an>Operações</div>{_chip('ativa', '--status-baixo')}</div>"
                   "<div class=ad>iniciativas por área da empresa (Notion) — semáforo de prazo e dependências por trimestre</div></a>")
    # ---- card Financeiro no MESMO molde das outras áreas (15/07): realizado
    # ao vivo × meta da planilha, colorido pelo ritmo do mês
    fin_card = ("<a class='area big' href='/financeiro'><div class=ahead>"
                f"<div class=an>Financeiro</div>{_chip('ativa', '--status-baixo')}</div>"
                "<div class=ad>planejamento × realizado — recebimento, bookings vs meta, "
                "funil projetado e receita recorrente</div></a>")
    try:
        from .sources import planejamento_financeiro as _PF
        _fin = _PF.carrega()
        _hj = dt.date.today()
        _iso = f"{_hj.year:04d}-{_hj.month:02d}"
        if _fin and _iso in _fin["meses"]:
            import calendar as _cal
            _i = _fin["meses"].index(_iso)
            _frac = mkt["frac"] if mkt else _hj.day / _cal.monthrange(_hj.year, _hj.month)[1]
            _mb = _PF.linha(_fin, "Meta Bookings [R$]")[_i]
            _mr = _PF.linha(_fin, "Recebimento TOTAL [R$]")[_i]
            _rec_pct = _PF.linha(_fin, "Recebimento RECORRENTE [%]")[_i]
            _inad = _PF.linha(_fin, "Inadimplência [%]")[_i]
            _isr = _PF.linha(_fin, "ÍSR - Índice")[_i]
            _rec_live = sales["receita"] if sales else None
            # chip pelo ritmo da receita × meta (o NÚMERO em si fica no card de
            # Vendas — aqui é caixa/estrutura, sem repetir bookings; 16/07)
            _no_ritmo = (_rec_live / _mb >= _frac) if (_rec_live is not None and _mb) else None
            _chip_fin = (_chip("no ritmo", "--status-baixo") if _no_ritmo
                         else _chip("atrás da meta", "--status-alto") if _no_ritmo is not None
                         else _chip("ativa", "--status-baixo"))
            fin_card = ("<a class='area big' href='/financeiro'><div class=ahead>"
                        f"<div class=an>Financeiro</div>{_chip_fin}</div>"
                        "<div class=agrid>"
                        + am(_fmt_brl(_mr) if _mr else "—", "recebimento projetado do mês")
                        + am(f"{_rec_pct * 100:.0f}%" if _rec_pct is not None else "—", "% recorrente projetado")
                        + am(f"{_inad * 100:.1f}%" if _inad is not None else "—", "inadimplência alvo",
                             None if _inad is None else ("var(--status-baixo)" if _inad <= 0.04 else
                                                         "var(--status-medio)" if _inad <= 0.08 else "var(--status-critico)"))
                        + am(f"{_isr:,.0f}".replace(",", ".") if _isr is not None else "—", "ISR B2-B5 (≥100 = crescendo)",
                             None if _isr is None else ("var(--status-baixo)" if _isr >= 100 else "var(--status-critico)"))
                        + f"</div><div class=ad>ritmo esperado {_frac * 100:.0f}% do mês · chip = receita × meta (número no card de Vendas) · "
                          "receita recorrente na aba própria</div></a>")
    except Exception:  # noqa: BLE001 — planilha fora não derruba a central
        pass
    area_cards = growth_card + mkt_card + pv_card + vd_card + op_card + fin_card

    # ---- KPIs do topo: retenção (Growth) + aquisição (Marketing)
    kpis = [
        (_num(st["monitored"]), "Contas monitoradas", None),
        (_num(n_alerts), "Alertas abertos", "var(--status-critico)" if n_alerts else None),
        (_fmt_brl(st["mrr_risk"]), "MRR em risco", "var(--status-alto)" if st["mrr_risk"] else None),
    ]
    if mkt and mkt.get("leads_meta"):
        v, c = vs_meta(mkt["leads"], mkt["leads_meta"], mkt["frac"])
        kpis.append((v, "Leads no mês", c))
    if mkt and mkt.get("book_meta"):
        v, c = vs_meta(mkt["book"], mkt["book_meta"], mkt["frac"])
        kpis.append((v, "Bookings no mês", c))
    if sales:
        kpis.append((_fmt_brl(sales["receita"]), "Receita no mês",
                     None if not sales.get("receita_meta") else
                     ("var(--status-baixo)" if mkt and sales["receita"] / sales["receita_meta"] >= mkt["frac"]
                      else "var(--status-critico)")))
    if len(kpis) == 3:
        kpis.append(("6<span style='color:var(--text-faint);font-size:18px'>/6</span>",
                     "Áreas ativas", None))
    kpi_html = "".join(
        f"<div class=kpi><div class=n{f' style=\"color:{c}\"' if c else ''}>{v}</div>"
        f"<div class=l>{lbl}</div></div>" for v, lbl, c in kpis)

    # ---- faixa de saúde por área (pior primeiro = onde olhar agora)
    hbar = ""
    for arn in sorted(saude, key=lambda k: -_NIVEL[saude[k][0]][2]):
        nv, motivo = saude[arn]
        var, lbl, sev = _NIVEL[nv]
        nome, href = _AREA_LBL[arn]
        tag = ("<span class=htag>maior atenção agora</span>"
               if arn == pior and _NIVEL[pior_nv][2] >= 1 else "")
        hbar += (f"<a class='hpill{' hpill-pior' if arn == pior and _NIVEL[pior_nv][2] >= 1 else ''}' href='{href}'>"
                 f"<span class=sdot style='--c:var({var})'></span>"
                 f"<div style='min-width:0'><div class=hn>{nome} · <span style='color:var({var})'>{lbl}</span>{tag}</div>"
                 f"<div class=hm>{escape(motivo)}</div></div></a>")

    head = """<!doctype html><html lang=pt-br><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Integracomm IA — Central</title>
<link rel=preconnect href="https://fonts.googleapis.com"><link rel=preconnect href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Poppins:wght@500;600;700&display=swap" rel=stylesheet>
<style>
__TOKENS__
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
.nav-item.soon{opacity:.55} .nav-item .tag{font-size:9px;text-transform:uppercase;letter-spacing:.08em;color:var(--text-faint)}
/* cabeçalho de GRUPO no sidebar (não clicável): Áreas × Visões da empresa —
   área = lugar da empresa; visão = corte transversal dos dados (17/07) */
.nav-h{font-size:9.5px;text-transform:uppercase;letter-spacing:.14em;color:var(--text-faint);padding:14px 12px 4px}
.rail-foot{padding:12px 16px;border-top:1px solid var(--border);font-size:var(--fs-2xs);color:var(--text-muted);line-height:1.5}
main{flex:1;min-width:0;padding:26px 32px 48px;max-width:var(--content-max)}
h1{font-family:var(--font-display);font-weight:700;font-size:var(--fs-h1);letter-spacing:var(--tracking-tight);margin:0}
.sub{font-size:var(--fs-sm);color:var(--text-muted);margin-top:6px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-top:22px}
.kpi{background:var(--surface-1);border:1px solid var(--border-mid);border-radius:var(--radius-md);padding:16px 18px}
.kpi .n{font-family:var(--font-display);font-weight:700;font-size:28px;line-height:1}
.kpi .l{font-size:var(--fs-2xs);color:var(--text-muted);text-transform:uppercase;letter-spacing:var(--tracking-label);margin-top:8px}
/* camadas do cockpit com SEPARAÇÃO clara (20/07): divisor entre seções +
   acento dourado no título — hierarquia visual, não blocos soltos */
section{margin-top:32px;padding-top:22px;border-top:1px solid var(--border)}
section:first-of-type{border-top:none;padding-top:0}
h2{font-family:var(--font-display);font-weight:600;font-size:var(--fs-lg);margin:0 0 4px;position:relative;padding-left:12px}
h2::before{content:"";position:absolute;left:0;top:4px;bottom:4px;width:3px;border-radius:2px;background:var(--brand)}
.secsub{font-size:var(--fs-sm);color:var(--text-muted);margin:0 0 14px;line-height:1.55;max-width:980px}
.areas{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:12px}
.area{display:block;background:var(--surface-1);border:1px solid var(--border-mid);border-radius:var(--radius-md);padding:16px 18px}
.area:hover{background:var(--surface-2);border-color:var(--border-strong)}
.area.soon{opacity:.55}
.area.big{grid-column:span 2}
@media (max-width:760px){.area.big{grid-column:span 1}}
.ahead{display:flex;align-items:center;justify-content:space-between;gap:10px}
.agrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:10px;margin:12px 0 10px}
.am .av{font-family:var(--font-display);font-weight:700;font-size:21px;line-height:1.1}
.am .al{font-size:var(--fs-2xs);color:var(--text-muted);text-transform:uppercase;letter-spacing:var(--tracking-label);margin-top:4px}
.an{font-family:var(--font-display);font-weight:600;font-size:15px}
.ast{margin:8px 0}
.ad{font-size:var(--fs-sm);color:var(--text-muted);line-height:1.45}
.central{background:var(--surface-1);border:1px solid var(--border-mid);border-left:3px solid var(--brand);border-radius:var(--radius-md);padding:18px 20px}
.hbar{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:10px}
.hpill{display:flex;gap:10px;align-items:flex-start;background:var(--surface-1);border:1px solid var(--border-mid);border-radius:var(--radius-md);padding:13px 15px}
.hpill:hover{background:var(--surface-2);border-color:var(--border-strong)}
.hpill .sdot{width:9px;height:9px;margin-top:4px;flex-shrink:0}
.hpill-pior{border-color:var(--status-critico);box-shadow:inset 3px 0 0 var(--status-critico)}
.hn{font-family:var(--font-display);font-weight:600;font-size:13.5px}
.hm{font-size:var(--fs-xs);color:var(--text-muted);line-height:1.45;margin-top:3px}
.htag{margin-left:8px;font-size:9px;text-transform:uppercase;letter-spacing:.08em;color:var(--status-critico);border:1px solid var(--status-critico);border-radius:999px;padding:2px 7px;vertical-align:middle;white-space:nowrap}
.init{display:flex;gap:10px;align-items:flex-start;padding:10px 0;border-top:1px solid var(--border)}
.init:first-child{border-top:none;padding-top:0}
.init .sdot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--c);margin-top:5px;flex-shrink:0}
a.init{text-decoration:none;color:inherit;cursor:pointer}
a.init:hover .it{color:var(--brand)}
a.init .ig{margin-left:auto;align-self:center;color:var(--text-faint);flex-shrink:0}
a.init:hover .ig{color:var(--brand)}
.it{font-weight:var(--fw-semibold);font-size:var(--fs-md)}
.id_{font-size:var(--fs-sm);color:var(--text-muted);line-height:1.5;margin-top:2px}
.foot{font-size:var(--fs-xs);color:var(--text-faint);margin-top:24px}
</style></head><body>
<div class=app>
 <aside class=rail>
   <div class=brand><div class=logo></div><div><div class=bt>Integracomm IA</div><div class=bs>Central</div></div></div>
   <nav>
     <a class="nav-item__HOME_ON__" href="/">Início</a>
     <a class="nav-item__ADM_ON__" href="/admin">Painel Administrativo</a>
     <div class="nav-h">Áreas</div>
     <a class="nav-item" href="/growth">Growth / Assessoria</a>
     <a class="nav-item" href="/marketing">Marketing</a>
     <a class="nav-item" href="/prevendas">Pré-vendas</a>
     <a class="nav-item" href="/vendas">Vendas</a>
     <a class="nav-item" href="/operacoes">Operações</a>
     <a class="nav-item" href="/financeiro">Financeiro</a>
     <div class="nav-h">Visões da empresa</div>
     <a class="nav-item__SM_ON__" href="/semana">Ações da Semana</a>
     <a class="nav-item__RX_ON__" href="/raiox">Raio-X por Bundle</a>
   </nav>
   <div class=rail-foot><b>__USERMAIL__</b> · <a href="/logout" style="color:var(--text-muted);text-decoration:underline">sair</a><br>humano no loop — a IA só sinaliza</div>
 </aside>
 <main>
__BODY__
  <p class=foot>Derivados do Postgres próprio (LGPD: sem conteúdo bruto). A IA calcula, exibe e sinaliza — a decisão é sempre humana.</p>
 </main>
</div>
</body></html>"""
    if page == "admin":
        body = (
            "<h1>Painel Administrativo</h1>"
            "<p class=sub>controle de acessos por conta — aprovar/bloquear cadastros e definir quais áreas cada usuário enxerga</p>"
            + _llm_budget_html(llm) + teams_html +
            "<section><h2>Contas e permissões</h2>"
            "<p class=secsub>pendentes primeiro · os interruptores aplicam NA HORA (vale em até 60s) · busca por nome/e-mail</p>"
            + _admin_html(users or []))
    else:
        # COCKPIT (17/07): camadas em ordem de atenção — foco da semana → o que
        # mudou → saúde → raio-x compacto → cards de área → iniciativas →
        # defasagem (recolhida). Cada bloco resume e LINKA; nada recalculado.
        body = (
            "<h1>Visão central</h1>"
            "<p class=sub>o cockpit da empresa: o foco da semana e o que mudou primeiro; abaixo, o estado de cada "
            "bundle e de cada área, as iniciativas priorizadas por R$ e as defasagens — cada bloco abre a visão completa.</p>"
            + foco_html
            + mudancas +
            "<section><h2>Números-chave do mês</h2>"
            "<p class=secsub>retenção (Growth) e aquisição (Marketing/Vendas) — o termômetro rápido antes do detalhe por área</p>"
            f"<div class=kpis style='margin-top:0'>{kpi_html}</div></section>"
            "<section><h2>Saúde por área</h2>"
            "<p class=secsub>diagnóstico automático do mês corrente, ordenado da área que mais demanda atenção para a mais saudável — clique para abrir</p>"
            f"<div class=hbar>{hbar}</div></section>"
            + raiox_mini +
            "<section><h2>Áreas</h2>"
            "<p class=secsub>resumo do andamento de cada área — clique para abrir o painel completo; verde = no ritmo/meta, vermelho = atenção</p>"
            f"<div class=areas>{area_cards}</div></section>"
            "<section><h2>Iniciativas de maior horizonte</h2>"
            "<p class=secsub>gargalos medidos que NÃO viraram objetivo desta semana (estruturais ou de prazo maior) — "
            "ordenados pelo impacto estimado em R$/mês, com premissa e defasagem; candidatos naturais às próximas semanas</p>"
            + _hint("Iniciativas de maior horizonte",
                    "O que mostra: os gargalos com impacto em R$/mês que não couberam nos objetivos DESTA semana — "
                    "o que casa com um objetivo confirmado é absorvido pelos cards de 'Prioridades da Semana' lá em "
                    "cima; aqui fica o horizonte maior.\n"
                    "Como ler: a faixa (conservador–otimista) e a PREMISSA de cada estimativa estão escritas no item — "
                    "são potenciais, não promessas. Cada item traz a defasagem esperada (quando cobrar resultado) e "
                    "abre a tela com os dados.\n"
                    "Fique de olho: (1) item que passa semanas aqui sem virar objetivo = gargalo estrutural — merece "
                    "projeto próprio, não semana; (2) valide as premissas com o gestor da área; (3) 'exposição' "
                    "(execução crítica) é risco exposto, não perda certa.")
            + f"<div class=central>{init_html}</div></section>"
            # defasagem RECOLHIDA por padrão (Cockpit): é referência de consulta
            # ('quando cobrar'), não leitura diária
            "<details style='margin-top:var(--space-8)'>"
            "<summary style='cursor:pointer;font-family:var(--font-display);font-weight:600;"
            "font-size:var(--fs-lg);list-style:none'>Defasagem esperada das correções "
            "<span style='font-size:var(--fs-2xs);color:var(--text-faint);font-weight:400'>"
            "(referência — clique para abrir)</span></summary>"
            "<p class=secsub style='margin-top:6px'>medida no NOSSO histórico (medianas) — quando cobrar resultado "
            "de cada tipo de correção; onde não há base, está dito</p>"
            f"<div class=central>{defasagem_html}</div></details>"
            # botão All Hands ao FINAL da página (Otávio 15/07: uso 1x/mês —
            # posição discreta, mas com cara de botão)
            "<p class=note style='margin-top:18px'><a href='/allhands' style='display:inline-block;"
            "background:var(--brand);color:var(--brand-ink);border-radius:var(--radius-sm);"
            "font-weight:600;font-size:var(--fs-sm);padding:8px 14px;text-decoration:none'>"
            "🎤 Gerar apresentação All Hands</a> "
            "<span style='color:var(--text-muted);font-size:var(--fs-sm)'>slides do mês fechado com os dados do painel + "
            "destaques/orientações que você preencher</span></p>")
            # Saúde da Receita Recorrente mudou p/ /financeiro?view=receita (15/07)
    if body_override is not None:  # página avulsa com o shell da central (Raio-X)
        body = body_override
    return (head.replace("__TOKENS__", _tokens_css()).replace("__USERMAIL__", escape(role))
            .replace("__HOME_ON__", " active" if page != "admin" and body_override is None else "")
            .replace("__ADM_ON__", " active" if page == "admin" else "")
            .replace("__RX_ON__", " active" if active_page == "raiox" else "")
            .replace("__SM_ON__", " active" if active_page == "semana" else "")
            .replace("__BODY__", body))


def _render_hub_page(role: str, body: str, active: str = "") -> str:
    """Página avulsa (ex.: /raiox) com o MESMO shell/nav da central — corpo
    pronto; os stats vazios não aparecem porque o body é substituído."""
    st_vazio = {"sev": {}, "mrr_crit": 0.0, "mrr_risk": 0.0, "monitored": 0,
                "evaluable": 0, "non_eval": 0, "non_eval_antigas": 0, "exec_late": 0}
    return _render_hub(role, st_vazio, body_override=body, active_page=active)


# mapeamento semântico -> variável de token (design-tokens.css é a fonte da verdade)
_BAND_VAR = {"critico": "--status-critico", "alto": "--status-alto", "medio": "--status-medio",
             "baixo": "--status-baixo", "sem_dados": "--status-semdados"}
_SEV_VAR = {"critico": "--status-critico", "alto": "--status-alto", "atencao": "--status-medio"}
_DASH = "<span style='color:var(--text-faint)'>—</span>"


def _tokens_css() -> str:
    """design-tokens.css inline (fonte única). Sem custo: lido do disco 1x."""
    global _TOKENS_CACHE
    try:
        return _TOKENS_CACHE
    except NameError:
        pass
    p = _ROOT / "frontend" / "design-tokens.css"
    css = p.read_text(encoding="utf-8") if p.exists() else ""
    globals()["_TOKENS_CACHE"] = css
    return css


def _chip(label: str, var: str, dot: bool = False) -> str:
    d = "<span class='dot'></span>" if dot else ""
    return f"<span class='chip' style='--c:var({var})'>{d}{escape(label)}</span>"


def _mrr_val(s) -> float:
    v = s.get("recurring_revenue")
    return float(v) if v is not None else -1.0


def _mrr_txt(s) -> str:
    v = s.get("recurring_revenue")
    return f"R$ {float(v):,.0f}".replace(",", ".") if v is not None else _DASH


def _exec_badge(s) -> str:
    """Selo de execução (ClickUp): situação das ENTREGAS da conta. Só o rótulo
    (saudável / atenção / crítica — rótulos de SAÚDE, não de pontualidade:
    nota 72 pode conviver com tarefa vencida ontem, caso LOJA REIS 16/07;
    CRÍTICA ≠ tarefa atrasada; a CAUSA fica no motivo/hover)."""
    v = s.get("exec_score")
    if v is None:
        return _DASH
    if v >= 70:
        var, txt = "--status-baixo", "saudável"
    elif v >= 40:
        var, txt = "--status-medio", "atenção"
    else:
        var, txt = "--status-critico", "crítica"
    mot = escape((s.get("exec_motivo") or "")[:140])
    tip = f"Saúde de execução no ClickUp: {v:.0f}/100. {mot}"
    return f"<span class='chip' style='--c:var({var})' title='{tip}'>{txt}</span>"


def _tag(name: str) -> str:
    """Tag completa do nome do grupo (ex.: ST-B1-S2) — mostrada no hover."""
    m = re.match(r"\s*\[([^\]]+)\]", name or "")
    return m.group(1).strip().upper() if m else "—"


def _squad(name: str) -> str:
    """Squad = os tokens Bx-Sy da convenção de nome `[TAG-Bx-Sy]` (ex.: B2-S2,
    B3-S1). Grupos sem Bx-Sy (ex.: ADS puros) caem no prefixo do tag (ADS, MKP…).
    Uso interno/legado — para exibição/filtro use `_squad_label` (valida na
    planilha) e para agregação por squad use `_resolve_squad`."""
    tag = _tag(name)
    m = re.search(r"B(\d)\D*S(\d)", tag)
    if m:
        return f"B{m.group(1)}-S{m.group(2)}"
    p = re.match(r"([A-Z]+)", tag)
    return p.group(1) if p else "—"


# status no tag (com tolerância a erros de digitação: FINALZADO, PROROGADO…)
_STATUS_WORDS = re.compile(r"\b(PAUS\w*|PRORROG\w*|PROROG\w*|ENCERR\w*|FINAL\w*|CANCEL\w*)\b", re.I)
_SQUAD_TOKEN = re.compile(r"B\d\s*-?\s*S\d")


def _service(name: str) -> str | None:
    """Código do SERVIÇO/plano no tag (ADS, ST, T, S, M, CONF, P, A, MKP, PBP…),
    ignorando status (PAUSADO/FINALIZADO…). É o prefixo de letras ANTES do
    Bx-Sy — assim o `B` de `B1-S2` nunca vira 'serviço' quando não há prefixo."""
    tag = _tag(name)
    if tag == "—":
        return None
    clean = _STATUS_WORDS.sub("", tag).strip(" -")
    before = _SQUAD_TOKEN.split(clean)[0].strip(" -")  # parte antes do 1º Bx-Sy
    m = re.match(r"([A-Za-z]+)", before)
    return m.group(1).upper() if m else None


def _squad_label(name: str, mirror: dict | None) -> str:
    """Rótulo de exibição/filtro: SERVIÇO + squad VÁLIDO (ex.: `ADS-B3-S2`) —
    mantém o tipo de serviço junto do bundle p/ filtragem, mas o squad é sempre
    o real da planilha (via `_resolve_squad`, com fallback do espelho). Sem squad
    conhecido, mostra só o serviço; sem serviço, só o squad; senão `—`."""
    svc = _service(name)
    sq = _resolve_squad(name, mirror)
    if svc and sq:
        return f"{svc}-{sq}"
    return sq or svc or "—"


def _guide(s: dict, practices: dict | None = None) -> str:
    g = action_guideline(
        s["stage"], is_legacy=bool(s.get("is_legacy")),
        recurring_revenue=(float(s["recurring_revenue"]) if s.get("recurring_revenue") is not None else None),
        evaluable=bool(s["evaluable"]),
        reasons=s.get("reasons"), exec_score=s.get("exec_score"),
    )
    # aprendizado: cita a prática que mais reteve em casos com a MESMA dor
    if practices:
        driver = _top_driver(s.get("reasons") or [])
        hit = practices.get(driver or "")
        if hit:
            action, n = hit
            g += f" 📚 Já funcionou nesta dor: “{action}” (reteve {n}×)."
    return g


_STAGE_LABEL = {"saudavel": "saudável", "desengajamento_inicial": "desengajamento",
                "insatisfacao_latente": "insatisfação latente", "insatisfacao_ativa": "insatisfação ativa",
                "intencao_de_saida": "intenção de saída", "nao_avaliavel": "não avaliável"}


def _carga_content(scores: list[dict], mirror: dict | None) -> str:
    """Carga e Capacidade por Squad (cross-área #2, 14/07): risco por TIME e
    por responsável, não por conta — alocação e suporte, NÃO ranking.
    Squad = o REAL da planilha de composição (S1..S8, sem fragmentar por
    serviço/bundle — feedback 14/07); responsável = campo 'gerente de contas'
    do espelho da Operação (mistura Growth e GC; cobertura reportada)."""
    def agrega(chave):
        m: dict[str, dict] = {}
        for s in scores:
            k = chave(s)
            d = m.setdefault(k, {"n": 0, "mrr": 0.0, "mrr_risco": 0.0, "crit": 0, "alto": 0,
                                 "atencao": 0, "exec_atr": 0, "bandas": {"baixo": 0, "medio": 0, "alto": 0, "critico": 0, "sem": 0}})
            d["n"] += 1
            mrr = max(0.0, _mrr_val(s))
            d["mrr"] += mrr
            band = s["risk_band"] if s["evaluable"] else "sem"
            d["bandas"][band if band in d["bandas"] else "sem"] += 1
            if band in ("alto", "critico"):
                d["mrr_risco"] += mrr
            sev = s.get("alert_sev")
            if sev in ("critico", "alto", "atencao"):
                d[sev if sev != "critico" else "crit"] = d.get(sev if sev != "critico" else "crit", 0) + 1
            if (s.get("exec_score") or 100) < 40:
                d["exec_atr"] += 1
        return m

    por_squad = agrega(lambda s: _resolve_squad(s["name"], mirror) or "(sem squad na planilha)")
    tot_risco = sum(d["mrr_risco"] for d in por_squad.values()) or 1.0
    _td = "padding:7px 9px;border-bottom:1px solid var(--border);text-align:right;font-variant-numeric:tabular-nums;font-size:var(--fs-sm)"
    _tdl = _td.replace("text-align:right", "text-align:left")

    def tabela(m, rotulo):
        linhas = ""
        for k, d in sorted(m.items(), key=lambda x: (x[0].startswith("(sem"), -x[1]["mrr_risco"], -x[1]["crit"])):
            conc = d["mrr_risco"] / tot_risco
            chip = (" <span class=chip style='--c:var(--status-critico)'>concentração de risco</span>"
                    if (d["crit"] >= 3 or conc >= 0.3) and not k.startswith("(sem") else "")
            faixas = (f"<span style='color:var(--status-baixo)'>{d['bandas']['baixo']}</span> · "
                      f"<span style='color:var(--status-medio)'>{d['bandas']['medio']}</span> · "
                      f"<span style='color:var(--status-alto)'>{d['bandas']['alto']}</span> · "
                      f"<span style='color:var(--status-critico)'>{d['bandas']['critico']}</span>"
                      + (f" · <span style='color:var(--text-faint)'>{d['bandas']['sem']} s/d</span>" if d['bandas']['sem'] else ""))
            linhas += (f"<tr><td style='{_tdl}'><b>{escape(k)}</b>{chip}</td>"
                       f"<td style='{_td}'>{d['n']}</td>"
                       f"<td style='{_td}'>R$ {d['mrr']:,.0f}</td>".replace(",", ".") +
                       f"<td style='{_td};color:var(--status-critico)'>{d['crit'] or ''}</td>"
                       f"<td style='{_td}'>{d['alto'] or ''}</td>"
                       f"<td style='{_td}'>{d['atencao'] or ''}</td>"
                       f"<td style='{_td}'>R$ {d['mrr_risco']:,.0f} ({conc * 100:.0f}%)</td>".replace(",", ".") +
                       f"<td style='{_td}'>{d['exec_atr'] or ''}</td>"
                       f"<td style='{_td};text-align:center'>{faixas}</td></tr>")
        ths = "".join(f"<th style='text-align:{al};padding:7px 9px;font-size:var(--fs-2xs)'>{h}</th>" for h, al in
                      ((rotulo, "left"), ("Contas", "right"), ("MRR", "right"), ("Crít.", "right"),
                       ("Alto", "right"), ("Aten.", "right"), ("MRR em risco", "right"),
                       ("Exec. crítica", "right"), ("Faixas 🟢🟡🟠🔴", "center")))
        return f"<div class=central style='padding:6px 14px 12px;overflow-x:auto'><table style='width:100%;border-collapse:collapse'><tr>{ths}</tr>{linhas}</table></div>"
    # ---- capacidade de atendimento: carteira ÷ tamanho do time (14/07 —
    # substitui 'Por responsável': não existe UM responsável, é o squad; o
    # Growth é o líder. Pergunta: o time dá conta? Redistribuir clientes?
    try:
        from .sources.squads_sheet import squad_teams
        times = squad_teams()
    except Exception:  # noqa: BLE001 — planilha fora não derruba a aba
        times = {}
    cap_rows = []
    for k, d in por_squad.items():
        if k.startswith("(sem"):
            continue
        pessoas = len(times.get(k, []))
        cap_rows.append((k, pessoas, d))
    # tarefas ABERTAS por squad (Otávio 16/07): contas/pessoa sozinho engana —
    # tarefas recorrentes (semanais+) fazem squads com MENOS contas carregarem
    # MAIS trabalho; a carga real é o nº de tarefas ativas no ClickUp
    try:
        from .sources.clickup_activities import open_task_ids as _open_fn
    except Exception:  # noqa: BLE001
        _open_fn = None
    # clientes pausados por inadimplência/concluídos ficam FORA das contagens
    # de tarefas (capacidade e atrasos): serviço suspenso não é carga nem
    # cobrança do squad (Otávio 20/07 — pausados inflavam os números)
    try:
        from .sources.clickup_activities import client_inactive_status as _inat_fn
    except Exception:  # noqa: BLE001
        _inat_fn = None

    def _inativo(nm: str) -> str | None:
        return _inat_fn(nm) if _inat_fn else None
    # dedupe por ID de tarefa (caso LUFRAN 20/07): cliente com 2+ contas no
    # painel (bundle + ADS, ou grupo duplicado) casa com o MESMO card do
    # ClickUp e a tarefa contava 2x. A conta 'principal' (não-ADS) entra
    # primeiro e fica com a atribuição.
    def _ordem_dedup(s):
        return (s["name"].upper().lstrip("[ ").startswith("ADS"), s["name"])
    tarefas_sq: dict[str, int] = {}
    _abertas_vistas: set[str] = set()
    if _open_fn is not None:
        for s in sorted(scores, key=_ordem_dedup):
            k_sq = _resolve_squad(s["name"], mirror)
            if k_sq is None or _inativo(s["name"]):
                continue
            try:
                ids = _open_fn(s["name"]) or set()
            except Exception:  # noqa: BLE001 — conta sem match não derruba a aba
                continue
            novas = ids - _abertas_vistas
            _abertas_vistas |= novas
            tarefas_sq[k_sq] = tarefas_sq.get(k_sq, 0) + len(novas)
    medias = [d["n"] / p for _k, p, d in cap_rows if p]
    med_cp = (sum(medias) / len(medias)) if medias else None
    _tps = [tarefas_sq.get(k, 0) / p for k, p, _d in cap_rows if p] if tarefas_sq else []
    med_tp = (sum(_tps) / len(_tps)) if _tps else None
    linhas_cap = ""
    sobre, folga = [], []
    for k, p, d in sorted(cap_rows, key=lambda x: -(x[2]["n"] / x[1] if x[1] else 0)):
        cp = d["n"] / p if p else None
        graves = d["crit"] + d["alto"]
        chip = ""
        if cp is not None and med_cp:
            if cp >= med_cp * 1.3:
                chip = " <span class=chip style='--c:var(--status-critico)'>sobrecarga</span>"
                sobre.append((k, cp, graves))
            elif cp <= med_cp * 0.7:
                chip = " <span class=chip style='--c:var(--status-baixo)'>folga</span>"
                folga.append((k, cp))
        saudaveis = d["bandas"]["baixo"]
        avaliadas = d["n"] - d["bandas"]["sem"]
        mrr_p = f"R$ {d['mrr'] / p:,.0f}".replace(",", ".") if p else "—"
        cp_txt = f"{cp:.1f}" if cp is not None else "—"
        graves_p = f"{graves / p:.1f}" if p else "—"
        saud_txt = f"{saudaveis / avaliadas * 100:.0f}%" if avaliadas else "—"
        tar = tarefas_sq.get(k, 0)
        tp = tar / p if p else None
        # tarefas/pessoa colorida vs média: é a CARGA REAL — pode divergir de
        # contas/pessoa quando o mix tem muita tarefa recorrente
        tp_cor = ""
        if tp is not None and med_tp:
            if tp >= med_tp * 1.3:
                tp_cor = ";color:var(--status-critico);font-weight:700"
            elif tp <= med_tp * 0.7:
                tp_cor = ";color:var(--status-baixo)"
        tar_txt = f"{tar}" if tarefas_sq else "—"
        tp_txt = f"{tp:.0f}" if tp is not None and tarefas_sq else "—"
        linhas_cap += (f"<tr><td style='{_tdl}'><b>{escape(k)}</b>{chip}</td>"
                       f"<td style='{_td}'>{p or '—'}</td>"
                       f"<td style='{_td}'>{d['n']}</td>"
                       f"<td style='{_td}'><b>{cp_txt}</b></td>"
                       f"<td style='{_td}'>{tar_txt}</td>"
                       f"<td style='{_td}{tp_cor}'>{tp_txt}</td>"
                       f"<td style='{_td}'>{mrr_p}</td>"
                       f"<td style='{_td}'>{graves_p}</td>"
                       f"<td style='{_td}'>{saud_txt}</td></tr>")
    leitura_cap = "Cargas relativamente equilibradas entre os squads — sem caso claro de redistribuição agora."
    if sobre:
        pior = sobre[0]
        alvo = f" O squad {folga[0][0]} tem folga ({folga[0][1]:.1f} contas/pessoa) e é o candidato natural a absorver contas do mesmo bundle." if folga else ""
        leitura_cap = (f"{pior[0]} está com {pior[1]:.1f} contas por pessoa (média: {med_cp:.1f}) e {pior[2]} alerta(s) grave(s) — "
                       f"candidato a redistribuição de clientes ou reforço.{alvo}")
    if tarefas_sq and med_tp:
        _rank_tp = sorted(((k, tarefas_sq.get(k, 0) / p) for k, p, _d in cap_rows if p), key=lambda x: -x[1])
        _rank_cp = sorted(((k, d["n"] / p) for k, p, d in cap_rows if p), key=lambda x: -x[1])
        if _rank_tp and _rank_cp and _rank_tp[0][0] != _rank_cp[0][0]:
            leitura_cap += (f" Atenção à carga REAL de trabalho: {_rank_tp[0][0]} lidera em tarefas abertas/pessoa "
                            f"({_rank_tp[0][1]:.0f}) embora {_rank_cp[0][0]} tenha mais contas/pessoa ({_rank_cp[0][1]:.1f}) — "
                            "tarefas recorrentes fazem a carga diferir do tamanho da carteira; use as duas colunas juntas.")
    ths_cap = "".join(f"<th style='text-align:{al};padding:7px 9px;font-size:var(--fs-2xs)'>{h}</th>" for h, al in
                      (("Squad", "left"), ("Pessoas", "right"), ("Contas", "right"), ("Contas/pessoa", "right"),
                       ("Tarefas abertas", "right"), ("Tarefas/pessoa", "right"),
                       ("MRR/pessoa", "right"), ("Graves/pessoa", "right"), ("% saudável", "right")))
    # ---- atividades em atraso por squad e por responsável (Otávio 16/07): os
    # atrasos que a aba Contas mostra por conta, agregados aqui por TIME e por
    # pessoa — e cruzados com contas/pessoa p/ responder se o atraso vem de
    # SOBRECARGA (capacidade) ou de RITMO/processo (squad sem excesso de carga)
    from collections import Counter
    try:
        from .sources.clickup_activities import _overdue_from_clickup as _atr_fn
    except Exception:  # noqa: BLE001 — sem ClickUp, a seção reporta indisponível
        _atr_fn = None
    atr_sq: dict[str, dict] = {}
    atr_resp: dict[str, dict] = {}
    atr_sem_squad = 0
    atr_inativos = 0        # tarefas vencidas de clientes pausados/concluídos
    atr_inativos_contas = 0  # (fora da conta — serviço suspenso; Otávio 20/07)
    atr_dup = 0             # mesma tarefa em 2+ contas do MESMO cliente (LUFRAN)
    _atr_vistas: set[str] = set()
    if _atr_fn is not None:
        _agora = dt.datetime.now(dt.timezone.utc)
        for s in sorted(scores, key=_ordem_dedup):
            try:
                tasks = _atr_fn(s["name"], _agora) or []
            except Exception:  # noqa: BLE001 — conta sem match não derruba a seção
                tasks = []
            if not tasks:
                continue
            if _inativo(s["name"]):
                atr_inativos += len(tasks)
                atr_inativos_contas += 1
                continue
            ineditas = [t for t in tasks if t["url"] not in _atr_vistas]
            atr_dup += len(tasks) - len(ineditas)
            _atr_vistas.update(t["url"] for t in ineditas)
            tasks = ineditas
            if not tasks:
                continue
            sq = _resolve_squad(s["name"], mirror)
            if sq is None:
                atr_sem_squad += len(tasks)
            else:
                d = atr_sq.setdefault(sq, {"tarefas": 0, "contas": 0, "pior": 0, "itens": []})
                d["tarefas"] += len(tasks)
                d["contas"] += 1
                d["pior"] = max(d["pior"], max(t["dias_atraso"] for t in tasks))
                d["itens"].extend((s["name"], t) for t in tasks)
            for t in tasks:
                for nome in (t.get("responsavel") or "(sem responsável)").split(", "):
                    r = atr_resp.setdefault(nome, {"tarefas": 0, "contas": set(), "squads": Counter(),
                                                   "pior": 0, "itens": []})
                    r["tarefas"] += 1
                    r["contas"].add(s["name"])
                    r["itens"].append((s["name"], t))
                    if sq:
                        r["squads"][sq] += 1
                    r["pior"] = max(r["pior"], t["dias_atraso"])
    # atrasos/pessoa por squad (mesmo denominador da capacidade) + correlação
    cp_by = {k: (d["n"] / p if p else None) for k, p, d in cap_rows}
    pess_by = {k: p for k, p, _d in cap_rows}
    apps = [atr_sq.get(k, {}).get("tarefas", 0) / p for k, p, _d in cap_rows if p]
    med_app = (sum(apps) / len(apps)) if apps else None

    def _pearson(pares: list[tuple[float, float]]) -> float | None:
        n = len(pares)
        if n < 3:
            return None
        mx = sum(x for x, _ in pares) / n
        my = sum(y for _, y in pares) / n
        sx = sum((x - mx) ** 2 for x, _ in pares) ** 0.5
        sy = sum((y - my) ** 2 for _, y in pares) ** 0.5
        if not sx or not sy:
            return None
        return sum((x - mx) * (y - my) for x, y in pares) / (sx * sy)

    _r_atr = _pearson([(cp_by[k], atr_sq.get(k, {}).get("tarefas", 0) / p)
                       for k, p, _d in cap_rows if p and cp_by.get(k) is not None])

    # drill-down (Otávio 16/07): clicar no squad/responsável abre a lista das
    # tarefas vencidas, cada uma com link direto p/ a TAREFA no ClickUp
    def _atr_lista(itens: list[tuple[str, dict]]) -> str:
        li = ""
        for conta, t in sorted(itens, key=lambda x: -x[1]["dias_atraso"]):
            nome_t = escape((t.get("nome") or "?")[:70])
            if t.get("url"):
                nome_t = (f"<a href='{t['url']}' target=_blank rel=noopener "
                          f"style='color:var(--text);text-decoration:underline;text-decoration-style:dotted' "
                          f"title='abrir a tarefa no ClickUp'>{nome_t}</a>")
            venceu = f"{t['vence_em'][8:10]}/{t['vence_em'][5:7]}" if t.get("vence_em") else "—"
            li += (f"<div style='display:flex;gap:10px;align-items:baseline;padding:4px 0;"
                   f"border-bottom:1px solid var(--border);font-size:var(--fs-xs)'>"
                   f"<span style='color:var(--status-critico);font-variant-numeric:tabular-nums;"
                   f"min-width:44px;text-align:right'>{t['dias_atraso']} d</span>"
                   f"<span style='flex:1;min-width:220px'>{nome_t}"
                   f"<span style='color:var(--text-muted)'> — {escape(conta[:42])}</span></span>"
                   f"<span style='color:var(--text-muted)'>{escape(t.get('responsavel') or 'sem responsável')}</span>"
                   f"<span style='color:var(--text-faint);white-space:nowrap'>venceu {venceu}</span></div>")
        return (f"<div style='padding:6px 10px 10px;background:var(--bg-panel);"
                f"border-radius:var(--radius-sm)'>{li}</div>")

    linhas_atr, top_atr = "", None
    for _i_sq, (k, _p, d) in enumerate(sorted(cap_rows, key=lambda x: -atr_sq.get(x[0], {}).get("tarefas", 0))):
        a = atr_sq.get(k, {"tarefas": 0, "contas": 0, "pior": 0})
        p = pess_by.get(k) or 0
        app = a["tarefas"] / p if p else None
        cp = cp_by.get(k)
        chip = ""
        # chip só quando o squad atrasa bem acima da média: a CAUSA provável
        # vem da comparação com a carga (contas/pessoa vs média dos squads)
        if app is not None and med_app and a["tarefas"] and app >= med_app * 1.3:
            if cp is not None and med_cp and cp >= med_cp * 1.3:
                chip = (" <span class=chip style='--c:var(--status-alto)' title='atrasos altos E carga alta: "
                        "o atraso é coerente com sobrecarga — redistribuir contas ou reforçar o time'>capacidade</span>")
            else:
                chip = (" <span class=chip style='--c:var(--status-critico)' title='atrasos altos SEM carga acima da média: "
                        "o gargalo não é falta de gente — revisar rotina, priorização e disciplina de prazo do squad'>ritmo/processo</span>")
        if top_atr is None and a["tarefas"]:
            top_atr = (k, a, chip)
        pct = f"{a['contas'] / d['n'] * 100:.0f}%" if d["n"] else "—"
        if a["tarefas"]:
            seta = ("<span style='color:var(--brand);font-size:var(--fs-2xs)' "
                    "title='clique para ver as tarefas'>▸</span> ")
            nome_sq = (f"<span style='cursor:pointer' onclick=\"atrTgl('atr-sq-{_i_sq}')\">"
                       f"{seta}<b style='text-decoration:underline;text-decoration-style:dotted'>{escape(k)}</b></span>")
        else:
            nome_sq = f"<b>{escape(k)}</b>"
        linhas_atr += (f"<tr><td style='{_tdl}'>{nome_sq}{chip}</td>"
                       f"<td style='{_td};color:var(--status-critico)'><b>{a['tarefas'] or ''}</b></td>"
                       f"<td style='{_td}'>{a['contas'] or ''}</td>"
                       f"<td style='{_td}'>{pct}</td>"
                       f"<td style='{_td}'>{f'{app:.1f}' if app is not None else '—'}</td>"
                       f"<td style='{_td}'>{f'{cp:.1f}' if cp is not None else '—'}</td>"
                       f"<td style='{_td}'>{a['pior'] or ''}</td></tr>")
        if a["tarefas"]:
            linhas_atr += (f"<tr id='atr-sq-{_i_sq}' style='display:none'>"
                           f"<td colspan=7 style='padding:2px 9px 10px'>{_atr_lista(a['itens'])}</td></tr>")
    ths_atr = "".join(f"<th style='text-align:{al};padding:7px 9px;font-size:var(--fs-2xs)'>{h}</th>" for h, al in
                      (("Squad", "left"), ("Tarefas atrasadas", "right"), ("Contas com atraso", "right"),
                       ("% da carteira", "right"), ("Atrasos/pessoa", "right"), ("Contas/pessoa", "right"),
                       ("Maior atraso (dias)", "right")))
    linhas_resp = ""
    resp_ord = sorted(atr_resp.items(), key=lambda x: -x[1]["tarefas"])
    for _i_r, (nome, r) in enumerate(resp_ord[:15]):
        sq_txt = ", ".join(f"{s} ({n})" for s, n in r["squads"].most_common(3)) or "—"
        seta = ("<span style='color:var(--brand);font-size:var(--fs-2xs)' "
                "title='clique para ver as tarefas'>▸</span> ")
        nome_r = (f"<span style='cursor:pointer' onclick=\"atrTgl('atr-rp-{_i_r}')\">"
                  f"{seta}<b style='text-decoration:underline;text-decoration-style:dotted'>{escape(nome)}</b></span>")
        linhas_resp += (f"<tr><td style='{_tdl}'>{nome_r}</td>"
                        f"<td style='{_td};color:var(--status-critico)'><b>{r['tarefas']}</b></td>"
                        f"<td style='{_td}'>{len(r['contas'])}</td>"
                        f"<td style='{_tdl}'>{escape(sq_txt)}</td>"
                        f"<td style='{_td}'>{r['pior']}</td></tr>"
                        f"<tr id='atr-rp-{_i_r}' style='display:none'>"
                        f"<td colspan=5 style='padding:2px 9px 10px'>{_atr_lista(r['itens'])}</td></tr>")
    ths_resp = "".join(f"<th style='text-align:{al};padding:7px 9px;font-size:var(--fs-2xs)'>{h}</th>" for h, al in
                       (("Responsável", "left"), ("Tarefas atrasadas", "right"), ("Contas", "right"),
                        ("Squad(s)", "left"), ("Maior atraso (dias)", "right")))
    # leitura automática: correlação carga × atraso responde a pergunta de
    # capacidade no agregado; o chip por squad responde caso a caso
    tot_atr = sum(a["tarefas"] for a in atr_sq.values())
    if _atr_fn is None:
        leitura_atr = "ClickUp não configurado — sem dados de atraso nesta visão."
    elif not tot_atr:
        leitura_atr = "Nenhuma tarefa aberta com vencimento estourado nos squads da planilha — carteira em dia."
    else:
        partes = []
        if top_atr:
            k, a, chip_top = top_atr
            causa = (" — e a carga dele também está acima da média: atraso coerente com SOBRECARGA"
                     if "capacidade" in chip_top else
                     " — SEM carga acima da média: aponta para ritmo/processo, não falta de gente"
                     if "ritmo" in chip_top else "")
            partes.append(f"{k} concentra mais atrasos ({a['tarefas']} tarefas em {a['contas']} conta(s)){causa}.")
        if _r_atr is not None:
            if _r_atr >= 0.5:
                partes.append(f"No agregado, atrasos ACOMPANHAM a carga (correlação {_r_atr:.2f} entre contas/pessoa e "
                              "atrasos/pessoa): o quadro geral é de capacidade — redistribuição/reforço tende a resolver.")
            elif _r_atr <= 0.1:
                partes.append(f"No agregado, atrasos NÃO acompanham a carga (correlação {_r_atr:.2f}): squads mais "
                              "carregados não são os que mais atrasam — o problema é de ritmo/processo em squads "
                              "específicos, não de falta de gente.")
            else:
                partes.append(f"Correlação carga × atraso moderada ({_r_atr:.2f}): capacidade explica parte dos atrasos, "
                              "mas há squads fora do padrão — olhar o chip de cada linha.")
        sem_resp = atr_resp.get("(sem responsável)", {}).get("tarefas", 0)
        if sem_resp:
            partes.append(f"{sem_resp} tarefa(s) vencida(s) SEM responsável atribuído no ClickUp — atraso órfão, "
                          "ninguém está sendo cobrado por elas.")
        leitura_atr = " ".join(partes)
    nota_atr = (f"<p class=note style='margin-top:8px'>{atr_sem_squad} tarefa(s) atrasada(s) em contas sem squad "
                "identificado ficaram fora da tabela.</p>" if atr_sem_squad else "")
    if atr_inativos:
        nota_atr += (f"<p class=note style='margin-top:4px'>{atr_inativos} tarefa(s) vencida(s) de "
                     f"{atr_inativos_contas} cliente(s) <b>pausado(s) por inadimplência ou concluído(s)</b> no ClickUp "
                     "ficaram fora das contagens — serviço suspenso não é cobrança do squad. "
                     "Voltam a contar se o cliente reativar.</p>")
    if atr_dup:
        nota_atr += (f"<p class=note style='margin-top:4px'>{atr_dup} tarefa(s) apareciam em <b>mais de uma conta "
                     "do mesmo cliente</b> (ex.: conta do bundle + conta ADS) e foram contadas UMA vez, na conta "
                     "principal — se o cliente tem grupos duplicados no painel, vale unificar.</p>")
    resto_resp = (f"<p class=note style='margin-top:8px'>+ {len(resp_ord) - 15} responsável(is) com menos atrasos "
                  "fora do top 15.</p>" if len(resp_ord) > 15 else "")
    atrasos_html = (
        "<section><h2>Atividades em atraso</h2>"
        "<p class=secsub>tarefas ABERTAS com vencimento estourado no ClickUp (as mesmas da coluna 'Atrasos' da aba Contas), "
        "agregadas por squad e por responsável — 'atrasos/pessoa' ao lado de 'contas/pessoa' responde se o atraso vem de "
        "sobrecarga (capacidade) ou de ritmo/processo · clientes pausados por inadimplência/concluídos ficam fora · "
        "<b>clique num squad ou responsável</b> para abrir a lista das "
        "tarefas, cada uma com link direto no ClickUp</p>"
        "<script>function atrTgl(id){var e=document.getElementById(id);"
        "e.style.display=(e.style.display==='none')?'':'none';}</script>"
        f"<div class=card><div class=sug-item>→ {escape(leitura_atr)}</div></div>"
        f"<div class=central style='padding:6px 14px 12px;overflow-x:auto'><table style='width:100%;border-collapse:collapse'>"
        f"<tr>{ths_atr}</tr>{linhas_atr}</table></div>{nota_atr}"
        "<div class=asslbl style='margin:14px 0 6px'>por responsável (assignee das tarefas vencidas no ClickUp)</div>"
        f"<div class=central style='padding:6px 14px 12px;overflow-x:auto'><table style='width:100%;border-collapse:collapse'>"
        f"<tr>{ths_resp}</tr>{linhas_resp}</table></div>{resto_resp}</section>")
    # análise/ranking por squad (antes na aba Relatórios — unificação 15/07:
    # 'Análise dos Squads' = ranking + insights + carga + capacidade num lugar só)
    _squad_an, _sem_squad = _squad_analysis(scores)
    squads_html = _squads_html(_squad_an, _sem_squad)
    return (
        "<div class=page-head><h1>Análise dos Squads</h1>"
        "<span class=role-chip>ranking, carga e capacidade por time</span></div>"
        "<p class=sub>tudo do TIME num lugar só: score composto e plano de ação, carga de risco e capacidade de atendimento — "
        "os pontos fortes/fracos de cada squad consideram todas essas dimensões</p>"
        "<section><h2>Ranking e análise</h2>"
        "<p class=secsub>score composto (50% relacionamento · 25% execução · 25% risco), "
        "dores dominantes e plano de ação por equipe — fortes/fracos incluem carga e concentração de risco</p>"
        + squads_html + "</section>"
        "<section><h2>Carga de risco por squad</h2>"
        "<p class=secsub>onde há carga desproporcional de contas críticas e MRR em risco — decidir realocação/reforço "
        "ANTES de a sobrecarga virar churn · chip = concentração (≥3 críticos ou ≥30% do MRR em risco)</p>"
        + tabela(por_squad, "Squad") + "</section>"
        "<section><h2>Capacidade de atendimento</h2>"
        "<p class=secsub>carteira E carga de trabalho ÷ tamanho do time — contas/pessoa mede a carteira; "
        "<b>tarefas abertas/pessoa</b> mede o trabalho REAL no ClickUp (tarefas recorrentes fazem os dois divergirem) · "
        "chip sobrecarga/folga = contas/pessoa vs média · tarefas/pessoa em vermelho/verde = bem acima/abaixo da média</p>"
        f"<div class=card><div class=sug-item>→ {escape(leitura_cap)}</div>"
        "<style>.sug-item{padding:7px 0 12px;font-size:var(--fs-sm);line-height:1.6;color:var(--text-2)}</style></div>"
        f"<div class=central style='padding:6px 14px 12px;overflow-x:auto'><table style='width:100%;border-collapse:collapse'>"
        f"<tr>{ths_cap}</tr>{linhas_cap}</table></div></section>"
        + atrasos_html)


def _render(role: str, scores: list[dict], alerts: list[dict],
            practices: dict | None = None, view: str = "contas",
            interventions: list | None = None, cancel: list | None = None,
            usermail: str = "", request: Request | None = None,
            base_bundle: dict | None = None, modelo: dict | None = None,
            evolucao: str = "") -> str:
    evaluable = [s for s in scores if s["evaluable"]]
    non_eval = [s for s in scores if not s["evaluable"]]
    evaluable.sort(key=lambda s: (float(s["score"]), -_mrr_val(s)))
    non_eval.sort(key=lambda s: -_mrr_val(s))
    ordered = evaluable + non_eval  # tabela única; não-avaliáveis ao fim
    # mapa do espelho (cacheado/prewarm) p/ resolver squad de nomes sem Bx-Sy
    try:
        from .sources.clickup_activities import _mirror_clientes
        _mirror = _mirror_clientes()
    except Exception:  # noqa: BLE001 — sem espelho, resolve só pelo nome
        _mirror = None
    try:
        from .sources.clickup_activities import card_url as _cu_card_url
    except Exception:  # noqa: BLE001
        _cu_card_url = None
    # contas com TAREFA ATRASADA de verdade (vencimento estourado) — filtro
    # próprio, separado da faixa 'crítica' da nota (Otávio 15/07)
    try:
        from .sources.clickup_activities import _overdue_from_clickup
        _agora_atr = dt.datetime.now(dt.timezone.utc)

        def _n_atrasadas(nm: str) -> int:
            try:
                return len(_overdue_from_clickup(nm, _agora_atr) or [])
            except Exception:  # noqa: BLE001
                return 0
    except Exception:  # noqa: BLE001
        def _n_atrasadas(nm: str) -> int:
            return 0
    # cliente pausado por inadimplência/concluído: chip próprio no lugar de
    # 'X atrasada(s)' — vencidas de serviço suspenso não são atraso do squad
    try:
        from .sources.clickup_activities import client_inactive_status as _inat_chip
    except Exception:  # noqa: BLE001
        def _inat_chip(nm: str):  # type: ignore[misc]
            return None
    squads = sorted({_squad_label(s["name"], _mirror) for s in ordered})

    def reason_txt(s):
        rs = s.get("reasons", [])[:3]
        return escape(" · ".join(r["text"] for r in rs)) if rs else ""

    def row(s):
        ev = bool(s["evaluable"])
        stage_key = s["stage"] if ev else "nao_avaliavel"
        band = s["risk_band"]
        sev = s.get("alert_sev") or "sem"
        sq = _squad_label(s["name"], _mirror)
        mrr = _mrr_val(s)
        xs = s.get("exec_score")
        exec_key = ("sem" if xs is None else
                    "em_dia" if xs >= 70 else "atencao" if xs >= 40 else "critica")
        # selo de execução clicável -> card do cliente no ClickUp (conferência
        # rápida das entregas; pedido Otávio 15/07)
        exec_cell = _exec_badge(s)
        cu_url = _cu_card_url(s["name"]) if _cu_card_url else None
        if cu_url and exec_cell != _DASH:
            exec_cell = (f"<a href='{cu_url}' target=_blank rel=noopener "
                         f"style='text-decoration:none' title='abrir o card no ClickUp'>{exec_cell}</a>")
        inat = _inat_chip(s["name"])
        n_atr = 0 if inat else _n_atrasadas(s["name"])
        if exec_cell == _DASH:
            atr_cell = _DASH
        elif inat:
            rot_inat = "pausado" if "pausada" in inat else "concluído"
            atr_cell = (f"<span class='chip' style='--c:var(--status-semdados)' "
                        f"title='cliente {escape(inat)} no ClickUp — serviço suspenso: tarefas vencidas "
                        f"não contam como atraso do squad; voltam a contar se reativar'>{rot_inat}</span>")
        elif n_atr:
            atr_cell = (f"<span class='chip' style='--c:var(--status-critico)' "
                        f"title='entregas abertas com vencimento estourado — nomes e responsáveis no relatório'>"
                        f"{n_atr} atrasada(s)</span>")
        else:
            atr_cell = (f"<span class='chip' style='--c:var(--status-baixo)' "
                        f"title='nenhuma entrega aberta vencida no ClickUp'>em dia</span>")
        # coluna Atrasos também clicável -> card no ClickUp (Otávio 16/07:
        # 'faria sentido ver QUAIS são as tarefas em atraso ao clicar ali')
        if cu_url and atr_cell != _DASH:
            atr_cell = (f"<a href='{cu_url}' target=_blank rel=noopener "
                        f"style='text-decoration:none' title='abrir o card no ClickUp para ver as tarefas'>{atr_cell}</a>")
        atr = "1" if n_atr else "0"
        score_cell = (f"<span class='score'>{float(s['score']):.1f}</span>" if ev
                      else "<span style='color:var(--text-faint)'>s/ dados</span>")
        mot = reason_txt(s)
        mot_line = f"<div class='mot'>{mot}</div>" if mot else ""
        stage_dot = (f"<span class='sdot' style='--c:var({_SEV_VAR.get(sev,'--status-semdados')})'></span>"
                     if sev != "sem" else "")
        return (
            f"<div class='row acct' data-name=\"{escape(s['name'].lower())}\" data-band=\"{band}\" "
            f"data-alert=\"{sev}\" data-stage=\"{stage_key}\" data-squad=\"{sq}\" data-mrr=\"{mrr:.0f}\" "
            f"data-exec=\"{exec_key}\" data-atr=\"{atr}\" data-aid=\"{s['account_id']}\">"
            f"<div class='c-name'><div class='nm'>{escape(s['name'][:60])}</div>{mot_line}"
            f"<div class='acts'>"
            f"<a class='repbtn' href='/growth/report?account_id={s['account_id']}' "
            f"title='Relatório mensal de assessoria (mês anterior; gerado na hora)'>📄 Relatório</a>"
            f"<select class='outsel' onchange=\"outc('{s['account_id']}',this)\" "
            f"title='registrar o DESFECHO real da conta — alimenta a medição de precisão do modelo (aba Alertas)'>"
            f"<option value=''>desfecho…</option><option value='retida'>retida</option>"
            f"<option value='cancelada'>cancelada</option><option value='em_negociacao'>em negociação</option></select></div></div>"
            f"<div class='c-score'>{score_cell}</div>"
            f"<div>{_chip(band, _BAND_VAR.get(band, '--status-semdados'))}</div>"
            f"<div class='c-stage'>{stage_dot}{escape(_STAGE_LABEL.get(stage_key, stage_key))}</div>"
            f"<div class='c-squad' title=\"{escape(_tag(s['name']))}\">{escape(sq)}</div>"
            f"<div class='c-mrr'>{_mrr_txt(s)}</div>"
            f"<div>{exec_cell}</div>"
            f"<div>{atr_cell}</div>"
            f"<div class='guide c-full'>{escape(_guide(s, practices))}</div>"
            f"</div>"
        )

    rows = "".join(row(s) for s in ordered)
    def _alert_row(a: dict) -> str:
        # linha de contexto: última atualização do caso (linha do tempo — inclui
        # os eventos automáticos do agente) > nota do próprio alerta
        nota = ""
        if a.get("case_note"):
            quando = _fmt_date_br(a.get("case_note_at"))
            quem = escape(str(a.get("case_note_by") or "—"))
            nota = f"<div class='mot'>{quando} · {escape(str(a['case_note'])[:150])} · {quem}</div>"
        elif a.get("notes"):
            ultima = str(a["notes"]).strip().splitlines()[-1]
            nota = f"<div class='mot'>{escape(ultima[:120])}</div>"
        aid = a.get("id")
        # nome clicável -> abre a conta na aba Contas (filtro pré-aplicado);
        # validação do gestor sem trocar de aba na mão (pedido Otávio 15/07)
        from urllib.parse import quote_plus
        conta_url = f"/growth?view=contas&conta={quote_plus(a['name'])}"
        return (
            f"<div class='row arow'><div class='c-name'><div class='nm'>"
            f"<a class='alnk' href='{conta_url}' title='abrir a conta na aba Contas'>{escape(a['name'][:60])}</a>"
            f"</div>{nota}</div>"
            f"<div>{_chip(a['severity'], _SEV_VAR.get(a['severity'], '--status-semdados'), dot=True)}</div>"
            f"<div class='c-stage'>{escape(_STAGE_LABEL.get(a['stage'], a['stage']))}</div>"
            f"<div class='c-status'>{escape(str(a['status']))}</div>"
            f"<div class='c-acts'>"
            f"<button class=abtn onclick=\"alertAct('{aid}','reconhecido')\" title='marca que o gestor viu e está tratando'>reconhecer</button>"
            f"<button class=abtn onclick=\"alertAct('{aid}','resolvido')\" title='fecha o alerta (pede nota do desfecho)'>resolver</button>"
            f"<button class=abtn onclick=\"alertAct('{aid}',null)\" title='só adicionar nota, sem mudar status'>nota</button>"
            f"</div></div>"
        )

    alert_rows = "".join(_alert_row(a) for a in alerts) or "<div class='row empty'>sem alertas abertos</div>"
    squad_opts = "".join(f"<option value='{escape(q)}'>{escape(q)}</option>" for q in squads)

    head = """<!doctype html><html lang=pt-br><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Integracomm IA · Growth — Saúde de clientes</title>
<link rel=preconnect href="https://fonts.googleapis.com"><link rel=preconnect href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Poppins:wght@500;600;700&display=swap" rel=stylesheet>
<style>
__TOKENS__
*{box-sizing:border-box}
body{margin:0;background:var(--bg-app);color:var(--text);font-family:var(--font-body);font-size:var(--fs-base);-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}
.app{display:flex;min-height:100vh}
/* --- sidebar --- */
.rail{width:var(--rail-width);flex-shrink:0;background:var(--bg-rail);border-right:1px solid var(--border);position:sticky;top:0;height:100vh;display:flex;flex-direction:column}
.brand{display:flex;align-items:center;gap:10px;padding:18px 16px 14px}
.brand .logo{width:22px;height:22px;border-radius:50%;background:var(--brand);position:relative;flex-shrink:0}
.brand .logo::after{content:"";position:absolute;width:9px;height:9px;border-radius:50%;background:var(--bg-rail);top:6.5px;left:9px}
.brand .bt{font-family:var(--font-display);font-weight:700;font-size:13.5px;line-height:1.15}
.brand .bs{font-size:10.5px;color:var(--text-muted);letter-spacing:.02em}
nav{padding:10px 12px;display:flex;flex-direction:column;gap:2px;flex:1}
.nav-item{display:flex;align-items:center;justify-content:space-between;padding:9px 12px;border-radius:var(--radius-sm);color:var(--text-muted);font-size:var(--fs-base);font-weight:var(--fw-medium)}
.nav-item:hover{background:var(--surface-2);color:var(--text-2)}
.nav-item.active{background:var(--surface-2);color:var(--text);box-shadow:inset 2px 0 0 var(--brand)}
.nav-item.soon{opacity:.55} .nav-item .tag{font-size:9px;text-transform:uppercase;letter-spacing:.08em;color:var(--text-faint)}
.rail-foot{padding:12px 16px;border-top:1px solid var(--border);font-size:var(--fs-2xs);color:var(--text-muted);line-height:1.5}
/* --- main --- */
main{flex:1;min-width:0;padding:26px 32px 48px;max-width:var(--content-max)}
.page-head{display:flex;align-items:baseline;gap:14px}
h1{font-family:var(--font-display);font-weight:700;font-size:var(--fs-h1);letter-spacing:var(--tracking-tight);margin:0}
.role-chip{font-size:var(--fs-xs);color:var(--text-muted)}
.role-chip b{color:var(--text-2)}
.kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:20px}
.kpi{background:var(--surface-1);border:1px solid var(--border-mid);border-radius:var(--radius-md);padding:16px 18px}
.kpi .n{font-family:var(--font-display);font-weight:700;font-size:var(--fs-kpi);line-height:1}
.kpi .l{font-size:var(--fs-2xs);color:var(--text-muted);text-transform:uppercase;letter-spacing:var(--tracking-label);margin-top:8px}
.kpi .s{font-size:var(--fs-xs);color:var(--text-faint);margin-top:3px}
/* seções com SEPARAÇÃO clara + acento no título (redesenho 20/07: cabeçalho
   em BLOCO — título em cima, descrição embaixo; nada espremido numa linha) */
section{margin-top:32px;padding-top:22px;border-top:1px solid var(--border)}
section:first-of-type{border-top:none;padding-top:0}
.sec-head{display:flex;flex-direction:column;gap:4px;margin-bottom:12px}
.sec-head h2{font-family:var(--font-display);font-weight:600;font-size:var(--fs-lg);margin:0;position:relative;padding-left:12px}
.sec-head h2::before,section>h2::before{content:"";position:absolute;left:0;top:4px;bottom:4px;width:3px;border-radius:2px;background:var(--brand)}
section>h2{position:relative;padding-left:12px}
.sec-head .sub{font-size:var(--fs-sm);color:var(--text-muted);line-height:1.55;max-width:980px}
.note{font-size:var(--fs-sm);color:var(--text-muted);margin:0 0 10px}
.note b{color:var(--text-2)}
/* --- tabelas em grid --- */
.tbl{background:var(--surface-1);border:1px solid var(--border-mid);border-radius:var(--radius-md);overflow-x:auto}
.row{display:grid;align-items:center;gap:12px;padding:10px 16px}
.thead{background:var(--surface-2);color:var(--text-muted);font-size:var(--fs-2xs);text-transform:uppercase;letter-spacing:var(--tracking-label);font-weight:var(--fw-semibold)}
.arow{border-top:1px solid var(--border);align-items:start}
/* cada CLIENTE é um CARTÃO próprio (redesign Otávio 16/07: 'muito carregado,
   informações muito juntas') — respiro entre cartões e borda esquerda na cor
   da faixa de risco p/ escanear a lista sem ler os chips */
.acct{align-items:start;padding:16px 16px 14px;background:var(--surface-1);
  border:1px solid var(--border-mid);border-left:3px solid var(--border-strong);
  border-radius:var(--radius-md);margin-top:12px}
.acct[data-band=critico]{border-left-color:var(--status-critico)}
.acct[data-band=alto]{border-left-color:var(--status-alto)}
.acct[data-band=medio]{border-left-color:var(--status-medio)}
.acct[data-band=baixo]{border-left-color:var(--status-baixo)}
.acct:hover,.arow:hover{background:var(--surface-2)}
.tbl-alerts .row{grid-template-columns:minmax(260px,1fr) 120px 170px 90px 230px}
.c-acts{display:flex;gap:6px;flex-wrap:wrap}
.abtn{cursor:pointer;background:var(--surface-3);border:1px solid var(--border-strong);border-radius:var(--radius-sm);color:var(--text-2);font-family:var(--font-body);font-size:var(--fs-2xs);padding:4px 9px}
.abtn:hover{border-color:var(--brand);color:var(--brand)}
/* contas: 7 colunas que CABEM na página (sem scroll lateral); a diretriz ocupa
   a largura inteira numa 2ª linha da mesma conta */
.tbl-acct{background:transparent;border:none}
.tbl-acct .thead{background:var(--surface-2);border:1px solid var(--border-mid);
  border-left-width:3px;border-radius:var(--radius-md)}
.tbl-acct .row{grid-template-columns:minmax(200px,1fr) 66px 96px 150px 78px 96px 96px 92px;row-gap:10px}
/* colunas 2–7 (Score..Execução) centralizadas — cabeçalho e linhas */
.tbl-acct .row>div:nth-child(n+2):nth-child(-n+8){text-align:center}
.c-full{grid-column:1/-1}
.pager{display:flex;align-items:center;gap:10px;justify-content:flex-end;margin-top:10px}
.pager button{cursor:pointer;background:var(--surface-3);border:1px solid var(--border-strong);border-radius:var(--radius-sm);color:var(--text-2);padding:6px 12px;font-size:var(--fs-sm)}
.pager button:disabled{opacity:.4;cursor:default}
.pager .pginfo{font-size:var(--fs-sm);color:var(--text-muted)}
.nm{font-weight:var(--fw-semibold);font-size:var(--fs-md);line-height:1.3}
.nm .alnk{color:inherit;text-decoration:none;border-bottom:1px dashed var(--border-strong)}
.nm .alnk:hover{color:var(--brand);border-bottom-color:var(--brand)}
.mot{font-size:var(--fs-2xs);color:var(--text-muted);margin-top:3px;line-height:1.4}
.score{font-family:var(--font-display);font-weight:700;font-size:15px}
.c-mrr{color:var(--text-2);font-variant-numeric:tabular-nums}
.c-squad{color:var(--text-muted);font-size:var(--fs-sm)}
.c-stage{color:var(--text-2);font-size:var(--fs-sm)} .c-status{color:var(--text-muted);font-size:var(--fs-sm)}
.sdot{display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--c);margin-right:6px;vertical-align:middle}
.guide{font-size:var(--fs-sm);color:var(--text-2);line-height:1.5;background:color-mix(in srgb,var(--brand) 5%,transparent);border-left:2px solid color-mix(in srgb,var(--brand) 35%,transparent);border-radius:var(--radius-xs);padding:7px 10px}
/* ações da conta (Relatório + desfecho): mesma altura, mesmo estilo */
.acts{display:flex;gap:8px;align-items:stretch;margin-top:10px}
.repbtn{display:inline-flex;align-items:center;gap:5px;font-size:var(--fs-2xs);font-weight:var(--fw-semibold);color:var(--text-2);background:var(--surface-3);border:1px solid var(--border-strong);border-radius:var(--radius-sm);padding:5px 11px;text-decoration:none;line-height:1.2}
.repbtn:hover{border-color:var(--brand);color:var(--brand)}
.outsel{cursor:pointer;background:var(--surface-3);border:1px solid var(--border-strong);border-radius:var(--radius-sm);color:var(--text-muted);font-family:var(--font-body);font-size:var(--fs-2xs);padding:4px 7px;line-height:1.2}
.outsel:hover,.outsel:focus{border-color:var(--brand);color:var(--text-2);outline:none}
.empty{color:var(--text-muted);padding:14px 16px}
/* --- filtros --- */
.filters{display:flex;flex-wrap:wrap;gap:10px;align-items:end;background:var(--surface-1);border:1px solid var(--border-mid);border-radius:var(--radius-md);padding:12px 14px;margin-bottom:10px}
.filters .grp{display:flex;flex-direction:column;gap:3px}
.filters label{font-size:var(--fs-2xs);color:var(--text-muted);text-transform:uppercase;letter-spacing:.06em}
.filters input,.filters select{background:var(--bg-panel);border:1px solid var(--border-strong);border-radius:var(--radius-sm);color:var(--text);font-family:var(--font-body);font-size:var(--fs-sm);padding:7px 9px;min-height:32px}
.filters input:focus,.filters select:focus{outline:none;border-color:var(--brand)}
#clearf{cursor:pointer;background:var(--surface-3);border:1px solid var(--border-strong);border-radius:var(--radius-sm);color:var(--text-2);padding:7px 12px;font-size:var(--fs-sm);min-height:32px}
.count{font-size:var(--fs-sm);color:var(--text-muted);margin-left:auto}.count b{color:var(--text)}
.foot{font-size:var(--fs-xs);color:var(--text-faint);margin-top:18px}
</style></head><body>
<div class=app>
 <aside class=rail>
   <div class=brand><div class=logo></div><div><div class=bt>Integracomm IA</div><div class=bs>Growth · Saúde de clientes</div></div></div>
   <nav>__NAV__</nav>
   <div class=rail-foot><b>__USERMAIL__</b> · <a href="/logout" style="color:var(--text-muted);text-decoration:underline">sair</a><br>humano no loop — o agente só sinaliza</div>
 </aside>
 <main>__CONTENT__</main>
</div>
__SCRIPT__
</body></html>"""

    # ---- navegação (view ativa; sessão define o papel — sem role na URL) ----
    nav = "<a class='nav-item' href='/'>← Início (central)</a>"
    for v, label in (("contas", "Contas"), ("alertas", "Alertas"),
                     ("carga", "Análise dos Squads"), ("cancelamentos", "Cancelamentos"),
                     ("playbooks", "Playbooks"), ("relatorios", "Relatórios")):
        cls = "nav-item active" if v == view else "nav-item"
        nav += f"<a class='{cls}' href='/growth?view={v}'>{label}</a>"
    # 'Configurações (em breve)' removido (Otávio 16/07): tudo que seria config
    # do Growth ou é calibração do modelo (decisão de gestão, não de tela), ou
    # já vive no Painel Administrativo (times, integrações) — placeholder morto

    foot = ("<p class=foot>Derivados do Postgres próprio (LGPD: sem conteúdo bruto). "
            "O agente calcula, exibe e sinaliza — nunca age.</p>")
    sev_counts: dict[str, int] = {}
    for a in alerts:
        sev_counts[a["severity"]] = sev_counts.get(a["severity"], 0) + 1

    alerts_tbl = (
        "<div class='tbl tbl-alerts'>"
        "<div class='row thead'><div>Conta / última nota</div><div>Severidade</div><div>Estágio</div><div>Status</div><div>Ações</div></div>"
        + alert_rows + "</div>")

    script = ""
    if view == "alertas":
        content = (
            f"<div class=page-head><h1>Alertas</h1><span class=role-chip>fila de ação — crítico → alto → atenção</span></div>"
            f"<div class=kpis>"
            f"<div class=kpi><div class=n style='color:var(--status-critico)'>{sev_counts.get('critico', 0)}</div><div class=l>Crítico</div><div class=s>sinal explícito de saída / faixa crítica</div></div>"
            f"<div class=kpi><div class=n style='color:var(--status-alto)'>{sev_counts.get('alto', 0)}</div><div class=l>Alto</div><div class=s>insatisfação ativa / risco alto</div></div>"
            f"<div class=kpi><div class=n style='color:var(--status-medio)'>{sev_counts.get('atencao', 0)}</div><div class=l>Atenção</div><div class=s>churner quieto — começando a cair</div></div>"
            f"</div>" + _modelo_html(modelo) + evolucao + f"<section>{alerts_tbl}"
            "<div class=pager><button id=pa-prev onclick='paGo(-1)'>‹ anterior</button>"
            f"<span class=pginfo id=painfo></span><span class=count>total: <b>{len(alerts)}</b></span>"
            "<button id=pa-next onclick='paGo(1)'>próxima ›</button></div>"
            "</section>" + foot)
        script = _ALERTS_JS
    elif view == "carga":
        content = _carga_content(ordered, _mirror) + foot
    elif view == "playbooks":
        content = _playbooks_content(practices or {}, interventions or []) + foot
    elif view == "cancelamentos":
        content = _cancel_content(cancel or [], request, base_bundle or {},
                                  _mrr_por_bundle(scores)) + foot
    elif view == "relatorios":
        rep = _report_from(scores, alerts)
        content = _relatorios_content(rep, scores) + foot
    else:  # contas
        content = (
            f"<div class=page-head><h1>Saúde de clientes</h1><span class=role-chip>papel: <b>{escape(role)}</b></span></div>"
            f"<div class=kpis>"
            f"<div class=kpi><div class=n>{len(evaluable)}</div><div class=l>Contas avaliáveis</div><div class=s>de {len(ordered)} contas monitoradas</div></div>"
            f"<div class=kpi><div class=n style='color:var(--status-critico)'>{len(alerts)}</div><div class=l>Alertas abertos</div><div class=s>ver aba Alertas</div></div>"
            f"<div class=kpi><div class=n>{len(non_eval)}</div><div class=l>Não avaliáveis</div><div class=s>sem dados suficientes de conversa</div></div>"
            f"</div>"
            "<section><div class=sec-head><h2>Contas por risco</h2><span class=sub>menor score = pior</span></div>"
            "<p class=note>Score e alertas vêm do WhatsApp; <b>MRR</b> desempata a prioridade. "
            "<b>Serviço-Squad</b> = tipo de serviço + time responsável (ex.: ADS-B3-S2); o squad é "
            "o real da planilha de composição, resolvido pelo nome ou pelo espelho da Operação "
            "(tag completa no hover). "
            "<b>Execução</b> = saúde das entregas no ClickUp (saudável / atenção / crítica); <b>Atrasos</b> = entregas abertas com vencimento estourado — em dia = nenhuma "
            "(nota e motivo no hover; clicar nos selos abre o card do cliente no ClickUp). "
            "A <b>diretriz de ação</b> aparece destacada sob cada conta; a borda esquerda do cartão segue a cor da faixa de risco.</p>"
            "<div class=filters>"
            "<div class=grp><label>buscar nome</label><input id=f-name placeholder='cliente…' oninput='applyF()'></div>"
            "<div class=grp><label>faixa</label><select id=f-band onchange='applyF()'><option value=''>todas</option><option value='baixo'>verde (baixo)</option><option value='medio'>amarelo (médio)</option><option value='alto'>laranja (alto)</option><option value='critico'>vermelho (crítico)</option><option value='sem_dados'>sem dados</option></select></div>"
            "<div class=grp><label>alerta</label><select id=f-alert onchange='applyF()'><option value=''>todos</option><option value='critico'>crítico</option><option value='alto'>alto</option><option value='atencao'>atenção</option><option value='sem'>sem alerta</option></select></div>"
            "<div class=grp><label>estágio</label><select id=f-stage onchange='applyF()'><option value=''>todos</option><option value='saudavel'>saudável</option><option value='desengajamento_inicial'>desengajamento</option><option value='insatisfacao_latente'>insatisfação latente</option><option value='insatisfacao_ativa'>insatisfação ativa</option><option value='intencao_de_saida'>intenção de saída</option><option value='nao_avaliavel'>não avaliável</option></select></div>"
            f"<div class=grp><label>squad</label><select id=f-squad onchange='applyF()'><option value=''>todos</option>{squad_opts}</select></div>"
            "<div class=grp><label>execução</label><select id=f-exec onchange='applyF()'><option value=''>todas</option><option value='em_dia'>saudável</option><option value='atencao'>atenção</option><option value='critica'>crítica</option><option value='sem'>sem dado</option></select></div><div class=grp><label>atrasos</label><select id=f-atr onchange='applyF()'><option value=''>todos</option><option value='1'>com atraso</option><option value='0'>em dia</option></select></div>"
            "<div class=grp><label>MRR mínimo (R$)</label><input id=f-mrr type=number min=0 step=100 placeholder='ex.: 3000' oninput='applyF()'></div>"
            "<button id=clearf onclick='clearF()'>limpar</button>"
            f"<span class=count>mostrando <b id=vis>0</b> de {len(ordered)}</span>"
            "</div>"
            "<div class='tbl tbl-acct'>"
            "<div class='row thead'><div>Conta / motivos</div><div class=c-score>Score</div><div>Faixa</div><div>Estágio</div><div>Serviço-Squad</div><div class=c-mrr>MRR</div><div>Execução</div><div>Atrasos</div></div>"
            + rows + "</div>"
            "<div class=pager><button id=pg-prev onclick='pgGo(-1)'>‹ anterior</button>"
            "<span class=pginfo id=pginfo></span>"
            "<button id=pg-next onclick='pgGo(1)'>próxima ›</button></div>"
            + foot + "</section>")
        script = _CONTAS_JS

    return (head.replace("__TOKENS__", _tokens_css())
            .replace("__NAV__", nav).replace("__USERMAIL__", escape(usermail or role))
            .replace("__CONTENT__", _growth_help(view, content))
            .replace("__SCRIPT__", script))


_CONTAS_JS = """<script>
function outc(id, sel){
  if(!sel.value) return;
  var lbl = sel.options[sel.selectedIndex].text;
  var nota = window.prompt('Registrar desfecho "'+lbl+'" para esta conta.\\nObservação (opcional):');
  if(nota===null){sel.value='';return;}
  fetch('/api/accounts/'+id+'/outcome',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({outcome:sel.value,notes:nota||null})})
  .then(function(r){return r.json();})
  .then(function(j){if(j.error){alert(j.error);sel.value='';}else{sel.style.borderColor='var(--status-baixo)';}})
  .catch(function(){alert('falha de rede');sel.value='';});
}
var PAGE=10, page=1, IDS=null; /* ?ids= = conjunto exato de contas (links do hub) */
function _match(d,f){
  return (!IDS||IDS.has(d.aid))&&(!f.n||d.name.indexOf(f.n)>=0)&&(!f.b||d.band===f.b)&&(!f.a||d.alert===f.a)
    &&(!f.st||d.stage===f.st)&&(!f.sq||d.squad===f.sq)&&(!f.x||d.exec===f.x)
    &&(!f.at||d.atr===f.at)&&(parseFloat(d.mrr)>=f.mrr);
}
function renderRows(){
  var f={n:document.getElementById('f-name').value.toLowerCase().trim(),
    b:document.getElementById('f-band').value, a:document.getElementById('f-alert').value,
    st:document.getElementById('f-stage').value, sq:document.getElementById('f-squad').value,
    x:document.getElementById('f-exec').value, at:document.getElementById('f-atr').value,
    mrr:parseFloat(document.getElementById('f-mrr').value)};
  if(isNaN(f.mrr)) f.mrr=-Infinity;
  var rows=[].slice.call(document.querySelectorAll('.acct'));
  var hit=rows.filter(function(r){return _match(r.dataset,f);});
  rows.forEach(function(r){r.style.display='none';});
  var pages=Math.max(1,Math.ceil(hit.length/PAGE));
  if(page>pages)page=pages; if(page<1)page=1;
  hit.slice((page-1)*PAGE,page*PAGE).forEach(function(r){r.style.display='';});
  document.getElementById('vis').textContent=hit.length;
  document.getElementById('pginfo').textContent='página '+page+' de '+pages;
  document.getElementById('pg-prev').disabled=(page<=1);
  document.getElementById('pg-next').disabled=(page>=pages);
}
function applyF(){page=1;renderRows();}
function pgGo(d){page+=d;renderRows();window.scrollTo({top:document.querySelector('.tbl-acct').offsetTop-80,behavior:'smooth'});}
function clearF(){IDS=null;['f-name','f-band','f-alert','f-stage','f-squad','f-exec','f-atr','f-mrr'].forEach(function(i){document.getElementById(i).value='';});applyF();}
if(document.getElementById('f-name')){
  // pré-filtros via URL: ?conta= (aba Alertas) · ?exec= / ?faixa= (iniciativas da central)
  // · ?ids= (itens de 'O que mudou desde ontem' — conjunto exato de contas)
  var _p=new URLSearchParams(location.search);
  if(_p.get('ids'))IDS=new Set(_p.get('ids').split(','));
  if(_p.get('conta'))document.getElementById('f-name').value=_p.get('conta');
  if(_p.get('exec')==='atrasadas'){document.getElementById('f-atr').value='1';}
  else if(_p.get('exec'))document.getElementById('f-exec').value=_p.get('exec');
  if(_p.get('atraso'))document.getElementById('f-atr').value=_p.get('atraso');
  if(_p.get('faixa'))document.getElementById('f-band').value=_p.get('faixa');
  applyF();
}
</script>"""

_ALERTS_JS = """<script>
function alertAct(id, status){
  var note=window.prompt(status==='resolvido'
    ? 'Nota do desfecho (obrigatória p/ resolver — ex.: reunião feita, cliente retido com plano X):'
    : 'Nota (opcional'+(status?'':' — obrigatória p/ registrar')+'):');
  if(note===null) return;                       // cancelou
  note=note.trim();
  if(status==='resolvido' && !note){alert('informe a nota do desfecho.');return;}
  if(!status && !note){alert('escreva a nota.');return;}
  var body={}; if(status)body.status=status; if(note)body.note=note;
  fetch('/api/alerts/'+id+'/update',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
  .then(function(r){return r.json().then(function(j){return [r.ok,j];});})
  .then(function(x){ if(!x[0]){alert(x[1].error||'falha');return;} location.reload(); })
  .catch(function(){alert('falha de rede');});
}
var PAGE=25, page=1;
function renderA(){
  var rows=[].slice.call(document.querySelectorAll('.arow'));
  var pages=Math.max(1,Math.ceil(rows.length/PAGE));
  if(page>pages)page=pages; if(page<1)page=1;
  rows.forEach(function(r){r.style.display='none';});
  rows.slice((page-1)*PAGE,page*PAGE).forEach(function(r){r.style.display='';});
  document.getElementById('painfo').textContent='página '+page+' de '+pages;
  document.getElementById('pa-prev').disabled=(page<=1);
  document.getElementById('pa-next').disabled=(page>=pages);
}
function paGo(d){page+=d;renderA();window.scrollTo({top:0,behavior:'smooth'});}
if(document.getElementById('painfo'))renderA();
</script>"""

_DRIVER_LABEL = {"silencio": "Silêncio (cliente sumindo)", "tom_negativo": "Tom negativo recorrente",
                 "iniciativa_cliente": "Queda de iniciativa", "comprimento_msg": "Mensagens encurtando",
                 "fala_em_cancelar": "Falou em cancelar", "critico_recente": "Evento crítico recente",
                 "tom_claude": "Tom da conversa esfriando (análise Claude)"}

_CARD = ("background:var(--surface-1);border:1px solid var(--border-mid);"
         "border-radius:var(--radius-md);padding:16px 18px")


def _playbooks_content(practices: dict, interventions: list) -> str:
    h = ("<div class=page-head><h1>Playbooks</h1>"
         "<span class=role-chip>boas práticas aprendidas com clientes reais</span></div>"
         "<p class=note style='margin-top:14px'>Toda ação registrada com um cliente vira aprendizado: quando o "
         "desfecho é <b>retido</b>, a prática entra aqui e passa a ser citada na diretriz de casos "
         "futuros com a mesma dor. Registro via <b>POST /api/interventions</b> (UI de registro entra "
         "com o login).</p>")
    if practices:
        cards = "".join(
            f"<div style='{_CARD}'><div style='font-size:var(--fs-2xs);color:var(--text-muted);"
            f"text-transform:uppercase;letter-spacing:var(--tracking-label)'>{escape(_DRIVER_LABEL.get(d, d))}</div>"
            f"<div style='font-family:var(--font-display);font-weight:600;font-size:15px;margin-top:8px'>“{escape(a)}”</div>"
            f"<div style='margin-top:8px'>{_chip(f'reteve {n}×', '--status-baixo', dot=True)}</div></div>"
            for d, (a, n) in practices.items())
        h += ("<section><div class=sec-head><h2>Práticas de referência</h2><span class=sub>a ação que mais reteve, por dor</span></div>"
              f"<div style='display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px'>{cards}</div></section>")
    else:
        h += (f"<section><div style='{_CARD};text-align:center;padding:34px'>"
              "<div style='font-size:15px;font-weight:600'>Nenhuma prática validada ainda</div>"
              "<div style='color:var(--text-muted);font-size:var(--fs-sm);margin-top:6px;line-height:1.6'>"
              "Registre as ações tomadas com cada cliente e feche o desfecho (retido / cancelou / sem efeito).<br>"
              "As que retiveram aparecem aqui e passam a orientar os próximos casos parecidos.</div></div></section>")
    if interventions:
        rows_i = "".join(
            f"<div class='row arow' style='grid-template-columns:minmax(220px,1fr) minmax(240px,1.4fr) 110px 130px'>"
            f"<div class='nm' style='font-size:var(--fs-sm)'>{escape((i.get('name') or '')[:44])}</div>"
            f"<div style='font-size:var(--fs-sm);color:var(--text-2)'>{escape((i.get('action_text') or '')[:90])}</div>"
            f"<div>{_chip(i.get('result') or 'pendente', {'retido': '--status-baixo', 'cancelou': '--status-critico', 'sem_efeito': '--status-semdados'}.get(i.get('result'), '--status-medio'))}</div>"
            f"<div class=c-status>{escape(_fmt_date_br(i.get('taken_at')))}</div></div>"
            for i in interventions)
        h += ("<section><div class=sec-head><h2>Ações recentes</h2><span class=sub>últimos registros</span></div>"
              "<div class='tbl'><div class='row thead' style='grid-template-columns:minmax(220px,1fr) minmax(240px,1.4fr) 110px 130px'>"
              "<div>Conta</div><div>Ação</div><div>Desfecho</div><div>Quando</div></div>"
              + rows_i + "</div></section>")
    return h


def _report_from(scores: list[dict], alerts: list[dict]) -> dict:
    """Relatório do estado atual — mesmo dado que alimentará o envio ao Slack."""
    ev = [s for s in scores if s["evaluable"]]
    nev = [s for s in scores if not s["evaluable"]]
    sev: dict[str, int] = {}
    for a in alerts:
        sev[a["severity"]] = sev.get(a["severity"], 0) + 1
    dist = lambda key: _count_by(scores, key)  # noqa: E731
    with_alert = [s for s in scores if s.get("alert_sev")]
    crit_accts = [s for s in scores if s.get("alert_sev") == "critico"]
    top10 = sorted(ev, key=lambda s: (float(s["score"]), -_mrr_val(s)))[:10]
    try:
        from .sources.clickup_activities import _mirror_clientes
        _mirror = _mirror_clientes()
    except Exception:  # noqa: BLE001
        _mirror = None
    squad_alerts: dict[str, int] = {}
    for s in with_alert:
        sq = _resolve_squad(s["name"], _mirror) or "sem squad"  # squad real da planilha
        squad_alerts[sq] = squad_alerts.get(sq, 0) + 1
    return {
        "data": dt.date.today().isoformat(),
        "monitoradas": len(scores), "avaliaveis": len(ev), "sem_dados": len(nev),
        "alertas": sev, "alertas_total": sum(sev.values()),
        "mrr_risco": sum(_mrr_val(s) for s in with_alert if _mrr_val(s) > 0),
        "mrr_critico": sum(_mrr_val(s) for s in crit_accts if _mrr_val(s) > 0),
        "faixa": dist("risk_band"), "estagio": dist("stage"), "trajetoria": dist("trajectory"),
        "piores": [{"nome": s["name"], "score": float(s["score"]), "estagio": s["stage"],
                    "mrr": (_mrr_val(s) if _mrr_val(s) > 0 else None)} for s in top10],
        "criticos": [{"nome": s["name"], "mrr": (_mrr_val(s) if _mrr_val(s) > 0 else None)} for s in crit_accts],
        "nao_avaliaveis": [s["name"] for s in nev],
        "alertas_por_squad": dict(sorted(squad_alerts.items(), key=lambda x: -x[1])),
        "exec_atrasada": sum(1 for s in scores if (s.get("exec_score") or 100) < 40),
    }


def _count_by(scores: list[dict], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for s in scores:
        out[str(s.get(key))] = out.get(str(s.get(key)), 0) + 1
    return out


def _report_text(rep: dict) -> str:
    """Versão texto do relatório — formato pronto para postar no Slack."""
    sev = rep["alertas"]
    lines = [
        f"*Integracomm IA · Growth — resumo do estado* ({_fmt_date_br(rep['data'])})",
        f"• Contas monitoradas: {rep['monitoradas']} ({rep['avaliaveis']} avaliáveis, {rep['sem_dados']} sem dados)",
        f"• Alertas abertos: {rep['alertas_total']} — crítico {sev.get('critico', 0)} · alto {sev.get('alto', 0)} · atenção {sev.get('atencao', 0)}",
        f"• MRR em risco: {_fmt_brl(rep['mrr_risco'])} (só críticos: {_fmt_brl(rep['mrr_critico'])})",
        f"• Execução crítica (ClickUp): {rep['exec_atrasada']} contas",
        "",
        "*Piores contas (score):*",
    ]
    for i, p in enumerate(rep["piores"][:5], 1):
        mrr = f", {_fmt_brl(p['mrr'])}" if p.get("mrr") else ""
        lines.append(f"{i}. {p['nome'][:48]} — {p['score']:.1f} ({_STAGE_LABEL.get(p['estagio'], p['estagio'])}{mrr})")
    if rep["criticos"]:
        lines += ["", f"*Alertas críticos ({len(rep['criticos'])}):*"]
        for i, c in enumerate(rep["criticos"], 1):
            mrr = f" — {_fmt_brl(c['mrr'])}" if c.get("mrr") else ""
            lines.append(f"{i}. {c['nome'][:48]}{mrr}")
    if rep["nao_avaliaveis"]:
        lines += ["", f"*Sem dados (revisar manualmente):* {len(rep['nao_avaliaveis'])} contas"]
    lines += ["", "_o agente só sinaliza — a decisão é do gestor_"]
    return "\n".join(lines)


def _assessoria_block(scores: list[dict]) -> str:
    """Bloco 'Relatório de Assessoria' da aba Relatórios: seletor de clientes
    (múltiplos) + mês de referência -> gera relatórios individuais sob demanda
    (POST /api/reports/batch) e lista os gerados NA SESSÃO (ver/exportar)."""
    import datetime as _dt
    prev = (_dt.date.today().replace(day=1) - _dt.timedelta(days=1)).strftime("%Y-%m")
    opts = "".join(
        f"<label class=asschk><input type=checkbox value='{s['account_id']}' "
        f"data-name=\"{escape(s['name'].lower())}\"><span>{escape(s['name'][:70])}</span></label>"
        for s in sorted(scores, key=lambda s: s["name"].lower())
    )
    return f"""
<section>
 <div class=sec-head><h2>Relatório de Assessoria</h2>
  <span class=sub>relatório mensal individual por cliente — faturamento, atividades e saúde</span></div>
 <div style='{_CARD}'>
  <div style="display:flex;gap:16px;flex-wrap:wrap;align-items:flex-start">
   <div style="flex:1;min-width:280px">
    <label class=asslbl>clientes</label>
    <input id=ass-search placeholder="filtrar por nome…" oninput="assFilter()"
      style="width:100%;background:var(--bg-panel);border:1px solid var(--border-strong);border-radius:var(--radius-sm);color:var(--text);font-family:var(--font-body);font-size:var(--fs-sm);padding:7px 9px;margin-bottom:6px">
    <div id=ass-accts>{opts}</div>
    <div style="font-size:var(--fs-2xs);color:var(--text-faint);margin-top:4px">
      <a href="#" onclick="assAll(true);return false" style="color:var(--text-muted)">marcar visíveis</a> ·
      <a href="#" onclick="assAll(false);return false" style="color:var(--text-muted)">desmarcar todos</a> ·
      <span id=ass-count>0 selecionados</span></div>
   </div>
   <div>
    <label class=asslbl>mês de referência</label>
    <input id=ass-month type=month value="{prev}" max="{prev}"
      style="background:var(--bg-panel);border:1px solid var(--border-strong);border-radius:var(--radius-sm);color:var(--text);font-family:var(--font-body);font-size:var(--fs-sm);padding:7px 9px">
    <div style="margin-top:12px">
      <button id=ass-btn onclick="assGerar()" style="cursor:pointer;background:var(--brand);color:var(--brand-ink);border:none;border-radius:var(--radius-sm);font-family:var(--font-body);font-weight:600;font-size:var(--fs-sm);padding:9px 16px">Gerar Relatório(s)</button>
    </div>
    <div id=ass-msg style="font-size:var(--fs-sm);color:var(--text-muted);margin-top:10px;max-width:260px;line-height:1.5"></div>
   </div>
  </div>
  <div id=ass-out style="display:none;margin-top:16px">
   <div class=asslbl style="margin-bottom:6px">relatórios gerados nesta sessão</div>
   <div id=ass-list></div>
  </div>
 </div>
</section>
<style>
.asslbl{{display:block;font-size:var(--fs-2xs);color:var(--text-muted);text-transform:uppercase;letter-spacing:var(--tracking-label);margin-bottom:5px}}
#ass-accts{{max-height:230px;overflow-y:auto;background:var(--bg-panel);border:1px solid var(--border-strong);border-radius:var(--radius-sm);padding:4px 0}}
.asschk{{display:flex;gap:8px;align-items:center;padding:5px 10px;font-size:var(--fs-sm);color:var(--text-2);cursor:pointer}}
.asschk:hover{{background:var(--surface-2)}}
.asschk input{{accent-color:var(--brand)}}
.assitem{{display:flex;gap:10px;align-items:center;justify-content:space-between;padding:8px 0;border-top:1px solid var(--border);font-size:var(--fs-sm)}}
.assitem:first-child{{border-top:none}}
.assitem a{{color:var(--brand);text-decoration:none;font-weight:var(--fw-semibold)}}
.assitem .err{{color:var(--status-critico)}}
</style>
<script>
function assChecks(){{return [].slice.call(document.querySelectorAll('#ass-accts input'));}}
function assCount(){{var n=assChecks().filter(function(c){{return c.checked;}}).length;
  document.getElementById('ass-count').textContent=n+' selecionados';}}
document.getElementById('ass-accts').addEventListener('change',assCount);
function assFilter(){{var q=document.getElementById('ass-search').value.toLowerCase().trim();
  assChecks().forEach(function(c){{c.parentNode.style.display=(!q||c.dataset.name.indexOf(q)>=0)?'':'none';}});}}
function assAll(v){{assChecks().forEach(function(c){{if(c.parentNode.style.display!=='none')c.checked=v;}});assCount();}}
function assGerar(){{
  var ids=assChecks().filter(function(c){{return c.checked;}}).map(function(c){{return c.value;}});
  var month=document.getElementById('ass-month').value;
  var msg=document.getElementById('ass-msg'), btn=document.getElementById('ass-btn');
  if(!ids.length){{msg.textContent='selecione ao menos um cliente.';return;}}
  if(!month){{msg.textContent='informe o mês de referência.';return;}}
  btn.disabled=true; msg.textContent='gerando '+ids.length+' relatório(s)… (busca planilha + ClickUp + sinais; pode levar alguns segundos por cliente)';
  fetch('/api/reports/batch',{{method:'POST',headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{account_ids:ids,month:month}})}})
  .then(function(r){{return r.json().then(function(j){{return [r.ok,j];}});}})
  .then(function(x){{
    btn.disabled=false;
    if(!x[0]){{msg.textContent=x[1].error||x[1].detail||'falha na geração';return;}}
    var ok=x[1].reports.filter(function(r){{return r.status==='ok';}}).length;
    var mp=x[1].month.split('-'); var mlabel=mp[1]+'-'+mp[0];
    msg.textContent=ok+' de '+x[1].reports.length+' relatório(s) gerado(s) para '+mlabel+'.';
    var list=document.getElementById('ass-list');
    x[1].reports.forEach(function(r){{
      var d=document.createElement('div'); d.className='assitem';
      if(r.status==='ok'){{
        d.innerHTML='<span>'+r.account_name.replace(/</g,'&lt;')+' · '+mlabel+'</span>'
          +'<span><a href="/growth/report?report_id='+r.report_id+'" target=_blank>visualizar</a>'
          +' · <a href="/growth/report?report_id='+r.report_id+'" target=_blank title="abra e use Exportar/Imprimir">exportar</a></span>';
      }} else {{
        d.innerHTML='<span>'+r.account_id+'</span><span class=err>erro: '+(r.error||'falha')+'</span>';
      }}
      list.insertBefore(d,list.firstChild);
    }});
    document.getElementById('ass-out').style.display='';
  }})
  .catch(function(){{btn.disabled=false;msg.textContent='falha de rede na geração.';}});
}}
</script>"""


_DRIVER_CURTO = {"silencio": "silêncio (cliente some)", "tom_negativo": "tom negativo",
                 "iniciativa_cliente": "queda de iniciativa", "comprimento_msg": "respostas encurtando",
                 "fala_em_cancelar": "fala em cancelar", "critico_recente": "evento crítico",
                 "tom_claude": "tom esfriando"}

_SQUAD_ACAO = {
    "silencio": "Instituir rotina de check-in PROATIVO semanal: nenhuma conta do squad sem conversa há mais de 7 dias; GC abre com conteúdo de valor, não com cobrança.",
    "tom_negativo": "Fazer war-room quinzenal das contas com tom negativo: Growth + GC revisam caso a caso, com 1 ação de reversão datada por conta.",
    "iniciativa_cliente": "Inverter o fluxo nas contas passivas: levar 2 propostas prontas por conta/mês (o cliente que parou de pedir precisa reencontrar valor sem esforço).",
    "execucao": "Mutirão de fila no ClickUp: repriorizar atrasadas com datas realistas e revisão semanal de fila com o time — atraso de entrega é o atrito que alimenta o resto.",
    "trajetoria": "Revisar as contas com trajetória caindo ANTES que virem alerta: 15 min por conta na reunião semanal do squad, com dono e próxima ação.",
}


def _resolve_squad(name: str, mirror: dict | None) -> str | None:
    """Squad VÁLIDO da conta = só os da planilha de composição. Resolve pela
    convenção Bx-Sy do nome; se não bater (planos antigos, ADS, [PAUSADO]…),
    tenta o campo `equipe` do espelho da Operação. None = sem squad conhecido
    (nome do grupo a atualizar). NÃO inventa squad a partir de tag de plano."""
    from .sources.squads_sheet import team_for_account
    fb = None
    if mirror is not None:
        from .sources.nps_sheets import norm_account
        fb = (mirror.get(norm_account(name)) or {}).get("equipe")
    hit = team_for_account(name, fallback_key=fb)
    return hit[0] if hit else None


def _squad_analysis(scores: list[dict]) -> tuple[list[dict], int]:
    """Análise por squad: subscores (relacionamento/execução/risco), dores
    dominantes, score composto 0-100 e plano de ação — base do ranking.
    Fortes/fracos/ações consideram TAMBÉM carga e capacidade (contas/pessoa vs
    média, concentração de MRR em risco, execução crítica) — pedido Otávio
    15/07 ao unificar tudo na aba 'Análise dos Squads'.
    Só entram os squads da PLANILHA de composição; contas sem squad conhecido
    ficam de fora (contadas à parte). Retorna (análise, n_sem_squad)."""
    import statistics as st
    from collections import Counter

    try:
        from .sources.clickup_activities import _mirror_clientes
        mirror = _mirror_clientes()
    except Exception:  # noqa: BLE001 — sem espelho, resolve só pelo nome
        mirror = None
    try:
        from .sources.squads_sheet import squad_teams
        times = squad_teams()
    except Exception:  # noqa: BLE001 — planilha de composição fora não derruba
        times = {}

    by: dict[str, list[dict]] = {}
    sem_squad = 0
    for s in scores:
        sq = _resolve_squad(s["name"], mirror)
        if sq is None:
            sem_squad += 1
            continue
        by.setdefault(sq, []).append(s)
    out = []
    for sq, contas in by.items():
        ev = [s for s in contas if s["evaluable"]]
        execs = [float(s["exec_score"]) for s in contas if s.get("exec_score") is not None]
        n_alert = sum(1 for s in contas if s.get("alert_sev"))
        rel = st.mean(float(s["score"]) for s in ev) if ev else None
        exe = st.mean(execs) if execs else None
        risco_pct = n_alert / len(contas) if contas else 0
        caindo_pct = (sum(1 for s in ev if s["trajectory"] == "caindo") / len(ev)) if ev else 0
        drivers = Counter(d for d in (_top_driver(s.get("reasons") or []) for s in ev) if d)
        dor = drivers.most_common(1)[0][0] if drivers else None
        base = rel if rel is not None else 50.0
        composto = (0.5 * base + 0.25 * (exe if exe is not None else base)
                    + 0.25 * (100 * (1 - risco_pct)))
        pessoas = len(times.get(sq, []))
        out.append({"squad": sq, "n": len(contas), "score": composto, "rel": rel, "exe": exe,
                    "risco_pct": risco_pct, "n_alert": n_alert, "caindo_pct": caindo_pct,
                    "dor": dor, "drivers": drivers,
                    "pessoas": pessoas, "cp": (len(contas) / pessoas if pessoas else None),
                    "exec_atr": sum(1 for s in contas if (s.get("exec_score") or 100) < 40),
                    "mrr_risco": sum(_mrr_val(s) for s in contas if s.get("alert_sev") and _mrr_val(s) > 0)})

    # dimensões RELATIVAS à carteira: média de contas/pessoa e total de MRR em risco
    cps = [a["cp"] for a in out if a["cp"]]
    med_cp = (sum(cps) / len(cps)) if cps else None
    tot_risco = sum(a["mrr_risco"] for a in out) or 1.0
    for a in out:
        fortes, fracos, acoes = [], [], []
        rel, exe = a["rel"], a["exe"]
        (fortes if (rel or 0) >= 60 else fracos).append(
            f"relacionamento (score médio {rel:.0f})" if rel is not None else "relacionamento (sem dados)")
        if exe is not None:
            (fortes if exe >= 70 else fracos).append(f"execução (média {exe:.0f}/100)")
        (fortes if a["risco_pct"] <= 0.35 else fracos).append(
            f"risco ({a['n_alert']} de {a['n']} contas em alerta)")
        if a["caindo_pct"] > 0.3:
            fracos.append(f"trajetória ({a['caindo_pct'] * 100:.0f}% das contas piorando)")
        # carga e capacidade (antes só na tabela; agora entram na análise)
        if a["cp"] is not None and med_cp:
            if a["cp"] >= med_cp * 1.3:
                fracos.append(f"carga ({a['cp']:.1f} contas/pessoa vs média {med_cp:.1f})")
                acoes.append("Sobrecarga: redistribuir contas (priorizar as saudáveis, que exigem menos "
                             "contexto) ou reforçar o time — sobrecarga sustentada vira atraso e churn.")
            elif a["cp"] <= med_cp * 0.7:
                fortes.append(f"carga com folga ({a['cp']:.1f} contas/pessoa vs média {med_cp:.1f})")
        conc = a["mrr_risco"] / tot_risco
        if conc >= 0.3:
            fracos.append(f"concentração de MRR em risco ({conc * 100:.0f}% da carteira, {_fmt_brl(a['mrr_risco'])})")
            acoes.append("Concentração de receita em risco: tratar as contas de maior MRR deste squad "
                         "como prioridade da semana (reunião de retenção com plano de ação individual).")
        if a["exec_atr"] and a["exec_atr"] / a["n"] > 0.2:
            fracos.append(f"entregas ({a['exec_atr']} contas com execução crítica no ClickUp)")
        # plano de ação: das dimensões mais fracas + dor dominante
        if a["dor"] and a["dor"] in _SQUAD_ACAO:
            acoes.append(_SQUAD_ACAO[a["dor"]])
        if exe is not None and exe < 70 and _SQUAD_ACAO["execucao"] not in acoes:
            acoes.append(_SQUAD_ACAO["execucao"])
        if a["caindo_pct"] > 0.3:
            acoes.append(_SQUAD_ACAO["trajetoria"])
        if not acoes:
            acoes.append("Squad saudável: manter a rotina e documentar as práticas que funcionam — "
                         "elas viram referência de playbook para os squads abaixo no ranking.")
        a.update({"fortes": fortes, "fracos": fracos, "acoes": acoes})
    out.sort(key=lambda x: -x["score"])
    return out, sem_squad


def _squads_html(analysis: list[dict], sem_squad: int = 0) -> str:
    """Ranking + card de análise/plano por squad (substitui 'Alertas por squad')."""
    rows = ""
    for i, a in enumerate(analysis, 1):
        rel = f"{a['rel']:.0f}" if a["rel"] is not None else "—"
        exe = f"{a['exe']:.0f}" if a["exe"] is not None else "—"
        rows += (f"<div class='row srow'><div class='rk'>{i}º</div><div class='sq'>{escape(a['squad'])}</div>"
                 f"<div class='num'><b>{a['score']:.0f}</b></div><div class='num'>{rel}</div>"
                 f"<div class='num'>{exe}</div><div class='num'>{a['n_alert']}/{a['n']}</div>"
                 f"<div class='num'>{_fmt_brl(a['mrr_risco'])}</div>"
                 f"<div>{escape(_DRIVER_CURTO.get(a['dor'] or '', a['dor'] or '—'))}</div></div>")
    cards = ""
    for i, a in enumerate(analysis, 1):
        team = None
        try:
            from .sources.squads_sheet import team_for_key
            team = team_for_key(a["squad"])
        except Exception:  # noqa: BLE001 — planilha de squads fora não derruba a aba
            pass
        equipe = (" · ".join(f"{m['funcao']}: {m['nome']}" for m in team[1]) if team else "")
        fortes = ", ".join(a["fortes"]) or "—"
        fracos = ", ".join(a["fracos"]) or "nenhum ponto fraco relevante"
        acoes = "".join(f"<div class='sug'><span class='b'>→</span><span>{escape(x)}</span></div>" for x in a["acoes"])
        cards += (f"<div style='{_CARD};margin-top:10px'>"
                  f"<div style='display:flex;gap:10px;align-items:baseline;flex-wrap:wrap'>"
                  f"<span style='font-family:var(--font-display);font-weight:700;font-size:16px'>{i}º · {escape(a['squad'])}</span>"
                  f"<span style='font-family:var(--font-display);font-weight:700;color:var(--brand)'>{a['score']:.0f}/100</span>"
                  f"<span style='font-size:var(--fs-xs);color:var(--text-muted)'>{a['n']} contas"
                  + (f" · {a['pessoas']} pessoas ({a['cp']:.1f}/pessoa)" if a.get("cp") else "")
                  + f"</span>"
                  f"<span style='font-size:var(--fs-xs);color:var(--text-muted)'>{escape(equipe[:120])}</span></div>"
                  f"<div style='font-size:var(--fs-sm);margin-top:8px'><span style='color:var(--status-baixo)'>fortes:</span> {escape(fortes)}</div>"
                  f"<div style='font-size:var(--fs-sm);margin-top:3px'><span style='color:var(--status-critico)'>fracos:</span> {escape(fracos)}</div>"
                  f"<div class='asslbl' style='margin:10px 0 2px'>plano de ação do squad</div>{acoes}</div>")
    head = ("<div class='tbl'><div class='row thead srow'><div>#</div><div>Squad</div><div>Score</div>"
            "<div>Relac.</div><div>Exec.</div><div>Alertas</div><div>MRR risco</div><div>Dor dominante</div></div>"
            + rows + "</div>"
            "<style>.srow{grid-template-columns:36px 76px 64px 64px 64px 72px 110px minmax(140px,1fr)}"
            ".srow .rk{font-family:var(--font-display);font-weight:700}"
            ".srow .num{text-align:center;font-variant-numeric:tabular-nums}"
            ".srow .sq{font-weight:var(--fw-semibold)}</style>")
    nota = ""
    if sem_squad:
        nota = (f"<p class=note style='margin-top:10px'>{sem_squad} conta(s) ficaram fora do ranking por "
                "<b>não ter squad identificado</b> — o nome do grupo não traz o padrão <b>Bx-Sy</b> "
                "(planos antigos, ADS) e o espelho da Operação também não tem a equipe. "
                "Atualizar o nome do grupo (ou a equipe no ClickUp) para incluí-las.</p>")
    return head + nota + cards


def _dist_html(rep: dict) -> str:
    """Quadro "Distribuições": três grupos lado a lado (Faixa / Estágio /
    Trajetória), cada um com título colorido e linha divisória — no lugar dos
    antigos separadores "— Faixa —" que se misturavam com as linhas de dado.
    Barra proporcional + ponto na cor semântica facilitam a leitura."""
    _EST_VAR = {"saudavel": "--status-baixo", "desengajamento_inicial": "--status-medio",
                "insatisfacao_latente": "--status-medio", "insatisfacao_ativa": "--status-alto",
                "intencao_de_saida": "--status-critico", "nao_avaliavel": "--status-semdados"}
    _TRAJ_VAR = {"subindo": "--status-baixo", "estavel": "--status-semdados", "caindo": "--status-critico"}
    _FAIXA_LBL = {"medio": "médio", "critico": "crítico", "sem_dados": "sem dados"}
    _TRAJ_LBL = {"estavel": "estável"}
    grupos = [
        ("Faixa de risco", rep["faixa"], _BAND_VAR, _FAIXA_LBL),
        ("Estágio", rep["estagio"], _EST_VAR, _STAGE_LABEL),
        ("Trajetória", rep["trajetoria"], _TRAJ_VAR, _TRAJ_LBL),
    ]
    cols = ""
    for titulo, dist, cores, lbls in grupos:
        total = sum(dist.values()) or 1
        rows = ""
        for k, v in sorted(dist.items(), key=lambda x: -x[1]):
            cor = f"var({cores.get(k, '--status-semdados')})"
            rows += (f"<div class=dist-r><span class=dist-dot style='background:{cor}'></span>"
                     f"<span class=dist-l>{escape(lbls.get(k, str(k)))}</span>"
                     f"<span class=dist-bar><span style='width:{v / total * 100:.0f}%;background:{cor}'></span></span>"
                     f"<b class=dist-n>{v}</b></div>")
        cols += f"<div class=dist-g><div class=dist-h>{titulo}</div>{rows}</div>"
    return (f"<div class=dist-wrap>{cols}</div>"
            "<style>"
            ".dist-wrap{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:18px 0}"
            ".dist-g{padding:0 24px;border-left:1px solid var(--border)}"
            ".dist-g:first-child{border-left:none;padding-left:0}"
            ".dist-g:last-child{padding-right:0}"
            ".dist-h{font-size:var(--fs-2xs);font-weight:var(--fw-semibold);text-transform:uppercase;"
            "letter-spacing:var(--tracking-label);color:var(--brand);"
            "border-bottom:1px solid var(--border-strong);padding-bottom:7px;margin-bottom:4px}"
            ".dist-r{display:grid;grid-template-columns:10px 1fr 72px 36px;gap:9px;align-items:center;"
            "padding:6px 0;border-bottom:1px solid var(--border);font-size:var(--fs-sm)}"
            ".dist-r:last-child{border-bottom:none}"
            ".dist-dot{width:8px;height:8px;border-radius:50%}"
            ".dist-l{color:var(--text-2)}"
            ".dist-bar{height:5px;background:var(--surface-3);border-radius:3px;overflow:hidden}"
            ".dist-bar>span{display:block;height:100%;border-radius:3px}"
            ".dist-n{text-align:right;font-variant-numeric:tabular-nums}"
            "</style>")


def _cancel_rows(conn: Any) -> list[dict]:
    """Cache local das planilhas de cancelamento (grw_cancelamentos)."""
    from .sources.cancel_sheets import _DDL
    with conn.cursor() as cur:
        cur.execute(_DDL)  # idempotente — 1ª visita antes do 1º sync
        cur.execute("""SELECT tipo, mes, cliente, data_inicio, data_saida, meses,
                              valor, plano, equipe, gc, motivo, situacao
                         FROM grw_cancelamentos ORDER BY mes, cliente""")
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


_PLANOS_LEGADO = ("ASS", "ADS", "ESTRAT", "CONSULT", "ANTIGO", "MASTER + ADS")


def _canc_bundle(r: dict) -> str | None:
    """Bundle (B1-B5) do cancelamento — pelo PLANO do cliente (correção Otávio
    20/07: a equipe vinha PRIMEIRO e o squad atende clientes de vários tipos —
    ex.: cliente ADS do squad B5-S3 contava como churn do B5/Elite). Ordem:
    (1) Bx explícito no plano; (2) nome do plano novo (START→B1 … ELITE→B5,
    régua oficial das barras de vendas); (3) plano lançado que NÃO é bundle
    (ADS, Estratégia, Assessoria antiga…) → None ('antigos/ADS' — NUNCA
    classificar pelo squad); (4) só SEM plano lançado a equipe entra como
    último recurso (aproximação)."""
    import re as _re
    principal = str(r.get("plano") or "").upper().split("+")[0].strip()
    m = _re.search(r"B[1-5](?!\w)", principal)  # Bx explícito (não casa 'BUNDLES')
    if m:
        return m.group(0)
    for k, b in (("START", "B1"), ("TRACTION", "B2"), ("SCALE", "B3"),
                 ("PLATINUM", "B4"), ("ELITE", "B5")):
        if k in principal:
            return b
    if principal and "BUNDLE" not in principal:
        return None  # plano específico não-bundle: ADS/Estratégia/antigos
    # sem plano OU plano genérico 'BUNDLES': a equipe é a única pista do bundle
    m = _re.search(r"B[1-5]", str(r.get("equipe") or ""))
    return m.group(0) if m else None


def _canc_legado(r: dict) -> bool:
    pl = str(r.get("plano") or "").upper()
    return any(x in pl for x in _PLANOS_LEGADO) and "TRACTION" not in pl


def _mrr_por_bundle(scores: list[dict]) -> dict[str, tuple[float, int]]:
    """MRR da base atual por bundle (p/ a taxa por FATURAMENTO — Otávio 16/07):
    (soma, nº de contas COM valor) — cobertura baixa suprime a taxa (antigos
    quase não têm MRR lançado e a taxa sairia absurda, ex.: 307%/mês).
    Compartilhada entre a tela HTML e o /api/growth/cancelamentos (redesenho)."""
    out: dict[str, tuple[float, int]] = {}
    for s in scores:
        m_b = re.search(r"B[1-5]", s["name"])
        k_b = m_b.group(0) if m_b else "outros"
        v_b = max(0.0, _mrr_val(s))
        soma, cnt = out.get(k_b, (0.0, 0))
        out[k_b] = (soma + v_b, cnt + (1 if v_b > 0 else 0))
    return out


def _cancel_dados(rows: list[dict], f_ini: dt.date, f_fim: dt.date,
                  base_bundle: dict, mrr_bundle: dict) -> dict:
    """Agregados da aba Cancelamentos como DADOS puros (JSON-able) — mesmas
    fórmulas da tela HTML (taxa = média do período ÷ base ATUAL; base de MRR
    estimada quando nem toda conta tem valor; B1 fora da taxa geral; aviso de
    base pequena <12). Endpoint do redesenho consome isto; qualquer mudança de
    régua acontece AQUI, e as duas UIs andam juntas."""
    import statistics as _st

    def _f(v):
        return float(v) if v is not None else None

    hoje = dt.date.today()
    mes_atual = hoje.replace(day=1)
    dentro = lambda r: f_ini <= r["mes"] <= f_fim  # noqa: E731
    canc = [r for r in rows if r["tipo"] == "cancelamento" and dentro(r)]
    term = [r for r in rows if r["tipo"] == "termino" and dentro(r)]
    trat = [r for r in rows if r["tipo"] == "tratativa"]
    rev = [r for r in rows if r["tipo"] == "revertido" and dentro(r)]
    meses = sorted({r["mes"] for r in canc})
    c_mes = [r for r in canc if r["mes"] == mes_atual]
    trat_mes = [r for r in trat if r["mes"] >= mes_atual]
    tempos = [_f(r["meses"]) for r in canc if r["meses"] is not None]

    por_mes = []
    for m in meses:
        cs = [r for r in canc if r["mes"] == m]
        vals = [_f(r["valor"]) for r in cs if r["valor"] is not None]
        tps = [_f(r["meses"]) for r in cs if r["meses"] is not None]
        por_mes.append({"mes": m.strftime("%Y-%m"), "mes_label": m.strftime("%m/%Y"),
                        "saidas": len(cs), "mrr_perdido": sum(_f(r["valor"]) or 0 for r in cs),
                        "ticket_medio": (_st.mean(vals) if vals else None),
                        "tempo_casa_mediano": (_st.median(tps) if tps else None),
                        "terminos_start": sum(1 for r in term if r["mes"] == m)})

    canc_bund: dict = {}
    for r in canc:
        canc_bund.setdefault(_canc_bundle(r) or "outros", []).append(r)
    n_meses = max(1, len({r["mes"] for r in canc}) or 1)

    def _tx(rotulo, bb, mrr_par, rs, recorrente=True):
        mrr_b, mrr_cnt = mrr_par
        cb = len(rs)
        mrr_p = sum(_f(r["valor"]) or 0 for r in rs)
        est = bool(bb and mrr_cnt and mrr_cnt < bb)
        if est:
            mrr_b = mrr_b / mrr_cnt * bb
        tx_c = (cb / n_meses) / bb if bb else None
        tx_f = (mrr_p / n_meses) / mrr_b if mrr_b else None
        return {"bundle": rotulo, "recorrente": recorrente,
                "base_atual": bb or 0, "saidas": cb, "janela_meses": n_meses,
                "mrr_perdido": mrr_p,
                "mrr_base": (mrr_b or None), "mrr_base_estimado": est,
                "mrr_base_com_valor": mrr_cnt,
                "taxa_clientes_pct": (round(tx_c * 100, 1) if tx_c is not None else None),
                "taxa_faturamento_pct": (round(tx_f * 100, 1) if tx_f is not None else None),
                "aviso": ("base pequena/encolheu — taxa pouco confiável"
                          if bb and bb < 12 else None)}

    _sem = (0.0, 0)
    taxa_bundle = [_tx("B1", base_bundle.get("B1", 0), mrr_bundle.get("B1", _sem),
                       canc_bund.get("B1", []), recorrente=False)]
    for b in ("B2", "B3", "B4", "B5"):
        taxa_bundle.append(_tx(b, base_bundle.get(b, 0), mrr_bundle.get(b, _sem),
                               canc_bund.get(b, [])))
    taxa_bundle.append(_tx("antigos/ADS", base_bundle.get("outros", 0),
                           mrr_bundle.get("outros", _sem), canc_bund.get("outros", [])))
    rec_base = sum(v for k, v in base_bundle.items() if k != "B1")
    rec_mrr = (sum(v[0] for k, v in mrr_bundle.items() if k != "B1"),
               sum(v[1] for k, v in mrr_bundle.items() if k != "B1"))
    rec_canc = [r for k, rs in canc_bund.items() if k != "B1" for r in rs]
    taxa_geral = _tx("GERAL (recorrentes, sem B1)", rec_base, rec_mrr, rec_canc)

    from collections import Counter
    motivos = [{"motivo": m, "saidas": n} for m, n in
               Counter((r["motivo"] or "").strip()[:48] for r in canc if r["motivo"]).most_common(8)]

    def _grupo(campo):
        agg: dict[str, list] = {}
        for r in canc:
            agg.setdefault((r[campo] or "—").strip().upper()[:24], []).append(r)
        out = []
        for k, rs in sorted(agg.items(), key=lambda x: -len(x[1]))[:12]:
            tps = [_f(r["meses"]) for r in rs if r["meses"] is not None]
            out.append({"nome": k, "saidas": len(rs),
                        "mrr_perdido": sum(_f(r["valor"]) or 0 for r in rs),
                        "tempo_casa_mediano": (_st.median(tps) if tps else None)})
        return out

    return {
        "periodo": {"ini": f_ini.strftime("%Y-%m"), "fim": f_fim.strftime("%Y-%m")},
        "meses_disponiveis": [m.strftime("%Y-%m") for m in sorted({r["mes"] for r in rows})],
        "kpis": {"saidas_mes": len(c_mes),
                 "mrr_perdido_mes": sum(_f(r["valor"]) or 0 for r in c_mes),
                 "em_tratativa": len(trat_mes), "revertidos": len(rev),
                 "tempo_casa_mediano": (_st.median(tempos) if tempos else None),
                 "tempo_casa_n": len(tempos)},
        "por_mes": por_mes, "taxa_bundle": taxa_bundle, "taxa_geral": taxa_geral,
        "motivos": motivos, "sem_motivo": sum(1 for r in canc if not (r["motivo"] or "").strip()),
        "casos_com_motivo": [{"mes": r["mes"].strftime("%m/%Y"), "cliente": r["cliente"],
                              "plano": r["plano"], "motivo": (r["motivo"] or "")[:160]}
                             for r in sorted(canc, key=lambda x: x["mes"], reverse=True)
                             if r["motivo"]][:15],
        "tratativas": [{"cliente": r["cliente"], "gc": r["gc"], "plano": r["plano"],
                        "situacao": r["situacao"] or "sem situação registrada"}
                       for r in sorted(trat_mes, key=lambda x: (x["mes"], x["cliente"]))],
        "por_plano": _grupo("plano"), "por_equipe": _grupo("equipe"),
    }


@app.get("/api/growth/cancelamentos")
def api_cancelamentos(request: Request, ini: str = Query(""), fim: str = Query("")):
    """JSON da aba Cancelamentos (redesenho, Lote 1) — mesmos números da tela
    HTML: tudo sai de _cancel_dados; o frontend só formata."""
    _require_api(request)
    with _conn() as c:
        rows = _cancel_rows(c)
        with c.cursor() as cur:
            cur.execute("""SELECT COALESCE(substring(name FROM 'B[1-5]'), 'outros'), count(*)
                             FROM accounts GROUP BY 1""")
            base_bundle = dict(cur.fetchall())
        mrr_bundle = _mrr_por_bundle(_latest_scores(c))
    if not rows:
        return JSONResponse({"error": "sem dados de cancelamento carregados"}, status_code=503)
    todos_meses = sorted({r["mes"] for r in rows})

    def _mes(sv, padrao):
        try:
            return dt.date.fromisoformat(sv + "-01")
        except ValueError:
            return padrao
    return _cancel_dados(rows, _mes(ini, todos_meses[0]), _mes(fim, todos_meses[-1]),
                         base_bundle, mrr_bundle)


def _cancel_content(rows: list[dict], request: Request, base_bundle: dict | None = None,
                    mrr_bundle: dict | None = None) -> str:
    """Aba Cancelamentos — análises sobre as planilhas do time (fonte oficial
    de churn realizado; ClickUp de cancelados é mal preenchido)."""
    if not rows:
        return ("<div class=page-head><h1>Cancelamentos</h1></div>"
                "<section><div style='" + _CARD + "'>Sem dados carregados — rode "
                "<code>python -m scripts.sync_cancelamentos</code> (usa as planilhas "
                "do time; cópia local em data/ quando não houver acesso público).</div></section>")
    import statistics as _st
    hoje = dt.date.today()
    mes_atual = hoje.replace(day=1)
    # ---- filtro temporal (?ini=YYYY-MM&fim=YYYY-MM; padrão = tudo)
    qp = request.query_params
    todos_meses = sorted({r["mes"] for r in rows}) or [mes_atual]
    def _mes_qp(nome, padrao):
        try:
            return dt.date.fromisoformat((qp.get(nome) or "") + "-01")
        except ValueError:
            return padrao
    f_ini = _mes_qp("ini", todos_meses[0])
    f_fim = _mes_qp("fim", todos_meses[-1])
    def _no_periodo(r):
        return f_ini <= r["mes"] <= f_fim
    canc = [r for r in rows if r["tipo"] == "cancelamento" and _no_periodo(r)]
    term = [r for r in rows if r["tipo"] == "termino" and _no_periodo(r)]
    trat = [r for r in rows if r["tipo"] == "tratativa"]
    rev = [r for r in rows if r["tipo"] == "revertido" and _no_periodo(r)]
    meses = sorted({r["mes"] for r in canc})
    opcoes = "".join(f"<option value='{m.strftime('%Y-%m')}'>{m.strftime('%m/%Y')}</option>" for m in todos_meses)
    form_filtro = (
        "<form method=get action=/growth><input type=hidden name=view value=cancelamentos>"
        "<div class=filters style='display:flex;gap:12px;align-items:end;background:var(--surface-1);"
        "border:1px solid var(--border-mid);border-radius:var(--radius-md);padding:12px 14px;margin:14px 0 4px'>"
        f"<div class=grp><label>de (mês)</label><select name=ini>{opcoes.replace(chr(39) + f_ini.strftime('%Y-%m') + chr(39), chr(39) + f_ini.strftime('%Y-%m') + chr(39) + ' selected')}</select></div>"
        f"<div class=grp><label>até (mês)</label><select name=fim>{opcoes.replace(chr(39) + f_fim.strftime('%Y-%m') + chr(39), chr(39) + f_fim.strftime('%Y-%m') + chr(39) + ' selected')}</select></div>"
        "<button id=clearf type=submit>Aplicar</button></div></form>")

    def _f(v):
        return float(v) if v is not None else None

    def card(inner):
        return f"<div style='{_CARD}'>{inner}</div>"

    def tbl(header, linhas):
        return f"<table style='width:100%;border-collapse:collapse'>{header}{linhas}</table>"

    # ---- KPIs do mês corrente
    c_mes = [r for r in canc if r["mes"] == mes_atual]
    mrr_mes = sum(_f(r["valor"]) or 0 for r in c_mes)
    trat_mes = [r for r in trat if r["mes"] >= mes_atual]
    tempos = [_f(r["meses"]) for r in canc if r["meses"] is not None]
    kpis = (
        "<div class=kpis>"
        f"<div class=kpi><div class=n style='color:var(--status-critico)'>{len(c_mes)}</div>"
        f"<div class=l>saídas em {mes_atual.strftime('%m-%Y')}</div><div class=s>formalizadas nas planilhas</div></div>"
        f"<div class=kpi><div class=n>{_fmt_brl(mrr_mes)}</div><div class=l>MRR perdido no mês</div>"
        f"<div class=s>soma das mensalidades</div></div>"
        f"<div class=kpi><div class=n style='color:var(--status-medio)'>{len(trat_mes)}</div>"
        f"<div class=l>em tratativa</div><div class=s>pipeline de retenção — agir antes de formalizar</div></div>"
        f"<div class=kpi><div class=n style='color:var(--status-baixo)'>{len(rev)}</div>"
        f"<div class=l>revertidos (anti-churn)</div><div class=s>intenção contornada — não contam como saída</div></div>"
        f"<div class=kpi><div class=n>{_st.median(tempos):.0f} m</div><div class=l>tempo de casa mediano</div>"
        f"<div class=s>na saída · {len(tempos)} c/ dado</div></div>"
        "</div>")

    # ---- por mês
    th = ("<tr><th style='text-align:left;padding:7px;border-bottom:1px solid var(--border-strong);color:var(--text-muted);font-size:var(--fs-2xs);text-transform:uppercase'>Mês</th>"
          + "".join(f"<th style='text-align:right;padding:7px;border-bottom:1px solid var(--border-strong);color:var(--text-muted);font-size:var(--fs-2xs);text-transform:uppercase'>{h}</th>"
                    for h in ("Saídas", "MRR perdido", "Ticket médio", "Tempo casa (med.)", "Términos START")) + "</tr>")
    max_n = max((sum(1 for r in canc if r["mes"] == m) for m in meses), default=1)
    linhas_m = ""
    for m in meses:
        cs = [r for r in canc if r["mes"] == m]
        mrr = sum(_f(r["valor"]) or 0 for r in cs)
        vals = [_f(r["valor"]) for r in cs if r["valor"] is not None]
        tps = [_f(r["meses"]) for r in cs if r["meses"] is not None]
        nt = sum(1 for r in term if r["mes"] == m)
        barra = (f"<span style='display:inline-block;vertical-align:middle;margin-left:8px;height:6px;"
                 f"width:{len(cs) / max_n * 90:.0f}px;background:var(--status-critico);border-radius:3px'></span>")
        td = "text-align:right;padding:7px;border-bottom:1px solid var(--border);font-variant-numeric:tabular-nums"
        tempo_td = f"{_st.median(tps):.0f} m" if tps else "—"
        linhas_m += (f"<tr><td style='padding:7px;border-bottom:1px solid var(--border)'><b>{m.strftime('%m-%Y')}</b></td>"
                     f"<td style='{td}'>{len(cs)}{barra}</td>"
                     f"<td style='{td}'>{_fmt_brl(mrr)}</td>"
                     f"<td style='{td}'>{_fmt_brl(_st.mean(vals)) if vals else '—'}</td>"
                     f"<td style='{td}'>{tempo_td}</td>"
                     f"<td style='{td}'>{nt or '—'}</td></tr>")

    # ---- tratativas em aberto (fila de retenção)
    linhas_t = ""
    for r in sorted(trat_mes, key=lambda x: (x["mes"], x["cliente"])):
        td = "padding:7px;border-bottom:1px solid var(--border);font-size:var(--fs-sm)"
        linhas_t += (f"<tr><td style='{td}'><b>{escape((r['cliente'] or '')[:52])}</b></td>"
                     f"<td style='{td}'>{escape(r['gc'] or '—')}</td>"
                     f"<td style='{td}'>{escape(r['plano'] or '—')}</td>"
                     f"<td style='{td};color:var(--text-muted)'>{escape((r['situacao'] or 'sem situação registrada')[:90])}</td></tr>")
    th_t = "".join(f"<th style='text-align:left;padding:7px;border-bottom:1px solid var(--border-strong);color:var(--text-muted);font-size:var(--fs-2xs);text-transform:uppercase'>{h}</th>"
                   for h in ("Cliente", "GC/Squad", "Plano", "Situação"))

    # ---- por plano e por equipe (todo o período) — barras comparativas com a
    # tabela completa preservada em details (Redesenho Parte A)
    def grupo(campo, titulo):
        from .viz import barras_h as _vzb, detalhe_tabela as _vzd
        agg: dict[str, list] = {}
        for r in canc:
            k = (r[campo] or "—").strip().upper()[:24]
            agg.setdefault(k, []).append(r)
        tops = sorted(agg.items(), key=lambda x: -len(x[1]))[:12]
        linhas = ""
        for k, rs in tops:
            mrr = sum(_f(r['valor']) or 0 for r in rs)
            tps = [_f(r['meses']) for r in rs if r['meses'] is not None]
            td = "text-align:right;padding:6px 7px;border-bottom:1px solid var(--border);font-variant-numeric:tabular-nums"
            linhas += (f"<tr><td style='padding:6px 7px;border-bottom:1px solid var(--border)'>{escape(k)}</td>"
                       f"<td style='{td}'>{len(rs)}</td><td style='{td}'>{_fmt_brl(mrr)}</td>"
                       f"<td style='{td}'>{(_st.median(tps) if tps else 0):.0f} m</td></tr>")
        th_g = ("<tr><th style='text-align:left;padding:6px 7px;border-bottom:1px solid var(--border-strong);color:var(--text-muted);font-size:var(--fs-2xs);text-transform:uppercase'>" + titulo + "</th>"
                + "".join(f"<th style='text-align:right;padding:6px 7px;border-bottom:1px solid var(--border-strong);color:var(--text-muted);font-size:var(--fs-2xs);text-transform:uppercase'>{h}</th>"
                          for h in ("Saídas", "MRR", "Tempo (med.)")) + "</tr>")
        graf = _vzb([(k, len(rs), _fmt_brl(sum(_f(r['valor']) or 0 for r in rs))) for k, rs in tops[:8]],
                    largura_rotulo=130)
        return graf + _vzd(tbl(th_g, linhas), f"ver tabela completa ({titulo.lower()}, MRR e tempo de casa)")

    # ---- motivos: PARETO agregado (Parte A) + casos recentes em details
    from .viz import barras_h as _vz_barras_m, detalhe_tabela as _vz_det_m

    def _pareto_motivos(rows_m):
        from collections import Counter
        cont = Counter((r["motivo"] or "").strip()[:48] for r in rows_m if r["motivo"])
        tops = cont.most_common(8)
        return _vz_barras_m([(m, n, None) for m, n in tops], largura_rotulo=240,
                            cores=["var(--status-critico)"] + ["var(--brand)"] * 7)

    com_motivo = [r for r in canc if r["motivo"]]
    linhas_mo = ""
    for r in sorted(com_motivo, key=lambda x: x["mes"], reverse=True)[:15]:
        td = "padding:7px;border-bottom:1px solid var(--border);font-size:var(--fs-sm)"
        linhas_mo += (f"<tr><td style='{td};white-space:nowrap'>{r['mes'].strftime('%m-%Y')}</td>"
                      f"<td style='{td}'><b>{escape((r['cliente'] or '')[:40])}</b></td>"
                      f"<td style='{td}'>{escape(r['plano'] or '—')}</td>"
                      f"<td style='{td};color:var(--text-2)'>{escape((r['motivo'] or '')[:160])}</td></tr>")

    # ---- taxa de cancelamento por bundle (base = contas monitoradas HOJE)
    # Régua GERAL (Otávio 16/07): só planos RECORRENTES — o B1 é semestral pago
    # à vista (não recorrente) e distorcia a taxa geral (explica a diferença p/
    # os decks antigos do All Hands). B1 segue exibido, mas FORA do total.
    # Duas visões lado a lado: por Nº DE CLIENTES e por FATURAMENTO (MRR).
    base_bundle = base_bundle or {}
    mrr_bundle = mrr_bundle or {}
    canc_bund: dict = {}
    for r in canc:
        canc_bund.setdefault(_canc_bundle(r) or "outros", []).append(r)
    n_meses = max(1, len({r["mes"] for r in canc}) or 1)

    graf_tx: list[tuple] = []  # (rótulo plano, taxa clientes, sublabel faturamento)

    def _linha_tx(rotulo, bb, mrr_par, rs, chip="", negrito=False, plain=""):
        mrr_b, mrr_cnt = mrr_par
        cb = len(rs)
        mrr_p = sum(_f(r["valor"]) or 0 for r in rs)
        tx_c = (cb / n_meses) / bb if bb else None
        # nem toda conta tem MRR lançado (cobertura 20-56% por bundle) — usar a
        # soma crua distorcia a taxa (antigos davam 307%/mês). Base ESTIMADA =
        # média das contas COM valor × total de contas, marcada com ≈.
        est = bool(bb and mrr_cnt and mrr_cnt < bb)
        if est:
            mrr_b = mrr_b / mrr_cnt * bb
        tx_f = (mrr_p / n_meses) / mrr_b if mrr_b else None
        pre = "≈ " if est else ""
        if mrr_b:
            mrr_b_txt = f"{pre}{_fmt_brl(mrr_b)}"
            if est:
                mrr_b_txt = (f"<span title='estimado: média das contas com MRR lançado × total "
                             f"({mrr_cnt} de {bb} têm valor)'>{mrr_b_txt}</span>")
        else:
            mrr_b_txt = "—"
        if plain and tx_c is not None:
            # contexto NA BARRA (20/07, caso B5): taxa = média do período ÷ base
            # ATUAL — quando a base encolheu, a taxa fica alta mesmo sem saídas
            # recentes; o sublabel conta a história e avisa
            sub_bits = [f"{cb} saída(s) em {n_meses}m · base atual {bb or 0}"]
            if tx_f is not None:
                sub_bits.append(f"faturamento: {pre}{tx_f * 100:.1f}%/mês")
            if bb and bb < 12:
                sub_bits.append("⚠ base pequena/encolheu — taxa pouco confiável")
            graf_tx.append((plain, tx_c * 100, " · ".join(sub_bits)))
        td = "text-align:right;padding:7px;border-bottom:1px solid var(--border);font-variant-numeric:tabular-nums"
        b = "font-weight:700" if negrito else ""
        borda = "border-top:2px solid var(--border-strong)" if negrito else ""
        return (f"<tr style='{borda}'><td style='padding:7px;border-bottom:1px solid var(--border);{b}'>{rotulo}{chip}</td>"
                f"<td style='{td};{b}'>{bb or '—'}</td>"
                f"<td style='{td};{b}'>{mrr_b_txt}</td>"
                f"<td style='{td};{b}'>{cb}</td>"
                f"<td style='{td};{b}'>{_fmt_brl(mrr_p)}</td>"
                f"<td style='{td};{b}'>{(f'{tx_c * 100:.1f}%/mês' if tx_c is not None else '—')}</td>"
                f"<td style='{td};{b}'>{(f'{pre}{tx_f * 100:.1f}%/mês' if tx_f is not None else '—')}</td></tr>")

    chip_b1 = (" <span class=chip style='--c:var(--status-semdados)' title='B1/Start é plano semestral pago à vista "
               "— não recorrente; entra na visão por plano mas fica FORA da taxa geral'>não recorrente</span>")
    _sem_mrr = (0.0, 0)
    tx_rows = _linha_tx("<b>B1</b>", base_bundle.get("B1", 0), mrr_bundle.get("B1", _sem_mrr),
                        canc_bund.get("B1", []), chip=chip_b1, plain="B1 (não recorrente)")
    for b in ("B2", "B3", "B4", "B5"):
        tx_rows += _linha_tx(f"<b>{b}</b>", base_bundle.get(b, 0), mrr_bundle.get(b, _sem_mrr),
                             canc_bund.get(b, []), plain=b)
    tx_rows += _linha_tx("antigos/ADS (sem Bx no nome)", base_bundle.get("outros", 0),
                         mrr_bundle.get("outros", _sem_mrr), canc_bund.get("outros", []), plain="antigos/ADS")
    rec_base = sum(v for k, v in base_bundle.items() if k != "B1")
    rec_mrr = (sum(v[0] for k, v in mrr_bundle.items() if k != "B1"),
               sum(v[1] for k, v in mrr_bundle.items() if k != "B1"))
    rec_canc = [r for k, rs in canc_bund.items() if k != "B1" for r in rs]
    tx_rows += _linha_tx("Taxa GERAL — recorrentes (sem B1)", rec_base, rec_mrr, rec_canc,
                         negrito=True, plain="GERAL (recorrentes)")
    # visual primeiro (barras comparativas), tabela completa preservada em
    # details (Redesenho Parte A — nenhum dado some)
    from .viz import barras_h as _vz_barras, detalhe_tabela as _vz_det
    graf_ordenado = sorted(graf_tx, key=lambda x: -x[1])
    cores_tx = ["var(--status-critico)" if "GERAL" in r else "var(--brand)" for r, _v, _s in graf_ordenado]
    taxa_html = ("<section><div class=sec-head><h2>Taxa de cancelamento por bundle</h2>"
                 f"<span class=sub>média mensal do período filtrado ({n_meses} m) ÷ base monitorada ATUAL (aproximação: sem base histórica mês a mês) · "
                 "taxa GERAL = só planos recorrentes — B1 fora (semestral, não recorrente) · "
                 "duas visões: por clientes e por faturamento (MRR) · ≈ = base de MRR estimada "
                 "(nem toda conta tem valor lançado; média das preenchidas × total)</span></div>"
                 + card(_vz_barras(graf_ordenado, fmt=lambda v: f"{v:.1f}%/mês", cores=cores_tx,
                                   largura_valor=250)
                        + _vz_det(tbl("<tr>" + "".join(f"<th style='text-align:{al};padding:7px;border-bottom:1px solid var(--border-strong);color:var(--text-muted);font-size:var(--fs-2xs);text-transform:uppercase'>{h}</th>" for h, al in (("Bundle", "left"), ("Base ativa", "right"), ("MRR da base", "right"), ("Saídas no período", "right"), ("MRR perdido", "right"), ("Taxa clientes", "right"), ("Taxa faturamento", "right"))) + "</tr>", tx_rows),
                                  "ver tabela completa (base, MRR, saídas, taxa por faturamento)"))
                 + "</section>")

    # ---- gráfico de evolução mensal (total × novos × antigos) + MRR
    from .marketing.ui import _svg_line
    lbls = [m.strftime("%m/%y") for m in meses]
    tot_s = [float(sum(1 for r in canc if r["mes"] == m)) for m in meses]
    novo_s = [float(sum(1 for r in canc if r["mes"] == m and not _canc_legado(r))) for m in meses]
    leg_s = [float(sum(1 for r in canc if r["mes"] == m and _canc_legado(r))) for m in meses]
    mrr_s = [float(sum(_f(r["valor"]) or 0 for r in canc if r["mes"] == m)) for m in meses]
    g1 = _svg_line([("Total", "var(--status-critico)", tot_s),
                    ("Planos novos (bundles)", "var(--brand)", novo_s),
                    ("Planos antigos/ADS", "var(--text-muted)", leg_s)], lbls)
    g2 = _svg_line([("MRR perdido (R$)", "var(--status-alto)", mrr_s)], lbls,
                   fmt_y=lambda v: f"R$ {v:,.0f}".replace(",", "."))
    evolucao_html = ("<section><div class=sec-head><h2>Evolução mensal</h2>"
                     "<span class=sub>cancelamentos por mês — total e separado por planos novos (bundles) × antigos/ADS</span></div>"
                     + card(g1) + "</section>"
                     "<section><div class=sec-head><h2>MRR perdido por mês</h2></div>" + card(g2) + "</section>")

    # ---- tempo de casa por bundle (visão complementar)
    tc_rows = ""
    for b in ("B1", "B2", "B3", "B4", "B5", "outros"):
        tps = [_f(r["meses"]) for r in canc_bund.get(b, []) if r.get("meses") is not None]
        if not tps:
            continue
        td = "text-align:right;padding:7px;border-bottom:1px solid var(--border)"
        tc_rows += (f"<tr><td style='padding:7px;border-bottom:1px solid var(--border)'><b>{b}</b></td>"
                    f"<td style='{td}'>{len(tps)}</td><td style='{td}'>{_st.median(tps):.0f} m</td>"
                    f"<td style='{td}'>{sum(1 for x in tps if x <= 3) / len(tps) * 100:.0f}%</td></tr>")
    tempo_html = ""
    if tc_rows:
        # barra EMPILHADA precoce×tardio por bundle (proporção — Parte A);
        # tabela com mediana preservada em details
        from .viz import detalhe_tabela as _vz_det2, empilhada as _vz_emp
        itens_emp = []
        for b in ("B1", "B2", "B3", "B4", "B5", "outros"):
            tps = [_f(r["meses"]) for r in canc_bund.get(b, []) if r.get("meses") is not None]
            if tps:
                prec = sum(1 for x in tps if x <= 3)
                itens_emp.append((b, {"precoce (≤3 meses)": prec, "tardio": len(tps) - prec}))
        emp = _vz_emp(itens_emp, [("precoce (≤3 meses)", "var(--status-critico)"),
                                  ("tardio", "var(--status-medio)")], largura_rotulo=90)
        tempo_html = ("<section><div class=sec-head><h2>Tempo de casa na saída, por bundle</h2>"
                      "<span class=sub>proporção precoce (≤3 meses) × tardio — churn precoce = problema de onboarding/expectativa, não de entrega · nº à direita = saídas com dado</span></div>"
                      + card(emp + _vz_det2(tbl("<tr>" + "".join(f"<th style='text-align:{al};padding:7px;border-bottom:1px solid var(--border-strong);color:var(--text-muted);font-size:var(--fs-2xs);text-transform:uppercase'>{h}</th>" for h, al in (("Bundle", "left"), ("Saídas c/ dado", "right"), ("Mediana", "right"), ("≤3 meses", "right"))) + "</tr>", tc_rows),
                                            "ver tabela (mediana de tempo de casa)")) + "</section>")

    return (
        "<div class=page-head><h1>Cancelamentos</h1>"
        "<span class=role-chip>fonte: planilhas do time (Saídas de Clientes + Bonificação Squads)</span></div>"
        + form_filtro + kpis + taxa_html + evolucao_html +
        f"<section><div class=sec-head><h2>Fila de retenção — clientes em tratativa</h2>"
        f"<span class=sub>saída ainda NÃO formalizada: é aqui que a retenção acontece</span></div>"
        + card(tbl(f"<tr>{th_t}</tr>", linhas_t) if linhas_t else "<span class=note>nenhuma tratativa aberta registrada</span>") +
        "</section>"
        f"<section><div class=sec-head><h2>Saídas por mês</h2><span class=sub>cancelamentos formalizados · términos de contrato START contados à parte</span></div>"
        + card(tbl(th, linhas_m)) + "</section>"
        "<section><div class=sec-head><h2>Por plano e por equipe</h2><span class=sub>todo o período das planilhas (dez-2025 em diante)</span></div>"
        "<div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px'>"
        + card(grupo("plano", "Plano")) + card(grupo("equipe", "Equipe/Squad")) + "</div></section>"
        + tempo_html +
        f"<section><div class=sec-head><h2>Motivos informados</h2><span class=sub>{len(com_motivo)} saídas com motivo registrado — Pareto dos motivos (o nº1 é o playbook prioritário); casos recentes na tabela recolhida</span></div>"
        + card(_pareto_motivos(com_motivo)
               + _vz_det_m(
                   tbl("<tr>" + "".join(f"<th style='text-align:left;padding:7px;border-bottom:1px solid var(--border-strong);color:var(--text-muted);font-size:var(--fs-2xs);text-transform:uppercase'>{h}</th>" for h in ("Mês", "Cliente", "Plano", "Motivo")) + "</tr>", linhas_mo),
                   "ver os 15 casos mais recentes (cliente e plano)")) +
        "</section>"
        "<p class=note style='margin-top:14px'>Duas réguas conciliadas: as ABAS MENSAIS (listas operacionais, histórico completo "
        "incl. ADS/ASS antigos) + a aba CONSOLIDADA do processo anti-churn (mar/26+, status oficial) — cliente marcado "
        "<b>Revertido</b>/<b>Em negociação</b> na consolidada não conta como saída aqui. "
        "Términos START têm semântica própria (fim de contrato, não churn de assinatura). Releitura diária via link público.</p>")


def _relatorios_content(rep: dict, scores: list[dict]) -> str:
    sev = rep["alertas"]

    def block(title, sub, inner):
        return (f"<section><div class=sec-head><h2>{title}</h2><span class=sub>{sub}</span></div>"
                f"<div style='{_CARD}'>{inner}</div></section>")

    def dl(pairs):
        return "".join(
            f"<div style='display:flex;justify-content:space-between;padding:6px 0;"
            f"border-bottom:1px solid var(--border);font-size:var(--fs-sm)'>"
            f"<span style='color:var(--text-muted)'>{escape(str(k))}</span><b>{escape(str(v))}</b></div>"
            for k, v in pairs)

    resumo = dl([
        ("Contas monitoradas", rep["monitoradas"]),
        ("Avaliáveis", rep["avaliaveis"]), ("Sem dados (revisar manual)", rep["sem_dados"]),
        ("Alertas abertos", f"{rep['alertas_total']}  (crítico {sev.get('critico', 0)} · alto {sev.get('alto', 0)} · atenção {sev.get('atencao', 0)})"),
        ("MRR em risco", _fmt_brl(rep["mrr_risco"])), ("MRR em risco crítico", _fmt_brl(rep["mrr_critico"])),
        ("Execução crítica (ClickUp)", f"{rep['exec_atrasada']} contas"),
    ])
    piores = dl([(f"{i}. {p['nome'][:44]}", f"{p['score']:.1f} · {_STAGE_LABEL.get(p['estagio'], p['estagio'])}"
                  + (f" · {_fmt_brl(p['mrr'])}" if p.get("mrr") else ""))
                 for i, p in enumerate(rep["piores"], 1)])
    dists = _dist_html(rep)

    return (
        "<div class=page-head><h1>Relatórios</h1>"
        "<span class=role-chip>estado atual — mesma base do envio ao Slack</span></div>"
        "<p class=note style='margin-top:14px;display:flex;align-items:center;gap:12px;flex-wrap:wrap'>"
        "<button id=slackbtn onclick=\"sendSlack()\" style='cursor:pointer;background:var(--brand);"
        "color:var(--brand-ink);border:none;border-radius:var(--radius-sm);font-family:var(--font-body);"
        "font-weight:600;font-size:var(--fs-sm);padding:8px 14px'>Enviar ao Slack agora</button>"
        "<span id=slackmsg style='font-size:var(--fs-sm);color:var(--text-muted)'>"
        "posta este resumo no grupo dos gestores (webhook do .env)</span></p>"
        "<script>function sendSlack(){var b=document.getElementById('slackbtn'),m=document.getElementById('slackmsg');"
        "b.disabled=true;m.textContent='enviando…';"
        "fetch('/api/reports/send-slack',{method:'POST'}).then(function(r){return r.json().then(function(j){return [r.ok,j];});})"
        ".then(function(x){m.textContent=x[0]?'enviado ao grupo ✓':(x[1].error||'falha no envio');b.disabled=false;})"
        ".catch(function(){m.textContent='falha de rede';b.disabled=false;});}</script>"
        + _assessoria_block(scores)
        # Relatório de Churn por Bundle (Otávio 20/07: dossiê do caso B3
        # produtizado — gerado sob demanda p/ qualquer bundle)
        + ("<section><div class=sec-head><h2>Relatório de Churn por Bundle"
           + _hint("Relatório de Churn por Bundle",
                   "O que mostra: o dossiê completo do churn de um plano — o número em contexto (taxa da "
                   "janela vs média histórica), o padrão de RELACIONAMENTO da equipe no WhatsApp antes de "
                   "cada pedido (respostas em 24h, quem inicia a conversa, silêncios longos) contra um grupo "
                   "de controle saudável, o padrão de ENTREGA no ClickUp (30 dias pré-pedido vs a média da "
                   "própria conta), os casos um a um e o churn precoce por canal de aquisição.\n"
                   "Como ler: é um documento imprimível (Exportar/Imprimir vira PDF) pensado para levar a "
                   "uma conversa de diretoria. Ressalvas aparecem SEMPRE junto do número — amostra pequena, "
                   "análise de mensagens parcial, motivo não preenchido.\n"
                   "Fique de olho: a primeira geração leva alguns minutos (mensagens do WhatsApp); depois "
                   "fica em cache por 20h — Regerar força a análise de novo. Associação não é causa "
                   "comprovada: use como pauta de investigação e ação, não como veredito.")
           + "</h2><span class=sub>dossiê apresentável por plano — casos, relacionamento, entrega e canal</span></div>"
           f"<div style='{_CARD}'><div style='display:flex;gap:10px;align-items:center;flex-wrap:wrap'>"
           + "".join(f"<a href='/growth/churn-report?b={x}' target=_blank rel=noopener "
                     "style='display:inline-block;padding:8px 18px;border-radius:999px;font-weight:600;"
                     "font-size:var(--fs-sm);background:var(--surface-2);color:var(--text);"
                     "border:1px solid var(--border-strong);text-decoration:none'>"
                     f"Gerar {x}</a>" for x in ("B1", "B2", "B3", "B4", "B5"))
           + "<span class=note style='margin-left:6px'>abre em nova aba · 1ª geração demora alguns minutos "
             "(mensagens); depois é instantâneo (cache 20h)</span></div></div></section>")
        + block("Resumo executivo", _fmt_date_br(rep["data"]), resumo)
        + block("Piores contas", "menor score = pior; MRR quando conhecido", piores)
        + block("Distribuições", "faixa · estágio · trajetória", dists)
        # análise por squad MUDOU de aba (unificação 15/07): ranking + insights
        # + carga + capacidade agora vivem juntos em 'Análise dos Squads'
        + "<p class=note style='margin-top:14px'>A <b>análise por squad</b> (ranking, pontos fortes/fracos e "
          "plano de ação por time) agora vive na aba <a href='/growth?view=carga' "
          "style='color:var(--brand)'>Análise dos Squads</a>, junto com carga e capacidade.</p>")


# ---------------------------------------------------------------------------
# Relatório mensal de assessoria (endpoints + página /growth/report).
# Incluído por ÚLTIMO: a rota genérica GET /api/reports/{report_id} não pode
# capturar as rotas fixas /api/reports/summary e /send-slack definidas acima
# (FastAPI casa na ordem de registro). Import tardio evita ciclo.
from .report_api import router as _report_router  # noqa: E402
from .churn_report import router as _churn_router  # noqa: E402
from .allhands import router as _allhands_router  # noqa: E402
from .financeiro.ui import router as _financeiro_router  # noqa: E402
from .marketing.ui import router as _marketing_router  # noqa: E402
from .operacoes.ui import router as _operacoes_router  # noqa: E402
from .raiox import router as _raiox_router  # noqa: E402
from .sales.ui import router as _sales_router  # noqa: E402
from .semana import router as _semana_router  # noqa: E402

app.include_router(_report_router)
app.include_router(_churn_router)
app.include_router(_marketing_router)
app.include_router(_sales_router)
app.include_router(_operacoes_router)
app.include_router(_financeiro_router)
app.include_router(_allhands_router)
app.include_router(_raiox_router)
app.include_router(_semana_router)

# frontend React (migração rota a rota — ver app/spa.py); registrado por
# ÚLTIMO para nunca sombrear rotas existentes: só atende /app + SPA_ROUTES
from . import spa as _spa  # noqa: E402

_spa.install(app)
