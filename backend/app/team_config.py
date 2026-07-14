"""Times por área CONFIGURÁVEIS pelo admin (tabela area_team no RDS).

Pedido do Otávio (14/07/26): as listas de colaboradores saem do código e viram
configuração editável no Painel Administrativo.
- vendas (closers): a lista COMPLETA é a RÉGUA do SQL do funil oficial ("deal
  na mão de closer" = agendou reunião) — equivalente ao SQL_CLOSERS do
  dashboard do time, incluindo quem já saiu (histórico dos meses passados).
- prevendas (SDRs): destaque e planos de ação da aba Time & Planos.
- DESLIGADOS: detecção AUTOMÁTICA pelo Pipedrive (usuário desativado =
  active_flag False, coluna owner_active) — somem de todas as telas, números
  permanecem nas réguas. O '-' na lista só força manualmente um caso raro.

Casamento de nome = o MESMO do app do time: sem acento, minúsculo, igual OU
contido no nome do Pipedrive. Cache por processo (60s) — é lido em todo funil.
"""
from __future__ import annotations

import time
import unicodedata
from typing import Any

_DDL = """CREATE TABLE IF NOT EXISTS area_team (
    area  TEXT NOT NULL,
    nome  TEXT NOT NULL,
    ativo BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (area, nome)
);
ALTER TABLE area_team ADD COLUMN IF NOT EXISTS papel TEXT NOT NULL DEFAULT 'membro'"""

# Papéis (esclarecidos pelo Otávio 14/07): 'membro' = colaborador do time
# (ranking + planos + régua); 'coordenacao'/'gerencia' = aparecem com chip,
# contam na régua, FORA de planos/mediana (Valéria coord. Vendas, Eduarda
# coord. PV, Marcos gerente das duas). DESLIGADO é AUTOMÁTICO: usuário com
# active_flag=False no Pipedrive (coluna owner_active, vem no cache) — some de
# TODAS as telas, mas fica na lista p/ a régua do SQL continuar batendo com o
# SQL_CLOSERS do dashboard nos meses em que atuou (Johnatan, Vitória, Lucas).
# ativo=False na tabela = desligamento FORÇADO manualmente (raro).
_SEEDS: dict[str, list[tuple[str, bool, str]]] = {
    "vendas": [("Camila Fernandes", True, "membro"), ("Denise", True, "membro"),
               ("Giovana Fornazari", True, "membro"), ("Ana Beatriz", True, "membro"),
               ("Johnatan", True, "membro"), ("Vitória Lazzerini", True, "membro"),
               ("Lucas Pereira", True, "membro"),
               ("Valéria", True, "coordenacao"), ("Marcos Rafael", True, "gerencia")],
    "prevendas": [("Giovana Moura", True, "membro"), ("Fernanda Araújo", True, "membro"),
                  ("Leticia Roman", True, "membro"),
                  ("Eduarda Martins", True, "coordenacao"), ("Marcos Rafael", True, "gerencia")],
}

_CACHE: dict[str, tuple[float, list[tuple[str, bool, str]]]] = {}
_TTL_S = 60


def norm(s: str | None) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", (s or "").lower())
                   if unicodedata.category(c) != "Mn").strip()


def listas(conn: Any, area: str) -> list[tuple[str, bool, str]]:
    """[(nome, ativo, papel)] da área; semeia na primeira leitura de área vazia."""
    hit = _CACHE.get(area)
    if hit and time.monotonic() - hit[0] < _TTL_S:
        return hit[1]
    with conn.cursor() as cur:
        cur.execute(_DDL)
        cur.execute("SELECT nome, ativo, papel FROM area_team WHERE area=%s ORDER BY ativo DESC, nome", (area,))
        rows = [(n, bool(a), p) for n, a, p in cur.fetchall()]
        if not rows and area in _SEEDS:
            cur.executemany("INSERT INTO area_team (area, nome, ativo, papel) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                            [(area, n, a, p) for n, a, p in _SEEDS[area]])
            rows = _SEEDS[area]
    _CACHE[area] = (time.monotonic(), rows)
    return rows


def casador(conn: Any, area: str, so_ativos: bool = False):
    """Retorna f(nome_pipedrive) -> bool com a régua de casamento do app do
    time (igualdade ou inclusão, sem acento). A régua do funil usa TODOS os
    papéis (inclusive 'regua' — equivalência com o SQL_CLOSERS do dashboard)."""
    alvos = [norm(n) for n, ativo, _p in listas(conn, area) if ativo or not so_ativos]

    def casa(nome: str | None) -> bool:
        n = norm(nome)
        return bool(n) and any(n == c or c in n for c in alvos)
    return casa


def _nomes_pipedrive(conn: Any, flag: bool) -> list[str]:
    key = f"_pd_{'ativos' if flag else 'inativos'}"
    hit = _CACHE.get(key)
    if hit and time.monotonic() - hit[0] < _TTL_S:
        return hit[1]
    with conn.cursor() as cur:
        cur.execute("""SELECT DISTINCT owner_name FROM mkt_deals_attribution
                        WHERE owner_active = %s AND owner_name IS NOT NULL""", (flag,))
        nomes = [r[0] for r in cur.fetchall()]
    _CACHE[key] = (time.monotonic(), nomes)
    return nomes


def desligados_pipedrive(conn: Any) -> list[str]:
    """Nomes de usuários DESATIVADOS no Pipedrive (active_flag=False, coluna
    owner_active vinda do cache) — a fonte automática de 'desligado'."""
    return _nomes_pipedrive(conn, False)


def status_pipedrive(conn: Any, nome: str | None) -> str:
    """'ativo' | 'desativado' | 'sem dados' — situação do usuário no Pipedrive
    (mostrada na confirmação de desligamento do admin)."""
    n = norm(nome)
    if not n:
        return "sem dados"

    def casa(lista):
        return any(n == c or c in n or n in c for c in (norm(x) for x in lista))
    if casa(_nomes_pipedrive(conn, True)):
        return "ativo"
    if casa(_nomes_pipedrive(conn, False)):
        return "desativado"
    return "sem dados"


def eh_desligado(conn: Any, area: str, nome: str | None) -> bool:
    """Desligado = usuário desativado no Pipedrive (automático) OU linha
    marcada com '-' na lista da área (força manual). Desligados somem de
    todas as telas; os números deles continuam nas réguas."""
    n = norm(nome)
    if not n:
        return False
    for pd in desligados_pipedrive(conn):
        c = norm(pd)
        if n == c or c in n:
            return True
    return any((n == norm(cn) or norm(cn) in n) and not at
               for cn, at, _p in listas(conn, area))


def papel_de(conn: Any, area: str, nome: str | None) -> str | None:
    """Papel do nome na área ('membro'/'coordenacao'/'gerencia');
    None = não está na lista."""
    n = norm(nome)
    if not n:
        return None
    for cfg_nome, _ativo, papel in listas(conn, area):
        c = norm(cfg_nome)
        if n == c or c in n:
            return papel
    return None


# --- operações do admin (UI de edição, 14/07) --------------------------------
PAPEIS_VALIDOS = ("membro", "coordenacao", "gerencia")


def _audit(cur, actor: str, detalhe: str) -> None:
    cur.execute("INSERT INTO audit_log (actor, action, scope) VALUES (%s,'area_team',%s)",
                (actor, detalhe))


def adicionar(conn: Any, area: str, nome: str, papel: str, actor: str) -> None:
    """Adiciona colaborador (ou RECONTRATA um desligado manual: volta ativo)."""
    papel = papel if papel in PAPEIS_VALIDOS else "membro"
    with conn.cursor() as cur:
        cur.execute(_DDL)
        cur.execute("""INSERT INTO area_team (area, nome, ativo, papel) VALUES (%s,%s,TRUE,%s)
                       ON CONFLICT (area, nome) DO UPDATE SET ativo=TRUE, papel=EXCLUDED.papel""",
                    (area, nome, papel))
        _audit(cur, actor, f"{area}: + {nome} ({papel})")
    _CACHE.pop(area, None)


def desligar(conn: Any, area: str, nome: str, actor: str) -> None:
    """Desligamento manual: some de todas as telas, PERMANECE na régua
    histórica do funil (nunca apagamos — o SQL de meses passados depende)."""
    with conn.cursor() as cur:
        cur.execute("UPDATE area_team SET ativo=FALSE WHERE area=%s AND nome=%s", (area, nome))
        _audit(cur, actor, f"{area}: desligado {nome}")
    _CACHE.pop(area, None)


def definir_papel(conn: Any, area: str, nome: str, papel: str, actor: str) -> None:
    """Troca a função (promoção: membro → coordenação, etc.)."""
    if papel not in PAPEIS_VALIDOS:
        return
    with conn.cursor() as cur:
        cur.execute("UPDATE area_team SET papel=%s WHERE area=%s AND nome=%s", (papel, area, nome))
        _audit(cur, actor, f"{area}: {nome} -> {papel}")
    _CACHE.pop(area, None)
