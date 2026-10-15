#!/usr/bin/env bash
# Arcade contract simulator entrypoint.
#
#   entrypoint.sh interactive   -> Xvfb + noVNC + Chromium kiosk (play one build)
#   entrypoint.sh check         -> headless contract checks, exits non-zero on failure
#   entrypoint.sh library       -> EmulationStation stand-in: menu of all synced
#                                  games; each launches at root on :8124
#   entrypoint.sh sync          -> pull the whole itch collection into /games
#   entrypoint.sh list          -> print installed game titles, one per line
#
# Reuses the arcade's real servers (webgame-server.py, exit-server.py,
# itch-watcher.py) so the HTTP contract — COOP/COEP, MIME types, cache headers,
# sidecars — matches the cabinet exactly.
set -euo pipefail

MODE="${1:-interactive}"
GAME_DIR="${GAME_DIR:-/game}"
GAMES_ROOT="${GAMES_ROOT:-/games}"
WEBGAME_PORT="${WEBGAME_PORT:-8124}"
MENU_PORT="${MENU_PORT:-8125}"
CACHE_DIR="${CACHE_DIR:-/cache}"
DISPLAY_NUM="${DISPLAY_NUM:-:99}"

# Kiosk framebuffer size (WxH). Smaller = far cheaper for SwiftShader and the
# VNC stream. Set via -e ARCADE_KIOSK_RES=640x360 (the default; --strict uses
# 1280x720).
KIOSK_RES="${ARCADE_KIOSK_RES:-1280x720}"
KIOSK_W="${KIOSK_RES%x*}"
KIOSK_H="${KIOSK_RES#*x}"
[[ "$KIOSK_W" =~ ^[0-9]+$ && "$KIOSK_H" =~ ^[0-9]+$ ]] || { KIOSK_W=1280; KIOSK_H=720; }

# Software renderer for the kiosk. Default llvmpipe (Mesa) — measurably faster
# than SwiftShader for 3D (~2x), which is what makes 3D games usable here. Set
# ARCADE_RENDERER=swiftshader to fall back. (Check mode always uses SwiftShader.)
RENDERER="${ARCADE_RENDERER:-llvmpipe}"
if [[ "$RENDERER" == "swiftshader" ]]; then
  GL_ARGS=(--use-gl=angle --use-angle=swiftshader --enable-unsafe-swiftshader)
else
  export LIBGL_ALWAYS_SOFTWARE=1
  GL_ARGS=(--use-gl=angle --use-angle=gl)
fi

mkdir -p "$CACHE_DIR/chrome_cache" "$CACHE_DIR/chrome_profile"

# exit-server.py invokes this hardcoded path when a game quits.
install -d /home/tagap/scripts
install -m 0755 /opt/arcade/exit-to-es.sh /home/tagap/scripts/exit-to-es.sh

# itch-watcher.py reads the API key from a file; allow -e ITCH_API_KEY to feed it.
if [[ -n "${ITCH_API_KEY:-}" ]]; then
  install -d "$HOME/.config"
  printf '%s' "$ITCH_API_KEY" > "$HOME/.config/itch_api_key"
  chmod 600 "$HOME/.config/itch_api_key"
fi

PIDS=()
cleanup() {
  for p in ${PIDS[@]+"${PIDS[@]}"}; do
    kill "$p" 2>/dev/null || true
  done
}
trap cleanup EXIT

wait_for_port() {
  for _ in $(seq 1 100); do
    if (exec 3<>/dev/tcp/127.0.0.1/"$1") 2>/dev/null; then
      exec 3>&- && return 0
    fi
    sleep 0.1
  done
  return 1
}

# Kiosk flags ported from scripts/launch-web-game.sh, plus the constraint
# profile: SwiftShader is forced on every host so all contributors get the same
# (pessimistic) GPU bound instead of a host-GPU-dependent result.
CHROMIUM_ARGS=(
  --no-sandbox
  --disable-gpu-watchdog
  --enable-gpu-rasterization
  --ignore-gpu-blocklist
  --enable-accelerated-2d-canvas
  --no-first-run
  --noerrdialogs
  --disable-infobars
  --disable-session-crashed-bubble
  --disable-features=TranslateUI
  --disable-restore-session-state
  --disable-background-networking
  "${GL_ARGS[@]}"
  --disk-cache-dir="${CACHE_DIR}/chrome_cache"
  --user-data-dir="${CACHE_DIR}/chrome_profile"
  --window-size="${KIOSK_W},${KIOSK_H}"
)

start_display() {
  Xvfb "$DISPLAY_NUM" -screen 0 "${KIOSK_W}x${KIOSK_H}x24" -nolisten tcp >/tmp/xvfb.log 2>&1 &
  PIDS+=("$!")
  export DISPLAY="$DISPLAY_NUM"
  sleep 1
  # x11vnc flags tuned for responsiveness (this is a live game view, not a
  # desktop): threads, no Xdamage, no client-side cache, low poll latency.
  x11vnc -display "$DISPLAY_NUM" -forever -shared -nopw -rfbport 5900 -quiet \
    -threads -noxdamage -ncache 0 -wait 5 -defer 5 >/tmp/x11vnc.log 2>&1 &
  PIDS+=("$!")
  websockify --web=/usr/share/novnc 6080 localhost:5900 \
    >/tmp/websockify.log 2>&1 &
  PIDS+=("$!")
  echo "=============================================================="
  echo " Open in your browser:  http://localhost:6080/"
  echo "   (tuned noVNC landing page; auto-connects)"
  echo "=============================================================="
}

case "$MODE" in
  sync)
    SRC_CFG=/opt/arcade/itch-games.yaml
    if [[ -f "$GAMES_ROOT/itch-games.yaml" ]]; then
      SRC_CFG="$GAMES_ROOT/itch-games.yaml"
    fi
    mkdir -p "$GAMES_ROOT"
    # Force restart_es:false (there is no EmulationStation in the container) and
    # keep any per-game overrides from the source config.
    python3 - "$SRC_CFG" /tmp/itch-games.yaml <<'PY'
import sys, yaml
src, dst = sys.argv[1], sys.argv[2]
with open(src) as f:
    data = yaml.safe_load(f) or {}
data["restart_es"] = False
with open(dst, "w") as f:
    yaml.safe_dump(data, f)
PY
    export GAMES_ROOT CONFIG_PATH=/tmp/itch-games.yaml
    exec python3 -u /opt/arcade/itch-watcher.py --once --force
    ;;

  list)
    GAMES_ROOT="$GAMES_ROOT" python3 - <<'PY'
import os
web = os.path.join(os.environ.get("GAMES_ROOT", "/games"), "web")
try:
    names = sorted(os.listdir(web), key=str.casefold)
except FileNotFoundError:
    names = []
for n in names:
    if os.path.isfile(os.path.join(web, n, "index.html")):
        print(n)
PY
    ;;

  check)
    if [[ ! -f "$GAME_DIR/index.html" ]]; then
      echo "ERROR: index.html not found at the root of $GAME_DIR" >&2
      exit 1
    fi
    python3 /opt/arcade/webgame-server.py "$WEBGAME_PORT" "$GAME_DIR" \
      >/tmp/webgame_server.log 2>&1 &
    PIDS+=("$!")
    wait_for_port "$WEBGAME_PORT" || { echo "webgame server did not bind" >&2; exit 1; }
    # DISPLAY must be unset so ANGLE uses headless SwiftShader instead of trying
    # to reach an X server (Vulkan-XCB path).
    unset DISPLAY
    exec node /opt/arcade/check.mjs "http://127.0.0.1:${WEBGAME_PORT}/index.html"
    ;;

  interactive)
    if [[ ! -f "$GAME_DIR/index.html" ]]; then
      echo "ERROR: index.html not found at the root of $GAME_DIR" >&2
      exit 1
    fi
    python3 /opt/arcade/webgame-server.py "$WEBGAME_PORT" "$GAME_DIR" \
      >/tmp/webgame_server.log 2>&1 &
    PIDS+=("$!")
    python3 -u /opt/arcade/exit-server.py >/tmp/exit_server.log 2>&1 &
    PIDS+=("$!")
    wait_for_port "$WEBGAME_PORT" || { echo "webgame server did not bind" >&2; exit 1; }

    start_display
    echo " Arcade contract simulator (interactive)"
    echo "   Play with the keyboard: arrows / Space(A) / R(B) / Esc(X) / Tab(Y)"
    echo "   Exit: the game's quit button, or Ctrl-C here."
    echo "=============================================================="

    chromium "${CHROMIUM_ARGS[@]}" \
      --kiosk --start-fullscreen \
      --app="http://127.0.0.1:${WEBGAME_PORT}/index.html" &
    CHROME_PID=$!
    PIDS+=("$CHROME_PID")
    wait "$CHROME_PID" || true
    ;;

  library)
    # Arcade API on :8123 (list + launch + /exit) + the in-container visual
    # menu on :8125, then a supervisor that keeps Chromium pointing at the
    # menu. Games call :8123/exit to quit; exit-to-es.sh kills Chromium and we
    # reopen the menu. The per-game server binds 0.0.0.0 so published ports
    # (for a host browser) can reach it.
    export WEBGAME_BIND="${WEBGAME_BIND:-0.0.0.0}"
    GAMES_ROOT="$GAMES_ROOT" WEBGAME_PORT="$WEBGAME_PORT" \
      API_HOST="${API_HOST:-0.0.0.0}" API_PORT="${API_PORT:-8123}" \
      python3 -u /opt/arcade/api-server.py >/tmp/api_server.log 2>&1 &
    PIDS+=("$!")
    GAMES_ROOT="$GAMES_ROOT" MENU_PORT="$MENU_PORT" WEBGAME_PORT="$WEBGAME_PORT" \
      python3 -u /opt/arcade/menu-server.py >/tmp/menu_server.log 2>&1 &
    PIDS+=("$!")

    start_display
    echo " Arcade contract simulator (library)"
    echo "   Menu -> game -> Quit returns to the menu."
    echo "   API (open from the host): http://127.0.0.1:${API_PORT:-8123}/"
    echo "   Games: $(GAMES_ROOT)/web   (host: docker/run.sh --list)"
    echo "=============================================================="

    STOP=0
    trap 'STOP=1' TERM INT
    while [[ "$STOP" -eq 0 ]]; do
      chromium "${CHROMIUM_ARGS[@]}" \
        --kiosk --start-fullscreen \
        --app="http://127.0.0.1:${MENU_PORT}/" &
      CHROME_PID=$!
      PIDS+=("$CHROME_PID")
      wait "$CHROME_PID" || true
      # Chromium exited (game Quit): reopen the menu.
      if [[ "$STOP" -eq 1 ]]; then
        break
      fi
      sleep 1
    done
    ;;

  *)
    echo "unknown mode: $MODE" >&2
    exit 2
    ;;
esac
