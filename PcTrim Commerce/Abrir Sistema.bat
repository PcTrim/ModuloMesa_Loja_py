@echo off
setlocal
REM Atalho para abrir o Sistema de Pedidos - Novaloja
REM Este arquivo inicia o servidor Flask no .venv e abre o login no navegador
REM IMPORTANTE: usa sempre a pasta onde este .bat está (não um caminho fixo de outro PC).

set "PROJECT_DIR=%~dp0"
cd /d "%PROJECT_DIR%"

set "PYTHON_EXE=%PROJECT_DIR%\.venv\Scripts\python.exe"
set "APP_FILE=%PROJECT_DIR%\app.py"

if not exist "%PYTHON_EXE%" (
	echo [ERRO] Ambiente virtual nao encontrado em .venv\Scripts\python.exe
	echo Execute primeiro a criacao do ambiente virtual nesta pasta: %PROJECT_DIR%
	pause
	exit /b 1
)

if not exist "%APP_FILE%" (
	echo [ERRO] app.py nao encontrado na pasta do projeto.
	pause
	exit /b 1
)

REM Evita dois Flask na mesma porta (ex.: python global C:\Python313\python.exe app.py noutra pasta = mudancas do Cursor nao aparecem)
echo.
echo [LojaOnline] A libertar porta 2001 se houver servidor antigo duplicado...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":2001" ^| findstr "LISTENING"') do (
	if not "%%a"=="0" (
		echo    Encerrando PID %%a
		taskkill /F /PID %%a >nul 2>&1
	)
)
timeout /t 2 >nul

echo.
echo [LojaOnline] Pasta deste servidor: %PROJECT_DIR%
echo [LojaOnline] Apos subir, abra: http://127.0.0.1:2001/onde-esta-o-servidor
echo [LojaOnline] O texto tem de mostrar o MESMO caminho acima (senao e outra copia do projeto).
echo.

start "Novaloja - Servidor" cmd /k "\"%PYTHON_EXE%\" \"%APP_FILE%\""

timeout /t 3 >nul
start "" http://127.0.0.1:2001/login/form

endlocal
