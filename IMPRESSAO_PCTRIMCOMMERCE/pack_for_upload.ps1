# Empacota PcTrim Commerce para upload (exclui .venv, .env, output, etc.)
# Uso: powershell -ExecutionPolicy Bypass -File deploy\pack_for_upload.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Dist = Join-Path $PSScriptRoot "dist"
$Ts = Get-Date -Format "yyyyMMdd_HHmmss"
$ZipName = "LojaOnline_upload_$Ts.zip"
$ZipPath = Join-Path $Dist $ZipName

$ExcludeDirs = @(
    ".venv", ".venv-1", "__pycache__", ".git", ".pytest_cache", ".idea", ".vscode",
    "output", "pedidos_salvos_export", "dist", "pedidos"
)
$ExcludeFiles = @(".env", "ultimo_arranque_loja.txt", "loja_erros.log")

New-Item -ItemType Directory -Force -Path $Dist | Out-Null

$Temp = Join-Path $env:TEMP "LojaOnline_pack_$Ts"
if (Test-Path $Temp) { Remove-Item -Recurse -Force $Temp }
New-Item -ItemType Directory -Force -Path $Temp | Out-Null

Write-Host "==> Copiando para staging: $Temp"

Get-ChildItem -Path $Root -Force | ForEach-Object {
    $name = $_.Name
    if ($ExcludeDirs -contains $name) { return }
    if ($_.PSIsContainer) {
        Copy-Item -Path $_.FullName -Destination (Join-Path $Temp $name) -Recurse -Force
    } else {
        if ($ExcludeFiles -contains $name) { return }
        Copy-Item -Path $_.FullName -Destination (Join-Path $Temp $name) -Force
    }
}

# Remover __pycache__ e .pyc recursivamente
Get-ChildItem -Path $Temp -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -Path $Temp -Recurse -Filter "*.pyc" -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue

if (Test-Path $ZipPath) { Remove-Item -Force $ZipPath }
Compress-Archive -Path (Join-Path $Temp "*") -DestinationPath $ZipPath -CompressionLevel Optimal
Remove-Item -Recurse -Force $Temp

$sizeMb = [math]::Round((Get-Item $ZipPath).Length / 1MB, 2)
Write-Host "==> Pacote criado: $ZipPath ($sizeMb MB)"
Write-Host "    Envie o conteudo do ZIP para /var/www/html/LojaOnline no servidor (FileZilla ou scp)."
