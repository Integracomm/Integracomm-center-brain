# -*- coding: utf-8 -*-
"""Paridade da Central nova (redesenho 22/07).

Protocolo dos lotes anteriores: a fonte de verdade é a tela HTML (`_render_hub`),
que não foi tocada pelo redesenho. Cada número que a Central nova exibe é
comparado com o que o HTML renderiza AGORA, com os mesmos dados.

Rodar de dentro de backend/:  python paridade_central.py
"""
import re
import app.api as A
from app.raiox import mini_cards_dados, mini_cards_html
from app.semana import objetivos_com_impacto, _impacto_objetivo, _seg, _objetivos

ok = fail = 0


def check(nome, esperado, obtido):
    global ok, fail
    bate = esperado == obtido
    ok, fail = ok + bate, fail + (not bate)
    print(f"  [{'OK ' if bate else 'FALHA'}] {nome}")
    if not bate:
        print(f"          HTML/fonte: {esperado!r}")
        print(f"          Central nova: {obtido!r}")


def sem_tags(s):
    return re.sub(r"<[^>]+>", "", s or "").strip()


with A._conn() as c:
    stats = A._hub_stats(c)
    mkt, sales, ops = A._hub_mkt_stats(c), A._hub_sales_stats(c), A._hub_op_stats(c)
    try:
        from app.marketing.ui import _ciclo_coorte
        coorte = _ciclo_coorte(c)[0]
    except Exception:
        coorte = None
    impactos = A._hub_impactos(c, mkt, sales, coorte=coorte)
    lags = A._hub_lags(c, coorte=coorte)
    saude = A._hub_saude(stats, mkt, sales)

    print("\n== 1. KPIs do mês (HTML × payload da Central nova)")
    kpis = A._hub_kpis(stats, mkt, sales)
    html = A._render_hub("x@y", stats, [], mkt, sales=sales, ops=ops,
                         impactos=impactos, lags=lags)
    # cada KPI do HTML é um bloco <div class=kpi> — fatiar por bloco evita o
    # regex guloso atravessar de um KPI para o outro
    blocos = {}
    for bloco in html.split("<div class=kpi>")[1:]:
        mv = re.search(r"<div class=n[^>]*>(.*?)</div>\s*<div class=l>([^<]+)</div>", bloco, re.S)
        if mv:
            blocos[sem_tags(mv.group(2))] = sem_tags(mv.group(1))
    for k in kpis:
        val_html = blocos.get(k["rotulo"], "(não achado)")
        if k["formato"] == "brl":
            esperado = A._fmt_brl(k["valor"])
        elif k["meta"] is not None:
            esperado = f"{k['valor']:,.0f}".replace(",", ".") + "/" + f"{k['meta']:,.0f}".replace(",", ".")
        else:
            esperado = f"{k['valor']:,.0f}".replace(",", ".")
        check(f"KPI {k['rotulo']}", esperado, val_html.replace(" ", ""))

    print("\n== 2. Saúde por área (nível e motivo)")
    for area, (nivel, motivo) in saude.items():
        m = re.search(r"class=hn>([^·]+)· <span[^>]*>([^<]+)</span>.*?class=hm>(.*?)</div>",
                      html, re.S)
        # confere que o motivo exato aparece no HTML
        check(f"saúde/{area}: motivo presente no HTML", True, motivo in sem_tags(html))
        check(f"saúde/{area}: rótulo do nível", A._NIVEL[nivel][1],
              A._NIVEL[saude[area][0]][1])

    print("\n== 3. Cards de área (cada métrica no HTML)")
    for cd in A._hub_area_cards(stats, mkt, sales, ops, saude):
        for mtr in cd["metricas"]:
            if mtr["texto"] is not None:
                alvo = mtr["texto"]
            elif mtr["formato"] == "brl":
                alvo = A._fmt_brl(mtr["valor"]) if mtr["valor"] is not None else "—"
            elif mtr["formato"] in ("pct1",):
                alvo = f"{mtr['valor'] * 100:.1f}%" if mtr["valor"] is not None else "—"
            elif mtr["formato"] in ("pct0",):
                alvo = f"{mtr['valor'] * 100:.0f}%" if mtr["valor"] is not None else "—"
            elif mtr["formato"] == "pctp":
                alvo = f"{mtr['valor']:.0f}%" if mtr["valor"] is not None else "—"
            else:
                alvo = f"{mtr['valor']:,.0f}".replace(",", ".") if mtr["valor"] is not None else "—"
            check(f"{cd['nome']} · {mtr['rotulo']}", True, alvo in sem_tags(html))

    print("\n== 4. Raio-X por bundle (dados × HTML da seção)")
    cards, nota = mini_cards_dados(c, coorte or [])
    rx_html = sem_tags(mini_cards_html(c, coorte or []))
    for b in cards:
        txt = f"{b['bookings']}/{b['meta']:.0f}" if b["meta"] else f"{b['bookings']}"
        check(f"bundle {b['bundle']} bookings×meta", True, txt in rx_html)
        if b["churn_precoce"] is not None:
            check(f"bundle {b['bundle']} churn precoce",
                  True, f"{b['churn_precoce'] * 100:.0f}% churn precoce" in rx_html)
    check("B5 com aviso de coorte pequena", True,
          any(b["bundle"] == "B5" and b["aviso"] for b in cards))
    check("nota dos bundles preenchida", True, bool(nota))

    print("\n== 5. Iniciativas de horizonte (mesma lista e mesma ordem)")
    week = _seg()
    objs_conf = [o for o in _objetivos(c, week) if o["status"] == "confirmado"]
    foco_kw = [o["title"].lower() for o in objs_conf]
    horiz = A._hub_horizonte(stats, mkt, sales, impactos, lags, foco_kw)
    for it in horiz:
        check(f"horizonte: {it['titulo'][:38]}", True, it["titulo"] in sem_tags(html))
    check("horizonte: ordenado por impacto desc",
          sorted([(h["faixa"][1] if h["faixa"] else -1) for h in horiz], reverse=True),
          [(h["faixa"][1] if h["faixa"] else -1) for h in horiz])

    print("\n== 6. Campo `impacto` novo × o que a Central já mostrava")
    api_objs = {o["title"]: o["impacto"] for o in objetivos_com_impacto(c, week)}
    for o in objs_conf:
        antigo = _impacto_objetivo(c, o, impactos)
        novo = api_objs.get(o["title"])
        esperado = ({"min": float(antigo["faixa"][0]), "max": float(antigo["faixa"][1]),
                     "premissa": antigo["premissa"]} if antigo and antigo.get("faixa") else None)
        check(f"impacto de “{o['title'][:32]}”", esperado, novo)

print(f"\n=========== PARIDADE: {ok} OK · {fail} FALHA(S) ===========")
