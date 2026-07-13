"""Metas por área (Operações) — réplica do app Lovable "Metas e Iniciativas".

KPIs por área (area-kpis.ts), meta trimestral redistribuída pelos meses
compensando déficit/superávit dos meses fechados (monthlyTargetsFromQuarterly)
e agregação trimestral (média p/ %, soma p/ R$/qtde). Realizado: AUTOMÁTICO
onde o nosso banco já tem o dado (Comercial/Marketing/Assessoria); manual via
Configurações para o resto (Financeiro/RH).
"""
from __future__ import annotations

import datetime as dt
from typing import Any

# (key, label, unit BRL|pct|num, direction min=maior-melhor|max=menor-melhor, is_ratio, auto)
AREA_KPIS: dict[str, list[tuple[str, str, str, str, bool, bool]]] = {
    "financeiro": [
        ("recebimento", "Recebimento", "BRL", "min", False, False),
        ("inadimplencia_pct", "Inadimplência", "pct", "max", False, False),
    ],
    "comercial": [
        ("bookings_receita", "Bookings (R$)", "BRL", "min", False, True),
        ("oportunidades", "Oportunidades", "num", "min", False, True),
        ("receita_por_mql", "Receita / MQL", "BRL", "min", True, True),
        ("conversao_op_ganho_pct", "Conversão Op→Ganho", "pct", "min", True, True),
        # régua definida pelo Otávio 13/07: cancelados ÷ total de clientes ativos
        ("tx_cancelamento_pct", "Tx. Cancelamento", "pct", "max", False, True),
        ("mix_b2b5_pct", "Mix B2–B5 (novos)", "pct", "min", False, True),
    ],
    "assessoria": [
        ("tx_cancelamento_pct", "Tx. Cancelamento", "pct", "max", False, True),
    ],
    "marketing": [
        ("mqls", "MQLs", "num", "min", False, True),
        ("oportunidades", "Oportunidades", "num", "min", False, True),
        ("lead_inaproveitavel_pct", "Lead Inaproveitável", "pct", "max", False, False),
    ],
    "rh": [],
    "growth": [],
}

DDL = """
CREATE TABLE IF NOT EXISTS op_kpi_targets (
    area TEXT NOT NULL, kpi_key TEXT NOT NULL, year INT NOT NULL, quarter INT NOT NULL,
    meta NUMERIC, PRIMARY KEY (area, kpi_key, year, quarter));
CREATE TABLE IF NOT EXISTS op_kpi_monthly (
    area TEXT NOT NULL, kpi_key TEXT NOT NULL, year INT NOT NULL, month INT NOT NULL,
    realizado NUMERIC, PRIMARY KEY (area, kpi_key, year, month));
"""


def quarter_months(quarter: int) -> list[int]:
    return [(quarter - 1) * 3 + 1, (quarter - 1) * 3 + 2, (quarter - 1) * 3 + 3]


def monthly_targets(meta_tri: float | None, months: list[int],
                    realizado: dict[int, float | None], unit: str,
                    is_ratio: bool = False) -> dict[int, float | None]:
    """Meta mensal ADAPTATIVA (regra exata da referência): somáveis consomem a
    meta trimestral; percentuais/razões consomem meta×N (média final = meta).
    Mês fechado abaixo da meta sobe a dos seguintes (e vice-versa; p/ métricas
    de teto como inadimplência a compensação naturalmente inverte, pois o
    'consumo' menor deixa mais folga)."""
    out: dict[int, float | None] = {}
    if meta_tri is None or not months:
        return out
    n = len(months)
    is_pct = unit == "pct" or is_ratio
    total = meta_tri * n if is_pct else meta_tri
    consumido = 0.0
    for i, m in enumerate(months):
        restante = total - consumido
        out[m] = max(0.0, restante) / (n - i)
        r = realizado.get(m)
        # DESVIO da referência (spec do Otávio 13/07): mês sem realizado consome
        # a própria meta recalculada (assume que vai bater) — assim 300k c/ 80k
        # no 1º mês vira 110k E 110k nos seguintes, não 110k e 220k.
        consumido += r if r is not None else out[m]
    return out


def aggregate_quarter(vals: list[float | None], unit: str, is_ratio: bool = False) -> float | None:
    xs = [v for v in vals if v is not None]
    if not xs:
        return None
    if unit == "pct" or is_ratio:
        return sum(xs) / len(xs)
    return sum(xs)


def fmt_val(v: float | None, unit: str) -> str:
    if v is None:
        return "—"
    if unit == "BRL":
        return f"R$ {v:,.0f}".replace(",", ".")
    if unit == "pct":
        return f"{v:.1f}%"
    return f"{v:,.0f}".replace(",", ".")


# ---------------------------------------------------------------------------
# Realizado AUTOMÁTICO a partir do nosso banco (por mês do trimestre)
# ---------------------------------------------------------------------------
def _auto_comercial(conn: Any, year: int, months: list[int]) -> dict[str, dict[int, float | None]]:
    out: dict[str, dict[int, float | None]] = {k: {} for k in
                                               ("bookings_receita", "oportunidades", "receita_por_mql",
                                                "conversao_op_ganho_pct", "tx_cancelamento_pct", "mix_b2b5_pct")}
    with conn.cursor() as cur:
        for m in months:
            a = f"{year}-{m:02d}-01 00:00-03"
            prox = dt.date(year + (m == 12), m % 12 + 1, 1)
            b = f"{prox} 00:00-03"
            # receita = campo VALOR do Pipedrive (régua do dashboard de metas); value é fallback
            cur.execute("""SELECT count(*), COALESCE(sum(COALESCE(valor_custom, valor)), 0)
                             FROM mkt_deals_attribution
                            WHERE status='won' AND won_time >= %s AND won_time < %s""", (a, b))
            wins, receita = cur.fetchone()
            cur.execute("""SELECT count(DISTINCT deal_id) FROM mkt_stage_events
                            WHERE stage_id = 7 AND entered_at >= %s AND entered_at < %s""", (a, b))
            oport = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM mkt_deals_attribution WHERE add_time >= %s AND add_time < %s", (a, b))
            mqls = cur.fetchone()[0]
            cur.execute("""SELECT count(*) FILTER (WHERE substring(produto FROM 'B[1-5]') IN ('B2','B3','B4','B5')),
                                  count(*) FILTER (WHERE produto IS NOT NULL)
                             FROM mkt_deals_attribution
                            WHERE status='won' AND won_time >= %s AND won_time < %s""", (a, b))
            b25, com_prod = cur.fetchone()
            cur.execute("""SELECT count(*) FROM grw_cancelamentos
                            WHERE mes = %s AND tipo = 'cancelamento'""", (dt.date(year, m, 1),))
            canc = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM accounts")
            base_ativa = cur.fetchone()[0] or 1
            fut = dt.date(year, m, 1) > dt.date.today().replace(day=1)
            out["bookings_receita"][m] = None if fut else float(receita or 0)
            out["oportunidades"][m] = None if fut else float(oport)
            out["receita_por_mql"][m] = None if fut or not mqls else float(receita or 0) / mqls
            out["conversao_op_ganho_pct"][m] = None if fut or not oport else 100.0 * wins / oport
            out["mix_b2b5_pct"][m] = None if fut or not com_prod else 100.0 * b25 / com_prod
            # régua do Otávio (13/07): cancelados ÷ total de clientes ativos
            out["tx_cancelamento_pct"][m] = None if fut else 100.0 * canc / base_ativa
    return out


def _auto_marketing(conn: Any, year: int, months: list[int]) -> dict[str, dict[int, float | None]]:
    out: dict[str, dict[int, float | None]] = {"mqls": {}, "oportunidades": {}}
    with conn.cursor() as cur:
        for m in months:
            a = f"{year}-{m:02d}-01 00:00-03"
            prox = dt.date(year + (m == 12), m % 12 + 1, 1)
            b = f"{prox} 00:00-03"
            fut = dt.date(year, m, 1) > dt.date.today().replace(day=1)
            cur.execute("SELECT count(*) FROM mkt_deals_attribution WHERE add_time >= %s AND add_time < %s", (a, b))
            out["mqls"][m] = None if fut else float(cur.fetchone()[0])
            cur.execute("""SELECT count(DISTINCT deal_id) FROM mkt_stage_events
                            WHERE stage_id = 7 AND entered_at >= %s AND entered_at < %s""", (a, b))
            out["oportunidades"][m] = None if fut else float(cur.fetchone()[0])
    return out


def auto_realizado(conn: Any, area: str, year: int, months: list[int]) -> dict[str, dict[int, float | None]]:
    """Realizado automático por KPI/mês; {} onde não há fonte (fica o manual)."""
    try:
        if area == "comercial":
            return _auto_comercial(conn, year, months)
        if area == "marketing":
            return _auto_marketing(conn, year, months)
        if area == "assessoria":
            return {"tx_cancelamento_pct": _auto_comercial(conn, year, months)["tx_cancelamento_pct"]}
    except Exception:  # noqa: BLE001 — fonte automática fora não derruba a tela
        return {}
    return {}


def load_metas(conn: Any, area: str, year: int, quarter: int) -> list[dict]:
    """KPIs da área com meta trimestral, realizado por mês (auto > manual),
    meta mensal adaptativa e agregado do trimestre."""
    defs = AREA_KPIS.get(area) or []
    if not defs:
        return []
    months = quarter_months(quarter)
    with conn.cursor() as cur:
        cur.execute(DDL)
        cur.execute("SELECT kpi_key, meta FROM op_kpi_targets WHERE area=%s AND year=%s AND quarter=%s",
                    (area, year, quarter))
        targets = {k: (float(v) if v is not None else None) for k, v in cur.fetchall()}
        cur.execute("""SELECT kpi_key, month, realizado FROM op_kpi_monthly
                        WHERE area=%s AND year=%s AND month = ANY(%s)""", (area, year, months))
        manual: dict[str, dict[int, float | None]] = {}
        for k, m, v in cur.fetchall():
            manual.setdefault(k, {})[m] = float(v) if v is not None else None
    if area == "marketing":  # Q3+: metas vêm da planilha de metas do Marketing (decisão 13/07)
        try:
            from ..marketing.ui import _plan_funil
            meses_d = [dt.date(year, m, 1) for m in months]
            plan = _plan_funil(conn, meses_d)
            soma = {"mqls": 0.0, "oportunidades": 0.0}
            for mes_d in meses_d:
                p = plan.get(mes_d) or {}
                soma["mqls"] += float(((p.get("MQL") or p.get("Lead")) or {}).get("qtde") or 0)
                soma["oportunidades"] += float((p.get("Oportunidade") or {}).get("qtde") or 0)
            for k, v in soma.items():
                if targets.get(k) is None and v:
                    targets[k] = v
        except Exception:  # noqa: BLE001 — planilha fora não derruba a tela
            pass
    auto = auto_realizado(conn, area, year, months)
    out = []
    for key, label, unit, direction, is_ratio, is_auto in defs:
        realizado = {m: (auto.get(key, {}).get(m) if is_auto else None) for m in months}
        for m in months:  # manual sobrepõe/completa
            mv = manual.get(key, {}).get(m)
            if mv is not None:
                realizado[m] = mv
        meta_tri = targets.get(key)
        metas_mes = monthly_targets(meta_tri, months, realizado, unit, is_ratio)
        real_tri = aggregate_quarter([realizado[m] for m in months], unit, is_ratio)
        pct = None
        if meta_tri and real_tri is not None:
            pct = 100.0 * real_tri / meta_tri
        ok = None
        if pct is not None:
            ok = (real_tri <= meta_tri) if direction == "max" else (pct >= 100.0)
        out.append({"key": key, "label": label, "unit": unit, "direction": direction,
                    "is_ratio": is_ratio, "auto": is_auto, "months": months,
                    "realizado": realizado, "metas_mes": metas_mes,
                    "meta_tri": meta_tri, "real_tri": real_tri, "pct": pct, "ok": ok})
    return out
