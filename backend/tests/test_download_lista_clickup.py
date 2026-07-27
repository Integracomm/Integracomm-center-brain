"""Paginação da lista do ClickUp: página que FALHA ≠ página VAZIA.

Incidente 24/07/2026. A API do ClickUp passou a devolver 500 esporádico em
páginas do meio das listas de assessoria (pág. 21) e de clientes ativos (pág. 7).
Duas consequências, ambas corrigidas aqui:

  1. o 500 subia como exceção e matava o download INTEIRO (~108 páginas), então
     o prewarm nunca conseguia aquecer a lista e toda requisição de usuário
     tentava baixar tudo na hora — os relatórios foram de segundos para minutos;
  2. ao tratar a falha devolvendo lista vazia, o laço leria "página curta = fim"
     e encerraria a paginação MAIS CEDO, em silêncio. Contas inteiras sumiriam
     do resultado sem nenhum aviso — foi exatamente o sintoma do WMA AUTOPECAS,
     que apareceu com histórico zerado num relatório e fez o plano de ação
     concluir que a conta "pode nunca ter começado a ser atendida".
"""
from __future__ import annotations

import pytest

from app.sources import clickup_activities as CU


def _pagina(page: int, n: int = 100) -> list[dict]:
    """Itens rastreáveis: o id diz de que página vieram."""
    return [{"id": f"p{page}-{i}"} for i in range(n)]


def _paginas_presentes(out: list[dict]) -> set[int]:
    return {int(t["id"].split("-")[0][1:]) for t in out}


def test_pagina_que_falha_nao_encerra_a_paginacao(monkeypatch):
    """A página 2 falha; as posteriores TÊM de continuar sendo baixadas.
    Se a falha fosse lida como fim, as páginas 8+ sumiriam em silêncio."""
    def fake(_token, _lst, page):
        if page == 2:
            raise CU._PaginaIndisponivel("500 simulado")
        return _pagina(page) if page < 10 else _pagina(page, 7)

    monkeypatch.setattr(CU, "_fetch_list_page", fake)
    out = CU._download_list("tok", "lista-x")

    presentes = _paginas_presentes(out)
    assert 2 not in presentes                      # a que falhou, de fato falta
    assert {0, 1, 3, 4, 5, 6, 7}.issubset(presentes)
    assert {8, 9, 10}.issubset(presentes), "a paginação parou na página que falhou"
    assert CU._download_falhas["lista-x"] == 1


def test_pagina_curta_encerra_normalmente(monkeypatch):
    """Página curta = fim real. O lote corrente termina (são 8 em paralelo),
    mas nenhum lote novo começa."""
    def fake(_token, _lst, page):
        return _pagina(page) if page < 3 else _pagina(page, 12)

    monkeypatch.setattr(CU, "_fetch_list_page", fake)
    out = CU._download_list("tok", "lista-y")
    presentes = _paginas_presentes(out)
    assert presentes == set(range(8))   # o lote 0-7 inteiro, e nada além dele
    assert CU._download_falhas["lista-y"] == 0


def test_download_parcial_nao_substitui_lista_boa_em_cache(monkeypatch):
    """Trocar uma lista íntegra por uma incompleta faria contas sumirem."""
    CU._cache["cu:lista-z"] = (0.0, _pagina(0, 500))

    def fake(_token, _lst, page):
        if page == 1:
            raise CU._PaginaIndisponivel("500 simulado")
        return _pagina(page) if page < 2 else _pagina(page, 3)

    monkeypatch.setattr(CU, "_fetch_list_page", fake)
    with pytest.raises(CU._PaginaIndisponivel):
        CU._refresh_list("tok", "lista-z")
    # o cache antigo (íntegro) continua lá
    assert len(CU._cache["cu:lista-z"][1]) == 500
    CU._cache.pop("cu:lista-z", None)


def test_retry_de_5xx_antes_de_desistir(monkeypatch):
    """Um 500 transitório tem de ser reexecutado, não propagado."""
    chamadas = {"n": 0}

    class Resp:
        def __init__(self, status): self.status_code, self.headers = status, {}
        def json(self): return {"tasks": _pagina(0, 4)}
        def raise_for_status(self): pass

    class Cli:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, *_a, **_k):
            chamadas["n"] += 1
            return Resp(500 if chamadas["n"] < 3 else 200)

    monkeypatch.setattr(CU.httpx, "Client", lambda **_k: Cli())
    monkeypatch.setattr(CU.time, "sleep", lambda _s: None)  # sem espera no teste
    assert len(CU._fetch_list_page("tok", "lista-w", 0)) == 4
    assert chamadas["n"] == 3


def test_desiste_com_excecao_e_nunca_com_lista_vazia(monkeypatch):
    """Desistir devolvendo [] seria lido como fim da lista — tem de EXPLODIR."""
    class Resp:
        status_code, headers = 500, {}

    class Cli:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, *_a, **_k): return Resp()

    monkeypatch.setattr(CU.httpx, "Client", lambda **_k: Cli())
    monkeypatch.setattr(CU.time, "sleep", lambda _s: None)
    with pytest.raises(CU._PaginaIndisponivel):
        CU._fetch_list_page("tok", "lista-v", 5)
