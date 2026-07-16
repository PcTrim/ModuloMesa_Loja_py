# Gate de produção (unit + api + integration). Exit != 0 bloqueia deploy.
# Uso: powershell -ExecutionPolicy Bypass -File deploy\run_test_gate.ps1
# Skip: $env:SKIP_TEST_GATE = "1"

$ErrorActionPreference = "Stop"
$AppRoot = Split-Path -Parent $PSScriptRoot
Set-Location $AppRoot

Write-Host "==> Test gate (tests/unit + tests/api + tests/integration)"
python -m tests.run_gate
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERRO: gate de testes falhou (exit $LASTEXITCODE)"
    exit $LASTEXITCODE
}
Write-Host "==> Gate OK"
