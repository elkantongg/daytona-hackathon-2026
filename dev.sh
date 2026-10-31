#!/usr/bin/env bash
# Start the Wayfound backend (port 8010) and dashboard (port 5173) together.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "No .env found. Copy .env.example to .env and fill it in first." >&2
  exit 1
fi

(cd backend && uv sync -q)
(cd frontend && [ -d node_modules ] || npm install --silent)

trap 'kill 0' EXIT
(cd backend && uv run uvicorn app.main:app --port 8010) &
(cd frontend && npm run dev -- --strictPort) &

echo
echo "  Dashboard: http://localhost:5173"
echo "  API:       http://localhost:8010/docs"
echo
wait
