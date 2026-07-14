"""Coletor Pipedrive → mkt_deals_attribution (deal com UTM/plano resolvidos).

Campos custom confirmados via /dealFields (2026-07-06): utm_source/medium/
term(público)/content(criativo)/campaign são varchar; `Produto` é enum (o
valor vem como id numérico — resolvemos p/ label via options do /dealFields,
ex. "B1 - NOVO START"). Atribuição: 100% dos deals pagos têm utm_campaign.

`oport_time` (14/07/26) = campo custom "Dia Oportunidade" (F_DIA_OPP), o MESMO
que o dashboard do time usa para contar Oportunidades — dia puro interpretado
como meia-noite BRT. Vem no payload do cache/API, sem custo extra; o diff de
meta (update quieto) backfilla os antigos na primeira rodada após o deploy.
"""
from __future__ import annotations

import datetime as dt
import os
from typing import Any

import httpx

F_SOURCE = "9ed28bb3e67c4336d4375949c87bbe6f306ef749"
F_MEDIUM = "14c742e76612142d336fe3f7c524b19f3f9064f8"
F_TERM = "6988285b5eb437ac88ad90a75c932c9f8f6efa3d"
F_CONTENT = "a4e181536d5f826605a31601bf992f4b50457b98"
F_CAMPAIGN = "9a853495a426a500ce75a58fa52d59a080c7e1ef"
F_PRODUTO = "9ad49f0040b563e8dfef6f58172830f0a115de12"
F_VALOR = "c84d155bc50db5f4ce79ee4b71a56081671524ce"  # VALOR (contrato) — o dashboard de metas usa este, não o value padrão
F_DIA_OPP = "167c46e9d6724bcd118c5f312589a695efe727c0"  # Dia Oportunidade — régua oficial de "Oportunidade" no funil do time


def _token() -> str:
    t = (os.environ.get("PIPEDRIVE_API_TOKEN") or "").strip().strip('"')
    if not t:
        raise RuntimeError("PIPEDRIVE_API_TOKEN ausente no .env")
    return t


class DailyBudgetExceeded(RuntimeError):
    """Orçamento DIÁRIO da API do Pipedrive esgotado — parar limpo e retomar
    amanhã (os marcadores incrementais garantem a retomada sem retrabalho)."""


_REQS = {"n": 0}  # requisições feitas neste processo (visibilidade nos logs)


def _get(path: str, params: dict) -> dict:
    r = httpx.get(f"https://api.pipedrive.com/v1/{path}",
                  params=dict(params, api_token=_token()), timeout=90)
    _REQS["n"] += 1
    if r.status_code == 429 and "daily request budget" in r.text:
        raise DailyBudgetExceeded(r.text[:120])
    r.raise_for_status()
    return r.json()


def produto_labels() -> dict[str, str]:
    """id da option -> label do enum Produto (ex.: '118' -> 'B1 - NOVO START')."""
    for f in _get("dealFields", {"limit": 500}).get("data") or []:
        if f.get("key") == F_PRODUTO:
            return {str(o["id"]): o["label"] for o in (f.get("options") or [])}
    return {}


def _txt(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, dict):  # enums podem vir como {"id":..,"label":..}
        return v.get("label")
    s = str(v).strip()
    return s or None


_DEALS_DDL_EXTRA = """ALTER TABLE mkt_deals_attribution
    ADD COLUMN IF NOT EXISTS owner_id BIGINT,
    ADD COLUMN IF NOT EXISTS owner_name TEXT,
    ADD COLUMN IF NOT EXISTS lost_reason TEXT,
    ADD COLUMN IF NOT EXISTS valor_custom NUMERIC"""


def _opp_ts(v) -> str | None:
    """'Dia Oportunidade' -> timestamp UTC. Dia puro = meia-noite BRT (03:00Z),
    a MESMA interpretação do dashboard do time; datetime vem UTC do Pipedrive."""
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    return f"{s} 03:00:00" if len(s) == 10 else s[:19]


def _num_br(v) -> float | None:
    """Campo VALOR pode vir numérico ou como texto BR ('1.500,00')."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("R$", "").strip()
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _upsert_deal(cur, d: dict, labels: dict[str, str]) -> None:
    """Upsert de UM deal (payload da API v1 ou do cache do Lovable — mesmo shape).
    updated_at só avança quando algo relevante mudou (IS DISTINCT FROM) — é esse
    carimbo que torna o enriquecimento /flow seletivo."""
    prod = _txt(d.get(F_PRODUTO))
    if prod and prod.isdigit():
        prod = labels.get(prod, prod)
    cur.execute(
        """INSERT INTO mkt_deals_attribution
               (deal_id, add_time, won_time, lost_time, status, valor, origem,
                utm_medium, utm_campaign, utm_term, utm_content, produto,
                stage_id, owner_id, owner_name, lost_reason, oport_time, updated_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
           ON CONFLICT (deal_id) DO UPDATE SET
                won_time=EXCLUDED.won_time, lost_time=EXCLUDED.lost_time,
                status=EXCLUDED.status, valor=EXCLUDED.valor, origem=EXCLUDED.origem,
                utm_medium=EXCLUDED.utm_medium, utm_campaign=EXCLUDED.utm_campaign,
                utm_term=EXCLUDED.utm_term, utm_content=EXCLUDED.utm_content,
                produto=EXCLUDED.produto, stage_id=EXCLUDED.stage_id,
                owner_id=EXCLUDED.owner_id, owner_name=EXCLUDED.owner_name,
                lost_reason=EXCLUDED.lost_reason, oport_time=EXCLUDED.oport_time,
                updated_at=now()
           WHERE (mkt_deals_attribution.status, mkt_deals_attribution.stage_id,
                  mkt_deals_attribution.won_time, mkt_deals_attribution.valor,
                  mkt_deals_attribution.owner_id, mkt_deals_attribution.lost_reason)
                 IS DISTINCT FROM
                 (EXCLUDED.status, EXCLUDED.stage_id, EXCLUDED.won_time, EXCLUDED.valor,
                  EXCLUDED.owner_id, EXCLUDED.lost_reason)""",
        (d["id"], d.get("add_time"), d.get("won_time"), d.get("lost_time"), d.get("status"),
         d.get("value"), (_txt(d.get(F_SOURCE)) or "").lower() or None,
         _txt(d.get(F_MEDIUM)), _txt(d.get(F_CAMPAIGN)), _txt(d.get(F_TERM)),
         _txt(d.get(F_CONTENT)), prod, d.get("stage_id"),
         (d.get("user_id") or {}).get("id") if isinstance(d.get("user_id"), dict) else d.get("user_id"),
         (d.get("user_id") or {}).get("name") if isinstance(d.get("user_id"), dict)
         else _txt(d.get("owner_name")),
         _txt(d.get("lost_reason")), _opp_ts(d.get(F_DIA_OPP))))


def sync_deals(conn: Any, since: dt.date = dt.date(2025, 1, 1)) -> int:
    """Upsert de todos os deals com add_time >= since DIRETO na API do Pipedrive
    (paginado, mais recentes primeiro; para quando a página inteira é anterior ao
    corte). Caro em requisições — preferir sync_deals_smart (cache do Lovable)."""
    labels = produto_labels()
    n, start = 0, 0
    with conn.cursor() as cur:
        cur.execute(_DEALS_DDL_EXTRA)
        while start is not None:
            j = _get("deals", {"limit": 500, "start": start, "sort": "add_time DESC"})
            data = j.get("data") or []
            page_old = True
            for d in data:
                add = d.get("add_time")
                if not add or add[:10] < since.isoformat():
                    continue
                page_old = False
                _upsert_deal(cur, d, labels)
                n += 1
            p = (j.get("additional_data") or {}).get("pagination") or {}
            if page_old and data:
                break  # página inteira antes do corte: fim do backfill
            start = p.get("next_start") if p.get("more_items_in_collection") else None
        # higiene: deals APAGADOS no Pipedrive (janela de 30d da API) saem do cache
        j = _get("deals", {"limit": 500, "status": "deleted"})
        apagados = [d["id"] for d in (j.get("data") or [])]
        if apagados:
            cur.execute("DELETE FROM mkt_deals_attribution WHERE deal_id = ANY(%s)", (apagados,))
    return n


# ---------------------------------------------------------------------------
# Cache do Lovable (10/07/26): o "Dashboard - Comercial (Pipedrive)" do time já
# extrai TODOS os deals a cada ~15min (horário comercial) e publica no Supabase
# dele. Ler de lá custa ZERO requisições ao Pipedrive — que é compartilhado com
# aplicações em tempo real e tem orçamento diário. Acesso somente leitura:
# edge function get-deals-cache (tabela sempre fresca) + PostgREST p/ os labels
# do enum Produto (cache deal_fields). Chave anon é pública por desenho.
# ---------------------------------------------------------------------------
_LOVABLE_SB = "https://tmyvsccfuvgwayitvbav.supabase.co"
_CACHE_MAX_AGE_H = 26  # cache mais velho que isso = suspeito -> fallback API


def _lovable_headers() -> dict:
    key = (os.environ.get("LOVABLE_SUPABASE_ANON_KEY") or "").strip().strip('"')
    if not key:
        raise RuntimeError("LOVABLE_SUPABASE_ANON_KEY ausente no .env")
    return {"Authorization": f"Bearer {key}", "apikey": key}


def _labels_from_cache() -> dict[str, str]:
    """Labels do enum Produto a partir do cache deal_fields do Lovable
    (PostgREST; policy pública de leitura). Fallback: 1 chamada à API."""
    try:
        r = httpx.get(f"{_LOVABLE_SB}/rest/v1/pipedrive_cache",
                      params={"cache_key": "eq.deal_fields", "select": "data"},
                      headers=_lovable_headers(), timeout=60)
        r.raise_for_status()
        import json
        fields = json.loads(r.json()[0]["data"])
        for f in fields:
            if f.get("key") == F_PRODUTO:
                return {str(o["id"]): o["label"] for o in (f.get("options") or [])}
    except Exception:  # noqa: BLE001 — cache indisponível não trava o sync
        pass
    return produto_labels()


def _norm_ts(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, dt.datetime):
        return v.astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return str(v)[:19] or None


def _norm_val(v) -> float | None:
    return None if v is None else float(v)


def _deal_tuplas(d: dict, labels: dict[str, str]) -> tuple[tuple, tuple]:
    """(core, meta) normalizados do payload do cache — core muda o funil
    (dispara /flow via updated_at), meta é atribuição/rótulo (update quieto)."""
    prod = _txt(d.get(F_PRODUTO))
    if prod and prod.isdigit():
        prod = labels.get(prod, prod)
    uid = d.get("user_id")
    core = (d.get("status"), d.get("stage_id"), _norm_ts(d.get("won_time")),
            _norm_val(d.get("value")),
            (uid or {}).get("id") if isinstance(uid, dict) else uid,
            _txt(d.get("lost_reason")))
    meta = ((_txt(d.get(F_SOURCE)) or "").lower() or None, _txt(d.get(F_MEDIUM)),
            _txt(d.get(F_TERM)), _txt(d.get(F_CAMPAIGN)), _txt(d.get(F_CONTENT)),
            prod, (uid or {}).get("name") if isinstance(uid, dict) else _txt(d.get("owner_name")),
            _num_br(d.get(F_VALOR)), _opp_ts(d.get(F_DIA_OPP)))
    return core, meta


def sync_deals_from_cache(conn: Any, since: dt.date = dt.date(2025, 1, 1)) -> int:
    """Deals a partir do cache do Lovable (zero requisições Pipedrive). Compara
    com o banco ANTES de escrever: só deals novos/alterados geram round-trip
    (o RDS derruba conexões em cargas longas — 10/07). Mudança de funil passa
    pelo upsert (avança updated_at -> /flow seletivo); mudança só de UTM/
    produto/dono é um UPDATE quieto que NÃO avança updated_at (senão milhares
    de deals re-entrariam na fila do /flow sem necessidade). Levanta
    RuntimeError se o cache estiver velho/suspeito (chamador cai p/ API)."""
    import json
    r = httpx.get(f"{_LOVABLE_SB}/functions/v1/get-deals-cache",
                  headers=_lovable_headers(), timeout=180)
    r.raise_for_status()
    upd = r.headers.get("X-Cache-Updated-At")
    if upd:
        age_h = (dt.datetime.now(dt.timezone.utc)
                 - dt.datetime.fromisoformat(upd.replace("Z", "+00:00"))).total_seconds() / 3600
        if age_h > _CACHE_MAX_AGE_H:
            raise RuntimeError(f"cache do Lovable com {age_h:.0f}h — usando API direta")
    deals = json.loads(r.text)
    if isinstance(deals, str):  # a tabela guarda o JSON como string
        deals = json.loads(deals)
    if isinstance(deals, dict) and deals.get("storage"):
        # 13/07 à tarde: o app deles passou a guardar só um PONTEIRO na tabela;
        # o payload vive no Storage público (gzip) — segue o ponteiro
        import gzip
        import time
        sr = httpx.get(f"{_LOVABLE_SB}/storage/v1/object/public/pipedrive-cache/{deals['storage']}",
                       params={"cb": int(time.time())}, timeout=180)
        sr.raise_for_status()
        raw = sr.content
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        deals = json.loads(raw)
        if isinstance(deals, str):
            deals = json.loads(deals)
    if not isinstance(deals, list) or len(deals) < 15_000:
        raise RuntimeError(f"cache do Lovable suspeito ({len(deals) if isinstance(deals, list) else '?'} deals)")
    labels = _labels_from_cache()
    corte = since.isoformat()
    with conn.cursor() as cur:
        cur.execute(_DEALS_DDL_EXTRA)
        cur.execute("""SELECT deal_id, status, stage_id, won_time, valor, owner_id, lost_reason,
                              origem, utm_medium, utm_term, utm_campaign, utm_content,
                              produto, owner_name, valor_custom, oport_time
                         FROM mkt_deals_attribution""")
        db: dict[int, tuple[tuple, tuple]] = {}
        for row in cur.fetchall():
            db[row[0]] = ((row[1], row[2], _norm_ts(row[3]), _norm_val(row[4]), row[5], row[6]),
                          tuple(row[7:14]) + (_norm_val(row[14]), _norm_ts(row[15])))
    novos = mudou_core = mudou_meta = 0
    ids_cache: list[int] = []
    with conn.cursor() as cur:
        for d in deals:
            add = d.get("add_time")
            if not add or add[:10] < corte:
                continue
            did = d["id"]
            ids_cache.append(did)
            core, meta = _deal_tuplas(d, labels)
            atual = db.get(did)
            if atual is None or core != atual[0]:
                _upsert_deal(cur, d, labels)
                novos += atual is None
                mudou_core += atual is not None
            elif meta != atual[1]:
                cur.execute("""UPDATE mkt_deals_attribution SET origem=%s, utm_medium=%s,
                                   utm_term=%s, utm_campaign=%s, utm_content=%s,
                                   produto=%s, owner_name=%s, valor_custom=%s, oport_time=%s
                                 WHERE deal_id=%s""",
                            (*meta, did))
                mudou_meta += 1
        # apagados: sumiu do cache íntegro = deletado no Pipedrive
        cur.execute("""DELETE FROM mkt_deals_attribution
                        WHERE add_time >= %s AND NOT (deal_id = ANY(%s))""",
                    (corte, ids_cache))
    print(f"  [deals] cache: {novos} novos, {mudou_core} mudança de funil, "
          f"{mudou_meta} só atribuição (quieto)", flush=True)
    return novos + mudou_core + mudou_meta


def sync_deals_smart(conn: Any, since: dt.date = dt.date(2025, 1, 1)) -> int:
    """Cache do Lovable primeiro (zero requisições); API direta só de fallback."""
    try:
        n = sync_deals_from_cache(conn, since=since)
        print("  [deals] fonte: cache do Lovable (0 req Pipedrive)", flush=True)
        return n
    except Exception as e:  # noqa: BLE001
        print(f"  [deals] cache indisponível ({type(e).__name__}: {str(e)[:80]}) — API direta", flush=True)
        return sync_deals(conn, since=since)


# ---------------------------------------------------------------------------
# Histórico de mudanças de etapa (/deals/{id}/flow) → mkt_stage_events.
# É o que permite contar o funil POR EVENTO no período (mesma régua do
# Pipedrive/app Lovable do time: "entrou na etapa X em julho"), em vez de
# coorte. 1 chamada por deal: backfill pesado (~2k deals), incremental leve.
# ---------------------------------------------------------------------------
_EVENTS_DDL = """
CREATE TABLE IF NOT EXISTS mkt_stage_events (
    deal_id    BIGINT NOT NULL,
    stage_id   INTEGER NOT NULL,
    entered_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (deal_id, stage_id, entered_at)
);
CREATE INDEX IF NOT EXISTS idx_mkt_stage_ev_t ON mkt_stage_events(entered_at);
-- deals já enriquecidos (re-buscamos só os que mudaram depois)
CREATE TABLE IF NOT EXISTS mkt_flow_synced (
    deal_id   BIGINT PRIMARY KEY,
    synced_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def _flow_events(deal_id: int) -> list[tuple[int, str]]:
    """(stage_id, log_time) de cada mudança de etapa do deal, via /flow."""
    import time
    out: list[tuple[int, str]] = []
    start = 0
    while True:
        for tent in range(4):
            try:
                j = _get(f"deals/{deal_id}/flow", {"limit": 500, "start": start})
                break
            except httpx.HTTPStatusError as e:  # 429: espera e tenta de novo
                if e.response.status_code == 429 and tent < 3:
                    time.sleep(2.0 * (tent + 1))
                    continue
                raise
        for item in j.get("data") or []:
            if item.get("object") != "dealChange":
                continue
            d = item.get("data") or {}
            if d.get("field_key") == "stage_id" and d.get("new_value") is not None:
                try:
                    out.append((int(d["new_value"]), d.get("log_time")))
                except (TypeError, ValueError):
                    pass
        p = (j.get("additional_data") or {}).get("pagination") or {}
        if not p.get("more_items_in_collection"):
            return out
        start = p.get("next_start")


def sync_stage_events(conn: Any, *, full: bool = False, window_days: int = 60,
                      max_deals: int = 400) -> int:
    # teto 400/dia (13/07, ordem do Otávio): a API é compartilhada com apps em
    # TEMPO REAL — nunca esgotar o orçamento diário; backlog drena aos poucos
    """Enriquece com o histórico de etapas os deals NOVOS/ALTERADOS desde o
    último enriquecimento (updated_at > synced_at); `full` refaz todos."""
    import time
    with conn.cursor() as cur:
        cur.execute(_EVENTS_DDL)
        if full:
            cur.execute("SELECT deal_id FROM mkt_deals_attribution ORDER BY add_time DESC")
        else:
            # MAIS RECENTES PRIMEIRO (13/07): o funil corrente precisa estar exato
            # hoje; o histórico antigo pode esperar as próximas rodadas
            cur.execute("""SELECT d.deal_id FROM mkt_deals_attribution d
                             LEFT JOIN mkt_flow_synced f ON f.deal_id = d.deal_id
                            WHERE (f.deal_id IS NULL AND d.add_time >= now() - %s * interval '1 day')
                               OR d.updated_at > f.synced_at
                            ORDER BY GREATEST(d.updated_at, d.add_time) DESC NULLS LAST""",
                        (window_days,))
        ids = [r[0] for r in cur.fetchall()]
    ids = ids[:max_deals]  # teto diário: o resto retoma amanhã (marcador)
    n = 0
    with conn.cursor() as cur:
        for i, did in enumerate(ids):
            try:
                evs = _flow_events(did)
            except DailyBudgetExceeded:
                print(f"  [flow] orçamento diário esgotou em {i}/{len(ids)} — retoma amanhã", flush=True)
                break
            except httpx.HTTPError:
                continue  # deal problemático não trava o lote; re-tenta amanhã
            for sid, quando in evs:
                if not quando:
                    continue
                cur.execute("""INSERT INTO mkt_stage_events (deal_id, stage_id, entered_at)
                               VALUES (%s,%s,%s) ON CONFLICT DO NOTHING""", (did, sid, quando))
                n += 1
            cur.execute("""INSERT INTO mkt_flow_synced (deal_id, synced_at) VALUES (%s, now())
                           ON CONFLICT (deal_id) DO UPDATE SET synced_at=now()""", (did,))
            time.sleep(0.12)  # folga p/ o rate limit (~80 req/2s no plano)
            if i and i % 200 == 0:
                print(f"  [flow] {i}/{len(ids)} deals...", flush=True)
    return n


# ---------------------------------------------------------------------------
# Primeiro contato por deal (speed-to-lead das áreas de Pré-vendas/Vendas).
# Uma passada paginada em /activities (todas as pessoas, concluídas) guardando
# o PRIMEIRO toque de cada deal — barato (500/página) e incremental por data.
# ---------------------------------------------------------------------------
_TOUCH_DDL = """
CREATE TABLE IF NOT EXISTS sales_first_touch (
    deal_id     BIGINT PRIMARY KEY,
    first_at    TIMESTAMPTZ NOT NULL,   -- criação da 1ª atividade do deal
    done_at     TIMESTAMPTZ,            -- quando foi concluída
    tipo        TEXT,                   -- call|whatsapp|email|fluxo_de_cadencia...
    quem        TEXT,                   -- responsável pela atividade
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def sync_first_touch(conn: Any, since: dt.date | None = None,
                     max_pages: int = 200) -> int:
    """Varre atividades (desc) e registra o 1º contato de cada deal; para na
    página inteira anterior a `since` (default: 10 dias — incremental diário)."""
    corte = (since or (dt.date.today() - dt.timedelta(days=10))).isoformat()
    n, start, paginas = 0, 0, 0
    with conn.cursor() as cur:
        cur.execute(_TOUCH_DDL)
        while start is not None and paginas < max_pages:
            paginas += 1
            j = _get("activities", {"user_id": 0, "limit": 500, "start": start,
                                    "done": 1, "sort": "add_time DESC"})
            data = j.get("data") or []
            page_old = True
            for a in data:
                add = a.get("add_time")
                if not add:
                    continue
                if add[:10] >= corte:
                    page_old = False
                if not a.get("deal_id"):
                    continue
                cur.execute(
                    """INSERT INTO sales_first_touch (deal_id, first_at, done_at, tipo, quem, updated_at)
                       VALUES (%s,%s,%s,%s,%s,now())
                       ON CONFLICT (deal_id) DO UPDATE SET
                            first_at=LEAST(sales_first_touch.first_at, EXCLUDED.first_at),
                            done_at=LEAST(COALESCE(sales_first_touch.done_at, EXCLUDED.done_at),
                                          COALESCE(EXCLUDED.done_at, sales_first_touch.done_at)),
                            tipo=CASE WHEN EXCLUDED.first_at < sales_first_touch.first_at
                                      THEN EXCLUDED.tipo ELSE sales_first_touch.tipo END,
                            quem=CASE WHEN EXCLUDED.first_at < sales_first_touch.first_at
                                      THEN EXCLUDED.quem ELSE sales_first_touch.quem END,
                            updated_at=now()""",
                    (a["deal_id"], add, a.get("marked_as_done_time") or None,
                     a.get("type"), (a.get("owner_name") or "")))
                n += 1
            p = (j.get("additional_data") or {}).get("pagination") or {}
            if page_old and data:
                break
            start = p.get("next_start") if p.get("more_items_in_collection") else None
    return n
