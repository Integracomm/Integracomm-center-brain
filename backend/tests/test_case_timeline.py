"""Linha do tempo do caso — agrupamento de falas de cancelamento em episódios."""
import datetime as dt

from app.agents.growth.collectors import _cluster_episodes


def d(day: int, month: int = 6) -> dt.date:
    return dt.date(2026, month, day)


def test_dias_proximos_viram_um_episodio():
    # caso ALMEIDA: falas em 25 e 26/06 = UM episódio (início 25, fim 26)
    assert _cluster_episodes({d(25), d(26)}) == [(d(25), d(26))]


def test_gap_maior_que_sete_dias_abre_novo_episodio():
    eps = _cluster_episodes({d(1), d(3), d(20), d(22)})
    assert eps == [(d(1), d(3)), (d(20), d(22))]


def test_sem_falas_sem_episodios():
    assert _cluster_episodes(set()) == []


def test_dia_unico():
    assert _cluster_episodes({d(10)}) == [(d(10), d(10))]
