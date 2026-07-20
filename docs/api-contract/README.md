# Pacote de contrato da API — Integracomm IA

Gerado em **20/07/2026** a partir do painel local rodando (dados reais capturados e
**anonimizados**: nomes de clientes → `CLIENTE NNN`, pessoas → `contato-N` / `gestor-N` /
`Lead N`, URLs de planilha/ClickUp → placeholder). **Estrutura, nomes de campo e tipos
estão exatamente como a API retorna** — construa o frontend contra estes formatos.
Listas grandes foram cortadas para 10–15 itens representativos (incluindo casos de
borda: campos nulos, `evaluable: false`, avisos), preservando o envelope.

- `openapi.json` — schema OpenAPI completo exportado do FastAPI (49 rotas).
- `api__*.json` — uma resposta real por endpoint JSON de tela (tabela abaixo).

## Tela / aba → endpoint → arquivo de exemplo

| Tela / aba | Endpoint | Arquivo de exemplo |
|---|---|---|
| Growth · Contas (tabela de scores) | `GET /api/scores` | `api__scores.json` |
| Growth · Alertas | `GET /api/alerts` | `api__alerts.json` |
| Growth · Playbooks (boas práticas) | `GET /api/practices` | `api__practices.json` (lista vazia hoje — formato real) |
| Central · resumo executivo | `GET /api/reports/summary` | `api__reports__summary.json` |
| Growth · Relatório mensal da conta | `GET /api/accounts/{account_id}/report?month=YYYY-MM` | `api__accounts__id__report.json` |
| Semana · objetivos | `GET /api/semana/objetivos` | `api__semana__objetivos.json` |
| Semana · ações por time | `GET /api/semana/acoes` | `api__semana__acoes.json` |
| Semana · revisão da semana anterior | `GET /api/semana/revisao` | `api__semana__revisao.json` |

Sem exemplo próprio (de propósito):

- `GET /api/reports/{report_id}` — devolve um relatório **já gerado**, com a **mesma
  estrutura** de `api__accounts__id__report.json`.
- `GET /api/reports/sheet-data?account_id=` — diagnóstico de suporte (despeja a planilha
  bruta do cliente); não alimenta tela e não foi incluído por conter dado cru sensível.
- `GET /healthz` — `{"ok": true}`.

## Autenticação

- **Login**: `POST /login` com corpo `application/x-www-form-urlencoded`:
  `user=<email>&password=<senha>`. Resposta: **303 redirect** para a home do papel +
  `Set-Cookie`.
- **Sessão**: cookie **`iasession`** (httponly, `SameSite=Lax`, `Secure` quando HTTPS,
  **TTL 12h**). Valor: `user|role|expiry|hmac_sha256` assinado no servidor.
- **Chamadas seguintes**: o cookie é enviado automaticamente pelo browser — **não há
  header Authorization / Bearer**. Todo `/api/*` exige o cookie; sem ele retorna
  `401 {"detail": "não autenticado — faça login em /login"}` (os endpoints de
  `/api/semana/*` retornam `403 {"error": "não autorizado"}`).
- **Logout**: `GET /logout` (apaga o cookie).
- **Signup**: `POST /signup` (form: name, email, role, password, password2) — conta
  nasce `pendente` até o admin aprovar.
- ⚠️ **Atenção para frontend em outra origem** (ex.: Lovable): a API não tem CORS
  configurado e a sessão é cookie `SameSite=Lax` httponly — um frontend servido de outro
  domínio **não consegue autenticar hoje**. Vai precisar de CORS + ajuste de cookie
  (`SameSite=None`) ou de um endpoint de login que devolva token para header. Lacuna a
  decidir junto com os endpoints JSON que faltam (lista abaixo).

## Papéis (RBAC)

| Papel | O que enxerga |
|---|---|
| `admin` | Tudo: central `/`, todas as áreas, `/admin` (usuários/times), confirma a semana. |
| `gestor_growth` | Área Growth (`/growth`) — contas, alertas, cancelamentos, relatórios. |
| `gestor_marketing` | Área Marketing (`/marketing`). |
| `gestor_prevendas` | Área Pré-vendas (`/prevendas`). |
| `gestor_vendas` | Área Vendas (`/vendas`). |
| `gestor_operacoes` | Área Operações (`/operacoes`). |

- Áreas do produto: `growth`, `marketing`, `vendas`, `prevendas`, `financeiro`,
  `operacoes`. O admin pode liberar **áreas extras por conta** (coluna `users.areas`);
  a home pós-login é a primeira área liberada.
- Usuários bootstrap (`.env`): `adm@integracomm.com.br` / `admin` (papel admin) e
  `gestor_growth`. Demais usuários vivem na tabela `users` (bcrypt, aprovação do admin).
- `POST /api/semana/propor|confirmar|decompor` são **admin-only** (403 para os demais).

## Parâmetros de query relevantes

| Endpoint | Parâmetro | Valores / formato |
|---|---|---|
| `/api/accounts/{id}/report` | `month` | `YYYY-MM` (default: mês de referência corrente). 400 se malformado. |
| `/api/reports/summary` | `format` | `json` (default) ou `text` (payload pronto p/ Slack, text/plain). |
| `/api/semana/objetivos` | `week` | `YYYY-MM-DD` (segunda-feira; default: semana corrente — vira no domingo). |
| `/api/semana/acoes` | `team`, `week` | `team`: `growth`, `marketing`, `prevendas`, `vendas` (vazio = todos). `week` idem acima. |
| `/api/semana/revisao` | `week` | `YYYY-MM-DD` (default: semana anterior). |
| `/api/reports/sheet-data` | `account_id` | UUID da conta (obrigatório). |

POSTs de ação (corpo JSON; ver `openapi.json` para o shape): `/api/interventions`,
`/api/interventions/{iid}/result`, `/api/accounts/{id}/updates`,
`/api/alerts/{alert_id}/update`, `/api/reports/batch` (máx. 50 contas),
`/api/reports/send-slack`, `/api/accounts/{id}/outcome`, `/api/admin/times`,
`/api/users/{id}/status|areas`, `/api/operacoes/*`, `/api/semana/*`.

## Convenções de resposta

- **Datas**: ISO 8601. Timestamps com timezone (`2026-07-16T23:59:59.999999+00:00`),
  datas simples `YYYY-MM-DD`, mês de referência `YYYY-MM`. Quando a tela precisa do
  rótulo pt-BR, a API já manda campo `*_label` pronto (`"junho/2026"`).
- **Moeda**: número puro em BRL (`5800.0`) — sem símbolo e sem string; o frontend
  formata (`R$ 5.800,00`). Campos: `mrr`, `mrr_risco`, `recurring_revenue`, `total_ref`,
  `prev`/`ref`/`delta_abs` etc.
- **Percentuais**: escala 0–100 (`delta_pct: -4.8` = −4,8%). `confidence` é exceção:
  fração 0–1.
- **Nulos**: qualquer métrica pode vir `null` (ex.: `mrr`, `exec_score`, `prev` sem
  base) — exibir "—", nunca 0.
- **Campos de ressalva** (o frontend **precisa** exibir estes avisos):
  - `aviso` (string \| null) — presente nos blocos do relatório (`faturamento`,
    `atividades`, `atrasadas`, `proximas`) e em outros pontos; quando não-nulo, mostrar
    como banner de atenção.
  - `match_note` (string) — qualidade do vínculo conta ↔ planilha; exibir quando não
    contiver "exato".
  - `conf` (bool) — confiança do parse da planilha (false = layout incerto).
  - `evaluable` (bool) + `risk_band: "sem_dados"` — conta sem dados suficientes para
    score; não tratar como score baixo.
  - `confidence` (0–1) e `coverage_weeks` (int) — qualidade/base do score.
  - `sinais_do_mes` (bool, relatório) — false = sinais mais recentes fora do mês de
    referência.
  - `maturacao` (bool, `/api/semana/revisao`) — true = objetivo ainda em janela de
    maturação (~60d p/ churn); **não** é falha da semana.
  - `lag` (string, `/api/semana/acoes`) — defasagem esperada até a ação refletir na
    métrica; exibir junto da ação.
  - Textos gerados por IA vêm rotulados no próprio payload (`gerado_por`:
    `"Claude (gestor de CS sênior)"` ou `"template determinístico (…)"`) — manter o
    rótulo visível (hipótese, não causa comprovada).

## Telas que hoje são HTML server-side (sem endpoint JSON) — lacunas

Estas telas renderizam HTML no backend; para o frontend novo, cada uma vai precisar de
um endpoint JSON equivalente (a decidir):

| Tela | Rota HTML | Abas (`?view=`) / params |
|---|---|---|
| Início (central / cockpit) | `GET /` | — |
| Growth | `GET /growth` | `contas`, `alertas`, `carga`, `cancelamentos`, `playbooks`, `relatorios` (⚠️ `contas`/`alertas` têm equivalente parcial em `/api/scores` + `/api/alerts`; as demais abas não) |
| Marketing | `GET /marketing` | `visao`, `metas`, `funil`, `canais`, `origens`, `midia`, `lag`, `planejador`, `criativos`, `ciclo` |
| Pré-vendas | `GET /prevendas` | `funil`, `speed`, `ponte`, `horarios`, `sdrs` |
| Vendas | `GET /vendas` | `funil`, `ponte`, `winloss`, `ciclo`, `horarios`, `closers`, `forecast` |
| Financeiro | `GET /financeiro` | `visao` (Planejamento x Realizado), `receita` (Receita Recorrente) |
| Operações | `GET /operacoes` | — |
| Raio-X por bundle | `GET /raiox` | `b`: `TODOS` (default) ou `B1`…`B5`; `j`: janela de fechamento em dias (30/90/120, default 120) |
| Ações da Semana (página) | `GET /semana` | — (⚠️ os **dados** já existem em JSON: `/api/semana/*`) |
| All Hands (gerador de deck) | `GET /allhands` | — (+ `POST /allhands/gerar`, `POST /allhands/pptx`) |
| Admin (usuários/times) | `GET /admin` | — |
| Relatório de horários PV | `GET /prevendas/horarios/relatorio` | — |
| Relatório da conta (página) | `GET /growth/report` | `account_id` ou `report_id`, `month` — casca que consome `/api/accounts/{id}/report` (**já coberto por JSON**) |

## Resumo da cobertura

- **8 endpoints JSON de tela** documentados com resposta real anonimizada.
- **3 GET adicionais** documentados sem arquivo próprio (`/api/reports/{report_id}` =
  mesma estrutura do relatório; `/api/reports/sheet-data` = diagnóstico com dado cru,
  excluído por LGPD; `/healthz`).
- **16 endpoints POST de ação** listados (shapes no `openapi.json`).
- **13 telas HTML server-side** sinalizadas como lacuna (tabela acima) — a maior parte
  do conteúdo visual do painel (Growth/Marketing/PV/Vendas/Financeiro/Raio-X/Central)
  hoje só existe como HTML; decidir quais viram endpoints JSON antes de construir essas
  telas no frontend novo.
