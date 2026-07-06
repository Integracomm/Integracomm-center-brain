"""Área de MARKETING — inteligência de tráfego pago e geração de leads.

Fontes (validadas 2026-07-06): Meta Ads (act_560054575531813), Google Ads
(customer 9513419241), Pipedrive (UTMs 100% preenchidos nos deals pagos +
campo Produto = plano vendido), planilha de metas (matriz mês × indicador),
ad-insightify Supabase (creative_history_daily/runs — histórico de testes).

Módulos: schema (tabelas mkt_*), coletores em app/sources/ (meta_ads,
google_ads, pipedrive_deals, mkt_goals, creative_history), análises (lag,
funil, ranking) e a UI (abas da área /marketing no painel).
"""
