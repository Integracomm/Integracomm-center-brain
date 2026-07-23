# -*- coding: utf-8 -*-
"""Paridade do Lote 6 — HTML × payload, no MESMO instante.

Comparar dois RENDERS em momentos diferentes não serve: o dado é vivo (a rodada
diária atualiza speed-to-lead durante o dia) e a diferença aparece como se fosse
divergência de régua. Aqui o HTML e o payload saem da mesma execução, e o que se
compara é: cada número do payload APARECE no HTML renderizado?

Rodar de dentro de backend/:  python paridade_l6.py
"""
import datetime as dt
import re

import app.api as A

ok = fail = 0


def check(nome, cond, detalhe=""):
    global ok, fail
    ok, fail = ok + bool(cond), fail + (not cond)
    print(f"  [{'OK ' if cond else 'FALHA'}] {nome}" + (f"  — {detalhe}" if not cond and detalhe else ""))


def sem_tags(s):
    return re.sub(r"<[^>]+>", " ", s or "")


def num_br(v, casas=0):
    return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


class Req:
    query_params = {}


# ---------------------------------------------------------------- PV · SDRs
print("\n== Pré-vendas · Desempenho Individual (sdrs)")
from app.sales import ui as U
from app.sales.dados import pv_sdrs_dados

hoje = dt.date.today()
with A._conn() as c:
    U._ensure_touch(c)
    d = pv_sdrs_dados(c, hoje.replace(day=1), hoje)
    html = sem_tags(U._pv_sdrs(c, Req()))

for p in d["pessoas"]:
    check(f"pessoa {p['nome'][:24]}: leads {p['leads']}", str(p["leads"]) in html)
    check(f"pessoa {p['nome'][:24]}: oportunidades {p['oport']}", str(p["oport"]) in html)
check(f"total de leads {d['total']['leads']}", str(d["total"]["leads"]) in html)
check(f"total de oportunidades {d['total']['oport']}", str(d["total"]["oport"]) in html)
check(f"total de bookings {d['total']['book']}", str(d["total"]["book"]) in html)
if d["ex_colaboradores"]:
    check("linha (ex-colaboradores) presente", "(ex-colaboradores)" in html)
check(f"{len(d['colunas'])} colunas de SDR nos estudos cruzados", len(d["colunas"]) > 0)
for o in d["origens"][:4]:
    check(f"origem “{o['origem'][:20]}” no HTML", o["origem"][:26] in html)
for pl in d["planos"][:4]:
    check(f"plano {pl['plano']} no HTML", pl["plano"] in html)
for ai in d["acoes_individuais"]:
    check(f"plano de ação de {ai['nome'][:22]} no HTML", ai["nome"] in html)
    for t in (ai["fortes"] + ai["fracos"] + ai["acoes"])[:2]:
        check(f"   texto “{t[:34]}…”", sem_tags(t)[:34] in html)

print(f"\n=========== LOTE 6 · PARIDADE: {ok} OK · {fail} FALHA(S) ===========")
