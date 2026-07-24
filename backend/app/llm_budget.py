"""Guarda de ORÇAMENTO da API do Claude — teto mensal em US$ para o projeto TODO.

Decisão do Otávio (10/07/26): US$ 20 carregados para o 1º mês de uso, valendo
para todas as funções de LLM de todas as áreas, sem extrapolar. O teto aqui é
US$ 18 (margem de 10% para variação de preço/estimativa).

Contrato — toda chamada ao Claude, em qualquer área, deve:
  1. chamar ensure_budget(conn) ANTES  -> levanta LlmBudgetExceeded se o teto
     do mês já foi atingido (quem chama decide: pular, cair no determinístico);
  2. chamar record_usage(conn, feature, model, in, out) DEPOIS -> grava tokens
     e custo REAL na tabela llm_usage (fonte do medidor no Painel Administrativo).

Preço por MTok (conferido na referência oficial 23/07/26): Sonnet 5 promocional
US$2/US$10 até 31/08/2026 (depois 3/15); Haiku 4.5 US$1/US$5; Opus 4.8 US$5/US$25.

CACHE (corrigido 23/07/26): até então TODO token de input era cobrado a preço
cheio, inclusive os de cache — e o docstring dizia "superestima de leve". Não
era de leve: `growth:tom_claude` usa system prompt cacheado e respondia por 83%
do gasto (US$4,65 de US$5,62), com 2,0M tokens de input em 231 chamadas, a maior
parte deles LEITURA de cache. Preços reais: leitura de cache = 0,1× do input
(estávamos cobrando 10× a mais) e escrita de cache = 1,25× (cobrávamos a menos).
Agora os três componentes são gravados e precificados separadamente.
"""
from __future__ import annotations

import datetime as dt
import os

_DDL = """CREATE TABLE IF NOT EXISTS llm_usage (
    id bigserial PRIMARY KEY,
    ts timestamptz NOT NULL DEFAULT now(),
    feature text NOT NULL,
    model text NOT NULL,
    tokens_in bigint NOT NULL,
    tokens_out bigint NOT NULL,
    cost_usd numeric(10,6) NOT NULL
)"""

_SONNET_INTRO_ATE = dt.date(2026, 8, 31)


class LlmBudgetExceeded(RuntimeError):
    """Teto mensal de gasto com LLM atingido — nenhuma chamada nova até o mês virar."""


def price_per_mtok(model: str, when: dt.date | None = None) -> tuple[float, float]:
    """(input, output) em US$/MTok. Modelo desconhecido assume o mais caro."""
    when = when or dt.date.today()
    m = (model or "").lower()
    if "haiku" in m:
        return 1.0, 5.0
    if "sonnet" in m:
        return (2.0, 10.0) if when <= _SONNET_INTRO_ATE else (3.0, 15.0)
    if "opus" in m:
        return 5.0, 25.0  # Opus 4.8/4.7 (o fallback antigo dizia 15/75 — 3x a mais)
    return 15.0, 75.0  # modelo desconhecido: mantém o teto conservador


def budget_cap() -> float:
    return float(os.environ.get("LLM_BUDGET_USD", "18"))


def month_spend(conn) -> float:
    """Gasto do mês corrente (US$) somando o custo real registrado."""
    with conn.cursor() as cur:
        cur.execute(_DDL)
        cur.execute("SELECT COALESCE(sum(cost_usd), 0) FROM llm_usage "
                    "WHERE ts >= date_trunc('month', now())")
        return float(cur.fetchone()[0])


def ensure_budget(conn) -> float:
    """Gate pré-chamada: levanta LlmBudgetExceeded se o mês estourou. Retorna o gasto."""
    spent = month_spend(conn)
    cap = budget_cap()
    if spent >= cap:
        raise LlmBudgetExceeded(
            f"orçamento mensal de LLM atingido: US$ {spent:.2f} de US$ {cap:.2f} — "
            "chamadas bloqueadas até o próximo mês (ou aumente LLM_BUDGET_USD no .env)")
    return spent


_MIG = """
ALTER TABLE llm_usage ADD COLUMN IF NOT EXISTS cache_read_tokens     bigint NOT NULL DEFAULT 0;
ALTER TABLE llm_usage ADD COLUMN IF NOT EXISTS cache_creation_tokens bigint NOT NULL DEFAULT 0;
"""

# multiplicadores sobre o preço de INPUT (referência oficial da API)
_MULT_CACHE_READ = 0.1     # leitura de cache custa 10% do input
_MULT_CACHE_WRITE = 1.25   # escrita de cache (TTL 5 min) custa 125%


def record_usage(conn, feature: str, model: str, tokens_in: int, tokens_out: int,
                 cache_read: int = 0, cache_creation: int = 0) -> float:
    """Grava o uso e devolve o custo (US$) real desta chamada.

    `tokens_in` = TOTAL de tokens de entrada (inclui os de cache) — mantido
    assim para não quebrar a série histórica já gravada. `cache_read` e
    `cache_creation` são as PARTES desse total que têm preço diferente; o que
    sobra é input não-cacheado, a preço cheio."""
    pin, pout = price_per_mtok(model)
    cache_read = max(0, int(cache_read or 0))
    cache_creation = max(0, int(cache_creation or 0))
    puro = max(0, int(tokens_in) - cache_read - cache_creation)
    cost = ((puro
             + cache_read * _MULT_CACHE_READ
             + cache_creation * _MULT_CACHE_WRITE) / 1e6 * pin
            + tokens_out / 1e6 * pout)
    with conn.cursor() as cur:
        cur.execute(_DDL)
        cur.execute(_MIG)
        cur.execute("INSERT INTO llm_usage (feature, model, tokens_in, tokens_out, cost_usd,"
                    " cache_read_tokens, cache_creation_tokens) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (feature, model, tokens_in, tokens_out, cost, cache_read, cache_creation))
    conn.commit()
    return cost


def month_summary(conn) -> dict:
    """Resumo p/ o Painel Administrativo: gasto, teto, % e quebra por função."""
    with conn.cursor() as cur:
        cur.execute(_DDL)
        cur.execute("""SELECT feature, count(*), sum(tokens_in), sum(tokens_out), sum(cost_usd)
                         FROM llm_usage WHERE ts >= date_trunc('month', now())
                        GROUP BY feature ORDER BY 5 DESC""")
        por_funcao = [{"feature": f, "chamadas": n, "tokens_in": int(ti or 0),
                       "tokens_out": int(to or 0), "cost_usd": float(c or 0)}
                      for f, n, ti, to, c in cur.fetchall()]
    spent = sum(x["cost_usd"] for x in por_funcao)
    cap = budget_cap()
    return {"spent_usd": spent, "cap_usd": cap,
            "pct": (spent / cap if cap else 0), "por_funcao": por_funcao}
