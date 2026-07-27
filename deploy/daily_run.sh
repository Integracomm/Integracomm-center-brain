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

# ORDEM INVERTIDA em 27/07 — as fontes LEVES vêm PRIMEIRO.
# O `set -e` já tinha saído (20/07) porque um crash do portfolio abortava o
# resto. Só que isso não bastava: quando o processo é MORTO por fora (teto de
# tempo, OOM, container recriado), nenhuma etapa seguinte chega a rodar. Foi o
# que aconteceu de 24 a 27/07 — o Otávio viu no painel Meta Ads, Google Ads,
# Notion e atividades do Pipedrive TODOS parados em 23/07, exatamente a última
# rodada que terminou. Marketing/Notion levam minutos e são estáveis; o
# portfolio leva horas e é frágil: quem é barato e confiável roda primeiro e
# deixa de ser refém.
echo "--- cancelamentos: recarga das planilhas do time ---"
python -m scripts.sync_cancelamentos || echo "[ERRO] sync_cancelamentos falhou (código $?)"
echo "--- marketing: coleta $([ "$(date +%u)" = "1" ] && echo 'semanal (c/ metas+lag)' || echo 'incremental') ---"
if [ "$(date +%u)" = "1" ]; then
    python -m scripts.sync_marketing --weekly || echo "[ERRO] sync_marketing --weekly falhou (código $?)"
else
    python -m scripts.sync_marketing || echo "[ERRO] sync_marketing falhou (código $?)"
fi

echo "--- carteira: pontuação + Slack (etapa longa) ---"
python -m scripts.run_portfolio --slack || echo "[ERRO] run_portfolio falhou (código $?) — seguindo para as demais etapas"

# 2ª VARREDURA — só o que sobrou (Otávio 27/07: "não seria melhor já fazer uma
# segunda varredura logo em seguida apenas dessas contas restantes?").
# Na 1ª passada de hoje: 220 de 251 pontuadas, 28 cortadas pelo prazo e 2 com
# falha de leitura. Deixar para amanhã significa o gestor decidir com score de
# ontem numa conta que talvez seja justamente a que virou risco.
# Não precisa de lista: `--limit` corta DEPOIS da ordenação por defasagem, então
# "as 60 mais defasadas" JÁ SÃO as que ficaram de fora — as demais, recém
# pontuadas, nem entram. Sem --slack: o relatório do dia já foi enviado.
echo "--- carteira: 2ª varredura (só as contas que ficaram para trás) ---"
python -m scripts.run_portfolio --limit 60 --prazo-min 45 \
    || echo "[ERRO] 2ª varredura falhou (código $?) — as pendentes entram primeiro amanhã"
# REDE DE SEGURANÇA DO SLACK (27/07). O `--slack` acima é a última linha do
# run_portfolio: se ele morre no meio (teto de tempo, OOM, container recriado),
# o relatório simplesmente não sai — foi o que aconteceu de 24 a 27/07, com o
# time sem relatório e ninguém sabendo. Esta chamada envia o que houver de mais
# recente no banco. É idempotente por dia: se o run_portfolio JÁ enviou, aqui
# imprime 'ja-enviado-hoje' e não duplica.
python -m scripts.send_slack_report || echo "[ERRO] envio de backup do Slack falhou (código $?)"
if [ "$(date +%d)" = "02" ]; then
    echo "--- dia 2: checagem mensal NPS ---"
    python -m scripts.check_nps_fill --slack || echo "[ERRO] check_nps_fill falhou (código $?)"
fi
echo "=== ok $(date '+%H:%M:%S') ==="
