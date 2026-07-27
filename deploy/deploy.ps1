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
    [switch]$SemConfirmacao,
    # deploya MESMO com a rodada diaria em andamento (mata a pontuacao do dia).
    # So use quando a rodada estiver comprovadamente travada e voce quiser
    # substitui-la — ver o guarda no passo [2.5/4].
    [switch]$MesmoComRodada,
    # deploya SEM ter validado no painel local. Existe para emergencia (hotfix
    # com o local fora do ar); o padrao e a regra da casa: local primeiro.
    [switch]$SemValidacaoLocal
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

# =============================================================================
# GUARDA DE ORDEM: LOCAL PRIMEIRO, ONLINE DEPOIS (regra do Otavio, 10/07)
# -----------------------------------------------------------------------------
# "O localhost deve sempre ser atualizado primeiro, e apenas depois de validacao
# e que a aplicacao online deve ser alterada. Do contrario ficaria muito dificil
# analisar se erros foram deixados de lado durante alguma atualizacao." (27/07)
#
# A regra existia desde 10/07 e mesmo assim foi violada 6x em 27/07: cada deploy
# subiu direto e o painel local ficou para tras EM SILENCIO — o Otavio viu a
# correcao de fuso valendo online e nao no local, e perdeu a chance de validar
# antes. Depender da minha memoria nao funcionou; agora o script confere.
#
# Como se mede: o uvicorn local roda SEM --reload, entao ele so tem o codigo
# novo se o processo tiver sido iniciado DEPOIS do ultimo commit que mexeu em
# backend/ ou frontend/. Se for mais velho, o local esta defasado.
# =============================================================================
Write-Host "== [0/4] o painel LOCAL esta com este codigo? ==" -ForegroundColor Cyan
$commitCodigo = git log -1 --format=%cI -- backend frontend
$dtCommit = if ($commitCodigo) { [datetime]::Parse($commitCodigo) } else { $null }
# O painel carimba o proprio boot em logs/painel_boot.txt (ver _prewarm em
# api.py). NAO use Get-Process().StartTime: o painel roda como SYSTEM e um
# PowerShell sem elevacao le vazio - o guarda acusaria "defasado" sempre.
$bootFile = Join-Path $root "logs\painel_boot.txt"
$dtBoot = $null
if (Test-Path $bootFile) {
    try { $dtBoot = [datetime]::Parse((Get-Content $bootFile -Raw).Trim()) } catch { $dtBoot = $null }
}

if (-not $dtBoot) {
    Write-Host "   painel local nunca registrou boot (nao rodou desde esta melhoria?)" -ForegroundColor Yellow
    $localOk = $false
} else {
    $localOk = ($dtCommit -ne $null -and $dtBoot -gt $dtCommit)
    if ($localOk) {
        Write-Host ("   OK - painel local subiu {0}, depois do ultimo commit de codigo" -f $dtBoot.ToLocalTime().ToString('dd/MM HH:mm')) -ForegroundColor Green
    } else {
        Write-Host ("   DEFASADO - painel local subiu {0}, ANTES do ultimo commit ({1})" -f $dtBoot.ToLocalTime().ToString('dd/MM HH:mm'), $dtCommit.ToLocalTime().ToString('dd/MM HH:mm')) -ForegroundColor Yellow
    }
}

if (-not $localOk) {
    Write-Host "   Regra da casa: validar no localhost:8000 ANTES de subir para os gestores." -ForegroundColor Yellow
    Write-Host "   Reinicie o painel local (tarefa IntegracommIA-Painel) e valide; depois rode o deploy." -ForegroundColor Yellow
    if ($SemValidacaoLocal) {
        Write-Host "   (-SemValidacaoLocal: seguindo assim mesmo, sob sua responsabilidade)" -ForegroundColor Yellow
    } elseif ($SemConfirmacao) {
        throw "painel local defasado - deploy abortado. Valide local primeiro ou use -SemValidacaoLocal."
    } else {
        $r = Read-Host "   Subir para PRODUCAO sem ter validado no local? (s/N)"
        if ($r -notmatch '^[sS]') { Write-Host "Cancelado - valide no local primeiro."; exit 1 }
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

# GUARDA (27/07): `up -d --build` RECRIA o container do app e MATA o que estiver
# rodando dentro dele. A rodada diaria das 06h morreu assim hoje, as 08:10, por
# causa de um deploy meu — e o log so dizia "estourou o teto de 4h", o que
# escondeu a causa por dias. Deployar por cima de uma rodada custa o dia inteiro
# de pontuacao e o relatorio do Slack.
Write-Host "== [2.5/4] checando se ha rodada em andamento ==" -ForegroundColor Cyan
$rodando = ssh -i $KeyPath "ubuntu@$ServerIP" "sudo docker top deploy-app-1 -eo pid,args 2>/dev/null | grep -E 'daily_run|python -m scripts\.' | head -3"
if ($rodando -and -not $MesmoComRodada) {
    Write-Host "   ATENCAO: ha processo da rodada ativo no container:" -ForegroundColor Yellow
    Write-Host "   $rodando" -ForegroundColor Yellow
    if (-not $SemConfirmacao) {
        $r = Read-Host "   Deployar agora MATA essa rodada (perde a pontuacao do dia). Continuar? (s/N)"
        if ($r -notmatch '^[sS]') { throw "deploy cancelado - rodada em andamento." }
    } else {
        throw "rodada em andamento - deploy abortado. Espere terminar ou rode com -MesmoComRodada."
    }
} elseif ($rodando) {
    Write-Host "   rodada ativa, mas -MesmoComRodada foi passado - seguindo" -ForegroundColor Yellow
} else {
    # ATENCAO: NADA de travessao/acento DENTRO de string neste arquivo. O PS 5.1
    # le .ps1 sem BOM como ANSI e o travessao vira aspa curva (0x94), que FECHA
    # a string e quebra o parse do script inteiro. Foi assim que este guarda
    # abortou o deploy em 27/07. Em comentario passa; em string, nao.
    Write-Host "   nenhuma rodada ativa - seguro" -ForegroundColor Green
}

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
