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

## Rodada de ajustes do Lote 1 (feedback do Otávio, 21/07)

- **Execução: ~25 min** · ciclos de correção: 1 (heredoc do shell, trocado por
  script — sem impacto no código). Itens: títulos sem prefixo da área (nav com
  cabeçalho de grupo); KPI cards sem corte; legendas completas nas barras de
  plano/equipe (largura 235); Contas com colunas Execução/Atrasos (campos novos
  `atrasadas`/`clickup_inativo` no /api/scores, mesmas regras dos chips HTML,
  pausados sinalizados), coluna Squad sem GC, filtros de squad/plano(B1-B5)/
  execução; Alertas com "Precisão do modelo + evolução do risco" em `<details>`
  colapsado com fetch sob demanda (endpoint novo /api/growth/modelo reusando
  _modelo_precisao + grw_risk_snapshot).
- Lição p/ extrapolação: a rodada de ajustes custa na ordem do próprio lote —
  manter nos planos 1 rodada por lote.

## Rodada de ajustes 2 do Lote 1 (feedback com screenshot, 21/07)

- **Execução: ~12 min** · ciclos de correção: 0. Causa-raiz das legendas
  faltando: o Recharts pula rótulos alternados por padrão (interval auto) —
  corrigido na BIBLIOTECA (BarListH: interval=0 + altura por linha no chamador
  + cor por item via Cell), beneficia todas as telas futuras. Itens: motivos
  com respiro (52px/linha), plano/equipe completos, taxa sem B1 no gráfico com
  GERAL primeiro e destacado (B1 segue na tabela — nenhum dado some),
  comparativo novos×antigos de volta na Evolução (campos saidas_novos/antigos
  no payload, MESMA régua _canc_legado do HTML), paginação em Alertas (25/pág).

## Lote 2 — Pré-vendas (Qualificação+Speed), Melhor Horário, Win/Loss

- **Início:** 21/07 10:41 · **fim:** 10:54 · **execução efetiva: ~13 min**
  (medido no relógio, corrigido — a estimativa de memória dizia 45; o deploy
  dos Lotes 0-1 correu em BACKGROUND sem custar tempo do lote; a leitura das
  ~600 linhas de compute do sales/ui.py foi o custo dominante).
- **Entregue:** `app/sales/dados.py` (pv_dados + winloss_dados — transcrição
  fiel das queries; funil REUSA _funil_oficial do Marketing); /api/prevendas,
  /api/vendas/winloss, /api/prevendas/horarios (embrulha o _horarios_calc que
  JÁ era puro); chaveamento por view em /prevendas e /vendas; 3 telas React
  (PV = funil+speed numa página, conforme o desenho do lote; Melhor Horário
  com 2 heatmaps dia×hora + grades origem×hora e colaborador×hora; Win/Loss
  com Pareto + cards por bundle + heatmaps motivo×origem e motivo×closer);
  extensão aprovável na biblioteca: Heatmap.rowScale (escala por linha, padrão
  das grades da tela antiga). Honestidade: win rate NÃO entrou no Win/Loss —
  a tela HTML não o calcula e inventar régua violaria a regra (vem no Lote 3
  com a régua do Funil de Fechamento).
- **Ciclos de correção: 1** (leftover de código morto na página de horários).
- **Paridade: 10/10** (3 probes iniciais "divergentes" eram formato do próprio
  check — separador de milhar; números batiam).
- **Validação:** 6 rotas conferidas (3 SPA + ponte/funil de vendas seguem
  HTML), 3 endpoints 200 (1,8-3,6s), 2 telas conferidas no navegador com
  dados reais; 56 testes ok.
- **Interrupção operacional:** 0.

## Rodada de ajustes do Lote 2 (feedback do Otávio, 21/07)

- **Execução: ~40 min** · ciclos de correção: 1 (gerador de strings do script).
- Itens: (1) **ⓘ "como ler este campo" de volta em TODAS as telas SPA** — raiz
  resolvida com /api/help servindo os textos do help_texts.py (fonte ÚNICA,
  HTML e SPA compartilham; componente Hint com cache); (2) PV recuperou a
  Evolução mensal 6m e o Diagnóstico do especialista (rotulado com persona +
  'regras determinísticas'); (3) Melhor Horário: heatmaps com as MESMAS linhas
  de hora (07h alinhado com 07h), listas de melhores horários por agendamento
  E por taxa (só janelas 5+ ligações), grades origem/colaborador em modo dense
  — medido no DOM: zero overflow horizontal; (4) Win/Loss: heatmaps INVERTIDOS
  (origem×motivo e closer×motivo, célula = % das perdas da LINHA — responde
  'esse closer perde por quê'), dense + rowScale, sem overflow; (5) nav de
  Vendas completa (7 views). Lição de biblioteca: dense (colunas estreitas sem
  scroll) e o alinhamento por linhas compartilhadas viram padrão dos próximos
  heatmaps.

## Rodada de ajustes 2 do Lote 2 (21/07)

- **Execução: ~35 min** · ciclos de correção: 2 (encoding de heredoc → script
  em arquivo; âncora de inserção do help). Itens: (1) **37 usos de ⓘ nas 6
  telas, 100% com entrada no help** (8 entradas NOVAS escritas no padrão 16/07
  em help_texts.py — fonte única); (2) régua da TAXA do Melhor Horário
  refinada na FUNÇÃO COMPARTILHADA (hipótese do Otávio confirmada: agendamento
  de indicação/inbound sem ligação inflava a taxa) — numerador só com deals
  que têm ligação registrada, excluídos contados e avisados nas DUAS UIs;
  (3) headers dos 2 heatmaps equalizados (desalinho 16px → 2px, medido no
  DOM via headerClassName no SectionCard); (4) nota sob o mapa de taxa com a
  contagem de agendamentos sem ligação.
- Nota: a percepção de "menu dentro do Win/Loss antigo" em Vendas é o estado
  TRANSITÓRIO da migração (SPA e HTML coexistem com shells diferentes até a
  área migrar inteira — Lote 3 em execução converge Funil/Ponte/Ciclo).

## Rodada de ajustes 3 do Lote 2 — taxa v3 (21/07, ~14:20-14:40)

- **Execução: ~20 min** (inclui validação contra o banco) · ciclos: 0.
- Feedback do Otávio: células ainda passavam de 100% ("outros canais impactando").
- **Causa REAL (não era canal vazando): eventos distintos nos dois lados da
  divisão** — numerador contava o agendamento na hora em que o card ENTROU na
  etapa; denominador, a ligação na hora em que foi CONCLUÍDA. Ligação 9h que
  agenda p/ 10h = célula das 10h com mais agendamentos que ligações.
- **Régua v3 (na função COMPARTILHADA _horarios_calc):** a taxa agora mede a
  CONVERSÃO DA LIGAÇÃO — célula = hora em que a ligação foi feita; numerador =
  ligações creditadas (a ÚLTIMA do deal antes da 1ª entrada em agenda,
  tolerância 2h p/ atividade concluída depois de mover o card); 1 crédito por
  deal ⇒ numerador ⊆ denominador ⇒ **≤100% por construção**. Agendamentos sem
  ligação seguem fora e contados na nota.
- **Validação no banco:** 4 cenários (mês, ano, junho, mês+B3) — 0 células
  >100%, 0 órfãs; taxa geral 3-4% (plausível p/ ligação fria); helps e
  subtítulos atualizados nas DUAS UIs.

## Lote 3 — parte Vendas: Funil de Fechamento, Ponte PV→Vendas, Ciclo & Empacados (21/07)

- **Início:** ~14:15 · execução efetiva **~40 min** até o build (3 dados-fns +
  3 endpoints + 3 telas + nav + helps + paridade); validação no navegador na
  sequência.
- **Motivação da ordem:** feedback do Otávio — entrar em Vendas abria o painel
  ANTIGO (view padrão `funil` era HTML) e o Win/Loss abria o SPA com outra
  sidebar. Migrando funil+ponte+ciclo, a ENTRADA da área já é SPA e a nav fica
  uma só (restam Melhor Horário/Desempenho/Performance como "(HTML)").
- **Entregue:** `vd_funil_dados`/`vd_ponte_dados`/`vd_ciclo_dados` em
  sales/dados.py (transcrição fiel; funil REUSA _funil_oficial + ESP.insights_
  vendas; serve-stale _kick_deals_sync no endpoint do funil como na tela);
  /api/vendas/{funil,ponte,ciclo}; 3 páginas React; win rate oficial =
  Oportunidade→Booking meta 15% NA tela do Funil (como decidido — Win/Loss não
  inventa régua); 4 entradas novas de help (Diagnóstico/Leitura/tempo de
  qualificação/origem/Ciclo e distribuição) no padrão 16/07.
- **Paridade: 3/3 telas** (kpis, etapas do funil oficial, segmentos da ponte,
  empacados por deal_id — HTML × JSON no mesmo instante).
- **Ciclos de correção: 0** (typecheck e build de primeira; 56 pytest ok).
- Bundle: 755→895 KB com Lote 2+3 (code splitting segue ADIADO com gatilho
  Portal do Cliente — PENDENCIAS.md).

## Lote 3 — fechamento: Ponte em Pré-vendas + Marketing Canais/Origens (21/07, ~15:10-15:50)

- **Execução efetiva: ~35 min** · ciclos de correção: 0 (tsc/build/pytest de
  primeira). **LOTE 3 COMPLETO.**
- **Ponte PV → Vendas em Pré-vendas** (pedido do Otávio): a MESMA página React
  serve as duas áreas — como no HTML, que já usava uma função só
  (`_vd_ponte(area=...)`); helps já eram aliased
  (`HELP["prevendas/ponte"] = HELP["vendas/ponte"]`). Custo: 1 linha de router
  + env. Nav de PV agora só tem Desempenho Individual "(HTML)".
- **Marketing Canais + Origens**: `marketing/dados.py` novo (mkt_canais_dados/
  mkt_origens_dados) EMBRULHANDO ranking_canais/funil_por_origem de
  analysis.py (que já eram puros — o melhor caso da regra); evolução mensal da
  mídia paga e chips escalar?/revisar transcritos com as MESMAS regras;
  endpoints /api/marketing/{canais,origens} (com o serve-stale
  _kick_deals_sync da área); hook view_response no handler de /marketing
  (primeira vez da área no chaveamento); 2 páginas React (origens com
  drill-down campanha/criativo SEM recarregar a página — estado local, mesma
  API); grupo Marketing completo na nav do shell (10 views, 2 SPA); 5 entradas
  novas de help (Ranking, Evolução mídia paga, Funil por origem, Campanhas e
  criativos) no padrão 16/07.
- **Paridade: canais 5/5 + evolução, origens 14/14 linhas + chips idênticos
  (escalar? prospeccao; revisar shopee/meta_ads_v3) + drill-down 6/6.**
- Verificado no navegador: canais (ROAS 9.2x Google vs 1.4x Meta no mês),
  origens com chips, drill-down shopee, ponte em /prevendas com nav correta;
  console limpo. Bundle 905 KB.
- **Estado do redesenho pós-Lote 3:** Growth 3 views SPA · Marketing 2 ·
  Pré-vendas 4 · Vendas 4. Restam (Lotes 4-6): Marketing pesado (visao, metas,
  funil, midia, lag, planejador, criativos, ciclo), PV sdrs, Vendas horarios/
  closers/forecast, Central/Raio-X/Financeiro/Semana, cauda (Admin fica HTML).

## Ajustes 22/07 (feedback do Otávio): link ClickUp em Atrasos + Atendimento por origem

- **Link do ClickUp em Contas (SPA):** na tela HTML, Execução e Atrasos eram
  células-LINK para o card do cliente no ClickUp (card_url) — os badges do SPA
  perderam isso na migração. Fix: /api/scores ganhou `clickup_url` por conta e
  os dois badges viraram âncoras (target _blank), paridade com o HTML.
- **Atendimento de ligações por origem × hora (seção NOVA no Melhor Horário):**
  o mapa "Taxa de conversão da ligação" saiu do SPA (Otávio: muitos
  agendamentos não nascem de ligação — insight fraco) e no lugar entrou a
  pergunta certa: das ligações FEITAS para leads de cada canal naquela hora,
  % que o lead ATENDEU. Viabilizado por um achado: a telefonia escreve o
  desfecho no subject da atividade ('atendida às …' / 'não foi atendida:
  Caixa postal…'). Coluna nova `sales_activities.atendida` (BOOLEAN; NULL =
  ligação manual sem desfecho, fica FORA da taxa), derivação no sync,
  bloco no `_horarios_calc` compartilhado, seção nas DUAS UIs (HTML ganhou a
  seção; SPA trocou o card), help novo padrão 16/07. A lista "Melhores
  horários por taxa" continua (a ressalva dos agendamentos sem ligação migrou
  p/ lá). **Cobertura: desfecho coletado a partir de 22/07** — histórico
  depende de re-backfill (só em janela aprovada; ~90 páginas, custo <0,1% do
  orçamento diário do Pipedrive).

## Ajustes 22/07 (2ª rodada): layout do Melhor Horário + backfill do desfecho

- **PISO DE RESERVA no cliente do Pipedrive (guarda-corpo permanente)**: o
  `_get` agora lê `x-daily-ratelimit-token-remaining` a cada resposta e
  ABORTA qualquer coleta nossa (DailyBudgetExceeded) ao encostar no piso
  `PIPEDRIVE_MIN_TOKENS` (padrão 300k; backfill rodou com 400k). Vale para
  TODAS as coletas, não só o backfill — a regra dura do Otávio deixou de
  depender de disciplina de script e virou código.
- **Backfill do desfecho** (janela aprovada 22/07): since=01/03, teto 260 pág,
  pausa 1,2s, saldo medido antes/depois. Saldo antes: 1.068.620 de 1.170.000
  (91,3%).
- **Layout do Melhor Horário (feedback Otávio)**: "Agendamentos — hora × dia"
  passa a ocupar a LINHA INTEIRA sozinho; "Atendimento de ligações — origem ×
  hora" desce e fica LADO A LADO com "Padrão por origem do lead — origem ×
  hora" (mesmo assunto: comportamento por canal — um mostra quando o lead
  ATENDE, o outro quando ele AGENDA), headers equalizados em 72px.
- **"Melhores janelas de aproveitamento"** (lista nova, sob o mapa de
  atendimento, nas DUAS UIs): ranking canal+hora por % de atendimento, só
  janelas com 5+ ligações, com help próprio. Distinção explicitada no texto:
  aproveitamento da DISCAGEM ≠ conversão em reunião (essa fica em "Melhores
  horários por taxa").
- Paridade HTML×payload do ranking novo: OK (Google Ads 08h 83%, 09h 80%,
  12h 80%; Orgânico 11h 54%). tsc limpo, 56 pytest ok.
