"""Saúde da Receita Recorrente (ISR e Quick Ratio) — fonte: planilha
Planejamento_Receita_2026, aba `2026` (mapeamento CONFIRMADO pelo Otávio
14/07/26). PARSER ISOLADO de propósito: quando o Financeiro abrir e os dados
vierem do Postgres/Omie, só este módulo troca de fonte — a lógica fica.

A aba tem um bloco dedicado já calculado ("ÍNDICE DE SAÚDE DA RECEITA
RECORRENTE"): Recebimento Recorrente B2-B5 / Nova / Perdida-Churn, idem
Planos Antigos e CONSOLIDADO. O parse ancora por RÓTULO (imune a inserção de
linhas — os números de linha do mapeamento deslocavam no CSV do gviz); ISR e
QR são recalculados aqui com as MESMAS fórmulas confirmadas (base ÷ base
anterior ×100; nova ÷ perdida). Validação: B2-B5 jan/26 = R$ 15.250 ✓.
NÃO usar 'Recebimento Recorrente [R$]' simples (resíduo no 1º mês: 559k).
"""
from __future__ import annotations

import csv
import io
import time

import httpx

SHEET_ID = "1V_lVveaEYrr_stZONWKY3beHfJ_JwQ0I"
_CACHE: dict = {"t": 0.0, "dados": None}
_TTL_S = 600  # mesmo padrão da planilha do financeiro (10 min)

MESES = ["dez/25", "jan/26", "fev/26", "mar/26", "abr/26", "mai/26", "jun/26",
         "jul/26", "ago/26", "set/26", "out/26", "nov/26", "dez/26"]


def _num(s: str) -> float | None:
    """'R$ 1.323.166,45' / '$15.250' / '5,00%' / '-' -> float (% vira fração)."""
    s = (s or "").strip().replace("R$", "").replace("$", "").replace("\xa0", "").strip()
    if not s or s == "-":
        return None
    pct = s.endswith("%")
    s = s.rstrip("%").strip().replace(".", "").replace(",", ".")
    try:
        v = float(s)
    except ValueError:
        return None
    return v / 100 if pct else v


def _linha_rotulo(rows: list[list[str]], prefixo: str) -> list[float | None]:
    """Valores (13 meses) da 1ª linha cujo rótulo começa com o prefixo dado."""
    alvo = prefixo.lower()
    for r in rows:
        if r and (r[0] or "").strip().lower().startswith(alvo):
            return [_num(r[i]) if len(r) > i else None for i in range(1, 14)]
    return [None] * 13


def carrega(force: bool = False) -> dict | None:
    """Baixa e computa a série. → {meses, base_b2b5, isr_b2b5, isr_consol,
    novo, perdido, qr, antigos, crossover_idx, alertas} (None se planilha fora)."""
    if not force and _CACHE["dados"] is not None and time.monotonic() - _CACHE["t"] < _TTL_S:
        return _CACHE["dados"]
    try:
        r = httpx.get(f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq",
                      params={"tqx": "out:csv", "sheet": "2026"}, timeout=60,
                      follow_redirects=True)
        r.raise_for_status()
        rows = list(csv.reader(io.StringIO(r.text)))
    except Exception:  # noqa: BLE001 — planilha indisponível não derruba a central
        return _CACHE["dados"]
    base_b2b5 = _linha_rotulo(rows, "recebimento recorrente b2-b5")
    novo = _linha_rotulo(rows, "receita recorrente nova b2-b5")
    perdido = _linha_rotulo(rows, "receita recorrente perdida - churn b2-b5")
    antigos = _linha_rotulo(rows, "recebimento recorrente planos antigos")
    consol = _linha_rotulo(rows, "recebimento recorrente consolidado")
    novo_c = _linha_rotulo(rows, "receita recorrente nova consolidado")
    perdido_c = _linha_rotulo(rows, "receita recorrente perdida - churn consolidado")

    def isr(serie):
        out: list[float | None] = [None]
        for i in range(1, 13):
            a, b = serie[i - 1], serie[i]
            out.append(b / a * 100 if a and b is not None else None)
        return out
    isr_b = isr(base_b2b5)
    isr_c = isr(consol)
    qr = [(novo[i] / perdido[i]) if novo[i] is not None and perdido[i] else None for i in range(13)]
    qr_c = [(novo_c[i] / perdido_c[i]) if novo_c[i] is not None and perdido_c[i] else None for i in range(13)]
    crossover = next((i for i in range(13)
                      if base_b2b5[i] is not None and antigos[i] is not None
                      and base_b2b5[i] > antigos[i]), None)
    # alerta: ISR<100 ou QR<1 por DOIS meses seguidos (sinal de sangria)
    alertas = []
    for i in range(2, 13):
        if isr_b[i] is not None and isr_b[i - 1] is not None and isr_b[i] < 100 and isr_b[i - 1] < 100:
            alertas.append((MESES[i], "ISR B2-B5 < 100 há 2 meses"))
        if qr[i] is not None and qr[i - 1] is not None and qr[i] < 1 and qr[i - 1] < 1:
            alertas.append((MESES[i], "Quick Ratio < 1 há 2 meses"))
    dados = {"meses": MESES, "base_b2b5": base_b2b5, "isr_b2b5": isr_b,
             "isr_consol": isr_c, "consol": consol, "novo": novo, "perdido": perdido,
             "qr": qr, "qr_consol": qr_c, "antigos": antigos,
             "crossover_idx": crossover, "alertas": alertas}
    _CACHE.update(t=time.monotonic(), dados=dados)
    return dados
