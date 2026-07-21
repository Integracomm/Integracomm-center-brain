# Medição real da migração de frontend (pedido Otávio 21/07/2026)

Registro por lote: tempo de execução efetiva, ciclos de correção, onde o
tempo foi, e interrupções operacionais (separadas do custo da migração).
Base para reextrapolar os lotes 2–6 com dado real.

## Lote 0 — Fundação

- **Início:** 21/07 09:00 · **fim da execução:** 21/07 09:11 · **execução efetiva: ~11 min**
  (mais ~4 min de verificação/registro na sequência).
- **Entregue:** scaffold Vite+TS+Tailwind4+React Router; biblioteca inteira portada
  (6 charts + blocks + kpi/caveat/states + 10 componentes ui) com as 3 correções
  aprovadas (2× hachura theme-aware, Fragment key, caveats Set→array); 2 primitivos
  novos (BarListHGrouped, MetaBar); shell (sidebar/tema/guard 401); cliente de API;
  vitrine /app exercitando tudo; app/spa.py servindo estático com chaveamento por
  rota (SPA_ROUTES); estágio bun no Dockerfile do deploy.
- **Ciclos de correção: 0** — typecheck e build passaram de primeira (9,1s de build);
  console do navegador sem erros; guard e rotas antigas verificados via HTTP.
- **Onde foi o tempo:** ~3 min instalação do bun (máquina não tinha Node/npm/bun —
  imprevisto nº 1); ~2 min leitura do protótipo p/ mapear deps; ~4 min geração de
  código; ~2 min build+verificação.
- **Interrupção operacional:** 0 min dentro do lote (o backfill do Pipedrive seguia
  em background, sem custo de atenção).
- **Nota honesta:** o Dockerfile com estágio bun ainda NÃO foi exercitado num build
  real de deploy — primeiro deploy do Lote 1 é o teste; risco baixo, mas existe.

## Lote 1 — Growth core (Contas, Alertas, Cancelamentos)

- **Início:** 21/07 09:13 · **fim:** 21/07 09:32 · **execução efetiva: ~19 min**
  (endpoints + 3 telas + chaveamento por view + paridade + validação).
- **Entregue:** `/api/scores` com `kpis` (reuso do `_report_from` — mesma régua do
  cockpit/Slack) + `squad`/`responsavel` por conta; `/api/alerts` com `kpis`;
  `/api/growth/cancelamentos` novo, extraído para `_cancel_dados()` (função pura;
  `_mrr_por_bundle` também extraído e compartilhado com o HTML); 3 telas React
  (Contas portada da referência; Alertas e Cancelamentos compostas — os arquivos
  do protótipo eram PLACEHOLDER, ver observação); chaveamento por VIEW
  (`SPA_GROWTH_VIEWS`, habilitado só no .env local); tabelas completas preservadas
  em "ver tabela completa"; ressalvas ao lado do número (B5 base pequena, MRR
  estimado ≈, sem-motivo, GC vazio).
- **Ciclos de correção: 1** (campo `meses_disponiveis` faltando no tipo TS — 1 min).
- **Paridade: 9/9 checks OK** (KPIs do mês, sublabel e taxa do B3, taxa geral —
  HTML antigo × JSON novo batendo com a planilha mudando DURANTE o dia).
- **Onde foi o tempo:** ~6 min extração do compute p/ funções puras (a parte de
  engenharia de verdade); ~8 min geração das 3 telas; ~5 min validação
  (paridade + HTTP + navegador). Um SELECT frio no RDS custou ~1 min de espera.
- **Interrupção operacional:** 0 no lote (backfill do Pipedrive rodando em
  background no servidor, sem custo de atenção).
- **Observações:** (1) no protótipo, só Contas tinha referência real — Alertas e
  Cancelamentos eram placeholders; compor com a biblioteca custou pouco (a regra
  de escolha de visual decide rápido); (2) 1 pendência de régua registrada
  (MRR em risco: alerta aberto vs faixa — PENDENCIAS.md).

## Extrapolação (dado real, não estimativa)

- **Medido:** Lote 0 = 11 min · Lote 1 (3 telas + 2 endpoints + paridade) = 19 min.
- **Custo por tela observado: ~5–7 min** (incluindo endpoint e paridade), quando a
  fonte de cálculo já existe em função reutilizável.
- **Lotes 2–6 (~24 telas restantes):** extrapolando com folga 2× para telas sem
  referência e endpoints que exigem extração de compute maior (Ponte, Central,
  Raio-X): **~4 a 7 horas de execução efetiva no total**, distribuídas por lote —
  mais o tempo de validação do Otávio entre lotes e as interrupções operacionais
  do dia a dia (que dominam o calendário, não a execução).
- **Conclusão honesta:** os "9–11 dias de execução" eram hábito de estimativa
  humana. O gargalo real do calendário passa a ser (b) validação + operação
  diária, não (a) execução. Proposta: 1 lote por dia útil nos dias de operação
  normal → migração completa em ~1 semana de calendário.
