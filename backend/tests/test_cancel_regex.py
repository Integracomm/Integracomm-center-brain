"""Detecção de fala explícita de cancelamento — casos reais e contra-exemplos."""
from app.agents.growth.collectors import _CANCEL_RE, _norm_txt


def hit(s: str) -> bool:
    return bool(_CANCEL_RE.search(_norm_txt(s)))


def test_caso_real_bene_tu_formal_substantivado():
    # 01/07/2026 — solicitação FORMAL que a regex antiga não pegava
    msg = ("Bom dia pessoal. Venho por meio desta, solicitar o cancelamento de "
           "nosso contrato e gostaria que me passassem os procedimentos para a "
           "formalização desse encerramento. Obrigado pelo apoio dado nesse período.")
    assert hit(msg)


def test_formas_explicitas():
    for s in ("quero cancelar o contrato", "solicito o cancelamento",
              "peço o encerramento do serviço", "pensando seriamente em parar",
              "vamos assinar o distrato", "cancelamento do nosso plano",
              "não vale a pena continuar"):
        assert hit(s), s


def test_nao_confunde_com_marketplace():
    # cancelamentos de ANÚNCIO/PEDIDO nos marketplaces não são churn
    for s in ("cancelaram meu anuncio no mercado livre",
              "o cliente cancelou o pedido da shopee",
              "como cancelo uma promoção?",
              "encerramos o expediente mais cedo hoje"):
        assert not hit(s), s
