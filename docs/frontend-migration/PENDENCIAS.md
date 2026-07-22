# Pendências de decisão do Otávio — migração de frontend

Regra combinada (21/07): discrepância de número ou dúvida de conteúdo NÃO para o
lote — entra aqui e o Otávio decide tudo junto no fim do lote.

## EM ABERTO — Central: reconstrução (feedback Otávio 22/07)

**Contexto honesto:** a Central entregue no Lote 5 saiu INCOMPLETA — 4 blocos do
hub HTML não foram portados e os cards compactos de área viraram seções grandes
(piorou a leitura). Isto aqui é a especificação para terminar; cada item é
independente e pode ser commitado sozinho.

**1. Blocos que faltam, na ORDEM CANÔNICA do hub** (ver `api.py`, corpo do
`_render_hub`, comentário "mudou → saúde → raio-x compacto → cards de área →
iniciativas → defasagem"):
   1. Prioridades da Semana (existe) → 2. O que mudou desde ontem (existe) →
   3. **Números-chave do mês** (`kpi_html`) → 4. **Saúde por área** (`hbar`,
   ordenado da área que mais demanda atenção) → 5. **Raio-X compacto por
   bundle** (`raiox.mini_cards_html` — precisa de versão em dados) →
   6. **Áreas** (`area_cards` — CARDS COMPACTOS lado a lado, não seções
   grandes) → 7. **Iniciativas de maior horizonte** (gargalos com impacto R$
   que não viraram objetivo da semana) → 8. Defasagens (recolhida).
   *A ordem importa: é a rotina de leitura diária do Otávio.*

**2. Design de "Prioridades da Semana":** hoje "parecem informações juntas e
jogadas". Precisa de hierarquia — impacto em R$ como âncora visual, separação
clara entre objetivos, e as ações por área legíveis de relance.
   - JÁ FEITO: critério de ordem (maior impacto pelo PISO da faixa; sem
     estimativa por último) e o selo "impacto não estimado".

**3. Design de "O que mudou desde ontem":** destacar as mudanças que exigem ação
(ex.: conta ENTROU em crítico) das informativas.
   - JÁ FEITO: cada linha leva ao recorte exato (`?ids=` honrado na tela de
     Contas, com chip "recorte do link: N conta(s) · ver todas").

**4. HOME ÚNICA (decidido pelo Otávio 22/07, via AskUserQuestion):**
   - Nova tela inicial para TODOS (admin e gestores). Sidebar mostra só o que a
     pessoa acessa: as áreas dela + "Visões da empresa".
   - Resolve dois problemas REAIS e anteriores à migração: (a) o gestor com
     várias áreas cai hoje na 1ª área em ordem ALFABÉTICA (`sorted(áreas)[0]`
     em `api.py` login) — arbitrário; (b) ele NÃO tem como trocar de área pela
     interface (o "← Início" só existia para admin).
   - A Central vira item do bloco **Admin** (já renomeada de "Início" para
     "Central" no menu).
   - Conteúdo da home: atalhos do que a pessoa acessa + o foco da semana do
     time dela (`/api/semana/foco` já existe).
   - **Raio-X por Bundle: VISÍVEL para todos os gestores** (decidido) — hoje o
     handler já libera por sessão; falta só entrar na navegação deles.

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
