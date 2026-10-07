#!/bin/bash
# NOVA Bot + CardCheckout API — both processes
set -u

CHECKER_THREADS=${CHECKER_THREADS:-200}
CHECKER_RETRIES=${CHECKER_RETRIES:-1}
API_PORT=${API_PORT:-8000}

export CHECKER_THREADS
export CHECKER_RETRIES

echo "==> Booting CardCheckout API on :${API_PORT}"
python3 -u -m uvicorn api_server:app \
  --host 0.0.0.0 \
  --port "${API_PORT}" \
  --workers 1 \
  --timeout-keep-alive 60 \
  --log-level warning &

API_PID=$!

# If the API dies, kill the container so Railway restarts cleanly
( while kill -0 "$API_PID" 2>/dev/null; do sleep 5; done; \
  echo "==> API process died — killing container"; kill 1 ) &

echo "==> Booting NOVA bot (foreground)"
exec python3 -u bot.py
