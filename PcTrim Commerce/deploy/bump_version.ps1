# Incrementa minor em version.py (ex.: 265-0 -> 265-1)
# Uso: powershell -ExecutionPolicy Bypass -File deploy\bump_version.ps1 [-Quiet]

param(
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$VersionFile = Join-Path $Root "version.py"

if (-not (Test-Path $VersionFile)) {
    Write-Error "version.py nao encontrado: $VersionFile"
    exit 1
}

$c = Get-Content -Raw $VersionFile
if ($c -match 'APP_VERSION\s*=\s*["''](\d+)-(\d+)["'']') {
    $maj = $Matches[1]
    $min = [int]$Matches[2] + 1
    $newVer = "$maj-$min"
    $c = [regex]::Replace($c, 'APP_VERSION\s*=\s*["'']\d+-\d+["'']', "APP_VERSION = `"$newVer`"")
    Set-Content -NoNewline -Path $VersionFile -Value $c
    if (-not $Quiet) {
        Write-Host "Nova versao: $newVer"
    }
    Write-Output $newVer
} else {
    Write-Error "Padrao de versao nao reconhecido em version.py"
    exit 1
}
