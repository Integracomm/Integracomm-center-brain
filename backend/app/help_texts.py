"""Explicações de campos por tela — painel "Como ler esta tela" (pedido do
Otávio 13/07: gestores vão validar as áreas e precisam entender cada campo e
que visão extraem dele). Chave = "area/view"; item = (campo, significado + visão).
Injetado automaticamente pelas cascas — para editar textos, só mexer aqui.
"""
from __future__ import annotations

from html import escape

HELP: dict[str, list[tuple[str, str]]] = {
    "growth/contas": [
        ("Score (0-100)", "saúde da conta calculada das conversas de WhatsApp, execução e sinais de risco — quanto MENOR, maior o risco de churn. Use para priorizar quem o gestor atende primeiro."),
        ("Estágio", "fase do risco (saudável → atenção → insatisfação ativa → intenção de saída). Intenção de saída só aparece com fala explícita de cancelamento do cliente."),
        ("Serviço-Squad", "tag do contrato + squad responsável (ex. ADS-B3-S2) — permite comparar carteiras entre squads."),
        ("Trajetória", "se a conta está melhorando ou piorando nas últimas semanas — uma conta 'média mas piorando' merece mais atenção que uma 'ruim estável'."),
    ],
    "growth/alertas": [
        ("Severidade", "crítico = fala de cancelamento ou faixa crítica; alto/atenção = insatisfação relevante. A fila é a agenda de retenção do dia."),
        ("Estágio e última nota", "contexto do caso + última atualização registrada pelo gestor — o histórico alimenta o plano de ação do relatório."),
        ("Reconhecer / Resolver", "reconhecer = alguém assumiu; resolver = caso encerrado (retido vira referência de playbook). Mantém a fila limpa e auditável."),
    ],
    "growth/cancelamentos": [
        ("Cancelamentos por mês", "contagem oficial validada com as planilhas do time (fev 26, mar 26, abr 26...). Vale conferir tendência, não só o número do mês."),
        ("Taxa por bundle", "cancelamentos ÷ base ativa daquele bundle — mostra se o churn está concentrado em algum plano."),
        ("Novos × antigos", "separa churn precoce (até 3 meses de casa = problema de onboarding/expectativa) de churn tardio (problema de valor contínuo)."),
        ("MRR perdido", "receita recorrente que saiu com os cancelamentos — dimensiona o impacto financeiro."),
    ],
    "growth/playbooks": [
        ("Intervenções", "registro de cada ação de retenção feita e seu resultado — caso retido vira receita replicável para os próximos."),
    ],
    "growth/relatorios": [
        ("Resumo / análise por squad", "score composto por squad (retenção, execução, cobertura) com ranking — aponta qual squad precisa de apoio."),
        ("Relatório individual", "dossiê da conta: faturamento por CNPJ, atividades, saúde, plano de ação (Claude) e histórico do caso — material da reunião com o cliente."),
    ],
    "marketing/visao": [
        ("KPIs vs mês anterior", "volume do mês corrente comparado ao anterior — direção geral da aquisição."),
        ("Funil do mês vs meta", "cada etapa (Lead→Booking) contra a meta, com marcador do ritmo esperado pelo dia do mês — abaixo do traço = atrás da meta."),
        ("Metas por plano (B3-B5)", "prioridade da empresa — o gap destes planos é a dor a atacar no trimestre."),
    ],
    "marketing/metas": [
        ("Realizado × meta por etapa", "grade mês a mês da planilha de metas H2 — pacing = % da meta pelo % do mês decorrido."),
        ("Custo por etapa", "quanto custou cada lead/oportunidade vs alvo planejado — eficiência do investimento."),
        ("Oportunidades por canal", "META/Prospecção/Eventos/Shopee etc., planejado × realizado (por utm_source) — qual canal está entregando."),
    ],
    "marketing/funil": [
        ("Lead→MQL→SAL→SQL→Oportunidade→Booking", "régua validada com o Pipedrive: contagem POR EVENTO no período (quem ENTROU na etapa), corte de Brasília. Indicações pulam etapas — Oportunidade pode superar SQL."),
        ("TX / TX Lead", "conversão vs etapa anterior e vs o topo — a etapa com a maior queda é onde investir."),
        ("Metas de taxa", "editáveis por mês (pré-semeadas da planilha) — sugestões apontam a etapa mais distante da meta."),
    ],
    "marketing/canais": [
        ("Ranking de canais", "leads e conversão por canal com variação vs período anterior — sobe/desce a verba com base aqui."),
    ],
    "marketing/origens": [
        ("Escalar? / Revisar", "chips automáticos por origem: volume bom + conversão boa = escalar; volume alto + conversão fraca = revisar segmentação."),
    ],
    "marketing/midia": [
        ("Leads/CPL", "leads = deals do Pipedrive (não o pixel da plataforma — evita dupla contagem); CPL = gasto ÷ leads reais."),
        ("CTR/impressões", "estes sim da plataforma (Meta/Google) — saúde do anúncio antes do clique."),
        ("Galeria de criativos", "desempenho por criativo com miniatura — qual peça está pagando a conta."),
    ],
    "marketing/lag": [
        ("p25/mediana/p75", "tempo entre o lead entrar e virar booking — 50% dos leads convertem em até X dias. Dimensiona quando o investimento de hoje vira receita."),
        ("Por campanha", "campanhas com lag muito acima da mediana geral indicam público frio ou qualificação lenta."),
    ],
    "marketing/planejador": [
        ("Quantidades por bundle", "informe quantos bookings de cada bundle quer e quando — a ferramenta devolve leads e verba necessários no ritmo histórico."),
        ("Campanhas que já fecharam", "quais campanhas/criativos historicamente fecharam aquele bundle — por onde começar."),
    ],
    "marketing/criativos": [
        ("Ranking por público", "conversão de cada criativo por público testado (ad-insightify) — evita repetir teste que já perdeu."),
    ],
    "prevendas/funil": [
        ("Leads recebidos → Reunião agendada", "funil da qualificação (até o handoff p/ Vendas), por evento no período."),
        ("Qualidade por origem", "taxa lead→reunião por canal — realimenta o Marketing sobre onde está o lead bom."),
        ("Motivos de desqualificação", "por que os leads morrem antes da reunião — se um motivo domina, é filtro de campanha, não de SDR."),
    ],
    "prevendas/speed": [
        ("1º contato mediano", "tempo entre o lead entrar e o primeiro toque registrado — referência de mercado: < 15 min. Lead que espera esfria."),
        ("Sem contato registrado", "fila de leads nunca tocados — zerar diariamente é a ação de maior retorno da área."),
        ("Por responsável / origem", "onde o atraso se concentra: pessoa (carga/processo) ou canal (chega fora do horário?)."),
    ],
    "prevendas/horarios": [
        ("Mapa de calor dia × hora", "QUANDO os agendamentos acontecem (momento em que o deal entrou em Reunião Agendada, Brasília) — as células escuras são as janelas de ouro para ligar."),
        ("% após 18h / almoço / antes das 9h", "volume fora do expediente clássico — base objetiva para decidir estender (ou não) o horário do time."),
        ("Por bundle", "a melhor janela pode variar por plano (B1 ≠ B5) — atenção ao aviso de amostra pequena."),
    ],
    "prevendas/sdrs": [
        ("Leads / Reuniões / Lead→Reunião", "produtividade individual pela atribuição do 1º contato — compare com a mediana do time, não com o número absoluto."),
        ("Speed mediano por SDR", "velocidade individual de primeiro toque — junto da taxa, separa problema de volume de problema de abordagem."),
        ("Planos individuais", "fortes/fracos/ações derivados por regra vs mediana do time — pauta pronta para o 1:1 da coordenação."),
    ],
    "vendas/funil": [
        ("Reunião → Negociação → Booking", "funil do fechamento (da Reunião Agendada em diante) + receita do período."),
        ("Tendência mensal", "conversão Oportunidade→Booking mês a mês — queda aqui com leads estáveis = problema de fechamento, não de topo."),
    ],
    "vendas/winloss": [
        ("Motivos de perda", "por que negociações morrem (categorizado do Pipedrive) — o motivo nº 1 é o playbook a construir."),
        ("Win rate", "ganhos ÷ (ganhos + perdidos) no período — a régua de eficiência do time."),
    ],
    "vendas/ciclo": [
        ("Ciclo de venda", "dias entre criação e fechamento — ciclos longos travam caixa e esfriam cliente."),
        ("Empacados", "negociações paradas há mais tempo que o normal — fila de destrave da coordenação."),
    ],
    "vendas/closers": [
        ("Bookings / receita / conversão por closer", "produtividade individual (dono atual do deal) vs mediana do time."),
        ("Planos individuais", "fortes/fracos/ações por regra — pauta do 1:1 da Valéria."),
    ],
    "vendas/forecast": [
        ("Meta × realizado por plano", "metas da planilha financeira (qtde e R$) vs fechado no mês; barra = pacing (traço vertical = ritmo esperado)."),
        ("Gap / Pipeline / Oport. necessárias", "o que falta, o que há aberto e quantas oportunidades são necessárias no ritmo de conversão dos últimos 90d."),
        ("O que falta para bater as metas", "o gap traduzido em oportunidades e leads — o pedido concreto a Pré-vendas e Marketing."),
    ],
    "operacoes/iniciativas": [
        ("Semáforo", "verde = concluída · vermelho = prazo vencido · amarelo = em andamento no prazo · cinza = sem prazo ou não iniciada."),
        ("Aguardando ação anterior atrasada", "dentro do mesmo escopo, se a 1ª ação pendente está atrasada, as seguintes herdam o aviso — dependência sequencial visível."),
        ("Agrupamento", "gestor → iniciativa (nº no nome) → detalhamento do escopo → ações por prazo. Fonte: Notion (somente leitura), sincronizado diariamente."),
    ],
}


def help_panel(area: str, view: str) -> str:
    """Painel recolhível "Como ler esta tela" — vazio se não houver textos."""
    itens = HELP.get(f"{area}/{view}")
    if not itens:
        return ""
    linhas = "".join(
        f"<div style='padding:6px 0;border-top:1px solid var(--border);font-size:var(--fs-sm);line-height:1.55'>"
        f"<b>{escape(campo)}</b> — <span style='color:var(--text-2)'>{escape(txt)}</span></div>"
        for campo, txt in itens)
    return (
        "<details style='margin:14px 0;background:var(--surface-1);border:1px solid var(--border-mid);"
        "border-left:3px solid var(--brand);border-radius:var(--radius-md);padding:10px 16px'>"
        "<summary style='cursor:pointer;font-size:var(--fs-sm);font-weight:600;color:var(--text-2)'>"
        "❓ Como ler esta tela — o que significa cada campo</summary>"
        f"<div style='margin-top:6px'>{linhas}</div></details>")
