"""Tabelas da área de Marketing (prefixo mkt_) — cache local das fontes.

Criadas de forma idempotente em runtime (ensure_mkt_tables), mesmo padrão das
demais tabelas do projeto. O cache existe para NÃO bater nas APIs a cada
render: os coletores escrevem aqui (upsert) e o painel só lê o Postgres.
"""
from __future__ import annotations

from typing import Any

_DDL = """
-- campanhas Meta/Google (cache)
CREATE TABLE IF NOT EXISTS mkt_campaigns (
    id          TEXT PRIMARY KEY,            -- id na plataforma
    canal       TEXT NOT NULL,               -- meta|google
    nome        TEXT NOT NULL,
    objetivo    TEXT,
    status      TEXT,
    data_inicio DATE,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- métricas diárias por campanha/adset/criativo (grão = dia × ad)
CREATE TABLE IF NOT EXISTS mkt_insights_daily (
    canal        TEXT NOT NULL,
    date         DATE NOT NULL,
    campaign_id  TEXT NOT NULL,
    adset_id     TEXT,
    adset_name   TEXT,
    ad_id        TEXT NOT NULL DEFAULT '',
    ad_name      TEXT,
    spend        NUMERIC NOT NULL DEFAULT 0,
    impressions  BIGINT  NOT NULL DEFAULT 0,
    clicks       BIGINT  NOT NULL DEFAULT 0,
    leads        INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (canal, date, campaign_id, ad_id)
);
CREATE INDEX IF NOT EXISTS idx_mkt_ins_campaign ON mkt_insights_daily(campaign_id, date);

-- deals do Pipedrive com atribuição resolvida (grão = deal)
CREATE TABLE IF NOT EXISTS mkt_deals_attribution (
    deal_id      BIGINT PRIMARY KEY,
    add_time     TIMESTAMPTZ NOT NULL,        -- criação do lead
    won_time     TIMESTAMPTZ,
    lost_time    TIMESTAMPTZ,
    status       TEXT,                        -- open|won|lost
    valor        NUMERIC,
    origem       TEXT,                        -- utm_source normalizado (lower)
    utm_medium   TEXT,
    utm_campaign TEXT,
    utm_term     TEXT,                        -- público/adset
    utm_content  TEXT,                        -- criativo
    produto      TEXT,                        -- plano vendido (label do enum)
    stage_id     INTEGER,
    oport_time   TIMESTAMPTZ,                 -- 1ª mudança p/ etapa de oportunidade
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_mkt_deals_origem ON mkt_deals_attribution(origem, add_time);
CREATE INDEX IF NOT EXISTS idx_mkt_deals_camp ON mkt_deals_attribution(utm_campaign);

-- lag agregado campanha->resultado (recalculado semanalmente)
CREATE TABLE IF NOT EXISTS mkt_campaign_lag_stats (
    canal            TEXT NOT NULL,
    tipo             TEXT NOT NULL DEFAULT 'todas',  -- agregação por tipo de campanha
    marco            TEXT NOT NULL,   -- primeiro_lead|primeira_oport|primeiro_booking|p50_leads
    n_campanhas      INTEGER NOT NULL,
    mediana_dias     NUMERIC,
    p25_dias         NUMERIC,
    p75_dias         NUMERIC,
    computed_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (canal, tipo, marco)
);

-- metas mensais da planilha financeira
CREATE TABLE IF NOT EXISTS mkt_goals (
    mes          DATE NOT NULL,               -- 1º dia do mês
    plano        TEXT NOT NULL,               -- B1..B5|antigos|total
    meta_qtde    INTEGER,
    meta_valor   NUMERIC,
    ticket_medio NUMERIC,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (mes, plano)
);
"""


def ensure_mkt_tables(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute(_DDL)
