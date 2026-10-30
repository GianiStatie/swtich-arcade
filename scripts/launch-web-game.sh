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
#
# webgame-server.py sends no-store cache headers; plain `http.server` does not,
# and Chromium's heuristic caching then serves stale pck/wasm after updates.
#
# Each game gets its own origin (port), not just its own directory. Godot's
# PWA service worker is registered at the origin root and caches generic names
# (index.html/index.js/index.wasm/index.pck). On a shared port, one game's
# service worker serves its cached files to the next game, so the JS glue and
# the wasm/pck come from different builds (e.g. LinkError: import "env"
# "memory" must be a WebAssembly.Memory object). A stable per-game port keeps
# each service worker and CacheStorage isolated inside the shared profile.
if [[ -n "${WEBGAME_PORT:-}" ]]; then
  PORT="${WEBGAME_PORT}"
else
  GAME_NAME="$(basename "${GAME_DIR%/}")"
  GAME_HASH="$(printf '%s' "${GAME_NAME}" | cksum | awk '{print $1}')"
  PORT=$(( 8200 + GAME_HASH % 500 ))
fi
if [[ -x "${GAME_DIR%/*}/../scripts/webgame-server.py" ]]; then
  SERVER_SCRIPT="${GAME_DIR%/*}/../scripts/webgame-server.py"
elif [[ -x "/home/tagap/scripts/webgame-server.py" ]]; then
  SERVER_SCRIPT="/home/tagap/scripts/webgame-server.py"
fi

# Reap any stale server still holding the port (e.g. one left over from a
# crashed or manual launch). Without this the new server cannot bind, and the
# kiosk would then be answered by the stale one — showing the wrong game (or
# a leftover test page) on every launch.
pkill -f "webgame-server.py ${PORT}" 2>/dev/null || true
pkill -f "http.server ${PORT} " 2>/dev/null || true
pkill -f "busybox httpd -f -p ${PORT}" 2>/dev/null || true
sleep 0.5

if [[ -n "${SERVER_SCRIPT:-}" ]]; then
  python3 "${SERVER_SCRIPT}" "${PORT}" "${GAME_DIR}" \
    >/tmp/webgame_server.log 2>&1 &
  SERVER_PID=$!
elif command -v python3 >/dev/null 2>&1; then
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

# If the server died (e.g. the port was still busy), fail visibly instead of
# letting Chromium connect to whatever else owns the port.
if ! kill -0 "${SERVER_PID}" 2>/dev/null; then
  echo "ERROR: web game server failed to start (see /tmp/webgame_server.log)" >&2
  exit 1
fi

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
