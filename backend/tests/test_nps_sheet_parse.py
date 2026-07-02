"""Parser da planilha individual de NPS/faturamento — casos reais observados.

As duas grades abaixo reproduzem as variações vistas nas planilhas de clientes:
(a) colunas contíguas + linha em branco antes dos dados (SWEET LIFE);
(b) coluna vazia extra no cabeçalho + meses atravessando o ano (LA BELLA).
"""
import csv
import io

from app.sources.nps_sheets import (faturamento_compare, find_master_row,  # noqa: F401
                                    norm_account, norm_full, parse_individual_csv)


def _rows(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text.strip())))


SHEET_A = """Cliente,Equipe,GC Responsável,Plano,Início,Término,Meta,Status,Observações,
,,,,,,,,,
"SWEET LIFE | MARCELO ",Os Borracha,Lucas,Master,7/2/2025,12/25/2025,,Ativo,,
,,,,,,,,,
Mês,Jan,Fev,Mar,Abr,Maio,Jun,Jul,Ago,Set
NPS GC,,,,,,,,5,
Qt CNPJ,,,,,,,,1,
CNPJ ,,,,,,,,,
Faturamento,,,,,,,,,
Mercado Livre,,,,,,,,"R$ 9.961,97","R$ 11.171,00"
Amazon,,,,,,,,"R$ 2.679,53",
Shopee,,,,,,,,"R$ 5.444,14",
"""

SHEET_B = """Cliente,,Equipe,GC Responsável,Plano,Início,Término,Meta,Status,Observações,,,,
LA BELLA TAVOLA | AMEDEO,,B1-S1,Mayra,Start,19/09/2025,22/12/2025,,,,,,,
,,,,,,,,,,,,,
Mês,Jan,Fev,Mar,Abr,Mai,Jun,Jul,Ago,Set,Out,Nov,Dez,Jan
Qt CNPJ,,,,,,,,,1,1,,,
CNPJ LA BELLA TAVOLA ,,,,,,,,,,,,,
Faturamento,,,,,,,,,,,,,
Mercado Livre,,,,,,,,,"R$ 0,00","R$ 100,00","R$ 0,00","R$ 0,00","R$ 300,00"
Shopee,,,,,,,,,"R$ 0,00","R$ 0,00","R$ 0,00","R$ 0,00","R$ 0,00"
"""


def test_parse_header_contiguo():
    p = parse_individual_csv(_rows(SHEET_A))
    assert p["info"]["cliente"].startswith("SWEET LIFE")
    assert p["info"]["gc"] == "Lucas"
    assert p["info"]["plano"] == "Master"
    # ano-base = ano do Início (2025); Ago = 2025-08
    assert p["months"][0] == "2025-01"
    assert "2025-08" in p["months"] and "2025-09" in p["months"]


def test_parse_faturamento_e_comparativo():
    p = parse_individual_csv(_rows(SHEET_A))
    assert len(p["cnpjs"]) == 1
    ml = p["cnpjs"][0]["marketplaces"]["Mercado Livre"]
    assert ml["2025-08"] == 9961.97 and ml["2025-09"] == 11171.0
    comp = faturamento_compare(p, "2025-09", "2025-08")
    row_ml = next(r for r in comp[0]["rows"] if r["marketplace"] == "Mercado Livre")
    assert round(row_ml["delta_abs"], 2) == 1209.03
    # Amazon/Shopee só têm agosto -> aparecem com ref None (queda a zero é sinal!)
    row_amz = next(r for r in comp[0]["rows"] if r["marketplace"] == "Amazon")
    assert row_amz["prev"] == 2679.53 and row_amz["ref"] is None


def test_parse_coluna_extra_e_virada_de_ano():
    p = parse_individual_csv(_rows(SHEET_B))
    assert p["info"]["equipe"] == "B1-S1" and p["info"]["gc"] == "Mayra"
    # 13 meses: Jan/2025..Dez/2025 + Jan/2026 (vira o ano quando repete)
    assert p["months"][0] == "2025-01" and p["months"][-1] == "2026-01"
    ml = p["cnpjs"][0]["marketplaces"]["Mercado Livre"]
    assert ml["2026-01"] == 300.0 and ml["2025-10"] == 100.0
    assert p["cnpjs"][0]["cnpj"] == "LA BELLA TAVOLA"


def test_norm_match_banco_vs_mestre():
    # nome do banco (grupo WhatsApp) casa com a coluna B da mestre
    assert norm_account("[ST-B1-S2] SWEET LIFE | MARCELO ID: 9") == norm_account("SWEET LIFE | MARCELO")
    assert norm_account("[A-B2-S1] 3DBR TECNOLOGIA | INTEGRACOMM | ID: 110") == "3dbr tecnologia"
    # norm_full preserva o responsável p/ desempatar homônimos
    assert norm_full("LIDER 3D DESING | IVAN") != norm_full("LIDER 3D DESING | JOSE")
