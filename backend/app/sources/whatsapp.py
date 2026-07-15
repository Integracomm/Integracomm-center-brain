"""Leitor SOMENTE LEITURA do WhatsApp Connector.

Acesso via edge function `growth-agent-read` (Lovable Cloud) — GET apenas,
autenticada por `GROWTH_AGENT_API_KEY` (NÃO a anon key). Substitui o plano
original de role Postgres RO, já que o projeto roda em Lovable Cloud sem
Supabase Dashboard / connection string.

Endpoints: /whatsapp_groups, /messages, /analyses
Paginação por cursor: ?cursor=...&cursor_id=...&limit=...&order=desc
A resposta traz next_cursor + next_cursor_id para encadear.

LGPD: este é o ÚNICO ponto que toca conteúdo de mensagem (dado sensível). O
restante da casca consome SINAIS DERIVADOS daqui — nada de conteúdo bruto é
persistido no Postgres próprio. Toda leitura é registrada na auditoria.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Iterator

import httpx


@dataclass
class WhatsAppGroup:
    id: str
    whatsapp_group_id: str
    name: str
    is_active: bool
    raw: dict[str, Any]


@dataclass
class WhatsAppMessage:
    id: str
    group_id: str
    sender_name: str | None
    sender_phone: str | None
    message_text: str | None
    message_type: str
    audio_transcription: str | None
    received_at: dt.datetime | None
    raw: dict[str, Any]


@dataclass
class Analysis:
    id: str
    group_id: str
    analysis_date: str
    classification: str
    summary: str | None
    message_count: int | None
    raw: dict[str, Any]


def _parse_dt(v: Any) -> dt.datetime | None:
    if not v:
        return None
    s = str(v).replace("Z", "+00:00")
    try:
        return dt.datetime.fromisoformat(s)
    except ValueError:
        return None


class WhatsAppReader:
    """Cliente HTTP por cursor. Read-only; nunca escreve."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        audit: Any = None,
        run_id: str | None = None,
        client: httpx.Client | None = None,
        page_limit: int = 200,  # group_id pagina por keyset; 200 fica sob o limite de payload (500+ estoura)
    ) -> None:
        # base_url já inclui /growth-agent-read (WHATSAPP_READ_API_URL).
        if not base_url or not api_key:
            raise ValueError("WhatsAppReader requer WHATSAPP_READ_API_URL e WHATSAPP_READ_API_KEY.")
        self._base = base_url.rstrip("/")
        self._headers = {"x-api-key": api_key, "Authorization": f"Bearer {api_key}"}
        self._audit = audit
        self._run_id = run_id
        self._client = client or httpx.Client(timeout=30.0)
        self._page_limit = page_limit

    # -- baixo nível ----------------------------------------------------
    def _url(self, endpoint: str) -> str:
        return f"{self._base}/{endpoint.lstrip('/')}"

    def _get_with_retry(self, endpoint: str, params: dict[str, Any], max_attempts: int = 5) -> httpx.Response:
        """GET com retry em erros transitórios: 429 / 5xx (incl. 546 do gateway) E
        timeouts/erros de rede (ReadTimeout etc.) — um timeout isolado não pode
        derrubar a coleta de uma conta (menos ainda a rodada inteira).
        Backoff 1s→3s→7s→15s: gateway SATURADO (visto 07/07: 500 em série com
        rodada + diagnóstico simultâneos) precisa de folga real, não 3 tiros em 7s."""
        import time

        delay = 1.0
        last: httpx.Response | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                last = self._client.get(self._url(endpoint), headers=self._headers, params=params)
            except httpx.TransportError:  # timeout de leitura/conexão = transitório
                if attempt < max_attempts:
                    time.sleep(delay)
                    delay = delay * 2 + 1
                    continue
                raise
            if last.status_code < 400:
                return last
            if (last.status_code == 429 or last.status_code >= 500) and attempt < max_attempts:
                time.sleep(delay)
                delay = delay * 2 + 1
                continue
            break
        assert last is not None
        last.raise_for_status()
        return last

    def _paginate(
        self,
        endpoint: str,
        *,
        order: str = "desc",
        limit: int | None = None,
        extra_params: dict[str, Any] | None = None,
        stop: Any = None,  # callable(item) -> bool: True interrompe (janela incremental)
    ) -> Iterator[dict[str, Any]]:
        """Encadeia as páginas via next_cursor/next_cursor_id até esgotar ou `stop`."""
        cursor: str | None = None
        cursor_id: str | None = None
        page_limit = limit or self._page_limit
        scope = endpoint
        while True:
            params: dict[str, Any] = {"limit": page_limit, "order": order}
            if cursor is not None:
                params["cursor"] = cursor
            if cursor_id is not None:
                params["cursor_id"] = cursor_id
            if extra_params:
                params.update(extra_params)

            try:
                resp = self._get_with_retry(endpoint, params)
            except httpx.HTTPStatusError as e:
                # 546/500 PERSISTENTE (retries esgotados) em grupos específicos =
                # payload da página estourou o limite da edge function (grupos com
                # áudios/mensagens longas — BABY GU, ÍNDIA, MARCIO 15/07). Reduzir
                # a página pela metade e repetir a MESMA página resolve; desistir
                # deixava a conta eternamente ilegível.
                if e.response.status_code >= 500 and page_limit > 25:
                    page_limit = max(25, page_limit // 2)
                    continue
                raise
            body = resp.json()
            items = body.get("data") or body.get("items") or body.get("rows") or []

            if self._audit is not None:
                self._audit.record_read(source="whatsapp", scope=f"{scope}:{cursor or 'start'}", run_id=self._run_id)

            for item in items:
                if stop is not None and stop(item):
                    return
                yield item

            cursor = body.get("next_cursor")
            cursor_id = body.get("next_cursor_id")
            if not items or cursor is None:
                return
            # espaçamento entre páginas: alivia o gateway quando leitores
            # concorrem (rodada + sentinela + diagnóstico) — custo ~1-2min
            # numa rodada completa, contra a saturação vista em 07/07
            import time
            time.sleep(0.15)

    # -- alto nível -----------------------------------------------------
    def iter_groups(self) -> Iterator[WhatsAppGroup]:
        for r in self._paginate("whatsapp_groups", order="asc"):
            yield WhatsAppGroup(
                id=str(r.get("id")),
                whatsapp_group_id=str(r.get("whatsapp_group_id") or ""),
                name=r.get("name") or "",
                is_active=bool(r.get("is_active", True)),
                raw=r,
            )

    def iter_messages(
        self,
        *,
        group_id: str | None = None,
        window_start: dt.datetime | None = None,
        order: str = "desc",
    ) -> Iterator[WhatsAppMessage]:
        """Lê mensagens por cursor. `group_id` filtra por grupo (server-side);
        com order=desc + window_start, para ao cruzar a janela."""

        def _stop(item: dict[str, Any]) -> bool:
            if window_start is None or order != "desc":
                return False
            ts = _parse_dt(item.get("received_at"))
            return ts is not None and ts < window_start

        extra = {"group_id": group_id} if group_id else None
        for r in self._paginate("messages", order=order, extra_params=extra, stop=_stop):
            yield WhatsAppMessage(
                id=str(r.get("id")),
                group_id=str(r.get("group_id") or ""),
                sender_name=r.get("sender_name"),
                sender_phone=r.get("sender_phone"),
                message_text=r.get("message_text"),
                message_type=r.get("message_type") or "text",
                audio_transcription=r.get("audio_transcription"),
                received_at=_parse_dt(r.get("received_at")),
                raw=r,
            )

    def iter_analyses(self, *, group_id: str | None = None) -> Iterator[Analysis]:
        extra = {"group_id": group_id} if group_id else None
        for r in self._paginate("analyses", order="desc", extra_params=extra):
            yield Analysis(
                id=str(r.get("id")),
                group_id=str(r.get("group_id") or ""),
                analysis_date=str(r.get("analysis_date") or ""),
                classification=r.get("classification") or "",
                summary=r.get("summary"),
                message_count=r.get("message_count"),
                raw=r,
            )

    def close(self) -> None:
        self._client.close()
