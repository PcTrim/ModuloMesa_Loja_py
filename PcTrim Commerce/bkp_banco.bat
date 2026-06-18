@echo off
setlocal

REM === CONFIGURAÇÕES ===
set MYSQL_USER=seu_usuario
set MYSQL_PASS=sua_senha
set MYSQL_DB=nome_do_banco
set BKP_DIR=%~dp0bkp
set BKP_FILE=%BKP_DIR%\%MYSQL_DB%_bkp_%DATE:~6,4%-%DATE:~3,2%-%DATE:~0,2%_%TIME:~0,2%%TIME:~3,2%%TIME:~6,2%.sql

REM === CRIA PASTA DE BACKUP SE NÃO EXISTIR ===
if not exist %BKP_DIR% mkdir %BKP_DIR%

REM === EXECUTA O BACKUP ===
"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqldump.exe" -u%MYSQL_USER% -p%MYSQL_PASS% --databases %MYSQL_DB% --routines --events --triggers --single-transaction > "%BKP_FILE%"

echo Backup gerado: %BKP_FILE%
pause
