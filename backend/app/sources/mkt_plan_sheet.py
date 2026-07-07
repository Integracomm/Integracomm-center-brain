"""Plano detalhado do Marketing (planilha "Metas Marketing" do time) → mkt_plan_*.

Estrutura (inspecionada 2026-07-07), aba gid=0, ano implícito = ANO:
  * MATRIZ topo — col 0 = indicador, cols 1-12 = Janeiro..Dezembro.
      "Leads [Qtde]".."Bookings [Qtde]"  → mkt_plan_funnel.qtde
      "Tx. X x Y [%]"                    → semeia mkt_funnel_goals (taxa-alvo da
                                           etapa DESTINO; edição manual do painel
                                           prevalece: ON CONFLICT DO NOTHING)
  * BLOCOS "Custo Médio por <etapa>" — linha homônima com valores = custo-alvo
    unitário; "Investimento Mensal Realizado/Necessário (R$)" = verba do mês.
  * CANAIS (só sob o bloco CPO) — rótulo na col 6 (META, PROSPECÇÃO, EVENTOS,
    SHOPEE, LOW TICKET, INST ORG, TOTAL), oportunidades/mês nas cols 7-12
    (jul-dez); a ÚLTIMA linha "R$ ..." antes do próximo rótulo é a verba
    (a do META tem uma linha de custo unitário no meio).
Usamos export?format=csv (e não gviz) porque preserva o rótulo das células
mescladas dos canais. Jan-jun já vem como realizado na planilha; gravamos tudo
e o painel decide o que é meta (mês futuro) ou referência (mês passado).
"""
from __future__ import annotations

import csv
import io
import re
from typing import Any

import httpx

SHEET_ID = "1W6fVtHa-xTVvlA8cbgGI_VgIneu-ETMP6sfQ5nnsZpU"
GID = "0"
ANO = 2026  # planilha não traz o ano; é o planejamento anual corrente

_MESES = {"janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4,
          "maio": 5, "junho": 6, "julho": 7, "agosto": 8, "setembro": 9,
          "outubro": 10, "novembro": 11, "dezembro": 12}
_ETAPA_QTDE = {"Leads [Qtde]": "Lead", "MQLs [Qtde]": "MQL", "SAL [Qtde]": "SAL",
               "SQL [Qtde]": "SQL", "Oportunidades [Qtde]": "Oportunidade",
               "Bookings [Qtde]": "Booking"}
# taxa da planilha → etapa DESTINO na taxonomia do funil (mkt_funnel_goals)
_ETAPA_TAXA = {"Tx. Lead x MQL [%]": "MQL", "Tx. MQL x SAL [%]": "SAL",
               "Tx. SAL x SQL [%]": "SQL", "Tx. SQL x Oportunidade [%]": "Oportunidade",
               "Tx. Oportunidade x Booking [%]": "Booking"}
_ETAPA_CUSTO = {"Lead": "Lead", "MQL": "MQL", "SAL": "SAL", "SQL": "SQL",
                "Oportunidade": "Oportunidade"}
_CANAIS = {"META", "PROSPECÇÃO", "EVENTOS", "SHOPEE", "LOW TICKET", "INST ORG", "TOTAL"}
_CUSTO_HDR = re.compile(r"Custo Médio por (Lead|MQL|SAL|SQL|Oportunidade)")


def _num(v: str) -> float | None:
    x = re.sub(r"[^\d,\-]", "", v or "")
    if not x or x in ("-", ","):
        return None
    try:
        return float(x.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def fetch_rows() -> list[list[str]]:
    r = httpx.get(f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export",
                  params={"format": "csv", "gid": GID}, timeout=60, follow_redirects=True)
    r.raise_for_status()
    return list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))


def parse(rows: list[list[str]]):
    """→ (funil {(mes,etapa): {qtde,custo_unit,investimento}}, taxas {(mes,etapa): fração},
    canais {(mes,canal): {meta_oport, verba}})."""
    def cel(r, j):
        return (r[j] if j < len(r) else "").strip()

    def mes_iso(m: int) -> str:
        return f"{ANO}-{m:02d}-01"

    # colunas de mês da matriz do topo (linha 0)
    col_mes = {j: _MESES[c.lower()] for j, c in enumerate(rows[0])
               if c.strip().lower() in _MESES}
    funil: dict[tuple[str, str], dict] = {}
    taxas: dict[tuple[str, str], float] = {}
    canais: dict[tuple[str, str], dict] = {}

    etapa_custo = None       # bloco "Custo Médio por X" corrente
    canal_atual = None       # canal corrente (rótulo col 6)
    verba_canal: list[str] | None = None  # última linha R$ vista do canal

    def fecha_canal():
        if canal_atual and verba_canal is not None:
            for j in range(7, 13):  # cols 7-12 = julho..dezembro (índice == mês)
                v = _num(cel(verba_canal, j))
                if v is not None:
                    canais.setdefault((mes_iso(j), canal_atual), {})["verba"] = v

    for r in rows[1:]:
        rotulo = cel(r, 0)
        # matriz do topo — volumes e taxas
        if rotulo in _ETAPA_QTDE:
            for j, m in col_mes.items():
                v = _num(cel(r, j))
                if v is not None:
                    funil.setdefault((mes_iso(m), _ETAPA_QTDE[rotulo]), {})["qtde"] = v
            continue
        if rotulo in _ETAPA_TAXA:
            for j, m in col_mes.items():
                v = _num(cel(r, j))
                if v is not None:
                    taxas[(mes_iso(m), _ETAPA_TAXA[rotulo])] = v / 100.0
            continue
        # blocos de custo — o cabeçalho não tem valores; a linha homônima tem
        m_hdr = _CUSTO_HDR.search(rotulo)
        if m_hdr:
            etapa_custo = _ETAPA_CUSTO[m_hdr.group(1)]
            vals = {j: _num(cel(r, j)) for j, m in col_mes.items()}
            if any(v is not None for v in vals.values()):
                for j, m in col_mes.items():
                    if vals[j] is not None:
                        funil.setdefault((mes_iso(m), etapa_custo), {})["custo_unit"] = vals[j]
            continue
        if rotulo.startswith("Investimento Mensal") and etapa_custo:
            for j, m in col_mes.items():
                v = _num(cel(r, j))
                if v is not None:
                    funil.setdefault((mes_iso(m), etapa_custo), {})["investimento"] = v
            continue
        # canais — rótulo na col 6, meses jul-dez nas cols 7-12
        lbl = cel(r, 6).upper()
        if lbl in _CANAIS:
            fecha_canal()
            canal_atual, verba_canal = lbl, None
            for j in range(7, 13):
                v = _num(cel(r, j))
                if v is not None:
                    canais.setdefault((mes_iso(j), canal_atual), {})["meta_oport"] = v
            continue
        if canal_atual and any("R$" in cel(r, j) for j in range(7, 13)):
            verba_canal = r  # a última R$ antes do próximo rótulo é a verba
    fecha_canal()
    return funil, taxas, canais


def sync_plan(conn: Any) -> int:
    funil, taxas, canais = parse(fetch_rows())
    n = 0
    with conn.cursor() as cur:
        for (mes, etapa), v in funil.items():
            cur.execute(
                """INSERT INTO mkt_plan_funnel (mes, etapa, qtde, custo_unit, investimento, updated_at)
                   VALUES (%s,%s,%s,%s,%s,now())
                   ON CONFLICT (mes, etapa) DO UPDATE SET
                        qtde=COALESCE(EXCLUDED.qtde, mkt_plan_funnel.qtde),
                        custo_unit=COALESCE(EXCLUDED.custo_unit, mkt_plan_funnel.custo_unit),
                        investimento=COALESCE(EXCLUDED.investimento, mkt_plan_funnel.investimento),
                        updated_at=now()""",
                (mes, etapa, v.get("qtde"), v.get("custo_unit"), v.get("investimento")))
            n += 1
        for (mes, canal), v in canais.items():
            cur.execute(
                """INSERT INTO mkt_plan_channels (mes, canal, meta_oport, verba, updated_at)
                   VALUES (%s,%s,%s,%s,now())
                   ON CONFLICT (mes, canal) DO UPDATE SET
                        meta_oport=COALESCE(EXCLUDED.meta_oport, mkt_plan_channels.meta_oport),
                        verba=COALESCE(EXCLUDED.verba, mkt_plan_channels.verba),
                        updated_at=now()""",
                (mes, canal, v.get("meta_oport"), v.get("verba")))
            n += 1
        # taxa-alvo por etapa: semeia o que o gestor ainda não editou no painel
        for (mes, etapa), t in taxas.items():
            cur.execute(
                """INSERT INTO mkt_funnel_goals (mes, etapa, taxa_meta, updated_at)
                   VALUES (%s,%s,%s,now()) ON CONFLICT (mes, etapa) DO NOTHING""",
                (mes, etapa, t))
            n += 1
    return n
