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

# LIBERA A RAM ANTES DA RODADA (27/07) — a causa raiz das mortes.
# O painel acumula cache do ClickUp ao longo do dia (chegou a 1,34 GB num host
# de 1,9 GB) e a rodada precisa de ~515 MB: não cabia, e o kernel matava o
# processo (global_oom). Reiniciar o container do app IMEDIATAMENTE antes
# devolve a memória — às 06h ninguém está usando o painel, então o custo é
# zero, e ele volta a encher sozinho conforme o dia. Sem isso, a rodada
# dependeria de alguém lembrar de desligar o prewarm na véspera.
echo "=== $(agora) liberando memória: reiniciando o painel antes da rodada ==="
/usr/bin/docker compose -f "$COMPOSE" restart app >/dev/null 2>&1 \
    || echo "    (aviso: restart do app falhou — seguindo assim mesmo)"
sleep 20   # o app volta a atender antes de a rodada começar a consumir

INICIO=$(date +%s)
# 27/07: `run --rm rodada` (container PRÓPRIO, perfil `batch`) no lugar de
# `exec app`. A rodada deixa de dividir o cgroup do painel: ganha teto e swap
# seus, e um estouro vira lentidão dela em vez de OOM do HOST — que em 27/07
# matou o processo e levaria junto painel/Caddy/SSH se o kernel escolhesse
# outra vítima. `--rm` garante que o container some ao terminar.
timeout -k 60 "$TETO" /usr/bin/docker compose -f "$COMPOSE" run --rm -T rodada
CODIGO=$?

DUROU=$(( $(date +%s) - INICIO ))
if [ "$CODIGO" -eq 124 ] || [ "$CODIGO" -eq 137 ]; then
    # 27/07: os dois códigos imprimiam "estourou o teto de 4h" e isso ESCONDEU
    # três falhas DIFERENTES por dias — 25 e 26/07 bateram o teto de verdade
    # (4h exatas), mas 24/07 morreu em 1h53 e 27/07 em 2h10, que não é teto
    # nenhum. 137 = SIGKILL: OOM do cgroup ou o container recriado por baixo
    # (um `deploy` durante a rodada mata o processo que roda dentro dele).
    # Diagnóstico só existe se o log disser o que REALMENTE aconteceu.
    if [ "$CODIGO" -eq 124 ]; then
        echo "=== $(agora) ABORTADA: estourou o teto de $TETO (rodou ${DUROU}s) ==="
    else
        echo "=== $(agora) ABORTADA: processo MORTO (SIGKILL, código 137) após ${DUROU}s —" \
             "NÃO foi o teto de $TETO. Suspeitar de OOM do cgroup ou de deploy/restart" \
             "do container durante a rodada ==="
    fi
    # matar o cliente do `docker exec` NÃO mata o processo dentro do container:
    # ele seguiria consumindo gateway e RAM com a trava já liberada. A imagem é
    # slim (sem pkill/pgrep), então o alvo vem do `docker top`, que dá o PID no
    # HOST — e o kill sai daqui mesmo.
    # o padrão pega o script E qualquer etapa `python -m scripts.X` (hoje
    # run_portfolio, sync_cancelamentos, sync_marketing, check_nps_fill; amanhã
    # o que entrar). NÃO casa com o painel, que é `python -m uvicorn`.
    # com container próprio, derrubar a rodada é parar O CONTAINER DELA — sem
    # tocar no painel. O `docker top` no app fica como rede de segurança para
    # execuções antigas (`exec app`) que ainda estejam vivas.
    docker ps -q --filter "ancestor=integracomm-ia:latest" --filter "status=running" 2>/dev/null \
        | while read -r cid; do
            nome=$(docker inspect -f '{{.Name}}' "$cid" 2>/dev/null)
            case "$nome" in
                *rodada*) echo "    parando container da rodada: $nome"
                          docker stop -t 20 "$cid" >/dev/null 2>&1 ;;
            esac
        done
    alvos() {
        docker top deploy-app-1 -eo pid,args 2>/dev/null \
            | grep -E 'daily_run|python -m scripts\.' | awk '{print $1}'
    }
    PIDS=$(alvos)
    if [ -n "$PIDS" ]; then
        echo "    matando o que sobrou dentro do container: $PIDS"
        kill -TERM $PIDS 2>/dev/null
        sleep 10
        RESTO=$(alvos)
        [ -n "$RESTO" ] && kill -KILL $RESTO 2>/dev/null
        sleep 2
        SOBROU=$(docker top deploy-app-1 -eo pid,args 2>/dev/null \
                 | grep -E 'daily_run|python -m scripts\.')
        [ -n "$SOBROU" ] && echo "    ATENÇÃO, sobreviveu ao kill: $SOBROU"
    fi
elif [ "$CODIGO" -ne 0 ]; then
    echo "=== $(agora) FALHOU: código $CODIGO ==="
else
    echo "=== $(agora) rodada concluída ==="
fi
exit 0
