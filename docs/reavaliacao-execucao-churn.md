# Reavaliação: execução prediz churn? (2026-07-02)

## Contexto
A conclusão original do modelo — **"execução não prediz churn"** (AUC ~0,49/0,44
em churn−30/−60) — foi levantada como suspeita pelo Otávio: ela saiu do espelho
(mirror Supabase) da Operação, que se descobriu **incompleto**. Duas falhas
confirmadas e corrigidas:

1. **Truncamento silencioso**: o PostgREST do mirror corta toda resposta em 1.000
   linhas mesmo pedindo mais — o leitor de subtarefas recebia lotes cortados sem
   erro. Corrigido com paginação por offset (`app/sources/mirror.py`).
2. **Cobertura parcial**: para os clientes ativos casados à lista "Assessoria" do
   ClickUp, o mirror tinha só **~51% das subtarefas** (mediana 90% por card, mas
   vários clientes com 0 — ex.: Supley 431 reais vs 0 no mirror).

## Onde está o histórico dos cancelados (correção importante)
A 1ª tentativa buscou os cancelados na lista Assessoria e concluiu errado que o
ClickUp não retinha o histórico. **Correção do Otávio**: quando o contrato
encerra, o card é **movido para a lista CS/Cancelados (900700953811), levando a
árvore de atividades junto** (44+/61 da coorte casam lá; mediana de 17
subtarefas por card; cobertura de vencimento 77%, simétrica aos 80% da
Assessoria — sem viés estrutural entre coortes). Listas mapeadas para
calibração: CS/Cancelados `900700953811` (churn orgânico 2025→, principal),
Funil CS `900700895737` (onda de transição 2023-24, cards sem árvore de
atividades), Sem Renovação (id não registrado).

## O que foi testado
Script `backend/scripts/offline_exec_clickup_full.py`: mesma coorte (61
cancelados + 200 controles), mesma lógica `execution_asof` (as-of, sem
vazamento), trocando só a fonte das subtarefas — (a) mirror com paginação
corrigida vs (b) ClickUp completo via API oficial (cancelados: CS/Cancelados;
controles: Assessoria).

## Resultado

| horizonte | fonte | AUC | cancelados | controles |
|-----------|-------|-----|-----------|-----------|
| churn−30 | mirror (paginado) | 0,410 | n=45, μ=81,5 | n=120, μ=76,3 |
| churn−30 | **ClickUp completo** | **0,529** | n=48, μ=69,1 | n=121, μ=71,8 |
| churn−60 | mirror (paginado) | 0,351 | n=45, μ=83,8 | n=120, μ=76,3 |
| churn−60 | **ClickUp completo** | **0,455** | n=48, μ=71,8 | n=121, μ=71,8 |

## Leitura
1. **A suspeita de dados era procedente e materialmente relevante**: com dados
   completos, some o paradoxo do mirror (cancelados aparentando execução MELHOR,
   μ~82-84 → μ~69-72). O dado incompleto distorcia as médias.
2. **Mas a conclusão de modelagem não muda**: AUC ~0,53/0,46 ≈ moeda ao ar.
   Mesmo com o histórico completo, a saúde de execução 30-60 dias antes do churn
   não separa quem cancela de quem fica. O sinal líder continua sendo a conversa
   (WhatsApp/tom); a execução **confirma** insatisfação, não a antecipa.

## Decisão
**Mantida, agora sobre dados completos**: execução entra no score como
**confirmador** (bloco 15%, flag `EXECUTION_IN_SCORE`), não como preditor.
As correções de cobertura beneficiam o **relatório mensal** (atividades de
ativos completas via API) e qualquer análise futura sobre o mirror.

## Notas de método
- Cards no CS/Cancelados incluem etapas do funil ("Entrada/Saída de Cliente");
  o corte as-of por `data_criacao` já exclui as criadas após o ponto de medição.
- Clientes fora do mirror usam metadados sintéticos (sem serviço/venda) — caem
  no caminho normal do score, sem as penalidades de onboarding.
- Rate-limit do ClickUp (~100 req/min) torna a rodada completa lenta (~10-15
  min nas duas listas); o retry de 429 está em `_clickup_list_tasks`.
