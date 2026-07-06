# ============================================================================
# make_bundle.ps1 — monta o pacote de deploy (código + dump do banco + .env
# do servidor) em Downloads\integracomm_bundle.tar.gz. Rodar na SUA máquina:
#     powershell -ExecutionPolicy Bypass -File deploy\make_bundle.ps1
# ============================================================================
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$stage = Join-Path $env:TEMP 'integracomm_bundle'
if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
New-Item -ItemType Directory -Path $stage | Out-Null

Write-Host "== [1/4] codigo (arquivos versionados do git) =="
# NUNCA canalizar binario pelo pipe do PowerShell (corrompe): escreve em arquivo
$codeTar = Join-Path $env:TEMP 'integracomm_code.tar'
git archive --format=tar -o $codeTar HEAD
tar -xf $codeTar -C $stage
Remove-Item $codeTar
# caches offline necessarios a rodada diaria (data/ e gitignored)
New-Item -ItemType Directory -Path (Join-Path $stage 'data') -Force | Out-Null
foreach ($f in @('wa_analyses.csv','wa_groups.csv','nps_fat.csv','cases_expanded.csv','controls_active_bundles.csv')) {
    $src = Join-Path $root "data\$f"
    if (Test-Path $src) { Copy-Item $src (Join-Path $stage "data\$f") }
}

Write-Host "== [2/4] dump do banco local =="
$envMap = @{}
foreach ($line in Get-Content (Join-Path $root '.env')) {
    if ($line -and -not $line.StartsWith('#') -and $line.Contains('=')) {
        $k, $v = $line.Split('=', 2); $envMap[$k.Trim()] = $v.Trim()
    }
}
$pgdump = Get-ChildItem 'C:\Program Files\PostgreSQL\*\bin\pg_dump.exe' -ErrorAction SilentlyContinue |
    Sort-Object FullName -Descending | Select-Object -First 1
if (-not $pgdump) { throw 'pg_dump.exe nao encontrado em C:\Program Files\PostgreSQL' }
New-Item -ItemType Directory -Path (Join-Path $stage 'deploy\restore') -Force | Out-Null
& $pgdump.FullName --dbname=$($envMap['APP_DATABASE_URL']) -Fc --no-owner --no-privileges `
    -f (Join-Path $stage 'deploy\restore\db.dump')
Write-Host ("   dump: {0:N1} MB" -f ((Get-Item (Join-Path $stage 'deploy\restore\db.dump')).Length / 1MB))

Write-Host "== [3/4] .env do servidor =="
function New-Secret([int]$bytes = 24) {
    $b = New-Object byte[] $bytes
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
    return ([Convert]::ToBase64String($b) -replace '[+/=]', 'x')
}
$dbpw = New-Secret 18
$serverEnv = @(
    '# ===== Integracomm IA - .env do SERVIDOR (gerado por make_bundle.ps1) ====='
    '# >>> PREENCHA o dominio antes de rodar o bootstrap: <<<'
    'DOMAIN='
    ''
    "DB_PASSWORD=$dbpw"
    "AUTH_SECRET=$(New-Secret 32)"
    "AUTH_ADMIN_PASSWORD=$($envMap['AUTH_ADMIN_PASSWORD'])"
    "AUTH_GESTOR_GROWTH_PASSWORD=$($envMap['AUTH_GESTOR_GROWTH_PASSWORD'])"
    ''
    '# fontes (read-only) - copiadas do .env local'
    "CLICKUP_API_TOKEN=$($envMap['CLICKUP_API_TOKEN'])"
    "CLICKUP_WORKSPACE_ID=$($envMap['CLICKUP_WORKSPACE_ID'])"
    "CLICKUP_LIST_FUNIL_CS=$($envMap['CLICKUP_LIST_FUNIL_CS'])"
    "CLICKUP_LIST_ASSESSORIA=$($envMap['CLICKUP_LIST_ASSESSORIA'])"
    "WHATSAPP_READ_API_URL=$($envMap['WHATSAPP_READ_API_URL'])"
    "WHATSAPP_READ_API_KEY=$($envMap['WHATSAPP_READ_API_KEY'])"
    "SLACK_WEBHOOK_URL=$($envMap['SLACK_WEBHOOK_URL'])"
    "ANTHROPIC_API_KEY=$($envMap['ANTHROPIC_API_KEY'])"
    'GROWTH_LLM_PLANS=0'
    ''
    '# o compose injeta APP_DATABASE_URL apontando pro servico db'
) -join "`n"
[IO.File]::WriteAllText((Join-Path $stage '.env'), $serverEnv + "`n")

Write-Host "== [4/4] empacota =="
$out = Join-Path $env:USERPROFILE 'Downloads\integracomm_bundle.tar.gz'
if (Test-Path $out) { Remove-Item $out }
tar -czf $out -C $stage .
Write-Host ("PRONTO: {0}  ({1:N1} MB)" -f $out, ((Get-Item $out).Length / 1MB)) -ForegroundColor Green
Write-Host "Proximo passo: deploy\RUNBOOK.md (enviar ao servidor e rodar o bootstrap)."
