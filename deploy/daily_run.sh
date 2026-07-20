#!/bin/sh
# Rodada diária DENTRO do container (chamada pelo cron do host às 06:00
# America/Sao_Paulo): carteira completa + Slack; no dia 2, também a checagem
# mensal do preenchimento de faturamento nas planilhas NPS.
#
# 20/07: SEM `set -e` global — o portfolio depende do gateway do WhatsApp, que
# oscila (500/ReadTimeout); quando ele morria, o `set -e` abortava o script e
# o sync_marketing/Notion NUNCA rodavam (mídia/atividades ficaram 4 dias
# paradas no incidente de 17-20/07). Agora cada etapa é tolerante a falha: o
# erro é LOGADO e as etapas seguintes rodam mesmo assim.
cd /app/backend
echo "=== rodada $(date '+%Y-%m-%d %H:%M:%S') ==="
python -m scripts.run_portfolio --slack || echo "[ERRO] run_portfolio falhou (código $?) — seguindo para as demais etapas"
if [ "$(date +%d)" = "02" ]; then
    echo "--- dia 2: checagem mensal NPS ---"
    python -m scripts.check_nps_fill --slack || echo "[ERRO] check_nps_fill falhou (código $?)"
fi
echo "--- cancelamentos: recarga das planilhas do time ---"
# 20/07 (Otávio): a planilha é viva — formalizações entram toda semana; sem
# esta etapa o painel ficava até semanas defasado (3 cancelamentos B3 de julho
# invisíveis no incidente de 20/07). Recarga total idempotente, tabela pequena.
python -m scripts.sync_cancelamentos || echo "[ERRO] sync_cancelamentos falhou (código $?)"
echo "--- marketing: coleta $([ "$(date +%u)" = "1" ] && echo 'semanal (c/ metas+lag)' || echo 'incremental') ---"
if [ "$(date +%u)" = "1" ]; then
    python -m scripts.sync_marketing --weekly || echo "[ERRO] sync_marketing --weekly falhou (código $?)"
else
    python -m scripts.sync_marketing || echo "[ERRO] sync_marketing falhou (código $?)"
fi
echo "=== ok $(date '+%H:%M:%S') ==="
