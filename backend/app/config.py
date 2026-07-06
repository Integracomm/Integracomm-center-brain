"""Configuração por variáveis de ambiente — segredos nunca no código.

Lê do ambiente (ou de um .env local, fora do git). Cada fonte usa uma
credencial dedicada, somente leitura e de permissão mínima.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = Field("staging", alias="ENVIRONMENT")

    # Claude — cérebro dos agentes
    anthropic_api_key: str | None = Field(None, alias="ANTHROPIC_API_KEY")
    # Planos de ação via LLM (gestor de CS sênior). DESLIGADO por padrão: sem
    # créditos de API, cada chamada falha e só adiciona latência ao relatório.
    # Ligar (GROWTH_LLM_PLANS=1) quando os créditos estiverem disponíveis.
    growth_llm_plans: bool = Field(False, alias="GROWTH_LLM_PLANS")

    # ClickUp (RO)
    clickup_api_token: str | None = Field(None, alias="CLICKUP_API_TOKEN")
    clickup_workspace_id: str | None = Field(None, alias="CLICKUP_WORKSPACE_ID")
    clickup_list_funil_cs: str | None = Field(None, alias="CLICKUP_LIST_FUNIL_CS")
    clickup_list_assessoria: str | None = Field(None, alias="CLICKUP_LIST_ASSESSORIA")
    clickup_list_clientes_ativos: str | None = Field(None, alias="CLICKUP_LIST_CLIENTES_ATIVOS")

    # WhatsApp Connector (Lovable Cloud) — edge function read-only `growth-agent-read`
    # URL já inclui /growth-agent-read; o reader concatena /<endpoint>.
    whatsapp_read_api_url: str | None = Field(None, alias="WHATSAPP_READ_API_URL")
    whatsapp_read_api_key: str | None = Field(None, alias="WHATSAPP_READ_API_KEY")

    # ML Connect — endpoint read-only já existente (plan_name, gestor, faturamento)
    ml_connect_url: str | None = Field(None, alias="ML_CONNECT_URL")
    ml_connect_token: str | None = Field(None, alias="ML_CONNECT_TOKEN")

    # Google Sheets — cancelamentos 2026 (service account viewer)
    google_sa_json_path: str | None = Field(None, alias="GOOGLE_SA_JSON_PATH")
    saidas_default_spreadsheet_id: str | None = Field(None, alias="SAIDAS_DEFAULT_SPREADSHEET_ID")
    saidas_2026_spreadsheet_id: str | None = Field(None, alias="SAIDAS_2026_SPREADSHEET_ID")

    # Postgres próprio da ferramenta (estado/score/alerta/auditoria)
    app_database_url: str | None = Field(None, alias="APP_DATABASE_URL")


@lru_cache
def get_settings() -> Settings:
    return Settings()
