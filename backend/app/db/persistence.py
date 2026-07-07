"""Loop de feedback — grava sinais (série), scores, alertas, desfechos e auditoria.

Isto é o que torna o modelo preditivo de fato: a cada execução guardamos os
sinais de cada conta (signal_snapshots) e, quando conhecido, o desfecho
(outcomes: renovou/cancelou). Com sinal × desfecho acumulados, os pesos do
modelo passam de heurísticos a calibrados.

psycopg3. Funções recebem uma conexão aberta; a casca gerencia o ciclo.
LGPD: aqui só entram DERIVADOS (métricas, score, motivo). Nada de conteúdo
bruto de WhatsApp.
"""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from ..agents.base import AccountScore


def ensure_account(conn: Any, *, id_interno: str | None, name: str, name_norm: str,
                   plan_category: str | None, is_legacy: bool,
                   recurring_revenue: float | None, manager_name: str | None = None,
                   whatsapp_group_id: str | None = None) -> str:
    """Upsert da conta canônica; retorna o UUID interno."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO accounts (id_interno, name, name_norm, plan_category, is_legacy,
                                  recurring_revenue, manager_name, whatsapp_group_id, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s, now())
            ON CONFLICT (id_interno) DO UPDATE SET
                name=EXCLUDED.name, name_norm=EXCLUDED.name_norm,
                plan_category=EXCLUDED.plan_category, is_legacy=EXCLUDED.is_legacy,
                recurring_revenue=EXCLUDED.recurring_revenue,
                manager_name=EXCLUDED.manager_name,
                whatsapp_group_id=EXCLUDED.whatsapp_group_id, updated_at=now()
            RETURNING id
            """,
            (id_interno, name, name_norm, plan_category, is_legacy,
             recurring_revenue, manager_name, whatsapp_group_id),
        )
        return cur.fetchone()[0]


def record_signal_snapshots(conn: Any, *, account_id: str, run_id: str,
                            captured_at: dt.datetime, signals: list[dict]) -> None:
    """Grava a foto de hoje dos sinais (série temporal por conta/sinal/dia)."""
    with conn.cursor() as cur:
        for s in signals:
            cur.execute(
                """
                INSERT INTO signal_snapshots
                    (account_id, captured_at, source, signal_key, value_num, value_text, is_leading, run_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (account_id, signal_key, captured_at) DO NOTHING
                """,
                (account_id, captured_at, s["source"], s["signal_key"],
                 s.get("value_num"), s.get("value_text"), s.get("leading", True), run_id),
            )


def record_score(conn: Any, *, account_id: str, run_id: str, score: AccountScore) -> str:
    """Grava o score + trajetória + motivos. Retorna o UUID do score."""
    sid = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO scores (id, account_id, run_id, score, trajectory, velocity, stage,
                                risk_band, lead_time_days, confidence, coverage_weeks, evaluable,
                                recommendation, computed_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (sid, account_id, run_id, score.score, score.trajectory.value, score.velocity,
             score.stage.value, score.risk_band, score.lead_time_days, score.confidence,
             score.coverage_weeks, score.evaluable,
             score.recommendation, score.computed_at),
        )
        for r in score.reasons:
            cur.execute(
                "INSERT INTO score_reasons (score_id, source, text, is_leading, weight) VALUES (%s,%s,%s,%s,%s)",
                (sid, r.source, r.text, r.leading, r.weight),
            )
    return sid


def record_alert(conn: Any, *, account_id: str, score_id: str, score: AccountScore) -> None:
    """Mantém NO MÁXIMO um alerta aberto por conta (humano no loop, sem ruído).

    Severidade (critico|alto|atencao) vem de scoring.alert_severity; None = sem alerta.
    - Já existe alerta aberto → ATUALIZA severidade/estágio (created_at preserva a
      idade do caso) em vez de abrir duplicado — antes cada rodada abria um novo
      e o painel acumulava ~2,8 alertas/conta, enterrando o que era prioridade.
    - Conta AVALIÁVEL que normalizou (severity None) → fecha os abertos sozinho
      com nota; não-avaliável não fecha nada (sem dado ≠ recuperada).
    """
    from ..agents.growth.scoring import alert_severity

    severity = alert_severity(score)
    with conn.cursor() as cur:
        if severity is None:
            if score.evaluable:
                cur.execute(
                    """UPDATE alerts SET status='resolvido',
                              notes = COALESCE(notes || ' · ', '') ||
                                      'auto: risco normalizado em ' || to_char(now(), 'DD-MM-YYYY')
                        WHERE account_id=%s AND status='aberto'""",
                    (account_id,),
                )
            return
        cur.execute(
            """SELECT id FROM alerts WHERE account_id=%s AND status='aberto'
               ORDER BY created_at DESC LIMIT 1""",
            (account_id,),
        )
        row = cur.fetchone()
        if row:
            cur.execute(
                """UPDATE alerts SET severity=%s, risk_band=%s, stage=%s, score_id=%s
                    WHERE id=%s""",
                (severity, score.risk_band, score.stage.value, score_id, row[0]),
            )
        else:
            cur.execute(
                """INSERT INTO alerts (account_id, score_id, risk_band, stage, severity)
                   VALUES (%s,%s,%s,%s,%s)""",
                (account_id, score_id, score.risk_band, score.stage.value, severity),
            )


def record_outcome(conn: Any, *, account_id: str, outcome: str, outcome_date: dt.date | None,
                   cancellation_request_date: dt.date | None, source: str,
                   is_transition_churn: bool) -> None:
    """Fecha o loop: renovou/cancelou — alimenta a recalibração dos pesos."""
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO outcomes (account_id, outcome, outcome_date, cancellation_request_date,
                                     source, is_transition_churn)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            (account_id, outcome, outcome_date, cancellation_request_date, source, is_transition_churn),
        )


def record_intervention(conn: Any, *, account_id: str, action_text: str,
                        driver: str | None = None, stage: str | None = None,
                        taken_by: str | None = None, alert_id: str | None = None) -> str:
    """Registra a AÇÃO tomada com uma conta (base do aprendizado de práticas)."""
    iid = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO interventions (id, account_id, alert_id, driver, stage, action_text, taken_by)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (iid, account_id, alert_id, driver, stage, action_text, taken_by),
        )
    return iid


def set_intervention_result(conn: Any, *, intervention_id: str, result: str,
                            notes: str | None = None) -> None:
    """Fecha a intervenção: retido|cancelou|sem_efeito. 'retido' vira boa prática."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE interventions SET result=%s, result_at=now(), notes=COALESCE(%s,notes) WHERE id=%s",
            (result, notes, intervention_id),
        )


def top_practices(conn: Any) -> dict[str, tuple[str, int]]:
    """Boas práticas por DOR: a ação que mais RETEVE para cada driver.
    {driver: (action_text, n_retencoes)} — citada na diretriz de casos futuros."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT driver, action_text, count(*) AS n FROM interventions
                WHERE result='retido' AND driver IS NOT NULL
                GROUP BY driver, action_text ORDER BY n DESC, max(result_at) DESC"""
        )
        out: dict[str, tuple[str, int]] = {}
        for driver, action, n in cur.fetchall():
            out.setdefault(driver, (action, n))
        return out


def audit(conn: Any, *, actor: str, action: str, source: str | None = None,
          scope: str | None = None, account_id: str | None = None, run_id: str | None = None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO audit_log (actor, action, source, scope, account_id, run_id)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            (actor, action, source, scope, account_id, run_id),
        )


def start_run(conn: Any, agent_key: str, window_start: dt.datetime, window_end: dt.datetime) -> str:
    rid = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO agent_runs (id, agent_key, window_start, window_end) VALUES (%s,%s,%s,%s)",
            (rid, agent_key, window_start, window_end),
        )
    return rid


def finish_run(conn: Any, run_id: str, status: str = "ok") -> None:
    with conn.cursor() as cur:
        cur.execute("UPDATE agent_runs SET finished_at=now(), status=%s WHERE id=%s", (status, run_id))
