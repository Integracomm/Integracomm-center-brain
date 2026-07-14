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
);
ALTER TABLE area_team ADD COLUMN IF NOT EXISTS papel TEXT NOT NULL DEFAULT 'membro'"""

# Papéis (esclarecidos pelo Otávio 14/07): 'membro' = colaborador do time
# (ranking + planos + régua); 'coordenacao'/'gerencia' = aparecem com chip,
# contam na régua, FORA de planos/mediana (Valéria coord. Vendas, Eduarda
# coord. PV, Marcos gerente das duas); 'regua' = NÃO é colaborador — some dos
# rankings mas PERMANECE na régua do SQL (Vitória/Lucas, que estão no
# SQL_CLOSERS do dashboard do time). ativo=False = desligado (chip, sem plano).
_SEEDS: dict[str, list[tuple[str, bool, str]]] = {
    "vendas": [("Camila Fernandes", True, "membro"), ("Denise", True, "membro"),
               ("Giovana Fornazari", True, "membro"), ("Ana Beatriz", True, "membro"),
               ("Johnatan", False, "membro"),
               ("Valéria", True, "coordenacao"), ("Marcos Rafael", True, "gerencia"),
               ("Vitória Lazzerini", True, "regua"), ("Lucas Pereira", True, "regua")],
    "prevendas": [("Giovana Moura", True, "membro"), ("Fernanda Araújo", True, "membro"),
                  ("Leticia Roman", False, "membro"),
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


def ativo(conn: Any, area: str, nome: str | None) -> bool:
    """O nome casa com alguém ATIVO da lista? (chip 'desligado' nos rankings)"""
    return casador(conn, area, so_ativos=True)(nome)


def papel_de(conn: Any, area: str, nome: str | None) -> str | None:
    """Papel do nome na área ('membro'/'coordenacao'/'gerencia'/'regua');
    None = não está na lista."""
    n = norm(nome)
    if not n:
        return None
    for cfg_nome, _ativo, papel in listas(conn, area):
        c = norm(cfg_nome)
        if n == c or c in n:
            return papel
    return None


_PAPEIS = {"coordenacao": "coordenacao", "gerencia": "gerencia", "regua": "regua"}


def _papel_do_sufixo(s: str) -> str:
    x = norm(s)
    if "coorden" in x:
        return "coordenacao"
    if "geren" in x:
        return "gerencia"
    if "regua" in x or "fora" in x:
        return "regua"
    return "membro"


def salvar(conn: Any, area: str, linhas: list[str], actor: str) -> None:
    """Substitui a lista da área. Formato da linha: Nome [| papel];
    '-' no começo = desligado. Papéis: coordenação · gerência · só régua."""
    trios: list[tuple[str, bool, str]] = []
    for ln in linhas:
        ln = ln.strip()
        if not ln:
            continue
        inativo = ln.startswith("-")
        corpo = ln.lstrip("-").strip()
        nome, _, sufixo = corpo.partition("|")
        nome = nome.strip()
        if nome:
            trios.append((nome, not inativo, _papel_do_sufixo(sufixo) if sufixo else "membro"))
    with conn.cursor() as cur:
        cur.execute(_DDL)
        cur.execute("DELETE FROM area_team WHERE area=%s", (area,))
        if trios:
            cur.executemany("INSERT INTO area_team (area, nome, ativo, papel) VALUES (%s,%s,%s,%s)",
                            [(area, n, a, p) for n, a, p in trios])
        cur.execute("INSERT INTO audit_log (actor, action, scope) VALUES (%s,'area_team',%s)",
                    (actor, f"{area}:{len(trios)} nomes"))
    _CACHE.pop(area, None)
