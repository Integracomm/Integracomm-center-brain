# ============================================================================
# deploy.ps1 — sobe uma atualizacao de codigo pro servidor em 1 comando.
# NAO mexe em .env nem no banco (so codigo versionado no git); seguro rodar
# quantas vezes quiser. Para o 1o deploy (servidor zerado), use make_bundle.ps1
# + RUNBOOK.md em vez deste.
#
#     powershell -ExecutionPolicy Bypass -File deploy\deploy.ps1
# ============================================================================
param(
    [string]$ServerIP = "56.125.8.49",
    [string]$KeyPath = "$env:USERPROFILE\Downloads\lightsail.pem",
    [string]$RemotePath = "/opt/integracomm"
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

if (-not (Test-Path $KeyPath)) { throw "Chave SSH nao encontrada em $KeyPath (baixe no console Lightsail: Account > SSH keys)." }

$dirty = git status --porcelain
if ($dirty) {
    Write-Host "AVISO: ha mudancas NAO commitadas - elas nao vao subir (o deploy usa o ultimo commit):" -ForegroundColor Yellow
    git status --short
    $answer = Read-Host "Continuar mesmo assim? (s/N)"
    if ($answer -ne 's') { Write-Host "Cancelado."; exit 1 }
}

Write-Host "== [1/3] empacotando codigo (git archive HEAD) ==" -ForegroundColor Cyan
$tarPath = Join-Path $env:TEMP "integracomm_update.tar.gz"
if (Test-Path $tarPath) { Remove-Item $tarPath }
git archive --format=tar.gz -o $tarPath HEAD
Write-Host ("   {0:N1} MB" -f ((Get-Item $tarPath).Length / 1MB))

Write-Host "== [2/3] enviando para o servidor ==" -ForegroundColor Cyan
scp -i $KeyPath $tarPath "ubuntu@${ServerIP}:/tmp/integracomm_update.tar.gz"
if ($LASTEXITCODE -ne 0) { throw "scp falhou (codigo $LASTEXITCODE)." }

Write-Host "== [3/3] extraindo e reconstruindo no servidor ==" -ForegroundColor Cyan
$remoteCmd = "set -e; cd $RemotePath && tar -xzf /tmp/integracomm_update.tar.gz && sudo docker compose -f deploy/docker-compose.yml up -d --build && docker compose -f deploy/docker-compose.yml ps"
ssh -i $KeyPath "ubuntu@$ServerIP" $remoteCmd
if ($LASTEXITCODE -ne 0) { throw "atualizacao no servidor falhou (codigo $LASTEXITCODE)." }

Write-Host "PRONTO. https://ia.integracomm.com.br atualizado." -ForegroundColor Green
