"""Histórico de testes de criativos — Supabase do ad-insightify (Lovable Cloud).

Policy de SELECT p/ anon aplicada pelo Otávio em 2026-07-06. Tabelas:
  creative_history_daily (métricas diárias por anúncio) e
  creative_history_runs (rodadas de teste: started_at/ended_at/days_active).
Leitura ao vivo com cache em memória (TTL 30 min) — histórico muda devagar;
não duplicamos no Postgres. ATENÇÃO .env: SUPABASE_URL sem https:// e valores
entre aspas — sempre limpar.
"""
from __future__ import annotations

import os
import time
from typing import Any

import httpx

_TTL = 1800.0
_cache: dict[str, tuple[float, Any]] = {}


def _conf() -> tuple[str, str]:
    url = (os.environ.get("SUPABASE_URL") or "").strip().strip('"').strip("'")
    key = (os.environ.get("SUPABASE_PUBLISHABLE_KEY") or "").strip().strip('"').strip("'")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL/SUPABASE_PUBLISHABLE_KEY ausentes no .env")
    if not url.startswith("http"):
        url = "https://" + url
    return url.rstrip("/"), key


def _fetch_all(table: str, order: str) -> list[dict]:
    key_c = f"cri:{table}"
    hit = _cache.get(key_c)
    if hit and time.monotonic() - hit[0] < _TTL:
        return hit[1]
    url, key = _conf()
    h = {"apikey": key, "Authorization": f"Bearer {key}"}
    out: list[dict] = []
    offset = 0
    with httpx.Client(timeout=60.0) as cli:
        while True:  # PostgREST corta em 1000 linhas/resposta — paginar sempre
            r = cli.get(f"{url}/rest/v1/{table}",
                        params={"order": order, "limit": "1000", "offset": str(offset)}, headers=h)
            r.raise_for_status()
            page = r.json()
            out.extend(page)
            if len(page) < 1000:
                break
            offset += 1000
    _cache[key_c] = (time.monotonic(), out)
    return out


def daily() -> list[dict]:
    """Métricas diárias por anúncio (ad_id, adset_name, campaign_name, spend, ...)."""
    return _fetch_all("creative_history_daily", "date.asc")


def runs() -> list[dict]:
    """Rodadas de teste por criativo (started_at, ended_at, days_active, ...)."""
    return _fetch_all("creative_history_runs", "started_at.asc")
