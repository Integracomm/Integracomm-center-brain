"""Planilha de PLANEJAMENTO FINANCEIRO (Planejamento_Receita_2026, aba 2026)
— fonte da área /financeiro (pedido Otávio 15/07/26).

Grade: coluna 0 = rótulo da métrica; colunas seguintes = meses dez/25..dez/26,
com uma coluna extra "<mês> (Parcial)" = realizado ATÉ AGORA do mês corrente
(preenchida manualmente pelo time). Meses PASSADOS = realizado; mês corrente e
seguintes = meta/projeção. O parse ancora por RÓTULO (imune a inserção de
linhas) e detecta os meses pelo CABEÇALHO (imune a inserção de colunas).

Mesma filosofia do receita_recorrente.py (que lê OUTRO bloco desta mesma
planilha): parser isolado — quando o Financeiro migrar ao Omie/Postgres, só
este módulo troca de fonte.
"""
from __future__ import annotations

import csv
import io
import re
import time

import httpx

SHEET_ID = "1V_lVveaEYrr_stZONWKY3beHfJ_JwQ0I"
GID = "1955381933"
_CACHE: dict = {"t": 0.0, "dados": None}
_TTL_S = 600  # planilha muda poucas vezes ao dia; 10 min como as demais

_MES_NUM = {"jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
            "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12}


def _num(s: str) -> float | None:
    """'R$ 1.323.166,45' / '$15.250' / '5,00%' / '4,2x' / '-' → float
    (% vira fração; 'x' de Quick Ratio é descartado)."""
    s = (s or "").strip().replace("R$", "").replace("$", "").replace("\xa0", "").strip()
    if not s or s in ("-", "–"):
        return None
    pct = s.endswith("%")
    s = s.rstrip("%").rstrip("xX").strip().replace(".", "").replace(",", ".")
    try:
        v = float(s)
    except ValueError:
        return None
    return v / 100 if pct else v


def _mes_iso(celula: str) -> str | None:
    """'dez.-25' / 'jul - 26 (Parcial)' / 'jul.-26' → 'YYYY-MM'."""
    c = (celula or "").strip().lower()
    m = re.match(r"([a-zç]{3})", c)
    n = re.search(r"(\d{2})", c)
    if not (m and n and m.group(1) in _MES_NUM):
        return None
    return f"20{n.group(1)}-{_MES_NUM[m.group(1)]:02d}"


def carrega(force: bool = False) -> dict | None:
    """→ {meses: ['YYYY-MM'...], parcial_mes, linhas: {rotulo: {vals, parcial}},
    ordem: [rotulos]} — None se a planilha estiver fora do ar."""
    if not force and _CACHE["dados"] is not None and time.monotonic() - _CACHE["t"] < _TTL_S:
        return _CACHE["dados"]
    try:
        r = httpx.get(f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq",
                      params={"tqx": "out:csv", "gid": GID}, timeout=60, follow_redirects=True)
        r.raise_for_status()
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig", errors="replace"))))
        if not rows or len(rows) < 10:
            raise ValueError("planilha vazia/suspeita")

        # cabeçalho: mapeia coluna -> mês; a coluna '(Parcial)' vira canal próprio.
        # ATENÇÃO: o gviz às vezes devolve o cabeçalho da Parcial VAZIO (célula
        # mesclada) — fallback: coluna SEM mês no cabeçalho mas COM valores
        # numéricos, entre colunas de mês, é a Parcial do mês da coluna seguinte.
        col_mes: list[tuple[int, str]] = []   # (col, iso) — SEM a parcial
        parcial_col, parcial_mes = None, None
        for j, cell in enumerate(rows[0][1:], start=1):
            iso = _mes_iso(cell)
            if not iso:
                continue
            if "parcial" in cell.lower():
                parcial_col, parcial_mes = j, iso
            else:
                col_mes.append((j, iso))
        if len(col_mes) < 6:
            raise ValueError(f"cabeçalho de meses não reconhecido ({len(col_mes)} meses)")
        if parcial_col is None:
            cols_com_mes = {j for j, _ in col_mes}
            for j in range(col_mes[0][0] + 1, col_mes[-1][0]):
                if j in cols_com_mes:
                    continue
                n_vals = sum(1 for row in rows[1:] if j < len(row) and _num(row[j]) is not None)
                if n_vals >= 3:
                    parcial_col = j
                    parcial_mes = next((iso for c, iso in col_mes if c > j), None)
                    break

        linhas: dict[str, dict] = {}
        ordem: list[str] = []
        for row in rows[1:]:
            rot = (row[0] if row else "").strip()
            if not rot or rot in linhas:
                continue
            vals = [_num(row[j]) if j < len(row) else None for j, _ in col_mes]
            if not any(v is not None for v in vals):
                # linha-título de seção (ISR / INFLUÊNCIA...) — guarda vazia p/ ordem
                linhas[rot] = {"vals": vals, "parcial": None, "secao": True}
                ordem.append(rot)
                continue
            parcial = (_num(row[parcial_col]) if parcial_col is not None
                       and parcial_col < len(row) else None)
            linhas[rot] = {"vals": vals, "parcial": parcial, "secao": False}
            ordem.append(rot)

        dados = {"meses": [iso for _, iso in col_mes], "parcial_mes": parcial_mes,
                 "linhas": linhas, "ordem": ordem}
        _CACHE.update(t=time.monotonic(), dados=dados)
        return dados
    except Exception:  # noqa: BLE001 — planilha fora não derruba a área
        return _CACHE["dados"]


def linha(dados: dict, prefixo: str) -> list[float | None]:
    """Valores da 1ª linha cujo rótulo começa com o prefixo (case-insensitive)."""
    alvo = prefixo.lower()
    for rot, d in dados["linhas"].items():
        if rot.lower().startswith(alvo) and not d["secao"]:
            return d["vals"]
    return [None] * len(dados["meses"])


def parcial(dados: dict, prefixo: str) -> float | None:
    alvo = prefixo.lower()
    for rot, d in dados["linhas"].items():
        if rot.lower().startswith(alvo) and not d["secao"]:
            return d["parcial"]
    return None
