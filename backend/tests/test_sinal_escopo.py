"""Sinal de ESCOPO/EXPECTATIVA nos comentários dos gestores (caso PP Sports).

Estes testes existem por causa de um erro real: a 1ª versão do detector usava
`não (está|faz parte|contempla)` solto e, varrendo a carteira, deu 9 falsos
positivos em 10 contas — casava anotação de onboarding ("Bling não está bem
configurado", "não está conseguindo emitir notas", "a pessoa responsável não
está mais na empresa"). Os negativos abaixo são as FRASES REAIS que vazaram;
qualquer afrouxamento do padrão volta a quebrá-los.
"""
from app.reports import sinal_escopo


def _c(texto: str):
    return [{"texto": texto, "data": "2026-07-01", "autor": "gestor"}]


# --- deve DETECTAR: o cliente questiona o que o plano cobre ------------------
POSITIVOS = [
    # PP Sports 22/07 — a fala que precedeu o cancelamento
    "para boa parte de suas solicitações, recebe como resposta que está fora "
    "do escopo do contrato. Pretende contratar outras pessoas",
    # PP Sports 17/06 — o aviso um mês antes
    "Marcar uma reunião para alinhar o plano com o cliente, ele questiona que "
    "antes era feito vários pontos que o plano dele não contempla, precisa alinhar!",
    "cliente cobrou que o plano dele não cobre gestão de ADS",
    "reclamou que isso não faz parte do contrato dele",
]

# --- NÃO pode detectar: português genérico de anotação de conta -------------
NEGATIVOS = [
    "cliente não está demonstrando insatisfação com o serviço e sim com o Mercado livre",
    "Usa o Bling - não está bem configurado, 1 cnpj, interesse em vender na amazon",
    "a pessoa que ficava responsável pelos marketplaces não está mais na empresa",
    "Bling nao esta bem configurado. anuncios : 52 meli 37 shopee",
    "Possui Bling, não está configuração. Quer aumentar as vendas, porém quer ter margem.",
    "Quer migrar de IDERIS Pra outro, não esta conseguindo nem subir anuncios mais.",
    "Ja utiliza o bling porem nao esta integrado. Contratou uma funcionaria",
    "Amazon não esta conseguindo entrar. -time : ela e duas irmas",
    "não está conseguindo emitir notas fiscais nem expandir a operação",
]


def test_detecta_questionamento_de_escopo():
    for texto in POSITIVOS:
        assert sinal_escopo(_c(texto)), f"deveria sinalizar: {texto[:60]}"


def test_nao_dispara_em_anotacao_generica():
    for texto in NEGATIVOS:
        assert sinal_escopo(_c(texto)) is None, f"falso positivo: {texto[:60]}"


def test_devolve_evidencia_e_nao_veredito():
    """O gestor é o confirmador: a saída tem de trazer a FRASE, data e autor."""
    r = sinal_escopo(_c(POSITIVOS[0]))
    assert r["n"] == 1
    o = r["ocorrencias"][0]
    assert o["data"] == "2026-07-01" and o["autor"] == "gestor"
    assert "fora do escopo" in o["trecho"].lower()
    assert "risco" not in r  # não classifica


def test_sem_comentarios_nao_sinaliza():
    assert sinal_escopo([]) is None
    assert sinal_escopo(None) is None
