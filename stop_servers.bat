@echo off
title Stop AI Stock Background Servers
echo ===================================================
echo   Stopping AI Stock Background Servers safely...
echo ===================================================

:: Stop backend on port 8080
echo Checking port 8080 (Backend)...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8080 ^| findstr LISTENING 2^>nul') do (
    echo [OK] Stopping Backend process with PID %%a...
    taskkill /F /PID %%a
)

:: Stop frontend on port 5173
echo Checking port 5173 (Frontend)...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :5173 ^| findstr LISTENING 2^>nul') do (
    echo [OK] Stopping Frontend process with PID %%a...
    taskkill /F /PID %%a
)

echo.
echo AI Stock servers stopped.
timeout /t 3
