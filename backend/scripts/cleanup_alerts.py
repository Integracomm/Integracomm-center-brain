"""Saneamento ÚNICO da fila de alertas (pós-correção do record_alert).

    python -m scripts.cleanup_alerts --dry   # mostra o que faria
    python -m scripts.cleanup_alerts         # aplica

Duas passadas, espelhando as regras novas do record_alert (dedup + auto-resolve):
  1. DEDUP — mantém só o alerta aberto MAIS RECENTE de cada conta; os demais
     viram 'resolvido' com nota "auto: duplicado consolidado".
  2. NORMALIZADOS — conta AVALIÁVEL cujo último score não justifica alerta
     (alert_severity = None) tem o aberto fechado com "auto: risco normalizado".
Nada é apagado: status+nota preservam a trilha de auditoria.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[2]


def load_env() -> None:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


# Mesma lógica de scoring.alert_severity, sobre as COLUNAS do último score.
_SEV_SQL = """
CASE
  WHEN NOT u.evaluable THEN NULL
  WHEN u.stage = 'intencao_de_saida' OR u.risk_band = 'critico' THEN 'critico'
  WHEN u.stage = 'insatisfacao_ativa' OR u.risk_band = 'alto'
       OR (u.risk_band = 'medio' AND u.trajectory = 'caindo') THEN 'alto'
  WHEN u.risk_band = 'baixo' AND u.trajectory = 'caindo' THEN 'atencao'
  ELSE NULL
END
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="só mostra, não altera")
    args = ap.parse_args()
    load_env()
    conn = psycopg.connect(os.environ["APP_DATABASE_URL"])
    conn.autocommit = not args.dry
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM alerts WHERE status='aberto'")
        antes = cur.fetchone()[0]

        # 1) dedup: fecha todo aberto que não é o mais recente da conta
        cur.execute("""
            WITH keep AS (SELECT DISTINCT ON (account_id) id FROM alerts
                          WHERE status='aberto' ORDER BY account_id, created_at DESC)
            UPDATE alerts SET status='resolvido',
                   notes = COALESCE(notes || ' · ', '') || 'auto: duplicado consolidado'
             WHERE status='aberto' AND id NOT IN (SELECT id FROM keep)""")
        dedup = cur.rowcount

        # 2) contas avaliáveis normalizadas: fecha o aberto restante
        cur.execute(f"""
            WITH ult AS (SELECT DISTINCT ON (account_id) account_id, risk_band, stage,
                                trajectory, evaluable
                           FROM scores ORDER BY account_id, computed_at DESC)
            UPDATE alerts al SET status='resolvido',
                   notes = COALESCE(al.notes || ' · ', '') || 'auto: risco normalizado'
              FROM ult u
             WHERE u.account_id = al.account_id AND al.status='aberto'
               AND u.evaluable AND ({_SEV_SQL}) IS NULL""")
        norm = cur.rowcount

        # 3) severidade do aberto restante = a do último score (fila fiel ao estado atual)
        cur.execute(f"""
            WITH ult AS (SELECT DISTINCT ON (account_id) account_id, risk_band, stage,
                                trajectory, evaluable
                           FROM scores ORDER BY account_id, computed_at DESC)
            UPDATE alerts al SET severity = ({_SEV_SQL}), risk_band = u.risk_band, stage = u.stage
              FROM ult u
             WHERE u.account_id = al.account_id AND al.status='aberto'
               AND ({_SEV_SQL}) IS NOT NULL AND al.severity <> ({_SEV_SQL})""")
        resev = cur.rowcount

        cur.execute("SELECT count(*) FROM alerts WHERE status='aberto'")
        depois = cur.fetchone()[0]
        cur.execute("""SELECT severity, count(*) FROM alerts WHERE status='aberto'
                       GROUP BY 1 ORDER BY 1""")
        dist = cur.fetchall()
    print(f"abertos antes: {antes}")
    print(f"  fechados por dedup:          {dedup}")
    print(f"  fechados por normalização:   {norm}")
    print(f"  severidade reclassificada:   {resev}")
    print(f"abertos depois: {depois}  {dict(dist)}")
    if args.dry:
        conn.rollback()
        print("(dry: nada foi gravado)")
    conn.close()


if __name__ == "__main__":
    main()
