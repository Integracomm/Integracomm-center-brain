"""Times por área CONFIGURÁVEIS pelo admin (tabela area_team no RDS).

Pedido do Otávio (14/07/26): as listas de colaboradores saem do código e viram
configuração editável no Painel Administrativo. Dois papéis:
- vendas (closers): a lista é a RÉGUA do SQL do funil oficial ("deal na mão de
  closer" = agendou reunião). Ex-closers ficam na lista como INATIVOS — saem
  dos rankings/planos, mas a régua continua idêntica à do dashboard do time
  (o SQL_CLOSERS deles mantém quem saiu).
- prevendas (SDRs): destaque e planos de ação da aba Time & Planos.

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
)"""

# seeds (14/07/26): closers = SQL_CLOSERS do dashboard Lovable (régua do funil,
# Johnatan desligado mas mantido na régua); SDRs = time atual validado
# (Leticia desligada início de jul; Eduarda = coordenação, fica fora dos
# planos individuais mas aparece nas tabelas por ter deals no nome)
_SEEDS: dict[str, list[tuple[str, bool]]] = {
    "vendas": [("Camila Fernandes", True), ("Denise", True), ("Marcos Rafael", True),
               ("Valéria", True), ("Vitória Lazzerini", True), ("Lucas Pereira", True),
               ("Giovana Fornazari", True), ("Ana Beatriz", True), ("Johnatan", False)],
    "prevendas": [("Giovana Moura", True), ("Fernanda Araújo", True), ("Leticia Roman", False)],
}

_CACHE: dict[str, tuple[float, list[tuple[str, bool]]]] = {}
_TTL_S = 60


def norm(s: str | None) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", (s or "").lower())
                   if unicodedata.category(c) != "Mn").strip()


def listas(conn: Any, area: str) -> list[tuple[str, bool]]:
    """[(nome, ativo)] da área; semeia na primeira leitura de uma área vazia."""
    hit = _CACHE.get(area)
    if hit and time.monotonic() - hit[0] < _TTL_S:
        return hit[1]
    with conn.cursor() as cur:
        cur.execute(_DDL)
        cur.execute("SELECT nome, ativo FROM area_team WHERE area=%s ORDER BY ativo DESC, nome", (area,))
        rows = [(n, bool(a)) for n, a in cur.fetchall()]
        if not rows and area in _SEEDS:
            cur.executemany("INSERT INTO area_team (area, nome, ativo) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                            [(area, n, a) for n, a in _SEEDS[area]])
            rows = _SEEDS[area]
    _CACHE[area] = (time.monotonic(), rows)
    return rows


def casador(conn: Any, area: str, so_ativos: bool = False):
    """Retorna f(nome_pipedrive) -> bool com a régua de casamento do app do
    time (igualdade ou inclusão, sem acento). Régua do funil usa TODOS
    (so_ativos=False); rankings usam só ativos."""
    alvos = [norm(n) for n, ativo in listas(conn, area) if ativo or not so_ativos]

    def casa(nome: str | None) -> bool:
        n = norm(nome)
        return bool(n) and any(n == c or c in n for c in alvos)
    return casa


def ativo(conn: Any, area: str, nome: str | None) -> bool:
    """O nome casa com alguém ATIVO da lista? (chip 'desligado' nos rankings)"""
    return casador(conn, area, so_ativos=True)(nome)


def salvar(conn: Any, area: str, linhas: list[str], actor: str) -> None:
    """Substitui a lista da área. Linha começando com '-' = inativo."""
    pares: list[tuple[str, bool]] = []
    for ln in linhas:
        ln = ln.strip()
        if not ln:
            continue
        inativo = ln.startswith("-")
        nome = ln.lstrip("-").strip()
        if nome:
            pares.append((nome, not inativo))
    with conn.cursor() as cur:
        cur.execute(_DDL)
        cur.execute("DELETE FROM area_team WHERE area=%s", (area,))
        if pares:
            cur.executemany("INSERT INTO area_team (area, nome, ativo) VALUES (%s,%s,%s)",
                            [(area, n, a) for n, a in pares])
        cur.execute("INSERT INTO audit_log (actor, action, scope) VALUES (%s,'area_team',%s)",
                    (actor, f"{area}:{len(pares)} nomes"))
    _CACHE.pop(area, None)
