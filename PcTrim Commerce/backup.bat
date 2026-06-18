@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "VERMODE=ASK"
if /i "%~1"=="/version"   set "VERMODE=YES"
if /i "%~1"=="/noversion" set "VERMODE=NO"

for /f "usebackq delims=" %%i in (`powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HHmmss"`) do set "TS=%%i"
set "BACKUP_ROOT=%~dp0..\_Backups_LojaOnline"
set "DEST=%BACKUP_ROOT%\LojaOnline_%TS%"

echo ============================================
echo  Backup LojaOnline  -  %TS%
echo  Destino: %DEST%
echo ============================================

if not exist "%BACKUP_ROOT%" mkdir "%BACKUP_ROOT%"
mkdir "%DEST%"

echo.
echo [1/3] Copiando arquivos da aplicacao...
robocopy "%~dp0." "%DEST%\app" /E /R:1 /W:1 /NFL /NDL /NP ^
  /XD ".venv" "venv" "__pycache__" "node_modules" ".git" ".cursor" "_Backups_LojaOnline" ^
  /XF "*.pyc"
if %ERRORLEVEL% GEQ 8 (
  echo   ERRO ao copiar arquivos. Verifique espaco/permissoes.
  goto :fim
)
echo   Arquivos copiados.

echo.
echo [2/3] Backup do banco de dados...
where mysqldump >nul 2>&1
if errorlevel 1 (
  echo   mysqldump nao encontrado - PULANDO backup do banco.
) else (
  set "MYSQL_HOST=" & set "MYSQL_PORT=" & set "MYSQL_USER=" & set "MYSQL_PASSWORD=" & set "MYSQL_DATABASE="
  for /f "usebackq tokens=1,* delims==" %%a in ("%~dp0.env") do (
    if /i "%%a"=="MYSQL_HOST"     set "MYSQL_HOST=%%b"
    if /i "%%a"=="MYSQL_PORT"     set "MYSQL_PORT=%%b"
    if /i "%%a"=="MYSQL_USER"     set "MYSQL_USER=%%b"
    if /i "%%a"=="MYSQL_PASSWORD" set "MYSQL_PASSWORD=%%b"
    if /i "%%a"=="MYSQL_DATABASE" set "MYSQL_DATABASE=%%b"
  )
  echo   Exportando !MYSQL_DATABASE! de !MYSQL_HOST!:!MYSQL_PORT! ...
  mysqldump -h !MYSQL_HOST! -P !MYSQL_PORT! -u !MYSQL_USER! -p!MYSQL_PASSWORD! --single-transaction --routines --events !MYSQL_DATABASE! > "%DEST%\!MYSQL_DATABASE!.sql"
  if errorlevel 1 ( echo   ERRO no mysqldump. ) else ( echo   Banco exportado. )
)

echo.
echo [3/3] Versao da aplicacao...
if "%VERMODE%"=="ASK" (
  set /p BUMP="Incrementar a versao minor (265-0 -^> 265-1)? (S/N): "
  if /i "!BUMP!"=="S" set "VERMODE=YES"
)
if "%VERMODE%"=="YES" (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$p='version.py'; $c=Get-Content -Raw $p; if($c -match 'APP_VERSION = .(\d+)-(\d+).'){ $maj=$matches[1]; $min=[int]$matches[2]+1; $q=[char]34; $new='APP_VERSION = '+$q+$maj+'-'+$min+$q; $c=[regex]::Replace($c,'APP_VERSION = .\d+-\d+.',$new); Set-Content -NoNewline -Path $p -Value $c; Write-Host ('   Nova versao: '+$maj+'-'+$min) } else { Write-Host '   Padrao de versao nao reconhecido - nada alterado' }"
) else (
  echo   Versao nao alterada.
)

:fim
echo.
echo ============================================
echo  Concluido.
echo ============================================
pause
