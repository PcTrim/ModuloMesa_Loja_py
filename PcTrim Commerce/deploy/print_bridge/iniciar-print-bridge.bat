@echo off

chcp 65001 >nul

title LojaOnline - Print Bridge

cd /d "%~dp0"



where python >nul 2>&1

if errorlevel 1 (

  where py >nul 2>&1

  if errorlevel 1 (

    echo [ERRO] Python nao encontrado. Instale Python 3 com "Add to PATH".

    pause

    exit /b 1

  )

  set "PY_BOOT=py -3"

) else (

  set "PY_BOOT=python"

)



set "PY=%~dp0.venv\Scripts\python.exe"

set "VENV_OK=0"

if exist "%PY%" (

  "%PY%" -c "import sys" >nul 2>&1

  if not errorlevel 1 set "VENV_OK=1"

)



if "%VENV_OK%"=="0" (

  if exist "%~dp0.venv" (

    echo [AVISO] .venv invalido — recriando...

    rmdir /s /q "%~dp0.venv" 2>nul

  ) else (

    echo Criando ambiente virtual...

  )

  %PY_BOOT% -m venv "%~dp0.venv"

  if errorlevel 1 (

    echo [ERRO] Falha ao criar .venv

    pause

    exit /b 1

  )

  set "PY=%~dp0.venv\Scripts\python.exe"

)



echo Instalando dependencias...

"%PY%" -m pip install -q --upgrade pip

"%PY%" -m pip install -q -r "%~dp0requirements.txt"

if errorlevel 1 (

  echo [ERRO] Falha no pip install. Apague .venv e tente de novo.

  pause

  exit /b 1

)



echo.

echo ========================================

echo   Print Bridge — impressora vem do SITE

echo   (MySQL: impressoras / comanda_delivery)

echo ========================================

echo   NAO FECHE ESTA JANELA

echo   Teste: http://127.0.0.1:9123/health

echo ========================================

echo.



"%PY%" "%~dp0app.py"

echo.

echo [Encerrado ou erro acima]

pause

