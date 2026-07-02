"""Specs da fórmula de score de churn. Rodar com pytest no host de staging."""
import datetime as dt

from app.agents.base import AccountScore, DeclineStage, Trajectory
from app.agents.growth.scoring import (
    SignalInput,
    WEIGHTS,
    _ABSOLUTE_BLEND,
    _stage,
    _sustained_rising,
    action_guideline,
    alert_severity,
    score_account,
    should_alert,
    signal_risk,
)


def _pts(pairs):
    return [(BASE + dt.timedelta(days=d), float(v)) for d, v in pairs]

_STAGE_SEQ = [
    DeclineStage.HEALTHY,
    DeclineStage.EARLY_DISENGAGEMENT,
    DeclineStage.LATENT_DISSATISFACTION,
    DeclineStage.ACTIVE_DISSATISFACTION,
    DeclineStage.EXIT_INTENT,
]

BASE = dt.date(2026, 4, 1)


def _series(start_val, end_val, days=60, step=3):
    """Série linear de start_val→end_val ao longo de `days`."""
    pts = []
    n = days // step
    for i in range(n + 1):
        d = BASE + dt.timedelta(days=i * step)
        v = start_val + (end_val - start_val) * (i / n)
        pts.append((d, float(v)))
    return pts


def test_pesos_aprovados_45_25_15_15():
    assert WEIGHTS == {"engagement": 45, "tone": 25, "execution": 15, "lagging": 15}
    assert sum(WEIGHTS.values()) == 100


def test_conta_saudavel_score_alto_e_estavel():
    signals = [
        SignalInput("silencio", "engagement", _series(0.3, 0.3), higher_is_worse=True),
        SignalInput("iniciativa_cliente", "engagement", _series(10, 10), higher_is_worse=False),
        SignalInput("tom_negativo", "tone", _series(0.1, 0.1), higher_is_worse=True),
    ]
    s = score_account("acc1", "Cliente Saudável", signals)
    assert s.score >= 85
    assert s.trajectory == Trajectory.STABLE
    assert s.stage == DeclineStage.HEALTHY
    assert s.risk_band == "baixo"


def test_conta_desengajando_score_cai_e_alerta_cedo():
    signals = [
        # silêncio sobe, iniciativa cai, mensagens encurtam, tom piora
        SignalInput("silencio", "engagement", _series(0.3, 0.8), higher_is_worse=True, absolute_is_risk=True),
        SignalInput("iniciativa_cliente", "engagement", _series(20, 4), higher_is_worse=False),
        SignalInput("comprimento_msg", "tone", _series(90, 30), higher_is_worse=False),
        SignalInput("tom_negativo", "tone", _series(0.1, 0.5), higher_is_worse=True, absolute_is_risk=True),
    ]
    s = score_account("acc2", "Cliente em Queda", signals)
    assert s.score < 70
    assert s.trajectory == Trajectory.FALLING
    assert s.stage != DeclineStage.HEALTHY        # alerta deve disparar
    assert s.lead_time_days is not None
    # motivos devem priorizar sinais líderes (engagement/tone)
    assert any(r.leading for r in s.reasons)


def test_legado_recomenda_migracao():
    signals = [SignalInput("silencio", "engagement", _series(0.4, 0.5), higher_is_worse=True)]
    s = score_account("acc3", "Cliente Legado", signals, is_legacy=True)
    assert "MIGRAÇÃO" in s.recommendation.upper()


def test_alerta_dispara_em_medio_mais_caindo():
    # Conta em desengajamento que chega a faixa MÉDIA com trajetória CAINDO:
    # deve gerar alerta (pegar cedo), não só em alto/crítico.
    signals = [
        SignalInput("silencio", "engagement", _series(0.3, 0.85), higher_is_worse=True, absolute_is_risk=True),
        SignalInput("iniciativa_cliente", "engagement", _series(20, 4), higher_is_worse=False),
        SignalInput("tom_negativo", "tone", _series(0.1, 0.6), higher_is_worse=True, absolute_is_risk=True),
    ]
    s = score_account("acc_alerta", "Cliente em Deterioração", signals)
    assert s.trajectory == Trajectory.FALLING
    assert s.risk_band in ("medio", "alto")   # banda exata depende da calibração
    assert should_alert(s) is True


def test_nao_alerta_conta_saudavel_estavel():
    signals = [SignalInput("silencio", "engagement", _series(0.3, 0.3), higher_is_worse=True)]
    s = score_account("acc_ok", "Cliente OK", signals)
    assert s.risk_band == "baixo"
    assert should_alert(s) is False


def test_estagio_sensivel_a_trajetoria():
    # MESMO nível de risco (risco_total=0.45 -> profundidade 'insatisfação latente'),
    # trajetórias OPOSTAS -> estágios diferentes. Prova que a jornada (não só o
    # nível instantâneo) define o estágio.
    rt = 0.45
    falling = _stage(rt, {}, Trajectory.FALLING)
    stable = _stage(rt, {}, Trajectory.STABLE)
    rising = _stage(rt, {}, Trajectory.RISING)
    assert falling == DeclineStage.LATENT_DISSATISFACTION   # ocupa o nível cheio
    assert stable == DeclineStage.EARLY_DISENGAGEMENT       # segura um passo atrás
    assert rising == DeclineStage.HEALTHY                   # recua (recuperando)
    assert _STAGE_SEQ.index(falling) > _STAGE_SEQ.index(stable) > _STAGE_SEQ.index(rising)


def test_lagging_forte_sem_fala_explicita_e_insatisfacao_ativa():
    # CRÍTICO recente (lagging 0.7) SEM fala de saída: insatisfação ATIVA, não saída
    # (caso WMA: cobrar resposta da equipe ≠ querer cancelar).
    assert _stage(0.10, {"lagging": [0.7]}, Trajectory.RISING) == DeclineStage.ACTIVE_DISSATISFACTION
    # com fala EXPLÍCITA de saída -> aí sim intenção de saída
    assert _stage(0.10, {"lagging": [0.7]}, Trajectory.RISING, exit_explicit=True) == DeclineStage.EXIT_INTENT


def test_lagging_cancelamento_explicito_vira_intencao_de_saida():
    # Conta com WhatsApp saudável/estável, MAS com FALA EXPLÍCITA de cancelamento
    # (is_exit_signal=True) -> intenção de saída. É o caso SAMA.
    signals = [
        SignalInput("silencio", "engagement", _series(0.3, 0.3), higher_is_worse=True, absolute_is_risk=True),
        SignalInput("fala_em_cancelar", "lagging", [], higher_is_worse=True, direct_risk=0.9, is_exit_signal=True),
    ]
    s = score_account("sama", "Cliente Cancelando", signals)
    assert s.stage == DeclineStage.EXIT_INTENT
    assert should_alert(s) is True   # saída confirmada SEMPRE alerta (mesmo faixa baixa)
    assert alert_severity(s) == "critico"


def test_critico_recente_sem_fala_nao_e_intencao_de_saida():
    # Caso WMA: CRÍTICO recente do Gemini (insatisfação grave, cobrar resposta) SEM
    # fala de cancelamento -> insatisfação ATIVA, jamais "intenção de saída".
    signals = [
        SignalInput("silencio", "engagement", _series(0.5, 0.6), higher_is_worse=True, absolute_is_risk=True),
        SignalInput("tom_negativo", "tone", _series(0.3, 0.5), higher_is_worse=True, absolute_is_risk=True),
        SignalInput("critico_recente", "lagging", [], higher_is_worse=True, direct_risk=0.9, is_exit_signal=False),
    ]
    s = score_account("wma", "WMA AUTOPECAS", signals)
    assert s.stage == DeclineStage.ACTIVE_DISSATISFACTION
    assert s.stage != DeclineStage.EXIT_INTENT
    assert should_alert(s) is True   # insatisfação ativa alerta (não passa em branco)


def _mk_score(*, band, trajectory, stage):
    return AccountScore(account_id="x", account_name="X", score=0.0, trajectory=trajectory,
                        velocity=0.0, stage=stage, risk_band=band, lead_time_days=None, confidence=1.0)


def test_severidade_tres_niveis():
    # churner quieto: faixa BAIXA mas CAINDO -> 'atencao' (caso LOJA)
    s_at = _mk_score(band="baixo", trajectory=Trajectory.FALLING, stage=DeclineStage.EARLY_DISENGAGEMENT)
    assert alert_severity(s_at) == "atencao" and should_alert(s_at) is True
    # médio + caindo -> 'alto'
    s_alto = _mk_score(band="medio", trajectory=Trajectory.FALLING, stage=DeclineStage.EARLY_DISENGAGEMENT)
    assert alert_severity(s_alto) == "alto"
    # saída confirmada (estágio) -> 'critico' mesmo em faixa baixa
    s_crit = _mk_score(band="baixo", trajectory=Trajectory.STABLE, stage=DeclineStage.EXIT_INTENT)
    assert alert_severity(s_crit) == "critico"
    # baixo + estável -> sem alerta
    s_none = _mk_score(band="baixo", trajectory=Trajectory.STABLE, stage=DeclineStage.HEALTHY)
    assert alert_severity(s_none) is None and should_alert(s_none) is False


def test_melhora_sustentada_vs_pico_isolado():
    # silêncio (higher_is_worse) caindo de forma consistente = melhora sustentada
    sustentada = [SignalInput("silencio", "engagement", _pts([(0, 0.8), (7, 0.6), (14, 0.4), (21, 0.2)]), True)]
    # pico: série piora e SÓ o último ponto melhora = não sustentada
    pico = [SignalInput("silencio", "engagement", _pts([(0, 0.3), (7, 0.5), (14, 0.7), (21, 0.2)]), True)]
    assert _sustained_rising(sustentada) is True
    assert _sustained_rising(pico) is False


def test_blend_absoluto_pega_churner_sempre_quieto():
    """Sinal cronicamente RUIM mas PLANO (sem desvio do próprio baseline):
    o churner sempre-quieto. Sem o blend absoluto marcaria risco ~0 (a inversão
    que derrubava o AUC); com absolute_is_risk=True, o NÍVEL absoluto entra."""
    plano_ruim = _series(0.7, 0.7)  # 70% de dias em silêncio, estável
    rel = signal_risk(SignalInput("silencio", "engagement", plano_ruim, higher_is_worse=True))[0]
    blend = signal_risk(
        SignalInput("silencio", "engagement", plano_ruim, higher_is_worse=True, absolute_is_risk=True)
    )[0]
    assert rel < 0.1                                  # só relativo: cego ao nível
    assert blend == _ABSOLUTE_BLEND * 0.7 + (1 - _ABSOLUTE_BLEND) * rel
    assert blend > rel                                # o nível absoluto puxa o risco pra cima


def test_trajetoria_ponderada_ignora_ruido_de_iniciativa():
    """A trajetória usa os MESMOS pesos do score: silêncio/tom estáveis mandam;
    iniciativa despencando (ruído relativo, peso 0,25) NÃO deve virar a trajetória
    para 'caindo'. (Era a causa do falso 61% caindo na 1ª rodada real.)"""
    signals = [
        SignalInput("silencio", "engagement", _series(0.2, 0.2), higher_is_worse=True, absolute_is_risk=True),
        SignalInput("tom_negativo", "tone", _series(0.1, 0.1), higher_is_worse=True, absolute_is_risk=True),
        SignalInput("iniciativa_cliente", "engagement", _series(20, 6), higher_is_worse=False),  # despenca
    ]
    s = score_account("a", "a", signals)
    assert s.trajectory != Trajectory.FALLING  # o ruído rebaixado não arrasta a trajetória

    # controle: se o SILÊNCIO (peso 0,75) é que despenca, aí sim tem que cair
    piora = [
        SignalInput("silencio", "engagement", _series(0.2, 0.9), higher_is_worse=True, absolute_is_risk=True),
        SignalInput("tom_negativo", "tone", _series(0.1, 0.6), higher_is_worse=True, absolute_is_risk=True),
    ]
    assert score_account("b", "b", piora).trajectory == Trajectory.FALLING


def test_peso_intrabloco_silencio_domina_iniciativa():
    """Opção A (down-weight): silêncio (0,75) manda no engagement; iniciativa (0,25)
    é secundária. Um silêncio saudável com iniciativa 'despencando' (ruído relativo)
    não deve derrubar o score como derrubaria na média simples antiga."""
    import app.agents.growth.scoring as sc
    signals = [
        SignalInput("silencio", "engagement", _series(0.15, 0.15), higher_is_worse=True, absolute_is_risk=True),
        SignalInput("iniciativa_cliente", "engagement", _series(25, 2), higher_is_worse=False),  # cai muito
        SignalInput("tom_negativo", "tone", _series(0.1, 0.1), higher_is_worse=True, absolute_is_risk=True),
    ]
    s_down = score_account("a", "a", signals)
    saved = dict(sc._INTRA_BLOCK_WEIGHT)
    sc._INTRA_BLOCK_WEIGHT.clear()  # tudo peso 1 = média simples (comportamento antigo)
    try:
        s_equal = score_account("a", "a", signals)
    finally:
        sc._INTRA_BLOCK_WEIGHT.update(saved)
    assert s_down.score > s_equal.score  # rebaixar iniciativa reduz o ruído -> score mais alto


def test_conta_sem_cobertura_nao_e_avaliavel():
    """Ausência de dado NÃO é saúde: conta com < MIN_COVERAGE_WEEKS semanas de sinal
    líder não vira 'saudável 100' — fica não avaliável, sem alerta, p/ revisão manual.
    (Era a causa do AUC ~aleatório ao vivo: cancelado em silêncio pontuava 100.)"""
    # 1 só semana de sinal: risco 0 -> score 100, MAS sem cobertura
    poucos = [SignalInput("silencio", "engagement", _pts([(0, 0.0)]), higher_is_worse=True)]
    s = score_account("accX", "Sem Dados", poucos)
    assert s.score == 100.0                 # pela fórmula pareceria perfeito...
    assert s.coverage_weeks < 2
    assert s.evaluable is False             # ...mas é marcada como NÃO avaliável
    assert s.risk_band == "sem_dados"
    assert should_alert(s) is False         # não dispara alerta automático
    assert "manual" in s.recommendation.lower()


def test_conta_com_cobertura_e_avaliavel():
    signals = [
        SignalInput("silencio", "engagement", _series(0.3, 0.3), higher_is_worse=True),
        SignalInput("tom_negativo", "tone", _series(0.1, 0.1), higher_is_worse=True),
    ]
    s = score_account("accY", "Com Dados", signals)
    assert s.evaluable is True
    assert s.coverage_weeks >= 2
    assert s.risk_band != "sem_dados"


def test_diretriz_de_acao_por_caso():
    G = DeclineStage
    # overrides
    assert "manual" in action_guideline(G.HEALTHY, evaluable=False).lower()
    assert "migração" in action_guideline(G.HEALTHY, is_legacy=True).lower()
    # jornada (headline por estágio)
    assert "imediato" in action_guideline(G.EXIT_INTENT).lower()
    assert "urgente" in action_guideline(G.ACTIVE_DISSATISFACTION).lower()
    assert "alinhamento" in action_guideline(G.LATENT_DISSATISFACTION).lower()
    assert "proativo" in action_guideline(G.EARLY_DISENGAGEMENT).lower()
    # saudável com MRR alto vs baixo
    assert "valiosa" in action_guideline(G.HEALTHY, recurring_revenue=8000).lower()
    assert "padrão" in action_guideline(G.HEALTHY, recurring_revenue=500).lower()
    # aceita string (valor do enum), como o painel passa
    assert action_guideline("intencao_de_saida") == action_guideline(G.EXIT_INTENT)
    # precedência: não-avaliável ganha de tudo
    assert "manual" in action_guideline(G.EXIT_INTENT, evaluable=False, is_legacy=True).lower()


def test_diretriz_personaliza_pela_dor_e_contexto():
    G = DeclineStage
    reasons_sil = [{"text": "silencio: risco 80% (tendência piorando)", "weight": 36.0},
                   {"text": "tom_negativo: risco 20%", "weight": 5.0}]
    g = action_guideline(G.EARLY_DISENGAGEMENT, reasons=reasons_sil)
    assert "SILÊNCIO" in g  # tática pela dor dominante (silêncio)
    # execução com atraso entra como alerta na diretriz
    g2 = action_guideline(G.ACTIVE_DISSATISFACTION, reasons=reasons_sil, exec_score=35)
    assert "Execução com pendências" in g2 and "ClickUp 35" in g2
    # MRR alto adiciona ênfase de prioridade
    g3 = action_guideline(G.ACTIVE_DISSATISFACTION, reasons=reasons_sil, recurring_revenue=8000)
    assert "Alto valor" in g3 and "8.000" in g3
    # dor de tom negativo dá tática diferente
    reasons_tom = [{"text": "tom_negativo: risco 70%", "weight": 30.0}]
    assert "TOM NEGATIVO" in action_guideline(G.LATENT_DISSATISFACTION, reasons=reasons_tom)


def test_tardio_forte_vai_para_intencao_de_saida():
    signals = [
        SignalInput("silencio", "engagement", _series(0.4, 0.45), higher_is_worse=True, absolute_is_risk=True),
        SignalInput("fala_em_cancelar", "lagging", [], higher_is_worse=True, direct_risk=0.9, is_exit_signal=True),
    ]
    s = score_account("acc4", "Cliente Crítico", signals)
    assert s.stage == DeclineStage.EXIT_INTENT


def test_execucao_entra_como_confirmador_15pct():
    """Sinal de execução (direct_risk) ativa o bloco de 15%: piora o score quando a
    entrega está ruim; ausência do sinal renormaliza fora (não pune)."""
    base = [
        SignalInput("silencio", "engagement", _series(0.3, 0.3), higher_is_worse=True, absolute_is_risk=True),
        SignalInput("tom_negativo", "tone", _series(0.1, 0.1), higher_is_worse=True, absolute_is_risk=True),
    ]
    sem = score_account("a", "a", base)
    com_ruim = score_account("a", "a", base + [
        SignalInput("execucao", "execution", [], higher_is_worse=True, direct_risk=0.8)])
    com_boa = score_account("a", "a", base + [
        SignalInput("execucao", "execution", [], higher_is_worse=True, direct_risk=0.0)])
    assert com_ruim.score < sem.score      # execução ruim derruba (peso 15 renormalizado)
    assert com_boa.score >= sem.score      # execução boa não pune
    # e não vira "intenção de saída" (não é fala de saída)
    assert com_ruim.stage != DeclineStage.EXIT_INTENT


def test_tom_claude_completa_bloco_tone_e_renormaliza():
    """O sinal tom_claude (série semanal de risco, absolute_is_risk) entra no bloco
    tone com peso intra 0,5 e a renormalização por blocos PRESENTES segue correta:
    (a) tom piorando via Claude derruba o score; (b) sem o sinal, o bloco tone segue
    funcionando só com tom_negativo; (c) execução ausente continua renormalizando fora."""
    base = [
        SignalInput("silencio", "engagement", _series(0.2, 0.2), higher_is_worse=True, absolute_is_risk=True),
        SignalInput("tom_negativo", "tone", _series(0.1, 0.1), higher_is_worse=True, absolute_is_risk=True),
    ]
    sem_tom = score_account("a", "a", base)
    # tom via Claude AZEDANDO (caloroso 0.0 -> negativo 0.9)
    com_tom_ruim = score_account("a", "a", base + [
        SignalInput("tom_claude", "tone", _series(0.0, 0.9), higher_is_worse=True, absolute_is_risk=True)])
    com_tom_bom = score_account("a", "a", base + [
        SignalInput("tom_claude", "tone", _series(0.0, 0.0), higher_is_worse=True, absolute_is_risk=True)])
    assert com_tom_ruim.score < sem_tom.score      # tom azedando derruba
    assert com_tom_bom.score >= sem_tom.score - 1  # tom caloroso não pune
    # renormalização: só engagement+tone presentes -> pesos 45/25 renormalizados
    # (execução/lagging ausentes não puxam o score pra cima)
    assert sem_tom.score > 80  # sinais saudáveis -> score alto mesmo sem os 4 blocos


def test_regex_de_saida_pega_frases_novas():
    from app.agents.growth.collectors import _CANCEL_RE, _norm_txt
    # deve pegar (fala de saída)
    for t in ["estou pensando seriamente em parar", "vou desistir", "quero parar",
              "não vale a pena continuar", "encerrar a parceria"]:
        assert _CANCEL_RE.search(_norm_txt(t)), t
    # NÃO deve pegar (cobrança de resposta, sem fala de saída — caso WMA)
    for t in ["desde sexta-feira tentando contato", "por favor responda o e-mail",
              "qual foi sua ultima tentativa de contato"]:
        assert not _CANCEL_RE.search(_norm_txt(t)), t
