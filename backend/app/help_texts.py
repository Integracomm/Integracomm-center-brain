"""Explicações por tela e por campo — pedido do Otávio (13/07): gestores em
validação precisam entender cada métrica e os insights que ela dá.

Estrutura: HELP["area/view"] = [("_intro", texto geral da página)] +
[(título-âncora da seção, explicação detalhada)]. O título-âncora casa com o
<h2> real da tela (tokens, sem acento); o que não casa cai no painel do topo.
Para editar/adicionar textos, só mexer aqui.
"""
from __future__ import annotations

import re
import unicodedata
from html import escape

HELP: dict[str, list[tuple[str, str]]] = {
    # ============================== GROWTH ==============================
    "growth/contas": [
        ("_intro", "Carteira completa de clientes monitorados pela IA. Cada linha é uma conta com seu score de saúde (0-100, calculado das conversas de WhatsApp, execução no ClickUp e sinais de risco), estágio, trajetória e squad responsável. Use os filtros para focar em faixa de risco, squad ou serviço. O objetivo da página: decidir QUEM o gestor atende primeiro hoje."),
        ("Contas por risco", "Lista ordenada pelo risco: score baixo = risco alto de churn. Estágio mostra a fase (saudável → atenção → insatisfação ativa → intenção de saída; este último SÓ com fala explícita de cancelamento). Trajetória indica direção: conta 'média piorando' merece mais atenção que 'ruim estável'. Serviço-Squad (ex. ADS-B3-S2) permite comparar carteiras. Insights: (1) priorize intenção de saída e críticos do dia; (2) trajetórias piorando em massa num squad = problema de processo, não de cliente; (3) botão Relatório abre o dossiê para a reunião."),
    ],
    "growth/alertas": [
        ("_intro", "Fila de trabalho da retenção: cada alerta é uma conta que cruzou um limiar de risco. O fluxo é reconhecer (alguém assumiu) → tratar → resolver (registrando o desfecho; retido vira playbook). A última nota de cada caso alimenta o plano de ação do relatório individual."),
        ("Fila de retenção", "Alertas abertos por severidade: crítico = fala de cancelamento ou faixa crítica (agir HOJE — sem contato na semana a decisão se consolida); alto/atenção = insatisfação relevante. Insights: (1) a fila é a agenda de retenção do dia; (2) alertas antigos sem reconhecimento = furo de processo; (3) a última nota mostra o estado real da tratativa sem abrir o caso."),
        ("Ações recentes", "Trilha de auditoria: quem reconheceu/resolveu o quê e quando. Insight: tempo entre alerta e 1ª ação é o 'speed-to-lead' da retenção — quanto menor, maior a taxa de reversão."),
    ],
    "growth/cancelamentos": [
        ("_intro", "Visão oficial dos cancelamentos (números validados com as planilhas do time — batem com a contagem da gestão). Combina volume mensal, taxa por bundle, MRR perdido, tempo de casa e motivos, com filtro temporal. Objetivo: separar ONDE o churn dói (plano, época, precocidade) para atacar a causa certa."),
        ("Saídas por mês", "Contagem mensal oficial (fev 26, mar 26, abr 26, mai 22, jun 18...). Insight: a tendência importa mais que o mês isolado; queda sustentada = retenção funcionando."),
        ("Evolução mensal", "Total dividido em clientes NOVOS (até 3 meses de casa) × ANTIGOS. Insights: churn precoce alto = problema de onboarding/expectativa de venda; churn tardio = problema de valor contínuo/relacionamento. Cada um tem dono e remédio diferentes."),
        ("MRR perdido por mês", "Receita recorrente que saiu com os cancelamentos. Insight: mês com POUCOS cancelamentos mas MUITO MRR = perdemos contas grandes — investigue individualmente no relatório de cada uma."),
        ("Taxa de cancelamento por bundle", "Cancelamentos ÷ base ativa daquele bundle (não o número absoluto — B1 cancela mais porque É maior). Insight: taxa alta num bundle específico = revisar preço/entrega/perfil de cliente daquele plano."),
        ("Tempo de casa na saída", "Quanto tempo o cliente ficou antes de sair, por bundle. Insight: se a moda é ≤3 meses, o problema começa na venda (expectativa) ou no onboarding — antes do gestor de contas."),
        ("Motivos informados", "O que o time registrou como causa. Insight: motivo dominante = playbook prioritário; muitos '(sem motivo)' = disciplina de registro a cobrar."),
        ("Por plano e por equipe", "Cruzamento bundle × squad. Insight: churn concentrado num squad específico com bundles variados = questão de equipe; concentrado num bundle em vários squads = questão de produto/preço."),
    ],
    "growth/playbooks": [
        ("_intro", "Biblioteca viva de retenção: cada intervenção registrada (o que foi feito, em quem, com que resultado). Casos retidos viram referência replicável."),
        ("Práticas de referência", "Intervenções que REVERTERAM cancelamento, com o contexto e a ação. Insight: antes de improvisar numa tratativa nova, procure aqui um caso parecido (mesmo estágio/motivo) e replique o que funcionou."),
    ],
    "growth/relatorios": [
        ("_intro", "Relatórios consolidados da área: resumo executivo com envio ao Slack, análise comparativa por squad e o relatório multi-cliente de Assessoria. É a página de onde saem os materiais de reunião de gestão."),
        ("Análise por squad", "Score composto (50% retenção, 25% execução, 25% cobertura) com ranking dos 8 squads e plano de ação. Insights: (1) squad no fim do ranking por 2+ semanas = apoio estruturado, não cobrança pontual; (2) execução baixa com retenção alta ainda = risco futuro, aja antes de virar churn."),
        ("Relatório de Assessoria", "Multi-cliente: saúde e entregas de cada conta da assessoria num documento só. Insight: use na reunião semanal do time para revisar a carteira em 15 minutos."),
    ],
    # ============================= MARKETING ============================
    "marketing/visao": [
        ("_intro", "Painel executivo da aquisição no mês: KPIs vs mês anterior, o funil completo contra as metas com marcador de ritmo, o progresso consolidado e o gap dos planos prioritários (B3-B5). Em 30 segundos: estamos no ritmo? Onde está o gargalo? O que falta nos planos que importam?"),
        ("Funil do mês vs meta", "Cada etapa (Lead→MQL→SAL→SQL→Oportunidade→Booking) contra a meta do mês; o traço vertical é o ritmo esperado pelo dia corrente. Insights: (1) a PRIMEIRA etapa abaixo do traço é o gargalo real — as seguintes são consequência dela; (2) topo no ritmo + fundo atrás = problema de conversão (Pré-vendas/Vendas), não de volume; (3) tudo atrás = problema de geração (verba/campanha)."),
        ("Progresso vs meta do mês", "% da meta realizada vs % do mês decorrido. Verde = tendência de bater; vermelho = ação AINDA ESTE MÊS (aumentar verba, destravar campanha), não no fechamento, quando já é tarde."),
        ("Gap para a meta (B3-B5)", "Quanto falta nos planos prioritários da empresa (ticket maior). Insights: (1) este gap é a pauta do trimestre — B1 no ritmo não compensa B4 parado; (2) cruze com o Planejador para converter o gap em leads e verba necessários por canal."),
    ],
    "marketing/metas": [
        ("_intro", "Metas detalhadas do semestre (planilha do time) contra o realizado: funil mês a mês, custo por etapa, investimento e oportunidades por canal. É a página de prestação de contas do plano H2."),
        ("Funil mês a mês", "Grade mês × etapa com realizado/meta e pacing. Insight: meses passados mostram o padrão de erro do planejamento (sempre otimista numa etapa específica?) — recalibre a meta, não só a execução."),
        ("Custo por etapa vs alvo", "Quanto custou gerar cada lead/oportunidade vs o alvo planejado. Insights: (1) CPL no alvo mas custo/oportunidade estourado = lead barato e ruim — problema de qualidade, não de preço; (2) compare canais antes de cortar verba."),
        ("Investimento planejado × gasto", "Verba planejada vs executada por mês. Insight: subexecução de verba com meta batida = eficiência (replique); subexecução com meta perdida = travou operação de campanha — problema de execução, não de orçamento."),
        ("Oportunidades por canal", "META/Prospecção/Eventos/Shopee/Low Ticket/Inst. Orgânico: planejado × realizado (por utm_source). Insight: canal sistematicamente abaixo = replanejar mix; acima = candidato a verba extra."),
    ],
    "marketing/funil": [
        ("_intro", "O funil de prospecção com a régua OFICIAL do dashboard do time (a mesma que a gestão confere no Pipedrive): Lead = deals criados no período (corte de Brasília); MQL e SAL = Lead descontando os perdidos por motivo de desqualificação (lead score baixo, sem retorno, dropshipping…); SQL = lead cujo dono atual é um closer (agendou reunião = handoff); Oportunidade = campo Dia Oportunidade no período (não é coorte — pode superar SQL); Booking = ganhos. ATENÇÃO: MQL/SAL/SQL são retroativos — desqualificar um lead depois move o número do mês em que ele entrou."),
        ("Funil", "Volumes por etapa no período filtrado, visual espelhado no dashboard do time. Insights: (1) compare períodos para ver sazonalidade; (2) a taxa que mais cai vs histórico é o alarme da semana."),
        ("Taxas por etapa", "Conversão de cada etapa vs a anterior (TX) e vs o topo (TX Lead). Insight: TX Lead→Booking é a eficiência global — se caiu, as taxas por etapa mostram exatamente onde."),
        ("Metas de taxa do mês", "Metas de conversão editáveis por mês (pré-semeadas da planilha; edição manual prevalece). Insight: a etapa mais distante da meta é onde investir treinamento/processo."),
        ("Como alcançar a meta", "Sugestões automáticas a partir da etapa mais distante da meta. Insight: é o ponto de partida da conversa, não a conclusão — valide com o contexto do time."),
    ],
    "marketing/canais": [
        ("_intro", "Ranking de canais por leads e conversão, com variação vs período anterior. Objetivo: decidir onde sobe e onde desce a verba com base em dado, não em impressão. Insight-chave: canal com MUITO volume e conversão fraca desperdiça verba de mídia E tempo de SDR — segmente ou corte."),
    ],
    "marketing/origens": [
        ("_intro", "Cada origem de lead (utm_source) com volume, conversão e um chip de decisão automático: ESCALAR (volume + conversão bons) ou REVISAR (volume alto, conversão fraca). Clique para o drill da origem. Insight-chave: os chips são a lista de decisões da semana de mídia; filtro de mídia paga/não paga separa o que é comprado do que é orgânico."),
    ],
    "marketing/midia": [
        ("_intro", "Desempenho diário da mídia paga. IMPORTANTE: leads e CPL usam os DEALS do Pipedrive (não o pixel da plataforma, que infla) — este é o número real; CTR e impressões vêm da plataforma. Inclui a galeria de criativos com miniaturas."),
        ("Leads por dia", "Deals criados por dia atribuídos à mídia. Insight: quedas bruscas num dia específico = campanha pausada/reprovada ou verba esgotada — cheque o gestor de anúncios naquele dia."),
        ("Gasto por dia", "Investimento diário somado das plataformas. Insight: gasto subindo com leads estáveis = CPL derretendo — fadiga de criativo ou leilão mais caro."),
        ("CPL por dia", "Custo por lead REAL (gasto ÷ deals). Insight: compare com o CPL-alvo da aba Metas; 3+ dias acima do alvo = troca de criativo/público, não espere o mês fechar."),
        ("Criativos do período", "Cada peça com gasto, leads e custo. Insight: os 20% melhores criativos costumam pagar a conta — identifique o padrão deles (formato, promessa, público) antes de brifar os próximos."),
    ],
    "marketing/lag": [
        ("_intro", "Quanto tempo o lead demora para virar booking (p25/mediana/p75), no agregado, por canal e por campanha. Responde: o investimento de hoje vira receita QUANDO? Essencial para não julgar campanha nova cedo demais."),
        ("Curva de acúmulo de leads", "% dos leads que já converteram após X dias. Insight: se 50% convertem em ~30 dias, a campanha lançada há 2 semanas ainda não mostrou metade do resultado — segure o julgamento."),
        ("Lag agregado por canal", "Mediana de conversão por canal. Insight: canal de lag curto (ex. indicação) financia o caixa; canal de lag longo precisa de esteira constante — não ligue/desligue."),
        ("Por campanha", "Lag por campanha específica. Insight: lag muito acima da mediana do canal = público frio ou qualificação lenta — ajuste segmentação ou cadência de Pré-vendas."),
    ],
    "marketing/planejador": [
        ("_intro", "Planejamento reverso POR BUNDLE: informe quantos bookings de cada plano quer e até quando; a ferramenta devolve leads e verba necessários no ritmo histórico de conversão e lag, e mostra quais campanhas/criativos já fecharam aquele bundle antes."),
        ("Estratégias e criativos recomendados", "Campanhas e criativos que historicamente FECHARAM o bundle pedido. Insight: começar por eles reduz o risco do plano — é o caminho já pavimentado; o resto é aposta."),
    ],
    "marketing/criativos": [
        ("_intro", "Desempenho de criativos por público (base ad-insightify) + histórico de testes + ideias. Evita repetir teste que já perdeu e industrializa o que já ganhou."),
        ("Histórico de testes", "Testes de criativo×público já rodados com resultado. Insight: antes de aprovar um teste novo, confira se já não foi feito — orçamento de teste é finito."),
        ("Ideias", "Sugestões heurísticas a partir dos padrões vencedores. Insight: use como brief inicial para a produção, não como peça final."),
    ],
    # ============================= PRÉ-VENDAS ===========================
    "prevendas/funil": [
        ("_intro", "Funil da qualificação com a MESMA taxonomia e régua OFICIAL do Funil de Prospecção do Marketing (a que a gestão confere no Pipedrive): Lead = criados no período; MQL/SAL = Lead descontando desqualificados por motivo; SQL = lead na mão de um closer (agendou reunião). Pré-vendas termina no SQL (handoff para Vendas); Oportunidade e Booking seguem no Funil de Fechamento. Números batem com a aba Funil do Marketing e com o dashboard do time. Responde: os leads estão virando reunião? Onde morrem os que não viram?"),
        ("Funil", "Lead (criados no período) → MQL (desconta perdidos por lead score baixo) → SAL (desconta os demais motivos de desqualificação) → SQL (dono atual é closer = agendou reunião, handoff para Vendas), com taxas vs etapa anterior e vs Lead. Insights: (1) MQL→SAL baixo = muito lead desqualificado — veja os motivos abaixo e devolva o padrão ao Marketing; (2) SAL→SQL baixo = lead aceito que não vira reunião — problema de cadência/abordagem, cruze com Speed-to-Lead; (3) as etapas são retroativas: o funil do mês ainda se move enquanto os SDRs tratam a fila."),
        ("Conversão por dia de chegada do lead", "Taxa de agendamento pelo dia da semana em que o lead ENTROU (coorte; a reunião conta a qualquer tempo). Insights: (1) sexta/fim de semana com taxa bem menor = lead esfriando sem contato — caso para plantão reduzido ou automação de primeira resposta; (2) cruze com a aba Melhor Horário: dia que gera muito lead e converte pouco é onde a fila acumula; (3) se as taxas forem uniformes, a distribuição semanal de verba de mídia não precisa mudar."),
        ("Qualidade do lead por origem", "Taxa lead→reunião POR CANAL. Insights: (1) realimenta o Marketing: canal com conversão 3x maior merece verba; (2) SDR reclamando de 'lead ruim' — aqui está a prova (ou não) por origem."),
        ("Motivos de desqualificação", "Por que os leads morrem antes da reunião. Insight: motivo dominante tipo 'sem faturamento mínimo' = filtro NA CAMPANHA (formulário/segmentação), não é falha de SDR."),
        ("Diagnóstico do especialista", "Leitura automática de um head de pré-vendas: taxa de contato, agendamento e desqualificação vs referências. Insight: pauta pronta para a reunião semanal da coordenação."),
    ],
    "prevendas/speed": [
        ("_intro", "Velocidade do 1º contato: tempo entre o lead entrar e o primeiro toque registrado no Pipedrive. Referência de mercado: contato em até 15 minutos multiplica conversão. Inclui a fila de leads nunca tocados — o dinheiro parado na mesa."),
        ("Velocidade do 1º contato × conversão", "Leads do período agrupados pelo tempo até o 1º contato registrado (até 15 min, 15-60 min, 1-4h, 4-24h, 24h+, sem contato); Agendaram = quantos viraram reunião (a qualquer tempo — coorte); Taxa = conversão de cada faixa. Insights: (1) a diferença de taxa entre 'até 15 min' e '24h+' é o preço, em reuniões, de cada lead esperando — argumento pronto para priorizar a fila; (2) faixa 'sem contato' com taxa quase zero = dinheiro de mídia desperdiçado, zere-a diariamente; (3) se as taxas forem parecidas entre faixas, o problema da conversão não é velocidade — investigue a qualidade do lead por origem no Funil."),
        ("Taxa de agendamento por tipo de 1º contato", "Cada tipo de abordagem inicial registrada no Pipedrive (ligação, WhatsApp, cadência…) com leads, agendamentos e taxa. Insights: (1) tipo com taxa muito acima = padronize-o como primeira tentativa do time; (2) cadência automática com taxa baixa = régua de mensagens a reescrever, não a abandonar; (3) '(sem registro)' grande = disciplina de registro de atividades a cobrar — sem isso a leitura de speed fica cega."),
        ("Por responsável do 1º contato", "Mediana e % ≤15min por SDR. Insights: (1) speed lento generalizado = processo/ferramenta; lento em UMA pessoa = carga ou disciplina; (2) compare com a taxa de agendamento — velocidade sem conversão indica abordagem a treinar."),
        ("Por origem", "Speed por canal de entrada. Insight: canal sistematicamente lento (ex. leads chegando de madrugada) = caso para automação de primeira resposta ou revisão de horário do time — cruze com a aba Melhor Horário."),
    ],
    "prevendas/horarios": [
        ("_intro", "Estudo de QUANDO as reuniões são agendadas (momento em que o deal entrou em Reunião Agendada, horário de Brasília). Mapa de calor dia×hora, top janelas, % fora do expediente e recorte por bundle. Base objetiva para decidir horário de ligação e eventual extensão de expediente. Botão 'Gerar relatório' cria a versão imprimível para validação da gestora."),
        ("Mapa de calor", "Células escuras = mais agendamentos naquele dia/hora. Insights: (1) as janelas de ouro são onde concentrar as tentativas de ligação; (2) ressalva: o carimbo é a movimentação do card — SDR que atualiza em lote no fim do dia infla as últimas horas; a gestora sabe distinguir."),
        ("Agendamentos por colaborador × hora", "Quando cada pessoa agenda (atribuição pelo campo SDR do deal); o sombreado é na escala DA PESSOA, então dá para comparar o padrão de horário de quem tem volumes muito diferentes. Insights: (1) pico de alguém em janela que o mapa geral mostra fraca = método que funciona fora do óbvio — vale entender e testar com o time; (2) alguém sem agendamento nas janelas de ouro do time = revisar a agenda dela nesses horários (reunião interna? pausa?); (3) atenção ao aviso de amostra pequena e ao carimbo do card (quem atualiza em lote infla o fim do dia)."),
        ("Top 5 janelas", "As 5 combinações dia+hora com mais agendamentos e o % do total. Insight: se as top 5 concentram muito volume, vale blindar esses horários na agenda do time (sem reunião interna, foco em ligação)."),
        ("Melhores janelas por bundle", "A melhor janela pode variar por plano (decisor de B5 atende em horário diferente do de B1). Insight: atenção ao aviso de amostra pequena — não mude escala de time por meia dúzia de casos."),
    ],
    "prevendas/sdrs": [
        ("_intro", "Uma tabela única por colaborador + planos de ação por regra. Volumes na régua OFICIAL dos gráficos do Pipedrive (atribuição pelo campo SDR do deal) e, na última coluna, o speed do 1º contato registrado nas atividades. A lista do time é editável no Painel Administrativo."),
        ("Leads e oportunidades por colaborador", "Leads = deals criados no período; oportunidades = campo Dia Oportunidade no período (não é coorte — a oportunidade pode ser de lead antigo); bookings = ganhos no período; atribuição = campo SDR do deal, sem fallback; Speed = mediana do tempo até o 1º contato registrado. Insights: (1) estes números conferem com os gráficos do Pipedrive; (2) '(sem SDR definido)' grande = leads ainda não distribuídos/tocados — é a fila a zerar (cruze com Speed-to-Lead); (3) Lead→Oport muito diferente entre SDRs com volume parecido = mix de origem ou abordagem — o speed ajuda a separar esforço de conversa; (4) nomes 'fora do time de PV' têm deals no nome (closers, ex-SDRs) — ajuste a lista no Painel Administrativo se alguém entrou/saiu."),
        ("Planos de ação individuais", "Fortes/fracos/ações por pessoa, derivados por regra. Insight: leve para o 1:1 como ponto de partida — a coordenação contextualiza o que o número não vê (férias, mix de leads, rampagem)."),
    ],
    # ============================== VENDAS ==============================
    "vendas/funil": [
        ("_intro", "Funil do fechamento: da Reunião Agendada (handoff de Pré-vendas) até o booking, com receita do período e tendência mensal de conversão. Inclui o funil COMPLETO (Lead→Booking) na régua oficial do dashboard do time. Responde: as reuniões estão virando contrato?"),
        ("Funil completo", "O funil inteiro (Lead → MQL → SAL → SQL → Oportunidade → Booking) com a régua OFICIAL do dashboard do time — os mesmos números das abas de Marketing e Pré-vendas. Insights: (1) é a visão de contexto: mostra quanto do resultado de Vendas é herança do topo; (2) Oportunidade usa o campo Dia Oportunidade e não é coorte — pode superar SQL; (3) para o detalhe do fechamento, use as seções abaixo."),
        ("KPIs do fechamento", "Reuniões → Negociação → Booking + receita. Insights: (1) queda Reunião→Negociação = no-show ou reunião fraca — cruze com no-shows; (2) queda Negociação→Booking = proposta/preço/urgência — veja os motivos de perda."),
        ("Tendência Oportunidade → Booking", "Conversão mês a mês. Insight: conversão caindo com volume estável = problema de FECHAMENTO (time/proposta/concorrência), não de topo de funil — o remédio é diferente de gerar mais lead."),
        ("Oportunidades por bundle", "Oportunidades = deals que entraram em Negociação no período, já com o plano definido (é nesse momento que o campo Produto é preenchido no Pipedrive). % do mix = participação de cada bundle nas oportunidades novas — o retrato do que o funil está produzindo. Bookings = contratos FECHADOS no período, por plano (mesma régua do controle da gestão); planos antigos e exceções aparecem pelo nome. Oport→Booking = eficiência de fechamento de cada plano. Insights: (1) mix concentrado em B1 com meta em B3-B5 = o gargalo está na geração/qualificação, não no fechamento; (2) se a conversão cresce com o bundle, gerar 1 oportunidade B4 rende mais que várias B1 — priorize a qualificação para cima; (3) bundle com muitas oportunidades e conversão baixa = revisar proposta/preço daquele plano."),
        ("Conversões por origem × plano", "Quais origens de lead FECHAM quais bundles: bookings do período cruzados origem × plano, com TX = bookings ÷ leads da origem. Insights: (1) a origem que fecha B3-B5 é onde escalar verba mesmo com CPL maior; (2) origem com volume alto e TX baixa consome agenda de closer sem retorno; (3) indicação costuma fechar plano maior — se não estiver fechando, o programa de indicações merece atenção."),
    ],
    "vendas/winloss": [
        ("_intro", "Por que ganhamos e perdemos: motivos de perda categorizados do Pipedrive, win rate e o cruzamento motivo×plano. É a matéria-prima do playbook de objeções."),
        ("Motivos de perda", "Ranking dos motivos registrados nos deals perdidos. Insights: (1) o motivo nº1 merece um playbook escrito de resposta; (2) 'preço' dominante em um bundle específico = discussão de pricing, não de vendedor."),
        ("Motivo × plano", "Cruzamento: qual objeção mata qual plano. Insight: se B4-B5 morrem por 'timing' e B1 por 'preço', o discurso de valor precisa ser diferente por segmento — um pitch único não serve."),
    ],
    "vendas/ciclo": [
        ("_intro", "Tempo de ciclo (criação → fechamento) e a lista de deals EMPACADOS — negociações paradas além do normal. Ciclo longo esfria cliente e trava previsibilidade."),
        ("Deals empacados", "Negociações abertas paradas há mais tempo que o padrão. Insights: (1) é a fila de destrave da coordenação — cada linha merece decisão: reativar com prazo ou perder oficialmente; (2) empacado antigo inflando o pipeline = forecast irreal."),
    ],
    "vendas/closers": [
        ("_intro", "Produtividade individual dos closers (dono atual do deal): bookings, receita, conversão e ciclo, mais planos de ação por regra vs mediana do time. Material do 1:1 da Valéria."),
        ("Performance por closer", "Números individuais do período. Insights: (1) receita alta com poucos bookings = perfil caçador de ticket grande — combine a distribuição de leads com isso; (2) conversão abaixo da mediana com ciclo longo = deals presos, veja os empacados dessa pessoa."),
        ("Planos de ação individuais", "Fortes/fracos/ações por closer, derivados por regra. Insight: ponto de partida do 1:1 — contextualize com mix de leads e ausências antes de cobrar."),
    ],
    "vendas/forecast": [
        ("_intro", "Performance & Meta do mês: metas por plano (quantidade e R$, da planilha financeira) × fechado, com pacing, gap, pipeline aberto e a tradução do que falta em oportunidades e leads. É a página de gestão do resultado do mês — mês selecionável para revisar históricos."),
        ("Meta realizado por plano", "B1-B5 + total: meta, fechado, receita, % com barra de pacing (traço = ritmo esperado pelo dia), gap, pipeline aberto e oportunidades necessárias no ritmo de conversão dos últimos 90d. Insights: (1) B3-B5 destacados são a prioridade — % total bonito com B4 zerado é meta mal batida; (2) pipeline MENOR que as oportunidades necessárias = matematicamente não fecha sem gerar mais topo AGORA."),
        ("O que falta para bater as metas", "O gap traduzido em números acionáveis: quantos bookings faltam → quantas oportunidades no ritmo atual → quantos leads. Insight: é o pedido CONCRETO a Pré-vendas e Marketing — sai daqui com número, não com 'precisamos vender mais'."),
    ],
    # ============================= OPERAÇÕES ============================
    "operacoes/iniciativas": [
        ("_intro", "Controle das iniciativas de cada área da empresa por trimestre, sincronizado do Notion (somente leitura, diário às 06:00 e sob demanda). Agrupamento: gestor → iniciativa (nº no nome) → detalhamento do escopo → ações por prazo. Semáforo: verde = concluída · vermelho = prazo vencido · amarelo = em andamento no prazo · cinza = sem prazo/não iniciada. Ações que dependem de uma anterior atrasada recebem o aviso 'aguardando ação anterior atrasada'. Insights: (1) vermelhos concentrados num gestor = conversa de capacidade; (2) muitos 'sem prazo' = plano ainda não operacional; (3) o link ↗ abre a página no Notion para atualizar na fonte."),
        ("Configuração", "Um campo por área para colar a URL da página do trimestre no Notion (a busca encontra as databases 'Iniciativas' até 3 níveis, inclusive subpáginas por gestor). A página precisa estar compartilhada com a integração no Notion — sem isso o sync retorna vazio."),
        ("Últimas sincronizações", "Log de cada sync: quando, quantos itens, erros. Insight: sync com 0 itens numa área que deveria ter dados = página não compartilhada com a integração ou URL errada."),
    ],
}


def _norm(s: str) -> str:
    x = unicodedata.normalize("NFD", (s or "").lower())
    return "".join(c for c in x if unicodedata.category(c) != "Mn")


def _hint(campo: str, txt: str) -> str:
    return ("<details style='margin:2px 0 8px'><summary style='cursor:pointer;font-size:var(--fs-2xs);"
            "color:var(--brand)'>ⓘ como ler este campo</summary>"
            f"<div style='margin:5px 0 0;padding:8px 12px;background:var(--surface-1);border-left:3px solid var(--brand);"
            f"border-radius:var(--radius-sm);font-size:var(--fs-xs);color:var(--text-2);line-height:1.55'>"
            f"<b>{escape(campo)}</b> — {escape(txt)}</div></details>")


def inject_help(area: str, view: str, content: str) -> str:
    """_intro → painel 'O que você encontra nesta página' no topo; demais itens
    ancorados SOB o <h2> correspondente (match por tokens, sem acento); itens
    sem âncora caem no painel do topo junto do intro."""
    itens = HELP.get(f"{area}/{view}")
    if not itens:
        return content
    intro = next((t for c, t in itens if c == "_intro"), None)
    sobras: list[tuple[str, str]] = []
    for campo, txt in itens:
        if campo == "_intro":
            continue
        toks = [t for t in _norm(campo).split() if len(t) > 3]
        achou = None
        for m in re.finditer(r"<h2[^>]*>(.*?)</h2>(\s*<p class=secsub>.*?</p>)?", content, re.S):
            h2 = _norm(re.sub(r"<[^>]+>", "", m.group(1)))
            if toks and all(t in h2 for t in toks):
                achou = m
                break
        if achou:
            fim = achou.end()
            content = content[:fim] + _hint(campo, txt) + content[fim:]
        else:
            sobras.append((campo, txt))
    if intro or sobras:
        corpo = ""
        if intro:
            corpo += (f"<div style='font-size:var(--fs-sm);line-height:1.6;color:var(--text-2)'>{escape(intro)}</div>")
        corpo += "".join(
            f"<div style='padding:6px 0;border-top:1px solid var(--border);font-size:var(--fs-sm);line-height:1.55'>"
            f"<b>{escape(c)}</b> — <span style='color:var(--text-2)'>{escape(t)}</span></div>"
            for c, t in sobras)
        content = (
            "<details style='margin:14px 0;background:var(--surface-1);border:1px solid var(--border-mid);"
            "border-left:3px solid var(--brand);border-radius:var(--radius-md);padding:10px 16px'>"
            "<summary style='cursor:pointer;font-size:var(--fs-sm);font-weight:600;color:var(--text-2)'>"
            "❓ O que você encontra nesta página</summary>"
            f"<div style='margin-top:8px'>{corpo}</div></details>") + content
    return content


def help_panel(area: str, view: str) -> str:
    """Compatibilidade (cascas antigas) — a injeção real é inject_help."""
    return ""
