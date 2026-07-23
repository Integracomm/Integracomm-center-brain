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


def admin_webhook_configured() -> bool:
    return bool(os.environ.get("SLACK_WEBHOOK_ADMIN_URL"))


def send_admin_text(text: str) -> None:
    """Posta num canal SÓ DO ADMIN (`SLACK_WEBHOOK_ADMIN_URL`, opcional).

    Existe porque o webhook padrão vai para o grupo dos GESTORES, e há aviso que
    não é para eles — o pedido de redefinição de senha, por exemplo (Otávio
    23/07: "ali todos os gestores têm acesso e não seria útil para eles").
    Sem a variável configurada, não envia nada: o aviso vive no painel, que é
    onde o admin resolve. NUNCA cai no webhook do grupo."""
    url = os.environ.get("SLACK_WEBHOOK_ADMIN_URL", "")
    if not url:
        return
    httpx.post(url, json={"text": text}, timeout=30.0).raise_for_status()


def send_text(text: str) -> None:
    """Posta `text` no canal do webhook. Levanta exceção em falha (sem retry
    silencioso: quem chama decide reportar)."""
    url = os.environ.get("SLACK_WEBHOOK_URL", "")
    if not url:
        raise RuntimeError("SLACK_WEBHOOK_URL não configurada no .env da raiz")
    r = httpx.post(url, json={"text": text}, timeout=30.0)
    r.raise_for_status()
