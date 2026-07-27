"""Régua ÚNICA da taxa de cancelamento (Otávio 27/07).

"Nem para clientes ativos e nem para cancelados devemos levar em conta clientes
B1, e podemos contar novos e antigos separadamente e juntos. Esses cálculos
devem estar de acordo com todas as áreas da aplicação."

B1-START é semestral pago à vista — não é recorrente e distorcia a taxa nas
DUAS pontas. Antes cada tela decidia sozinha: o All Hands já tirava o B1, mas a
aba Cancelamentos só o excluía da linha GERAL e montava a base com
`substring(name FROM 'B[1-5]')` sobre TODAS as contas — o mesmo bug de regex
que os chips já tinham corrigido ([ADS-B4-S1] virava B4) e ainda contando
canceladas como base viva.
"""
from __future__ import annotations

import pytest

from app.api import churn_por_grupo, grupo_churn, grupo_churn_saida, taxa_churn


# --- classificação: as TRÊS formas em que o plano aparece no sistema ---------
@pytest.mark.parametrize("entrada,esperado", [
    # 1) nome da conta com tag de serviço (aba Contas, scores)
    ("[ST-B1-S2] FULANO | INTEGRACOMM", "b1"),
    ("[T-B2-S1] BELTRANO | INTEGRACOMM", "novo"),
    ("[S-B3-S1] SICRANO", "novo"),
    ("[P-B4-S1] X", "novo"),
    ("[E-B5-S3] Y", "novo"),
    ("[PAUSADO ST-B1-S2] Z", "b1"),          # estado é pulado
    # o Bx da tag é do SQUAD, não do plano — [ADS-B4-S1] é cliente ADS
    ("[ADS-B4-S1] CLIENTE ADS", "antigo"),
    ("[CONF-B3-S1] WMA AUTOPECAS", "antigo"),
    ("[M-B2-S1] MASTER ANTIGO", "antigo"),
    # 2) código do plano
    ("B1-START", "b1"), ("B2-TRACTION", "novo"), ("B5-ELITE", "novo"),
    # 3) nome comercial (lista Clientes Ativos do ClickUp) — este era o furo:
    #    sem o mapa, TODO bundle novo caía em "antigo" no All Hands
    ("Start", "b1"), ("Traction", "novo"), ("Scale", "novo"),
    ("Platinum", "novo"), ("Elite", "novo"),
    ("ADS", "antigo"), ("Master", "antigo"), ("Smart", "antigo"),
    ("Estratégia", "antigo"), ("Antigo/Basic", "antigo"),
    ("", "sem_tag"),
])
def test_classificacao_das_tres_formas(entrada, esperado):
    assert grupo_churn(entrada) == esperado


def test_saida_classifica_pelo_plano_nunca_pelo_squad():
    """Régua de 20/07: cliente ADS atendido pelo squad B5-S3 NÃO é churn de B5."""
    assert grupo_churn_saida({"plano": "ADS", "equipe": "B5-S3"}) == "antigo"
    assert grupo_churn_saida({"plano": "Traction", "equipe": "B3-S1"}) == "novo"
    assert grupo_churn_saida({"plano": "START", "equipe": "B1-S2"}) == "b1"
    # só SEM plano lançado a equipe entra como último recurso
    assert grupo_churn_saida({"plano": "BUNDLES", "equipe": "B3-S1"}) == "novo"


# --- a fórmula ---------------------------------------------------------------
def test_taxa_e_saidas_sobre_base():
    assert taxa_churn(5, 100) == 0.05
    assert taxa_churn(0, 100) == 0.0
    assert taxa_churn(5, 0) is None      # sem base não há taxa (nunca 0 nem erro)


def test_b1_fica_fora_das_duas_pontas():
    """O ponto central do pedido: B1 não entra nem no numerador nem no
    denominador de nenhuma das três taxas."""
    base = ["Start"] * 50 + ["Traction"] * 30 + ["ADS"] * 20
    saidas = ["Start"] * 9 + ["Traction"] * 3 + ["ADS"] * 4
    g = churn_por_grupo(base, saidas)

    assert g["novos"] == {"base": 30, "saidas": 3, "taxa": 0.1}
    assert g["antigos"] == {"base": 20, "saidas": 4, "taxa": 0.2}
    # juntos: 50 de base, 7 saídas — os 50 Start e as 9 saídas ficam DE FORA
    assert g["recorrentes"]["base"] == 50
    assert g["recorrentes"]["saidas"] == 7
    assert g["recorrentes"]["taxa"] == pytest.approx(0.14)
    # o B1 é contado à parte, para ninguém achar que sumiu
    assert g["b1_fora"] == {"base": 50, "saidas": 9}


def test_recorrentes_e_a_soma_de_novos_e_antigos():
    g = churn_por_grupo(["Traction"] * 10 + ["ADS"] * 10 + ["Start"] * 5,
                        ["Traction"] * 2 + ["ADS"] * 3)
    assert g["recorrentes"]["base"] == g["novos"]["base"] + g["antigos"]["base"]
    assert g["recorrentes"]["saidas"] == g["novos"]["saidas"] + g["antigos"]["saidas"]


def test_toda_conta_e_classificada_em_algum_grupo():
    """Nenhuma conta pode sumir na classificação — a soma dos grupos TEM de
    fechar com o total, senão a base da taxa fica silenciosamente menor."""
    base = ["Start", "Traction", "ADS", "[ADS-B4-S1] X", "[T-B2-S1] Y", ""]
    g = churn_por_grupo(base, [])
    soma = (g["novos"]["base"] + g["antigos"]["base"]
            + g["b1_fora"]["base"] + g["sem_tag"]["base"])
    assert soma == len(base)


def test_base_vazia_nao_quebra():
    g = churn_por_grupo([], [])
    assert g["recorrentes"]["taxa"] is None
    assert g["novos"]["base"] == 0
