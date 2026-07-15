"""Specs do porte de computeLiveScore. Rodar com: pytest (no host de staging)."""
import datetime as dt

from app.agents.growth.execution_score import (
    Cliente,
    Subtarefa,
    compute_execution_score,
)

NOW = dt.datetime(2026, 6, 25, tzinfo=dt.timezone.utc)


def _d(days_ago: int) -> dt.datetime:
    return NOW - dt.timedelta(days=days_ago)


def test_cliente_saudavel_sem_ocorrencias():
    # No prazo = conclusao <= vencimento. _d(n) = há n dias (n maior = mais antigo),
    # então conclusao=_d(d+1) (mais antiga) <= vencimento=_d(d) (mais recente).
    # 5 atividades em 5 dias distintos (>3 evita a penalidade 'pouco trabalhado';
    # dias distintos sem batch dão +5 de cadência -> clamp 100).
    subs = [
        Subtarefa(data_conclusao=_d(d + 1), data_vencimento=_d(d))
        for d in (1, 3, 5, 7, 9)
    ]
    r = compute_execution_score(Cliente(servico="B2 - TRACTION"), subs, 0, now=NOW)
    assert r.score == 100, r.motivo


def test_penaliza_atrasadas_em_aberto():
    subs = [Subtarefa(data_vencimento=_d(10)) for _ in range(3)]  # 3 abertas e atrasadas
    r = compute_execution_score(Cliente(servico="B3 - SCALE"), subs, 0, now=NOW)
    assert r.score is not None and r.score < 100
    assert "atrasada" in r.motivo


def test_servico_apenas_ads_nao_avaliado():
    r = compute_execution_score(Cliente(servico="ADS para Marketplace"), [], 0, now=NOW)
    assert r.score is None
    assert "ADS" in r.motivo


def test_implantacao_critica_acima_de_9_meses():
    cli = Cliente(servico="Implantação", data_venda=_d(int(10 * 30.4375)))
    r = compute_execution_score(cli, [], 0, now=NOW)
    assert r.score == 25
    assert "Implantação crítica" in r.motivo


def test_postergacoes_penalizam():
    subs = [Subtarefa(data_conclusao=_d(3), data_vencimento=_d(4))]
    r = compute_execution_score(Cliente(servico="B1 - START"), subs, postergacoes_2_semanas=3, now=NOW)
    assert r.score is not None and r.score < 100
    assert "postergando" in r.motivo


def test_vence_hoje_ainda_no_prazo():
    """Regra do Otávio (14/07/26, caso GH IMPORTS): atividade que vence HOJE
    está DENTRO do prazo — atrasada só a partir do dia seguinte. O carimbo do
    ClickUp costuma ser madrugada/manhã do dia do vencimento; comparar por
    instante marcava tudo de hoje como atrasado à tarde."""
    hoje_madrugada = NOW.replace(hour=3, minute=0)   # vence hoje, carimbo 03:00Z
    subs = [Subtarefa(data_vencimento=hoje_madrugada) for _ in range(4)]
    # 4+ atividades no período evita a penalidade 'pouco trabalhado'
    r = compute_execution_score(Cliente(servico="B4 - SCALE"), subs, 0,
                                now=NOW.replace(hour=18))  # tarde do MESMO dia
    # o que importa: NENHUMA penalidade de atraso (outras penalidades, como
    # 'sem entregas recentes', podem existir e não são o alvo deste teste)
    assert "atrasada" not in r.motivo, r.motivo


def test_vencida_ontem_conta_atrasada():
    subs = [Subtarefa(data_vencimento=_d(1)) for _ in range(4)]  # venceu ontem
    r = compute_execution_score(Cliente(servico="B4 - SCALE"), subs, 0, now=NOW)
    assert r.score is not None and r.score < 100
    assert "atrasada" in r.motivo


def test_concluida_no_mesmo_dia_do_vencimento_e_no_prazo():
    """Concluir à tarde uma tarefa que vencia de madrugada NO MESMO DIA não é
    atraso — comparação por dia BRT, dos dois lados."""
    subs = [Subtarefa(data_vencimento=_d(d).replace(hour=3),
                      data_conclusao=_d(d).replace(hour=20)) for d in (1, 3, 5, 7, 9)]
    r = compute_execution_score(Cliente(servico="B2 - TRACTION"), subs, 0, now=NOW)
    assert r.score == 100, r.motivo
