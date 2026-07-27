"""Cache persistente não pode servir payload com FORMATO antigo depois do deploy.

Incidente 27/07/2026, bug meu. Em 24/07 criei um cache do payload do All Hands
no RDS (serve-stale) para a tela não reconstruir tudo a cada deploy. Em 27/07
mudei o formato: `assessoria.nps` saiu e entrou `assessoria.reunioes`.

O cache sobrevive ao deploy — então a primeira abertura da tela nova leu o
payload VELHO do banco, ainda no formato antigo, e o card de reuniões
simplesmente não existia. O Otávio abriu exatamente nessa janela e reportou
"não consigo ver as informações de NPS e reuniões". Pior: o serve-stale
reconstruía em segundo plano, então na recarga seguinte aparecia — o sintoma
era intermitente, que é o pior tipo de bug para diagnosticar.

A chave agora carrega a VERSÃO do formato: formato novo = chave nova = é
impossível servir uma resposta com o formato errado.
"""
from __future__ import annotations

import app.allhands as AH


def test_chave_carrega_a_versao_do_formato():
    chave = AH._chave_dados("2026-06-01")
    assert f"v{AH._DADOS_VERSAO}" in chave
    assert "2026-06-01" in chave


def test_versoes_diferentes_nao_colidem():
    """O ponto todo: bumpar a versão TEM de gerar uma chave nova, senão o
    payload velho continua sendo servido."""
    atual = AH._chave_dados("2026-06-01")
    original = AH._DADOS_VERSAO
    try:
        AH._DADOS_VERSAO = original + 1
        assert AH._chave_dados("2026-06-01") != atual
    finally:
        AH._DADOS_VERSAO = original


def test_meses_diferentes_nao_colidem():
    assert AH._chave_dados("2026-06-01") != AH._chave_dados("2026-07-01")


def test_formato_atual_tem_reunioes_e_nao_nps(monkeypatch):
    """Trava o contrato que a tela consome. Se alguém trocar o formato de novo
    sem bumpar _DADOS_VERSAO, este teste continua passando — mas o de cima
    documenta a obrigação. Aqui garantimos ao menos que o campo que a tela lê
    é o que o backend produz."""
    import inspect
    fonte = inspect.getsource(AH._monta_dados)
    assert '"reunioes"' in fonte, "a tela lê assessoria.reunioes"
    assert '"nps"' not in fonte, "campo antigo removido — se voltar, bumpar _DADOS_VERSAO"
