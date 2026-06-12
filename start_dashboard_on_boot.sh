#!/bin/bash
set -euo pipefail

# Start CryptoTrader monitor at boot
if [ -x /home/pi/Desktop/test/start_trader_monitor_on_boot.sh ]; then
  /home/pi/Desktop/test/start_trader_monitor_on_boot.sh
else
  bash /home/pi/Desktop/test/start_trader_monitor_on_boot.sh
fi

PROJECT_ROOT="/home/pi/Desktop/test"
BACKEND_DIR="$PROJECT_ROOT/backend/website_chatbot"
FRONTEND_DIR="$PROJECT_ROOT/frontend/website_chatbot"
LOG_DIR="$PROJECT_ROOT/logs"
BACKEND_LOG="$LOG_DIR/dashboard_backend.log"
FRONTEND_LOG="$LOG_DIR/dashboard_frontend.log"
BOOT_LOG="$LOG_DIR/dashboard_boot.log"

mkdir -p "$LOG_DIR"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting dashboard boot sequence" >> "$BOOT_LOG"

start_backend() {
  if ss -tln 2>/dev/null | grep -q ':5000 '; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backend already running on :5000" >> "$BOOT_LOG"
    return
  fi

  cd "$BACKEND_DIR"
  nohup python3 app.py >> "$BACKEND_LOG" 2>&1 &
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backend started" >> "$BOOT_LOG"
}

start_frontend() {
  if ss -tln 2>/dev/null | grep -q ':3000 '; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Frontend already running on :3000" >> "$BOOT_LOG"
    return
  fi

  # Serve the production build with serve (lightweight, ~10MB RAM vs 190MB webpack dev server).
  # To rebuild after source changes: cd frontend/website_chatbot && npm run build
  nohup serve -s "$FRONTEND_DIR/build" -l 3000 >> "$FRONTEND_LOG" 2>&1 &
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Frontend started (production build via serve)" >> "$BOOT_LOG"
}

open_dashboard_tab() {
  # Attempt browser open only when desktop session is available.
  if command -v xdg-open >/dev/null 2>&1; then
    export DISPLAY=:0
    (nohup xdg-open "http://localhost:3000" >/dev/null 2>&1 &) || true
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Attempted browser open for dashboard" >> "$BOOT_LOG"
  fi
}

start_backend
sleep 5
start_frontend
sleep 8
open_dashboard_tab

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Dashboard boot sequence complete" >> "$BOOT_LOG"
