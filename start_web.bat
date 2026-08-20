@echo off
cd /d "%~dp0"
echo ===================================================
echo   Starting AI Stock V3.7 (US + India Dual Market Engine)
echo   Backend: Port 8080  ^|  Frontend: Port 5173
echo ===================================================

echo [1/2] Starting Backend Engine (Port 8080, auto-restart + log capture)...
start "AI Stock Backend" cmd /c "call "%~dp0start_trading_bot.bat""

echo Waiting for backend to initialize...
timeout /t 5 /nobreak > NUL

echo [2/2] Starting Web Dashboard (Port 5173)...
start "AI Stock Frontend" cmd /k "cd /d "%~dp0frontend" && npm run dev"

echo.
echo ===================================================
echo   All services started.
echo   Backend:  http://localhost:8080
echo   Frontend: http://localhost:5173
echo   Logs:     backend\logs\server.log
echo.
echo   Run start_log_monitor.bat to watch for errors.
echo ===================================================
