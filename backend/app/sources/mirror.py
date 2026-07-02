"""Leitor read-only do mirror Supabase da Operação (ClickUp) — `vhflfvdfjhncfioncwpl`.

Fonte da EXECUÇÃO/entrega: a tabela `subtarefas` retém datas reais (2023→2026),
o que permite reconstruir a saúde de execução AS-OF-DATE (sem vazamento: só o que
existia até a data). `clientes` traz serviço/venda/onboarding p/ o porte fiel
(`execution_score.compute_execution_score`). Anon key pública por design (mesma
do código-fonte do HUB); acesso somente leitura. Toda leitura é auditável.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Iterator

import httpx


def parse_dt(v: Any) -> dt.datetime | None:
    if not v:
        return None
    try:
        d = dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)
    except (ValueError, TypeError):
        return None


@dataclass
class ClienteRow:
    id: str
    nome_cliente: str | None
    servico: str | None
    data_venda: dt.datetime | None
    data_onboarding: dt.datetime | None
    status: str | None
    valor_assessoria: float | None  # MRR (priorização/receita)


class MirrorReader:
    def __init__(self, base_url: str, anon_key: str, *, client: httpx.Client | None = None,
                 audit: Any = None, run_id: str | None = None) -> None:
        if not base_url or not anon_key:
            raise ValueError("MirrorReader requer base_url e anon_key.")
        self._base = base_url.rstrip("/")
        self._h = {"apikey": anon_key, "Authorization": f"Bearer {anon_key}"}
        self._client = client or httpx.Client(timeout=60.0)
        self._audit = audit
        self._run_id = run_id

    def _get(self, path: str, params: dict[str, Any], scope: str) -> list[dict]:
        """GET paginado: o PostgREST do mirror corta TODA resposta em 1000 linhas
        (mesmo com limit maior) — sem offset, lotes grandes vinham truncados em
        silêncio (afetava o score de execução). Pagina até a página vir curta."""
        out: list[dict] = []
        offset = 0
        while True:
            p = dict(params, limit="1000", offset=str(offset))
            r = self._client.get(f"{self._base}/{path}", headers=self._h, params=p)
            r.raise_for_status()
            rows = r.json()
            out.extend(rows)
            if len(rows) < 1000:
                break
            offset += 1000
        if self._audit is not None:
            self._audit.record_read(source="clickup_mirror", scope=scope, run_id=self._run_id)
        return out

    def clientes(self) -> list[ClienteRow]:
        rows = self._get(
            "clientes",
            {"select": "id,nome_cliente,servico,data_venda,data_onboarding,status,valor_assessoria",
             "limit": "10000"},
            "clientes",
        )
        return [
            ClienteRow(
                id=r["id"], nome_cliente=r.get("nome_cliente"), servico=r.get("servico"),
                data_venda=parse_dt(r.get("data_venda")),
                data_onboarding=parse_dt(r.get("data_onboarding")),
                status=r.get("status"),
                valor_assessoria=(float(r["valor_assessoria"]) if r.get("valor_assessoria") else None),
            )
            for r in rows
        ]

    def subtarefas_by_cliente(self, cliente_ids: list[str], *, chunk: int = 40) -> dict[str, list[dict]]:
        """Subtarefas (cru) por cliente_id, em lotes. Campos p/ o porte fiel +
        data_criacao (guarda anti-vazamento as-of)."""
        out: dict[str, list[dict]] = {}
        ids = sorted(set(cliente_ids))
        sel = "cliente_id,status,data_vencimento,data_conclusao,recorrente,proximo_vencimento,data_criacao"
        for i in range(0, len(ids), chunk):
            group = ids[i:i + chunk]
            rows = self._get(
                "subtarefas",
                {"select": sel, "cliente_id": f"in.({','.join(group)})", "limit": "20000"},
                f"subtarefas:{i//chunk}",
            )
            for s in rows:
                out.setdefault(s["cliente_id"], []).append(s)
        return out

    def close(self) -> None:
        self._client.close()
