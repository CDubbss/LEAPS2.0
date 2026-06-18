@echo off

REM Self-elevate to Administrator if not already
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo Requesting admin rights to free port 8001...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

echo Starting Leaps2.0...

REM Kill any process holding port 8001
echo Clearing port 8001...
powershell -NoProfile -Command "try { $p = (Get-NetTCPConnection -LocalPort 8001 -State Listen -EA Stop).OwningProcess; Stop-Process -Id $p -Force; Start-Sleep 1 } catch {}"

REM 1. Redis
docker compose -f "%~dp0docker-compose.yml" up -d

REM 2. Backend
start "Leaps Backend" cmd /k "cd /d %~dp0 && backend\.venv\Scripts\activate && python -m uvicorn backend.main:app --port 8001"

REM 3. Frontend
start "Leaps Frontend" cmd /k "cd /d %~dp0\frontend && npm run dev"

echo.
echo Backend  ^>  http://localhost:8001
echo Frontend ^>  http://localhost:5173
echo.
