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


def test_fase2_gestor_entra_e_uso_fica_com_o_admin(monkeypatch):
    """Fase 2: o chat abre para todo usuário logado; a visão de USO (custo por
    pessoa) segue exclusiva do admin."""
    import app.api as A
    monkeypatch.setattr(A, "_require_api", lambda r: ("gestor@x", "gestor_growth"))
    monkeypatch.setattr(AS, "get_settings", lambda: type("S", (), {
        "anthropic_api_key": "sk-teste", "assistente_perguntas_dia": 40})())
    monkeypatch.setattr(A, "_conn", lambda: (_ for _ in ()).throw(RuntimeError("sem banco")))
    r = AS.api_assistente_status(_Req())
    assert r["disponivel"] is True  # banco fora não fecha o gate (usadas=0)
    assert AS.api_assistente_uso(_Req()).status_code == 403


# --- RBAC por área: o chat NÃO é porta dos fundos ----------------------------
def test_gestor_nao_alcanca_ferramenta_de_outra_area(monkeypatch):
    """Os endpoints JSON só exigem login — a área é conferida na camada do
    assistente, com a MESMA régua das telas (_areas_of)."""
    import app.api as A
    monkeypatch.setattr(A, "_areas_of", lambda u, r: {"growth"})
    assert AS._pode_usar("g@x", "gestor_growth", "growth_contas") is None
    assert AS._pode_usar("g@x", "gestor_growth", "carga_squads") is None
    recusa = AS._pode_usar("g@x", "gestor_growth", "marketing_canais")
    assert recusa and "marketing" in recusa
    assert AS._pode_usar("g@x", "gestor_growth", "financeiro_meta") is not None
    # ponte aceita QUALQUER uma das duas áreas
    monkeypatch.setattr(A, "_areas_of", lambda u, r: {"prevendas"})
    assert AS._pode_usar("g@x", "gestor_prevendas", "ponte_pv_vendas") is None


def test_admin_alcanca_todas_as_ferramentas():
    for nome in AS._FERRAMENTAS:
        assert AS._pode_usar("adm", "admin", nome) is None, nome


def test_ferramentas_de_area_tem_area_declarada():
    """Toda ferramenta de dado de área TEM de declarar a área — esquecer o 4º
    campo deixaria a ferramenta aberta a qualquer logado."""
    sem_area_ok = {"central_overview", "semana",   # endpoints já barram (admin)
                   "raiox_bundle"}                 # visão da empresa, régua da tela
    for nome, (_r, _s, _f, area) in AS._FERRAMENTAS.items():
        if nome not in sem_area_ok:
            assert area, f"{nome} sem área declarada"


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
def test_cardapio_completo_e_coerente():
    nomes = {t["name"] for t in AS._TOOLS_SCHEMA}
    assert nomes == set(AS._FERRAMENTAS) == {
        "central_overview", "raiox_bundle", "growth_contas", "growth_alertas",
        "cancelamentos", "carga_squads", "marketing_canais", "marketing_funil",
        "ciclo_vida", "prevendas", "funil_vendas", "winloss", "ponte_pv_vendas",
        "financeiro_meta", "receita_recorrente", "semana", "operacoes_iniciativas"}
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
