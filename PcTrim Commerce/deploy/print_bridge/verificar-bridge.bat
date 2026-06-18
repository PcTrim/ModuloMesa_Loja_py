@echo off

chcp 65001 >nul

title Verificar Print Bridge

cd /d "%~dp0"

echo.

echo === Verificacao Print Bridge (este PC) ===

echo.



where python >nul 2>&1

if errorlevel 1 (

  where py >nul 2>&1

  if errorlevel 1 (

    echo [X] Python NAO instalado ou sem PATH

    echo     Instale: https://www.python.org  marque Add to PATH

    goto fim

  )

  echo [OK] py -3 encontrado

) else (

  echo [OK] python encontrado

)



if exist "%~dp0.venv\Scripts\python.exe" (

  "%~dp0.venv\Scripts\python.exe" -c "import sys" >nul 2>&1

  if errorlevel 1 (

    echo [X] .venv invalido — apague a pasta .venv e rode iniciar-print-bridge.bat

  ) else (

    echo [OK] .venv existe

  )

) else (

  echo [!] .venv ainda nao criado — rode iniciar-print-bridge.bat uma vez

)



echo.

echo Testando http://127.0.0.1:9123/health ...

powershell -NoProfile -Command "try { $r=Invoke-WebRequest -Uri 'http://127.0.0.1:9123/health' -UseBasicParsing -TimeoutSec 3; if ($r.Content -match '\"ok\"') { exit 0 } else { exit 2 } } catch { exit 1 }"

if errorlevel 1 (

  echo [X] Bridge NAO responde — abra iniciar-print-bridge.bat e deixe a janela ABERTA

) else (

  echo [OK] Bridge rodando neste PC

)



:fim

echo.

pause


