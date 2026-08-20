@echo off
title AI Stock Trading Bot

if not exist "E:\Ai Stock\backend\logs" mkdir "E:\Ai Stock\backend\logs"

:start
echo [%date% %time%] Starting AI Stock Trading Bot...
cd /d "E:\Ai Stock\backend"

REM Kill any lingering uvicorn processes from a previous run
taskkill /F /IM python.exe /T >NUL 2>&1
timeout /t 2 /nobreak >NUL

REM Run server — server.py has RotatingFileHandler writing to logs\server.log internally.
REM No Tee-Object needed (and Tee-Object caused "file in use" lock conflicts on restart).
REM IV&V C1: bind to loopback only so the API is not exposed on the LAN/internet.
REM To reach it from another device, use an SSH tunnel or set the host explicitly.
python -m uvicorn api.server:app --host 127.0.0.1 --port 8080

echo [%date% %time%] Server stopped. Restarting in 10 seconds...
timeout /t 10
goto :start
