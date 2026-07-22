# Pendências de decisão do Otávio — migração de frontend

Regra combinada (21/07): discrepância de número ou dúvida de conteúdo NÃO para o
lote — entra aqui e o Otávio decide tudo junto no fim do lote.

## EM ABERTO — Central: reconstrução (feedback Otávio 22/07)

**Contexto honesto:** a Central entregue no Lote 5 saiu INCOMPLETA — 4 blocos do
hub HTML não foram portados e os cards compactos de área viraram seções grandes
(piorou a leitura). Isto aqui é a especificação para terminar; cada item é
independente e pode ser commitado sozinho.

**1. Blocos que faltavam, na ORDEM CANÔNICA do hub — FEITO (22/07, `06132ac`).**
   Ordem entregue: 1. Prioridades da Semana → 2. O que mudou desde ontem →
   3. Números-chave do mês → 4. Saúde por área (pior primeiro) → 5. Raio-X
   compacto por bundle → 6. Áreas (cards COMPACTOS lado a lado) →
   7. Iniciativas de maior horizonte → 8. Defasagens (recolhida).
   Como: o cálculo saiu do `_render_hub` e virou função pura compartilhada
   (`_hub_saude`, `_hub_kpis`, `_hub_area_cards`, `_hub_horizonte`,
   `_hub_defasagem_linhas`, `raiox.mini_cards_dados`) — o endpoint EMBRULHA a
   mesma régua e o `_render_hub` só formata. Diff do HTML renderizado contra o
   commit anterior, com dados reais: idêntico, fora o rótulo "MRR com alerta
   aberto" (decisão do Lote 1, aplicada agora nas duas telas) e o ponto de
   status nos chips de Operações/Financeiro.

**2. Design de "Prioridades da Semana" — FEITO (22/07).** O impacto em R$ virou
   âncora visual (número grande à direita, não chip solto), rank grande à
   esquerda, cada objetivo num card fechado e as ações por área em linhas com o
   rótulo do time fixo na margem.
   - Antes: critério de ordem (maior impacto pelo PISO da faixa; sem estimativa
     por último) e o selo "impacto não estimado".

**3. Design de "O que mudou desde ontem" — FEITO (22/07).** Os itens passaram a
   carregar `tom` do backend (`_hub_mudancas_itens`) e a tela separa **exige
   ação** (entrou em crítico, piorou de faixa, CPL subiu, iniciativa atrasada)
   do informativo.
   - Antes: cada linha leva ao recorte exato (`?ids=` honrado na tela de
     Contas, com chip "recorte do link: N conta(s) · ver todas").

**4. HOME ÚNICA — FEITO (22/07, `2d52aae`).**
   - `/` = tela inicial de TODOS; a Central do admin foi para `/central`.
   - A sidebar da home e os atalhos vêm de `/api/home`, que deriva das áreas
     liberadas para a conta (`_areas_of`, mesma régua do RBAC) na ORDEM
     CANÔNICA do painel — não mais alfabética.
   - `ROLE_HOME` de todos os papéis = `/`; o login sempre cai na home, e o
     "← Início" dos shells de área deixou de ser exclusivo do admin.
   - Raio-X por Bundle entrou em "Visões da empresa" para todos os gestores.
   - **Falta o teste com uma conta real de gestor multi-área** (o teste local
     foi com `gestor_growth`, que tem uma área só) e decidir se a home ganha
     algum número além do foco da semana.

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
