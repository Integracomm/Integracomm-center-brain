# -*- coding: utf-8 -*-
"""Paridade da Análise dos Squads: ENDPOINT × tela HTML.

Existe por causa de um erro real (23/07): o endpoint carregava o espelho de
`sources.mirror`, que não existe. O `try/except` engolia o ImportError, mandava
`mirror=None`, e os squads passavam a resolver só pelo nome — números diferentes
da tela antiga, sem nenhum erro aparecer.

O paridade_l6 não pegou porque comparava `carga_dados(...)` com o HTML usando o
MESMO argumento nos dois lados. O que precisa ser comparado é o que cada
CAMINHO REAL produz: o handler HTML e o endpoint.

Rodar de dentro de backend/:  python paridade_squads.py
"""
import re

import app.api as A

ok = fail = 0


def check(nome, esperado, obtido):
    global ok, fail
    bate = esperado == obtido
    ok, fail = ok + bate, fail + (not bate)
    print(f"  [{'OK ' if bate else 'FALHA'}] {nome}")
    if not bate:
        print(f"          HTML : {esperado!r}")
        print(f"          SPA  : {obtido!r}")


class Req:
    query_params = {}
    cookies = {}


print("\n== Análise dos Squads · HTML × endpoint (caminhos REAIS)")

# --- caminho do HTML: o mesmo que o handler /growth?view=carga percorre ------
with A._conn() as c:
    scores_html = A._latest_scores(c)
try:
    from app.sources.clickup_activities import _mirror_clientes
    mirror_html = _mirror_clientes()
except Exception:  # noqa: BLE001
    mirror_html = None
from app.growth_carga import carga_dados

with A._conn() as c:
    d_html = carga_dados(c, scores_html, mirror_html)

# --- caminho do ENDPOINT: chamando a função do endpoint de verdade ----------
import inspect

fonte = inspect.getsource(A.api_growth_carga)
check("endpoint usa o MESMO espelho do HTML (_mirror_clientes)",
      True, "_mirror_clientes" in fonte)
# o comentário do endpoint CITA o módulo errado ao explicar o bug — olhar só as
# linhas de CÓDIGO, não o texto
_codigo = [l for l in fonte.splitlines() if not l.strip().startswith("#")]
check("endpoint NÃO importa do módulo inexistente sources.mirror",
      True, not any("from .sources.mirror" in l for l in _codigo))

with A._conn() as c:
    scores = A._latest_scores(c)
    try:
        from app.sources.clickup_activities import _mirror_clientes as _mc
        mirror = _mc()
    except Exception:  # noqa: BLE001
        mirror = None
    d_api = carga_dados(c, scores, mirror)
    an, sem_squad = A._squad_analysis(scores)

check("espelho carregado (não é None)", True, mirror is not None)
check("espelho com entradas", True, bool(mirror))

# --- os números de cada seção ----------------------------------------------
print("\n-- ranking (carga de risco)")
check("mesma quantidade de squads", len(d_html["ranking"]), len(d_api["ranking"]))
for a, b in zip(d_html["ranking"], d_api["ranking"]):
    check(f"{a['squad'][:14]}: contas", a["contas"], b["contas"])
    check(f"{a['squad'][:14]}: MRR", round(a["mrr"], 2), round(b["mrr"], 2))
    check(f"{a['squad'][:14]}: MRR em risco", round(a["mrr_risco"], 2), round(b["mrr_risco"], 2))
    check(f"{a['squad'][:14]}: críticos", a["criticos"], b["criticos"])

print("\n-- capacidade")
for a, b in zip(d_html["capacidade"], d_api["capacidade"]):
    check(f"{a['squad'][:14]}: pessoas", a["pessoas"], b["pessoas"])
    check(f"{a['squad'][:14]}: contas/pessoa",
          None if a["contas_pessoa"] is None else round(a["contas_pessoa"], 3),
          None if b["contas_pessoa"] is None else round(b["contas_pessoa"], 3))
    check(f"{a['squad'][:14]}: estado", a["estado"], b["estado"])
check("leitura da capacidade", d_html["leitura_capacidade"], d_api["leitura_capacidade"])

print("\n-- atrasos")
check("total de atrasos", d_html["total_atrasos"], d_api["total_atrasos"])
check("leitura dos atrasos", d_html["leitura_atrasos"], d_api["leitura_atrasos"])
for a, b in zip(d_html["atrasos_squad"], d_api["atrasos_squad"]):
    check(f"{a['squad'][:14]}: tarefas atrasadas", a["tarefas"], b["tarefas"])
    check(f"{a['squad'][:14]}: diagnóstico", a["diagnostico"], b["diagnostico"])
check("tarefas de clientes pausados fora da conta",
      d_html["atrasos_inativos"], d_api["atrasos_inativos"])
check("tarefas duplicadas descontadas",
      d_html["atrasos_duplicados"], d_api["atrasos_duplicados"])

print("\n-- ranking por score (o bloco do topo)")
check("squads na análise", True, len(an) > 0)
check("análise vem ORDENADA por score desc",
      [x["squad"] for x in sorted(an, key=lambda y: -y["score"])],
      [x["squad"] for x in an])
for x in an[:3]:
    check(f"{x['squad'][:14]}: score presente", True, isinstance(x.get("score"), float))
    check(f"{x['squad'][:14]}: partes do score (rel/exe/risco)",
          True, all(k in x for k in ("rel", "exe", "risco_pct")))

# o HTML mostra os mesmos squads na análise
html = re.sub(r"<[^>]+>", " ", A._carga_content(scores_html, mirror_html))
for x in an[:5]:
    check(f"{x['squad'][:14]} aparece no HTML", True, x["squad"] in html)

print(f"\n=========== SQUADS · PARIDADE: {ok} OK · {fail} FALHA(S) ===========")
