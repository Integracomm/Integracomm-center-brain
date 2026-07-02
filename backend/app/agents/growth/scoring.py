"""Fórmula de score de saúde / risco de churn (Growth) — pesos aprovados.

Desenho aprovado pelo Otávio (2026-06-26) a partir da calibração caso-controle:
- LÍDERES (disparam o alerta), medidos como TRAJETÓRIA vs. baseline da conta:
    engajamento relacional (peso 45) e tom (peso 25).
- SECUNDÁRIO: execução ClickUp (peso 15) — ver flag PROVISIONAL abaixo.
- TARDIOS (confirmam, não antecipam): CRÍTICO explícito / financeiro (peso 15).

O score é 0–100 (100 = saudável). O gatilho do alerta é a *tendência* cruzar
para risco — idealmente já no estágio de desengajamento inicial.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from ..base import AccountScore, DeclineStage, SignalReason, Trajectory
from .trajectory import Point, analyze_series

# ---------------------------------------------------------------------------
# Pesos por bloco (somam 100). Aprovados 45/25/15/15.
#
# EXECUÇÃO ATIVA como CONFIRMADOR (2026-07-01, pedido do Otávio; flag
# EXECUTION_IN_SCORE no runner, default ligado). Evidência completa:
#  - NÃO prediz churn sozinha (revalidação churn-30/-60, port fiel: AUC 0,49/0,44
#    — cancelados eram bem atendidos até sair). Ver scripts/validate_execution.py.
#  - A 15% renormalizado NÃO degrada o ranking (AUC coorte 0,822→0,820, neutro)
#    e traz atrito de entrega para o score/motivos. Ver scripts/offline_exec_in_score.py.
# O sinal entra como direct_risk (1 - exec_score/100) computado pelo runner via
# mirror ClickUp (execution_collector.execution_asof). Sem sinal -> bloco ausente,
# renormaliza fora (não pune ausência).
# ---------------------------------------------------------------------------
WEIGHTS: dict[str, int] = {
    "engagement": 45,   # líder forte — desengajamento (silêncio↑, iniciativa↓, freq↓)
    "tone": 25,         # líder forte — virada de tom (negativo↑, mensagem encurta)
    "execution": 15,    # PROVISIONAL — ver bloco acima
    "lagging": 15,      # tardio — CRÍTICO explícito / inadimplência (confirmador)
}
_EXECUTION_IS_PROVISIONAL = True  # exposto para a UI/auditoria sinalizarem

# Blend nível-absoluto x relativo no risco de UM sinal (só p/ sinais com escala
# absoluta de risco — ver SignalInput.absolute_is_risk). Calibração caso-controle:
# o modelo só-relativo APAGA a diferença absoluta validada (churner sempre-quieto
# não desvia do próprio baseline) -> AUC de ranking caía a ~0,5. Trazer o NÍVEL
# de volta recupera a ordenação. Varredura offline (silêncio+tom): AUC 0,65 (só
# relativo) -> 0,75 (só absoluto) -> 0,77 (blend). Platô 0,6–0,8; 0,6 conservador.
_ABSOLUTE_BLEND = 0.6  # peso do nível absoluto; (1-_ABSOLUTE_BLEND) fica no relativo

# Cobertura mínima (semanas distintas com sinal LÍDER de WhatsApp) p/ a conta ser
# AVALIÁVEL. Abaixo disso a ausência de dado vira "saudável 100" — a pior falha
# (cancelando em silêncio aparece perfeito). Validação caso-controle: 11/44
# cancelados tinham 0–1 semana e pontuavam 100; o gate ≥2 sobe o AUC de 0,59
# (tudo) p/ 0,79. Conta não avaliável NÃO entra no ranking de saúde — vai p/ a
# lista "revisar manualmente".
MIN_COVERAGE_WEEKS = 2
_BAND_NO_DATA = "sem_dados"

# Peso INTRA-bloco por sinal (down-weight aprovado 2026-06-30, opção A): silêncio e
# tom negativo são os líderes fortes (têm escala absoluta, validados no caso-controle);
# iniciativa e comprimento são secundários/relativos e, com peso igual, dominavam o
# bloco e adicionavam ruído (validação ao vivo: modelo completo 0,52 < só líderes 0,61).
# Rebaixados a confirmadores — entram no score e nos "motivos", mas não mandam.
# Bloco = média PONDERADA dos sinais presentes; sinal sem peso definido -> 1,0 (igual).
_INTRA_BLOCK_WEIGHT: dict[str, float] = {
    "silencio": 0.75,
    "iniciativa_cliente": 0.25,
    "tom_negativo": 0.75,
    "comprimento_msg": 0.25,
    # tom via Claude (3b): série semanal caloroso/neutro/transacional/negativo -> risco.
    # Peso intermediário (novo sinal, ainda não calibrado contra outcomes) — completa
    # o bloco tone junto com tom_negativo (Gemini) e comprimento_msg.
    "tom_claude": 0.5,
}
_DEFAULT_INTRA_WEIGHT = 1.0


@dataclass
class SignalInput:
    """Um sinal de uma conta, como série temporal, pronto para virar risco."""

    key: str                      # ex.: "silencio", "iniciativa_cliente", "tom_negativo"
    block: str                    # engagement | tone | execution | lagging
    points: list[Point]           # série cronológica (data, valor)
    higher_is_worse: bool         # True: valor alto = risco (ex.: silêncio)
    source: str = "whatsapp"      # whatsapp | clickup | omie | ml_connect
    direct_risk: float | None = None  # risco 0–1 pré-computado (confirmadores tardios:
    #                                   CRÍTICO/fala-em-cancelar; ignora trajetória/baseline)
    absolute_is_risk: bool = False  # o VALOR do sinal já é um risco 0–1 com escala
    #   absoluta (ex.: %dias-em-silêncio, %dias-negativos) — higher_is_worse e em
    #   [0,1]. Quando True, o risco mistura nível absoluto + trajetória (ver
    #   _ABSOLUTE_BLEND). Sinais sem "normal" absoluto (contagem/comprimento) ficam
    #   False = puramente relativos ao baseline da conta.
    is_exit_signal: bool = False  # confirmador tardio que representa FALA EXPLÍCITA de
    #   saída (regex de cancelamento). SÓ isto dispara o estágio "intenção de saída".
    #   CRÍTICO recente do Gemini (insatisfação grave) NÃO é fala de saída -> fica em
    #   "insatisfação ativa" (era o falso-positivo da WMA: cobrar resposta ≠ querer sair).


# Faixas de estágio por risco total (0–1). O alerta deve disparar já em
# EARLY_DISENGAGEMENT, não só na intenção de saída.
_STAGE_BANDS: list[tuple[float, DeclineStage]] = [
    (0.20, DeclineStage.HEALTHY),
    (0.40, DeclineStage.EARLY_DISENGAGEMENT),
    (0.60, DeclineStage.LATENT_DISSATISFACTION),
    (0.80, DeclineStage.ACTIVE_DISSATISFACTION),
    (1.01, DeclineStage.EXIT_INTENT),
]


def signal_risk(sig: SignalInput) -> tuple[float, SignalTrajectoryView]:
    """Converte um sinal em risco 0–1 (1 = pior), via desvio do baseline + velocidade.

    Confirmadores tardios (com `direct_risk`) entram com o risco já pronto — não
    passam por baseline/velocidade (um "quero cancelar" não é tendência, é fato).
    """
    if sig.direct_risk is not None:
        r = max(0.0, min(1.0, sig.direct_risk))
        return r, SignalTrajectoryView(sig.key, sig.block, sig.source, r, 0.0, sig.higher_is_worse)
    tr = analyze_series(sig.points)
    # desvio na direção "ruim"
    dev = tr.deviation if sig.higher_is_worse else -tr.deviation
    # velocidade na direção "ruim" (piorando)
    vel = tr.velocity if sig.higher_is_worse else -tr.velocity
    # risco RELATIVO = combinação saturada de desvio e velocidade (ambos relativos)
    dev_risk = _squash(dev)            # quão longe do normal, no sentido ruim
    vel_risk = _squash(vel * 30)       # tendência ~mensal piorando
    risk = max(0.0, min(1.0, 0.6 * dev_risk + 0.4 * vel_risk))
    # Para sinais com escala absoluta de risco (silêncio, tom negativo), mistura o
    # NÍVEL absoluto — senão o churner sempre-quieto (que nunca desvia do próprio
    # baseline) marca risco ~0 mesmo cronicamente ruim. Nível = média da janela.
    if sig.absolute_is_risk and sig.points:
        abs_level = max(0.0, min(1.0, _mean([v for _, v in sig.points])))
        risk = max(0.0, min(1.0, _ABSOLUTE_BLEND * abs_level + (1 - _ABSOLUTE_BLEND) * risk))
    return risk, SignalTrajectoryView(sig.key, sig.block, sig.source, risk, tr.velocity, sig.higher_is_worse)


def score_account(
    account_id: str,
    account_name: str,
    signals: list[SignalInput],
    *,
    plan_category: str | None = None,
    is_legacy: bool = False,
    recurring_revenue: float | None = None,
    now: dt.datetime | None = None,
) -> AccountScore:
    """Compõe o score 0–100 + trajetória + estágio + motivos a partir dos sinais."""
    now = now or dt.datetime.now(dt.timezone.utc)

    # risco por bloco (média PONDERADA dos sinais do bloco) e visão por sinal p/ motivos
    by_block: dict[str, list[float]] = {}
    wt_by_block: dict[str, list[float]] = {}  # pesos intra-bloco alinhados a by_block
    views: list[SignalTrajectoryView] = []
    for sig in signals:
        r, view = signal_risk(sig)
        by_block.setdefault(sig.block, []).append(r)
        wt_by_block.setdefault(sig.block, []).append(
            _INTRA_BLOCK_WEIGHT.get(sig.key, _DEFAULT_INTRA_WEIGHT)
        )
        views.append(view)

    # (b) Renormaliza sobre os blocos PRESENTES. Um bloco sem nenhum sinal (ex.:
    # execução ainda não ligada) NÃO entra no denominador — senão sua fração do
    # peso vira "risco 0" e infla o score, creditando ausência como saúde.
    present_w = sum(WEIGHTS[b] for b in WEIGHTS if by_block.get(b))
    risk_total = 0.0
    if present_w > 0:
        for block in WEIGHTS:
            risks = by_block.get(block)
            if not risks:
                continue
            wts = wt_by_block[block]
            wsum = sum(wts)
            # média ponderada; pesos renormalizam sobre os sinais PRESENTES do bloco
            # (se só silêncio veio, ele vale 1 — não é penalizado por iniciativa ausente)
            block_risk = sum(w * r for w, r in zip(wts, risks)) / wsum if wsum else sum(risks) / len(risks)
            risk_total += (WEIGHTS[block] / present_w) * block_risk

    health = round(100 * (1 - risk_total), 1)

    # trajetória: média PONDERADA (mesmos pesos do score: bloco × intra-bloco) das
    # velocidades de saúde. Sem ponderar, iniciativa/comprimento (relativos,
    # ruidosos, rebaixados no score p/ 0,25) dominavam a trajetória e geravam
    # "caindo" falso — 61% da carteira caindo na 1ª rodada real. Exclui
    # confirmadores diretos (lagging não tem tendência, velocidade é sempre 0).
    mean_health_velocity = _weighted_health_velocity(signals, views, present_w)
    trajectory = _trajectory_from_velocity(mean_health_velocity)
    sustained = _sustained_rising(signals)  # melhora persiste >1 período? (não é pico isolado)

    # fala explícita de saída (regex de cancelamento) = único gatilho de intenção de saída
    exit_explicit = any(
        sig.is_exit_signal and (sig.direct_risk or 0.0) >= 0.6 for sig in signals
    )
    stage = _stage(risk_total, by_block, trajectory, sustained, exit_explicit=exit_explicit)
    band = _risk_band(health)
    confidence = _confidence(signals)
    lead = _lead_time_days(risk_total, mean_health_velocity)
    reasons = _reasons(views)
    rec = _recommendation(stage, is_legacy)

    # Gate de cobertura: sem semanas suficientes de sinal líder, a conta NÃO é
    # avaliável (ausência de dado não é saúde). Marca a faixa e a recomendação p/
    # a lista de revisão manual; o alerta automático fica suprimido (ver alert_severity).
    coverage_weeks = _coverage_weeks(signals)
    evaluable = coverage_weeks >= MIN_COVERAGE_WEEKS
    if not evaluable:
        band = _BAND_NO_DATA
        rec = (f"Sem dados suficientes de WhatsApp ({coverage_weeks} semana(s) de cobertura, "
               f"mínimo {MIN_COVERAGE_WEEKS}) — NÃO avaliável automaticamente. Revisar manualmente.")

    return AccountScore(
        account_id=account_id,
        account_name=account_name,
        score=health,
        trajectory=trajectory,
        velocity=round(mean_health_velocity, 4),
        stage=stage,
        risk_band=band,
        lead_time_days=lead,
        confidence=confidence,
        coverage_weeks=coverage_weeks,
        evaluable=evaluable,
        reasons=reasons,
        recommendation=rec,
        plan_category=plan_category,
        is_legacy=is_legacy,
        recurring_revenue=recurring_revenue,
        computed_at=now,
    )


def alert_severity(score: AccountScore) -> str | None:
    """Severidade do alerta (None = sem alerta). Três níveis:

    - `critico`: saída confirmada (estágio intenção de saída) ou faixa `critico`;
    - `alto`: insatisfação ativa, faixa `alto`, ou `medio` + trajetória caindo;
    - `atencao`: faixa `baixo` MAS já CAINDO — o churner quieto (cancela em
      silêncio). Severidade branda, mas não pode passar sem registro.

    Conta NÃO avaliável (sem cobertura) não gera alerta automático — não dá pra
    afirmar risco sem dado; vai p/ a lista de revisão manual.
    """
    if not score.evaluable:
        return None
    if score.stage == DeclineStage.EXIT_INTENT or score.risk_band == "critico":
        return "critico"
    if (
        score.stage == DeclineStage.ACTIVE_DISSATISFACTION
        or score.risk_band == "alto"
        or (score.risk_band == "medio" and score.trajectory == Trajectory.FALLING)
    ):
        return "alto"
    if score.risk_band == "baixo" and score.trajectory == Trajectory.FALLING:
        return "atencao"
    return None


def should_alert(score: AccountScore) -> bool:
    """Dispara alerta se houver qualquer severidade (ver `alert_severity`)."""
    return alert_severity(score) is not None


_MRR_ALTO = 3000.0  # limiar de "conta valiosa" p/ a diretriz de manutenção

# Tática específica pela DOR dominante (sinal de maior peso) — personaliza a
# diretriz ao que está realmente puxando o risco daquele cliente.
_DRIVER_TATICA: dict[str, str] = {
    "silencio": "Dor principal: SILÊNCIO — o cliente parou de conversar. Reabra o canal com "
                "um motivo concreto de valor (um resultado recente, um próximo passo) e confirme "
                "se as entregas estão chegando.",
    "tom_negativo": "Dor principal: TOM NEGATIVO recorrente. Faça escuta ativa para achar a "
                    "queixa específica ANTES de propor solução — não parta para oferta sem entender a causa.",
    "iniciativa_cliente": "Dor principal: queda de INICIATIVA — o cliente não procura mais a "
                          "gente. Traga valor proativamente para reativar o diálogo; não espere ele chamar.",
    "comprimento_msg": "Dor principal: mensagens ENCURTANDO (desengajamento). Aprofunde com "
                       "perguntas abertas e um contato mais próximo.",
    "fala_em_cancelar": "Gatilho: o cliente FALOU EM SAIR. Ouça o motivo real antes de qualquer proposta.",
    "critico_recente": "Gatilho: EVENTO CRÍTICO recente. Enderece diretamente o que gerou a irritação.",
    "tom_claude": "Dor principal: o TOM da conversa esfriou/azedou (análise semanal). Revise as "
                  "últimas trocas antes da reunião e enderece o que mudou o clima.",
}


def _top_driver(reasons) -> str | None:
    """Chave do sinal de MAIOR peso (a dor dominante), a partir dos motivos."""
    if not reasons:
        return None
    top = max(reasons, key=lambda r: r.get("weight", 0) if isinstance(r, dict) else 0)
    text = top.get("text", "") if isinstance(top, dict) else str(top)
    return text.split(":")[0].strip() or None


def action_guideline(
    stage: "DeclineStage | str",
    *,
    is_legacy: bool = False,
    recurring_revenue: float | None = None,
    evaluable: bool = True,
    reasons: list | None = None,
    exec_score: float | None = None,
) -> str:
    """Diretriz de ação PERSONALIZADA — norte para o gestor antes da reunião.
    Compõe: (1) headline pela jornada (estágio), (2) tática pela DOR dominante
    (sinal de maior peso), (3) alerta de EXECUÇÃO se houver atraso no ClickUp
    (pode ser a raiz da insatisfação), (4) ênfase de MRR. Overrides:
    não-avaliável e legado. Determinística (sem custo de API); os motivos/execução
    vêm do que já temos de cada cliente."""
    s = stage.value if isinstance(stage, DeclineStage) else str(stage)
    if not evaluable:
        return ("Revisar manualmente — sem histórico de conversa suficiente para avaliar. "
                "Confirmar se o grupo está ativo.")
    if is_legacy:
        return ("Abordar migração — conta em plano descontinuado; priorizar oferta de "
                "upgrade para bundle novo.")
    mrr = float(recurring_revenue) if recurring_revenue else 0.0
    high_mrr = mrr >= _MRR_ALTO
    headline = {
        DeclineStage.EXIT_INTENT.value: "Contato imediato do gestor/líder — cliente sinalizou saída.",
        DeclineStage.ACTIVE_DISSATISFACTION.value: "Ação urgente — insatisfação ativa; enderece o problema agora.",
        DeclineStage.LATENT_DISSATISFACTION.value: "Reunião de alinhamento — insatisfação latente; agir antes que escale.",
        DeclineStage.EARLY_DISENGAGEMENT.value: "Retomada de contato proativo — reengajar cedo.",
        DeclineStage.HEALTHY.value: ("Manutenção de relacionamento — conta valiosa estável; check-in de valor."
                                     if high_mrr else "Sem ação crítica — manter acompanhamento padrão."),
    }.get(s, "")
    parts = [headline]
    if s != DeclineStage.HEALTHY.value:
        tatica = _DRIVER_TATICA.get(_top_driver(reasons) or "")
        if tatica:
            parts.append(tatica)
        if exec_score is not None and exec_score < 70:
            parts.append(f"⚠️ Execução com pendências (ClickUp {exec_score:.0f}/100) — regularize ou "
                         "explique as entregas antes da conversa; pode ser a raiz da insatisfação.")
    if high_mrr:
        parts.append(f"💰 Alto valor (R$ {mrr:,.0f}".replace(",", ".") + ") — priorize; envolva a liderança se necessário.")
    return " ".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
@dataclass
class SignalTrajectoryView:
    key: str
    block: str
    source: str
    risk: float
    velocity: float
    higher_is_worse: bool


def _squash(x: float) -> float:
    """Mapeia desvio/velocidade relativos para 0–1 de forma saturada (~logística)."""
    import math

    return 1 / (1 + math.exp(-2.5 * x)) * 2 - 1 if x > 0 else 0.0


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _weighted_health_velocity(signals, views, present_w: float) -> float:
    """Velocidade de saúde COMENSURÁVEL e ponderada, para a trajetória.

    Problema que isto resolve: as velocidades brutas dos sinais estão em unidades
    DIFERENTES (silêncio/tom em fração 0–1; iniciativa em contagem; comprimento em
    caracteres). Somá-las — mesmo ponderando — deixa comprimento/iniciativa (bruto
    grande) dominarem e gerarem "caindo" falso (61% da carteira na 1ª rodada real).

    Solução: mede a trajetória pela MUDANÇA DE NÍVEL dos sinais de risco ABSOLUTO
    (silêncio, tom — os líderes validados, ambos frações 0–1, logo comparáveis),
    comparando a metade RECENTE vs a metade ANTIGA da série. Nível de risco caindo
    => saúde subindo. Ponderado pelos mesmos pesos do score (bloco × intra-bloco).
    Sinais sem escala absoluta (iniciativa/comprimento) não entram na trajetória —
    são secundários e ruidosos; entram só no nível do score.
    """
    intra_sum: dict[str, float] = {}
    for sig in signals:
        if sig.absolute_is_risk:
            intra_sum[sig.block] = intra_sum.get(sig.block, 0.0) + _INTRA_BLOCK_WEIGHT.get(
                sig.key, _DEFAULT_INTRA_WEIGHT
            )
    num = den = 0.0
    for sig in signals:
        if not sig.absolute_is_risk or present_w <= 0:
            continue
        if sig.block not in WEIGHTS or not intra_sum.get(sig.block):
            continue
        pts = sorted(sig.points, key=lambda p: p[0])
        if len(pts) < 2:
            continue
        mid = len(pts) // 2
        old_level = _mean([v for _, v in pts[:mid]] or [v for _, v in pts])
        new_level = _mean([v for _, v in pts[mid:]] or [v for _, v in pts])
        # higher_is_worse (silêncio/tom): nível caindo => risco caindo => saúde subindo
        health_vel = old_level - new_level
        w = (WEIGHTS[sig.block] / present_w) * (
            _INTRA_BLOCK_WEIGHT.get(sig.key, _DEFAULT_INTRA_WEIGHT) / intra_sum[sig.block]
        )
        num += w * health_vel
        den += w
    return num / den if den else 0.0


def _trajectory_from_velocity(health_velocity: float) -> Trajectory:
    if health_velocity <= -0.05:
        return Trajectory.FALLING
    if health_velocity >= 0.05:
        return Trajectory.RISING
    return Trajectory.STABLE


# Ordem dos estágios (índice 0 = saudável ... 4 = intenção de saída).
_STAGE_ORDER: list[DeclineStage] = [s for _, s in _STAGE_BANDS]

# Ajuste de estágio pela TRAJETÓRIA: a conta só AVANÇA na jornada quando a
# deterioração é sustentada (caindo); se está estável ou subindo, segura/recua.
_TRAJECTORY_OFFSET: dict[Trajectory, int] = {
    Trajectory.FALLING: 0,    # deterioração sustentada -> ocupa o nível cheio
    Trajectory.STABLE: -1,    # parado num nível -> um passo atrás do nível
    Trajectory.RISING: -2,    # recuperando -> recua mais
    Trajectory.UNKNOWN: -1,   # sem trajetória confiável -> conservador como estável
}


def _level_index(risk_total: float) -> int:
    """Profundidade pelo nível de risco (0..4), sem trajetória."""
    for i, (threshold, _) in enumerate(_STAGE_BANDS):
        if risk_total < threshold:
            return i
    return len(_STAGE_ORDER) - 1


def _stage(
    risk_total: float,
    by_block: dict[str, list[float]],
    trajectory: Trajectory,
    sustained: bool = True,
    exit_explicit: bool = False,
) -> DeclineStage:
    # 1) FALA EXPLÍCITA de saída (regex de cancelamento) é o ÚNICO gatilho de
    #    "intenção de saída" — único sinal inequívoco de que o cliente quer sair.
    if exit_explicit:
        return DeclineStage.EXIT_INTENT
    # 2) nível dá a profundidade potencial; trajetória decide quanto dela ocupa
    level = _level_index(risk_total)
    offset = _TRAJECTORY_OFFSET[trajectory]
    # 3) guarda de melhora sustentada: um "subindo" de pico isolado (não confirmado
    #    em 2+ períodos) rebaixa no máximo 1 estágio (recuperando), não saudável pleno.
    if trajectory == Trajectory.RISING and not sustained:
        offset = -1
    idx = max(0, min(len(_STAGE_ORDER) - 1, level + offset))
    # 4) CRÍTICO recente / inadimplência (lagging forte) SEM fala de saída é problema
    #    crítico ATUAL — piso em insatisfação ativa. Mas sem a fala explícita NÃO
    #    chega a "intenção de saída": o teto é insatisfação ativa (a urgência do
    #    alerta crítico, quando faixa crítica, vem da faixa, não do estágio).
    active_idx = _STAGE_ORDER.index(DeclineStage.ACTIVE_DISSATISFACTION)
    if max(by_block.get("lagging") or [0.0]) >= 0.6:
        idx = max(idx, active_idx)
    idx = min(idx, active_idx)
    return _STAGE_ORDER[idx]


def _health_velocity(points: list[Point], higher_is_worse: bool) -> float:
    """Velocidade no sentido da SAÚDE (positivo = melhorando) para um sinal."""
    v = analyze_series(points).velocity
    return -v if higher_is_worse else v


def _sustained_rising(signals: list[SignalInput]) -> bool:
    """Melhora é sustentada (não pico isolado): para os sinais que estão melhorando,
    a melhora persiste mesmo removendo o período mais recente. Maioria decide."""
    votes: list[bool] = []
    for sig in signals:
        if sig.direct_risk is not None:
            continue
        pts = sorted(sig.points, key=lambda p: p[0])
        if len(pts) < 3:
            continue
        full = _health_velocity(pts, sig.higher_is_worse)
        if full > 0.0:  # este sinal está melhorando
            without_last = _health_velocity(pts[:-1], sig.higher_is_worse)
            votes.append(without_last > 0.0)  # AINDA melhora sem o último ponto? (não é pico)
    return bool(votes) and (sum(votes) / len(votes) >= 0.5)


def _risk_band(health: float) -> str:
    if health > 70:
        return "baixo"
    if health > 50:
        return "medio"
    if health > 30:
        return "alto"
    return "critico"


def _coverage_weeks(signals: list[SignalInput]) -> int:
    """Semanas DISTINTAS com sinal líder de WhatsApp (engagement/tone, não-tardio).
    É a base da avaliabilidade: poucas semanas = ausência de dado, não saúde."""
    weeks = {
        p[0]
        for s in signals
        if s.block in ("engagement", "tone") and s.direct_risk is None
        for p in s.points
    }
    return len(weeks)


def _confidence(signals: list[SignalInput]) -> float:
    """Confiança 0–1: cresce com nº de pontos e alcance temporal dos sinais."""
    if not signals:
        return 0.0
    spans = []
    for s in signals:
        pts = sorted(s.points, key=lambda p: p[0])
        if len(pts) >= 2:
            spans.append((pts[-1][0] - pts[0][0]).days)
    if not spans:
        return 0.1
    avg_span = sum(spans) / len(spans)
    # 60+ dias de histórico ~ confiança plena; pouco histórico = baixa
    return round(max(0.1, min(1.0, avg_span / 60)), 2)


def _lead_time_days(risk_total: float, health_velocity: float) -> int | None:
    """Estimativa grosseira de antecedência: quão cedo (estágio baixo) + quão rápido cai."""
    if health_velocity >= 0:
        return None
    # quanto mais saudável ainda e mais rápida a queda, maior a antecedência detectada
    return int(max(7, min(120, (1 - risk_total) * 120)))


def _reasons(views: list[SignalTrajectoryView]) -> list[SignalReason]:
    out: list[SignalReason] = []
    for v in sorted(views, key=lambda x: x.risk, reverse=True):
        if v.risk < 0.15:
            continue
        leading = v.block in ("engagement", "tone")
        out.append(
            SignalReason(
                source=v.source,
                text=f"{v.key}: risco {round(v.risk * 100)}% (tendência {'piorando' if v.velocity != 0 else 'estável'})",
                leading=leading,
                weight=round(v.risk * WEIGHTS.get(v.block, 0), 1),
            )
        )
    return out


def _recommendation(stage: DeclineStage, is_legacy: bool) -> str:
    if is_legacy:
        return ("Conta legado em sunset: priorizar MIGRAÇÃO para bundle novo, "
                "não retenção genérica. Apresentar proposta de upgrade.")
    rec = {
        DeclineStage.HEALTHY: "Sem ação — manter acompanhamento padrão.",
        DeclineStage.EARLY_DISENGAGEMENT: "Reengajar proativamente: o cliente está reduzindo iniciativa/conversa. Buscar contato de valor (resultado recente, próximos passos).",
        DeclineStage.LATENT_DISSATISFACTION: "Investigar insatisfação latente: revisar entregas e tom recente; ligar para o cliente.",
        DeclineStage.ACTIVE_DISSATISFACTION: "Insatisfação ativa: escalar para o gestor da conta; plano de recuperação com prazos.",
        DeclineStage.EXIT_INTENT: "Risco de saída iminente: intervenção do líder de Growth; proposta de retenção concreta.",
    }
    return rec[stage]
