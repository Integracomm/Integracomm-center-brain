"""Composição dos SQUADs (Google Sheets) — quem atende cada cliente.

Planilha "SQUADs — volume de serviços e pessoas": blocos por Bundle+Squad
(B1-S1, B1-S2, ... B5-S3) com pares Função → Colaborador (Growth, Gerente de
Contas, Assessor 1..3, Gestor de ADS...). O squad do CLIENTE vem da convenção
de nome do grupo (`[TAG-Bx-Sy] ...` — mesma regra do painel). Fallback: se a
squad exata não existir na planilha mas o bundle tiver UMA só (ex.: B5 → B5-S3),
usa essa. Lido ao vivo (cache 10 min) — a planilha é a fonte da verdade; não
copiamos para o banco para não criar cópia que envelhece.
"""
from __future__ import annotations

import re

from .nps_sheets import _fetch_csv, _get_cached, _norm_label

# 15/07: a planilha original do time ficou restrita (401) e derrubava o
# /growth; o Otávio fez uma CÓPIA no drive dele — precisa estar compartilhada
# como 'qualquer pessoa com o link: leitor' p/ o export funcionar
SQUADS_SHEET_ID = "1mt676ES7rM6caO6vx4tqoVTbqt9wElkiQeAR2fl4ToI"
SQUADS_GID = "241964574"

_SQUAD_RE = re.compile(r"B(\d)\D*S(\d)")


def squad_of(account_name: str | None) -> str | None:
    """Squad Bx-Sy do tag `[...]` do nome da conta (mesma regra do painel)."""
    m = re.match(r"\s*\[([^\]]+)\]", account_name or "")
    if not m:
        return None
    q = _SQUAD_RE.search(m.group(1).upper())
    return f"B{q.group(1)}-S{q.group(2)}" if q else None


def parse_squads_csv(rows: list[list[str]]) -> dict[str, list[dict]]:
    """Grade CSV -> {"B1-S1": [{"funcao": ..., "nome": ...}, ...], ...}."""
    hdr = None
    cols: dict[str, int] = {}
    for i, r in enumerate(rows):
        labels = [_norm_label(c) for c in r]
        if "bundle" in labels and "squad" in labels and "funcao" in labels:
            cols = {"bundle": labels.index("bundle"), "squad": labels.index("squad"),
                    "funcao": labels.index("funcao"), "colab": labels.index("colaborador")}
            hdr = i
            break
    if hdr is None:
        return {}

    def cell(r: list[str], j: int) -> str:
        return (r[j] if j < len(r) else "").strip()

    out: dict[str, list[dict]] = {}
    key = None
    for r in rows[hdr + 1:]:
        b, s = cell(r, cols["bundle"]).upper(), cell(r, cols["squad"]).upper()
        if b and s:
            key = f"{b}-{s}"
            out.setdefault(key, [])
        if key is None:
            continue
        funcao, colab = cell(r, cols["funcao"]), cell(r, cols["colab"])
        if funcao and colab:
            out[key].append({"funcao": funcao, "nome": colab})
    return {k: v for k, v in out.items() if v}


_ULTIMO_BOM: dict[str, list[dict]] = {}
_FALHA_ATE = {"t": 0.0}


def squad_teams() -> dict[str, list[dict]]:
    """NUNCA levanta exceção (15/07: um 401 do Google no export derrubou o
    /growth com 500 em plena preparação de reunião). Falhou → devolve o último
    dado BOM em memória (ou vazio) e faz cache negativo de 5 min para não
    pagar 1 request lento por conta na montagem da página."""
    import time as _t
    if _t.monotonic() < _FALHA_ATE["t"]:
        return _ULTIMO_BOM

    def load():
        url = f"https://docs.google.com/spreadsheets/d/{SQUADS_SHEET_ID}/export"
        return parse_squads_csv(_fetch_csv(url, {"format": "csv", "gid": SQUADS_GID}))
    try:
        out = _get_cached("squads", load)
        if out:
            _ULTIMO_BOM.clear()
            _ULTIMO_BOM.update(out)
        return out
    except Exception:  # noqa: BLE001 — planilha fora/restrita não derruba página
        _FALHA_ATE["t"] = _t.monotonic() + 300
        return _ULTIMO_BOM


def team_for_key(key: str | None) -> tuple[str, list[dict]] | None:
    """(squad, membros) p/ uma chave Bx-Sy; fallback de bundle quando a squad
    exata não consta (ex.: B5-S1 pedido, planilha só tem B5-S3)."""
    if not key:
        return None
    q = _SQUAD_RE.search(key.upper())
    if not q:
        return None
    key = f"B{q.group(1)}-S{q.group(2)}"
    teams = squad_teams()
    if key in teams:
        return key, teams[key]
    bundle = key.split("-")[0]
    same_bundle = [k for k in teams if k.startswith(bundle + "-")]
    if len(same_bundle) == 1:
        return same_bundle[0], teams[same_bundle[0]]
    return None


def team_for_account(account_name: str | None, fallback_key: str | None = None) -> tuple[str, list[dict]] | None:
    """(squad, membros) da conta. PRIORIDADE: `fallback_key` (campo equipe do
    espelho da Operação, atualizado pelo HUB) sobre o tag Bx-Sy do nome do
    grupo — o tag fica DESATUALIZADO quando o cliente troca de squad e ninguém
    renomeia o grupo (Otávio 15/07: CEREJA CHIC tag B3-S1 mas equipe real
    B3-S2; DNEZA tag B3-S1 mas B1-S2). Tag do nome = fallback."""
    return team_for_key(fallback_key) or team_for_key(squad_of(account_name))


def gc_of_team(members: list[dict]) -> str | None:
    for m in members:
        if _norm_label(m["funcao"]).startswith("gerente"):
            return m["nome"]
    return None
