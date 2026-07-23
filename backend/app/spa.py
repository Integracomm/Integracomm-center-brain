"""Serve o frontend React buildado (frontend/dist) — migração rota a rota.

Desenho (aprovado no plano do redesenho, Otávio 21/07):
  - Assets em /spa/* (base do Vite). As ROTAS de tela continuam no domínio
    raiz: cada rota MIGRADA passa a devolver o index.html do SPA; as demais
    seguem no HTML server-side. Mesma origem -> cookie `iasession` intacto,
    zero CORS.
  - Chaveamento: /app (vitrine da biblioteca) é sempre do SPA; as telas
    migradas entram em SPA_ROUTES (env, csv — ex.: "/growth,/prevendas")
    conforme os lotes são validados e deployados.
  - Sem build (dist ausente): as rotas do SPA avisam em vez de 500 — o
    painel HTML continua funcionando normalmente.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def spa_routes() -> list[str]:
    extra = [p.strip() for p in os.environ.get("SPA_ROUTES", "").split(",")
             if p.strip().startswith("/")]
    return ["/app", *extra]


def _index(request: Request):
    from . import api as A
    if not A._session(request):
        return RedirectResponse("/login", status_code=302)
    idx = _DIST / "index.html"
    if not idx.exists():
        return HTMLResponse(
            "<p style='font-family:sans-serif;padding:40px'>Frontend novo sem build nesta máquina — "
            "rode <code>bun run build</code> em frontend/ (o painel HTML continua em <a href='/'>/</a>).</p>",
            status_code=503)
    return FileResponse(idx, media_type="text/html")


def view_response(request: Request, area: str, view: str):
    """Chaveamento por VIEW dentro de uma área (?view=): devolve a resposta do
    SPA se aquela view estiver migrada+habilitada, senão None (segue o HTML).
    Habilitação por env SPA_<AREA>_VIEWS (csv) — ex.: SPA_GROWTH_VIEWS=
    "contas,alertas,cancelamentos". Vazio (padrão) = tudo no HTML; o flip por
    ambiente permite validar local sem tocar produção."""
    # ESCOTILHA `?legado=1` (Lote 6): força a tela ANTIGA mesmo com a view
    # migrada. Existe porque uma tela pode ter um sub-fluxo ainda não portado
    # (ex.: a geração em lote do Relatório de Assessoria) — sem isso, ligar a
    # flag tornaria esse fluxo inacessível. É uma ponte, não um destino: cada
    # uso é uma pendência registrada.
    if request.query_params.get("legado"):
        return None
    habilitadas = {v.strip() for v in
                   os.environ.get(f"SPA_{area.upper()}_VIEWS", "").split(",") if v.strip()}
    if view not in habilitadas:
        return None
    _audita(request, f"{area}/{view}")
    return _index(request)


def _audita(request: Request, scope: str) -> None:
    """Registra a abertura da tela no audit_log.

    Cada handler chamava `_audit_view` DEPOIS do chaveamento do SPA, então toda
    view migrada parou de contar acesso — a tela de permissões passou a mostrar
    gestores com 0 acessos (22/07). Aqui é o ponto único por onde passam todas
    as views migradas, então o registro volta a valer para todas de uma vez."""
    from . import api as A
    try:
        s = A._session(request)
        if not s:
            return
        with A._conn() as c:
            A._audit_view(c, s[0], scope=scope)
    except Exception:  # noqa: BLE001 — auditoria nunca derruba a tela
        pass


def install(app) -> None:
    """Monta assets e registra as rotas migradas. Chamado pelo api.py."""
    if _DIST.exists():
        from fastapi.staticfiles import StaticFiles
        app.mount("/spa", StaticFiles(directory=_DIST), name="spa")
    for path in spa_routes():
        # rota migrada entrega o index do SPA; o router client-side assume
        app.add_api_route(path, _index, methods=["GET"], include_in_schema=False)
        app.add_api_route(path + "/{resto:path}", _index, methods=["GET"],
                          include_in_schema=False)
