"""Contrato comum a todos os agentes da casca.

Um agente é um módulo que implementa este contrato e se registra no
``registry``. Adicionar um novo agente (Marketing, Financeiro, etc.) é
escrever uma subclasse e registrá-la — a casca (backend, RBAC, painel,
auditoria) não precisa ser reaberta.

Ciclo de processamento (todas as etapas são auditadas):

    collect()  -> lê as fontes em modo SOMENTE LEITURA, em janela incremental
    analyze()  -> interpreta os sinais (Claude para o qualitativo)
    score()    -> deriva score 0-100 + trajetória + estágio + motivos
    persist()  -> grava score/alerta/auditoria no Postgres próprio
    surface()  -> expõe o resultado no painel, sob o papel (RBAC) correto

Princípios inegociáveis aplicados aqui:
- Nenhuma etapa escreve nas fontes de origem nem executa ação consequente.
- Toda leitura de dado sensível e todo score/alerta gera registro de auditoria.
"""
from __future__ import annotations

import abc
import datetime as dt
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Trajectory(str, Enum):
    """Direção da tendência do score ao longo do tempo (o preditor central)."""

    RISING = "subindo"
    STABLE = "estavel"
    FALLING = "caindo"
    UNKNOWN = "desconhecida"


class DeclineStage(str, Enum):
    """Estágio na jornada de saída — o alerta deve vir cedo (desengajamento)."""

    HEALTHY = "saudavel"
    EARLY_DISENGAGEMENT = "desengajamento_inicial"
    LATENT_DISSATISFACTION = "insatisfacao_latente"
    ACTIVE_DISSATISFACTION = "insatisfacao_ativa"
    EXIT_INTENT = "intencao_de_saida"


@dataclass(frozen=True)
class SignalReason:
    """Motivo explicável de um score, rastreável à fonte e ao tipo (líder/tardio)."""

    source: str  # whatsapp | clickup | pipedrive | omie | ml_connect
    text: str
    leading: bool  # True = indicador líder (antecede); False = tardio (confirma)
    weight: float = 0.0


@dataclass
class AccountScore:
    """Saída por conta — calcula, exibe e sinaliza; nunca age."""

    account_id: str
    account_name: str
    score: float  # 0-100
    trajectory: Trajectory
    velocity: float  # variação por dia (negativa = piorando)
    stage: DeclineStage
    risk_band: str  # baixo | medio | alto | critico
    lead_time_days: int | None  # antecedência estimada do alerta
    confidence: float  # 0-1
    coverage_weeks: int = 0  # semanas distintas com sinal LÍDER (WhatsApp) na janela
    evaluable: bool = True    # False = sem dados suficientes -> NÃO ranquear como saúde;
    #                           vai p/ lista "revisar manualmente" (ausência ≠ saudável)
    reasons: list[SignalReason] = field(default_factory=list)
    recommendation: str = ""  # texto para o time de Growth — sem executar nada
    plan_category: str | None = None  # B1-START..B5-ELITE | Planos Antigos
    is_legacy: bool = False  # legado em sunset -> ação = priorizar migração
    recurring_revenue: float | None = None  # pondera contas de maior receita
    computed_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.timezone.utc))


@dataclass
class AgentContext:
    """Janela e dependências injetadas pela casca em cada execução."""

    window_start: dt.datetime
    window_end: dt.datetime
    run_id: str
    audit: "AuditSink"
    incremental_cursor: dict[str, Any] = field(default_factory=dict)


class AuditSink(abc.ABC):
    """Toda leitura sensível / score / alerta passa por aqui (quem, o quê, quando)."""

    @abc.abstractmethod
    def record_read(self, *, source: str, scope: str, run_id: str) -> None: ...

    @abc.abstractmethod
    def record_score(self, *, score: AccountScore, run_id: str) -> None: ...

    @abc.abstractmethod
    def record_alert(self, *, score: AccountScore, run_id: str) -> None: ...


class Agent(abc.ABC):
    """Classe-base do contrato. Subclasses implementam as cinco etapas."""

    #: identificador estável usado no registry e no RBAC (ex.: "growth")
    key: str
    #: papel que pode ver este agente no painel (ex.: "gestor_growth")
    role: str

    @abc.abstractmethod
    def collect(self, ctx: AgentContext) -> Any:
        """Lê as fontes em modo somente leitura, em janela incremental."""

    @abc.abstractmethod
    def analyze(self, ctx: AgentContext, raw: Any) -> Any:
        """Interpreta os sinais coletados (qualitativo via Claude)."""

    @abc.abstractmethod
    def score(self, ctx: AgentContext, analyzed: Any) -> list[AccountScore]:
        """Deriva score 0-100 + trajetória + estágio + motivos por conta."""

    @abc.abstractmethod
    def persist(self, ctx: AgentContext, scores: list[AccountScore]) -> None:
        """Grava scores/alertas/auditoria no Postgres próprio (derivados)."""

    @abc.abstractmethod
    def surface(self, ctx: AgentContext, scores: list[AccountScore]) -> None:
        """Expõe no painel sob o papel correto (RBAC)."""

    def run(self, ctx: AgentContext) -> list[AccountScore]:
        """Orquestra o ciclo. A casca chama isto na agenda (ex.: diária)."""
        raw = self.collect(ctx)
        analyzed = self.analyze(ctx, raw)
        scores = self.score(ctx, analyzed)
        self.persist(ctx, scores)
        self.surface(ctx, scores)
        return scores
