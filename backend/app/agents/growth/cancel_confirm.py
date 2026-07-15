"""Confirmador SEMÂNTICO de fala de cancelamento — Claude (Haiku) por mensagem.

Por que existe (15/07/26, validação do Otávio p/ reunião de gestores): a regex
_CANCEL_RE sozinha não distingue cancelar o CONTRATO da assessoria de cancelar
um pedido/campanha/NF do dia a dia ("vou cancelar essa e fazer outra", "pode
cancelar essa campanha", "vou parar o carro"). Na auditoria dos 79 alertas
[auto] da carteira, ~40% eram falso-positivos desse tipo. A regex segue como
FILTRO BARATO (recall); o Claude entra só nos candidatos (precisão).

Contrato:
  - build_confirmer(conn_factory) -> callable | None (None = desligado/sem chave
    -> comportamento regex-only, idêntico ao anterior);
  - confirmer([(msg_id, texto), ...]) -> {msg_id: True/False};
  - cache por msg_id na tabela grw_cancel_llm (LGPD: só o veredito, NUNCA o
    conteúdo da mensagem) — cada mensagem é julgada UMA vez na vida;
  - passa pelo teto mensal (llm_budget); teto estourado ou erro de API ->
    candidato mantido (True) — indisponibilidade não pode esconder churn real.

Desligar: GROWTH_LLM_CANCEL=0 no .env.
"""
from __future__ import annotations

import os
import sys
from typing import Any, Callable

_MODEL = "claude-haiku-4-5-20251001"

_DDL = """CREATE TABLE IF NOT EXISTS grw_cancel_llm (
    msg_id     TEXT PRIMARY KEY,
    is_cancel  BOOLEAN NOT NULL,
    model      TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)"""

_SYSTEM = """Você audita conversas de WhatsApp entre a Integracomm (assessoria de marketplaces:
Mercado Livre, Shopee, Amazon) e seus clientes B2B. Você recebe UMA mensagem enviada pelo CLIENTE
no grupo e responde se ela expressa pedido, decisão ou ameaça de CANCELAR/ENCERRAR/RESCINDIR o
CONTRATO ou SERVIÇO com a assessoria (risco de churn da assessoria).

NÃO é cancelamento do serviço (responda NAO): cancelar/encerrar pedido de venda, compra, anúncio,
campanha, promoção, assinatura de marketplace ou ERP de terceiros (Bling, Tiny, Olist, Magis etc.),
nota fiscal, reunião ou visita; frases operacionais ("vou sair para almoçar", "vou parar o carro",
"não quero mais essa foto"); e desabafos sem intenção de romper com a assessoria.

É cancelamento do serviço (responda SIM) mesmo quando indireto: "não vale a pena continuar",
"pensando seriamente em parar [com o serviço]", "meu jurídico vai quebrar o contrato".

Responda EXATAMENTE uma palavra: SIM ou NAO."""


def _judge_uncached(cli: Any, texto: str) -> tuple[bool, int, int]:
    """(veredito, tokens_in, tokens_out) de UMA mensagem, sem cache."""
    msg = cli.messages.create(
        model=_MODEL, max_tokens=4, temperature=0.0,
        system=[{"type": "text", "text": _SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": texto[:1500]}],
    )
    tin = (msg.usage.input_tokens + (msg.usage.cache_read_input_tokens or 0)
           + (msg.usage.cache_creation_input_tokens or 0))
    resp = next((b.text for b in msg.content if b.type == "text"), "").strip().upper()
    return resp.startswith("SIM"), tin, msg.usage.output_tokens


def build_confirmer(conn_factory: Any) -> Callable[[list[tuple[str, str]]], dict[str, bool]] | None:
    """Confirmador com cache+orçamento, ou None (desligado / sem chave / sem conn)."""
    from ...config import get_settings

    s = get_settings()
    ligado = os.environ.get("GROWTH_LLM_CANCEL", "1").lower() in ("1", "true", "sim")
    if not (ligado and s.anthropic_api_key and conn_factory):
        return None

    def confirmer(candidatos: list[tuple[str, str]]) -> dict[str, bool]:
        out: dict[str, bool] = {}
        if not candidatos:
            return out
        try:
            import anthropic

            from ...llm_budget import LlmBudgetExceeded, ensure_budget, record_usage
            conn = conn_factory()
            try:
                with conn.cursor() as cur:
                    cur.execute(_DDL)
                    cur.execute("SELECT msg_id, is_cancel FROM grw_cancel_llm WHERE msg_id = ANY(%s)",
                                ([mid for mid, _ in candidatos],))
                    out.update({m: bool(v) for m, v in cur.fetchall()})
                conn.commit()
                novos = [(mid, txt) for mid, txt in candidatos if mid not in out]
                if not novos:
                    return out
                ensure_budget(conn)
                cli = anthropic.Anthropic(api_key=s.anthropic_api_key, max_retries=1, timeout=30.0)
                for mid, txt in novos:
                    try:
                        verdict, tin, tout = _judge_uncached(cli, txt)
                    except LlmBudgetExceeded:
                        raise
                    except Exception as e:  # noqa: BLE001 — 1 msg não derruba o lote
                        print(f"  [cancel-llm] falha em {mid}: {type(e).__name__} — mantém regex",
                              file=sys.stderr)
                        out[mid] = True
                        continue
                    record_usage(conn, "growth:cancel_confirm", _MODEL, tin, tout)
                    out[mid] = verdict
                    with conn.cursor() as cur:
                        cur.execute("""INSERT INTO grw_cancel_llm (msg_id, is_cancel, model)
                                       VALUES (%s,%s,%s) ON CONFLICT (msg_id) DO NOTHING""",
                                    (mid, verdict, _MODEL))
                    conn.commit()
            finally:
                conn.close()
        except Exception as e:  # noqa: BLE001 — orçamento/DB/import: mantém regex-only
            print(f"  [cancel-llm] indisponível ({type(e).__name__}: {e}) — mantém regex",
                  file=sys.stderr)
            for mid, _ in candidatos:
                out.setdefault(mid, True)
        return out

    return confirmer
