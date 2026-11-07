# SmartDoc Automated Startup Script for Windows PowerShell
$ErrorActionPreference = "SilentlyContinue"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
if ($projectRoot) { Set-Location $projectRoot }

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "       SmartDoc — Starting Application" -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Check for existing process on port 8000 and free it
$occupied = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | Where-Object { $_.State -eq 'Listen' }
if ($occupied) {
    $pidToKill = $occupied.OwningProcess | Select-Object -Unique
    Write-Host "[INFO] Freeing port 8000 (killing process ID $pidToKill)..." -ForegroundColor Yellow
    Stop-Process -Id $pidToKill -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}

# 2. Launch browser
Start-Process "http://localhost:8000"

# 3. Start Uvicorn server
Write-Host "[INFO] Starting SmartDoc on http://127.0.0.1:8000..." -ForegroundColor Green
Write-Host "[INFO] Press Ctrl+C to stop the server." -ForegroundColor Gray
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000

