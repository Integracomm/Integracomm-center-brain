"""Análise de TOM das conversas via Claude (passo 3b) — completa o bloco tone (25%).

Para cada conta, monta a transcrição da janela pré-score (90 dias ou desde a 1ª
mensagem) e pede ao Claude **Sonnet** (volume; escolha do Otávio p/ custo) uma
classificação estruturada:
  - trajetória de tom POR SEMANA: caloroso | neutro | transacional | negativo
  - iniciativa: cliente | equilibrada | equipe
  - temas de insatisfação (sem cancelamento explícito — já é o sinal tardio)

O tom semanal vira uma série de risco 0-1 (`TONE_RISK`) que entra no bloco tone
como sinal `tom_claude` (absolute_is_risk). Custo controlado: thinking desligado,
saída estruturada (json_schema), system prompt cacheado entre contas, transcrição
com teto de tamanho. Uso de tokens é retornado p/ auditoria.
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field

import anthropic

MODEL = "claude-sonnet-5"

# tom -> risco 0-1 (heurística provisória; recalibrar pelo loop de outcomes)
TONE_RISK: dict[str, float] = {
    "caloroso": 0.0,
    "neutro": 0.25,
    "transacional": 0.5,
    "negativo": 0.9,
}

_MAX_MSG_CHARS = 240          # trunca cada mensagem
_MAX_MSGS_PER_WEEK = 18       # amostra por semana (mais recentes primeiro dentro da semana)
_MAX_TRANSCRIPT_CHARS = 48_000

_SYSTEM = """Você analisa conversas de WhatsApp entre a equipe de uma assessoria de \
marketplaces (remetentes marcados EQUIPE) e um cliente (remetentes CLIENTE).

Classifique o TOM do relacionamento em CADA semana listada, considerando sobretudo as \
mensagens do CLIENTE:
- caloroso: colaborativo, positivo, engajado, agradece, compartilha resultados
- neutro: cordial padrão, sem sinal forte em nenhuma direção
- transacional: seco, mínimo, só o operacional, respostas curtas sem engajamento
- negativo: irritação, cobrança, frustração, reclamação, insatisfação

Avalie também:
- iniciativa: quem puxa a conversa — "cliente" (procura ativamente), "equilibrada", \
ou "equipe" (só a equipe puxa; cliente apenas responde)
- temas_insatisfacao: temas CONCRETOS de insatisfação mencionados (ex.: demora de \
resposta, atrasos de entrega, resultado fraco de vendas, preço/custo, erro operacional). \
NÃO inclua menções a cancelar/encerrar contrato — isso é capturado por outro sinal. \
Lista vazia se não houver.

Semana sem mensagens suficientes: use o contexto adjacente ou "neutro". Responda \
somente o JSON pedido."""

_SCHEMA = {
    "type": "object",
    "properties": {
        "semanas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "semana": {"type": "string", "description": "segunda-feira da semana, YYYY-MM-DD"},
                    "tom": {"type": "string", "enum": ["caloroso", "neutro", "transacional", "negativo"]},
                },
                "required": ["semana", "tom"],
                "additionalProperties": False,
            },
        },
        "iniciativa": {"type": "string", "enum": ["cliente", "equilibrada", "equipe"]},
        "temas_insatisfacao": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["semanas", "iniciativa", "temas_insatisfacao"],
    "additionalProperties": False,
}


@dataclass
class ToneAnalysis:
    weeks: list[tuple[dt.date, str]]          # (segunda-feira, tom)
    iniciativa: str
    temas: list[str]
    tokens_in: int
    tokens_out: int
    window_start: dt.date
    window_end: dt.date
    n_msgs: int
    raw: dict = field(repr=False, default_factory=dict)

    def series(self) -> list[tuple[dt.date, float]]:
        """Série semanal de risco 0-1 (tom -> TONE_RISK), p/ SignalInput tom_claude."""
        return [(wk, TONE_RISK.get(tom, 0.25)) for wk, tom in sorted(self.weeks)]


def _monday(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=d.weekday())


def build_transcript(reader, group_id: str, asof: dt.date,
                     window_days: int = 90) -> tuple[str, list[dt.date], dt.date, int] | None:
    """Transcrição compacta da janela (asof-90d .. asof), agrupada por semana.
    Retorna (texto, semanas, inicio_real, n_msgs) ou None se não houver mensagens."""
    start_default = asof - dt.timedelta(days=window_days)
    start_dt = dt.datetime.combine(start_default, dt.time.min, tzinfo=dt.timezone.utc)
    by_week: dict[dt.date, list[str]] = {}
    first: dt.date | None = None
    n = 0
    for m in reader.iter_messages(group_id=group_id, window_start=start_dt, order="desc"):
        if not m.received_at:
            continue
        d = m.received_at.date()
        if d < start_default or d > asof:
            continue
        first = d if first is None else min(first, d)
        txt = (m.message_text or m.audio_transcription or "").strip()
        if not txt:
            continue
        who = "EQUIPE" if (m.sender_name and "INTEGRACOMM" in m.sender_name.upper()) else "CLIENTE"
        wk = _monday(d)
        bucket = by_week.setdefault(wk, [])
        if len(bucket) < _MAX_MSGS_PER_WEEK:  # desc: mantém as mais recentes da semana
            bucket.append(f"[{d.isoformat()}] {who}: {txt[:_MAX_MSG_CHARS]}")
            n += 1
    if not by_week:
        return None
    weeks = sorted(by_week)
    parts = [f"Janela analisada: {max(start_default, first or start_default)} a {asof}.",
             "Semanas a classificar: " + ", ".join(w.isoformat() for w in weeks), ""]
    for wk in weeks:
        parts.append(f"--- semana {wk.isoformat()} ---")
        parts.extend(reversed(by_week[wk]))  # ordem cronológica dentro da semana
        parts.append("")
    text = "\n".join(parts)
    if len(text) > _MAX_TRANSCRIPT_CHARS:
        text = text[:_MAX_TRANSCRIPT_CHARS] + "\n[transcrição truncada]"
    return text, weeks, max(start_default, first or start_default), n


def analyze_tone(client: anthropic.Anthropic, transcript: str, weeks: list[dt.date],
                 window_start: dt.date, window_end: dt.date, n_msgs: int) -> ToneAnalysis:
    """Uma chamada ao Sonnet (thinking off, saída estruturada, system cacheado)."""
    resp = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        thinking={"type": "disabled"},  # classificação em volume — sem thinking p/ custo
        system=[{"type": "text", "text": _SYSTEM,
                 "cache_control": {"type": "ephemeral"}}],  # prefixo idêntico entre contas
        output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
        messages=[{"role": "user", "content": transcript}],
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("análise recusada pelos classificadores (refusal)")
    text = next(b.text for b in resp.content if b.type == "text")
    data = json.loads(text)
    parsed_weeks: list[tuple[dt.date, str]] = []
    valid = set(w.isoformat() for w in weeks)
    for item in data.get("semanas", []):
        try:
            wk = dt.date.fromisoformat(item["semana"])
        except (ValueError, KeyError):
            continue
        if wk.isoformat() in valid or _monday(wk).isoformat() in valid:
            parsed_weeks.append((_monday(wk), item["tom"]))
    return ToneAnalysis(
        weeks=parsed_weeks,
        iniciativa=data.get("iniciativa", "equilibrada"),
        temas=[t for t in data.get("temas_insatisfacao", []) if isinstance(t, str)][:8],
        tokens_in=resp.usage.input_tokens + (resp.usage.cache_read_input_tokens or 0)
        + (resp.usage.cache_creation_input_tokens or 0),
        tokens_out=resp.usage.output_tokens,
        window_start=window_start, window_end=window_end, n_msgs=n_msgs,
        raw=data,
    )
