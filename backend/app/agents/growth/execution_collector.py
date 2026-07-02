"""Collector de EXECUÇÃO — do mirror ClickUp para o bloco 'execution' do score.

Reconstrói a saúde de execução AS-OF-DATE (sem vazamento) e a entrega como
`SignalInput` do bloco execution (peso 15). Usa o porte fiel
`compute_execution_score`. Guarda anti-vazamento: subtarefa criada depois do
as-of não existia; conclusão depois do as-of ainda não tinha acontecido.
"""
from __future__ import annotations

import datetime as dt

from .execution_score import Cliente, ExecutionResult, Subtarefa, compute_execution_score
from .scoring import SignalInput
from ...sources.mirror import ClienteRow, parse_dt


def _asof_subs(rows: list[dict], asof: dt.datetime) -> list[Subtarefa]:
    """Converte subtarefas cruas -> Subtarefa NA foto do as-of (sem vazamento)."""
    out: list[Subtarefa] = []
    for r in rows:
        criada = parse_dt(r.get("data_criacao"))
        if criada and criada > asof:
            continue  # não existia ainda
        concl = parse_dt(r.get("data_conclusao"))
        if concl and concl > asof:
            concl = None  # ainda não concluída na data
        out.append(Subtarefa(
            status=r.get("status"),
            data_vencimento=parse_dt(r.get("data_vencimento")),
            data_conclusao=concl,
            recorrente=bool(r.get("recorrente")),
            proximo_vencimento=parse_dt(r.get("proximo_vencimento")),
        ))
    return out


def execution_asof(cli: ClienteRow, subs_rows: list[dict], asof: dt.datetime) -> ExecutionResult:
    """Score de execução 0-100 (ou None) na data as-of. postergacoes=0 (não há
    histórico de adiamentos no mirror — é uma penalidade entre várias)."""
    cliente = Cliente(servico=cli.servico, data_venda=cli.data_venda, data_onboarding=cli.data_onboarding)
    return compute_execution_score(cliente, _asof_subs(subs_rows, asof), postergacoes_2_semanas=0, now=asof)


def execution_signal(cli: ClienteRow, subs_rows: list[dict], asof: dt.datetime) -> SignalInput | None:
    """SignalInput do bloco execution (risco direto = 1 - score/100). None quando
    não avaliável (ex.: serviço só ADS, ou sem subtarefas) -> bloco ausente,
    renormaliza sobre os presentes."""
    res = execution_asof(cli, subs_rows, asof)
    if res.score is None:
        return None
    risk = max(0.0, min(1.0, 1 - res.score / 100.0))
    return SignalInput("execucao", "execution", [], higher_is_worse=True, source="clickup", direct_risk=risk)
