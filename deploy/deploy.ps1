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
    [string]$RemotePath = "/opt/integracomm",
    # pula a confirmacao da worktree suja (uso NAO interativo). O prompt segue
    # sendo o padrao p/ uso humano - so nao trava execucao automatizada.
    [switch]$SemConfirmacao
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

if (-not (Test-Path $KeyPath)) { throw "Chave SSH nao encontrada em $KeyPath (baixe no console Lightsail: Account > SSH keys)." }

$dirty = git status --porcelain
if ($dirty) {
    Write-Host "AVISO: ha mudancas NAO commitadas - elas nao vao subir (o deploy usa o ultimo commit):" -ForegroundColor Yellow
    git status --short
    if ($SemConfirmacao) {
        Write-Host "(-SemConfirmacao: seguindo com o ultimo commit)" -ForegroundColor Yellow
    } else {
        $answer = Read-Host "Continuar mesmo assim? (s/N)"
        if ($answer -ne 's') { Write-Host "Cancelado."; exit 1 }
    }
}

# INCIDENTE 22/07: o build do SPA rodava DENTRO do servidor (estagio bun no
# Dockerfile) e derrubou a instancia por falta de RAM — o build do Docker NAO
# respeita mem_limit. Desde entao o dist e buildado AQUI e viaja no pacote.
Write-Host "== [1/4] checando tipos e buildando o frontend LOCALMENTE ==" -ForegroundColor Cyan
$bun = "$env:USERPROFILE\.bun\bin\bun.exe"
if (-not (Test-Path $bun)) { throw "bun nao encontrado em $bun (necessario p/ buildar o SPA antes do deploy)." }
Push-Location (Join-Path $root "frontend")
# `vite build` NAO checa tipos: em 22/07 uma variavel removida passou pelo build
# e deixou a tela de Melhor Horario EM BRANCO (ReferenceError so em runtime). O
# typecheck e o unico passo que pega isso — roda antes e aborta o deploy.
& $bun run typecheck
if ($LASTEXITCODE -ne 0) { Pop-Location; throw "typecheck do frontend falhou - deploy abortado." }
& $bun run build
$okBuild = $LASTEXITCODE -eq 0
Pop-Location
if (-not $okBuild) { throw "build do frontend falhou - deploy abortado." }
if (-not (Test-Path (Join-Path $root "frontend\dist\index.html"))) { throw "frontend/dist nao foi gerado." }

Write-Host "== [2/4] empacotando codigo (git archive HEAD) + dist ==" -ForegroundColor Cyan
$tarPath = Join-Path $env:TEMP "integracomm_update.tar.gz"
$distPath = Join-Path $env:TEMP "integracomm_dist.tar.gz"
foreach ($p in @($tarPath, $distPath)) { if (Test-Path $p) { Remove-Item $p } }
git archive --format=tar.gz -o $tarPath HEAD
# dist/ e gitignored (nao entra no archive) - vai num pacote proprio
tar -czf $distPath -C $root "frontend/dist"
Write-Host ("   codigo {0:N1} MB · dist {1:N1} MB" -f ((Get-Item $tarPath).Length / 1MB), ((Get-Item $distPath).Length / 1MB))

Write-Host "== [3/4] enviando para o servidor ==" -ForegroundColor Cyan
scp -i $KeyPath $tarPath "ubuntu@${ServerIP}:/tmp/integracomm_update.tar.gz"
if ($LASTEXITCODE -ne 0) { throw "scp do codigo falhou (codigo $LASTEXITCODE)." }
scp -i $KeyPath $distPath "ubuntu@${ServerIP}:/tmp/integracomm_dist.tar.gz"
if ($LASTEXITCODE -ne 0) { throw "scp do dist falhou (codigo $LASTEXITCODE)." }

Write-Host "== [4/4] extraindo e reconstruindo no servidor ==" -ForegroundColor Cyan
# rm -rf do dist antigo antes de extrair: arquivos com hash no nome se acumulam
$remoteCmd = "set -e; cd $RemotePath && tar -xzf /tmp/integracomm_update.tar.gz && rm -rf frontend/dist && tar -xzf /tmp/integracomm_dist.tar.gz && sudo docker compose -f deploy/docker-compose.yml up -d --build && sudo docker compose -f deploy/docker-compose.yml ps"
ssh -i $KeyPath "ubuntu@$ServerIP" $remoteCmd
if ($LASTEXITCODE -ne 0) { throw "atualizacao no servidor falhou (codigo $LASTEXITCODE)." }

Write-Host "PRONTO. https://ia.integracomm.com.br atualizado." -ForegroundColor Green
