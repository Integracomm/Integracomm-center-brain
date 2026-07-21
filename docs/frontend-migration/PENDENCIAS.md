# Pendências de decisão do Otávio — migração de frontend

Regra combinada (21/07): discrepância de número ou dúvida de conteúdo NÃO para o
lote — entra aqui e o Otávio decide tudo junto no fim do lote.

## Lote 0

1. **Bundle JS de 755 KB (225 KB gzip)** — Recharts é o peso. Funciona normal;
   dá para dividir em chunks (carregar gráficos sob demanda) se a primeira
   carga incomodar.
   _(DECIDIDO 21/07: ADIADO COM GATILHO — ferramenta interna, rede boa,
   download único cacheado. REVISITAR quando o Portal do Cliente entrar em
   pauta: usuários externos/celular/conexão ruim → code splitting por rota.)_
   _(medição 21/07 pós-Lote 3: 895 KB / 262 KB gzip — cresce ~35 KB por lote;
   o gatilho segue o mesmo.)_

## Lote 1

1. **Régua do "MRR em risco"** — o spec do protótipo (`_shapes.md`) definia a base
   como `risk_band` alto|médio; o cockpit/Slack (`_report_from`) usa contas COM
   ALERTA ABERTO. O endpoint novo seguiu o cockpit (nenhuma tela diverge da outra),
   mas cabe decisão: qual é a régua oficial? Se preferir a por faixa, mudo o
   `_report_from` junto (muda cockpit, Slack e /api/scores de uma vez).
   _(DECIDIDO 21/07: régua = ALERTA ABERTO, em todas as telas — estado
   acionável, não saída de modelo. Definição vai no RÓTULO: a UI passa a dizer
   "MRR com alerta aberto". Telas HTML herdam o rótulo conforme migram.)_

2. **Primeira carga da Contas após restart do painel: ~2min** (reconstrução do
   índice do ClickUp + SELECT frio no RDS — custo idêntico ao do HTML antigo,
   mas no SPA o usuário vê skeleton em vez de página em branco). Proposta:
   aquecer o índice no startup do painel (prewarm) e/ou cachear o payload de
   /api/scores por ~5 min. _(decisão: pendente)_
