"""Smoke test do LOOP DE FEEDBACK contra o Postgres real.

Pontua 2 contas sintéticas (uma saudável, uma em queda) e persiste via
GrowthAgent.persist → confirma que scores/reasons/snapshots/alerts/audit
gravam de fato. Lê APP_DATABASE_URL direto do .env (sem dep de pydantic).

Rodar:  backend/.venv/Scripts/python -m scripts.smoke_persist
"""
from __future__ import annotations

import datetime as dt
import uuid
from pathlib import Path

import psycopg

from app.agents.base import AgentContext
from app.agents.growth.agent import GrowthAgent
from app.agents.growth.scoring import SignalInput, score_account

ENV = Path(__file__).resolve().parents[2] / ".env"


def _db_url() -> str:
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if line.startswith("APP_DATABASE_URL="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("APP_DATABASE_URL não encontrado no .env")


def _series(a: float, b: float, n: int = 12):
    base = dt.date(2026, 4, 1)
    return [(base + dt.timedelta(days=i * 3), a + (b - a) * i / n) for i in range(n + 1)]


def main() -> None:
    url = _db_url()
    agent = GrowthAgent(conn_factory=lambda: psycopg.connect(url))

    scores = [
        score_account("SMOKE-001", "Cliente Smoke Saudável",
                      [SignalInput("silencio", "engagement", _series(0.3, 0.3), True)]),
        score_account("SMOKE-002", "Cliente Smoke Queda", [
            SignalInput("silencio", "engagement", _series(0.3, 0.85), True),
            SignalInput("iniciativa_cliente", "engagement", _series(20, 4), False),
            SignalInput("tom_negativo", "tone", _series(0.1, 0.6), True),
        ]),
    ]
    for s in scores:
        print(f"  {s.account_name}: score={s.score} traj={s.trajectory.value} estágio={s.stage.value} faixa={s.risk_band}")

    run_id = str(uuid.uuid4())
    ctx = AgentContext(
        window_start=dt.datetime(2026, 4, 1, tzinfo=dt.timezone.utc),
        window_end=dt.datetime(2026, 6, 26, tzinfo=dt.timezone.utc),
        run_id=run_id, audit=None,  # persist usa persistence.audit, não ctx.audit
    )
    agent.persist(ctx, scores)
    print(f"persist() OK — run_id={run_id}")

    # lê de volta para provar a gravação
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        for tbl in ("accounts", "scores", "score_reasons", "signal_snapshots", "alerts", "audit_log"):
            cur.execute(f"SELECT count(*) FROM {tbl}")
            print(f"  {tbl}: {cur.fetchone()[0]} linha(s)")
        cur.execute("SELECT account_id, risk_band, stage FROM alerts ORDER BY created_at DESC LIMIT 3")
        for row in cur.fetchall():
            print(f"  ALERTA: account={row[0]} faixa={row[1]} estágio={row[2]}")


if __name__ == "__main__":
    main()
