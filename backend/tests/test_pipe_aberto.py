"""Pipe ABERTO por bundle — régua única entre a aba Funil e o Performance & Meta.

Otávio (27/07): "não encontrei uma análise de quantas oportunidades estão em
aberto para cada bundle hoje". O número existia, mas só como a coluna
"Pipeline" da tabela de metas — contagem crua, sem valor nem idade, num lugar
onde ninguém procura "o que está aberto".

Duas coisas ficam travadas aqui:
1. as DUAS telas leem da MESMA função (antes a consulta vivia solta dentro do
   forecast; a segunda tela reimplementaria e as duas divergiriam);
2. o vocabulário: pipe aberto ≠ Oportunidade. "Oportunidade" é o campo Dia
   Oportunidade e conta ENTRADA no período — regra do Otávio de 14/07, que
   proíbe chamar pipe aberto de oportunidade.
"""
from __future__ import annotations

from app.sales.dados import _ST_PIPE_ABERTO, pipe_aberto_por_bundle


class _Cur:
    def __init__(self, linhas): self._l, self.sql = linhas, ""
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, sql, params=None): self.sql = " ".join(sql.split())
    def fetchall(self): return self._l


class _Conn:
    def __init__(self, linhas): self._l = linhas; self.ultimo_sql = ""
    def cursor(self):
        c = _Cur(self._l)
        self._cur = c
        return c


def test_soma_valor_idade_e_parados_por_bundle():
    conn = _Conn([("B1", 57, 493959.0, 12.0, 11),
                  ("B2", 18, 50250.0, 5.0, 2),
                  ("outros", 39, 11999.0, 10.0, 2)])
    r = pipe_aberto_por_bundle(conn)
    por = {x["bundle"]: x for x in r["por_bundle"]}
    assert por["B1"]["deals"] == 57
    assert por["B1"]["valor"] == 493959.0
    assert por["B1"]["idade_mediana_dias"] == 12
    assert por["B1"]["parados_30d"] == 11
    assert r["total"]["deals"] == 57 + 18 + 39
    assert r["total"]["valor"] == 493959.0 + 50250.0 + 11999.0
    assert r["total"]["parados_30d"] == 15


def test_bundle_sem_pipe_aparece_zerado_e_nao_some():
    """Bundle sem nada aberto TEM de aparecer com 0 — sumir da tabela faria o
    gestor achar que o dado não existe, em vez de ver que o pipe está vazio."""
    conn = _Conn([("B1", 3, 100.0, 4.0, 0)])
    r = pipe_aberto_por_bundle(conn)
    bundles = [x["bundle"] for x in r["por_bundle"]]
    for b in ("B1", "B2", "B3", "B4", "B5"):
        assert b in bundles, f"{b} sumiu da tabela"
    assert next(x for x in r["por_bundle"] if x["bundle"] == "B5")["deals"] == 0
    # 'outros' só aparece quando existe (não é um bundle de verdade)
    assert "outros" not in bundles


def test_so_conta_as_etapas_do_closer():
    """Reunião(6)/Reagendamento(5)/Negociação(7). Topo de funil não é pipe."""
    assert set(_ST_PIPE_ABERTO) == {5, 6, 7}
    conn = _Conn([])
    pipe_aberto_por_bundle(conn)
    sql = conn._cur.sql
    assert "status='open'" in sql
    assert "stage_id IN (6, 5, 7)" in sql


def test_nota_separa_pipe_aberto_de_oportunidade():
    """A nota vai junto do dado para o vocabulário não se perder na leitura."""
    nota = pipe_aberto_por_bundle(_Conn([]))["nota"].lower()
    assert "abertos" in nota
    assert "entraram" in nota, "a nota tem de contrastar com o que ENTROU no período"
