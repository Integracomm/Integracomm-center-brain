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


def _ja_enviou_hoje(conn) -> bool:
    """True se já houve um envio do relatório diário HOJE (fuso -03). Guarda de
    idempotência: a rodada das 06h (run_portfolio --slack) e o backup das 10h15
    compartilham este cheque — quem chega primeiro envia, o outro fica quieto."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM audit_log WHERE action='report_slack' "
            "AND (at AT TIME ZONE 'America/Sao_Paulo')::date "
            "  = (now() AT TIME ZONE 'America/Sao_Paulo')::date LIMIT 1")
        return cur.fetchone() is not None


def enviar_relatorio_diario(*, actor: str, force: bool = False) -> str:
    """Envia o relatório de Growth ao Slack UMA vez por dia, a partir do estado
    atual do banco. Desacoplado da rodada (24/07): a rodada das 06h pode travar
    ou estourar o teto de 4h e nunca chegar ao envio — este caminho garante que
    o relatório saia mesmo assim, com o dado disponível e um aviso de idade.

    - idempotente por dia (`_ja_enviou_hoje`), a menos que force=True;
    - se os scores não são de hoje (rodada não pontuou), prepende um aviso —
      silêncio sobre dado velho é pior que o dado velho.
    Retorna um rótulo do que aconteceu (para o log do cron)."""
    # imports tardios: api.py importa este módulo, então nada de topo circular
    from .api import (_conn, _latest_scores, _open_alerts, _report_from,
                      _report_text)

    with _conn() as c:
        if not force and _ja_enviou_hoje(c):
            return "ja-enviado-hoje"
        scores = _latest_scores(c)
        text = _report_text(_report_from(scores, _open_alerts(c)))

        # idade do dado: a rodada trava e o painel fica congelado sem ninguém ver
        import datetime as dt
        computados = [s["computed_at"] for s in scores if s.get("computed_at")]
        aviso = ""
        if computados:
            with c.cursor() as cur:
                cur.execute("SELECT (now() AT TIME ZONE 'America/Sao_Paulo')::date "
                            "- (max(computed_at) AT TIME ZONE 'America/Sao_Paulo')::date "
                            "FROM scores")
                dias = cur.fetchone()[0] or 0
            if dias >= 1:
                aviso = (f":warning: *Atenção: dado de {dias} dia(s) atrás* — a rodada de "
                         "pontuação não fechou desde então; os números abaixo são o último "
                         "estado válido, não o de hoje.\n\n")
        send_text(aviso + text)
        with c.cursor() as cur:
            cur.execute("INSERT INTO audit_log (actor, action, scope) VALUES (%s,%s,%s)",
                        (actor, "report_slack", "slack:webhook"))
    return "enviado-com-aviso" if aviso else "enviado"
