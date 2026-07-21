# Pendências de decisão do Otávio — migração de frontend

Regra combinada (21/07): discrepância de número ou dúvida de conteúdo NÃO para o
lote — entra aqui e o Otávio decide tudo junto no fim do lote.

## Lote 0

1. **Bundle JS de 755 KB (225 KB gzip)** — Recharts é o peso. Funciona normal;
   dá para dividir em chunks (carregar gráficos sob demanda) se a primeira
   carga incomodar. Proposta: deixar como está até o Lote 2 e medir na prática.
   _(decisão: pendente)_

## Lote 1

1. **Régua do "MRR em risco"** — o spec do protótipo (`_shapes.md`) definia a base
   como `risk_band` alto|médio; o cockpit/Slack (`_report_from`) usa contas COM
   ALERTA ABERTO. O endpoint novo seguiu o cockpit (nenhuma tela diverge da outra),
   mas cabe decisão: qual é a régua oficial? Se preferir a por faixa, mudo o
   `_report_from` junto (muda cockpit, Slack e /api/scores de uma vez).
   _(decisão: pendente)_
