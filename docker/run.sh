#!/usr/bin/env bash
# Arcade contract simulator — build & run wrapper.
#
#   ./run.sh <build-dir>             interactive: play one build in a browser
#   ./run.sh --check <build-dir>     headless contract checks (CI-friendly)
#   ./run.sh --library [--sync]      menu of every synced game (ES stand-in)
#   ./run.sh --sync                  pull the whole itch collection into /games
#   ./run.sh --list                  print installed game titles
#
# Hardware constraints are applied by default (see docker/docs/FIDELITY.md):
#   maxed by default (8 cores / 8g / 640x360, software GL); --strict for the
#   cabinet figure (4 cores / 4g / 1280x720).
#
# Sync/library need an itch.io API key (env ITCH_API_KEY, or
# ~/.config/itch_api_key mounted read-only) and network access.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
IMAGE="${ARCADE_IMAGE:-arcade-contract-sim}"
CACHE_VOLUME="${ARCADE_CACHE_VOLUME:-arcade-contract-sim-cache}"
GAMES_VOLUME="${ARCADE_GAMES_VOLUME:-arcade-contract-sim-games}"

MODE=""
GAME_DIR=""
WANT_SYNC=0
PROFILE="max"

usage() {
  cat <<EOF
Usage: $(basename "$0") [options] [build-directory]

Modes (default: interactive with <build-directory>):
  <build-directory>    interactive: play this build (needs index.html at root)
  --check              headless contract checks; exits non-zero on failure
  --library            menu of every synced game (EmulationStation stand-in)
  --sync               pull the whole itch.io collection into the games volume
  --list               print installed game titles, one per line
  -h, --help           show this help

Options:
  --sync               with --library: sync before starting the menu
  --max                use the container's ceiling (DEFAULT): more CPU/RAM +
                       640x360 kiosk, so 3D games run ~30 fps
  --strict             restore the cabinet-faithful profile instead
                       (4 cores / 4g / 1280x720)

Env (each overrides the profile default):
  ARCADE_IMAGE         image tag (default: arcade-contract-sim)
  ARCADE_CACHE_VOLUME  volume for the browser cache
  ARCADE_GAMES_VOLUME  volume for the synced game library
  ITCH_API_KEY         itch.io API key (or mount ~/.config/itch_api_key)
  ARCADE_CPU_QUOTA     CPU time limit, microseconds per period (max 800000 ~ 8 cores; strict 400000 ~ 4)
  ARCADE_CPU_PERIOD    quota period in microseconds (default 100000)
  ARCADE_MEMORY        container RAM limit (max 8g; strict 4g)
  ARCADE_KIOSK_RES     kiosk framebuffer size WxH (max 640x360; strict 1280x720)
  ARCADE_RENDERER      kiosk software GL: llvmpipe (default, faster) | swiftshader

Note: the container can never exceed the Docker VM's resources (colima/Docker
Desktop). Raise those first for real headroom (see docker/docs/FIDELITY.md).

No bash (e.g. Windows)? Use docker/compose.yaml instead — see docker/README.md.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --check) MODE="check"; shift ;;
    --library) MODE="library"; shift ;;
    --list) MODE="list"; shift ;;
    --sync) WANT_SYNC=1; shift ;;
    --max) PROFILE="max"; shift ;;
    --strict|--cabinet) PROFILE="strict"; shift ;;
    -h|--help) usage; exit 0 ;;
    -*) echo "unknown option: $1" >&2; usage; exit 2 ;;
    *) GAME_DIR="$1"; shift ;;
  esac
done

# Profile defaults (max is the default way we run it). Env vars override these.
if [[ "$PROFILE" == "strict" ]]; then
  DEF_QUOTA=400000; DEF_MEM=4g; DEF_RES=1280x720
else
  DEF_QUOTA=800000; DEF_MEM=8g; DEF_RES=640x360
fi

if [[ -z "$MODE" ]]; then
  if (( WANT_SYNC )); then
    MODE="sync"
  elif [[ -n "$GAME_DIR" ]]; then
    MODE="interactive"
  else
    usage
    exit 2
  fi
fi

if ! docker info >/dev/null 2>&1; then
  echo "ERROR: the Docker daemon is not reachable." >&2
  exit 1
fi

ensure_image() {
  if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "Building image '$IMAGE' (first run only; context = repo root)..."
    docker build -f "${SCRIPT_DIR}/Dockerfile" -t "$IMAGE" "$REPO_ROOT"
  fi
}

# itch.io API key: env var first, else a mounted key file.
KEY_ARGS=()
if [[ -n "${ITCH_API_KEY:-}" ]]; then
  KEY_ARGS+=(-e ITCH_API_KEY)
elif [[ -f "$HOME/.config/itch_api_key" ]]; then
  KEY_ARGS+=(-v "$HOME/.config/itch_api_key:/root/.config/itch_api_key:ro")
fi

# Kiosk software renderer override (entrypoint defaults to llvmpipe).
RENDERER_ARGS=()
if [[ -n "${ARCADE_RENDERER:-}" ]]; then
  RENDERER_ARGS+=(-e ARCADE_RENDERER)
fi

run_sync() {
  echo "Syncing the itch collection into volume '$GAMES_VOLUME'..."
  if [[ ${#KEY_ARGS[@]} -eq 0 ]]; then
    echo "ERROR: no itch.io API key. Set ITCH_API_KEY, or write one to ~/.config/itch_api_key." >&2
    return 1
  fi
  docker run --rm \
    "${CONSTRAINTS[@]}" \
    ${KEY_ARGS[@]+"${KEY_ARGS[@]}"} \
    -v "${GAMES_VOLUME}:/games" \
    "$IMAGE" sync || return 1
  local n
  n="$(game_list | wc -l | tr -d ' ')"
  if [[ "$n" == "0" ]]; then
    echo "WARNING: no games were installed (check the API key, network, and collection id)." >&2
    return 1
  fi
}

game_list() {
  docker run --rm -v "${GAMES_VOLUME}:/games" "$IMAGE" list
}

ensure_image

# CPU limit as a cgroup quota (microseconds of CPU time per period). Defaults
# come from the profile (max unless --strict): see DEF_QUOTA/DEF_MEM/DEF_RES.
CPU_QUOTA="${ARCADE_CPU_QUOTA:-$DEF_QUOTA}"
CPU_PERIOD="${ARCADE_CPU_PERIOD:-100000}"
CPU_CORES="$(awk "BEGIN{c=$CPU_QUOTA/$CPU_PERIOD; if (c==int(c)) printf \"%d\", c; else printf \"%.2f\", c}" 2>/dev/null || echo "?")"
MEMORY="${ARCADE_MEMORY:-$DEF_MEM}"
KIOSK_RES="${ARCADE_KIOSK_RES:-$DEF_RES}"

CONSTRAINTS=( --memory="$MEMORY" --memory-swap="$MEMORY" \
  --cpu-quota="$CPU_QUOTA" --cpu-period="$CPU_PERIOD" )

case "$MODE" in
  check)
    if [[ -z "$GAME_DIR" || ! -f "$GAME_DIR/index.html" ]]; then
      echo "ERROR: --check needs a build directory containing index.html at its root" >&2
      exit 1
    fi
    GAME_DIR="$(cd "$GAME_DIR" && pwd)"
    echo "Running contract checks (constrained: ${MEMORY} RAM, ${CPU_CORES} CPU, offline, SwiftShader)..."
    docker run --rm \
      "${CONSTRAINTS[@]}" \
      --network=none \
      -v "${GAME_DIR}:/game:ro" \
      -v "${CACHE_VOLUME}:/cache" \
      "$IMAGE" check
    ;;

  interactive)
    if [[ -z "$GAME_DIR" || ! -f "$GAME_DIR/index.html" ]]; then
      echo "ERROR: needs a build directory containing index.html at its root" >&2
      exit 1
    fi
    GAME_DIR="$(cd "$GAME_DIR" && pwd)"
    echo "Starting interactive session (constrained: ${MEMORY} RAM, ${CPU_CORES} CPU, SwiftShader, ${KIOSK_RES})..."
    echo "Open http://localhost:6080/ in your browser."
    docker run --rm -it \
      "${CONSTRAINTS[@]}" \
      -e ARCADE_KIOSK_RES="$KIOSK_RES" \
      ${RENDERER_ARGS[@]+"${RENDERER_ARGS[@]}"} \
      -p 6080:6080 \
      -v "${GAME_DIR}:/game:ro" \
      -v "${CACHE_VOLUME}:/cache" \
      "$IMAGE" interactive
    ;;

  sync)
    run_sync || exit 1
    echo "Done. Installed games:"
    game_list | sed 's/^/  - /'
    ;;

  list)
    game_list
    ;;

  library)
    if (( WANT_SYNC )); then
      run_sync
    elif [[ -z "$(game_list)" ]]; then
      echo "Library is empty; syncing first (needs an itch.io API key)..."
      run_sync || echo "WARNING: sync failed; starting with an empty library." >&2
    fi
    echo "Starting library (constrained: ${MEMORY} RAM, ${CPU_CORES} CPU, SwiftShader, ${KIOSK_RES})..."
    echo "  noVNC kiosk (constrained):  http://localhost:6080/"
    echo "  Arcade API (host, fast):    http://127.0.0.1:8123/"
    docker run --rm -it \
      "${CONSTRAINTS[@]}" \
      -e ARCADE_KIOSK_RES="$KIOSK_RES" \
      ${RENDERER_ARGS[@]+"${RENDERER_ARGS[@]}"} \
      -p 6080:6080 \
      -p 127.0.0.1:8123:8123 \
      -p 127.0.0.1:8124:8124 \
      ${KEY_ARGS[@]+"${KEY_ARGS[@]}"} \
      -v "${GAMES_VOLUME}:/games" \
      -v "${CACHE_VOLUME}:/cache" \
      "$IMAGE" library
    ;;

  *)
    echo "unknown mode: $MODE" >&2
    exit 2
    ;;
esac
