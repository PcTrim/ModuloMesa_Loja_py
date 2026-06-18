@echo off
setlocal
cd /d "%~dp0"

echo Executando diagnostico do Abrir Sistema.vbs...
echo.

cscript //nologo "Abrir Sistema.vbs" > "erro_vbs.txt" 2>&1

echo.
echo Diagnostico salvo em: %cd%\erro_vbs.txt
echo.
notepad "erro_vbs.txt"

endlocal
