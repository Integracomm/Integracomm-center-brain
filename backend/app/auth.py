"""Login + RBAC do painel — sessão por cookie HMAC-assinado.

Duas camadas de usuário:
  1. BOOTSTRAP (.env): `admin` e `gestor_growth` fixos — garantem acesso mesmo
     com o banco vazio (senhas geradas no 1º boot, nunca commitadas);
  2. MULTIUSUÁRIO (tabela `users`): gestores criam a própria conta na tela de
     login (nome, e-mail, senha com hash bcrypt), que nasce `pendente` e só
     entra depois que o ADMIN aprovar no hub. Papel padrão: gestor_growth.

Proteções para exposição pública: bcrypt nas senhas, rate-limit de tentativas
de login (5 falhas/5 min por usuário+IP → espera), cookie httponly (e `secure`
quando servido via HTTPS). Token = "user|role|expiry|hmac_sha256", TTL 12h,
verificação timing-safe.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
_ENV = _ROOT / ".env"
_TTL_SECONDS = 12 * 3600

# user -> role. O login canônico do admin é o E-MAIL; "admin" segue como alias
# (mesma senha). Chave da senha no .env por usuário em _PWD_KEY.
USERS: dict[str, str] = {
    "adm@integracomm.com.br": "admin",
    "admin": "admin",
    "gestor_growth": "gestor_growth",
}
_PWD_KEY: dict[str, str] = {
    "adm@integracomm.com.br": "AUTH_ADMIN_PASSWORD",
    "admin": "AUTH_ADMIN_PASSWORD",
    "gestor_growth": "AUTH_GESTOR_GROWTH_PASSWORD",
}
ROLE_HOME: dict[str, str] = {"admin": "/", "gestor_growth": "/growth",
                             "gestor_marketing": "/marketing",
                             "gestor_prevendas": "/prevendas", "gestor_vendas": "/vendas",
                             "gestor_operacoes": "/operacoes"}

# Áreas do produto (controle de acesso POR CONTA — admin marca no hub quais
# áreas cada conta enxerga). Chave = slug usado na coluna users.areas (csv).
AREAS: dict[str, str] = {"growth": "Growth / Assessoria", "marketing": "Marketing",
                         "vendas": "Vendas", "prevendas": "Pré-vendas",
                         "financeiro": "Financeiro", "operacoes": "Operações"}
AREA_HOME: dict[str, str] = {"growth": "/growth", "marketing": "/marketing",
                             "vendas": "/vendas", "prevendas": "/prevendas",
                             "operacoes": "/operacoes"}
_ROLE_AREAS: dict[str, set[str]] = {"admin": set(AREAS), "gestor_growth": {"growth"},
                                    "gestor_marketing": {"marketing"},
                                    "gestor_prevendas": {"prevendas"},
                                    "gestor_vendas": {"vendas"},
                                    "gestor_operacoes": {"operacoes"}}
COOKIE = "iasession"


def _load_env() -> None:
    if _ENV.exists():
        for line in _ENV.read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def ensure_auth() -> None:
    """Garante AUTH_SECRET e as senhas no ambiente; gera e grava no .env se faltar."""
    _load_env()
    missing: list[tuple[str, str]] = []
    if not os.environ.get("AUTH_SECRET"):
        missing.append(("AUTH_SECRET", secrets.token_hex(32)))
    for key in sorted(set(_PWD_KEY.values())):
        if not os.environ.get(key):
            missing.append((key, secrets.token_urlsafe(12)))
    if missing:
        with _ENV.open("a", encoding="utf-8") as f:
            f.write("\n# --- auth do painel (gerado no 1º boot; troque à vontade) ---\n")
            for k, v in missing:
                f.write(f"{k}={v}\n")
                os.environ[k] = v


def check_login(user: str | None, password: str | None) -> str | None:
    """Valida credenciais dos usuários de BOOTSTRAP (.env); retorna role ou None.
    Usuários do banco entram por `authenticate_db`. Timing-safe."""
    ensure_auth()
    u = (user or "").strip().lower()
    role = USERS.get(u)
    if not role:
        return None
    want = os.environ.get(_PWD_KEY[u], "")
    return role if want and hmac.compare_digest(password or "", want) else None


# --------------------------------------------------------------------------
# Multiusuário (tabela `users`) — cadastro com aprovação do admin
# --------------------------------------------------------------------------
_USERS_DDL = """
CREATE TABLE IF NOT EXISTS users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email         TEXT UNIQUE NOT NULL,          -- sempre minúsculo
    name          TEXT NOT NULL,
    password_hash TEXT NOT NULL,                 -- bcrypt
    role          TEXT NOT NULL DEFAULT 'gestor_growth',
    status        TEXT NOT NULL DEFAULT 'pendente',  -- pendente|aprovado|bloqueado
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    approved_by   TEXT,
    approved_at   TIMESTAMPTZ
);
ALTER TABLE users ADD COLUMN IF NOT EXISTS areas TEXT;  -- csv de slugs (ver AREAS)
"""
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def ensure_users_table(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute(_USERS_DDL)


def create_user(conn: Any, email: str, name: str, password: str,
                role: str = "gestor_growth") -> str | None:
    """Cria conta PENDENTE. Retorna mensagem de erro ou None (sucesso)."""
    import bcrypt

    email = (email or "").strip().lower()
    name = (name or "").strip()
    if role not in ("gestor_growth", "gestor_marketing", "gestor_prevendas",
                    "gestor_vendas", "gestor_operacoes"):
        return "área inválida"
    if not _EMAIL_RE.match(email):
        return "e-mail inválido"
    if len(name) < 2:
        return "informe seu nome"
    if len(password or "") < 8:
        return "senha muito curta (mínimo 8 caracteres)"
    if email in USERS:
        return "este e-mail já é um usuário do sistema"
    ensure_users_table(conn)
    h = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM users WHERE email=%s", (email,))
        if cur.fetchone():
            return "já existe uma conta com este e-mail"
        cur.execute("INSERT INTO users (email, name, password_hash, role) VALUES (%s,%s,%s,%s)",
                    (email, name, h, role))
    return None


def authenticate_db(conn: Any, email: str, password: str) -> tuple[str | None, str | None]:
    """(role, erro) para usuários do banco. role=None com erro explicativo quando
    a conta existe mas não pode entrar (pendente/bloqueada); (None, None) se não existe."""
    import bcrypt

    ensure_users_table(conn)
    email = (email or "").strip().lower()
    with conn.cursor() as cur:
        cur.execute("SELECT password_hash, role, status FROM users WHERE email=%s", (email,))
        row = cur.fetchone()
    if not row:
        return None, None
    pwd_hash, role, status = row
    if not bcrypt.checkpw((password or "").encode(), pwd_hash.encode()):
        return None, "senha incorreta"
    if status == "pendente":
        return None, "conta aguardando aprovação do administrador"
    if status != "aprovado":
        return None, "conta bloqueada — fale com o administrador"
    return role, None


def list_users(conn: Any) -> list[dict]:
    ensure_users_table(conn)
    with conn.cursor() as cur:
        cur.execute("""SELECT id, email, name, role, status, created_at, areas
                         FROM users ORDER BY (status='pendente') DESC, created_at DESC""")
        return [{"id": str(i), "email": e, "name": n, "role": r, "status": s,
                 "created_at": c.isoformat(),
                 "areas": sorted(a.split(",")) if a else sorted(_ROLE_AREAS.get(r, set()))}
                for i, e, n, r, s, c, a in cur.fetchall()]


def user_areas(conn: Any, email: str, role: str) -> set[str]:
    """Áreas que a conta enxerga: coluna `areas` (se o admin configurou) ou o
    padrão do papel escolhido no cadastro. Bootstrap (.env) usa só o papel."""
    if email in USERS:
        return set(_ROLE_AREAS.get(role, set()))
    ensure_users_table(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT areas, role FROM users WHERE email=%s", (email,))
        row = cur.fetchone()
    if not row:
        return set()
    areas, r = row
    if areas:
        return {a for a in areas.split(",") if a in AREAS}
    return set(_ROLE_AREAS.get(r, set()))


def set_user_areas(conn: Any, user_id: str, areas: list[str]) -> bool:
    clean = sorted({a for a in areas if a in AREAS})
    ensure_users_table(conn)
    with conn.cursor() as cur:
        cur.execute("UPDATE users SET areas=%s WHERE id=%s", (",".join(clean) or None, user_id))
        return cur.rowcount > 0


def set_user_status(conn: Any, user_id: str, status: str, actor: str) -> bool:
    if status not in ("aprovado", "bloqueado", "pendente"):
        return False
    ensure_users_table(conn)
    with conn.cursor() as cur:
        cur.execute("""UPDATE users SET status=%s, approved_by=%s, approved_at=now()
                        WHERE id=%s""", (status, actor, user_id))
        return cur.rowcount > 0


# --- rate limit de login (memória do processo; suficiente p/ 1 instância) ---
_ATTEMPTS: dict[str, list[float]] = {}
_MAX_FAILS, _WINDOW, _LOCK = 5, 300.0, 60.0


def login_blocked(key: str) -> bool:
    now = time.time()
    fails = [t for t in _ATTEMPTS.get(key, []) if now - t < _WINDOW]
    _ATTEMPTS[key] = fails
    return len(fails) >= _MAX_FAILS and (now - fails[-1]) < _LOCK


def record_login_fail(key: str) -> None:
    _ATTEMPTS.setdefault(key, []).append(time.time())


def clear_login_fails(key: str) -> None:
    _ATTEMPTS.pop(key, None)


def _sign(payload: str) -> str:
    ensure_auth()
    return hmac.new(os.environ["AUTH_SECRET"].encode(), payload.encode(), hashlib.sha256).hexdigest()


def make_token(user: str, role: str) -> str:
    exp = int(time.time()) + _TTL_SECONDS
    payload = f"{user}|{role}|{exp}"
    return f"{payload}|{_sign(payload)}"


def verify_token(token: str | None) -> tuple[str, str] | None:
    """Retorna (user, role) se o cookie é válido e não expirou; senão None."""
    if not token or token.count("|") != 3:
        return None
    user, role, exp, sig = token.split("|")
    if not hmac.compare_digest(sig, _sign(f"{user}|{role}|{exp}")):
        return None
    try:
        if int(exp) < time.time():
            return None
    except ValueError:
        return None
    # a confiança vem da ASSINATURA HMAC; o role só precisa ser um papel válido
    # (usuários do banco não estão em USERS). Bootstrap segue checado à parte.
    if role not in ROLE_HOME:
        return None
    if user in USERS and USERS[user] != role:
        return None
    return (user, role)
