#!/usr/bin/env bash
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"

# Trap Ctrl+C to kill backend when frontend exits
cleanup() {
  echo ""
  echo "Shutting down..."
  if [ -n "$BACKEND_PID" ]; then
    kill "$BACKEND_PID" 2>/dev/null && echo "Backend stopped."
  fi
  exit 0
}
trap cleanup INT TERM

# 1. Redis
echo "==> Starting Redis..."
docker compose -f "$ROOT/docker-compose.yml" up -d

# 2. Backend
echo "==> Activating venv and starting backend (http://localhost:8001)..."
source "$ROOT/backend/.venv/Scripts/activate"
python -m uvicorn backend.main:app --port 8001 &
BACKEND_PID=$!
echo "    Backend PID: $BACKEND_PID"

# 3. Frontend — launch in a new CMD window (Git Bash can't keep Vite alive)
echo "==> Starting frontend in CMD (http://localhost:5173)..."
FRONTEND_DIR="$(cygpath -w "$ROOT/frontend")"
cmd.exe /c "start cmd.exe /k \"cd /d $FRONTEND_DIR && npm run dev\""
echo "    Frontend launching in a new CMD window."
echo "    Press Ctrl+C here to stop the backend."
# Keep script alive so backend stays running
wait $BACKEND_PID

# If frontend exits cleanly, run cleanup
cleanup
