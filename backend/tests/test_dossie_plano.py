"""O dossiê do plano de ação tem de dizer QUE DIA É HOJE e se a conta está viva.

Dois defeitos reais que o Otávio pegou em 24/07/2026:
  1. planos com prazos JÁ VENCIDOS ("até 15/07" num relatório aberto em 24/07)
     — o modelo ancorava as datas no mês de REFERÊNCIA, que é o mês anterior;
  2. o plano do WMA AUTOPECAS afirmou "conta parada desde a largada / pode nunca
     ter começado a ser atendida" enquanto o mesmo relatório listava dezenas de
     atividades — o dossiê só mandava o contador do mês de referência (0) e
     escondia a recência.
"""
from __future__ import annotations

import datetime as dt

from app.agents.growth.action_plan import _dossie

_BASE = {
    "header": {"cliente": "[CONF-B3-S1] WMA AUTOPECAS | INTEGRACOMM", "plano": "Configuração",
               "reference_month_label": "junho/2026", "prev_month_label": "maio/2026"},
    "saude": {"score": 45.6, "faixa": "alto risco", "estagio": "maduro",
              "trajetoria": "piorando", "tom": {"rotulo": "negativo", "detalhe": "evento crítico"},
              "motivos": [], "exec_score": 25},
    "faturamento": {"available": False, "aviso": None, "comparativo": [], "conf": True},
    "atividades": {"total": 0, "total_hist": 0, "ultima_em": None,
                   "ultimas_30d": 0, "ultimas_90d": 0,
                   "proximas": {"tasks": []}, "atrasadas": {"tasks": []}},
}


def _com(**atividades) -> dict:
    d = {k: (dict(v) if isinstance(v, dict) else v) for k, v in _BASE.items()}
    d["atividades"] = {**_BASE["atividades"], **atividades}
    return d


def test_dossie_declara_a_data_de_hoje():
    """Sem isto o modelo escrevia prazos no passado."""
    txt = _dossie(_com(), [])
    hoje = dt.date.today()
    assert f"HOJE: {hoje.strftime('%d/%m/%Y')}" in txt
    # e diz até quando vão as 2 semanas, para o prazo nascer no futuro
    assert (hoje + dt.timedelta(days=14)).strftime("%d/%m/%Y") in txt


def test_dossie_avisa_que_mes_ref_nao_e_o_mes_corrente():
    txt = _dossie(_com(), [])
    assert "mês ANTERIOR" in txt


def test_conta_viva_com_zero_no_mes_de_referencia_nao_parece_abandonada():
    """Caso WMA: 0 entregas em junho, mas trabalho recente. O dossiê tem de
    mostrar a recência ANTES do contador mensal."""
    ontem = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    txt = _dossie(_com(ultima_em=ontem, ultimas_30d=7, ultimas_90d=19, total_hist=64), [])
    assert "ATIVIDADE DE ENTREGA" in txt
    assert ontem in txt
    assert "7 nos últimos 30 dias" in txt
    assert "64 no histórico todo" in txt
    # e o alerta explícito contra a leitura errada que gerou o incidente
    assert "NÃO significa conta abandonada" in txt


def test_conta_realmente_sem_entregas_e_dita_como_tal():
    txt = _dossie(_com(), [])
    assert "NENHUMA entrega concluída no histórico" in txt


def test_temas_de_insatisfacao_chegam_ao_dossie():
    """A análise de tom já extraía os temas e a postura do cliente e gravava em
    signal_snapshots — mas ninguém lia. É o dado de relacionamento mais concreto
    que temos e ele tem de estar no preparo da reunião."""
    d = _com()
    d["saude"] = {**_BASE["saude"],
                  "temas_insatisfacao": ["demora nas respostas", "anúncios sem otimização"],
                  "iniciativa_cliente": "cliente",
                  "tom_analisado_em": "2026-07-20"}
    txt = _dossie(d, [])
    assert "TEMAS DE INSATISFAÇÃO" in txt
    assert "demora nas respostas" in txt
    assert "anúncios sem otimização" in txt
    assert "POSTURA DO CLIENTE: cliente" in txt


def test_sem_temas_nao_polui_o_dossie():
    assert "TEMAS DE INSATISFAÇÃO" not in _dossie(_com(), [])


def test_leitura_degradada_avisa_para_nao_concluir_abandono():
    """Caso WMA de verdade: a API do ClickUp falhou, o relatório caiu no espelho
    da Operação e ele devolveu 0 atividades. O plano NÃO pode ler esse zero como
    conta parada — tem de saber que a leitura falhou."""
    d = _com()
    d["atividades"]["source"] = "mirror"
    d["atividades"]["aviso"] = "API ClickUp indisponível (HTTPStatusError)"
    txt = _dossie(d, [])
    assert "LEITURA DE ATIVIDADES DEGRADADA" in txt
    assert "NÃO conclua que a conta parou" in txt


def test_fonte_boa_nao_dispara_aviso_de_degradacao():
    d = _com()
    d["atividades"]["source"] = "clickup_api"
    d["atividades"]["aviso"] = None
    assert "DEGRADADA" not in _dossie(d, [])


def test_tarefas_vencidas_entram_como_pauta_da_reuniao():
    d = _com()
    d["atividades"]["atrasadas"] = {"tasks": [{"nome": "x"}, {"nome": "y"}]}
    assert "TAREFAS VENCIDAS EM ABERTO: 2" in _dossie(d, [])
