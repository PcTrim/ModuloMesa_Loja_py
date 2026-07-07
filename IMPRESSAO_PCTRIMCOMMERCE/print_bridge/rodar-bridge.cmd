@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Rode iniciar-print-bridge.bat uma vez antes.
  pause
  exit /b 1
)
title LojaOnline - Print Bridge
echo NAO FECHE ESTA JANELA - http://127.0.0.1:9123/health
".venv\Scripts\python.exe" "%~dp0app.py"
pause
