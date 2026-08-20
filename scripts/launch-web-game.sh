#!/bin/bash
# Launch a web build in Chromium kiosk mode with GPU acceleration.
# Called by EmulationStation via es_systems.cfg.
# Usage: launch-web-game.sh <path-to-game-dir-or-marker>

GAME_PATH="$1"

# Resolve the game directory. If given a ".web" marker file, the game lives in
# a folder of the same name (without the .web extension) next to the marker:
#   web/Dragon Jump.web  ->  web/Dragon Jump/index.html
if [ -f "$GAME_PATH" ]; then
  case "$GAME_PATH" in
    *.web)
      GAME_DIR="${GAME_PATH%.web}"   # strip the .web marker to get the folder
      ;;
    *)
      GAME_DIR="$(dirname "$GAME_PATH")"
      ;;
  esac
else
  GAME_DIR="$GAME_PATH"
fi

INDEX_FILE="$GAME_DIR/index.html"

if [ ! -f "$INDEX_FILE" ]; then
  echo "No index.html found in $GAME_DIR" >&2
  exit 1
fi

# Godot/Unity web builds load their assets (index.pck, .wasm) via fetch()/
# XHR, which the browser blocks under file:// ("failed to fetch"). Serve the
# game over HTTP from a local loopback server instead.
PORT="${WEBGAME_PORT:-8124}"
if command -v python3 >/dev/null 2>&1; then
  python3 -m http.server "${PORT}" --directory "${GAME_DIR}" \
    >/tmp/webgame_server.log 2>&1 &
  SERVER_PID=$!
elif command -v busybox >/dev/null 2>&1; then
  ( cd "${GAME_DIR}" && busybox httpd -f -p "${PORT}" ) \
    >/tmp/webgame_server.log 2>&1 &
  SERVER_PID=$!
else
  echo "ERROR: no python3 or busybox available to serve the web game" >&2
  exit 1
fi

# Give the server a moment to bind before Chromium connects.
sleep 1

# Persistent cache dir so shaders/wasm survive reboots and are shared across games.
CACHE_DIR="/home/tagap/.cache/arcade"
mkdir -p "${CACHE_DIR}"

# Start the exit server (powers the in-game Quit button) if not already running.
if ! pgrep -f "exit-server.py" >/dev/null 2>&1; then
  setsid python3 -u /home/tagap/scripts/exit-server.py >/tmp/exit_server.log 2>&1 </dev/null &
  disown 2>/dev/null || true
fi

# Start the gamepad bridge (D-pad/buttons -> keyboard keys, Start+Select
# force-quit) if not already running. It is normally started by the Openbox
# autostart; this is a fallback so a game still works if it is missing.
if ! pgrep -f "gamepad-bridge.py" >/dev/null 2>&1; then
  setsid python3 -u /home/tagap/scripts/gamepad-bridge.py >/tmp/gamepad_bridge.log 2>&1 </dev/null &
  disown 2>/dev/null || true
fi

# Launch Chromium in kiosk, no bars, no dialogs, GPU accelerated
chromium-browser \
  --no-sandbox \
  --disable-gpu-watchdog \
  --kiosk \
  --start-fullscreen \
  --app="http://127.0.0.1:${PORT}/index.html" \
  --noerrdialogs \
  --disable-infobars \
  --disable-session-crashed-bubble \
  --disable-features=TranslateUI \
  --ozone-platform=x11 \
  --use-angle=gl \
  --enable-gpu-rasterization \
  --ignore-gpu-blocklist \
  --enable-accelerated-2d-canvas \
  --no-first-run \
  --disk-cache-dir=${CACHE_DIR}/chrome_cache \
  --user-data-dir=${CACHE_DIR}/chrome_profile \
  --disable-restore-session-state \
  --disable-background-networking

# When Chromium exits, stop the server and return to EmulationStation.
if [[ -n "${SERVER_PID:-}" ]]; then
  kill "${SERVER_PID}" 2>/dev/null || true
fi

exit 0
