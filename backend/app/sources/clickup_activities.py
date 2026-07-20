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
    _cache.pop(f"cu-idx:{list_id}", None)    # força reconstrução dos índices na próxima leitura
    _cache.pop(f"cu-roots:{list_id}", None)
    _subs_by_norm_raw(token, list_id)        # ...e já reconstrói agora (fora do caminho do usuário)
    _roots_by_norm(token, list_id)


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
                for lst in _report_lists(s):
                    _refresh_list(s.clickup_api_token, lst)
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


def _roots_by_norm(token: str, list_id: str) -> dict[str, set[str]]:
    """Índice derivado (cacheado): nome-base → ids dos CARDS-raiz da lista.
    Usado p/ pular o BFS quando o card do mirror já está numa lista indexada
    (o BFS pagava 1 GET por subtarefa — 97s no caso RADIADORES)."""
    def build():
        tasks = _clickup_list_tasks(token, list_id)
        out: dict[str, set[str]] = {}
        for t in tasks:
            if not t.get("parent"):
                n = norm_account(t.get("name") or "")
                if n:
                    out.setdefault(n, set()).add(t["id"])
        return out
    return _cached(f"cu-roots:{list_id}", build, ttl=_LIST_TTL)


def _subs_lookup(token: str, list_id: str, n: str) -> list[dict]:
    """Subtarefas da conta no índice, com fallback por INCLUSÃO do nome-base:
    cards de serviço são nomeados com prefixo ('Configuração de Sistema
    (UpSeller) - CEREJA CHIC MODAS') e escapavam do match exato — caso real
    CEREJA CHIC 15/07 (o relatório só via o card da lista Clientes Ativos)."""
    idx = _subs_by_norm_raw(token, list_id)
    out = {t["id"]: t for t in idx.get(n, [])}
    if len(n) >= 6:
        for k, subs in idx.items():
            if k != n and n in k:
                for t in subs:
                    out.setdefault(t["id"], t)
    return list(out.values())


def _roots_lookup(token: str, list_id: str, n: str) -> set[str]:
    """Ids dos cards-raiz da conta (exato + inclusão do nome-base)."""
    idx = _roots_by_norm(token, list_id)
    out = set(idx.get(n, set()))
    if len(n) >= 6:
        for k, roots in idx.items():
            if k != n and n in k:
                out |= roots
    return out


def _report_lists(s) -> list[str]:
    """Listas indexadas p/ relatório: assessoria + clientes ativos (cards de
    cliente podem viver em qualquer uma — caso SOLUTION STORE/RADIADORES)."""
    return [lst for lst in (s.clickup_list_assessoria, s.clickup_list_clientes_ativos) if lst]


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


def _bfs_nodes(token: str, root_id: str, max_nodes: int = 200) -> list[tuple[str, dict]]:
    """Varre a ÁRVORE de subtarefas de um card via /task/{id}?include_subtasks=true
    e devolve os nós CRUS [(id, task)]. É a rota cara (1 GET por nó, sob rate
    limit do ClickUp — 97s no caso RADIADORES), então o resultado é CACHEADO
    por 30min; o filtro por período fica no chamador."""
    def scan():
        nodes: list[tuple[str, dict]] = []
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
                if tid != root_id:
                    nodes.append((tid, t))
                for s2 in (t.get("subtasks") or []):
                    sid = s2.get("id")
                    if sid and sid not in visited:
                        visited.add(sid)
                        frontier.append(sid)
        return nodes
    return _cached(f"cu-bfs:{root_id}", scan, ttl=_LIST_TTL)


def _bfs_completed(token: str, root_id: str, start: dt.datetime, end: dt.datetime,
                   skip_ids: set[str], max_nodes: int = 200) -> list[dict]:
    """Itens concluídos no período dentro da árvore do card (nós via _bfs_nodes,
    cacheado). O root não vira item."""
    out: list[dict] = []
    for tid, t in _bfs_nodes(token, root_id, max_nodes):
        if tid in skip_ids:
            continue
        item = _mk_item(t, start, end)
        if item:
            out.append(item)
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
    known_roots: set[str] = set()

    # rota 1: listas INDEXADAS (assessoria + clientes ativos) — cards de cliente
    # por nome (exato + inclusão do nome-base) + subtarefas da própria lista
    vistos_ids: set[str] = set()
    for lst in _report_lists(s):
        idx = _subs_by_norm_raw(token, lst)
        known_ids |= {t["id"] for sub in idx.values() for t in sub}
        for roots in _roots_by_norm(token, lst).values():
            known_roots |= roots
        for t in _subs_lookup(token, lst, norm_account(account_name)):
            if t["id"] in vistos_ids:
                continue  # card presente nas duas listas
            vistos_ids.add(t["id"])
            item = _mk_item(t, start, end)
            if item:
                out.append(item)

    # rota 2 (último recurso): card do mirror FORA das listas indexadas — BFS
    # nó a nó (1 GET/subtarefa, caro: rate limit do ClickUp), com cache de 30min
    extra_roots: set[str] = set()
    try:
        info = _mirror_clientes().get(norm_account(account_name)) or {}
        if info.get("clickup_task_id"):
            extra_roots.add(info["clickup_task_id"])
    except Exception:  # noqa: BLE001 — mirror fora do ar não bloqueia a rota da API
        pass
    seen_ids = known_ids | {i["id"] for i in out}
    for root in extra_roots:
        if root in known_ids or root in known_roots:
            continue  # já coberto por lista indexada
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
    subs, vistos = [], set()
    for lst in _report_lists(s):
        for t in _subs_lookup(s.clickup_api_token, lst, norm_account(account_name)):
            if t["id"] not in vistos:
                vistos.add(t["id"])
                subs.append(t)
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


def card_url(account_name: str) -> str | None:
    """URL do card-raiz do cliente no ClickUp (conferência rápida da execução —
    pedido Otávio 15/07). Preferência: card na lista de assessoria (é o card de
    execução); fallback: card apontado pelo mirror. None = não localizado."""
    s = get_settings()
    n = norm_account(account_name)
    try:
        if s.clickup_api_token:
            for lst in _report_lists(s):
                roots = _roots_lookup(s.clickup_api_token, lst, n)
                if roots:
                    return f"https://app.clickup.com/t/{sorted(roots)[0]}"
    except Exception:  # noqa: BLE001 — link é conveniência, nunca derruba a página
        pass
    try:
        cli = _mirror_clientes().get(n) or {}
        if cli.get("clickup_task_id"):
            return f"https://app.clickup.com/t/{cli['clickup_task_id']}"
    except Exception:  # noqa: BLE001
        pass
    return None


def _overdue_from_clickup(account_name: str, now: dt.datetime, limit: int = 20) -> list[dict] | None:
    """Atividades ABERTAS com vencimento JÁ VENCIDO (a cobrança do gestor) —
    complementa as 'próximas': tarefa vencida não é próxima nem concluída e
    ficava invisível no relatório (caso D LA BELLA 15/07: 'Configuração de
    Sistema' urgente vencida em 30/06 não aparecia). None = API não configurada."""
    s = get_settings()
    if not (s.clickup_api_token and s.clickup_list_assessoria):
        return None
    subs, vistos = [], set()
    for lst in _report_lists(s):
        for t in _subs_lookup(s.clickup_api_token, lst, norm_account(account_name)):
            if t["id"] not in vistos:
                vistos.add(t["id"])
                subs.append(t)
    out = []
    for t in subs:
        if t.get("date_done") or t.get("date_closed") or not t.get("due_date"):
            continue
        due = dt.datetime.fromtimestamp(int(t["due_date"]) / 1000, tz=dt.timezone.utc)
        if due >= now - dt.timedelta(days=1):
            continue  # futuras/de hoje ficam nas 'próximas'
        assg = ", ".join(a.get("username", "") for a in (t.get("assignees") or [])) or None
        out.append({"nome": t.get("name"),
                    "vence_em": due.astimezone(dt.timezone(dt.timedelta(hours=-3))).date().isoformat(),
                    "dias_atraso": (now - due).days,
                    "responsavel": assg, "status": (t.get("status") or {}).get("status"),
                    # link direto da TAREFA (drill-down dos squads, Otávio 16/07)
                    "url": t.get("url") or f"https://app.clickup.com/t/{t['id']}"})
    return sorted(out, key=lambda x: -x["dias_atraso"])[:limit]


# --- clientes INATIVOS: pausados por inadimplência / concluídos -------------
# Tarefa vencida de cliente com serviço SUSPENSO não é cobrança do squad e
# inflava as contagens de atraso/capacidade (caso real Otávio 20/07: pausados
# por inadimplência contando em 'Atividades em atraso'). Fonte do status:
# card do cliente na lista Clientes Ativos (ativo/concluído/pausada por
# inatividade/aguardando documentos) + card de assessoria (só a pausa — lá
# 'concluído' é status do TRABALHO, não do cliente) + espelho como complemento.
# 'aguardando documentos' segue ATIVO: onboarding é trabalho real a cobrar.
_ST_INATIVOS = ("pausada por inatividade", "concluído", "concluido")


def inactive_clients() -> dict[str, str]:
    """{nome_normalizado: status} dos clientes inativos. Cacheado (30 min)."""
    def build():
        out: dict[str, str] = {}
        s = get_settings()
        if s.clickup_api_token:
            for lst in (s.clickup_list_clientes_ativos, s.clickup_list_assessoria):
                if not lst:
                    continue
                so_pausa = (lst == s.clickup_list_assessoria)
                try:
                    for t in _clickup_list_tasks(s.clickup_api_token, lst):
                        if t.get("parent"):
                            continue  # status de cliente vive no card-RAIZ
                        st = ((t.get("status") or {}).get("status") or "").strip().lower()
                        if st in _ST_INATIVOS and not (so_pausa and st != "pausada por inatividade"):
                            n = norm_account(t.get("name") or "")
                            if n:
                                out.setdefault(n, st)
                except Exception:  # noqa: BLE001 — lista indisponível não derruba o filtro
                    pass
        try:
            for n, c in _mirror_clientes().items():
                st = (c.get("status") or "").strip().lower()
                if st in _ST_INATIVOS:
                    out.setdefault(n, st)
        except Exception:  # noqa: BLE001
            pass
        return out
    return _cached("cu-inativos", build, ttl=_LIST_TTL)


def client_inactive_status(account_name: str) -> str | None:
    """Status ('pausada por inatividade' | 'concluído') se o cliente está
    inativo; None = ativo/desconhecido. Match EXATO do nome-base — sem o
    fallback por inclusão das subtarefas (marcar cliente ativo como pausado
    por parecença de nome seria pior que o bug original)."""
    try:
        return inactive_clients().get(norm_account(account_name))
    except Exception:  # noqa: BLE001
        return None


def open_tasks_count(account_name: str) -> int | None:
    """Tarefas ABERTAS da conta (sem conclusão/fechamento) nos índices já
    cacheados — carga REAL de trabalho p/ a Capacidade por squad (Otávio 16/07:
    tarefas recorrentes fazem squads com menos contas carregarem mais trabalho).
    None = API não configurada."""
    s = get_settings()
    if not (s.clickup_api_token and s.clickup_list_assessoria):
        return None
    vistos: set[str] = set()
    n = 0
    for lst in _report_lists(s):
        for t in _subs_lookup(s.clickup_api_token, lst, norm_account(account_name)):
            if t["id"] in vistos:
                continue
            vistos.add(t["id"])
            if not (t.get("date_done") or t.get("date_closed")):
                n += 1
    return n


def overdue_activities(account_name: str, now: dt.datetime | None = None) -> dict:
    """Mesmo contrato de completed/upcoming: {source, aviso|None, tasks}."""
    now = now or dt.datetime.now(dt.timezone.utc)
    try:
        tasks = _overdue_from_clickup(account_name, now)
        if tasks is not None:
            return {"source": "clickup_api", "aviso": None, "tasks": tasks}
        aviso = "token/lista ClickUp não configurados"
    except Exception as e:  # noqa: BLE001
        aviso = f"API ClickUp indisponível ({type(e).__name__})"
    return {"source": "nenhuma", "aviso": aviso, "tasks": []}


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
