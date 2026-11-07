@echo off
setlocal
cd /d "%~dp0"
echo ========================================================
echo        SmartDoc — Starting Application
echo ========================================================
echo.

:: 1. Check if port 8000 is occupied, and free it
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8000 ^| findstr LISTENING') do (
    echo [INFO] Port 8000 is occupied by process ID %%a. Freeing port...
    taskkill /F /PID %%a >nul 2>&1
)

:: 2. Launch browser and start Uvicorn
echo [INFO] Starting SmartDoc server at http://localhost:8000 ...
echo [INFO] Press Ctrl+C in this window to stop the server.
echo.

start "" http://localhost:8000
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
pause

