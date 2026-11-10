@echo off
setlocal
rem Abre Mouse Compartido como Administrador, para poder controlar tambien
rem las ventanas elevadas (Administrador de tareas, instaladores, etc.).
rem   iniciar.bat           abre la ventana del programa
rem   iniciar.bat menu      abre el menu de texto de la primera version
net session >nul 2>&1
if %errorlevel% neq 0 (
    if "%~1"=="" (
        powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    ) else (
        powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '%*' -Verb RunAs"
    )
    exit /b
)
cd /d "%~dp0"

rem 1. Buscar Python: primero "python", si no el lanzador "py".
set "PY="
python -c "import sys" >nul 2>&1 && set "PY=python"
if not defined PY py -3 -c "import sys" >nul 2>&1 && set "PY=py -3"
if not defined PY (
    echo No encontre Python.
    echo Instalalo con el archivo de la carpeta "instaladores" y tilda "Add python.exe to PATH".
    pause
    exit /b 1
)

rem 2. La primera vez, instalar lo que necesita la ventana: PySide6.
%PY% -c "import PySide6" >nul 2>&1
if %errorlevel% neq 0 (
    echo Instalando la interfaz grafica. Es solo la primera vez y tarda un minuto...
    %PY% -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo No se pudo instalar. Revisa que haya internet y volve a abrir iniciar.bat.
        pause
        exit /b 1
    )
)

rem 3. Abrir. La ventana va con pythonw, que no deja una consola negra abierta.
if "%~1"=="" goto ventana
if /i "%~1"=="--bandeja" goto ventana
%PY% main.py %*
pause
exit /b

:ventana
set "PYW="
for /f "delims=" %%P in ('%PY% -c "import sys, pathlib; p = pathlib.Path(sys.executable); w = p.with_name('pythonw.exe'); print(w if w.exists() else p)"') do set "PYW=%%P"
start "" "%PYW%" main.py %*
exit /b
