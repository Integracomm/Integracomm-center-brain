"""Score de execução/entrega (ClickUp) — porte fiel do `computeLiveScore`.

Origem: costumerhealth/src/lib/clickupScores.ts (lógica validada em produção
no "Saúde do Cliente - HUB Connector"). É o nosso sinal LÍDER FORTE: atrasos,
postergações e queda de ritmo de execução costumam *causar* o churn, então o
antecedem.

Este módulo calcula a FOTO de hoje (0-100 + motivos explicáveis). A casca
guarda um snapshot por dia; a camada de TRAJETÓRIA/BASELINE (ver
``trajectory.py``, a construir) deriva tendência/velocidade/inflexão a partir
da série de snapshots por conta — é o que torna o modelo preditivo, não a foto.

Mudanças vs. o original TS: tradução idiomática para Python e tipagem; a regra
de negócio (penalidades, limites, casos Implantação/ADS) é preservada
fielmente para manter a compatibilidade com o que o time já valida.

DIVERGÊNCIA INTENCIONAL do TS (regra do Otávio, 14/07/26): prazo é comparado
por DIA (BRT), não por instante — atividade que vence HOJE está DENTRO do
prazo; só conta atrasada a partir do dia seguinte. O original comparava
timestamps e marcava como atrasada, à tarde, tudo que vencia no próprio dia
(caso GH IMPORTS). Vale para abertas, recorrentes e conclusões no mesmo dia.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

_DAY = dt.timedelta(days=1)
_TWO_WEEKS = dt.timedelta(days=14)
_MONTH_DAYS = 30.4375  # média usada no original
_BRT = dt.timezone(dt.timedelta(hours=-3))


def _dia(d: dt.datetime) -> dt.date:
    """Dia BRT do carimbo (naive = UTC). Prazo se compara por DIA: vence hoje
    ainda está no prazo — atrasada só a partir de amanhã."""
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d.astimezone(_BRT).date()


@dataclass
class Subtarefa:
    status: str | None = None
    data_vencimento: dt.datetime | None = None
    data_conclusao: dt.datetime | None = None
    recorrente: bool | None = None
    proximo_vencimento: dt.datetime | None = None


@dataclass
class Cliente:
    servico: str | None = None
    data_venda: dt.datetime | None = None
    data_onboarding: dt.datetime | None = None


@dataclass
class ExecutionResult:
    score: float | None  # None = não avaliado (ex.: serviço apenas ADS)
    motivo: str


def _is_recorrente_aberta(s: Subtarefa, now: dt.datetime) -> bool:
    return bool(s.recorrente and s.proximo_vencimento and _dia(s.proximo_vencimento) >= _dia(now))


def _is_recorrente_vencida(s: Subtarefa, now: dt.datetime) -> bool:
    return bool(s.recorrente and s.proximo_vencimento and _dia(s.proximo_vencimento) < _dia(now))


def _dias_uteis_entre(inicio: dt.datetime, fim: dt.datetime) -> int:
    """Dias úteis (seg-sex) entre as datas, menos 1 — igual ao original."""
    cur = inicio.replace(hour=0, minute=0, second=0, microsecond=0)
    end = fim.replace(hour=0, minute=0, second=0, microsecond=0)
    dias = 0
    while cur <= end:
        if cur.weekday() < 5:  # 0=seg .. 4=sex
            dias += 1
        cur += _DAY
    return max(0, dias - 1)


def compute_execution_score(
    cliente: Cliente,
    subs: list[Subtarefa],
    postergacoes_2_semanas: int,
    now: dt.datetime | None = None,
) -> ExecutionResult:
    """Porte fiel de computeLiveScore(). Retorna score 0-100 ou None + motivo."""
    now = now or dt.datetime.now(dt.timezone.utc)
    duas_semanas_atras = now - _TWO_WEEKS
    servico = (cliente.servico or "").strip()
    servico_lower = servico.lower()
    is_apenas_ads = servico_lower == "ads para marketplace"
    is_implantacao = "implanta" in servico_lower

    concluidas_reais = [
        s for s in subs if s.data_conclusao and not _is_recorrente_aberta(s, now)
    ]
    total = len(subs)
    concluidas = len(concluidas_reais)
    abertas = total - concluidas
    no_prazo = sum(
        1
        for s in concluidas_reais
        if s.data_vencimento and s.data_conclusao and _dia(s.data_conclusao) <= _dia(s.data_vencimento)
    )

    def _aberta_atrasada(s: Subtarefa) -> bool:
        if s.data_conclusao and not _is_recorrente_aberta(s, now):
            return False
        if _is_recorrente_aberta(s, now):
            return False
        if _is_recorrente_vencida(s, now):
            return True
        return bool(s.data_vencimento and _dia(s.data_vencimento) < _dia(now))

    abertas_atrasadas = sum(1 for s in subs if _aberta_atrasada(s))
    atrasadas = (len(concluidas_reais) - no_prazo) + abertas_atrasadas
    base_denom = no_prazo + atrasadas
    percentual_no_prazo = (no_prazo / base_denom * 100) if base_denom > 0 else 100.0

    if is_apenas_ads:
        return ExecutionResult(
            None,
            "Cliente com serviço apenas 'ADS para Marketplace' — score não avaliado (rotina específica).",
        )

    tem_outro_plano = bool(
        re.search(r"\b(b[1-5]|assessoria|start|traction|scale|platinum|elite)\b", servico, re.I)
    )
    if is_implantacao and not tem_outro_plano:
        if not cliente.data_venda:
            return ExecutionResult(
                None, "Cliente em Implantação sem data de venda registrada — idade do contrato indisponível."
            )
        meses = (now - cliente.data_venda).total_seconds() / (86400 * _MONTH_DAYS)
        m = round(meses * 10) / 10
        if meses < 6:
            return ExecutionResult(85, f"Implantação dentro do prazo: {m} meses desde a venda (limite saudável: <6m).")
        if meses <= 9:
            return ExecutionResult(55, f"Implantação em alerta: {m} meses desde a venda (entre 6 e 9 meses).")
        return ExecutionResult(25, f"Implantação crítica: {m} meses desde a venda (>9 meses, processo deveria ter encerrado).")

    score = 100.0
    motivos: list[str] = []

    if abertas_atrasadas > 0:
        pen = min(35, abertas_atrasadas * 8)
        score -= pen
        motivos.append(f"−{pen}: {abertas_atrasadas} atividade(s) em aberto e atrasada(s).")

    concluidas_com_atraso_2sem = sum(
        1
        for s in concluidas_reais
        if s.data_conclusao
        and s.data_vencimento
        and s.data_conclusao >= duas_semanas_atras
        and _dia(s.data_conclusao) > _dia(s.data_vencimento)
    )
    if concluidas_com_atraso_2sem > 0:
        pen = min(20, concluidas_com_atraso_2sem * 5)
        score -= pen
        motivos.append(f"−{pen}: {concluidas_com_atraso_2sem} atividade(s) concluída(s) com atraso nas últimas 2 semanas.")

    conclusoes_por_dia: dict[str, int] = {}
    for s in concluidas_reais:
        if s.data_conclusao and s.data_conclusao >= duas_semanas_atras:
            key = s.data_conclusao.date().isoformat()
            conclusoes_por_dia[key] = conclusoes_por_dia.get(key, 0) + 1
    max_batch = max(conclusoes_por_dia.values(), default=0)
    if max_batch >= 4:
        pen = min(15, (max_batch - 3) * 4)
        score -= pen
        motivos.append(f"−{pen}: {max_batch} atividades encerradas no mesmo dia (batch suspeito).")

    conclusoes_ult_2sem = sum(
        1 for s in concluidas_reais if s.data_conclusao and s.data_conclusao >= duas_semanas_atras
    )
    total_atividades_periodo = abertas + conclusoes_ult_2sem
    if total_atividades_periodo <= 3:
        score -= 10
        motivos.append(
            f"−10: apenas {total_atividades_periodo} atividade(s) movimentada(s) nas últimas 2 semanas (cliente pouco trabalhado)."
        )

    if cliente.data_venda:
        meses = (now - cliente.data_venda).total_seconds() / (86400 * _MONTH_DAYS)
        if meses <= 3:
            if cliente.data_onboarding:
                dias = _dias_uteis_entre(cliente.data_venda, cliente.data_onboarding)
                if dias > 3:
                    pen = min(15, (dias - 3) * 3)
                    score -= pen
                    motivos.append(f"−{pen}: onboarding ocorreu {dias} dias úteis após a venda (limite: 3).")
            else:
                dias_desde_venda = _dias_uteis_entre(cliente.data_venda, now)
                if dias_desde_venda > 3:
                    score -= 12
                    motivos.append(f"−12: sem reunião de onboarding registrada (venda há {dias_desde_venda} dias úteis).")

    if postergacoes_2_semanas > 0:
        pen = min(15, postergacoes_2_semanas * 4)
        score -= pen
        motivos.append(f"−{pen}: {postergacoes_2_semanas} alteração(ões) de prazo postergando vencimentos nas últimas 2 semanas.")

    if conclusoes_ult_2sem == 0 and abertas > 0:
        score -= 8
        motivos.append("−8: nenhuma atividade concluída nas últimas 2 semanas (sem entregas recentes).")

    if len(conclusoes_por_dia) >= 3 and max_batch < 4:
        score += 5
        motivos.append("+5: cadência saudável — entregas distribuídas em vários dias.")

    if base_denom >= 3 and percentual_no_prazo < 60:
        pen = round((60 - percentual_no_prazo) / 4)
        score -= pen
        motivos.append(f"−{pen}: apenas {round(percentual_no_prazo)}% das atividades com vencimento foram entregues no prazo.")

    score = max(0.0, min(100.0, round(score)))
    if not motivos:
        motivos.append("Cliente sem ocorrências negativas no período avaliado.")
    return ExecutionResult(score, " | ".join(motivos))
