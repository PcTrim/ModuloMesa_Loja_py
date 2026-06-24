# Deploy completo: pack local + scp + backup + update no servidor Hostinger
# Pre-requisito: copie deploy.local.env.example para deploy.local.env e preencha SSH.
#
# Uso: powershell -ExecutionPolicy Bypass -File deploy\deploy_update.ps1

$ErrorActionPreference = "Stop"
$DeployDir = $PSScriptRoot
$AppRoot = Split-Path -Parent $DeployDir
$EnvFile = Join-Path $DeployDir "deploy.local.env"

function Load-DeployEnv {
    if (-not (Test-Path $EnvFile)) {
        Write-Host "ERRO: Crie deploy\deploy.local.env a partir de deploy.local.env.example"
        Write-Host "      Preencha DEPLOY_SSH_HOST, DEPLOY_SSH_USER, DEPLOY_REMOTE_PATH"
        exit 1
    }
    Get-Content $EnvFile | ForEach-Object {
        if ($_ -match '^\s*#' -or $_ -match '^\s*$') { return }
        if ($_ -match '^([^=]+)=(.*)$') {
            Set-Variable -Name $Matches[1].Trim() -Value $Matches[2].Trim() -Scope Script
        }
    }
    if (-not $DEPLOY_SSH_HOST -or -not $DEPLOY_SSH_USER -or -not $DEPLOY_REMOTE_PATH) {
        Write-Host "ERRO: deploy.local.env incompleto (HOST, USER, REMOTE_PATH)"
        exit 1
    }
    if (-not $DEPLOY_SSH_PORT) { $script:DEPLOY_SSH_PORT = "22" }
}

Load-DeployEnv

Write-Host "==> Fase 0: Empacotar arquivos locais"
& powershell -ExecutionPolicy Bypass -File (Join-Path $DeployDir "pack_for_upload.ps1")

$Dist = Join-Path $DeployDir "dist"
$Zip = Get-ChildItem -Path $Dist -Filter "LojaOnline_upload_*.zip" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $Zip) {
    Write-Host "ERRO: ZIP nao encontrado em deploy\dist"
    exit 1
}

$SshTarget = "${DEPLOY_SSH_USER}@${DEPLOY_SSH_HOST}"
$SshOpts = @("-p", $DEPLOY_SSH_PORT, "-o", "BatchMode=yes", "-o", "ConnectTimeout=15")

Write-Host "==> Fase 1: Backup no servidor ($SshTarget)"
$BackupCmd = "cd '$DEPLOY_REMOTE_PATH' && sudo bash deploy/backup_production.sh"
ssh @SshOpts $SshTarget $BackupCmd
if ($LASTEXITCODE -ne 0) {
    Write-Host "AVISO: backup falhou ou script ainda nao existe no servidor. Continuando apos primeiro upload parcial..."
}

Write-Host "==> Fase 2: Upload (rsync via scp do pacote + extracao)"
$RemoteZip = "/tmp/LojaOnline_upload.zip"
scp @SshOpts $Zip.FullName "${SshTarget}:${RemoteZip}"

$ExtractCmd = @"
set -e
cd '$DEPLOY_REMOTE_PATH'
unzip -o '$RemoteZip' -d '$DEPLOY_REMOTE_PATH'
rm -f '$RemoteZip'
echo 'Upload extraido em $DEPLOY_REMOTE_PATH'
"@
ssh @SshOpts $SshTarget $ExtractCmd

Write-Host "==> Fase 3-4: Update + restart no servidor"
$UpdateCmd = "cd '$DEPLOY_REMOTE_PATH' && bash deploy/update_production.sh"
ssh @SshOpts $SshTarget $UpdateCmd

Write-Host "==> Deploy concluido."
if ($DEPLOY_PUBLIC_URL) {
    Write-Host "    Valide: $DEPLOY_PUBLIC_URL"
} else {
    Write-Host "    Valide a URL publica da LojaOnline no navegador."
}
