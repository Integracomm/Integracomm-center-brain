"""Envio de relatórios ao Slack — Incoming Webhook do grupo dos gestores.

`SLACK_WEBHOOK_URL` no .env da raiz (nunca no código). O texto enviado é o MESMO
de `GET /api/reports/summary?format=text` (mrkdwn do Slack). Envio é sempre uma
ação deliberada (botão, flag --slack ou script) — nunca automático silencioso —
e fica registrado na auditoria (action='report_slack').
"""
from __future__ import annotations

import os

import httpx


def webhook_configured() -> bool:
    return bool(os.environ.get("SLACK_WEBHOOK_URL"))


def send_text(text: str) -> None:
    """Posta `text` no canal do webhook. Levanta exceção em falha (sem retry
    silencioso: quem chama decide reportar)."""
    url = os.environ.get("SLACK_WEBHOOK_URL", "")
    if not url:
        raise RuntimeError("SLACK_WEBHOOK_URL não configurada no .env da raiz")
    r = httpx.post(url, json={"text": text}, timeout=30.0)
    r.raise_for_status()
