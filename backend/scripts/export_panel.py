"""Exporta o painel como HTML ESTÁTICO (snapshot do banco), sem subir servidor.
Gera na raiz do projeto: painel_growth.html — com um bloco de documentação para o
DESIGNER no topo (dicionário de campos, componentes e interações).

    backend/.venv/Scripts/python -m scripts.export_panel
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

from app.api import _conn, _latest_scores, _open_alerts, _render, _top_practices

OUT = Path(__file__).resolve().parents[2] / "painel_growth.html"

# Nota de handoff embutida como comentário HTML (não renderiza; guia o designer).
_DESIGNER_NOTE = """<!--
====================================================================
 PAINEL GROWTH — INTEGRACOMM IA · referência para o design do frontend
 Snapshot ESTÁTICO gerado em {ts} a partir do banco (dados reais).
 O app real é servido por FastAPI (app/api.py, rota GET /); este arquivo
 é só a REFERÊNCIA visual/funcional — pode reconstruir o layout à vontade,
 mantendo os campos e as interações abaixo.

 PRINCÍPIO DE PRODUTO: o agente CALCULA, EXIBE e SINALIZA — nunca age.
 Humano no loop; a decisão/ação é sempre do gestor.

 DUAS VISÕES:
  1) "Alertas abertos" = fila de ação, por severidade (crítico > alto > atenção).
  2) "Contas por risco" = termômetro (menor score = pior), tabela filtrável.
     Inclui as não-avaliáveis (sem dados suficientes) ao fim.

 FILTROS (combináveis via AND, client-side em applyF()): nome (busca),
 faixa, alerta, estágio, squad, MRR mínimo. Cada linha carrega data-attrs:
   data-name, data-band, data-alert, data-stage, data-squad, data-mrr.

 CAMPOS POR CONTA (colunas da tabela "Contas por risco"):
  - conta        : nome do grupo de WhatsApp; sublinha = motivos (sinais de maior peso).
  - score        : 0–100, saúde (100 = saudável). "s/ dados" quando não-avaliável.
  - faixa        : baixo(verde) | medio(amarelo) | alto(laranja) | critico(vermelho) | sem_dados(cinza).
  - estágio      : saudável | desengajamento | insatisfação latente | insatisfação ativa |
                   intenção de saída | não avaliável. ● colorido = tem alerta aberto.
  - squad        : token do [tag] do nome (ST, M, T, ADS, CONF…).
  - MRR          : receita recorrente (desempata prioridade).
  - execução     : selo ClickUp (em dia/atenção/atrasada) — CONTEXTO, não entra no score.
  - diretriz     : orientação de ação AUTOMÁTICA por caso (headline por estágio +
                   dor dominante + alerta de execução + ênfase de MRR).

 IDENTIDADE VISUAL: tema DARK, marca amarelo Integracomm. Tokens em
  frontend/design-tokens.css (fonte da verdade, injetados inline). Ver a seção
  "Design System" no backend/README.md.

 COMPONENTES / CLASSES CSS reaproveitáveis:
  .rail (sidebar) · .kpi (KPIs no topo) · .chip (badges de status) ·
  .tbl/.row (tabelas em grid) · .guide (diretriz) · .nm/.mot (nome/motivos).

 CORES (faixa/severidade, via tokens): baixo #3DDC84 · medio #F5C518 ·
  alto #FF8A3D · critico #FF4D5E · sem_dados #77777E · marca #F5C518 · bg #0B0B0C.
====================================================================
-->
"""


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    with _conn() as c:
        html = _render("admin", _latest_scores(c), _open_alerts(c), _top_practices(c))
    note = _DESIGNER_NOTE.format(ts=dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
    html = html.replace("<body>", "<body>\n" + note, 1)
    OUT.write_text(html, encoding="utf-8")
    print(f"painel exportado (com nota p/ designer): {OUT}  ({len(html)//1024} KB)")


if __name__ == "__main__":
    main()
