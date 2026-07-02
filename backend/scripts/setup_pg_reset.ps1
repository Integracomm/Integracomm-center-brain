# ============================================================================
# RESET da senha do superusuário postgres — RODAR COMO ADMINISTRADOR.
# Procedimento padrão de recuperação (trust temporário). Seguro:
#  - backup do pg_hba.conf antes de tocar
#  - try/finally garante reverter o pg_hba.conf e reiniciar mesmo em erro
#  - a senha NOVA é gerada aleatoriamente e gravada no .env (NUNCA impressa)
# Depois disto, o Claude (sem privilégio) cria o banco/role e aplica o schema.
# ============================================================================
$ErrorActionPreference = 'Stop'
$bin  = 'C:\Program Files\PostgreSQL\18\bin'
$data = 'C:\Program Files\PostgreSQL\18\data'
$hba  = Join-Path $data 'pg_hba.conf'
$svc  = 'postgresql-x64-18'
$envFile = Join-Path $PSScriptRoot '..\..\.env'

# exige elevação
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { Write-Error "Rode este script num PowerShell COMO ADMINISTRADOR."; exit 1 }

$stamp  = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = "$hba.bak-$stamp"
Copy-Item $hba $backup -Force
Write-Host "Backup do pg_hba.conf -> $backup"

# senha nova aleatoria (24 chars)
$pw = -join ((48..57)+(65..90)+(97..122) | Get-Random -Count 24 | ForEach-Object {[char]$_})

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)  # sem BOM (BOM quebra o parser do Postgres)
try {
    # 1) trust temporario (loopback + local) — escrito SEM BOM
    $trustContent = (Get-Content $hba -Raw) -replace 'scram-sha-256','trust' -replace '\bmd5\b','trust'
    [System.IO.File]::WriteAllText($hba, $trustContent, $utf8NoBom)
    Restart-Service $svc -Force
    Start-Sleep -Seconds 3

    # 2) define a senha nova (trust = entra sem senha)
    & "$bin\psql.exe" -U postgres -h localhost -d postgres -v ON_ERROR_STOP=1 -c "ALTER USER postgres WITH PASSWORD '$pw';"
    if ($LASTEXITCODE -ne 0) { throw "ALTER USER falhou (exit $LASTEXITCODE)" }
}
finally {
    # 3) reverte SEMPRE para o pg_hba.conf original e reinicia
    Copy-Item $backup $hba -Force
    Restart-Service $svc -Force
    Start-Sleep -Seconds 3
    Write-Host "pg_hba.conf revertido ao original e serviço reiniciado."
}

# 4) verifica autenticacao por senha
$env:PGPASSWORD = $pw
& "$bin\psql.exe" -U postgres -h localhost -d postgres -c "SELECT 'auth-ok' AS status;" | Out-Null
$ok = ($LASTEXITCODE -eq 0)
$env:PGPASSWORD = $null
if (-not $ok) { Write-Error "Verificacao por senha FALHOU."; exit 1 }

# 5) grava a senha no .env (sem imprimir), para o Claude usar no setup
$envFull = [System.IO.Path]::GetFullPath($envFile)
$lines = @()
if (Test-Path $envFull) { $lines = Get-Content $envFull | Where-Object { $_ -notmatch '^PG_SUPERUSER_PASSWORD=' } }
$lines += "PG_SUPERUSER_PASSWORD=$pw"
[System.IO.File]::WriteAllLines($envFull, $lines, $utf8NoBom)  # sem BOM

Write-Host "OK: senha do postgres redefinida, pg_hba.conf restaurado, PG_SUPERUSER_PASSWORD gravada no .env."
Write-Host "Pode fechar este terminal admin e avisar o Claude para seguir."
