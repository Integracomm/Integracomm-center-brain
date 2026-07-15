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


def test_caso_real_inteel_nao_quero_mais_operacional():
    # 02/07/2026 — áudio da INTEEL (ID 18814) sobre variações do ANÚNCIO gerou
    # alerta falso de cancelamento: "não quero mais" sem objeto de serviço
    msg = ("Então, os dois anúncios são meus. O primeiro que eu lhe enviei é o "
           "que eu preciso que seja reformulado, porque ele está tamanho casal, "
           "solteiro e Queen. Eu não quero mais. Eh, vai ser cada um seu tamanho.")
    assert not hit(msg)
    # variações operacionais do dia a dia que também NÃO são churn
    for s in ("não quero mais esse título no anúncio",
              "não quero mais receber esses relatórios por email",
              "não quero mais essa foto na vitrine"):
        assert not hit(s), s


def test_caso_real_vou_sair_operacional():
    # 15/07/2026 — "vou sair" sem objeto gerava alerta falso (casos reais)
    for s in ("eu consigo as três porque às 4 vou sair para faculdade",
              "não vou sair prejudicada",
              "pode ir almoçar, eu vou sair agora também"):
        assert not hit(s), s
    # com objeto de relacionamento (ou intenção explícita) segue pegando
    for s in ("vou sair da integracomm", "vou sair do contrato",
              "vou sair desse grupo", "eu quero sair", "decidi sair"):
        assert hit(s), s


def test_nao_quero_mais_com_objeto_de_servico_segue_pegando():
    for s in ("não quero mais o serviço", "não quero mais a assessoria",
              "não quero mais continuar com vocês", "não quero mais renovar",
              "não quero mais trabalhar com a integracomm",
              "não quero continuar", "não quero renovar o plano"):
        assert hit(s), s
