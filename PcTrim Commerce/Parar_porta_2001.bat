@echo off
REM Para todos os processos que estao a escutar na porta 2001 (Flask duplicado / Python global).
echo Encerrando o que estiver em LISTENING na porta 2001...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":2001" ^| findstr "LISTENING"') do (
	if not "%%a"=="0" (
		echo   PID %%a
		taskkill /F /PID %%a
	)
)
echo.
echo Pronto. Agora use "Abrir Sistema.bat" ou inicie: .venv\Scripts\python.exe app.py
pause
