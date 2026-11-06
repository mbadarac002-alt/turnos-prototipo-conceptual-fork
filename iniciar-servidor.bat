
@echo off
title Servidor Turnos (Ctrl+C para detener)
cd /d "%~dp0"
echo Iniciando API de Turnos en http://localhost:8000 ...
start "" cmd /c "timeout /t 4 /nobreak >nul & start http://localhost:8000/docs"
python -m uvicorn main:app --reload --port 8000
pause
