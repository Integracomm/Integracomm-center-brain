"""Parser da planilha de composição dos SQUADs (grade real resumida)."""
import csv
import io

from app.sources.squads_sheet import gc_of_team, parse_squads_csv, squad_of


SHEET = """,Bundle,Squad,Serviço,Quantidade,Função,Colaborador,Total Serviços,Total Colaboradores,Serviços / Colaboradores
,B1,S1,Antigo/Basic,,Growth,Vitor Bonfim ,39,4,"9,8"
,,,Smart,1,Gerente de Contas,Maria Eduarda,,,
,,,Master,2,Assessor 1,Gustavo Magri,,,
,,,ADS,2,Assessor 2,,,,
,B5,S3,Antigo/Basic,,Growth,Lucas Silva,26,4,"6,5"
,,,Smart,,Gerente de Contas,,,,
,,,Master,1,Assessor 1,David,,,
"""


def _teams():
    return parse_squads_csv(list(csv.reader(io.StringIO(SHEET))))


def test_parse_blocos_e_membros():
    t = _teams()
    assert set(t) == {"B1-S1", "B5-S3"}
    assert {"funcao": "Growth", "nome": "Vitor Bonfim"} in t["B1-S1"]
    # Assessor 2 sem colaborador não vira membro
    assert all(m["nome"] for m in t["B1-S1"])
    assert gc_of_team(t["B1-S1"]) == "Maria Eduarda"
    assert gc_of_team(t["B5-S3"]) is None  # GC vazio no B5


def test_squad_da_conta():
    assert squad_of("[ST-B1-S2] SWEET LIFE | MARCELO ID: 9") == "B1-S2"
    assert squad_of("[ADS-B4-S1]-R WORLD GARDEN | GILVAN") == "B4-S1"
    assert squad_of("Marketplace Supley - Operação ID: 206") is None
