"""AuditSink concreto — grava a trilha de auditoria no Postgres próprio.

Fecha o inegociável de auditoria ponta-a-ponta: TODA leitura de fonte sensível
(via WhatsAppReader) e todo score/alerta vira registro em `audit_log` (quem, o
quê, quando, escopo). Usa conexão própria em AUTOCOMMIT — a auditoria não pode
depender do commit do pipeline: uma leitura registrada fica registrada mesmo se
a rodada falhar depois.
"""
from __future__ import annotations

from typing import Any

from .agents.base import AccountScore, AuditSink


class DbAuditSink(AuditSink):
    def __init__(self, conn_factory: Any, actor: str = "agent:growth") -> None:
        self._conn = conn_factory()
        self._conn.autocommit = True  # trilha independe do commit do pipeline
        self._actor = actor

    def _log(self, action: str, *, source: str | None = None, scope: str | None = None,
             account_id: str | None = None, run_id: str | None = None) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO audit_log (actor, action, source, scope, account_id, run_id) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (self._actor, action, source, scope, account_id, run_id),
            )

    def record_read(self, *, source: str, scope: str, run_id: str | None) -> None:
        self._log("read", source=source, scope=scope, run_id=run_id)

    def record_score(self, *, score: AccountScore, run_id: str | None) -> None:
        self._log("score", scope=score.account_name, run_id=run_id)

    def record_alert(self, *, score: AccountScore, run_id: str | None) -> None:
        self._log("alert", scope=f"{score.account_name}:{score.risk_band}", run_id=run_id)

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass
