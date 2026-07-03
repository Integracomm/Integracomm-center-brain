"""Faturamento (planilhas NPS individuais) prediz churn? — caso-controle as-of.

Antes não dava para testar: as planilhas individuais estavam bloqueadas
(acesso liberado pelo Otávio em 2026-07-03) e a crença registrada era
"faturamento esparso+tardio, não é preditor". Este script testa com os dados
completos, sem vazamento: para cada conta, série mensal de faturamento total
(soma de todos os CNPJs/marketplaces; mês sem NENHUM lançamento = ausente, não
zero) e sinais de QUEDA medidos só com meses ANTERIORES ao mês do evento
(churn p/ casos; 2026-06 p/ controles → m0 = mês cheio anterior).

Sinais (menor = pior, mesma convenção do score):
  mom    = fat[m0] / fat[m0−1]            (queda mês a mês)
  base3  = fat[m0] / média(fat[m0−3..m0−1]) (queda vs baseline de 3 meses)
  slide2 = fat[m0] / fat[m0−2]            (queda em 2 meses)

AUC = P(cancelado < controle): >0,5 = queda de faturamento ANTECEDE churn.

    backend/.venv/Scripts/python -m scripts.offline_fat_sweep   # 1º (cache)
    backend/.venv/Scripts/python -m scripts.offline_fat_churn
"""
from __future__ import annotations

import datetime as dt
import json
import statistics
import sys
from pathlib import Path

from app.sources.nps_sheets import norm_account
from scripts.offline_abs_vs_rel import DATA, rows
from scripts.offline_score_account_check import auc

CACHE = DATA / "nps_indiv_cache.json"


def month_add(ym: str, delta: int) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    t = y * 12 + (m - 1) + delta
    return f"{t // 12:04d}-{t % 12 + 1:02d}"


def revenue_series(parsed: dict) -> dict[str, float]:
    """{YYYY-MM: total} somando CNPJs/marketplaces; mês sem lançamento = ausente."""
    out: dict[str, float] = {}
    for b in parsed.get("cnpjs", []):
        for vals in b["marketplaces"].values():
            for ym, v in vals.items():
                if v is not None:
                    out[ym] = out.get(ym, 0.0) + v
    return out


def signals(series: dict[str, float], m0: str) -> dict[str, float | None]:
    def get(ym):
        return series.get(ym)
    f0, f1, f2, f3 = get(m0), get(month_add(m0, -1)), get(month_add(m0, -2)), get(month_add(m0, -3))
    mom = (f0 / f1) if (f0 is not None and f1) else None
    base = [x for x in (f1, f2, f3) if x]
    base3 = (f0 / statistics.mean(base)) if (f0 is not None and len(base) >= 2) else None
    slide2 = (f0 / f2) if (f0 is not None and f2) else None
    return {"mom": mom, "base3": base3, "slide2": slide2}


def _fix_mojibake(s: str) -> str:
    """Repara nomes gravados com dupla decodificação nos CSVs da coorte
    (ex.: 'CALÃ\x87ADOS' -> 'CALÇADOS')."""
    try:
        fixed = s.encode("latin-1").decode("utf-8")
        return fixed if fixed != s else s
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def _lookup(by_name: dict[str, dict], nome: str) -> dict | None:
    """Match exato pelo nome-base; fallback: sobreposição de tokens ≥ 2/3 do
    lado mais curto (cobre 'LOONEY BABY CONFECÇÕES' vs 'Looney Baby | Renato')."""
    n = norm_account(_fix_mojibake(nome))
    if n in by_name:
        return by_name[n]
    tc = set(n.split())
    if not tc:
        return None
    best, best_score = None, 0.0
    for mn, series in by_name.items():
        tm = set(mn.split())
        score = len(tc & tm) / max(1, min(len(tc), len(tm)))
        if score > best_score:
            best_score, best = score, series
    return best if best_score >= 0.67 else None


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    cache = json.loads(CACHE.read_text(encoding="utf-8"))
    by_name: dict[str, dict] = {}
    for r in cache:
        if r["status"] == 200 and r["parsed"]:
            n = norm_account(r["clickup_name"])
            if n and n not in by_name:
                by_name[n] = revenue_series(r["parsed"])

    cohort = []  # (label, nome, mês-do-evento)
    for r in rows(DATA / "cases_expanded.csv"):
        if r.get("date"):
            cohort.append(("cancelado", r["cliente"], r["date"][:7]))
    for r in rows(DATA / "controls_active_bundles.csv"):
        cohort.append(("controle", r["cliente"], "2026-06"))

    for lead_label, lead in (("m0 = evento−1 mês", 1), ("m0 = evento−2 meses", 2)):
        vals = {k: {"cancelado": [], "controle": []} for k in ("mom", "base3", "slide2")}
        matched = {"cancelado": 0, "controle": 0}
        no_sheet = 0
        for label, nome, ev_month in cohort:
            series = _lookup(by_name, nome)
            if not series:
                no_sheet += 1
                continue
            m0 = month_add(ev_month, -lead)
            sg = signals(series, m0)
            if any(v is not None for v in sg.values()):
                matched[label] += 1
            for k, v in sg.items():
                if v is not None:
                    vals[k][label].append(v)
        print(f"\n=== {lead_label} ===  (com sinal: canc={matched['cancelado']}/61  "
              f"ctrl={matched['controle']}/200  |  sem planilha/sem série: {no_sheet})")
        for k in ("mom", "base3", "slide2"):
            c, t = vals[k]["cancelado"], vals[k]["controle"]
            if len(c) < 8 or len(t) < 20:
                print(f"  {k:7s}: amostra insuficiente (canc={len(c)} ctrl={len(t)})")
                continue
            a = auc(c, t)
            print(f"  {k:7s}: AUC={a:.3f}  canc n={len(c)} mediana={statistics.median(c):.2f}  "
                  f"ctrl n={len(t)} mediana={statistics.median(t):.2f}")


if __name__ == "__main__":
    main()
