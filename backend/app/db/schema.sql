-- =====================================================================
-- Postgres PRÓPRIO da ferramenta (staging) — guarda apenas DERIVADOS e
-- DECISÕES. Os dados-fonte permanecem nos sistemas de origem.
--
-- LGPD: NÃO armazenamos conteúdo bruto de mensagens de WhatsApp aqui.
-- Guardamos sinais derivados (métricas, tendência) e, no máximo, o resumo
-- qualitativo gerado pelo Claude — acesso restrito por papel (RBAC).
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ---------------------------------------------------------------------
-- Registro canônico de contas (cache/dedup das fontes; chave de join)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS accounts (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    id_interno         TEXT UNIQUE,                 -- "ID: XXXX" (join cross-fonte)
    name               TEXT NOT NULL,
    name_norm          TEXT NOT NULL,               -- normalizado p/ match (ver normalizeForMatch)
    plan_category      TEXT,                        -- B1-START..B5-ELITE | Planos Antigos
    is_legacy          BOOLEAN NOT NULL DEFAULT FALSE, -- legado em sunset -> ação = migração
    recurring_revenue  NUMERIC,                     -- pondera contas de maior receita
    manager_name       TEXT,                        -- gestor de contas
    whatsapp_group_id  TEXT,                        -- mapeamento p/ o WhatsApp Connector
    clickup_task_id    TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_accounts_name_norm ON accounts(name_norm);

-- ---------------------------------------------------------------------
-- Série temporal de sinais (o coração do loop prospectivo).
-- Um registro por conta/sinal/dia — base p/ baseline e trajetória.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS signal_snapshots (
    id            BIGSERIAL PRIMARY KEY,
    account_id    UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    captured_at   TIMESTAMPTZ NOT NULL,
    source        TEXT NOT NULL,                    -- whatsapp|clickup|pipedrive|omie|ml_connect
    signal_key    TEXT NOT NULL,                    -- ex.: exec_score, resp_latency, tone, msg_freq
    value_num     NUMERIC,
    value_text    TEXT,                             -- ex.: resumo qualitativo (Claude)
    is_leading    BOOLEAN NOT NULL DEFAULT TRUE,    -- líder (antecede) vs tardio (confirma); 'leading' é reservado no SQL
    run_id        UUID,
    UNIQUE (account_id, signal_key, captured_at)
);
CREATE INDEX IF NOT EXISTS idx_signal_acct_key_time
    ON signal_snapshots(account_id, signal_key, captured_at DESC);

-- ---------------------------------------------------------------------
-- Scores por execução (foto) + trajetória derivada
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS scores (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id      UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    run_id          UUID NOT NULL,
    score           NUMERIC NOT NULL,               -- 0-100
    trajectory      TEXT NOT NULL,                  -- subindo|estavel|caindo|desconhecida
    velocity        NUMERIC,                        -- variação/dia (negativa = piorando)
    stage           TEXT NOT NULL,                  -- estágio de declínio
    risk_band       TEXT NOT NULL,                  -- baixo|medio|alto|critico
    lead_time_days  INTEGER,                        -- antecedência estimada
    confidence      NUMERIC,                        -- 0-1
    coverage_weeks  INTEGER NOT NULL DEFAULT 0,     -- semanas de sinal líder (cobertura)
    evaluable       BOOLEAN NOT NULL DEFAULT TRUE,  -- FALSE = sem dados -> revisar manual
    recommendation  TEXT,                           -- texto p/ Growth — NÃO executa nada
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_scores_acct_time ON scores(account_id, computed_at DESC);
-- migração idempotente p/ bancos já criados antes do gate de cobertura
ALTER TABLE scores ADD COLUMN IF NOT EXISTS coverage_weeks INTEGER NOT NULL DEFAULT 0;
ALTER TABLE scores ADD COLUMN IF NOT EXISTS evaluable BOOLEAN NOT NULL DEFAULT TRUE;

CREATE TABLE IF NOT EXISTS score_reasons (
    id          BIGSERIAL PRIMARY KEY,
    score_id    UUID NOT NULL REFERENCES scores(id) ON DELETE CASCADE,
    source      TEXT NOT NULL,
    text        TEXT NOT NULL,
    is_leading  BOOLEAN NOT NULL,
    weight      NUMERIC NOT NULL DEFAULT 0
);

-- ---------------------------------------------------------------------
-- Alertas (gerados quando a TENDÊNCIA cruza p/ risco) — humano no loop
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alerts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id      UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    score_id        UUID REFERENCES scores(id) ON DELETE SET NULL,
    risk_band       TEXT NOT NULL,
    stage           TEXT NOT NULL,
    severity        TEXT NOT NULL DEFAULT 'alto',   -- critico|alto|atencao (ver alert_severity)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    status          TEXT NOT NULL DEFAULT 'aberto', -- aberto|reconhecido|resolvido
    acknowledged_by TEXT,
    acknowledged_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status, created_at DESC);

-- ---------------------------------------------------------------------
-- Desfechos (renovou/cancelou) — fecha o loop de feedback p/ calibrar
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS outcomes (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id               UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    outcome                  TEXT NOT NULL,          -- renovou|cancelou
    outcome_date             DATE,                   -- melhor data disponível
    cancellation_request_date DATE,                  -- Solicitação de Cancelamento (mais próxima da decisão)
    source                   TEXT NOT NULL,          -- clickup_cscs|funil_cs|sheets_2026
    is_transition_churn      BOOLEAN NOT NULL DEFAULT FALSE, -- legado/transição -> estudar à parte
    recorded_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_outcomes_account ON outcomes(account_id);

-- ---------------------------------------------------------------------
-- Intervenções — o que o time FEZ com cada conta e o que resultou.
-- É a base do aprendizado de BOAS PRÁTICAS: ação + dor no momento +
-- desfecho (retido/cancelou). Ações com result='retido' viram referência
-- citada na diretriz de casos futuros com a mesma dor.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS interventions (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id   UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    alert_id     UUID REFERENCES alerts(id) ON DELETE SET NULL,
    driver       TEXT,                             -- dor dominante no momento (silencio|tom_negativo|...)
    stage        TEXT,                             -- estágio no momento da ação
    action_text  TEXT NOT NULL,                    -- o que foi feito (livre, curto)
    taken_by     TEXT,                             -- gestor que agiu
    taken_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    result       TEXT NOT NULL DEFAULT 'pendente', -- pendente|retido|cancelou|sem_efeito
    result_at    TIMESTAMPTZ,
    notes        TEXT
);
CREATE INDEX IF NOT EXISTS idx_interventions_driver ON interventions(driver, result);

-- ---------------------------------------------------------------------
-- Relatórios mensais de assessoria por cliente (gerados sob demanda no
-- painel; payload completo em JSONB). Criada de forma idempotente também
-- em runtime (app.reports.ensure_reports_table).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id TEXT NOT NULL,
    account_name TEXT NOT NULL,
    reference_month DATE NOT NULL,  -- primeiro dia do mês de referência
    generated_at TIMESTAMPTZ DEFAULT NOW(),
    generated_by TEXT,              -- usuário que gerou
    status TEXT DEFAULT 'generated',
    data JSONB NOT NULL,            -- relatório completo em JSON
    notes TEXT                      -- observações manuais adicionadas pelo GC
);
CREATE INDEX IF NOT EXISTS idx_reports_account ON reports(account_id, reference_month DESC);

-- ---------------------------------------------------------------------
-- Auditoria — quem/o quê/quando (trilha real e consultável)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agent_runs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_key     TEXT NOT NULL,
    window_start  TIMESTAMPTZ,
    window_end    TIMESTAMPTZ,
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at   TIMESTAMPTZ,
    status        TEXT NOT NULL DEFAULT 'rodando'    -- rodando|ok|erro
);

CREATE TABLE IF NOT EXISTS audit_log (
    id         BIGSERIAL PRIMARY KEY,
    at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor      TEXT NOT NULL,                        -- usuário ou 'agent:<key>'
    action     TEXT NOT NULL,                        -- read|score|alert|login
    source     TEXT,                                 -- fonte lida (quando read)
    scope      TEXT,                                 -- janela/tabela/escopo lido
    account_id UUID REFERENCES accounts(id) ON DELETE SET NULL,
    run_id     UUID
);
CREATE INDEX IF NOT EXISTS idx_audit_at ON audit_log(at DESC);
