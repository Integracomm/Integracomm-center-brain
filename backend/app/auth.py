"""Login + RBAC básico do painel — sessão por cookie HMAC-assinado (stdlib).

Dois usuários fixos nesta fase: `admin` (vê tudo, inclusive o hub central) e
`gestor_growth` (só a área de Growth). Senhas e segredo de assinatura vivem no
`.env` da RAIZ: se ausentes no 1º boot, são GERADOS aleatoriamente e gravados lá
— nunca impressos nem commitados (mesma higiene do setup do Postgres). Trocar a
senha = editar o .env e reiniciar.

Sem dependências novas: token = "user|role|expiry|hmac_sha256" em cookie
httponly. TTL 12h. Toda verificação usa compare_digest (timing-safe).
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from pathlib import Path

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
ROLE_HOME: dict[str, str] = {"admin": "/", "gestor_growth": "/growth"}
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
    """Valida credenciais; retorna o role ou None. Timing-safe."""
    ensure_auth()
    u = (user or "").strip().lower()
    role = USERS.get(u)
    if not role:
        return None
    want = os.environ.get(_PWD_KEY[u], "")
    return role if want and hmac.compare_digest(password or "", want) else None


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
    if USERS.get(user) != role:
        return None
    return (user, role)
