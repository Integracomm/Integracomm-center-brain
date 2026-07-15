"""Confirmador semântico no fluxo de coleta: só candidato CONFIRMADO vira
fala de cancelamento; sem confirmador, comportamento regex-only (anterior)."""
import datetime as dt
from types import SimpleNamespace

from app.agents.growth.collectors import build_account_signals

ASOF = dt.date(2026, 7, 15)


class _FakeReader:
    def __init__(self, msgs):
        self._msgs = msgs

    def iter_messages(self, *, group_id=None, window_start=None, order="desc"):
        yield from self._msgs


def _msg(mid, day_offset, text, sender="Cliente X"):
    return SimpleNamespace(
        id=mid, sender_name=sender, message_text=text, audio_transcription=None,
        received_at=dt.datetime.combine(ASOF - dt.timedelta(days=day_offset),
                                        dt.time(15, 0), tzinfo=dt.timezone.utc))


def _base_msgs():
    return [
        _msg("m1", 2, "quero cancelar o contrato"),          # candidato (regex)
        _msg("m2", 3, "bom dia, segue a planilha de skus"),   # não-candidato
    ]


def _lagging(sigs):
    return next(s for s in sigs if s.block == "lagging")


def test_sem_confirmador_mantem_regex_only():
    ev = {}
    sigs = build_account_signals(_FakeReader(_base_msgs()), group_internal_id="g",
                                 asof=ASOF, analyses_by_group={}, events_out=ev)
    assert _lagging(sigs).direct_risk == 0.9
    assert len(ev["episodios"]) == 1


def test_confirmador_nega_derruba_episodio_e_gatilho():
    ev = {}
    sigs = build_account_signals(_FakeReader(_base_msgs()), group_internal_id="g",
                                 asof=ASOF, analyses_by_group={}, events_out=ev,
                                 cancel_confirmer=lambda cands: {m: False for m, _ in cands})
    assert _lagging(sigs).direct_risk == 0.0
    assert ev["episodios"] == []


def test_confirmador_confirma_preserva():
    ev = {}
    julgados = []

    def conf(cands):
        julgados.extend(m for m, _ in cands)
        return {m: True for m, _ in cands}

    sigs = build_account_signals(_FakeReader(_base_msgs()), group_internal_id="g",
                                 asof=ASOF, analyses_by_group={}, events_out=ev,
                                 cancel_confirmer=conf)
    assert _lagging(sigs).direct_risk == 0.9
    assert len(ev["episodios"]) == 1
    assert julgados == ["m1"]  # só o candidato da regex vai ao LLM (custo)


def test_msg_fora_do_veredito_mantida_por_seguranca():
    # falha parcial do lote (msg sem veredito) NÃO pode esconder churn real
    ev = {}
    sigs = build_account_signals(_FakeReader(_base_msgs()), group_internal_id="g",
                                 asof=ASOF, analyses_by_group={}, events_out=ev,
                                 cancel_confirmer=lambda cands: {})
    assert _lagging(sigs).direct_risk == 0.9
