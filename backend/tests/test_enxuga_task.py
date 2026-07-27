"""Enxugamento da task do ClickUp — guardar só o que a aplicação lê.

Otávio autorizou em 27/07: "deixe apenas os dados que usamos ou algum outro que
você julgue necessário para uma visão futura; se houver necessidade no futuro,
nós os puxaremos novamente."

Motivo: a API devolve a task INTEIRA e nós retínhamos tudo — 12,7 mil tasks com
os 25 campos personalizados do workspace em cada uma (a maioria vazia). O
painel chegou a 1,15 GB num host de 1,9 GB e a rodada diária morria de OOM.
Medido numa página real: 15.672 → 1.054 bytes por task (**93,3% menos**).

Estes testes existem porque perder um campo aqui quebra em SILÊNCIO: a tela
mostra vazio, não dá erro. Cada campo abaixo foi levantado por grep em todo o
backend antes do corte.
"""
from __future__ import annotations

from app.sources.clickup_activities import _enxuga_task

CRUA = {
    "id": "abc123",
    "name": "Reunião GC: CLIENTE <> Integracomm",
    "parent": "pai999",
    "url": "https://app.clickup.com/t/abc123",
    "tags": [{"name": "urgente"}],
    "status": {"status": "concluído", "type": "closed", "color": "#fff", "orderindex": 3},
    "assignees": [{"username": "Maria Eduarda", "id": 1, "email": "x@y.com",
                   "profilePicture": "http://...", "initials": "ME"}],
    "date_done": "1753000000000",
    "date_closed": "1753000000001",
    "date_created": "1750000000000",
    "date_updated": "1753000000002",
    "due_date": "1753100000000",
    "priority": {"priority": "high"},
    "time_estimate": 3600000,
    "list": {"id": "900700780446", "name": "Assessoria", "access": True},
    "custom_fields": [
        {"name": "satisfação", "value": "5", "type": "emoji",
         "type_config": {"count": 5, "code_point": "2b50"}},
        {"name": "NPS", "value": None, "type": "number", "type_config": {}},
        {"name": "Campo vazio", "value": "", "type": "text", "type_config": {}},
    ],
    # peso morto que NÃO pode sobreviver
    "description": "x" * 5000,
    "text_content": "y" * 5000,
    "checklists": [{"items": [{"name": "z"} for _ in range(50)]}],
    "attachments": [{"url": "..."} for _ in range(20)],
    "watchers": [{"id": i} for i in range(30)],
    "sharing": {"public": False, "token": "..."},
    "permission_level": "create",
    "creator": {"id": 1, "username": "alguem", "profilePicture": "http://..."},
    "project": {"id": "1", "name": "p"},
    "folder": {"id": "2", "name": "f"},
    "space": {"id": "3"},
    "dependencies": [], "linked_tasks": [], "locations": [],
}


def test_preserva_todos_os_campos_que_a_aplicacao_le():
    """A lista veio de grep no backend inteiro. Se algum sair, a tela vai
    mostrar vazio sem dar erro — por isso o teste é explícito campo a campo."""
    e = _enxuga_task(CRUA)
    assert e["id"] == "abc123"
    assert e["name"] == CRUA["name"]
    assert e["parent"] == "pai999"
    assert e["url"] == CRUA["url"]
    assert e["tags"] == CRUA["tags"]
    assert e["date_done"] == CRUA["date_done"]
    assert e["date_closed"] == CRUA["date_closed"]
    assert e["date_created"] == CRUA["date_created"]
    assert e["due_date"] == CRUA["due_date"]


def test_status_continua_dict_com_a_chave_status():
    """O código lê `(t.get("status") or {}).get("status")` em 7 lugares — o
    FORMATO tem de sobreviver, não só o valor."""
    e = _enxuga_task(CRUA)
    assert isinstance(e["status"], dict)
    assert e["status"]["status"] == "concluído"


def test_assignees_continua_lista_de_dicts_com_username():
    """É assim que o GC das reuniões é identificado (98% de cobertura)."""
    e = _enxuga_task(CRUA)
    assert [a["username"] for a in e["assignees"]] == ["Maria Eduarda"]
    # o resto do perfil (foto, e-mail, id) é peso morto e sai
    assert "profilePicture" not in e["assignees"][0]


def test_custom_fields_mantem_so_os_preenchidos():
    """O maior peso morto: a API repete os 25 campos do workspace em CADA task,
    quase todos vazios. Guardamos só os que têm valor — e o `type_config`
    junto, que é o que decodifica o rating de satisfação."""
    e = _enxuga_task(CRUA)
    nomes = {c["name"] for c in e["custom_fields"]}
    assert nomes == {"satisfação"}, "campo vazio/None não deve ser retido"
    sat = e["custom_fields"][0]
    assert sat["value"] == "5"
    assert sat["type_config"]["count"] == 5


def test_descarta_o_peso_morto():
    e = _enxuga_task(CRUA)
    for campo in ("description", "text_content", "checklists", "attachments",
                  "watchers", "sharing", "permission_level", "creator",
                  "project", "folder", "space", "dependencies"):
        assert campo not in e, f"{campo} deveria ter sido descartado"


def test_guarda_margem_para_o_futuro():
    """Otávio pediu para manter o que possa servir depois — sem isso, qualquer
    uso novo exigiria rebaixar tudo da API."""
    e = _enxuga_task(CRUA)
    assert e["priority"] == {"priority": "high"}
    assert e["time_estimate"] == 3600000
    assert e["date_updated"] == CRUA["date_updated"]
    assert e["list"] == {"id": "900700780446"}, "de qual lista veio (temos 2)"


def test_subtarefas_tambem_sao_enxugadas():
    """O BFS percorre a árvore inteira — subtarefa gorda anula o ganho."""
    pai = dict(CRUA, subtasks=[dict(CRUA, id="filho1")])
    e = _enxuga_task(pai)
    assert e["subtasks"][0]["id"] == "filho1"
    assert "description" not in e["subtasks"][0]


def test_reduz_de_verdade():
    import json
    cru = len(json.dumps(CRUA, default=str))
    enx = len(json.dumps(_enxuga_task(CRUA), default=str))
    assert enx < cru * 0.35, f"reducao insuficiente: {cru} -> {enx}"


def test_entrada_invalida_nao_quebra():
    assert _enxuga_task({}) == {"assignees": [], "custom_fields": []}
    assert _enxuga_task(None) is None  # type: ignore[arg-type]
