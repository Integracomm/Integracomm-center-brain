"""Agentes ESPECIALISTAS de Pré-vendas e Vendas — v1 determinística.

Padrão do projeto (igual ao plano CS sênior do Growth): persona veterana de
e-commerce/marketplaces assina diagnósticos gerados por REGRAS explícitas,
comparando cada pessoa com a mediana do time. Quando houver créditos de API,
o mesmo gancho troca o template por análise redigida pelo Claude — a estrutura
de dados não muda. Tom construtivo: apontar quem precisa de suporte e quem
pode ensinar (decisão do Otávio no spec — sem ranking punitivo).
"""
from __future__ import annotations

import statistics as st

PERSONA_PREVENDAS = ("Especialista de Pré-vendas — persona: head de SDR com 15+ anos em "
                     "funis de e-commerce/marketplaces (regras determinísticas; análise "
                     "via Claude entra quando houver créditos de API)")
PERSONA_VENDAS = ("Especialista Comercial — persona: head de vendas com 15+ anos fechando "
                  "contratos de serviços para sellers de marketplace (regras determinísticas; "
                  "análise via Claude entra quando houver créditos de API)")

# times validados pelo Otávio (08/07/26); desligados ficam no histórico mas
# fora de rankings e planos correntes
COORD_PREVENDAS = "Eduarda"
SDRS = ["Giovana Moura Alves", "Fernanda Araújo", "Leticia Roman"]
COORD_VENDAS = "Valéria"
CLOSERS = ["Ana", "Denise", "Camila Fernandes", "Giovana Fornazari", "Johnatan"]
DESLIGADOS = {"Leticia Roman", "Johnatan"}  # início de jul/26


def _med(vals: list[float]) -> float | None:
    vals = [v for v in vals if v is not None]
    return st.median(vals) if vals else None


def time_de(nome: str | None, funcao: str) -> bool:
    """Pertence ao time? Casamento por prefixo (nomes do Pipedrive variam)."""
    if not nome:
        return False
    lista = SDRS if funcao == "sdr" else CLOSERS
    return any(nome.lower().startswith(p.split()[0].lower()) and
               (len(p.split()) == 1 or p.split()[1].lower() in nome.lower())
               for p in lista)


def plano_sdr(p: dict, time: list[dict]) -> dict:
    """Diagnóstico individual de UM SDR vs mediana do time.
    p: {nome, leads, agendadas, taxa_agend, speed_min (mediana de 1º contato), ativo}
    → {fortes: [], fracos: [], acoes: []}"""
    med_taxa = _med([q["taxa_agend"] for q in time if q["nome"] != p["nome"]])
    med_vol = _med([float(q["leads"]) for q in time if q["nome"] != p["nome"]])
    med_speed = _med([q["speed_min"] for q in time if q["nome"] != p["nome"] and q.get("speed_min") is not None])
    fortes, fracos, acoes = [], [], []
    if med_vol and p["leads"] >= med_vol * 1.25:
        fortes.append(f"Volume de leads trabalhados {p['leads'] / med_vol - 1:+.0%} vs mediana do time — capacidade de cadência alta.")
    if med_taxa is not None and p["taxa_agend"] is not None:
        if p["taxa_agend"] >= med_taxa * 1.15:
            fortes.append(f"Taxa de agendamento {p['taxa_agend']:.1%} (time: {med_taxa:.1%}) — abordagem que converte; candidata a ENSINAR o roteiro em par com quem está abaixo.")
        elif p["taxa_agend"] < med_taxa * 0.75 and p["leads"] >= 30:
            fracos.append(f"Taxa de agendamento {p['taxa_agend']:.1%} vs {med_taxa:.1%} do time com volume relevante — o gargalo é a CONVERSA, não o esforço.")
            acoes.append("Escutar 5 abordagens de quem está acima da mediana e ajustar o roteiro de qualificação (dor + urgência antes de oferecer agenda).")
    if p.get("speed_min") is not None:
        if p["speed_min"] <= 15:
            fortes.append(f"Speed-to-lead mediano de {p['speed_min']:.0f} min — dentro da melhor prática (<15 min o lead ainda está quente).")
        elif p["speed_min"] > 60:
            fracos.append(f"Speed-to-lead mediano de {p['speed_min']:.0f} min — lead esfria; a taxa de conexão despenca após a 1ª hora.")
            acoes.append("Bloquear janelas de resposta imediata na agenda (a cada nova entrada, 1º toque em minutos) e ativar o fluxo de cadência no Pipedrive p/ o 1º contato.")
        elif med_speed and p["speed_min"] > med_speed * 1.5:
            fracos.append(f"1º contato em {p['speed_min']:.0f} min vs {med_speed:.0f} min do time.")
    if med_vol and p["leads"] < med_vol * 0.6 and p.get("ativo", True):
        fracos.append(f"Volume {p['leads']:.0f} leads vs mediana {med_vol:.0f} — verificar distribuição de leads ou capacidade.")
        acoes.append("Revisar com a coordenação a régua de distribuição de leads e possíveis travas operacionais.")
    if not acoes and fortes:
        acoes.append("Manter o padrão e documentar o que funciona (roteiro/horários) para nivelar o time por cima.")
    if not fortes and not fracos:
        acoes.append("Volume ainda baixo para diagnóstico individual confiável — reavaliar com mais 2 semanas de dados.")
    return {"fortes": fortes, "fracos": fracos, "acoes": acoes}


def plano_closer(p: dict, time: list[dict]) -> dict:
    """Diagnóstico individual de UM closer vs mediana do time.
    p: {nome, oports, bookings, taxa_conv, ticket, ciclo_dias, perdas_top (str|None), ativo}"""
    med_conv = _med([q["taxa_conv"] for q in time if q["nome"] != p["nome"]])
    med_ticket = _med([q["ticket"] for q in time if q["nome"] != p["nome"] and q.get("ticket")])
    med_ciclo = _med([q["ciclo_dias"] for q in time if q["nome"] != p["nome"] and q.get("ciclo_dias") is not None])
    fortes, fracos, acoes = [], [], []
    if med_conv is not None and p["taxa_conv"] is not None:
        if p["taxa_conv"] >= med_conv * 1.15 and p["oports"] >= 10:
            fortes.append(f"Conversão {p['taxa_conv']:.1%} (time: {med_conv:.1%}) — fechamento acima do time; referência p/ role-play das reuniões.")
        elif p["taxa_conv"] < med_conv * 0.75 and p["oports"] >= 10:
            fracos.append(f"Conversão {p['taxa_conv']:.1%} vs {med_conv:.1%} do time em {p['oports']} oportunidades.")
            acoes.append("Gravar/assistir 3 reuniões com quem converte acima da mediana; revisar ancoragem de valor ANTES do preço e o follow-up estruturado (maioria fecha entre o 2º e 4º contato).")
    if med_ticket and p.get("ticket") and p["ticket"] >= med_ticket * 1.2:
        fortes.append(f"Ticket médio {p['ticket']:,.0f} vs {med_ticket:,.0f} do time — vende bem os bundles maiores (B3+).".replace(",", "."))
    elif med_ticket and p.get("ticket") and p["ticket"] < med_ticket * 0.75:
        fracos.append(f"Ticket médio {p['ticket']:,.0f} concentrado em planos de entrada — mix abaixo do time.".replace(",", "."))
        acoes.append("Treinar oferta de B3-B5: apresentar o plano acima do que o lead pediu com caso de resultado (a meta da empresa está justamente em B3-B5).")
    if med_ciclo is not None and p.get("ciclo_dias") is not None:
        if p["ciclo_dias"] <= med_ciclo * 0.7:
            fortes.append(f"Ciclo de {p['ciclo_dias']:.0f} dias vs {med_ciclo:.0f} do time — decide rápido sem perder conversão.")
        elif p["ciclo_dias"] > med_ciclo * 1.5:
            fracos.append(f"Ciclo de {p['ciclo_dias']:.0f} dias vs {med_ciclo:.0f} do time — deals esfriam na negociação.")
            acoes.append("Definir próximo passo COM DATA dentro da própria reunião (nunca sair sem compromisso agendado) e limpar pipeline parado >2× a mediana.")
    if p.get("perdas_top"):
        acoes.append(f"Motivo de perda dominante: “{p['perdas_top']}” — levar 3 casos p/ destrinchar na 1:1 com a coordenação.")
    if not acoes and fortes:
        acoes.append("Manter o padrão; documentar abordagem das reuniões que fecham p/ nivelar o time.")
    if not fortes and not fracos:
        acoes.append("Amostra pequena p/ diagnóstico confiável — reavaliar com mais 2 semanas de dados.")
    return {"fortes": fortes, "fracos": fracos, "acoes": acoes}


def insights_prevendas(d: dict) -> list[str]:
    """Diagnóstico do FUNIL de qualificação (d: métricas agregadas do período)."""
    out = []
    if d.get("taxa_contato") is not None and d["taxa_contato"] < 0.85:
        out.append(f"{1 - d['taxa_contato']:.0%} dos leads do período ainda SEM 1º contato — lead não tocado é verba de marketing desperdiçada; prioridade nº 1 é zerar essa fila diariamente.")
    if d.get("speed_med_min") is not None:
        if d["speed_med_min"] > 60:
            out.append(f"Speed-to-lead mediano do time em {d['speed_med_min']:.0f} min — melhores práticas de e-commerce apontam <15 min (a taxa de conexão cai ~8× após a 1ª hora). Automatizar o 1º toque via fluxo de cadência.")
        elif d["speed_med_min"] <= 15:
            out.append(f"Speed-to-lead mediano de {d['speed_med_min']:.0f} min — dentro da melhor prática; manter.")
    if d.get("taxa_agend") is not None and d.get("meta_agend"):
        if d["taxa_agend"] < d["meta_agend"]:
            out.append(f"Taxa lead→reunião em {d['taxa_agend']:.1%} vs {d['meta_agend']:.1%} de referência — revisar critérios de qualificação com o time antes de pedir mais volume ao Marketing.")
    if d.get("desq_top"):
        out.append(f"Desqualificação dominante: “{d['desq_top'][0]}” ({d['desq_top'][1]}× no período) — se vier concentrada de um canal, é ajuste de segmentação no Marketing, não de abordagem.")
    if not out:
        out.append("Sem desvios relevantes no período — funil de qualificação dentro dos padrões.")
    return out


def insights_vendas(d: dict) -> list[str]:
    """Diagnóstico do FUNIL de fechamento (métrica central: Oport→Booking)."""
    out = []
    if d.get("conv_oport_book") is not None:
        ref = d.get("meta_conv") or 0.15
        if d["conv_oport_book"] < ref:
            out.append(f"Conversão Oportunidade→Booking em {d['conv_oport_book']:.1%} vs {ref:.0%} da meta — o gargalo já apontado no Q3. Ver Win/Loss: se a perda dominante for preço/valor, o problema é ancoragem; se for qualificação, devolver critérios à Pré-vendas.")
        else:
            out.append(f"Conversão Oportunidade→Booking em {d['conv_oport_book']:.1%} — no alvo ({ref:.0%}).")
    if d.get("perda_top"):
        out.append(f"Maior motivo de perda: “{d['perda_top'][0]}” ({d['perda_top'][1]} deals, {d.get('perda_top_mrr', 0):,.0f} de MRR) — atacar esse motivo vale mais que qualquer outro ajuste isolado.".replace(",", "."))
    if d.get("empacados"):
        out.append(f"{d['empacados']} deals parados acima de 2× a mediana da etapa — pipeline inflado esconde a conversão real; limpar ou reativar com oferta de urgência.")
    if d.get("no_show") is not None and d["no_show"] > 0.2:
        out.append(f"No-show em {d['no_show']:.0%} das reuniões — confirmar por WhatsApp na véspera e oferecer reagendamento self-service.")
    if not out:
        out.append("Sem desvios relevantes no período — funil de fechamento dentro dos padrões.")
    return out
