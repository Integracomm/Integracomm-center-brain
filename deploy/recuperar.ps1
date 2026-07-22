# ============================================================================
# recuperar.ps1 — pós-incidente: confere o servidor e refaz o deploy pelo
# caminho LEVE (sem build remoto). Criado no incidente 22/07/2026, em que o
# estágio bun do Dockerfile buildava o SPA dentro da instância e derrubou o
# host (SSH parando no banner exchange).
#
# Uso:  powershell -ExecutionPolicy Bypass -File deploy\recuperar.ps1
#       -SoDiagnostico   → só mostra o estado, não mexe em nada
# ============================================================================
param(
    [string]$ServerIP = "56.125.8.49",
    [string]$KeyPath = "$env:USERPROFILE\Downloads\lightsail.pem",
    [string]$RemotePath = "/opt/integracomm",
    [switch]$SoDiagnostico
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

Write-Host "== [1] diagnostico do servidor ==" -ForegroundColor Cyan
$diag = @"
echo '--- uptime/carga ---'; uptime
echo '--- memoria (MB) ---'; free -m
echo '--- containers ---'; sudo docker ps -a --format '{{.Names}}  {{.Status}}'
echo '--- build pendurado? ---'; pgrep -af 'docker.*build|buildkit' | head -5 || echo 'nenhum build rodando'
echo '--- OOM recente no kernel ---'; sudo dmesg -T 2>/dev/null | grep -i 'out of memory' | tail -3 || echo 'sem OOM no dmesg'
echo '--- flags SPA no .env ---'; grep '^SPA_' .env || echo 'NENHUMA FLAG SPA'
"@
ssh -i $KeyPath -o ConnectTimeout=30 "ubuntu@$ServerIP" "cd $RemotePath; $diag"
if ($LASTEXITCODE -ne 0) { throw "servidor ainda inacessivel — reinicie a instancia no console do Lightsail." }

if ($SoDiagnostico) { Write-Host "(diagnostico apenas — nada alterado)" -ForegroundColor Yellow; exit 0 }

Write-Host "== [2] limpando restos do build que derrubou o host ==" -ForegroundColor Cyan
# cache do buildkit fica ocupando disco/RAM apos o build abortado; o prune e
# seguro (nao toca em imagens em uso nem em volumes de dados)
ssh -i $KeyPath "ubuntu@$ServerIP" "sudo docker builder prune -af 2>&1 | tail -2; sudo docker image prune -f 2>&1 | tail -1"

Write-Host "== [3] subindo os containers com a imagem ATUAL (sem rebuild) ==" -ForegroundColor Cyan
# primeiro objetivo: site DE VOLTA no ar com o codigo que ja esta na imagem
ssh -i $KeyPath "ubuntu@$ServerIP" "cd $RemotePath && sudo docker compose -f deploy/docker-compose.yml up -d --no-build && sudo docker compose -f deploy/docker-compose.yml ps"
if ($LASTEXITCODE -ne 0) { throw "falha ao subir os containers." }

Write-Host "== [4] conferindo o site ==" -ForegroundColor Cyan
try {
    $r = Invoke-WebRequest -Uri "https://ia.integracomm.com.br" -UseBasicParsing -TimeoutSec 30 -MaximumRedirection 0 -ErrorAction Stop
    Write-Host "   HTTP $($r.StatusCode) — site respondendo" -ForegroundColor Green
} catch {
    $code = if ($_.Exception.Response) { $_.Exception.Response.StatusCode.value__ } else { "sem resposta" }
    Write-Host "   HTTP $code" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "PROXIMO PASSO: com o site no ar, rode o deploy normal — ele agora" -ForegroundColor Green
Write-Host "builda o SPA LOCALMENTE e so envia o dist (nao builda no servidor):" -ForegroundColor Green
Write-Host "   powershell -ExecutionPolicy Bypass -File deploy\deploy.ps1" -ForegroundColor White
