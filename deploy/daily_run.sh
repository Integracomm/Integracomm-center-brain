#!/bin/sh
# Rodada diária DENTRO do container (chamada pelo cron do host às 06:00
# America/Sao_Paulo): carteira completa + Slack; no dia 2, também a checagem
# mensal do preenchimento de faturamento nas planilhas NPS.
set -e
cd /app/backend
echo "=== rodada $(date '+%Y-%m-%d %H:%M:%S') ==="
python -m scripts.run_portfolio --slack
if [ "$(date +%d)" = "02" ]; then
    echo "--- dia 2: checagem mensal NPS ---"
    python -m scripts.check_nps_fill --slack
fi
echo "=== ok $(date '+%H:%M:%S') ==="
