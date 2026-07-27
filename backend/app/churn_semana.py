"""Relatório SEMANAL de cancelamentos — o guia da reunião de cancelamentos.

Pedido do Otávio (27/07): "temos duas reuniões semanais importantes, a de
faturamento e a de cancelamentos. Na reunião de cancelamentos as ações da
semana servem como um ótimo guia, e ainda podemos ver os resultados da semana
anterior por lá (…) poderíamos colocar um relatório similar mas de cancelamento
semanal, com as ações que precisaríamos realizar na semana e os resultados da
semana anterior."

Mesmo molde das Ações da Semana: **o que aconteceu na semana que passou** +
**o que fazer nesta semana**. A diferença é que aqui as ações não são objetivos
digitados por alguém: elas saem dos DADOS de risco (alertas abertos, contas em
queda, tratativas em aberto), e a semana anterior é medida em cima do que
efetivamente saiu.

Nada de régua nova: cancelamentos vêm de `_cancel_rows`, a classificação
novo/antigo/B1 de `grupo_churn*` e a carteira viva de `_sem_encerradas` — as
MESMAS funções da aba Cancelamentos e do All Hands (regra da casa: um conceito,
uma régua, em toda a aplicação).
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, Query, Request

router = APIRouter()


def _deps():
    from . import api as A
    return A


def _seg(hoje: dt.date | None = None) -> dt.date:
    """Segunda da semana de trabalho — MESMA régua das Ações da Semana
    (no domingo já vira para a semana seguinte)."""
    from .semana import _seg as _s
    return _s(hoje)


def _saidas_da_semana(rows: list[dict], ini: dt.date, fim: dt.date) -> list[dict]:
    """Cancelamentos com data de saída dentro de [ini, fim).

    A planilha tem `mes` (granularidade mensal, sempre preenchido) e
    `data_saida` (dia exato, nem sempre). Para recorte SEMANAL só serve quem
    tem o dia — quem não tem entra na contagem do mês e é declarado à parte,
    para o número não sumir em silêncio."""
    out = []
    for r in rows:
        if r["tipo"] != "cancelamento":
            continue
        d = r.get("data_saida")
        if isinstance(d, dt.datetime):
            d = d.date()
        if isinstance(d, dt.date) and ini <= d < fim:
            out.append(r)
    return out


def _sem_dia_no_mes(rows: list[dict], ini: dt.date, fim: dt.date) -> int:
    """Cancelamentos do MÊS da semana que não têm dia lançado (lacuna medida)."""
    n = 0
    for r in rows:
        if r["tipo"] != "cancelamento":
            continue
        d = r.get("data_saida")
        if isinstance(d, dt.datetime):
            d = d.date()
        if isinstance(d, dt.date):
            continue
        m = r.get("mes")
        if isinstance(m, dt.date) and ini.replace(day=1) <= m <= fim.replace(day=1):
            n += 1
    return n


def _acoes_da_semana(conn, vivas: list[dict], rows: list[dict],
                     ini: dt.date) -> list[dict]:
    """Fila de trabalho da semana, em ordem de prioridade. Cada item diz O QUE
    é, POR QUE está aqui e PARA ONDE ir — nada de conselho genérico."""
    A = _deps()
    acoes: list[dict] = []

    # 1) alertas críticos abertos: o topo da fila, sempre
    alerts = A._open_alerts(conn)
    vivos = [a for a in alerts if not A.estado_encerrado(a.get("name") or "")]
    criticos = [a for a in vivos if a.get("severity") == "critico"]
    if criticos:
        acoes.append({
            "prioridade": 1, "tipo": "alerta_critico",
            "titulo": f"{len(criticos)} conta(s) com alerta CRÍTICO em aberto",
            "porque": "sinal de intenção de saída — é o que vira churn em semanas",
            "contas": [a["name"] for a in criticos[:10]],
            "link": "/growth/alertas",
        })

    # 2) tratativas em aberto (a planilha do time é a fonte)
    trat = [r for r in rows if r["tipo"] == "tratativa"
            and isinstance(r.get("mes"), dt.date) and r["mes"] >= ini.replace(day=1)]
    if trat:
        acoes.append({
            "prioridade": 2, "tipo": "tratativa",
            "titulo": f"{len(trat)} tratativa(s) de retenção em andamento",
            "porque": "cliente já pediu para sair ou sinalizou — desfecho ainda em aberto",
            "contas": [f"{r['cliente']} ({r.get('gc') or 'sem GC'})" for r in trat[:10]],
            "link": "/growth/cancelamentos",
        })

    # 3) piores scores SEM alerta aberto: risco que ninguém está olhando
    com_alerta = {(a.get("name") or "").strip().lower() for a in vivos}
    frios = [s for s in vivas
             if (s.get("name") or "").strip().lower() not in com_alerta
             and s.get("score") is not None and s["score"] < 50]
    frios.sort(key=lambda s: s["score"])
    if frios:
        acoes.append({
            "prioridade": 3, "tipo": "risco_sem_alerta",
            "titulo": f"{len(frios)} conta(s) com score baixo e NENHUM alerta aberto",
            "porque": "risco silencioso: ninguém foi avisado, então ninguém está agindo",
            "contas": [f"{s['name']} ({s['score']:.0f})" for s in frios[:10]],
            "link": "/growth/contas",
        })

    # 4) execução crítica: entrega ruim precede insatisfação
    exec_ruim = [s for s in vivas
                 if s.get("exec_score") is not None and s["exec_score"] < 40]
    if exec_ruim:
        exec_ruim.sort(key=lambda s: s["exec_score"])
        acoes.append({
            "prioridade": 4, "tipo": "execucao",
            "titulo": f"{len(exec_ruim)} conta(s) com execução crítica (<40)",
            "porque": "entrega travada vira insatisfação — tratar antes de virar pedido de saída",
            "contas": [f"{s['name']} ({s['exec_score']:.0f})" for s in exec_ruim[:10]],
            "link": "/growth/contas?exec=critica",
        })
    return acoes


def dados_semana(conn, week: dt.date | None = None) -> dict:
    """Payload do relatório semanal de cancelamentos (função PURA de dados —
    a tela só formata, como toda a casa)."""
    A = _deps()
    ini = week or _seg()
    fim = ini + dt.timedelta(days=7)
    ant_ini, ant_fim = ini - dt.timedelta(days=7), ini

    rows = A._cancel_rows(conn)
    vivas, _fora = A._sem_encerradas(A._latest_scores(conn))

    saidas_ant = _saidas_da_semana(rows, ant_ini, ant_fim)
    saidas_atual = _saidas_da_semana(rows, ini, fim)
    revertidos = [r for r in rows if r["tipo"] == "revertido"
                  and isinstance(r.get("data_saida"), (dt.date, dt.datetime))
                  and ant_ini <= (r["data_saida"].date()
                                  if isinstance(r["data_saida"], dt.datetime)
                                  else r["data_saida"]) < ant_fim]

    # a régua ÚNICA (mesma da aba Cancelamentos e do All Hands)
    grupos_ant = A.churn_por_grupo([s["name"] for s in vivas], saidas_ant)

    def _resumo(saidas: list[dict]) -> dict:
        return {
            "total": len(saidas),
            "mrr_perdido": sum(float(r["valor"] or 0) for r in saidas),
            "contas": [{"cliente": r["cliente"], "plano": r.get("plano"),
                        "gc": r.get("gc"), "motivo": (r.get("motivo") or "")[:160],
                        "grupo": A.grupo_churn_saida(r),
                        "meses_casa": (float(r["meses"]) if r.get("meses") is not None else None)}
                       for r in sorted(saidas, key=lambda x: str(x["cliente"]))],
        }

    return {
        "semana": {"ini": ini.isoformat(), "fim": (fim - dt.timedelta(days=1)).isoformat()},
        "semana_anterior": {"ini": ant_ini.isoformat(),
                            "fim": (ant_fim - dt.timedelta(days=1)).isoformat()},
        "anterior": {
            **_resumo(saidas_ant),
            "revertidos": len(revertidos),
            "por_grupo": {k: grupos_ant[k] for k in ("novos", "antigos", "recorrentes")},
            "b1_fora": grupos_ant["b1_fora"],
            # lacuna DECLARADA: sem dia lançado não dá para recortar por semana
            "sem_dia_lancado": _sem_dia_no_mes(rows, ant_ini, ant_fim),
        },
        "em_curso": _resumo(saidas_atual),
        "acoes": _acoes_da_semana(conn, vivas, rows, ini),
        "base_viva": len(vivas),
        "regua": grupos_ant["regua"],
    }


@router.get("/api/growth/churn-semana")
def api_churn_semana(request: Request, week: str = Query("")):
    """Relatório semanal de cancelamentos (JSON p/ o SPA)."""
    A = _deps()
    A._require_api(request)
    try:
        w = dt.date.fromisoformat(week) if week else None
    except ValueError:
        w = None
    with A._conn() as c:
        return dados_semana(c, w)
