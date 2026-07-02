# Casca — backend (staging)

Fundação modular + agente-piloto de Growth (risco de churn). Tudo somente
leitura nas fontes; nenhuma ação consequente; staging-first.

## Estrutura

```
app/
  config.py              # configuração por env (segredos fora do código)
  agents/
    base.py              # CONTRATO de agente: collect→analyze→score→persist→surface
    registry.py          # registrar um novo agente = register(MeuAgente())
    growth/
      execution_score.py # porte de computeLiveScore (sinal líder de execução)
tests/                   # pytest
```

## Encaixar um novo agente (ex.: Financeiro)

1. Criar `app/agents/financeiro/agent.py` com uma subclasse de `Agent`
   implementando as 5 etapas e definindo `key` + `role`.
2. `register(FinanceiroAgent())` no boot.
3. O painel passa a exibi-lo sob o papel `role` (RBAC) automaticamente.

A casca (backend, RBAC, painel, auditoria, agenda) não é reaberta — o agente
de Growth é a implementação de referência do contrato.

## Subir a aplicação web (localhost:8000)

A partir da **raiz do projeto** (`Nova aplicação Integracomm\`):

```powershell
backend\.venv\Scripts\python -m uvicorn backend.main:app --port 8000
```

Abra **http://localhost:8000** → você cai na tela de **/login**.

**Login e RBAC (básico):**
- Usuários: **`adm@integracomm.com.br`** (admin — vê tudo: hub central + Growth;
  `admin` segue como alias, mesma senha) e `gestor_growth` (só a área de Growth;
  o hub redireciona para `/growth`). Login é case-insensitive.
- **Senhas**: vivem no `.env` da raiz (`AUTH_ADMIN_PASSWORD`,
  `AUTH_GESTOR_GROWTH_PASSWORD`). São **geradas automaticamente no 1º boot** se
  não existirem (nunca impressas). Para trocar: edite o `.env` e reinicie.
- Sessão: cookie HMAC-assinado (`AUTH_SECRET`, também no .env), expira em 12h.
  Logout no rodapé do sidebar.
- Todas as rotas `/api/*` exigem sessão (401 sem login); `/healthz` é aberto.
- Logins são auditados em `audit_log` (actor = usuário).

**Pré-requisitos** (já satisfeitos no host atual): Postgres local rodando
(serviço `postgresql-x64-18`) com o banco `integracomm_ia` populado, e o `.env`
da raiz com `APP_DATABASE_URL` + credenciais das fontes. Para repopular os
scores: `backend\.venv\Scripts\python -m scripts.run_portfolio` (rodada ao vivo).

## Agendamento diário (Windows Task Scheduler)

O agente roda automaticamente **1× por dia às 06:00** via `run_agent_scheduled.ps1`
(raiz do projeto): executa a rodada completa da carteira, envia o relatório ao
Slack ao final (`--slack`) e grava o output em `logs\agent_YYYY-MM-DD.log`. Em
erro, registra no log e avisa o grupo do Slack.

**Registrar a tarefa** (PowerShell **como administrador**, uma vez):

```powershell
schtasks /Create /TN "IntegracommIA-RodadaDiaria" /SC DAILY /ST 06:00 /F /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"C:\Users\USUARIO\Desktop\Nova aplicação Integracomm\run_agent_scheduled.ps1\""
```

> Sem `/RU`/`/RP`, a tarefa roda com o usuário atual **apenas com sessão ativa**
> (máquina ligada e logada) — suficiente para o piloto interno.

**Verificar se está agendada:**

```powershell
schtasks /Query /TN "IntegracommIA-RodadaDiaria" /V /FO LIST
```

**Rodar manualmente fora do horário** (qualquer uma das duas):

```powershell
schtasks /Run /TN "IntegracommIA-RodadaDiaria"      # dispara a tarefa agendada
powershell -ExecutionPolicy Bypass -File .\run_agent_scheduled.ps1   # direto, da raiz
```

**Remover:** `schtasks /Delete /TN "IntegracommIA-RodadaDiaria" /F`

O resultado de cada rodada fica em `logs\agent_YYYY-MM-DD.log`; a última linha é
`OK: rodada concluida ...` ou `ERRO: ...`.

## Análise de tom via Claude (3b)

O sinal `tom_claude` (bloco tone, peso intra 0,5) vem de `scripts/run_tone_analysis.py`:
classifica o tom das conversas POR SEMANA (caloroso/neutro/transacional/negativo)
via **Claude Sonnet** (`claude-sonnet-5`, thinking off, saída estruturada, system
prompt cacheado), extrai iniciativa (cliente/equilibrada/equipe) e temas de
insatisfação. Requer `ANTHROPIC_API_KEY` no .env da raiz.

```bash
python -m scripts.run_tone_analysis --test    # 3 contas de validação
python -m scripts.run_tone_analysis           # base inteira (avaliáveis)
```

Resultados persistem em `signal_snapshots` (signal_key `tom_claude`) e cada
análise é auditada (`tone_analysis` no audit_log, com janela e tokens). O
`run_portfolio` anexa a série cacheada automaticamente na rodada seguinte; conta
sem análise segue pontuando sem o sinal (renormaliza dentro do bloco tone).

## Rodar testes / instalar deps (host de staging — Python 3.12+)

```bash
pip install -e ".[dev]"
cp ../.env.example ../.env   # preencher credenciais RO
pytest
```

## Páginas e rotas

- `GET /` — **hub central**: a inteligência que enxerga todas as áreas. KPIs da
  empresa, iniciativas sugeridas (derivadas dos sinais das áreas ativas) e o
  grid de áreas. Growth é a 1ª área ativa; Marketing/Pré-vendas/Financeiro/
  Operações são placeholders — cada nova área é um novo agente na mesma casca.
- `GET /growth?view=` — área de Growth/Assessoria, navegada pelo sidebar:
  **contas** (tabela filtrável + paginada + diretrizes), **alertas** (fila por
  severidade), **playbooks** (boas práticas aprendidas + ações recentes),
  **relatorios** (estado atual em blocos — a mesma base do envio ao Slack).
- `GET /api/reports/summary?format=json|text` — relatório do estado; `text` é o
  mesmo texto enviado ao Slack.
- `POST /api/reports/send-slack` — envia o relatório ao grupo do Slack
  (`SLACK_WEBHOOK_URL` no .env). Também disponível como botão na aba
  **Relatórios**, via `scripts/send_slack_report.py` (com `--dry-run`), ou
  automaticamente ao fim da rodada: `run_portfolio --slack`. Todo envio é
  auditado (`report_slack`).
- `GET /api/scores` · `/api/alerts` · `/api/practices` — JSON.
- `POST /api/interventions` · `POST /api/interventions/{id}/result` — registrar a
  ação tomada com uma conta e o desfecho (`retido|cancelou|sem_efeito`).

## Aprendizado de boas práticas

Toda ação tomada com um cliente pode ser registrada (`interventions`: ação, dor
dominante no momento, estágio, quem agiu) e fechada com o desfecho. Ações com
desfecho **retido** viram *práticas de referência*: a diretriz de ação passa a
citá-las automaticamente em casos futuros com a **mesma dor** (📚 no painel).
Hoje o registro é via API; a UI de registro entra na fase do auth/RBAC.

## Execução no score (bloco 15%)

Ativa por padrão via flag `EXECUTION_IN_SCORE` (env; `0` desliga). O sinal entra
como **confirmador** (risco direto = 1 − exec_score/100, porte fiel do
computeLiveScore, as-of via mirror ClickUp). Evidência documentada: não prediz
churn sozinha (AUC 0,49/0,44 em churn−30/−60), e a 15% renormalizado é neutra no
ranking (AUC 0,822→0,820) — entra pelo valor explicativo, não preditivo.

## Design System

A identidade visual (tema **dark**, marca **amarelo Integracomm**) foi desenhada
pelo Claude Design e destilada em **tokens**. Regra: **nenhuma cor/fonte/
espaçamento hardcodado** na UI — tudo consome as variáveis.

**Fonte da verdade:** [`frontend/design-tokens.css`](../frontend/design-tokens.css)
— `:root { --... }` com grupos: superfícies (`--bg-*`, `--surface-*`), bordas,
texto (`--text*`), **status** (`--status-baixo|medio|alto|critico|semdados`),
tipografia (`--font-display` Poppins, `--font-body` DM Sans, escala `--fs-*`,
pesos), raios (`--radius*`), espaçamento (`--space-*`), layout (`--rail-width`,
`--content-max`). Inclui a classe utilitária `.chip` (badge de status).

**Como é consumido:** `app/api.py` lê o `design-tokens.css` e o injeta inline no
`<style>` da página servida (`GET /`) e do export estático — um único ponto de
verdade para servidor e snapshot. Fontes vêm do Google Fonts (DM Sans + Poppins).

**Mapeamento semântico (faixa de risco / severidade → cor):**

| faixa / severidade | token | cor |
|---|---|---|
| baixo / saudável | `--status-baixo` | `#3DDC84` verde |
| médio / atenção | `--status-medio` | `#F5C518` amarelo |
| alto | `--status-alto` | `#FF8A3D` laranja |
| crítico | `--status-critico` | `#FF4D5E` vermelho |
| sem dados | `--status-semdados` | `#77777E` cinza |

**Componentes reaproveitáveis** (definidos em `_render`, estilizados via tokens):
shell com `.rail` (sidebar) + `main`, `.kpi` (cartões de topo), `.tbl`/`.row`
(tabelas em grid), `.chip` (badges), `.filters` (barra de filtros), `.guide`
(diretriz de ação).

**Replicar para novas áreas (Marketing, Pré-vendas, …):** o novo agente reusa a
MESMA casca visual — importa `design-tokens.css`, mantém o shell (`.rail` + `main`)
e adiciona seu item no `<nav>`; suas tabelas/cards usam `.tbl/.row/.kpi/.chip`.
Só o conteúdo (colunas/dados do agente) muda. Assim a identidade fica consistente
sem reimplementar estilos.

**Regenerar o painel estático** (snapshot fiel ao design, do banco):

```bash
backend/.venv/Scripts/python -m scripts.export_panel   # -> painel_growth.html (raiz)
# ou servir ao vivo: uvicorn app.api:app  (GET /?role=admin)
```

### Fidelidade e diferenças conhecidas
- Tokens (cores, fontes, raios, dimensões de layout) foram **extraídos do bundle
  de referência** (`Painel Growth - Integracomm.html`) — fidelidade alta por
  construção. O arquivo de referência é artefato de design (React), **não** vai
  para produção.
- A validação pixel-a-pixel não roda no sandbox atual (o MCP do navegador bloqueia
  `localhost`/`file:`/`data:`); conferir abrindo `painel_growth.html`.
- Diferenças esperadas: a referência é React com possíveis micro-interações
  (hover/animações) não replicadas 1:1; larguras de coluna do grid são
  aproximadas dos valores da referência; fontes carregadas via CDN (Google Fonts)
  em vez de embutidas no bundle.
