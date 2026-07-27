"""A rodada tem de CABER na janela e entregar dado fresco todo dia.

Otávio, 27/07/2026: "preciso que todos os dias esses relatórios sejam enviados
com dados que o time possa agir em cima."

O que quebrava: a coleta percorre ~250 contas em SÉRIE lendo o gateway do
WhatsApp, e cada conta condenada custa até ~3 min (5 tentativas × 30s de timeout
+ backoff). Quando o total passava do teto do envelope, o processo era MORTO —
e aí nada era pontuado, nada era gravado e o Slack não saía. Tudo ou nada.

Agora a coleta tem PRAZO: ao estourar, ela para de ler e pontua o que já leu.
Para isso ser seguro, a amostra chega ordenada da conta mais DEFASADA para a
menos — assim o corte cai sempre em quem já está fresco, e quem ficou de fora
hoje encabeça a fila amanhã. Sem a ordenação, o prazo cortaria sempre o mesmo
rabo da lista e aquelas contas nunca mais seriam pontuadas.
"""
from __future__ import annotations

import datetime as dt
import time

import pytest

from app.agents.growth.agent import GrowthAgent


class _CtxFalso:
    """Contexto mínimo — o collect só precisa de sample/deadline/audit/run_id."""

    def __init__(self, sample, deadline=None):
        self.sample = sample
        self.window_start = dt.datetime(2026, 4, 1, tzinfo=dt.timezone.utc)
        self.window_end = dt.datetime(2026, 7, 27, tzinfo=dt.timezone.utc)
        self.run_id = "run-teste"
        self.audit = None
        if deadline is not None:
            self.deadline = deadline


def _amostra(n: int) -> list[dict]:
    return [{"account_id": f"a{i}", "name": f"CONTA {i}", "group_id": f"g{i}",
             "asof": dt.date(2026, 7, 27)} for i in range(n)]


@pytest.fixture
def sem_rede(monkeypatch):
    """Neutraliza WhatsApp/Claude: aqui se testa o CONTROLE DE FLUXO, não IO."""
    import app.sources.whatsapp as W
    import app.agents.growth.collectors as C

    class _Reader:
        def __init__(self, *a, **k): pass
        def close(self): pass
        def iter_messages(self, **k): return iter(())
        def iter_analyses(self, **k): return iter(())

    monkeypatch.setattr(W, "WhatsAppReader", _Reader)
    monkeypatch.setattr(C, "build_account_signals", lambda *a, **k: [])
    monkeypatch.setenv("WHATSAPP_READ_API_URL", "http://x")
    monkeypatch.setenv("WHATSAPP_READ_API_KEY", "k")
    monkeypatch.setenv("GROWTH_LLM_CANCEL", "0")


def test_sem_prazo_le_a_carteira_inteira(sem_rede):
    ctx = _CtxFalso(_amostra(20))
    raw = GrowthAgent().collect(ctx)
    assert len(raw) == 20
    assert ctx.cortadas_por_prazo == 0


def test_prazo_ja_vencido_nao_le_nenhuma(sem_rede):
    """Prazo no passado: para na primeira e reporta o corte inteiro."""
    ctx = _CtxFalso(_amostra(20), deadline=time.monotonic() - 1)
    raw = GrowthAgent().collect(ctx)
    assert raw == {}
    assert ctx.cortadas_por_prazo == 20


def test_prazo_corta_no_meio_e_pontua_o_que_leu(sem_rede, monkeypatch):
    """O ponto central: estourar o prazo NÃO perde o trabalho já feito."""
    import app.agents.growth.collectors as C
    lidas = {"n": 0}
    t0 = time.monotonic()

    def conta_e_avanca(*a, **k):
        lidas["n"] += 1
        if lidas["n"] == 5:          # relógio "salta" o prazo na 5ª conta
            monkeypatch.setattr(time, "monotonic", lambda: t0 + 10_000)
        return []

    monkeypatch.setattr(C, "build_account_signals", conta_e_avanca)
    ctx = _CtxFalso(_amostra(30), deadline=t0 + 1_000)
    raw = GrowthAgent().collect(ctx)

    assert 0 < len(raw) < 30, "deveria pontuar uma PARTE — nem tudo, nem nada"
    assert len(raw) + ctx.cortadas_por_prazo == 30, "toda conta ou foi lida ou foi contada como cortada"


def test_conta_que_falha_nao_derruba_as_seguintes(sem_rede, monkeypatch):
    """Resiliência que já existia — garantir que o prazo não a quebrou."""
    import app.agents.growth.collectors as C

    def falha_na_terceira(*a, **k):
        falha_na_terceira.n = getattr(falha_na_terceira, "n", 0) + 1
        if falha_na_terceira.n == 3:
            raise TimeoutError("gateway fora")
        return []

    monkeypatch.setattr(C, "build_account_signals", falha_na_terceira)
    ctx = _CtxFalso(_amostra(10))
    raw = GrowthAgent().collect(ctx)
    assert len(raw) == 9
    assert len(ctx.skipped) == 1
