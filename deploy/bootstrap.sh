#!/bin/bash
# ============================================================================
# bootstrap.sh — sobe o painel Integracomm IA num Ubuntu 22.04/24.04 zerado.
#
# Pré-requisitos (ver deploy/RUNBOOK.md):
#   - bundle extraído em /opt/integracomm (este script roda de lá)
#   - .env na raiz com DOMAIN=... preenchido
#   - DNS do domínio já apontando para o IP desta máquina (portas 80/443 abertas)
#
#     cd /opt/integracomm && sudo bash deploy/bootstrap.sh
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

echo "== [1/6] valida .env =="
[ -f .env ] || { echo "ERRO: .env não encontrado na raiz ($ROOT)"; exit 1; }
grep -q '^DOMAIN=..*' .env || { echo "ERRO: preencha DOMAIN=seu.dominio no .env"; exit 1; }
grep -q '^DB_PASSWORD=..*' .env || { echo "ERRO: DB_PASSWORD ausente no .env (o make_bundle gera)"; exit 1; }

echo "== [2/6] timezone + docker =="
timedatectl set-timezone America/Sao_Paulo || true
if ! command -v docker >/dev/null 2>&1; then
    curl -fsSL https://get.docker.com | sh
fi

echo "== [3/6] sobe os serviços (build da imagem na 1ª vez: ~2 min) =="
mkdir -p logs deploy/restore
docker compose -f deploy/docker-compose.yml up -d --build

echo "== [4/6] restaura o banco local (se houver dump e o banco estiver vazio) =="
if [ -f deploy/restore/db.dump ]; then
    sleep 5
    TABLES=$(docker compose -f deploy/docker-compose.yml exec -T db \
        psql -U integracomm_app -d integracomm_ia -tAc \
        "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
    if [ "${TABLES:-0}" = "0" ]; then
        echo "   restaurando dump..."
        docker compose -f deploy/docker-compose.yml exec -T db \
            pg_restore -U integracomm_app -d integracomm_ia --no-owner --no-privileges /restore/db.dump
        echo "   banco restaurado."
    else
        echo "   banco já tem $TABLES tabelas — restauração pulada."
    fi
else
    echo "   sem deploy/restore/db.dump — banco começa vazio (schema criado pelo app)."
fi

echo "== [5/6] cron da rodada diária (06:00) =="
CRON_LINE="0 6 * * * cd $ROOT && /usr/bin/docker compose -f deploy/docker-compose.yml exec -T app sh /app/deploy/daily_run.sh >> $ROOT/logs/cron_diario.log 2>&1"
( crontab -l 2>/dev/null | grep -v 'daily_run.sh' ; echo "$CRON_LINE" ) | crontab -
echo "   instalado: $CRON_LINE"

echo "== [6/6] smoke test =="
sleep 3
docker compose -f deploy/docker-compose.yml ps
docker compose -f deploy/docker-compose.yml exec -T app \
    python -c "import httpx; print('healthz interno:', httpx.get('http://localhost:8000/healthz').status_code)" || true

DOMAIN=$(grep '^DOMAIN=' .env | cut -d= -f2)
echo ""
echo "=============================================================="
echo " Pronto. Acesse:  https://$DOMAIN"
echo " (o certificado HTTPS é emitido no 1º acesso — pode levar ~30s)"
echo " Login admin: adm@integracomm.com.br + AUTH_ADMIN_PASSWORD do .env"
echo " Gestores: 'Criar sua conta' na tela de login -> você aprova no hub"
echo "=============================================================="
