@echo off

REM ==========================================================================
REM  Leaps2.0 — LAN mode
REM  Serves the BUILT frontend from the backend on ONE port (8001), bound to
REM  0.0.0.0 so other devices on the same local network (e.g. your phone) can
REM  reach it at  http://<this-PC-LAN-IP>:8001
REM
REM  Access is gated by HTTP Basic Auth — set REVIEW_PASSWORD in backend\.env.
REM  (username = blank/anything, password = REVIEW_PASSWORD)
REM
REM  The normal localhost-only dev flow is still start.bat. Use THIS script
REM  only when you intend to expose the app to the LAN.
REM
REM  One-time firewall setup (run once, as admin), scoped to the local subnet:
REM    netsh advfirewall firewall add rule name="Leaps2.0 LAN" dir=in ^
REM      action=allow protocol=TCP localport=8001 remoteip=LocalSubnet profile=private
REM ==========================================================================

REM Self-elevate to Administrator if not already (needed to free the port)
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo Requesting admin rights...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

echo Starting Leaps2.0 in LAN mode...

REM Kill any process holding port 8001
echo Clearing port 8001...
powershell -NoProfile -Command "try { $p = (Get-NetTCPConnection -LocalPort 8001 -State Listen -EA Stop).OwningProcess; Stop-Process -Id $p -Force; Start-Sleep 1 } catch {}"

REM 1. Redis
docker compose -f "%~dp0docker-compose.yml" up -d

REM 2. Build the frontend so the served app is current
echo Building frontend (this bundles the latest code)...
cd /d "%~dp0frontend"
call npm run build
if %errorLevel% neq 0 (
    echo.
    echo Frontend build FAILED — aborting so a stale app is not served.
    pause
    exit /b 1
)

REM 3. Backend — bound to all interfaces, serving the built SPA at "/"
cd /d "%~dp0"

REM Show the LAN URL(s) to type on the phone
echo.
echo Reach the app from any device on this Wi-Fi at:
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4 Address"') do echo    http://%%a:8001
echo.
echo Login: username = (blank),  password = REVIEW_PASSWORD from backend\.env
echo.

start "Leaps LAN Backend" cmd /k "cd /d %~dp0 && backend\.venv\Scripts\activate && python -m uvicorn backend.main:app --host 0.0.0.0 --port 8001"

echo Backend launching in a new window. Close that window to stop the server.
