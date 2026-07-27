"""Diagnóstico de memória do painel — precisa medir o número CERTO.

Nasceu do OOM de 27/07 (a rodada diária morta 4 dias seguidos porque o painel
ocupava 1,34 GB num host de 1,9 GB e nada na tela mostrava essa pressão).

A 1ª versão media `ru_maxrss`, que é o PICO desde o boot — e pico NUNCA DESCE.
Era o número errado para acompanhar memória ao longo do dia: nenhuma redução
apareceria, e o card diria "1,3 GB" para sempre mesmo depois de liberar tudo.
Agora vêm os dois, separados e rotulados: ATUAL (decide se a rodada cabe hoje)
e PICO (explica um OOM que já aconteceu).
"""
from __future__ import annotations

import app.sources.clickup_activities as CU


def test_devolve_atual_e_pico_separados():
    m = CU.memoria_caches()
    assert "rss_mb" in m and "pico_mb" in m, "atual e pico têm de ser campos distintos"


def test_atual_vem_do_proc_e_nao_do_ru_maxrss(monkeypatch, tmp_path):
    """No Linux o atual sai de /proc/self/status (VmRSS). Se voltasse a sair de
    ru_maxrss, este teste falha — que é o ponto."""
    fake = tmp_path / "status"
    fake.write_text("Name:\tpython\nVmRSS:\t 524288 kB\nVmPeak:\t 999999 kB\n", encoding="utf-8")
    real_open = open

    def open_espiao(caminho, *a, **k):
        if str(caminho) == "/proc/self/status":
            return real_open(fake, *a, **k)
        return real_open(caminho, *a, **k)

    monkeypatch.setattr("builtins.open", open_espiao)
    m = CU.memoria_caches()
    assert m["rss_mb"] == 512.0, "524288 kB = 512 MB"


def test_sem_proc_nao_quebra(monkeypatch):
    """Windows (máquina do Otávio) não tem /proc — o campo fica None e o card
    simplesmente não aparece, em vez de derrubar o Admin."""
    def open_que_falha(caminho, *a, **k):
        if str(caminho) == "/proc/self/status":
            raise OSError("sem /proc")
        raise AssertionError("só o /proc deveria ser tocado aqui")

    monkeypatch.setattr("builtins.open", open_que_falha)
    m = CU.memoria_caches()
    assert m["rss_mb"] is None


def test_conta_as_entradas_de_cache_por_familia():
    """O card mostra quantas entradas cada família guarda — é o que liga o
    número de memória à causa (ex.: 'cu-bfs 60' = teto batendo)."""
    CU._cache["cu-bfs:teste1"] = (0.0, [])
    CU._cache["cu-bfs:teste2"] = (0.0, [])
    CU._cache["cu-coment:teste"] = (0.0, [])
    try:
        fam = CU.memoria_caches()["entradas_por_familia"]
        assert fam.get("cu-bfs") >= 2
        assert fam.get("cu-coment") >= 1
    finally:
        for k in ("cu-bfs:teste1", "cu-bfs:teste2", "cu-coment:teste"):
            CU._cache.pop(k, None)


def test_teto_por_conta_e_exposto():
    """O card explica que o excedente vive no banco — o número do teto precisa
    vir junto para a frase não ser vaga."""
    assert CU.memoria_caches()["teto_por_conta"] == CU._MEM_MAX_POR_CONTA
