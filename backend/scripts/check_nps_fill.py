"""Checagem MENSAL do preenchimento de faturamento nas planilhas NPS individuais.

Roda todo dia 2 (embutida na rodada diária: run_agent_scheduled.ps1 chama este
script quando (Get-Date).Day -eq 2) e avisa no MESMO grupo do Slack dos demais
relatórios quem ainda não lançou o mês anterior.

Regra do negócio (Otávio, 2026-07-06): cliente sem faturamento no mês deve ter
R$ 0 LANÇADO — nenhum cliente ativo pode ficar com o mês em branco.

Universo: aba "ClickUp" da planilha mestre (lista ativa mantida pela equipe;
Task ID + link NPS). Link da individual: coluna NPS(url) da própria aba, com
fallback por nome na aba "NPS De Omie para Clikup" (histórico).

    backend/.venv/Scripts/python -m scripts.check_nps_fill            # imprime (dry-run)
    backend/.venv/Scripts/python -m scripts.check_nps_fill --slack    # envia ao grupo
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.sources.nps_sheets import (MASTER_SHEET_ID, norm_full,  # noqa: E402
                                    parse_individual_csv)

_MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
          "agosto", "setembro", "outubro", "novembro", "dezembro"]
_SID = re.compile(r"/spreadsheets/d/([A-Za-z0-9_-]+)")


def _sid(u) -> str | None:
    m = _SID.search(str(u or ""))
    return m.group(1) if m else None


def _load_env() -> None:
    envf = Path(__file__).resolve().parents[2] / ".env"
    if envf.exists():
        for line in envf.read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def _fetch_tab(tab: str) -> list[list[str]]:
    r = httpx.get(f"https://docs.google.com/spreadsheets/d/{MASTER_SHEET_ID}/gviz/tq",
                  params={"tqx": "out:csv", "sheet": tab}, timeout=60, follow_redirects=True)
    r.raise_for_status()
    return list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))


def _ftoks(s: str) -> set[str]:
    return set(re.sub(r"\bid\b|\d+", "", norm_full(s)).split())


def ref_month(today: dt.date | None = None) -> str:
    d = (today or dt.date.today()).replace(day=1) - dt.timedelta(days=1)
    return d.strftime("%Y-%m")


def collect(today: dt.date | None = None) -> dict:
    """Verifica o mês anterior em todas as planilhas dos clientes da aba ClickUp.
    Retorna {ref, ok, pendentes: {categoria: [nomes]}}."""
    ref = ref_month(today)
    cu = _fetch_tab("ClickUp")
    clientes = [{"name": row[1].strip(), "sid": _sid(row[10] if len(row) > 10 else "")}
                for row in cu[1:] if len(row) > 1 and row[0].strip() and row[0].strip() != "Task ID"]
    # fallback de link pela aba histórico (match por nome)
    nps = _fetch_tab("NPS De Omie para Clikup")
    nps_idx = [(_ftoks(row[1]), _sid(row[2] if len(row) > 2 else ""))
               for row in nps[1:] if len(row) > 1 and row[1].strip()]

    def link_for(c) -> str | None:
        if c["sid"]:
            return c["sid"]
        tn = _ftoks(c["name"])
        best, sc = None, 0.0
        for tc, s in nps_idx:
            if not tc or not s:
                continue
            x = len(tn & tc) / max(1, min(len(tn), len(tc)))
            if x > sc:
                sc, best = x, s
        return best if sc >= 0.7 else None

    def check(c) -> tuple[str, str | None]:
        s = link_for(c)
        if not s:
            return c["name"], "sem link de planilha"
        try:
            r = httpx.get(f"https://docs.google.com/spreadsheets/d/{s}/export",
                          params={"format": "csv"}, timeout=45, follow_redirects=True)
            if r.status_code in (401, 403):
                return c["name"], "planilha com acesso bloqueado"
            r.raise_for_status()
            p = parse_individual_csv(list(csv.reader(io.StringIO(
                r.content.decode("utf-8-sig", errors="replace")))))
            if ref not in p.get("months", []) or not p["cnpjs"]:
                return c["name"], "planilha sem colunas até o mês"
            vals = [v for b in p["cnpjs"] for m in b["marketplaces"].values()
                    for k, v in m.items() if k == ref and v is not None]
            return c["name"], (None if vals else "mês em branco")
        except Exception as e:  # noqa: BLE001 — categoria própria; não derruba a checagem
            return c["name"], f"erro de leitura ({type(e).__name__})"

    with ThreadPoolExecutor(max_workers=6) as ex:
        res = list(ex.map(check, clientes))
    pend: dict[str, list[str]] = {}
    for name, cat in res:
        if cat:
            pend.setdefault(cat, []).append(name)
    return {"ref": ref, "total": len(clientes),
            "ok": sum(1 for _, c in res if c is None), "pendentes": pend}


def report_text(r: dict) -> str:
    y, m = r["ref"].split("-")
    label = f"{_MESES[int(m) - 1]}/{y}"
    n_pend = sum(len(v) for v in r["pendentes"].values())
    lines = [f"*NPS/Faturamento — checagem mensal ({label})*",
             f"• Clientes ativos verificados: {r['total']}",
             f"• Mês lançado: {r['ok']} ✅ · Pendentes: {n_pend} ❌"]
    ordem = ["mês em branco", "planilha sem colunas até o mês",
             "sem link de planilha", "planilha com acesso bloqueado"]
    cats = ordem + [c for c in r["pendentes"] if c not in ordem]
    for cat in cats:
        nomes = r["pendentes"].get(cat)
        if not nomes:
            continue
        lines += ["", f"*{cat.capitalize()} ({len(nomes)}):*"]
        lines += [f"• {n[:60]}" for n in sorted(nomes)]
    lines += ["", "_regra: sem faturamento no mês = lançar R$ 0 — nenhum cliente ativo pode ficar em branco_"]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slack", action="store_true", help="envia ao grupo do Slack (senão só imprime)")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    _load_env()
    r = collect()
    text = report_text(r)
    print(text)
    if args.slack:
        from app.slack import send_text, webhook_configured
        if not webhook_configured():
            print("\n[erro] SLACK_WEBHOOK_URL não configurada — não enviado", file=sys.stderr)
            sys.exit(2)
        send_text(text)
        print("\n[ok] enviado ao grupo do Slack")


if __name__ == "__main__":
    main()
