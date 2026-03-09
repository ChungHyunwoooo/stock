#!/bin/bash
# Start TSE backend + frontend
set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== Starting Trading Strategy Engine ==="

# Start FastAPI backend
echo "[1/2] Starting FastAPI backend on :8000..."
cd "$PROJECT_DIR"
.venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8001 &
BACKEND_PID=$!

# Start Next.js frontend
echo "[2/2] Starting Next.js frontend on :3000..."
cd "$PROJECT_DIR/web"
npm run dev -- -p 3000 &
FRONTEND_PID=$!

echo ""
echo "=== TSE Running ==="
echo "  Frontend: http://127.0.0.1:3000/stock"
echo "  Backend:  http://127.0.0.1:8001/api"
echo "  External: http://hwchung.iptime.org/stock"
echo ""
echo "  Backend PID:  $BACKEND_PID"
echo "  Frontend PID: $FRONTEND_PID"
echo ""
echo "Press Ctrl+C to stop all services"

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM
wait
