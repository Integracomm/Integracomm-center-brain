"""Guarda de ORÇAMENTO da API do Claude — teto mensal em US$ para o projeto TODO.

Decisão do Otávio (10/07/26): US$ 20 carregados para o 1º mês de uso, valendo
para todas as funções de LLM de todas as áreas, sem extrapolar. O teto aqui é
US$ 18 (margem de 10% para variação de preço/estimativa).

Contrato — toda chamada ao Claude, em qualquer área, deve:
  1. chamar ensure_budget(conn) ANTES  -> levanta LlmBudgetExceeded se o teto
     do mês já foi atingido (quem chama decide: pular, cair no determinístico);
  2. chamar record_usage(conn, feature, model, in, out) DEPOIS -> grava tokens
     e custo REAL na tabela llm_usage (fonte do medidor no Painel Administrativo).

Preço por MTok: Sonnet 5 promocional US$2/US$10 até 31/08/2026 (depois 3/15);
Haiku 4.5 US$1/US$5. Tokens de cache são contados ao preço cheio de input —
superestima de leve (leitura de cache custa 10%), a favor da margem.
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
    return 15.0, 75.0  # opus / desconhecido — conservador


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


def record_usage(conn, feature: str, model: str, tokens_in: int, tokens_out: int) -> float:
    """Grava o uso e devolve o custo (US$) desta chamada."""
    pin, pout = price_per_mtok(model)
    cost = tokens_in / 1e6 * pin + tokens_out / 1e6 * pout
    with conn.cursor() as cur:
        cur.execute(_DDL)
        cur.execute("INSERT INTO llm_usage (feature, model, tokens_in, tokens_out, cost_usd) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (feature, model, tokens_in, tokens_out, cost))
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
