@echo off
rem Abre el programa como Administrador, para poder controlar tambien
rem las ventanas elevadas (Administrador de tareas, instaladores, etc.).
net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
cd /d "%~dp0"
where python >nul 2>&1
if %errorlevel% equ 0 (
    python main.py %*
) else (
    py -3 main.py %*
)
pause
