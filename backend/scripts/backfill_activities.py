"""Backfill ÚNICO de sales_activities — SÓ rodar em janela aprovada pelo Otávio.

Regra dura (Otávio, 2x em 20/07/2026): o orçamento de requests do Pipedrive é
COMPARTILHADO com aplicações de produção que leem em tempo real e não podem
parar. Por isso: sequencial, pausa de 1s entre páginas, teto de páginas e
execução em madrugada. O incremental diário (sync_marketing) cobre 10 dias com
teto de 40 páginas — este script é só para completar o histórico uma vez.

Uso (na pasta backend): python -m scripts.backfill_activities [--since 2026-01-01]
"""
from __future__ import annotations

import argparse
import datetime as dt
import time

from app.auth import _load_env
from app.sources import pipedrive_deals as PD


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-01-01")
    ap.add_argument("--max-pages", type=int, default=300)
    ap.add_argument("--pausa", type=float, default=1.0)
    ap.add_argument("--tentativas", type=int, default=3)
    a = ap.parse_args()
    _load_env()
    import psycopg

    from app.api import _conn
    print(f"[backfill_atividades] inicio {dt.datetime.now():%Y-%m-%d %H:%M:%S} "
          f"(since={a.since}, teto={a.max_pages}p, pausa={a.pausa}s)")
    for t in range(1, a.tentativas + 1):
        try:
            with _conn() as c:
                n = PD.sync_activities(c, since=dt.date.fromisoformat(a.since),
                                       max_pages=a.max_pages, pausa=a.pausa)
            print(f"[backfill_atividades] ok na tentativa {t}: {n} registros")
            break
        except psycopg.OperationalError:
            # conexão ao RDS caiu no meio (aconteceu 20/07) — reconectar; os
            # inserts já feitos persistem (autocommit) e o upsert é idempotente
            print(f"[backfill_atividades] conexao caiu (tentativa {t}) — nova conexao em 15s")
            time.sleep(15)
    else:
        print("[backfill_atividades] NAO completou nas tentativas — cobertura parcial")
    with _conn() as c, c.cursor() as cur:
        cur.execute("""SELECT date_trunc('month', add_at)::date, count(*),
                              count(*) FILTER (WHERE tipo='call')
                         FROM sales_activities GROUP BY 1 ORDER BY 1""")
        for m, n, calls in cur.fetchall():
            print(f"  {m} total={n} calls={calls}")
    print(f"[backfill_atividades] fim {dt.datetime.now():%H:%M:%S}")


if __name__ == "__main__":
    main()
