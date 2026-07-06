"""Metas mensais da planilha financeira (Planejamento_Receita_2026_V3) → mkt_goals.

Estrutura (inspecionada 2026-07-06): MATRIZ — linha 1 = meses ("dez.-25" ..
"dez.-26"), demais linhas = indicadores. Extraímos por prefixo do rótulo:
  "B1..B5 - Meta: Booking [Qtde]/[R$]" e "Ticket médio", "Planos Antigos - ..."
  e o total "Meta Bookings [R$]". Valores em R$ brasileiro ("R$ 1.234,56").
Releitura semanal basta (a planilha muda pouco).
"""
from __future__ import annotations

import csv
import io
import re
from typing import Any

import httpx

SHEET_ID = "1V_lVveaEYrr_stZONWKY3beHfJ_JwQ0I"
GID = "1955381933"
_MES = {"jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
        "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12}


def _num(v: str) -> float | None:
    x = re.sub(r"[^\d,\-]", "", v or "")
    if not x or x in ("-", ","):
        return None
    try:
        return float(x.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def fetch_rows() -> list[list[str]]:
    r = httpx.get(f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq",
                  params={"tqx": "out:csv", "gid": GID}, timeout=60, follow_redirects=True)
    r.raise_for_status()
    return list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))


def sync_goals(conn: Any) -> int:
    rows = fetch_rows()
    # colunas de mês: "dez.-25" -> date(2025,12,1)
    meses: list[tuple[int, str]] = []
    for j, c in enumerate(rows[0]):
        m = re.match(r"([a-zç]{3})\.?-?(\d{2})$", (c or "").strip().lower())
        if m and m.group(1)[:3] in _MES:
            meses.append((j, f"20{m.group(2)}-{_MES[m.group(1)[:3]]:02d}-01"))
    plano_re = re.compile(r"^(B[1-5]|Planos Antigos)\s*-\s*(Meta: Booking \[(Qtde|R\$)\]|Ticket médio Booking)")
    dados: dict[tuple[str, str], dict] = {}
    for r in rows[1:]:
        rotulo = (r[0] or "").strip()
        m = plano_re.match(rotulo)
        alvo = None
        if m:
            plano = "antigos" if m.group(1) == "Planos Antigos" else m.group(1)
            alvo = ("meta_qtde" if "[Qtde]" in rotulo else
                    "meta_valor" if "Meta: Booking [R$]" in rotulo else "ticket_medio")
        elif rotulo == "Meta Bookings [R$]":
            plano, alvo = "total", "meta_valor"
        if not alvo:
            continue
        for j, mes in meses:
            v = _num(r[j] if j < len(r) else "")
            if v is not None:
                dados.setdefault((mes, plano), {})[alvo] = v
    n = 0
    with conn.cursor() as cur:
        for (mes, plano), vals in dados.items():
            cur.execute(
                """INSERT INTO mkt_goals (mes, plano, meta_qtde, meta_valor, ticket_medio, updated_at)
                   VALUES (%s,%s,%s,%s,%s,now())
                   ON CONFLICT (mes, plano) DO UPDATE SET
                        meta_qtde=COALESCE(EXCLUDED.meta_qtde, mkt_goals.meta_qtde),
                        meta_valor=COALESCE(EXCLUDED.meta_valor, mkt_goals.meta_valor),
                        ticket_medio=COALESCE(EXCLUDED.ticket_medio, mkt_goals.ticket_medio),
                        updated_at=now()""",
                (mes, plano, vals.get("meta_qtde"), vals.get("meta_valor"), vals.get("ticket_medio")))
            n += 1
    return n
