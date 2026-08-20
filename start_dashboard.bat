@echo off
cd /d "%~dp0"
echo ===================================================
echo   Starting AI Stock V3.7 Dashboard (Frontend Only)
echo   Frontend: Port 5173
echo   Requires backend already running on Port 8080
echo ===================================================
start "AI Stock Frontend" cmd /k "cd /d "%~dp0frontend" && npm run dev"
