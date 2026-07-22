#!/bin/sh
# ============================================================================
# Envelope da rodada diária — chamado pelo cron do host às 06:00.
#
# POR QUE EXISTE (22/07): a rodada não tinha teto de tempo nem trava contra
# sobreposição. Nos dias 17, 18, 19, 20 e 22/07 ela parou de responder logo
# depois do confirmador de cancelamento e ficou pendurada por mais de 24h — o
# `run_portfolio --slack` nunca chegava ao fim e o RELATÓRIO DO SLACK não saía.
# Pior: a rodada do dia seguinte começava POR CIMA da anterior, as duas
# disputando o gateway do WhatsApp e a RAM da instância (1,9 GB, já com swap).
# Como nada avisava, cinco dias passaram sem ninguém notar.
#
# O que este envelope garante:
#   1. TETO de tempo — a rodada morre em vez de ficar pendurada;
#   2. TRAVA — nunca começa uma rodada com a anterior ainda viva;
#   3. o motivo do fim fica ESCRITO no log (concluída / abortada / pulada).
#
# Não conserta a lentidão que causa o travamento; limita o estrago dela.
# ============================================================================
set -u
RAIZ=/opt/integracomm
COMPOSE="$RAIZ/deploy/docker-compose.yml"
LOCK=/var/lock/integracomm-diaria.lock
TETO=${TETO_RODADA:-4h}     # rodada saudável leva 1h45–3h50 (log de 14–21/07)

agora() { date '+%Y-%m-%d %H:%M:%S'; }

cd "$RAIZ" || exit 1

# fd 9 segura a trava enquanto este processo viver; `-n` = não espera
exec 9>"$LOCK"
if ! flock -n 9; then
    echo "=== $(agora) PULADA: a rodada anterior ainda está em execução ==="
    exit 0
fi

timeout -k 60 "$TETO" /usr/bin/docker compose -f "$COMPOSE" exec -T app sh /app/deploy/daily_run.sh
CODIGO=$?

if [ "$CODIGO" -eq 124 ] || [ "$CODIGO" -eq 137 ]; then
    echo "=== $(agora) ABORTADA: estourou o teto de $TETO ==="
    # matar o cliente do `docker exec` NÃO mata o processo dentro do container:
    # ele seguiria consumindo gateway e RAM com a trava já liberada. A imagem é
    # slim (sem pkill/pgrep), então o alvo vem do `docker top`, que dá o PID no
    # HOST — e o kill sai daqui mesmo.
    PIDS=$(docker top deploy-app-1 -eo pid,args 2>/dev/null \
           | grep -E 'run_portfolio|daily_run|sync_cancelamentos|sync_marketing' \
           | awk '{print $1}')
    if [ -n "$PIDS" ]; then
        echo "    matando o que sobrou dentro do container: $PIDS"
        kill -TERM $PIDS 2>/dev/null
        sleep 10
        kill -KILL $PIDS 2>/dev/null
    fi
elif [ "$CODIGO" -ne 0 ]; then
    echo "=== $(agora) FALHOU: código $CODIGO ==="
else
    echo "=== $(agora) rodada concluída ==="
fi
exit 0
