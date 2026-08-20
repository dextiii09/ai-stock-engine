@echo off
cd /d "%~dp0"
echo ===================================================
echo   Starting AI Stock V3.7 Backend (US + India Dual Engine)
echo   [DB_ENABLED=true] SQLite WAL mode + auto-restart
echo   Logs: backend\logs\server.log
echo ===================================================
start "AI Stock Backend" cmd /c "call "%~dp0start_trading_bot.bat""
echo.
echo Backend starting on Port 8080...
echo Run start_log_monitor.bat in a separate window to monitor errors.
