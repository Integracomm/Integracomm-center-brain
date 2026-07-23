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


# --------------------------------------------------------- Vendas · closers
print("\n== Vendas · Desempenho Individual (closers)")
from app.sales.dados import vd_closers_dados

with A._conn() as c:
    dc = vd_closers_dados(c, hoje.replace(day=1), hoje)
    html_c = sem_tags(U._vd_closers(c, Req()))

if dc["sem_dados"]:
    check("closers: sem dados no periodo (aviso na tela)", "atribui" in html_c)
else:
    for p in dc["pessoas"]:
        check(f"closer {p['nome'][:22]}: oports {p['oports']} · bookings {p['bookings']}",
              str(p["oports"]) in html_c and str(p["bookings"]) in html_c)
        if p["papel_label"]:
            check(f"   chip “{p['papel_label']}”", p["papel_label"] in html_c)
    for pl in dc["planos_bundle"][:4]:
        check(f"plano {pl['plano']} na grade por closer", pl["plano"] in html_c)
    for lin in dc["horas"][:3]:
        check(f"reunioes de {lin['nome'][:20]}: total {lin['total']}", str(lin["total"]) in html_c)
    for ai in dc["acoes_individuais"]:
        check(f"plano de acao de {ai['nome'][:20]}", ai["nome"] in html_c)

# -------------------------------------------------------- Vendas · forecast
print("\n== Vendas · Performance & Meta (forecast)")
from app.sales.dados import vd_forecast_dados

with A._conn() as c:
    df = vd_forecast_dados(c, hoje.replace(day=1))
    html_f = sem_tags(U._vd_forecast(c, Req()))

for l in df["linhas"]:
    check(f"{l['plano']}: meta {l['meta_q']:.0f} × fechado {l['real_q']}",
          f"{l['meta_q']:.0f}" in html_f and str(l["real_q"]) in html_f)
check(f"TOTAL fechado {df['total']['real_q']}", str(df["total"]["real_q"]) in html_f)
check(f"TOTAL gap {df['total']['gap']:.0f}", f"{df['total']['gap']:.0f}" in html_f)
for f_ in df["faltantes"][:3]:
    check(f"falta {f_['plano']}: {f_['gap']:.0f} bookings", f"{f_['gap']:.0f}" in html_f)
check("mes corrente marcado", isinstance(df["corrente"], bool))


# -------------------------------------------------------- Vendas · horarios
print("\n== Vendas · Melhor Horario (horarios)")
from app.sales.dados import vd_horarios_dados

with A._conn() as c:
    dh = vd_horarios_dados(c, hoje.replace(day=1), hoje)
    html_h = sem_tags(U._vd_horarios(c, Req()))

if dh["sem_dados"]:
    check("horarios: aviso de sem reunioes", "sem reuni" in html_h)
else:
    k = dh["kpis"]
    check(f"reunioes no periodo {k['reunioes']}", str(k["reunioes"]) in html_h)
    check(f"ganhas {k['won']} de {k['decididas']} decididas",
          str(k["won"]) in html_h and str(k["decididas"]) in html_h)
    check(f"em aberto {k['abertas']}", str(k["abertas"]) in html_h)
    if k["melhor_hora"] is not None:
        check(f"melhor hora {k['melhor_hora']:02d}h", f"{k['melhor_hora']:02d}h" in html_h)
    for ph in dh["por_hora"][:5]:
        check(f"hora {ph['hora']:02d}h com {ph['reunioes']} reunioes",
              f"{ph['hora']:02d}h" in html_h and str(ph["reunioes"]) in html_h)
    check("ressalva de amostra pequena coerente com os dados",
          ("amostra pequena" in html_h) == any(x["amostra_pequena"] for x in dh["por_hora"]))


# ------------------------------------------------------------ Growth · aba
print("\n== Growth · Playbooks e Relatorios")

with A._conn() as c:
    practices = A._top_practices(c)
    interv = A._recent_interventions(c)
    html_pb = sem_tags(A._playbooks_content(practices, interv))
    scores = A._latest_scores(c)
    rep = A._report_from(scores, A._open_alerts(c))
    html_rel = sem_tags(A._relatorios_content(rep, scores))

if practices:
    for d_, (acao, n) in list(practices.items())[:4]:
        check(f"pratica “{acao[:26]}” ({n}x)", acao[:26] in html_pb)
else:
    check("playbooks: estado vazio COM caminho (nao so 'sem dados')",
          "Registre as ações" in html_pb)
for i in interv[:3]:
    check(f"acao recente em “{(i.get('name') or '')[:22]}”",
          (i.get("name") or "")[:22] in html_pb)

# Relatorios: o resumo e o MESMO _report_from do envio ao Slack
check(f"monitoradas {rep['monitoradas']}", str(rep["monitoradas"]) in html_rel)
check(f"avaliaveis {rep['avaliaveis']}", str(rep["avaliaveis"]) in html_rel)
check(f"alertas abertos {rep['alertas_total']}", str(rep["alertas_total"]) in html_rel)
check(f"MRR em risco {rep['mrr_risco']:.0f}",
      f"{rep['mrr_risco']:,.0f}".replace(",", ".") in html_rel)
check(f"execucao critica {rep['exec_atrasada']}", str(rep["exec_atrasada"]) in html_rel)
for pior in rep["piores"][:3]:
    check(f"pior conta “{pior['nome'][:24]}”", pior["nome"][:24] in html_rel)
for grupo, dist in (("faixa", rep["faixa"]), ("estagio", rep["estagio"]),
                    ("trajetoria", rep["trajetoria"])):
    tot = sum(dist.values())
    check(f"distribuicao de {grupo}: {tot} contas somadas", tot > 0)
check("botao de envio ao Slack presente no HTML", "Enviar ao Slack" in html_rel)


# ------------------------------------------------- Growth · Analise dos Squads
print("\n== Growth · Analise dos Squads (carga)")
from app.growth_carga import carga_dados

with A._conn() as c:
    _scores = A._latest_scores(c)
    dcg = carga_dados(c, _scores, None)
    html_cg = sem_tags(A._carga_content(_scores, None))

for r in dcg["ranking"][:5]:
    check(f"squad {r['squad'][:14]}: {r['contas']} contas", str(r["contas"]) in html_cg)
    if r["concentra_risco"]:
        check(f"   selo de concentracao em {r['squad'][:12]}", "concentração de risco" in html_cg)
for cp in dcg["capacidade"][:5]:
    if cp["contas_pessoa"] is not None:
        check(f"capacidade {cp['squad'][:14]}: {cp['contas_pessoa']:.1f} contas/pessoa",
              f"{cp['contas_pessoa']:.1f}" in html_cg)
    if cp["estado"]:
        check(f"   estado “{cp['estado']}” marcado", cp["estado"] in html_cg)
check("leitura da capacidade presente", dcg["leitura_capacidade"][:40] in html_cg)
check("leitura dos atrasos presente", dcg["leitura_atrasos"][:40] in html_cg)
for a_ in dcg["atrasos_squad"][:4]:
    if a_["tarefas"]:
        check(f"atrasos {a_['squad'][:14]}: {a_['tarefas']} tarefas", str(a_["tarefas"]) in html_cg)
    if a_["diagnostico"]:
        rot = "capacidade" if a_["diagnostico"] == "capacidade" else "ritmo/processo"
        check(f"   diagnostico “{rot}” em {a_['squad'][:12]}", rot in html_cg)
for r_ in dcg["atrasos_responsavel"][:3]:
    check(f"responsavel {r_['responsavel'][:20]}: {r_['tarefas']} tarefas",
          r_["responsavel"][:20] in html_cg)
# as ressalvas do que ficou FORA da conta sao parte do numero
if dcg["atrasos_inativos"]:
    check("ressalva de clientes pausados/concluidos", "pausado(s) por inadimplência" in html_cg)
if dcg["atrasos_duplicados"]:
    check("ressalva de tarefa em 2+ contas do mesmo cliente",
          "mais de uma conta" in html_cg)
if dcg["atrasos_sem_squad"]:
    check("ressalva de contas sem squad", "sem squad" in html_cg)
check("correlacao carga x atraso calculada (ou None com <3 squads)",
      dcg["correlacao_carga_atraso"] is None or -1 <= dcg["correlacao_carga_atraso"] <= 1)

print(f"\n=========== LOTE 6 · PARIDADE: {ok} OK · {fail} FALHA(S) ===========")
