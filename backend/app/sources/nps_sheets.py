"""Leitor das planilhas de NPS/Faturamento (Google Sheets, API pública gviz/export).

Planilha MESTRE (aba "NPS De Omie para Clikup"): coluna A = Razão Social (Omie),
coluna B = nome no ClickUp (`NOME | RESPONSÁVEL`), coluna C = link da planilha
individual do cliente (ou um status tipo "Falta planilha" / "Contrato cancelado").

Planilha INDIVIDUAL (estrutura observada nas planilhas reais — varia um pouco
entre clientes, o parser é posicional pelos rótulos, não por número de linha):
  - uma linha de cabeçalho `Cliente | Equipe | GC Responsável | Plano | Início...`
    seguida da linha de dados do cliente;
  - uma linha `Mês` com os meses (Jan..Dez, repetindo a cada ano);
  - blocos por CNPJ: linha `CNPJ <rótulo>` → linha `Faturamento` → uma linha por
    marketplace (Mercado Livre, Shopee, ...) com valores `R$ x.xxx,xx` por mês.

ANO dos meses: o cabeçalho não traz ano; assumimos que a 1ª coluna `Jan` é
janeiro do ano de INÍCIO do contrato (campo `Início` da linha do cliente) e o
ano avança quando o mês "dá a volta" (…Dez, Jan…). Fallback: 2025 (início do
programa de NPS). A origem do ano vai em `base_year_source` para auditoria.

Acesso: leitura pública (planilhas compartilhadas por link). Usamos
`export?format=csv` para as individuais (preserva linhas/colunas vazias — o
gviz descarta linhas vazias e desalinha os meses) e gviz para a mestre (o
export exige gid; a mestre é referenciada por NOME de aba).
"""
from __future__ import annotations

import csv
import io
import re
import time
import unicodedata
from typing import Any

import httpx

MASTER_SHEET_ID = "1jyRXf04W7ThSW7KCzYthK84MdbiI4fx1Gg21g-AnrVw"
MASTER_TAB = "NPS De Omie para Clikup"

_MONTHS = {"jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
           "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12}
# rótulos de métricas que aparecem entre `Mês` e os blocos de faturamento
_METRIC_LABELS = {"nps gc", "demandas executadas", "demandas em horas",
                  "atendimento", "configuracao finalizada", "qt cnpj", "mes"}
_SHEET_URL_RE = re.compile(r"docs\.google\.com/spreadsheets/d/([A-Za-z0-9_-]+)")
_GID_RE = re.compile(r"[?#&]gid=(\d+)")

_TTL = 600.0  # cache em memória (a planilha muda 1x/mês; relatório é sob demanda)
_cache: dict[str, tuple[float, Any]] = {}


def norm_account(s: str | None) -> str:
    """Chave de match entre fontes — MESMA regra do run_portfolio.norm():
    remove `[tag]`, fica com a parte antes do 1º `|`, tira 'integracomm',
    acentos e pontuação. Ex.: '[ST-B1-S2] SWEET LIFE | MARCELO ID: 9' -> 'sweet life'."""
    if not s:
        return ""
    x = unicodedata.normalize("NFD", s.lower())
    x = "".join(c for c in x if unicodedata.category(c) != "Mn")
    x = re.sub(r"^\s*\[[^\]]*\]\s*", "", x).split("|")[0].replace("integracomm", "")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", x)).strip()


def norm_full(s: str | None) -> str:
    """Como norm_account, mas preservando TODOS os segmentos (nome + responsável)
    — desempata clientes homônimos ('LIDER 3D | IVAN' vs 'LIDER 3D | JOSÉ')."""
    if not s:
        return ""
    x = unicodedata.normalize("NFD", s.lower())
    x = "".join(c for c in x if unicodedata.category(c) != "Mn")
    x = re.sub(r"^\s*\[[^\]]*\]\s*", "", x)
    x = re.sub(r"\bid\s*:\s*[a-z0-9_-]+", "", x).replace("integracomm", "")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", x)).strip()


def _get_cached(key: str, fn):
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < _TTL:
        return hit[1]
    val = fn()
    _cache[key] = (time.monotonic(), val)
    return val


def _fetch_csv(url: str, params: dict | None = None) -> list[list[str]]:
    with httpx.Client(timeout=45.0, follow_redirects=True) as cli:
        r = cli.get(url, params=params)
        r.raise_for_status()
        text = r.content.decode("utf-8-sig", errors="replace")
    return list(csv.reader(io.StringIO(text)))


def master_rows() -> list[dict]:
    """Linhas da planilha mestre: [{razao_social, clickup_name, link_raw,
    sheet_id|None, gid|None}]. Cacheada por 10 min."""
    def load():
        url = f"https://docs.google.com/spreadsheets/d/{MASTER_SHEET_ID}/gviz/tq"
        rows = _fetch_csv(url, {"tqx": "out:csv", "sheet": MASTER_TAB})
        out = []
        for r in rows[1:]:  # linha 0 = cabeçalho
            if len(r) < 2 or not (r[0].strip() or r[1].strip()):
                continue
            link = (r[2] if len(r) > 2 else "").strip()
            m = _SHEET_URL_RE.search(link)
            g = _GID_RE.search(link)
            out.append({
                "razao_social": r[0].strip(), "clickup_name": r[1].strip(),
                "link_raw": link, "sheet_id": m.group(1) if m else None,
                "gid": g.group(1) if g else None,
            })
        return out
    return _get_cached("master", load)


def find_master_row(account_name: str) -> tuple[dict | None, str]:
    """Casa a conta (nome do banco = padrão ClickUp/WhatsApp) com a coluna B da
    mestre. Retorna (linha|None, nota_de_match) — a nota documenta matches não
    exatos, como pede a regra de negócio."""
    rows = [r for r in master_rows() if r["clickup_name"]]
    full, base = norm_full(account_name), norm_account(account_name)

    exact = [r for r in rows if norm_full(r["clickup_name"]) == full]
    if len(exact) == 1:
        return exact[0], "match exato (nome + responsável)"
    by_base = [r for r in rows if norm_account(r["clickup_name"]) == base]
    if by_base:
        with_link = [r for r in by_base if r["sheet_id"]] or by_base
        note = "match pelo nome-base"
        if len(by_base) > 1:
            note += f" (AMBÍGUO: {len(by_base)} linhas na mestre; usada a 1ª com link)"
        return with_link[0], note
    if len(base) >= 5:
        contains = [r for r in rows
                    if base in norm_account(r["clickup_name"]) or norm_account(r["clickup_name"]) in base]
        if contains:
            with_link = [r for r in contains if r["sheet_id"]] or contains
            return with_link[0], f"match parcial (contém) com “{with_link[0]['clickup_name']}”"
    return None, "conta não encontrada na planilha mestre"


def _parse_brl(v: str | None) -> float | None:
    if not v:
        return None
    x = re.sub(r"[^\d,.\-]", "", str(v))
    if not x or x in ("-", ".", ","):
        return None
    x = x.replace(".", "").replace(",", ".")
    try:
        return float(x)
    except ValueError:
        return None


def _norm_label(s: str) -> str:
    x = unicodedata.normalize("NFD", (s or "").lower().strip())
    return "".join(c for c in x if unicodedata.category(c) != "Mn")


def parse_individual_csv(rows: list[list[str]]) -> dict:
    """Parser puro da planilha individual (grade CSV -> estrutura). Testável
    offline; ver docstring do módulo para as convenções assumidas."""
    info: dict[str, str | None] = {}
    months: list[tuple[int, str]] = []  # (índice da coluna, 'YYYY-MM')
    base_year_source = "fallback 2025"

    # --- linha do cliente (cabeçalho `Cliente ...` + 1ª linha de dados) ---
    hdr_map: dict[str, int] = {}
    hdr_i = None
    for i, r in enumerate(rows):
        if r and _norm_label(r[0]).startswith("cliente"):
            for j, cell in enumerate(r):
                lbl = _norm_label(cell)
                for key, want in (("cliente", "cliente"), ("equipe", "equipe"),
                                  ("gc", "gc"), ("plano", "plano"), ("inicio", "inicio"),
                                  ("termino", "termino"), ("status", "status")):
                    if lbl.startswith(want) and key not in hdr_map:
                        hdr_map[key] = j
            hdr_i = i
            break
    if hdr_i is not None:
        for r in rows[hdr_i + 1:hdr_i + 6]:
            vals = {k: (r[j].strip() if j < len(r) else "") for k, j in hdr_map.items()}
            if any(vals.values()):
                info = {k: (v or None) for k, v in vals.items()}
                break

    # --- meses: ano-base vem (1) de uma linha de ANO acima do `Mês` (algumas
    # planilhas trazem "2025" solto ali), (2) do ano do Início, (3) fallback 2025;
    # avança quando o mês dá a volta (…Dez, Jan…). ---
    base_year = 2025
    m = re.search(r"(20\d\d)", info.get("inicio") or "")
    if m:
        base_year, base_year_source = int(m.group(1)), f"ano do Início ({info['inicio']})"
    mes_i = None
    for i, r in enumerate(rows):
        if r and _norm_label(r[0]) in ("mes", "mês"):
            mes_i = i
            break
    if mes_i is not None:
        for r in rows[max(0, mes_i - 3):mes_i]:
            years = [c.strip() for c in r if re.fullmatch(r"20\d\d", c.strip())]
            if years:
                base_year, base_year_source = int(years[0]), "linha de ano da planilha"
                break
    if mes_i is not None:
        year, prev_num = base_year, 0
        for j, cell in enumerate(rows[mes_i][1:], start=1):
            num = _MONTHS.get(_norm_label(cell)[:3])
            if not num:
                continue
            if num <= prev_num:
                year += 1
            prev_num = num
            months.append((j, f"{year:04d}-{num:02d}"))

    # --- blocos de CNPJ / faturamento por marketplace ---
    cnpjs: list[dict] = []
    current_label: str | None = None
    block: dict | None = None
    if mes_i is not None:
        for r in rows[mes_i + 1:]:
            c0 = (r[0] if r else "").strip()
            n0 = _norm_label(c0)
            if not c0:
                continue
            if n0.startswith("cnpj") and n0 != "qt cnpj":
                current_label = c0[4:].strip(" :-") or None
                block = None
                continue
            if n0 == "faturamento":
                block = {"cnpj": current_label, "marketplaces": {}}
                cnpjs.append(block)
                continue
            if n0 in _METRIC_LABELS or n0.startswith("qt cnpj") or n0.startswith("demandas"):
                block = None
                continue
            if block is not None:
                if "total" in n0:
                    continue
                vals = {iso: _parse_brl(r[j]) for j, iso in months if j < len(r)}
                block["marketplaces"][c0] = vals

    return {"info": info, "months": [iso for _, iso in months],
            "base_year_source": base_year_source, "cnpjs": cnpjs}


def fetch_individual(sheet_id: str, gid: str | None = None) -> dict:
    """Baixa e parseia a planilha individual. Levanta httpx.HTTPStatusError se a
    planilha não for pública (401/403) — o chamador converte em aviso."""
    def load():
        url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export"
        params = {"format": "csv"}
        if gid:
            params["gid"] = gid
        return parse_individual_csv(_fetch_csv(url, params))
    return _get_cached(f"indiv:{sheet_id}:{gid}", load)


def faturamento_compare(parsed: dict, ref_month: str, prev_month: str) -> list[dict]:
    """Comparativo mês de referência × anterior, por CNPJ e marketplace.
    [{cnpj, rows: [{marketplace, ref, prev, delta_abs, delta_pct}], total_ref,
    total_prev, ref_lancado}]. `ref_lancado=False` = célula VAZIA no mês de
    referência (planilha ainda não atualizada) — diferente de R$ 0,00 lançado."""
    out = []
    for b in parsed.get("cnpjs", []):
        rows, t_ref, t_prev = [], 0.0, 0.0
        for mkt, vals in b["marketplaces"].items():
            ref, prev = vals.get(ref_month), vals.get(prev_month)
            if ref is None and prev is None:
                continue
            d_abs = (ref - prev) if (ref is not None and prev is not None) else None
            d_pct = (d_abs / prev * 100) if (d_abs is not None and prev) else None
            rows.append({"marketplace": mkt, "ref": ref, "prev": prev,
                         "delta_abs": d_abs, "delta_pct": d_pct})
            t_ref += ref or 0.0
            t_prev += prev or 0.0
        if rows:
            out.append({"cnpj": b["cnpj"], "rows": rows,
                        "total_ref": t_ref, "total_prev": t_prev,
                        "ref_lancado": any(r["ref"] is not None for r in rows)})
    return out
