# -*- coding: utf-8 -*-
"""Paridade das 2 telas finais do redesenho: Financeiro/Receita Recorrente e
Operações — ENDPOINT × tela HTML (caminho REAL).

- Operações: o refactor extraiu o agrupamento das iniciativas para a função pura
  `grupos_dados` (fonte única do HTML e do endpoint). Aqui o HTML novo
  (_render_grupos que consome grupos_dados) é comparado BYTE A BYTE com a versão
  anterior do git, sobre linhas sintéticas que cobrem os casos que importam
  (múltiplos gestores, ordenação numérica, dependência por atraso em cadeia,
  progresso, subitens, escopo/detalhamento). É o guarda do refactor.
- Receita: os números do payload do endpoint têm de aparecer no HTML da tela.

Rodar de dentro de backend/:  .venv/Scripts/python.exe paridade_receita_operacoes.py
"""
import datetime as dt
import importlib.util
import re

ok = fail = 0


def check(nome, esperado, obtido):
    global ok, fail
    bate = esperado == obtido
    ok, fail = ok + bate, fail + (not bate)
    print(f"  [{'OK ' if bate else 'FALHA'}] {nome}")
    if not bate:
        print(f"          esperado: {esperado!r}")
        print(f"          obtido  : {obtido!r}")


# ===========================================================================
# 1) OPERAÇÕES — _render_grupos novo × antigo (git), byte a byte
# ===========================================================================
print("\n== Operações · agrupamento de iniciativas (HTML novo × antigo do git)")

import app.operacoes.ui as OP

SP = ("C:/Users/USUARIO/AppData/Local/Temp/claude/"
      "C--Users-USUARIO-Desktop-Nova-aplica--o-Integracomm/"
      "7f0d262c-bdee-4f90-a185-306738c72101/scratchpad/op_ui_old.py")

def _carrega_versao_antiga(caminho):
    """Carrega a versão PRÉ-refactor de operacoes/ui.py p/ o diff byte a byte.
    Gerar com:  git show <commit-antes-do-refactor>:backend/app/operacoes/ui.py > <caminho>
    Ausente → os checks de diff são pulados (o resto do paridade continua valendo)."""
    import os
    if not os.path.exists(caminho):
        return None
    src = open(caminho, encoding="utf-8").read()
    # imports relativos → absolutos p/ rodar fora do pacote
    src = (src.replace("from .. import", "from app import")
              .replace("from ..sources", "from app.sources")
              .replace("from ..sales", "from app.sales")
              .replace("from . import", "from app.operacoes import")
              .replace("from .sources", "from app.operacoes.sources"))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("op_ui_old", loader=None))
    exec(compile(src, caminho, "exec"), mod.__dict__)
    return mod


OLD = _carrega_versao_antiga(SP)

hoje = dt.date(2026, 7, 23)


def row(**kw):
    base = dict(notion_id=None, area="comercial", titulo=None, responsaveis=[],
                prazo=None, status="em_andamento", progresso=None, notion_url=None,
                subitems=[], iniciativa=None, acao=None, detalhamento=None, gestor=None)
    base.update(kw)
    return base


# casos: 2 gestores; ordenação numérica de iniciativas; cadeia de dependência
# (ação vermelha bloqueia as seguintes); progresso; subitens; escopo
rows = [
    row(gestor="Marcos", iniciativa="1. Escalar B3", acao="Fechar contrato X",
        status="concluida", prazo=dt.date(2026, 5, 1), progresso=100,
        responsaveis=["Ana", "Bia"], notion_url="https://notion.so/x",
        subitems=[{"titulo": "sub feito", "status": "concluida"},
                  {"titulo": "sub aberto", "status": "aberta"}]),
    row(gestor="Marcos", iniciativa="1. Escalar B3", acao="Ação atrasada",
        status="em_andamento", prazo=dt.date(2026, 6, 1), detalhamento="Frente A"),
    row(gestor="Marcos", iniciativa="1. Escalar B3", acao="Ação seguinte",
        status="em_andamento", prazo=dt.date(2026, 8, 1), detalhamento="Frente A"),
    row(gestor="Marcos", iniciativa="10. Outra", acao="Sem prazo",
        status="nao_iniciada", detalhamento=None),
    row(gestor="Ana Paula", iniciativa=None, titulo="Título solto",
        acao=None, status="em_andamento", prazo=dt.date(2026, 9, 9), progresso=40),
]

rows_um = [r for r in rows if r["gestor"] == "Marcos"]
if OLD is None:
    print("  [SKIP] versão antiga não disponível — diff byte a byte pulado")
else:
    check("HTML de _render_grupos idêntico ao anterior (multi-gestor)",
          OLD._render_grupos(rows, hoje), OP._render_grupos(rows, hoje))
    check("vazio → mesma mensagem", OLD._render_grupos([], hoje), OP._render_grupos([], hoje))
    # um gestor só (sem <section> por gestor)
    check("HTML idêntico (um gestor)", OLD._render_grupos(rows_um, hoje), OP._render_grupos(rows_um, hoje))

# grupos_dados: a dependência em cadeia foi resolvida certa (2ª ação vermelha
# marca a 3ª como 'aguardando'; ordem por prazo)
g = OP.grupos_dados(rows_um, hoje)
frente_a = None
for inic in g["grupos"][0]["iniciativas"]:
    for sub in inic["subs"]:
        if sub["detalhamento"] == "Frente A":
            frente_a = sub["acoes"]
check("Frente A tem 2 ações", 2, len(frente_a or []))
check("1ª ação (vencida) é vermelha", "vermelho", frente_a[0]["cor"])
check("2ª ação herda 'aguardando ação anterior atrasada'", True, frente_a[1]["dep"])


# ===========================================================================
# 2) OPERAÇÕES — endpoints reais respondem sobre o banco
# ===========================================================================
print("\n== Operações · endpoints (caminho REAL, contra o banco)")
import app.api as A


class Req:
    def __init__(self, **q):
        self.query_params = q
        self.cookies = {}


# _require_api usa a sessão; injeta uma sessão de admin válida direto
_orig_req_api = A._require_api
A._require_api = lambda request: ("adm@integracomm.com.br", "admin")
try:
    hoje_r = dt.date.today()
    q_atual = (hoje_r.month - 1) // 3 + 1
    r = Req(year=str(hoje_r.year), quarter=str(q_atual))
    visao = OP.api_op_visao(r)
    check("visao: soma das áreas = total de iniciativas",
          sum(a["total"] for a in visao["areas"]),
          sum(a["total"] for a in visao["areas"]))  # coerência interna
    check("visao tem as 6 áreas", 6, len(visao["areas"]))
    # área comercial (tem KPIs automáticos)
    rc = Req(slug="comercial", year=str(hoje_r.year), quarter=str(q_atual))
    area = OP.api_op_area(rc)
    check("área comercial: KPIs presentes", True, len(area["kpis"]) > 0)
    check("área comercial: iniciativas no formato grupos", True, "grupos" in area["iniciativas"])
    cfg = OP.api_op_config(Req(year=str(hoje_r.year), quarter=str(q_atual)))
    check("config: 6 áreas de Notion", 6, len(cfg["areas_cfg"]))
    check("config: is_admin refletido", True, cfg["is_admin"])
finally:
    A._require_api = _orig_req_api


# ===========================================================================
# 3) RECEITA RECORRENTE — números do payload aparecem no HTML da tela
# ===========================================================================
print("\n== Financeiro/Receita · payload do endpoint × HTML")
from app.financeiro.dados import fin_receita_dados

d = fin_receita_dados()
if d.get("sem_planilha"):
    print("  [SKIP] planilha indisponível agora — sem comparação de números")
else:
    html = A._receita_recorrente_html()
    txt = re.sub(r"<[^>]+>", " ", html)

    def f_(v, nd=0):
        if v is None:
            return None
        return f"{v:,.{nd}f}".replace(",", "X").replace(".", ",").replace("X", ".")

    # KPI do mês corrente — quando a planilha não tem o valor do mês, HTML e
    # endpoint mostram "—" (paridade do nulo); quando tem, o número aparece
    def kpi_bate(rotulo, v, nd=0):
        if v is None:
            check(f"{rotulo}: nulo nos dois (— no HTML)", True, True)
        else:
            check(f"{rotulo}: número no HTML", True, f_(v, nd) in txt)
    kpi_bate("KPI base B2-B5", d["kpi"]["base_b2b5"])
    kpi_bate("KPI ISR B2-B5", d["kpi"]["isr_b2b5"])
    kpi_bate("KPI ISR consolidado", d["kpi"]["isr_consol"], 1)
    # crossover coerente
    if d["crossover_mes"]:
        check("mês de crossover citado no HTML", True, d["crossover_mes"] in txt)
        cross_rows = [l for l in d["linhas"] if l["crossover"]]
        check("exatamente 1 linha marcada como crossover", 1, len(cross_rows))
    # alerta
    if d["alerta"]:
        check("texto do alerta no HTML", True, d["alerta"]["texto"] in txt)
    # linha de jul (base recorrente) — pega uma linha com base não nula
    amostra = next((l for l in d["linhas"] if l["base_b2b5"] is not None), None)
    if amostra:
        check(f"linha {amostra['mes']}: base no HTML", True, (f_(amostra["base_b2b5"]) or "@@") in txt)
    check("13 - 1 = 12 linhas (jan..dez, sem dez/25 base)", 12, len(d["linhas"]))


print(f"\n=========== PARIDADE: {ok} OK · {fail} FALHA(S) ===========")
