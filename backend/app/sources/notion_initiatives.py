"""Iniciativas por área ← Notion (área de Operações; réplica fiel da lógica do
app Lovable "Metas e Iniciativas" — src/lib/initiatives.functions.ts, lida em
13/07/26). Integração DIRETA com a API do Notion (sem gateway do Lovable):
NOTION_API_KEY no .env + cada database compartilhada manualmente com a
integração pelo Otávio. Somente leitura — nunca escreve de volta no Notion.

Sync = substituição total do cache da área+trimestre (sem upsert incremental).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
from typing import Any

import httpx

_BASE = "https://api.notion.com/v1"
_VER = "2022-06-28"
_PREFER = re.compile(r"^\s*iniciativas?\b", re.I)
_EXCLUI = re.compile(r"proposta|extra", re.I)

DDL = """
CREATE TABLE IF NOT EXISTS notion_config (
    area TEXT NOT NULL, year INT NOT NULL, quarter INT NOT NULL,
    database_id TEXT, database_name TEXT,
    PRIMARY KEY (area, year, quarter));
CREATE TABLE IF NOT EXISTS notion_initiatives_cache (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    notion_id TEXT NOT NULL, area TEXT NOT NULL, year INT NOT NULL, quarter INT NOT NULL,
    titulo TEXT, responsaveis_json JSONB, prazo DATE,
    status TEXT, progresso NUMERIC, notion_url TEXT, subitems_json JSONB,
    iniciativa TEXT, acao TEXT, detalhamento TEXT, gestor TEXT);
CREATE INDEX IF NOT EXISTS idx_notion_init_atq ON notion_initiatives_cache(area, year, quarter);
CREATE TABLE IF NOT EXISTS notion_sync_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    area TEXT, year INT, quarter INT, ok BOOLEAN, items_count INT, message TEXT,
    created_at TIMESTAMPTZ DEFAULT now());
"""


def _key() -> str:
    k = (os.environ.get("NOTION_API_KEY") or "").strip().strip('"')
    if not k:
        raise RuntimeError("NOTION_API_KEY ausente no .env — crie a integração em "
                           "notion.so/my-integrations e compartilhe as databases com ela")
    return k


def _nfetch(path: str, body: dict | None = None, method: str = "POST") -> dict:
    r = httpx.request(method, f"{_BASE}{path}",
                      headers={"Authorization": f"Bearer {_key()}", "Notion-Version": _VER,
                               "Content-Type": "application/json"},
                      json=body, timeout=60)
    r.raise_for_status()
    return r.json()


def normalize_id(raw: str) -> str | None:
    m = re.search(r"([a-f0-9]{32})", raw or "", re.I)
    if not m:
        m2 = re.search(r"([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})", raw or "", re.I)
        return m2.group(1) if m2 else None
    h = m.group(1)
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


def _children(block_id: str) -> list[dict]:
    out: list[dict] = []
    cursor = None
    for _ in range(10):
        qs = f"?start_cursor={cursor}&page_size=100" if cursor else "?page_size=100"
        data = _nfetch(f"/blocks/{block_id}/children{qs}", method="GET")
        out += data.get("results") or []
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return out


def _collect_dbs_in_page(page_id: str, depth: int, gestor: str | None) -> list[dict]:
    """DFS até 3 níveis por child_database "Iniciativas"; o título da 1ª subpágina
    no caminho vira o `gestor` (igual à referência)."""
    if depth > 3:
        return []
    out: list[dict] = []
    try:
        children = _children(page_id)
    except Exception:  # noqa: BLE001
        return out
    for b in children:
        if b.get("type") == "child_database":
            titulo = (b.get("child_database") or {}).get("title") or ""
            if _PREFER.search(titulo) and not _EXCLUI.search(titulo):
                out.append({"id": b["id"], "title": titulo, "gestor": gestor})
        if b.get("type") == "child_page":
            sub = ((b.get("child_page") or {}).get("title") or "").strip()
            out += _collect_dbs_in_page(b["id"], depth + 1, gestor or (sub or None))
    return out


def collect_initiative_dbs(raw_id: str) -> list[dict]:
    """ID/URL (database OU página) → lista de databases Iniciativas [{id,title,gestor}]."""
    nid = normalize_id(raw_id)
    if not nid:
        return []
    try:
        db = _nfetch(f"/databases/{nid}", method="GET")
        if db.get("object") == "database":
            t = "".join(x.get("plain_text", "") for x in db.get("title") or []).strip()
            found = [{"id": db["id"], "title": t or "(sem título)", "gestor": None}]
            parent = db.get("parent") or {}
            if parent.get("type") == "page_id":  # irmãs na mesma página (subpáginas por gestor)
                norm = lambda x: x.replace("-", "").lower()  # noqa: E731
                for s in _collect_dbs_in_page(parent["page_id"], 0, None):
                    if not any(norm(f["id"]) == norm(s["id"]) for f in found):
                        found.append(s)
            return found
    except Exception:  # noqa: BLE001 — não é database: tenta como página
        pass
    return _collect_dbs_in_page(nid, 0, None)


def _query_db(db_id: str) -> list[dict]:
    out: list[dict] = []
    cursor = None
    while True:
        body: dict = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        data = _nfetch(f"/databases/{db_id}/query", body)
        out += data.get("results") or []
        if not data.get("has_more"):
            return out
        cursor = data.get("next_cursor")


def _txt(prop: dict | None) -> str:
    if not prop:
        return ""
    for k in ("title", "rich_text"):
        if isinstance(prop.get(k), list):
            return "".join(t.get("plain_text", "") for t in prop[k]).strip()
    for k in ("select", "status"):
        if (prop.get(k) or {}).get("name"):
            return prop[k]["name"]
    return ""


def status_from_name(name: str) -> str | None:
    n = (name or "").lower().strip()
    if not n:
        return None
    if re.search(r"not.?started|n[aã]o.?iniciad|aguard|todo|pending|backlog", n):
        return "nao_iniciada"
    if re.search(r"conclu|done|finaliz|complet", n):
        return "concluida"
    if re.search(r"atras|delay|late|bloq", n):
        return "atrasada"
    if re.search(r"anda|progres|doing|in.?progress", n):
        return "em_andamento"
    return None


def _parse_page(page: dict) -> dict:
    props = page.get("properties") or {}
    titulo, prazo, responsaveis = "", None, []
    concluida, progresso, status_name = False, None, None
    for key, v in props.items():
        t = v.get("type")
        if t == "title":
            titulo = _txt(v)
        elif t == "date" and (v.get("date") or {}).get("start"):
            prazo = v["date"]["start"][:10]
        elif t == "people" and isinstance(v.get("people"), list):
            responsaveis = [p.get("name") for p in v["people"] if p.get("name")]
        elif t == "multi_select" and re.search(r"respons|owner|gestor", key, re.I):
            responsaveis = [m.get("name") for m in v.get("multi_select") or []]
        elif t in ("status", "select"):
            nome = ((v.get("status") or v.get("select")) or {}).get("name") or ""
            status_name = nome or None
            if re.search(r"conclu|done|finaliz", nome, re.I):
                concluida = True
        elif t == "checkbox" and re.search(r"conclu|done|feito", key, re.I):
            concluida = bool(v.get("checkbox"))
        elif t == "number" and re.search(r"progres|%", key, re.I):
            progresso = v.get("number")
    return {
        "titulo": titulo, "responsaveis": responsaveis, "prazo": prazo,
        "concluida": concluida, "progresso": progresso, "status_name": status_name,
        "iniciativa": _txt(props.get("Iniciativa")) or None,
        "acao": _txt(props.get("Ações")) or _txt(props.get("Acoes")) or _txt(props.get("Ação")) or None,
        "detalhamento": _txt(props.get("Detalhamento do escopo")) or _txt(props.get("Detalhamento")) or None,
        "gestor": titulo or (responsaveis[0] if responsaveis else None),
    }


def _subitems(page_id: str) -> list[dict]:
    try:
        subs = []
        for b in _children(page_id):
            if b.get("type") == "child_page":
                subs.append({"titulo": (b.get("child_page") or {}).get("title") or "",
                             "responsavel": None, "prazo": None, "status": None})
            if b.get("type") == "to_do":
                txt = "".join(t.get("plain_text", "") for t in (b["to_do"].get("rich_text") or []))
                if txt:
                    subs.append({"titulo": txt, "responsavel": None, "prazo": None,
                                 "status": "concluida" if b["to_do"].get("checked") else "em_andamento"})
        return subs
    except Exception:  # noqa: BLE001
        return []


def set_config(conn: Any, area: str, year: int, quarter: int, raw_url: str | None) -> dict:
    """Salva a URL/ID da página do trimestre da área (resolve e valida)."""
    with conn.cursor() as cur:
        cur.execute(DDL)
    db_id = db_name = None
    if raw_url:
        nid = normalize_id(raw_url)
        if not nid:
            return {"ok": False, "message": "URL/ID inválido — não encontrei um ID de 32 caracteres."}
        try:
            dbs = collect_initiative_dbs(raw_url)
            db_id = nid
            db_name = (" + ".join((f"{d['gestor']}/{d['title'] or 'Iniciativas'}" if d["gestor"]
                                   else d["title"] or "(sem título)") for d in dbs)
                       if dbs else "(não validado — compartilhe a página com a integração)")
        except Exception as e:  # noqa: BLE001
            db_id, db_name = nid, f"(não validado: {type(e).__name__})"
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO notion_config (area, year, quarter, database_id, database_name)
                       VALUES (%s,%s,%s,%s,%s) ON CONFLICT (area, year, quarter)
                       DO UPDATE SET database_id=EXCLUDED.database_id, database_name=EXCLUDED.database_name""",
                    (area, year, quarter, db_id, db_name))
    return {"ok": True, "database_id": db_id, "name": db_name}


def sync_initiatives(conn: Any, year: int, quarter: int, area: str | None = None) -> dict:
    """Sincroniza Notion → cache (substituição total por área+trimestre)."""
    with conn.cursor() as cur:
        cur.execute(DDL)
        q = "SELECT area, database_id FROM notion_config WHERE year=%s AND quarter=%s"
        args = [year, quarter]
        if area:
            q += " AND area=%s"
            args.append(area)
        cur.execute(q, args)
        cfgs = cur.fetchall()
    erros, total = [], 0

    def log(ar, ok, n, msg):
        with conn.cursor() as cur:
            cur.execute("INSERT INTO notion_sync_log (area, year, quarter, ok, items_count, message) "
                        "VALUES (%s,%s,%s,%s,%s,%s)", (ar, year, quarter, ok, n, msg[:400]))

    for ar, db_raw in cfgs:
        try:
            if not db_raw:
                erros.append(f"{ar}: sem database configurado — cole a URL da página do trimestre.")
                log(ar, False, 0, "sem database configurado")
                continue
            dbs = collect_initiative_dbs(db_raw)
            if not dbs:
                # distingue "sem acesso" (404 = página NÃO compartilhada) de "vazia"
                nid = normalize_id(db_raw)
                try:
                    _nfetch(f"/blocks/{nid}/children?page_size=1", method="GET")
                    msg = "página acessível mas SEM database 'Iniciativas' (trimestre ainda vazio?)"
                except httpx.HTTPStatusError as he:
                    msg = ("página NÃO compartilhada com a integração — no Notion: ··· → Conexões → "
                           "adicionar a integração" if he.response.status_code == 404
                           else f"HTTP {he.response.status_code} ao acessar a página")
                erros.append(f"{ar}: {msg}")
                log(ar, False, 0, msg)
                continue
            rows, seen = [], set()
            for db in dbs:
                for p in _query_db(db["id"]):
                    if p["id"] in seen:
                        continue
                    seen.add(p["id"])
                    d = _parse_page(p)
                    rows.append((p["id"], ar, year, quarter,
                                 d["iniciativa"] or d["acao"] or d["titulo"] or "(sem título)",
                                 json.dumps(d["responsaveis"], ensure_ascii=False), d["prazo"],
                                 "concluida" if d["concluida"] else (status_from_name(d["status_name"] or "") or "nao_iniciada"),
                                 d["progresso"], p.get("url"),
                                 json.dumps(_subitems(p["id"]), ensure_ascii=False),
                                 d["iniciativa"], d["acao"], d["detalhamento"],
                                 db["gestor"] or d["gestor"]))
            with conn.cursor() as cur:
                cur.execute("DELETE FROM notion_initiatives_cache WHERE area=%s AND year=%s AND quarter=%s",
                            (ar, year, quarter))
                for r in rows:
                    cur.execute("""INSERT INTO notion_initiatives_cache
                        (notion_id, area, year, quarter, titulo, responsaveis_json, prazo, status,
                         progresso, notion_url, subitems_json, iniciativa, acao, detalhamento, gestor)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", r)
            total += len(rows)
            log(ar, True, len(rows),
                "Sincronizado de " + " + ".join(f"\"{d['title']}\"" for d in dbs) + f" ({len(rows)} itens)")
        except Exception as e:  # noqa: BLE001 — uma área não derruba as demais
            erros.append(f"{ar}: {type(e).__name__}: {str(e)[:120]}")
            log(ar, False, 0, f"{type(e).__name__}: {e}")
    return {"synced": total, "errors": erros}


def sync_all_configured(conn: Any) -> int:
    """Rodada diária: sincroniza TODAS as configs existentes (todos os trimestres).
    Sem NOTION_API_KEY, avisa e não faz nada."""
    if not (os.environ.get("NOTION_API_KEY") or "").strip():
        print("  [notion] NOTION_API_KEY ausente — sync de iniciativas pulado", flush=True)
        return 0
    with conn.cursor() as cur:
        cur.execute(DDL)
        cur.execute("SELECT DISTINCT year, quarter FROM notion_config WHERE database_id IS NOT NULL")
        pares = cur.fetchall()
    n = 0
    for year, quarter in pares:
        n += sync_initiatives(conn, year, quarter)["synced"]
    return n
