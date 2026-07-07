"""Coletores de sinais reais (WhatsApp) → séries temporais por conta.

Transforma mensagens (via WhatsAppReader) + analyses (veredito diário) em
SÉRIES SEMANAIS dos sinais líderes validados na calibração:
  - silencio          (engagement) : % de dias SEM CONVERSA na semana
  - iniciativa_cliente(engagement) : nº de mensagens do cliente na semana
  - comprimento_msg   (tone)       : comprimento médio das msgs do cliente
  - tom_negativo      (tone)       : % de dias-de-conversa negativos (CRÍT/ATEN)

A janela é ancorada em max(asof-90d, primeira data com dado) — mesma correção
de confound usada na calibração (não confundir ausência de dado com silêncio).
Equipe vs cliente: sender_name com "INTEGRACOMM" = equipe.
"""
from __future__ import annotations

import csv
import datetime as dt
import os
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

import httpx

from ...sources.whatsapp import WhatsAppReader
from .scoring import SignalInput

# "Fala em cancelar" — regex CONSERVADORA (foco em cancelar SERVIÇO/contrato, não
# a conta do marketplace). O confirmador primário continua sendo o CRÍTICO das
# analyses (que já faz essa distinção); este texto é um reforço.
_CANCEL_RE = re.compile(
    r"(quero|vou|gostaria de|favor|pode|pra|para)\s+(cancelar|encerrar|rescindir)"
    r"|cancel\w*\s+(o\s+|nosso\s+|esse\s+)?(contrato|servico|plano)"
    r"|encerr\w+\s+(a\s+|o\s+|essa\s+|nossa\s+|com\s+)?(contrato|parceria|assessoria)"
    r"|rescis\w+|rescindir"
    r"|(quero|vou|decidi)\s+sair"
    r"|nao\s+vou\s+(continuar|renovar|investir)"
    r"|nao\s+quero\s+(mais|continuar|renovar)"
    # frases de saída que escapavam (ex.: SOLUTION STORE "pensando seriamente em parar")
    r"|pens\w+\s+(seriamente\s+)?em\s+(parar|sair|cancelar|desistir)"
    r"|(vou|quero|penso)\s+(parar|desistir)"
    r"|desist\w+\s+(do|da|de|dos)\s+(servico|contrato|plano|assessoria|integracomm)"
    r"|nao\s+(vale|compensa)\s+(a\s+pena\s+)?(continuar|seguir|manter)"
    # forma SUBSTANTIVADA/formal (caso real BENE TU 01/07/26: "venho por meio
    # desta, solicitar o cancelamento de nosso contrato... formalizacao desse
    # encerramento" — a versao anterior so cobria o VERBO "cancelar")
    r"|(solicit\w+|peco|pedir|pedimos|queremos|quero)\s+(o\s+)?(cancelamento|encerramento|rescisao|distrato)"
    r"|(cancelamento|encerramento)\s+(de\s+|do\s+|da\s+)?(o\s+|noss[oa]s?\s+|ess[ea]\s+|est[ea]\s+)?(contrato|servico|plano|parceria|assessoria)"
    r"|(formaliza\w+|procedimento\w*)\s+(desse|deste|do|de|da)\s+(encerramento|cancelamento|rescisao|distrato)"
    r"|distrato",
    re.IGNORECASE,
)


def _norm_txt(s: str) -> str:
    x = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in x if unicodedata.category(c) != "Mn")


def _monday(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=d.weekday())


def load_analyses_cache(path: Path) -> dict[str, list[tuple[str, str]]]:
    """data/wa_analyses.csv (group_id, analysis_date, classification) -> por grupo."""
    by_group: dict[str, list[tuple[str, str]]] = defaultdict(list)
    with path.open(encoding="utf-8-sig") as f:  # utf-8-sig descarta BOM do Export-Csv
        for row in csv.DictReader(f):
            by_group[row["group_id"]].append((row["analysis_date"], row["classification"]))
    return by_group


# Equipe que escreve de número PESSOAL (sem "INTEGRACOMM" no nome) — caso real:
# Eduardo (Coordenador de Performance) fez retenção no grupo ALMEIDA citando
# "cancelamento do contrato" e a frase contou como fala do CLIENTE. Lista
# configurável no .env: GROWTH_TEAM_SENDERS=Eduardo Luiz,Fulano
_TEAM_EXTRA = {s.strip().upper() for s in os.environ.get("GROWTH_TEAM_SENDERS", "").split(",")
               if s.strip()}


def _is_team(sender_name: str | None) -> bool:
    if not sender_name:
        return False
    up = sender_name.upper()
    return "INTEGRACOMM" in up or any(t in up for t in _TEAM_EXTRA)


def build_account_signals(
    reader: WhatsAppReader,
    *,
    group_internal_id: str,
    asof: dt.date,
    analyses_by_group: dict[str, list[tuple[str, str]]],
    window_days: int = 90,
) -> list[SignalInput]:
    """Constrói os SignalInput de WhatsApp de UMA conta na janela pré-asof."""
    end_dt = dt.datetime.combine(asof, dt.time.max, tzinfo=dt.timezone.utc)
    start_default = asof - dt.timedelta(days=window_days)

    # --- mensagens (cliente vs equipe) por semana ---
    cli_count: dict[dt.date, int] = defaultdict(int)
    cli_len: dict[dt.date, list[int]] = defaultdict(list)
    first_data: dt.date | None = None
    cancel_phrase = False  # "fala em cancelar" (texto) nas últimas 3 semanas
    cancel_cut = asof - dt.timedelta(days=21)
    start_dt = dt.datetime.combine(start_default, dt.time.min, tzinfo=dt.timezone.utc)
    # Paginação por group_id habilitada no gateway (índice + keyset). try/except
    # fica como defensivo. Silêncio/tom vêm das analyses; aqui: frequência,
    # comprimento e detecção textual de cancelamento.
    try:
        for m in reader.iter_messages(group_id=group_internal_id, window_start=start_dt, order="desc"):
            if not m.received_at:
                continue
            d = m.received_at.date()
            if d < start_default or d > asof:
                continue
            first_data = d if first_data is None else min(first_data, d)
            if not _is_team(m.sender_name):
                wk = _monday(d)
                cli_count[wk] += 1
                txt = m.message_text or m.audio_transcription or ""
                cli_len[wk].append(len(txt))
                if not cancel_phrase and d >= cancel_cut and txt and _CANCEL_RE.search(_norm_txt(txt)):
                    cancel_phrase = True
    except httpx.HTTPStatusError:
        pass  # defensivo

    # --- analyses (silêncio / negativo) por semana ---
    sem: dict[dt.date, int] = defaultdict(int)
    conv: dict[dt.date, int] = defaultdict(int)
    neg: dict[dt.date, int] = defaultdict(int)
    crit_dates: list[dt.date] = []  # dias CRÍTICO (confirmador tardio)
    for date_str, classif in analyses_by_group.get(group_internal_id, []):
        try:
            d = dt.date.fromisoformat(date_str)
        except ValueError:
            continue
        if d < start_default or d > asof:
            continue
        first_data = d if first_data is None else min(first_data, d)
        wk = _monday(d)
        c = classif.upper()
        if "SEM CONVERSA" in c or "SEM DADO" in c:
            sem[wk] += 1
        else:
            conv[wk] += 1
            is_crit = c.startswith("CR")
            if is_crit or "ATEN" in c:
                neg[wk] += 1
            if is_crit:
                crit_dates.append(d)

    # ancora o início no primeiro dado real (corrige o confound de janela)
    anchor = max(start_default, first_data) if first_data else start_default
    weeks = sorted({w for w in (set(cli_count) | set(sem) | set(conv)) if w >= _monday(anchor)})

    sil_s: list[tuple[dt.date, float]] = []
    neg_s: list[tuple[dt.date, float]] = []
    init_s: list[tuple[dt.date, float]] = []
    len_s: list[tuple[dt.date, float]] = []
    for wk in weeks:
        days = sem[wk] + conv[wk]
        sil_s.append((wk, sem[wk] / days if days else 0.0))
        neg_s.append((wk, neg[wk] / conv[wk] if conv[wk] else 0.0))
        init_s.append((wk, float(cli_count[wk])))
        lens = cli_len[wk]
        len_s.append((wk, sum(lens) / len(lens) if lens else 0.0))

    # --- LAGGING: confirmador de cancelamento (CRÍTICO recente + fala em cancelar) ---
    # Risco direto (não-trajetória): ≥0.60 dispara o override de intenção de saída.
    recent_crit = any(c >= asof - dt.timedelta(days=14) for c in crit_dates)
    older_crit = any(asof - dt.timedelta(days=30) <= c < asof - dt.timedelta(days=14) for c in crit_dates)
    # DOIS gatilhos tardios, com semânticas DIFERENTES no estágio:
    #  - FALA EXPLÍCITA de saída (regex) -> is_exit_signal=True -> "intenção de saída".
    #  - CRÍTICO recente do Gemini (insatisfação grave, ex.: cobrar resposta) -> eleva
    #    risco/alerta, mas NÃO é fala de saída -> teto em "insatisfação ativa".
    if cancel_phrase:
        lagging_risk, lag_key, exit_sig = 0.9, "fala_em_cancelar", True
    elif recent_crit:
        lagging_risk, lag_key, exit_sig = 0.9, "critico_recente", False
    elif older_crit:
        lagging_risk, lag_key, exit_sig = 0.5, "critico_recente", False
    else:
        lagging_risk, lag_key, exit_sig = 0.0, "sinal_tardio", False

    return [
        # silêncio e tom_negativo são frações 0–1 (%dias) com escala absoluta de
        # risco -> blend nível+trajetória (absolute_is_risk). iniciativa e
        # comprimento não têm "normal" absoluto -> puramente relativos ao baseline.
        SignalInput("silencio", "engagement", sil_s, higher_is_worse=True, absolute_is_risk=True),
        SignalInput("iniciativa_cliente", "engagement", init_s, higher_is_worse=False),
        SignalInput("comprimento_msg", "tone", len_s, higher_is_worse=False),
        SignalInput("tom_negativo", "tone", neg_s, higher_is_worse=True, absolute_is_risk=True),
        SignalInput(lag_key, "lagging", [], higher_is_worse=True,
                    direct_risk=lagging_risk, is_exit_signal=exit_sig),
    ]
