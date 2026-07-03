"""Varredura das planilhas individuais de NPS/faturamento (pós-liberação de acesso).

Baixa TODAS as planilhas individuais linkadas na mestre, mede acesso (200 vs
401/erro) e salva o parse em data/nps_indiv_cache.json — cache local (gitignored)
para as análises offline de faturamento×churn não refazerem ~350 downloads.

    backend/.venv/Scripts/python -m scripts.offline_fat_sweep
"""
from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from app.sources import nps_sheets as NPS

DATA = Path(__file__).resolve().parents[2] / "data"
OUT = DATA / "nps_indiv_cache.json"


def fetch_one(row: dict) -> dict:
    sid, gid = row["sheet_id"], row["gid"]
    url = f"https://docs.google.com/spreadsheets/d/{sid}/export"
    params = {"format": "csv"}
    if gid:
        params["gid"] = gid
    for attempt in range(3):
        try:
            with httpx.Client(timeout=45.0, follow_redirects=True) as cli:
                r = cli.get(url, params=params)
            if r.status_code == 429:
                time.sleep(5 * (attempt + 1))
                continue
            if r.status_code != 200:
                return {"clickup_name": row["clickup_name"], "sheet_id": sid,
                        "status": r.status_code, "parsed": None}
            import csv as _csv, io as _io
            rows = list(_csv.reader(_io.StringIO(r.content.decode("utf-8-sig", errors="replace"))))
            return {"clickup_name": row["clickup_name"], "sheet_id": sid,
                    "status": 200, "parsed": NPS.parse_individual_csv(rows)}
        except Exception as e:  # noqa: BLE001
            err = type(e).__name__
            time.sleep(2)
    return {"clickup_name": row["clickup_name"], "sheet_id": sid, "status": err, "parsed": None}


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    master = [r for r in NPS.master_rows() if r["sheet_id"]]
    # dedup por sheet_id (clientes com 2 linhas apontando p/ a mesma planilha)
    seen: dict[str, dict] = {}
    for r in master:
        seen.setdefault(r["sheet_id"], r)
    todo = list(seen.values())
    print(f"planilha mestre: {len(master)} linhas com link, {len(todo)} planilhas únicas")

    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(fetch_one, todo))

    ok = [r for r in results if r["status"] == 200]
    denied = [r for r in results if r["status"] in (401, 403)]
    other = [r for r in results if r["status"] not in (200, 401, 403)]
    com_fat = [r for r in ok if r["parsed"] and any(
        v is not None for b in r["parsed"]["cnpjs"] for vals in b["marketplaces"].values() for v in vals.values())]
    print(f"acessíveis: {len(ok)}/{len(todo)}  |  negadas (401/403): {len(denied)}  |  outros erros: {len(other)}")
    print(f"acessíveis COM faturamento lançado: {len(com_fat)}")
    if denied:
        print("ainda negadas:")
        for r in denied[:15]:
            print("  -", r["clickup_name"][:50], f"({r['status']})")
    if other:
        print("outros erros:")
        for r in other[:10]:
            print("  -", r["clickup_name"][:50], f"({r['status']})")

    OUT.write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")
    print(f"cache salvo em {OUT} ({OUT.stat().st_size/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
