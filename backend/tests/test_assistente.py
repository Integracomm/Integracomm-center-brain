"""Assistente de IA (Fase 1) — o que dá para garantir SEM gastar um token.

O assistente é somente leitura e herda o RBAC do usuário porque as ferramentas
chamam as funções de ENDPOINT existentes com o request de quem pergunta. Aqui
ficam os guarda-corpos baratos: gates de acesso, poda de payload (contexto não
estoura), saneamento do histórico e o contrato do cardápio. A qualidade das
respostas/paridade com as telas é validada no smoke com chamada real (piloto).
"""
from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

import app.assistente as AS


# --- gates de acesso ---------------------------------------------------------
class _Req:
    cookies: dict = {}


def test_status_exige_sessao():
    with pytest.raises(HTTPException) as e:
        AS.api_assistente_status(_Req())
    assert e.value.status_code == 401


def test_chat_exige_sessao():
    with pytest.raises(HTTPException) as e:
        AS.api_assistente_chat(_Req(), {"mensagens": [{"role": "user", "content": "oi"}]})
    assert e.value.status_code == 401


def test_nao_admin_nao_entra_no_piloto(monkeypatch):
    import app.api as A
    monkeypatch.setattr(A, "_require_api", lambda r: ("gestor@x", "gestor_growth"))
    r = AS.api_assistente_status(_Req())
    assert r["disponivel"] is False
    resp = AS.api_assistente_chat(_Req(), {"mensagens": [{"role": "user", "content": "oi"}]})
    assert resp.status_code == 403


def test_chat_sem_pergunta_retorna_422(monkeypatch):
    import app.api as A
    monkeypatch.setattr(A, "_require_api", lambda r: ("adm", "admin"))
    monkeypatch.setattr(AS, "get_settings", lambda: type("S", (), {
        "anthropic_api_key": "sk-teste", "assistente_perguntas_dia": 40})())
    assert AS.api_assistente_chat(_Req(), {"mensagens": []}).status_code == 422
    # histórico terminando em assistant também não vale
    assert AS.api_assistente_chat(_Req(), {"mensagens": [
        {"role": "assistant", "content": "olá"}]}).status_code == 422


# --- poda: retorno de ferramenta nunca estoura o contexto --------------------
def test_poda_corta_lista_e_declara_o_total():
    r = AS._poda(list(range(200)))
    assert len(r) == AS._LIMITE_LISTA + 1
    assert "total=200" in r[-1]["_aviso"]


def test_poda_preserva_avisos_e_janela():
    """As ressalvas das telas TÊM de sobreviver à poda — o modelo precisa
    vê-las para respeitá-las (regra de honestidade)."""
    d = {"aviso": "amostra pequena (n=4)", "janela": 120,
         "serie": list(range(500)), "nota": "x" * 5000}
    r = AS._poda(d)
    assert r["aviso"] == "amostra pequena (n=4)"
    assert r["janela"] == 120
    assert r["nota"].endswith("…(cortado)")


def test_json_ferramenta_respeita_o_teto():
    grande = {"linhas": [{"t": "x" * 1500} for _ in range(400)]}
    txt = AS._json_ferramenta(grande)
    assert len(txt) <= AS._LIMITE_PAYLOAD + 30


def test_resultado_converte_jsonresponse_de_erro_em_dado():
    """403/503 dos endpoints viram DADO explicável, nunca exceção que derruba
    a conversa — e nunca vazam dado de área não autorizada."""
    from fastapi.responses import JSONResponse
    r = AS._resultado(JSONResponse({"error": "a central é do administrador"}, status_code=403))
    assert r["erro"]["error"] == "a central é do administrador"


# --- contrato do cardápio ----------------------------------------------------
def test_cardapio_fase1_completo_e_coerente():
    nomes = {t["name"] for t in AS._TOOLS_SCHEMA}
    assert nomes == set(AS._FERRAMENTAS) == {
        "central_overview", "raiox_bundle", "growth_contas",
        "growth_alertas", "cancelamentos", "receita_recorrente"}
    for t in AS._TOOLS_SCHEMA:
        assert t["description"], t["name"]
        assert t["input_schema"]["type"] == "object"


def test_system_prompt_carrega_as_regras_da_casa():
    """As réguas oficiais e as regras de honestidade são o que impede o modelo
    de inventar definição própria e divergir das telas."""
    s = AS._SYSTEM
    for trecho in ("MRR em risco", "ISR", "Quick Ratio", "NÃO INVENTE",
                   "ASSOCIAÇÃO NÃO É CAUSA", "DADO NÃO CONFIÁVEL",
                   "SOMENTE LEITURA", "B1-START", "Consolidado"):
        assert trecho in s, f"system prompt perdeu: {trecho}"


def test_ferramentas_sao_somente_leitura():
    """Nenhum executor pode escrever: o módulo não toca INSERT/UPDATE/DELETE
    nem dispara Slack — inspeção direta do fonte, exceto o audit_log do chat."""
    import inspect
    fonte = inspect.getsource(AS)
    corpo_sem_audit = fonte.replace(
        "INSERT INTO audit_log (actor, action, source, scope) ", "")
    for proibido in ("INSERT INTO", "UPDATE ", "DELETE FROM", "send_text",
                     "webhook", "httpx.post"):
        assert proibido not in corpo_sem_audit, f"escrita proibida no assistente: {proibido}"
