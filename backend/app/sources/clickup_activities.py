"""Atividades CONCLUÍDAS por conta/mês — para o relatório mensal de assessoria.

Fonte primária: API oficial do ClickUp (token do .env, lista de assessoria) —
cards de cliente na lista `CLICKUP_LIST_ASSESSORIA`, subtarefas concluídas no
período. Fallback: o MIRROR Supabase da Operação (mesma base já usada pelo
score de execução — `clientes` + `subtarefas` com data_conclusao), para quando
o token estiver inválido/expirado (hoje é o caso: OAUTH_025) ou a API falhar.
A fonte usada vai no payload (`source`) + aviso quando cai no fallback.
"""
from __future__ import annotations

import datetime as dt
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx

from ..config import get_settings
from .mirror import MirrorReader, parse_dt
from .nps_sheets import norm_account

_CLICKUP_BASE = "https://api.clickup.com/api/v2"
_TTL = 600.0
# A lista de assessoria é grande (~10,8 mil tasks, ~108 páginas). É cara de
# baixar (minutos), mas muda devagar — cache mais longo + pré-aquecimento em
# background (prewarm) para que NENHUMA geração de relatório espere pelo download.
_LIST_TTL = 1800.0            # 30 min
_cache: dict[str, tuple[float, Any]] = {}
_cache_lock = threading.Lock()  # evita 2 downloads simultâneos da mesma lista


def _cached(key: str, fn, ttl: float = _TTL):
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < ttl:
        return hit[1]
    val = fn()
    _cache[key] = (time.monotonic(), val)
    return val


# --- caminho 1: API oficial do ClickUp --------------------------------------
def _fetch_list_page(token: str, list_id: str, page: int) -> list[dict]:
    """Uma página da lista; trata 429 com espera+retry. [] se a página é vazia."""
    with httpx.Client(timeout=60.0) as cli:
        for _ in range(6):
            r = cli.get(f"{_CLICKUP_BASE}/list/{list_id}/task",
                        params={"page": page, "subtasks": "true",
                                "include_closed": "true", "archived": "false"},
                        headers={"Authorization": token})
            if r.status_code == 429:
                time.sleep(float(r.headers.get("Retry-After") or 3))
                continue
            r.raise_for_status()
            return r.json().get("tasks", [])
    return []


def _download_list(token: str, list_id: str) -> list[dict]:
    """Baixa a lista inteira com páginas EM PARALELO (pool=8) por lotes até vir
    página curta (fim) — ~3x mais rápido que serial."""
    out: list[dict] = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        page, done = 0, False
        while not done and page < 300:
            batch = list(range(page, page + 8))
            for tasks in ex.map(lambda p: _fetch_list_page(token, list_id, p), batch):
                out.extend(tasks)
                if len(tasks) < 100:  # página curta = última
                    done = True
            page += 8
    return out


def _clickup_list_tasks(token: str, list_id: str) -> list[dict]:
    """Tasks da lista de assessoria. SERVE-STALE: se há QUALQUER valor cacheado,
    devolve na hora (mesmo velho) — o prewarm o mantém fresco em background. Só
    bloqueia p/ baixar quando NÃO há nada em cache (uma vez, no arranque). Assim
    nenhuma geração de relatório espera pelo download de ~10,8 mil tasks."""
    key = f"cu:{list_id}"
    hit = _cache.get(key)
    if hit is not None:
        return hit[1]
    with _cache_lock:  # 1º carregamento — outra thread pode ter aquecido enquanto esperávamos
        hit = _cache.get(key)
        if hit is not None:
            return hit[1]
        out = _download_list(token, list_id)
        _cache[key] = (time.monotonic(), out)
        return out


def _refresh_list(token: str, list_id: str) -> None:
    """Baixa a lista SEM bloquear leitores e troca o valor do cache (+ reconstrói
    o índice derivado). Usado só pelo prewarm."""
    fresh = _download_list(token, list_id)
    _cache[f"cu:{list_id}"] = (time.monotonic(), fresh)
    _cache.pop(f"cu-idx:{list_id}", None)  # força reconstrução do índice na próxima leitura
    _subs_by_norm_raw(token, list_id)      # ...e já reconstrói agora (fora do caminho do usuário)


def _warm_aux() -> None:
    """Aquece os demais caches lidos por relatório (mirror de clientes, planilha
    mestre de NPS, planilha de squads) — para a 1ª geração não pagar nada disso.
    Cada um falha em silêncio se a fonte estiver fora."""
    try:
        _mirror_clientes()
    except Exception:  # noqa: BLE001
        pass
    try:
        from . import nps_sheets as _NPS
        _NPS.master_rows()
    except Exception:  # noqa: BLE001
        pass
    try:
        from . import squads_sheet as _SQ
        _SQ.squad_teams()
    except Exception:  # noqa: BLE001
        pass


def prewarm_clickup() -> None:
    """Aquece a lista de assessoria num thread daemon e a RENOVA periodicamente,
    sem nunca bloquear as requisições (serve-stale). Chamado no startup. Silencioso:
    falhas de API não derrubam o servidor."""
    def loop():
        s = get_settings()
        if not (s.clickup_api_token and s.clickup_list_assessoria):
            return
        while True:
            try:
                _refresh_list(s.clickup_api_token, s.clickup_list_assessoria)
                _warm_aux()  # mirror de clientes, planilha mestre de NPS, squads
            except Exception:  # noqa: BLE001 — best-effort; próxima volta tenta de novo
                time.sleep(120)
                continue
            time.sleep(_LIST_TTL - 300)  # renova a cada ~25 min
    threading.Thread(target=loop, name="clickup-prewarm", daemon=True).start()


def _epoch_iso(ms) -> str | None:
    if not ms:
        return None
    try:
        return dt.datetime.fromtimestamp(int(ms) / 1000, tz=dt.timezone.utc).isoformat()
    except (ValueError, TypeError):
        return None


def _subs_by_norm_raw(token: str, list_id: str) -> dict[str, list[dict]]:
    """Índice DERIVADO e cacheado: nome-base do card → subtarefas cruas (task
    dicts). A resolução de card-raiz sobre ~10 mil tasks roda UMA vez por
    atualização da lista (não por relatório) — o gargalo de CPU que sobrava."""
    def build():
        tasks = _clickup_list_tasks(token, list_id)
        by_id = {t["id"]: t for t in tasks}

        def root_of(t: dict) -> str:
            seen: set[str] = set()
            cur = t
            while cur.get("parent") and cur["parent"] not in seen:
                seen.add(cur["parent"])
                nxt = by_id.get(cur["parent"])
                if not nxt:
                    return cur["parent"]
                cur = nxt
            return cur["id"]

        name_by_root = {t["id"]: (t.get("name") or "") for t in tasks if not t.get("parent")}
        out: dict[str, list[dict]] = {}
        for t in tasks:
            if not t.get("parent"):
                continue
            n = norm_account(name_by_root.get(root_of(t), ""))
            if n:
                out.setdefault(n, []).append(t)
        return out
    return _cached(f"cu-idx:{list_id}", build, ttl=_LIST_TTL)


def api_subs_by_norm() -> dict[str, list[dict]]:
    """Subtarefas por nome-base no MESMO formato do mirror — fonte preferida do
    score de EXECUÇÃO p/ clientes ativos (o mirror cobre só ~51%). Levanta
    exceção se a API estiver indisponível — o chamador decide o fallback."""
    s = get_settings()
    if not (s.clickup_api_token and s.clickup_list_assessoria):
        return {}
    raw = _subs_by_norm_raw(s.clickup_api_token, s.clickup_list_assessoria)
    return {n: [{
        "data_criacao": _epoch_iso(t.get("date_created")),
        "data_conclusao": _epoch_iso(t.get("date_done") or t.get("date_closed")),
        "data_vencimento": _epoch_iso(t.get("due_date")),
        "status": (t.get("status") or {}).get("status"),
        "recorrente": False, "proximo_vencimento": None,
    } for t in subs] for n, subs in raw.items()}


def _mk_item(t: dict, start: dt.datetime, end: dt.datetime) -> dict | None:
    """Task da API -> item de atividade, se CONCLUÍDA dentro do período."""
    done_ms = t.get("date_done") or t.get("date_closed")
    if not done_ms:
        return None
    done = dt.datetime.fromtimestamp(int(done_ms) / 1000, tz=dt.timezone.utc)
    if not (start <= done < end):
        return None
    tags = [g.get("name") for g in (t.get("tags") or []) if g.get("name")]
    assg = ", ".join(a.get("username", "") for a in (t.get("assignees") or [])) or None
    return {"id": t.get("id"), "nome": t.get("name"), "concluida_em": done.date().isoformat(),
            "responsavel": assg, "status": (t.get("status") or {}).get("status"),
            "categoria": (tags[0] if tags else None)}


def _bfs_completed(token: str, root_id: str, start: dt.datetime, end: dt.datetime,
                   skip_ids: set[str], max_nodes: int = 200) -> list[dict]:
    """Varre a ÁRVORE de subtarefas de um card via /task/{id}?include_subtasks=true
    — cobre cards que não estão na lista configurada (ex.: card apontado pelo
    mirror, ou card de assessoria vivendo em outra lista). O root não vira item."""
    out: list[dict] = []
    visited = {root_id}
    frontier = [root_id]
    with httpx.Client(timeout=60.0) as cli:
        while frontier and len(visited) <= max_nodes:
            tid = frontier.pop(0)
            r = cli.get(f"{_CLICKUP_BASE}/task/{tid}",
                        params={"include_subtasks": "true"},
                        headers={"Authorization": token})
            if r.status_code == 401:
                r.raise_for_status()  # token inválido -> aviso específico no chamador
            if r.status_code != 200:
                continue
            t = r.json()
            if tid != root_id and tid not in skip_ids:
                item = _mk_item(t, start, end)
                if item:
                    out.append(item)
            for s2 in (t.get("subtasks") or []):
                sid = s2.get("id")
                if sid and sid not in visited:
                    visited.add(sid)
                    frontier.append(sid)
    return out


def _from_clickup_api(account_name: str, start: dt.datetime, end: dt.datetime) -> list[dict] | None:
    """Duas rotas somadas (dedup por id): (1) lista de assessoria — cards de
    cliente por nome + subtarefas retornadas pela própria lista; (2) card
    apontado pelo mirror (`clientes.clickup_task_id`), que pode viver em OUTRA
    lista (ex.: Clientes Ativos) — varrido por BFS. O caso SOLUTION STORE provou
    que um cliente pode ter cards distintos por lista."""
    s = get_settings()
    if not s.clickup_api_token:
        return None
    token = s.clickup_api_token
    out: list[dict] = []
    known_ids: set[str] = set()

    if s.clickup_list_assessoria:
        # índice derivado (cacheado): subtarefas da conta já atribuídas ao card
        idx = _subs_by_norm_raw(token, s.clickup_list_assessoria)
        subs = idx.get(norm_account(account_name), [])
        known_ids = {t["id"] for lst in idx.values() for t in lst}
        for t in subs:
            item = _mk_item(t, start, end)
            if item:
                out.append(item)

    # rota 2: cards fora da lista configurada (mirror; cards homônimos idem)
    extra_roots: set[str] = set()
    try:
        info = _mirror_clientes().get(norm_account(account_name)) or {}
        if info.get("clickup_task_id"):
            extra_roots.add(info["clickup_task_id"])
    except Exception:  # noqa: BLE001 — mirror fora do ar não bloqueia a rota da API
        pass
    seen_ids = known_ids | {i["id"] for i in out}
    for root in extra_roots:
        if root in known_ids:
            continue  # já coberto pela lista de assessoria
        for item in _bfs_completed(token, root, start, end, skip_ids=seen_ids):
            if item["id"] not in seen_ids:
                seen_ids.add(item["id"])
                out.append(item)

    for i in out:
        i.pop("id", None)
    return out


# --- caminho 2 (fallback): mirror Supabase da Operação ----------------------
def _mirror_creds() -> tuple[str, str]:
    """Mesmas credenciais públicas (anon, read-only) usadas pelo score de
    execução — extraídas do exec_signals.ps1 para não duplicar o segredo."""
    ps1 = (Path(__file__).resolve().parents[2] / "scripts" / "exec_signals.ps1").read_text(encoding="utf-8")
    return (re.search(r'\$base="([^"]+)"', ps1).group(1),
            re.search(r'\$anon="([^"]+)"', ps1).group(1))


def _mirror_clientes() -> dict[str, dict]:
    """{nome_normalizado: cliente} do mirror (id, GC, plano/contrato, equipe)."""
    def load():
        base, anon = _mirror_creds()
        with httpx.Client(timeout=60.0) as cli:
            r = cli.get(f"{base}/clientes",
                        params={"select": "id,nome_cliente,clickup_task_id,gerente_de_contas,contrato,equipe,status",
                                "limit": "10000"},
                        headers={"apikey": anon, "Authorization": f"Bearer {anon}"})
            r.raise_for_status()
            out: dict[str, dict] = {}
            for c in r.json():
                n = norm_account(c.get("nome_cliente"))
                if n and n not in out:
                    out[n] = c
            return out
    return _cached("mirror:clientes", load)


def _from_mirror(account_name: str, start: dt.datetime, end: dt.datetime) -> list[dict] | None:
    cli = _mirror_clientes().get(norm_account(account_name))
    if not cli:
        return None
    base, anon = _mirror_creds()
    rows: list[dict] = []
    with httpx.Client(timeout=60.0) as http:
        offset = 0
        while True:  # PostgREST corta em 1000 linhas/resposta — paginar sempre
            r = http.get(f"{base}/subtarefas",
                         params={"select": "nome_subtarefa,status,responsavel,data_conclusao",
                                 "cliente_id": f"eq.{cli['id']}",
                                 "data_conclusao": f"gte.{start.date().isoformat()}",
                                 "order": "data_conclusao.asc",
                                 "limit": "1000", "offset": str(offset)},
                         headers={"apikey": anon, "Authorization": f"Bearer {anon}"})
            r.raise_for_status()
            page = r.json()
            rows.extend(page)
            if len(page) < 1000:
                break
            offset += 1000
    out = []
    for s in rows:
        done = parse_dt(s.get("data_conclusao"))
        if not done or not (start <= done < end):
            continue
        out.append({"nome": s.get("nome_subtarefa"), "concluida_em": done.date().isoformat(),
                    "responsavel": s.get("responsavel"), "status": s.get("status"),
                    "categoria": None})
    return out


def mirror_client_info(account_name: str) -> dict | None:
    """GC/plano/equipe do mirror — enriquece o cabeçalho quando a planilha não traz."""
    try:
        return _mirror_clientes().get(norm_account(account_name))
    except Exception:  # noqa: BLE001 — enriquecimento é opcional
        return None


def _upcoming_from_clickup(account_name: str, now: dt.datetime, limit: int = 20) -> list[dict] | None:
    """Atividades EM ABERTO com vencimento >= agora, na árvore do card do
    cliente (lista assessoria). None = API não configurada."""
    s = get_settings()
    if not (s.clickup_api_token and s.clickup_list_assessoria):
        return None
    subs = _subs_by_norm_raw(s.clickup_api_token, s.clickup_list_assessoria).get(
        norm_account(account_name), [])
    out = []
    for t in subs:
        if t.get("date_done") or t.get("date_closed") or not t.get("due_date"):
            continue
        due = dt.datetime.fromtimestamp(int(t["due_date"]) / 1000, tz=dt.timezone.utc)
        if due < now - dt.timedelta(days=1):  # vencidas antigas ficam de fora
            continue
        assg = ", ".join(a.get("username", "") for a in (t.get("assignees") or [])) or None
        # dia exibido em BRT (vencimento à noite caía no dia seguinte em UTC)
        out.append({"nome": t.get("name"),
                    "vence_em": due.astimezone(dt.timezone(dt.timedelta(hours=-3))).date().isoformat(),
                    "responsavel": assg, "status": (t.get("status") or {}).get("status")})
    return sorted(out, key=lambda x: x["vence_em"])[:limit]


def _upcoming_from_mirror(account_name: str, now: dt.datetime, limit: int = 20) -> list[dict] | None:
    cli = _mirror_clientes().get(norm_account(account_name))
    if not cli:
        return None
    base, anon = _mirror_creds()
    with httpx.Client(timeout=60.0) as http:
        r = http.get(f"{base}/subtarefas",
                     params={"select": "nome_subtarefa,status,responsavel,data_vencimento,data_conclusao",
                             "cliente_id": f"eq.{cli['id']}", "data_conclusao": "is.null",
                             "data_vencimento": f"gte.{(now - dt.timedelta(days=1)).date().isoformat()}",
                             "order": "data_vencimento.asc", "limit": "1000"},
                     headers={"apikey": anon, "Authorization": f"Bearer {anon}"})
        r.raise_for_status()
        rows = r.json()
    out = []
    for s in rows[:limit]:
        due = parse_dt(s.get("data_vencimento"))
        out.append({"nome": s.get("nome_subtarefa"),
                    "vence_em": due.date().isoformat() if due else None,
                    "responsavel": s.get("responsavel"), "status": s.get("status")})
    return out


def upcoming_activities(account_name: str, now: dt.datetime | None = None) -> dict:
    """Próximas atividades previstas (abertas, com vencimento a partir de hoje)
    — insumo p/ o GC antes da reunião com o cliente. Mesmo contrato de
    completed_activities: {source, aviso|None, tasks}."""
    now = now or dt.datetime.now(dt.timezone.utc)
    aviso = None
    try:
        tasks = _upcoming_from_clickup(account_name, now)
        if tasks is not None:
            return {"source": "clickup_api", "aviso": None, "tasks": tasks}
        aviso = "token/lista ClickUp não configurados — usando espelho da Operação"
    except Exception as e:  # noqa: BLE001 — fallback deliberado p/ o mirror
        status = getattr(getattr(e, "response", None), "status_code", None)
        aviso = ("token ClickUp do .env inválido/expirado — usando espelho da Operação"
                 if status == 401 else
                 f"API ClickUp indisponível ({type(e).__name__}) — usando espelho da Operação")
    try:
        tasks = _upcoming_from_mirror(account_name, now)
    except Exception as e:  # noqa: BLE001
        return {"source": "nenhuma", "tasks": [],
                "aviso": f"{aviso}; espelho também indisponível ({type(e).__name__})"}
    if tasks is None:
        return {"source": "mirror", "tasks": [],
                "aviso": f"{aviso}; conta não encontrada no espelho da Operação"}
    return {"source": "mirror", "aviso": aviso, "tasks": tasks}


def completed_activities(account_name: str, start: dt.datetime, end: dt.datetime) -> dict:
    """Atividades concluídas da conta no período [start, end).
    {source, aviso|None, tasks: [{nome, concluida_em, responsavel, status, categoria}]}"""
    aviso = None
    try:
        tasks = _from_clickup_api(account_name, start, end)
        if tasks is not None:
            return {"source": "clickup_api", "aviso": None,
                    "tasks": sorted(tasks, key=lambda t: t["concluida_em"])}
        aviso = "token/lista ClickUp não configurados — usando espelho da Operação"
    except Exception as e:  # noqa: BLE001 — fallback deliberado p/ o mirror
        status = getattr(getattr(e, "response", None), "status_code", None)
        if status == 401:
            aviso = ("token ClickUp do .env inválido/expirado (a API recusou com 401) — gerar novo "
                     "token pessoal no ClickUp e atualizar CLICKUP_API_TOKEN; usando espelho da Operação "
                     "(mesmos dados do ClickUp, atualizados pelo HUB)")
        else:
            aviso = f"API ClickUp indisponível ({type(e).__name__}) — usando espelho da Operação"
    try:
        tasks = _from_mirror(account_name, start, end)
    except Exception as e:  # noqa: BLE001
        return {"source": "nenhuma", "tasks": [],
                "aviso": f"{aviso}; espelho também indisponível ({type(e).__name__})"}
    if tasks is None:
        return {"source": "mirror", "tasks": [],
                "aviso": f"{aviso}; conta não encontrada no espelho da Operação"}
    return {"source": "mirror", "aviso": aviso,
            "tasks": sorted(tasks, key=lambda t: t["concluida_em"])}
