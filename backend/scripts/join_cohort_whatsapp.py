"""Join: coorte retrospectiva (cancelados abr-jun/2026) × grupos de WhatsApp.

Responde o número que falta: dos ~50-55 cancelamentos, quantos têm grupo de
WhatsApp COM sinal de conversa na janela pré-churn (e com quanta antecedência).

Usa o endpoint leve `analyses` (veredito por grupo/dia) para detectar presença
de conversa sem baixar conteúdo bruto. Rodar quando GROWTH_AGENT_* estiverem no
.env:

    cd backend && python -m scripts.join_cohort_whatsapp

Read-only. Não escreve em nenhuma fonte.
"""
from __future__ import annotations

import csv
import datetime as dt
import re
import sys
import unicodedata
from pathlib import Path

from app.config import get_settings
from app.sources.whatsapp import WhatsAppReader

DATA = Path(__file__).resolve().parents[2] / "data"
COHORT_CSV = DATA / "slice_abr_jun_2026.csv"  # CS/Cancelados abr-jun (41, bundle)
PRE_CHURN_DAYS = 90


def norm(s: str | None) -> str:
    if not s:
        return ""
    x = unicodedata.normalize("NFD", s.lower())
    x = "".join(c for c in x if unicodedata.category(c) != "Mn")
    x = re.sub(r"^\s*\[[^\]]*\]\s*", "", x)
    x = x.split("|")[0]
    x = re.sub(r"[^a-z0-9 ]", " ", x)
    return re.sub(r"\s+", " ", x).strip()


def extract_id(name: str | None) -> str | None:
    if not name:
        return None
    m = re.search(r"id\s*:\s*([a-z0-9_-]+)", name, re.I)
    return m.group(1).lower() if m else None


def load_cohort() -> list[dict]:
    if not COHORT_CSV.exists():
        sys.exit(f"Coorte não encontrada: {COHORT_CSV}")
    with COHORT_CSV.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main() -> None:
    s = get_settings()
    if not (s.whatsapp_read_api_url and s.whatsapp_read_api_key):
        sys.exit("Defina WHATSAPP_READ_API_URL e WHATSAPP_READ_API_KEY no .env antes de rodar.")

    reader = WhatsAppReader(s.whatsapp_read_api_url, s.whatsapp_read_api_key)
    cohort = load_cohort()
    print(f"Coorte: {len(cohort)} contas (abr-jun/2026).")

    # Índice de grupos por ID interno e por nome normalizado.
    by_id: dict[str, dict] = {}
    by_name: dict[str, dict] = {}
    n_groups = 0
    for g in reader.iter_groups():
        n_groups += 1
        gid = extract_id(g.name)
        if gid:
            by_id[gid] = g.raw | {"_internal_id": g.id}
        nm = norm(g.name)
        if nm:
            by_name.setdefault(nm, g.raw | {"_internal_id": g.id})
    print(f"Grupos de WhatsApp: {n_groups}")

    # Analyses por group_id (presença de conversa por dia).
    analyses_by_group: dict[str, list[str]] = {}
    for a in reader.iter_analyses():
        analyses_by_group.setdefault(a.group_id, []).append(a.analysis_date)

    rows = []
    matched = with_signal = 0
    for c in cohort:
        name = c.get("cliente") or ""
        best = c.get("best_date") or ""
        g = by_id.get(extract_id(name) or "") or by_name.get(norm(name))
        has_group = g is not None
        in_window = 0
        if g and best:
            try:
                end = dt.date.fromisoformat(best)
                start = end - dt.timedelta(days=PRE_CHURN_DAYS)
            except ValueError:
                end = start = None
            if end:
                dates = analyses_by_group.get(g["_internal_id"], [])
                in_window = sum(1 for d in dates if d and start.isoformat() <= d <= end.isoformat())
        if has_group:
            matched += 1
        if in_window > 0:
            with_signal += 1
        rows.append(
            {
                "cliente": name,
                "best_date": best,
                "plano": c.get("plano"),
                "tem_grupo": has_group,
                "dias_com_analise_na_janela": in_window,
            }
        )

    out = DATA / "join_cohort_whatsapp.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print("\n=== RESULTADO ===")
    print(f"  coorte:                          {len(cohort)}")
    print(f"  com grupo de WhatsApp:           {matched}")
    print(f"  com sinal de conversa na janela: {with_signal}  <- N retrospectivo utilizável")
    print(f"  salvo: {out}")
    reader.close()


if __name__ == "__main__":
    main()
