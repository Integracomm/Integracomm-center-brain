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
  <input type=text name=user placeholder="adm@integracomm.com.br" autofocus autocomplete=username>
  <label>senha</label>
  <input type=password name=password autocomplete=current-password>
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
  </select>
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
    with conn.cursor() as cur:
        cur.execute("ALTER TABLE alerts ADD COLUMN IF NOT EXISTS notes TEXT")  # idempotente
        cur.execute(
            """SELECT al.id, a.name, al.severity, al.risk_band, al.stage, al.created_at,
                      al.status, al.notes
                 FROM alerts al JOIN accounts a ON a.id = al.account_id
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
    _user, role = _require_api(request)
    with _conn() as c:
        return {"agents": _visible_agents(role), "scores": _serialize(_latest_scores(c))}


@app.get("/api/alerts")
def api_alerts(request: Request):
    _require_api(request)
    with _conn() as c:
        return {"alerts": _serialize(_open_alerts(c))}


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
        return RedirectResponse("/growth", status_code=302)
    with _conn() as c:
        _audit_view(c, user, scope="hub")
        stats = _hub_stats(c)
        mkt = _hub_mkt_stats(c)
        users = list_users(c)
    return HTMLResponse(_render_hub(user, stats, users, mkt))


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
    if view not in ("contas", "alertas", "playbooks", "relatorios"):
        view = "contas"
    with _conn() as c:
        _audit_view(c, user, scope=f"growth/{view}")
        scores = _latest_scores(c)
        alerts = _open_alerts(c)
        practices = _top_practices(c)
        interventions = _recent_interventions(c) if view == "playbooks" else None
    return HTMLResponse(_render(role, scores, alerts, practices, view=view,
                                interventions=interventions))


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
        cur.execute("""SELECT count(DISTINCT s.account_id) FROM signal_snapshots s
                       WHERE s.signal_key='exec_score' AND s.value_num < 70""")
        exec_late = cur.fetchone()[0]
    return {"monitored": monitored, "evaluable": evaluable, "sev": sev,
            "mrr_risk": mrr_risk, "mrr_crit": mrr_crit, "non_eval": non_eval,
            "exec_late": exec_late}


def _hub_mkt_stats(conn: Any) -> dict | None:
    """Resumo do mês corrente da área de Marketing p/ o hub — realizado (coorte
    Pipedrive + gasto de mídia) × plano da planilha de metas (mkt_plan_*)."""
    try:
        from .marketing.ui import _coorte, _dias_mes, _plan_funil
        hoje = dt.date.today()
        mes = hoje.replace(day=1)
        plan = _plan_funil(conn, [mes]).get(mes) or {}
        passou, booked, total = _coorte(conn, mes, hoje)
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
                "cpl_alvo": (plan.get("Lead") or {}).get("custo")}
    except Exception:  # noqa: BLE001 — marketing sem cache não derruba o hub
        return None


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


def _render_hub(role: str, st: dict, users: list[dict] | None = None,
                mkt: dict | None = None) -> str:
    n_alerts = sum(st["sev"].values())
    crit = st["sev"].get("critico", 0)
    # Iniciativas sugeridas pela inteligência central — derivadas dos dados
    # reais das áreas ativas (Growth + Marketing) = priorização cross-área.
    initiatives = []
    if crit:
        initiatives.append(("Reter as contas em risco crítico",
                            f"{crit} contas sinalizaram saída ou estão em faixa crítica — "
                            f"{_fmt_brl(st['mrr_crit'])} de MRR em jogo. Fila pronta na área de Growth.",
                            "--status-critico"))
    if mkt and mkt.get("book_meta") and mkt["book"] / mkt["book_meta"] < mkt["frac"] * 0.75:
        initiatives.append(("Destravar bookings do mês",
                            f"{mkt['book']} de {mkt['book_meta']:.0f} bookings da meta com "
                            f"{mkt['frac'] * 100:.0f}% do mês decorrido — ver etapa de maior perda no "
                            "Funil de Prospecção e o gap por plano.",
                            "--status-critico"))
    if mkt and mkt.get("leads_meta") and mkt["leads"] / mkt["leads_meta"] < mkt["frac"] * 0.75:
        initiatives.append(("Acelerar a geração de leads",
                            f"{mkt['leads']} de {mkt['leads_meta']:.0f} leads da meta do mês com "
                            f"{mkt['frac'] * 100:.0f}% do mês decorrido — revisar campanhas e verba "
                            "na aba Metas do Semestre.",
                            "--status-alto"))
    if st["exec_late"]:
        initiatives.append(("Regularizar execução nas contas em alerta",
                            f"{st['exec_late']} contas monitoradas têm entregas atrasadas no ClickUp — "
                            "atrito operacional que alimenta a insatisfação.",
                            "--status-alto"))
    if st["non_eval"]:
        initiatives.append(("Recuperar cobertura de dados",
                            f"{st['non_eval']} contas sem conversa suficiente no WhatsApp — o agente não as "
                            "enxerga; revisar manualmente e reativar os grupos.",
                            "--status-semdados"))
    init_html = "".join(
        f"<div class='init'><span class='sdot' style='--c:var({var})'></span>"
        f"<div><div class='it'>{escape(t)}</div><div class='id_'>{escape(d)}</div></div></div>"
        for t, d, var in initiatives
    ) or "<div class='init'><div class='id_'>sem iniciativas pendentes</div></div>"

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

    g_det = (f"{crit} críticos · {st['sev'].get('alto', 0)} altos · "
             f"{st['sev'].get('atencao', 0)} atenção · {st['non_eval']} sem cobertura")
    growth_card = (
        "<a class='area big' href='/growth'><div class=ahead>"
        f"<div class=an>Growth / Assessoria</div>{_chip('ativa', '--status-baixo')}</div>"
        "<div class=agrid>"
        + am(_num(st["monitored"]), "contas monitoradas")
        + am(_num(n_alerts), "alertas abertos", "var(--status-critico)" if n_alerts else None)
        + am(_fmt_brl(st["mrr_risk"]), "MRR em risco", "var(--status-alto)" if st["mrr_risk"] else None)
        + am(_num(st["exec_late"]), "execução atrasada", "var(--status-medio)" if st["exec_late"] else None)
        + f"</div><div class=ad>{escape(g_det)}</div></a>")

    if mkt:
        v_leads, c_leads = vs_meta(mkt["leads"], mkt.get("leads_meta"), mkt["frac"])
        v_oport, c_oport = vs_meta(mkt["oport"], mkt.get("oport_meta"), mkt["frac"])
        v_book, c_book = vs_meta(mkt["book"], mkt.get("book_meta"), mkt["frac"])
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
                 + cpl_txt + " · metas da planilha do time")
        mkt_card = (
            "<a class='area big' href='/marketing'><div class=ahead>"
            f"<div class=an>Marketing</div>{_chip('ativa', '--status-baixo')}</div>"
            "<div class=agrid>"
            + am(v_leads, "leads no mês", c_leads)
            + am(v_oport, "oportunidades", c_oport)
            + am(v_book, "bookings", c_book)
            + am(gasto_txt, "gasto mídia/verba", c_gasto)
            + f"</div><div class=ad>{escape(m_det)}</div></a>")
    else:
        mkt_card = ("<a class='area big' href='/marketing'><div class=ahead>"
                    f"<div class=an>Marketing</div>{_chip('ativa', '--status-baixo')}</div>"
                    "<div class=ad>tráfego pago, leads, funil e planejador — sem cache do mês "
                    "(rode o sync de marketing)</div></a>")

    area_cards = growth_card + mkt_card + "".join(
        "<div class='area soon'>"
        + f"<div class='an'>{escape(nm)}</div>"
        + f"<div class='ast'>{_chip('em breve', '--status-semdados')}</div>"
        + f"<div class='ad'>{escape(desc)}</div></div>"
        for nm, desc in (("Pré-vendas", "qualificação e conversão"),
                         ("Financeiro", "inadimplência e margem"),
                         ("Operações", "capacidade e SLA"))
    )

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
    if len(kpis) == 3:
        kpis.append(("2<span style='color:var(--text-faint);font-size:18px'>/5</span>",
                     "Áreas ativas", None))
    kpi_html = "".join(
        f"<div class=kpi><div class=n{f' style=\"color:{c}\"' if c else ''}>{v}</div>"
        f"<div class=l>{lbl}</div></div>" for v, lbl, c in kpis)

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
.rail-foot{padding:12px 16px;border-top:1px solid var(--border);font-size:var(--fs-2xs);color:var(--text-muted);line-height:1.5}
main{flex:1;min-width:0;padding:26px 32px 48px;max-width:var(--content-max)}
h1{font-family:var(--font-display);font-weight:700;font-size:var(--fs-h1);letter-spacing:var(--tracking-tight);margin:0}
.sub{font-size:var(--fs-sm);color:var(--text-muted);margin-top:6px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-top:22px}
.kpi{background:var(--surface-1);border:1px solid var(--border-mid);border-radius:var(--radius-md);padding:16px 18px}
.kpi .n{font-family:var(--font-display);font-weight:700;font-size:28px;line-height:1}
.kpi .l{font-size:var(--fs-2xs);color:var(--text-muted);text-transform:uppercase;letter-spacing:var(--tracking-label);margin-top:8px}
section{margin-top:var(--space-8)}
h2{font-family:var(--font-display);font-weight:600;font-size:var(--fs-lg);margin:0 0 4px}
.secsub{font-size:var(--fs-sm);color:var(--text-muted);margin:0 0 14px}
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
.init{display:flex;gap:10px;align-items:flex-start;padding:10px 0;border-top:1px solid var(--border)}
.init:first-child{border-top:none;padding-top:0}
.init .sdot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--c);margin-top:5px;flex-shrink:0}
.it{font-weight:var(--fw-semibold);font-size:var(--fs-md)}
.id_{font-size:var(--fs-sm);color:var(--text-muted);line-height:1.5;margin-top:2px}
.foot{font-size:var(--fs-xs);color:var(--text-faint);margin-top:24px}
</style></head><body>
<div class=app>
 <aside class=rail>
   <div class=brand><div class=logo></div><div><div class=bt>Integracomm IA</div><div class=bs>Central</div></div></div>
   <nav>
     <a class="nav-item active" href="/">Início</a>
     <a class="nav-item" href="/growth">Growth / Assessoria</a>
     <a class="nav-item" href="/marketing">Marketing</a>
     <a class="nav-item soon">Pré-vendas <span class=tag>em breve</span></a>
     <a class="nav-item soon">Financeiro <span class=tag>em breve</span></a>
     <a class="nav-item soon">Operações <span class=tag>em breve</span></a>
   </nav>
   <div class=rail-foot>papel: <b>__ROLE__</b> · <a href="/logout" style="color:var(--text-muted);text-decoration:underline">sair</a><br>humano no loop — a IA só sinaliza</div>
 </aside>
 <main>
  <h1>Visão central</h1>
  <p class=sub>A inteligência central consolida os sinais de todas as áreas e sugere iniciativas alinhadas entre elas. Hoje 2 de 5 áreas estão ativas (Growth e Marketing); as demais entram como novos agentes na mesma casca.</p>
  <div class=kpis>__KPIS__</div>
  <section>
    <h2>Iniciativas sugeridas</h2>
    <p class=secsub>derivadas dos sinais das áreas ativas — priorização da empresa, não de uma área só</p>
    <div class=central>__INITS__</div>
  </section>
  <section>
    <h2>Áreas</h2>
    <p class=secsub>resumo do andamento de cada área — clique para abrir o painel completo; verde = no ritmo/meta, vermelho = atenção</p>
    <div class=areas>__AREAS__</div>
  </section>
  <section>
    <h2>Contas de acesso</h2>
    <p class=secsub>cadastros feitos na tela de login — pendentes primeiro; aprovar libera o acesso à área de Growth</p>
    <div class=central>__USERS__</div>
  </section>
  <p class=foot>Derivados do Postgres próprio (LGPD: sem conteúdo bruto). A IA calcula, exibe e sinaliza — a decisão é sempre humana.</p>
 </main>
</div>
</body></html>"""
    return (head.replace("__TOKENS__", _tokens_css()).replace("__ROLE__", escape(role))
            .replace("__KPIS__", kpi_html)
            .replace("__INITS__", init_html).replace("__AREAS__", area_cards)
            .replace("__USERS__", _users_html(users or [])))


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
    (em dia / atenção / atrasada); nota 0-100 e motivo ficam no hover."""
    v = s.get("exec_score")
    if v is None:
        return _DASH
    if v >= 70:
        var, txt = "--status-baixo", "em dia"
    elif v >= 40:
        var, txt = "--status-medio", "atenção"
    else:
        var, txt = "--status-critico", "atrasada"
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


def _render(role: str, scores: list[dict], alerts: list[dict],
            practices: dict | None = None, view: str = "contas",
            interventions: list | None = None) -> str:
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
        score_cell = (f"<span class='score'>{float(s['score']):.1f}</span>" if ev
                      else "<span style='color:var(--text-faint)'>s/ dados</span>")
        mot = reason_txt(s)
        mot_line = f"<div class='mot'>{mot}</div>" if mot else ""
        stage_dot = (f"<span class='sdot' style='--c:var({_SEV_VAR.get(sev,'--status-semdados')})'></span>"
                     if sev != "sem" else "")
        return (
            f"<div class='row acct' data-name=\"{escape(s['name'].lower())}\" data-band=\"{band}\" "
            f"data-alert=\"{sev}\" data-stage=\"{stage_key}\" data-squad=\"{sq}\" data-mrr=\"{mrr:.0f}\">"
            f"<div class='c-name'><div class='nm'>{escape(s['name'][:60])}</div>{mot_line}"
            f"<a class='repbtn' href='/growth/report?account_id={s['account_id']}' "
            f"title='Relatório mensal de assessoria (mês anterior; gerado na hora)'>Relatório</a></div>"
            f"<div class='c-score'>{score_cell}</div>"
            f"<div>{_chip(band, _BAND_VAR.get(band, '--status-semdados'))}</div>"
            f"<div class='c-stage'>{stage_dot}{escape(_STAGE_LABEL.get(stage_key, stage_key))}</div>"
            f"<div class='c-squad' title=\"{escape(_tag(s['name']))}\">{escape(sq)}</div>"
            f"<div class='c-mrr'>{_mrr_txt(s)}</div>"
            f"<div>{_exec_badge(s)}</div>"
            f"<div class='guide c-full'>{escape(_guide(s, practices))}</div>"
            f"</div>"
        )

    rows = "".join(row(s) for s in ordered)
    def _alert_row(a: dict) -> str:
        nota = ""
        if a.get("notes"):
            ultima = str(a["notes"]).strip().splitlines()[-1]
            nota = f"<div class='mot'>{escape(ultima[:120])}</div>"
        aid = a.get("id")
        return (
            f"<div class='row arow'><div class='c-name'><div class='nm'>{escape(a['name'][:60])}</div>{nota}</div>"
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
section{margin-top:var(--space-8)}
.sec-head{display:flex;align-items:baseline;gap:10px;margin-bottom:10px}
.sec-head h2{font-family:var(--font-display);font-weight:600;font-size:var(--fs-lg);margin:0}
.sec-head .sub{font-size:var(--fs-sm);color:var(--text-muted)}
.note{font-size:var(--fs-sm);color:var(--text-muted);margin:0 0 10px}
.note b{color:var(--text-2)}
/* --- tabelas em grid --- */
.tbl{background:var(--surface-1);border:1px solid var(--border-mid);border-radius:var(--radius-md);overflow-x:auto}
.row{display:grid;align-items:center;gap:12px;padding:10px 16px}
.thead{background:var(--surface-2);color:var(--text-muted);font-size:var(--fs-2xs);text-transform:uppercase;letter-spacing:var(--tracking-label);font-weight:var(--fw-semibold)}
.arow{border-top:1px solid var(--border);align-items:start}
/* cada CLIENTE é um bloco (dados + diretriz) separado por uma linha nítida */
.acct{border-top:1px solid var(--border-strong);align-items:start;padding:13px 16px}
.acct:hover,.arow:hover{background:var(--surface-2)}
.tbl-alerts .row{grid-template-columns:minmax(260px,1fr) 120px 170px 90px 230px}
.c-acts{display:flex;gap:6px;flex-wrap:wrap}
.abtn{cursor:pointer;background:var(--surface-3);border:1px solid var(--border-strong);border-radius:var(--radius-sm);color:var(--text-2);font-family:var(--font-body);font-size:var(--fs-2xs);padding:4px 9px}
.abtn:hover{border-color:var(--brand);color:var(--brand)}
/* contas: 7 colunas que CABEM na página (sem scroll lateral); a diretriz ocupa
   a largura inteira numa 2ª linha da mesma conta */
.tbl-acct .row{grid-template-columns:minmax(200px,1fr) 66px 96px 150px 78px 96px 100px;row-gap:9px}
/* colunas 2–7 (Score..Execução) centralizadas — cabeçalho e linhas */
.tbl-acct .row>div:nth-child(n+2):nth-child(-n+7){text-align:center}
.c-full{grid-column:1/-1}
.pager{display:flex;align-items:center;gap:10px;justify-content:flex-end;margin-top:10px}
.pager button{cursor:pointer;background:var(--surface-3);border:1px solid var(--border-strong);border-radius:var(--radius-sm);color:var(--text-2);padding:6px 12px;font-size:var(--fs-sm)}
.pager button:disabled{opacity:.4;cursor:default}
.pager .pginfo{font-size:var(--fs-sm);color:var(--text-muted)}
.nm{font-weight:var(--fw-semibold);font-size:var(--fs-md);line-height:1.3}
.mot{font-size:var(--fs-2xs);color:var(--text-muted);margin-top:3px;line-height:1.4}
.score{font-family:var(--font-display);font-weight:700;font-size:15px}
.c-mrr{color:var(--text-2);font-variant-numeric:tabular-nums}
.c-squad{color:var(--text-muted);font-size:var(--fs-sm)}
.c-stage{color:var(--text-2);font-size:var(--fs-sm)} .c-status{color:var(--text-muted);font-size:var(--fs-sm)}
.sdot{display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--c);margin-right:6px;vertical-align:middle}
.guide{font-size:var(--fs-sm);color:var(--text-2);line-height:1.5;background:color-mix(in srgb,var(--brand) 5%,transparent);border-left:2px solid color-mix(in srgb,var(--brand) 35%,transparent);border-radius:var(--radius-xs);padding:7px 10px}
.repbtn{display:inline-block;margin-top:6px;font-size:var(--fs-2xs);font-weight:var(--fw-semibold);color:var(--text-2);background:var(--surface-3);border:1px solid var(--border-strong);border-radius:var(--radius-sm);padding:3px 9px;text-decoration:none}
.repbtn:hover{border-color:var(--brand);color:var(--brand)}
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
   <div class=rail-foot>papel: <b>__ROLE__</b> · <a href="/logout" style="color:var(--text-muted);text-decoration:underline">sair</a><br>humano no loop — o agente só sinaliza</div>
 </aside>
 <main>__CONTENT__</main>
</div>
__SCRIPT__
</body></html>"""

    # ---- navegação (view ativa; sessão define o papel — sem role na URL) ----
    nav = "<a class='nav-item' href='/'>← Início (central)</a>"
    for v, label in (("contas", "Contas"), ("alertas", "Alertas"),
                     ("playbooks", "Playbooks"), ("relatorios", "Relatórios")):
        cls = "nav-item active" if v == view else "nav-item"
        nav += f"<a class='{cls}' href='/growth?view={v}'>{label}</a>"
    nav += "<a class='nav-item soon'>Configurações <span class=tag>em breve</span></a>"

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
            f"</div><section>{alerts_tbl}"
            "<div class=pager><button id=pa-prev onclick='paGo(-1)'>‹ anterior</button>"
            f"<span class=pginfo id=painfo></span><span class=count>total: <b>{len(alerts)}</b></span>"
            "<button id=pa-next onclick='paGo(1)'>próxima ›</button></div>"
            "</section>" + foot)
        script = _ALERTS_JS
    elif view == "playbooks":
        content = _playbooks_content(practices or {}, interventions or []) + foot
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
            "<b>Execução</b> = situação das entregas no ClickUp — em dia / atenção / atrasada "
            "(nota e motivo no hover). A <b>diretriz de ação</b> aparece destacada sob cada conta.</p>"
            "<div class=filters>"
            "<div class=grp><label>buscar nome</label><input id=f-name placeholder='cliente…' oninput='applyF()'></div>"
            "<div class=grp><label>faixa</label><select id=f-band onchange='applyF()'><option value=''>todas</option><option value='baixo'>verde (baixo)</option><option value='medio'>amarelo (médio)</option><option value='alto'>laranja (alto)</option><option value='critico'>vermelho (crítico)</option><option value='sem_dados'>sem dados</option></select></div>"
            "<div class=grp><label>alerta</label><select id=f-alert onchange='applyF()'><option value=''>todos</option><option value='critico'>crítico</option><option value='alto'>alto</option><option value='atencao'>atenção</option><option value='sem'>sem alerta</option></select></div>"
            "<div class=grp><label>estágio</label><select id=f-stage onchange='applyF()'><option value=''>todos</option><option value='saudavel'>saudável</option><option value='desengajamento_inicial'>desengajamento</option><option value='insatisfacao_latente'>insatisfação latente</option><option value='insatisfacao_ativa'>insatisfação ativa</option><option value='intencao_de_saida'>intenção de saída</option><option value='nao_avaliavel'>não avaliável</option></select></div>"
            f"<div class=grp><label>squad</label><select id=f-squad onchange='applyF()'><option value=''>todos</option>{squad_opts}</select></div>"
            "<div class=grp><label>MRR mínimo (R$)</label><input id=f-mrr type=number min=0 step=100 placeholder='ex.: 3000' oninput='applyF()'></div>"
            "<button id=clearf onclick='clearF()'>limpar</button>"
            f"<span class=count>mostrando <b id=vis>0</b> de {len(ordered)}</span>"
            "</div>"
            "<div class='tbl tbl-acct'>"
            "<div class='row thead'><div>Conta / motivos</div><div class=c-score>Score</div><div>Faixa</div><div>Estágio</div><div>Serviço-Squad</div><div class=c-mrr>MRR</div><div>Execução</div></div>"
            + rows + "</div>"
            "<div class=pager><button id=pg-prev onclick='pgGo(-1)'>‹ anterior</button>"
            "<span class=pginfo id=pginfo></span>"
            "<button id=pg-next onclick='pgGo(1)'>próxima ›</button></div>"
            + foot + "</section>")
        script = _CONTAS_JS

    return (head.replace("__TOKENS__", _tokens_css())
            .replace("__NAV__", nav).replace("__ROLE__", escape(role))
            .replace("__CONTENT__", content).replace("__SCRIPT__", script))


_CONTAS_JS = """<script>
var PAGE=10, page=1;
function _match(d,f){
  return (!f.n||d.name.indexOf(f.n)>=0)&&(!f.b||d.band===f.b)&&(!f.a||d.alert===f.a)
    &&(!f.st||d.stage===f.st)&&(!f.sq||d.squad===f.sq)&&(parseFloat(d.mrr)>=f.mrr);
}
function renderRows(){
  var f={n:document.getElementById('f-name').value.toLowerCase().trim(),
    b:document.getElementById('f-band').value, a:document.getElementById('f-alert').value,
    st:document.getElementById('f-stage').value, sq:document.getElementById('f-squad').value,
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
function clearF(){['f-name','f-band','f-alert','f-stage','f-squad','f-mrr'].forEach(function(i){document.getElementById(i).value='';});applyF();}
if(document.getElementById('f-name'))applyF();
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
        f"• Execução atrasada (ClickUp): {rep['exec_atrasada']} contas",
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
    Só entram os squads da PLANILHA de composição; contas sem squad conhecido
    ficam de fora (contadas à parte). Retorna (análise, n_sem_squad)."""
    import statistics as st
    from collections import Counter

    try:
        from .sources.clickup_activities import _mirror_clientes
        mirror = _mirror_clientes()
    except Exception:  # noqa: BLE001 — sem espelho, resolve só pelo nome
        mirror = None

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
        # pontos fortes/fracos por dimensão
        fortes, fracos = [], []
        (fortes if (rel or 0) >= 60 else fracos).append(
            f"relacionamento (score médio {rel:.0f})" if rel is not None else "relacionamento (sem dados)")
        if exe is not None:
            (fortes if exe >= 70 else fracos).append(f"execução (média {exe:.0f}/100)")
        (fortes if risco_pct <= 0.35 else fracos).append(f"risco ({n_alert} de {len(contas)} contas em alerta)")
        if caindo_pct > 0.3:
            fracos.append(f"trajetória ({caindo_pct * 100:.0f}% das contas piorando)")
        # plano de ação: das dimensões mais fracas + dor dominante
        acoes = []
        if dor and dor in _SQUAD_ACAO:
            acoes.append(_SQUAD_ACAO[dor])
        if exe is not None and exe < 70 and _SQUAD_ACAO["execucao"] not in acoes:
            acoes.append(_SQUAD_ACAO["execucao"])
        if caindo_pct > 0.3:
            acoes.append(_SQUAD_ACAO["trajetoria"])
        if not acoes:
            acoes.append("Squad saudável: manter a rotina e documentar as práticas que funcionam — "
                         "elas viram referência de playbook para os squads abaixo no ranking.")
        out.append({"squad": sq, "n": len(contas), "score": composto, "rel": rel, "exe": exe,
                    "risco_pct": risco_pct, "n_alert": n_alert, "caindo_pct": caindo_pct,
                    "dor": dor, "drivers": drivers, "fortes": fortes, "fracos": fracos,
                    "acoes": acoes,
                    "mrr_risco": sum(_mrr_val(s) for s in contas if s.get("alert_sev") and _mrr_val(s) > 0)})
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
        ("Execução atrasada (ClickUp)", f"{rep['exec_atrasada']} contas"),
    ])
    piores = dl([(f"{i}. {p['nome'][:44]}", f"{p['score']:.1f} · {_STAGE_LABEL.get(p['estagio'], p['estagio'])}"
                  + (f" · {_fmt_brl(p['mrr'])}" if p.get("mrr") else ""))
                 for i, p in enumerate(rep["piores"], 1)])
    dists = dl([("— Faixa —", "")] + sorted(rep["faixa"].items(), key=lambda x: -x[1])
               + [("— Estágio —", "")] + sorted(rep["estagio"].items(), key=lambda x: -x[1])
               + [("— Trajetória —", "")] + sorted(rep["trajetoria"].items(), key=lambda x: -x[1]))
    _squad_an, _sem_squad = _squad_analysis(scores)
    squads_html = _squads_html(_squad_an, _sem_squad)

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
        + block("Resumo executivo", _fmt_date_br(rep["data"]), resumo)
        + block("Piores contas", "menor score = pior; MRR quando conhecido", piores)
        + block("Distribuições", "faixa · estágio · trajetória", dists)
        + "<section><div class=sec-head><h2>Análise por squad</h2>"
          "<span class=sub>score composto (50% relacionamento · 25% execução · 25% risco), "
          "ranking, dores dominantes e plano de ação por equipe</span></div>"
        + squads_html + "</section>")


# ---------------------------------------------------------------------------
# Relatório mensal de assessoria (endpoints + página /growth/report).
# Incluído por ÚLTIMO: a rota genérica GET /api/reports/{report_id} não pode
# capturar as rotas fixas /api/reports/summary e /send-slack definidas acima
# (FastAPI casa na ordem de registro). Import tardio evita ciclo.
from .report_api import router as _report_router  # noqa: E402
from .marketing.ui import router as _marketing_router  # noqa: E402

app.include_router(_report_router)
app.include_router(_marketing_router)
