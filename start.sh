#!/bin/bash
export CHECKER_THREADS="${CHECKER_THREADS:-200}"
export CHECK_TIMEOUT="${CHECK_TIMEOUT:-90}"
export PRICE_FLOOR="${PRICE_FLOOR:-0.10}"
export PRICE_CEIL="${PRICE_CEIL:-7.00}"
export MONGO_URL="${MONGO_URL:-mongodb://localhost:27017}"
export DB_NAME="${DB_NAME:-nova_bot}"
exec python3 -u bot.py
