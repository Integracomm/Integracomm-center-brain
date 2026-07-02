# Reavaliação: execução prediz churn? (2026-07-02)

## Contexto
A conclusão original do modelo — **"execução não prediz churn"** (AUC ~0,49/0,44 em
churn−30/−60) — foi levantada como suspeita pelo Otávio: ela saiu do espelho
(mirror Supabase) da Operação, que se descobriu **incompleto**. Duas falhas:

1. **Truncamento silencioso**: o PostgREST do mirror corta toda resposta em 1.000
   linhas mesmo pedindo mais — o leitor de subtarefas recebia lotes cortados sem
   erro. Corrigido com paginação por offset (`app/sources/mirror.py`).
2. **Cobertura parcial**: para os clientes ativos casados à lista "Assessoria" do
   ClickUp, o mirror tinha só **~51% das subtarefas** (mediana 90% por card, mas
   vários clientes com 0 — ex.: Supley 431 reais vs 0 no mirror).

## O que foi testado
Repetição do experimento caso-controle (script
`backend/scripts/offline_exec_clickup_full.py`), mantendo tudo idêntico ao
original — mesma coorte (61 cancelados + 200 controles), mesmos metadados de
cliente do mirror, mesma lógica `execution_asof` (as-of, sem vazamento) —
**trocando só a fonte das subtarefas** por: (a) mirror com paginação corrigida e
(b) lista Assessoria completa via API oficial do ClickUp.

## Resultado

| horizonte | fonte | AUC | cancelados | controles |
|-----------|-------|-----|-----------|-----------|
| churn−30 | mirror (paginado) | **0,419** | n=45, μ=81,2 | n=120, μ=76,2 |
| churn−30 | clickup ao vivo | 0,372 | **n=4** ⚠️ | n=120, μ=71,9 |
| churn−60 | mirror (paginado) | **0,361** | n=45, μ=83,5 | n=120, μ=76,2 |
| churn−60 | clickup ao vivo | 0,525 | **n=4** ⚠️ | n=120, μ=71,9 |

## Achado principal
**O ClickUp ao vivo não pode reconstruir a execução histórica da coorte de churn.**
Os cards dos clientes que cancelaram são removidos/movidos ao encerrar o contrato
— a lista Assessoria tem apenas 76 tarefas arquivadas (1 card raiz). Por isso só
~4 dos 61 cancelados casam (amostra sem valor). **O mirror é a única fonte
histórica** de quem já saiu.

Com a paginação do mirror corrigida (mais dados que antes), a execução continua
**não-preditiva — e levemente invertida**: cancelados tinham score de execução
até um pouco MELHOR que os controles (μ ~82 vs ~76), AUC abaixo de 0,5.

## Por que execução não antecede o churn (hipótese)
O score de execução tem penalidades relativas às "últimas 2 semanas". Um cliente
desengajando gera **menos** tarefas — menos entregas atrasadas recentes, menos
lotes suspeitos — então o score paradoxalmente **sobe** perto do churn. Execução
**confirma** insatisfação já instalada; não a antecipa. Isso é coerente com o
sinal líder ser a conversa (WhatsApp/tom), não a entrega.

## Decisão
**Mantida**: execução entra no score como **confirmador** (bloco 15%, flag
`EXECUTION_IN_SCORE`), não como preditor. A correção de cobertura de dados tem
valor **para o relatório mensal** (atividades de clientes ATIVOS agora completas
via API), mas **não altera o modelo de churn**.

## Limite honesto
Não é possível validar a completude do mirror para a coorte de churn (o ClickUp
já não tem esses clientes para comparar). A conclusão vale sobre a melhor fonte
histórica disponível. Se no futuro a Operação passar a reter o histórico de
cancelados no ClickUp (ou o mirror for auditado como completo), vale reabrir.
