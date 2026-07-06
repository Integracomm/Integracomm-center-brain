# ============================================================================
# setup_tasks.ps1 — registra as tarefas agendadas da Integracomm IA.
#
# COMO USAR: clique com o botao direito neste arquivo -> "Executar com o
# PowerShell" COMO ADMINISTRADOR. Ou, num PowerShell ELEVADO:
#     powershell -ExecutionPolicy Bypass -File "<caminho>\setup_tasks.ps1"
#
# Registra DUAS tarefas, ambas como SYSTEM (rodam sem ninguem logado, sem senha):
#   1. IntegracommIA-Painel       -> sobe o servidor web (localhost:8000) no BOOT
#   2. IntegracommIA-RodadaDiaria -> roda a carteira + envia ao Slack, 06:00
#
# Usa os cmdlets ScheduledTasks (nao o schtasks.exe) porque o caminho do projeto
# tem espacos e acento ("Nova aplicacao Integracomm"), o que quebra o parser de
# aspas do schtasks /TR. Os cmdlets recebem programa e argumentos separados.
# ============================================================================
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

# --- garante execucao elevada (SYSTEM exige admin) ---
$isAdmin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "ERRO: rode este script como ADMINISTRADOR." -ForegroundColor Red
    Write-Host "Clique com o botao direito -> 'Executar com o PowerShell' (admin)," -ForegroundColor Yellow
    Write-Host "ou abra um PowerShell como administrador e rode-o de novo." -ForegroundColor Yellow
    Read-Host "Enter para sair"
    exit 1
}

$painelCmd = Join-Path $root 'start_painel.cmd'
$rodadaPs1 = Join-Path $root 'run_agent_scheduled.ps1'
foreach ($f in @($painelCmd, $rodadaPs1)) {
    if (-not (Test-Path $f)) { throw "arquivo nao encontrado: $f" }
}

$system = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest

# 1) Servidor web no boot (sem limite de tempo — fica no ar)
$aPainel = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument ('/c "{0}"' -f $painelCmd)
$tPainel = New-ScheduledTaskTrigger -AtStartup
$tPainel.Delay = 'PT30S'   # espera 30s no boot (deixa o Postgres subir antes)
$sPainel = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName 'IntegracommIA-Painel' -Principal $system -Action $aPainel `
    -Trigger $tPainel -Settings $sPainel -Force `
    -Description 'Sobe o painel web da Integracomm IA (localhost:8000) no boot do Windows.' | Out-Null
Write-Host "OK  IntegracommIA-Painel (boot -> localhost:8000)" -ForegroundColor Green

# 2) Rodada diaria + Slack, 06:00
$aRodada = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument ('-NoProfile -ExecutionPolicy Bypass -File "{0}"' -f $rodadaPs1)
$tRodada = New-ScheduledTaskTrigger -Daily -At '06:00'
$sRodada = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Register-ScheduledTask -TaskName 'IntegracommIA-RodadaDiaria' -Principal $system -Action $aRodada `
    -Trigger $tRodada -Settings $sRodada -Force `
    -Description 'Rodada diaria da carteira de Growth + envio do relatorio ao Slack (06:00).' | Out-Null
Write-Host "OK  IntegracommIA-RodadaDiaria (diaria 06:00 -> Slack)" -ForegroundColor Green

Write-Host ""
Write-Host "Tarefas registradas. Para testar o servidor agora sem reiniciar:" -ForegroundColor Cyan
Write-Host "    Start-ScheduledTask -TaskName IntegracommIA-Painel" -ForegroundColor Cyan
Write-Host "    (aguarde ~10s e abra http://localhost:8000/)" -ForegroundColor Cyan
Read-Host "Enter para sair"
