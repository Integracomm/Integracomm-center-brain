# ============================================================================
# run_agent_scheduled.ps1 — rodada diária do agente de Growth (Task Scheduler)
#
# O que faz:
#   1. Usa o Python do venv do projeto (backend\.venv) — sem depender de PATH
#   2. Roda a carteira completa: python -m scripts.run_portfolio --slack
#      (--slack envia o relatório do estado ao grupo dos gestores ao final)
#   3. Grava todo o output em logs\agent_YYYY-MM-DD.log
#   4. Em caso de erro: registra no log e avisa o grupo do Slack
#
# Agendamento: ver seção "Agendamento diário" no backend/README.md
# ============================================================================
$ErrorActionPreference = 'Continue'
$root   = $PSScriptRoot
$logDir = Join-Path $root 'logs'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$log = Join-Path $logDir ("agent_{0}.log" -f (Get-Date -Format 'yyyy-MM-dd'))
$py  = Join-Path $root 'backend\.venv\Scripts\python.exe'

"=== rodada iniciada em $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" | Add-Content $log

if (-not (Test-Path $py)) {
    "ERRO: venv nao encontrado em $py" | Add-Content $log
    exit 1
}

# roda a partir de backend\ (pythonpath do projeto); cmd /c faz o redirect
Push-Location (Join-Path $root 'backend')
try {
    & cmd /c "`"$py`" -m scripts.run_portfolio --slack >> `"$log`" 2>&1"
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}

if ($code -ne 0) {
    "ERRO: rodada falhou com exit code $code em $(Get-Date -Format 'HH:mm:ss')" | Add-Content $log

    # webhook lido do .env da raiz (nunca hardcoded aqui).
    # Aceita SLACK_GROWTH_WEBHOOK (se existir) ou SLACK_WEBHOOK_URL (o atual).
    $hook = $null
    $envFile = Join-Path $root '.env'
    if (Test-Path $envFile) {
        foreach ($line in Get-Content $envFile) {
            if ($line -match '^SLACK_GROWTH_WEBHOOK=(.+)$') { $hook = $Matches[1].Trim(); break }
            if (-not $hook -and $line -match '^SLACK_WEBHOOK_URL=(.+)$') { $hook = $Matches[1].Trim() }
        }
    }
    if ($hook) {
        $dia  = Get-Date -Format 'yyyy-MM-dd'
        $body = @{ text = ":warning: *Integracomm IA - rodada diaria FALHOU* (exit $code). Ver logs/agent_$dia.log na maquina do agente." } | ConvertTo-Json
        try {
            Invoke-RestMethod -Uri $hook -Method Post -Body $body -ContentType 'application/json' | Out-Null
            "aviso de erro enviado ao Slack" | Add-Content $log
        } catch {
            "falha ao avisar o Slack: $($_.Exception.Message)" | Add-Content $log
        }
    } else {
        "webhook do Slack nao encontrado no .env - erro NAO notificado" | Add-Content $log
    }
    exit $code
}

"OK: rodada concluida em $(Get-Date -Format 'HH:mm:ss')" | Add-Content $log

# --- marketing: coleta diaria (segunda = semanal, com metas + recalculo do lag) ---
Push-Location (Join-Path $root 'backend')
try {
    $flag = if ((Get-Date).DayOfWeek -eq 'Monday') { '--weekly' } else { '' }
    & cmd /c "`"$py`" -m scripts.sync_marketing $flag >> `"$log`" 2>&1"
    "sync marketing: exit $LASTEXITCODE" | Add-Content $log
} finally {
    Pop-Location
}

# --- dia 2 do mes: checagem do preenchimento de faturamento nas planilhas NPS ---
# Avisa no MESMO grupo do Slack quem nao lancou o mes anterior (regra: sem
# faturamento = lancar R$0; nenhum cliente ativo pode ficar em branco).
if ((Get-Date).Day -eq 2) {
    "dia 2: checagem mensal do preenchimento NPS..." | Add-Content $log
    Push-Location (Join-Path $root 'backend')
    try {
        & cmd /c "`"$py`" -m scripts.check_nps_fill --slack >> `"$log`" 2>&1"
        "checagem NPS: exit $LASTEXITCODE" | Add-Content $log
    } finally {
        Pop-Location
    }
}
exit 0
