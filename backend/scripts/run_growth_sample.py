"""Roda o GrowthAgent numa AMOSTRA real e grava scores no Postgres.

Mistura contas conhecidas: cancelados (desengajando, asof = data do churn) e
ativos (saudável, asof = hoje). Resolve cada conta ao seu grupo de WhatsApp
pelo cache, roda collect→analyze→score→persist e imprime os scores.

    backend/.venv/Scripts/python -m scripts.run_growth_sample
"""
from __future__ import annotations

import csv
import datetime as dt
import os
import re
import unicodedata
import uuid
from pathlib import Path

import psycopg

from app.agents.base import AgentContext
from app.agents.growth.agent import GrowthAgent

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
TODAY = dt.date.today()  # asof dos ativos = hoje real (analyses ao vivo)


def load_env() -> None:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def norm(s: str | None) -> str:
    if not s:
        return ""
    x = unicodedata.normalize("NFD", s.lower())
    x = "".join(c for c in x if unicodedata.category(c) != "Mn")
    x = re.sub(r"^\s*\[[^\]]*\]\s*", "", x).split("|")[0]
    x = x.replace("integracomm", "")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", x)).strip()


def extract_id(s: str | None) -> str | None:
    m = re.search(r"id\s*:\s*([a-z0-9_-]+)", s or "", re.I)
    return m.group(1).lower() if m else None


def _rows(path: Path) -> list[dict]:
    # utf-8-sig descarta o BOM que o Export-Csv do PowerShell 5.1 grava
    with path.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def main() -> None:
    load_env()

    # índice de grupos: id interno (ID: XXXX) e nome normalizado -> UUID do grupo
    by_id, by_name = {}, {}
    for g in _rows(DATA / "wa_groups.csv"):
        gid = extract_id(g["name"])
        if gid:
            by_id[gid] = g["id"]
        n = norm(g["name"])
        if n:
            by_name.setdefault(n, g["id"])

    # MRR (planilha NPS) para ponderar receita
    mrr = {}
    for r in _rows(DATA / "nps_fat.csv"):
        v = re.sub(r"[^\d,]", "", r.get("Assessoria (currency)", "")).replace(",", ".")
        if v:
            try:
                mrr[norm(r["Task Name"])] = float(v)
            except ValueError:
                pass

    def resolve(name: str):
        return by_id.get(extract_id(name) or "") or by_name.get(norm(name))

    sample = []
    # cancelados (desengajando) — asof = data do churn
    for r in _rows(DATA / "cases_expanded.csv"):
        g = resolve(r["cliente"])
        if g and r.get("date"):
            sample.append({"account_id": r["cliente"][:60], "name": r["cliente"], "group_id": g,
                           "asof": dt.date.fromisoformat(r["date"]), "plan_category": r.get("plano"),
                           "is_legacy": False, "recurring_revenue": mrr.get(norm(r["cliente"])),
                           "_label": "cancelado/desengajando"})
        if len([s for s in sample if s["_label"].startswith("cancel")]) >= 3:
            break
    # ativos (saudável) — asof = hoje
    for r in _rows(DATA / "controls_active_bundles.csv"):
        g = resolve(r["cliente"])
        if g:
            sample.append({"account_id": r["cliente"][:60], "name": r["cliente"], "group_id": g,
                           "asof": TODAY, "plan_category": None, "is_legacy": False,
                           "recurring_revenue": mrr.get(norm(r["cliente"])), "_label": "ativo/saudavel"})
        if len([s for s in sample if s["_label"].startswith("ativo")]) >= 3:
            break

    print(f"Amostra resolvida: {len(sample)} contas")
    for s in sample:
        print(f"  [{s['_label']}] {s['name']}  asof={s['asof']}  mrr={s['recurring_revenue']}")

    url = os.environ["APP_DATABASE_URL"]
    agent = GrowthAgent(conn_factory=lambda: psycopg.connect(url))
    ctx = AgentContext(
        window_start=dt.datetime(2026, 4, 1, tzinfo=dt.timezone.utc),
        window_end=dt.datetime.combine(TODAY, dt.time.max, tzinfo=dt.timezone.utc),
        run_id=str(uuid.uuid4()), audit=None,
    )
    ctx.sample = sample
    scores = agent.run(ctx)

    print("\n=== SCORES (reais) ===")
    for s in sorted(scores, key=lambda x: x.score):
        alerta = "  *** ALERTA" if (s.risk_band in ("alto", "critico") or (s.risk_band == "medio" and s.trajectory.value == "caindo")) else ""
        print(f"  {s.score:5.1f} | {s.risk_band:7} | {s.trajectory.value:8} | {s.stage.value:22} | conf={s.confidence} | {s.account_name[:40]}{alerta}")

    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM scores"); n_sc = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM alerts"); n_al = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM signal_snapshots"); n_sg = cur.fetchone()[0]
        print(f"\nNo banco: scores={n_sc} alerts={n_al} signal_snapshots={n_sg}")


if __name__ == "__main__":
    main()
