"""Régua de bundle da conta VIVA pela tag de SERVIÇO do nome (24/07).

Mesmo princípio do _canc_bundle: o serviço manda, NUNCA o Bx da tag do squad —
[ADS-B4-S1] é cliente ADS atendido por squad B4, não um B4. `plan_category` do
banco herda o Bx da tag (o coletor usa regex no nome), por isso não serve.
Efeito real da régua: B4 caiu de 38 (tag) para 6 (serviço) e B5 de 9 para 1.
"""
from app.api import bundle_conta


def test_bundles_novos_pelo_prefixo_de_servico():
    assert bundle_conta("[ST-B1-S2] LOJA X | FULANO") == ("novo", "B1")
    assert bundle_conta("[T-B2-S1] LOJA Y | ID: 1") == ("novo", "B2")
    assert bundle_conta("[S-B3-S2] LOJA Z") == ("novo", "B3")
    assert bundle_conta("[P-B4-S1] PRIMAVERA GARDEN | ID: 17565") == ("novo", "B4")
    assert bundle_conta("[E-B5-S3] ELITE W") == ("novo", "B5")


def test_antigos_nao_herdam_o_bx_do_squad():
    # o Bx na tag é o SQUAD que atende — não o plano do cliente
    assert bundle_conta("[ADS-B4-S1] MAGNO FESTAS") == ("antigo", "ADS")
    assert bundle_conta("[CONF-B2-S1] D LA BELLA") == ("antigo", "Configuração")
    assert bundle_conta("[M-B3-S1] ORNATO TEMPERA") == ("antigo", "Master")
    assert bundle_conta("[A-B3-S1] PP SPORTS | ID: 197") == ("antigo", "Assessoria")
    assert bundle_conta("[SMART-B1-S2] IMPACTO TEE") == ("antigo", "Smart")


def test_prefixo_de_estado_e_pulado():
    assert bundle_conta("[PAUSADO ST-B1-S2] NOVAQX") == ("novo", "B1")
    assert bundle_conta("[PRORROGADO ADS-FA] DOAC") == ("antigo", "ADS")


def test_sem_tag():
    assert bundle_conta("Marketplace Supley - Operação ID: 206")[0] == "sem_tag"
    assert bundle_conta("")[0] == "sem_tag"
    assert bundle_conta(None)[0] == "sem_tag"
