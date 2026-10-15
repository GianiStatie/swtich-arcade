# How to run the arcade simulator

Copy-paste guide to running the container. For what it is and why it isn't the
cabinet, see [README.md](../README.md) and [FIDELITY.md](FIDELITY.md).

- [Prerequisites](#prerequisites)
- [Commands](#commands)
- [Passing your itch.io API key](#passing-your-itchio-api-key)
- [Test one build](#test-one-build)
- [Library mode](#library-mode)
- [The host API (:8123)](#the-host-api-8123)
- [Where things live / stopping](#where-things-live--stopping)
- [Performance knobs](#performance-knobs)
- [Windows / no bash (Docker Compose)](#windows--no-bash-docker-compose)
- [Build / distribute the image](#build--distribute-the-image)
- [Troubleshooting](#troubleshooting)

## Prerequisites

- **Docker** running (Docker Desktop, colima, or the Docker engine).
- A terminal. macOS/Linux use `docker/run.sh` (needs `bash`); Windows uses
  Docker Compose instead (see below).
- For `--sync`: an **itch.io API key** and network access.

```bash
docker info >/dev/null && echo "docker ok" || echo "docker not running"
```

## Commands

All commands run **from the repository root**.

| Command | What it does |
|---|---|
| `docker/run.sh <build-dir>` | Play one build in a browser (interactive). |
| `docker/run.sh --check <build-dir>` | Headless contract checks; non-zero exit on failure. |
| `docker/run.sh --library` | Menu of every synced game + host API on `:8123`. |
| `docker/run.sh --library --sync` | Sync the collection first, then start the menu. |
| `docker/run.sh --sync` | Pull the whole itch collection into the games volume. |
| `docker/run.sh --list` | Print installed game titles. |
| `docker/run.sh --strict --library` | Cabinet-faithful instead (4 cores / 4g / 1280×720). |
| `docker/run.sh --help` | Usage. |

The image builds automatically on first use. Every run is **maxed by default**
(8 cores / 8 GB / 640×360, llvmpipe); `--strict` gives the cabinet profile
(4 cores / 4 GB / 720p). Env vars override the profile — see
[Performance knobs](#performance-knobs).

## Passing your itch.io API key

Only `--sync` needs it (and `--library`'s auto-sync when the library is empty):

```bash
# 1. Inline, for a single command:
ITCH_API_KEY=ooCT9MSE... docker/run.sh --sync

# 2. Exported for the session:
export ITCH_API_KEY=ooCT9MSE...
docker/run.sh --sync

# 3. A key file (best for reuse) — run.sh mounts it read-only:
mkdir -p ~/.config
printf '%s' 'ooCT9MSE...' > ~/.config/itch_api_key
chmod 600 ~/.config/itch_api_key
docker/run.sh --sync
```

The key is never written to the repo; it's passed only as `-e ITCH_API_KEY`.
Treat it like a password and rotate it if it leaks.

## Test one build

Your build directory must contain **`index.html` at its root**.

```bash
docker/run.sh /path/to/your/build          # interactive -> http://localhost:6080/
docker/run.sh --check /path/to/your/build  # headless checks (CI-friendly)
```

Controls (keyboard, in the noVNC window):

| Arcade control | Key |
|---|---|
| Joystick / D-pad | Arrow keys |
| A | Space |
| B | R |
| X | Esc |
| Y | Tab |

## Library mode

```bash
docker/run.sh --library --sync   # first time: pull the collection (needs a key)
docker/run.sh --library          # later: cached in a volume, no key needed
```

Two ways to browse, both started by `--library`:

- **Kiosk (in-container):** open <http://localhost:6080/>. A menu of tiles; click
  one to play. The in-game Quit button returns to the menu.
- **Host API (recommended on your own machine):** see below.

`--sync` installs each game to `<games volume>/web/<Title>/` with `index.html`
at the root, exactly like the cabinet; games with no HTML upload are skipped.

## The host API (:8123)

In library mode a small API is published host-local at `127.0.0.1:8123`:

```bash
curl http://127.0.0.1:8123/                    # clickable HTML list
open http://127.0.0.1:8123/                    # (macOS) open in a browser
curl 'http://127.0.0.1:8123/?format=json'      # {"games":[{"name","play"}]}
curl 'http://127.0.0.1:8123/?format=text'      # one URL per line
curl -L http://127.0.0.1:8123/play/PolyTrack   # start + load a game
```

| Route | Purpose |
|---|---|
| `GET /` | HTML list of clickable play links (`?format=json` / `?format=text`). |
| `GET /play/<name>` | Points the shared `:8124` server at that game, then redirects to `http://<host>:8124/index.html`. |
| `GET /exit` | Returns `OK` and kills Chromium (games' in-game Quit button). |

`http://127.0.0.1:8123/` is also the live **status page** (Running banner,
uptime, library path, game list, copy/run commands).

`:8124` serves **one game at a time**, so it only responds *after* you launch a
game (via `/play/<name>` or the menu). Hitting `:8124` cold will refuse.

> Playing from the host uses **your** GPU unconstrained — a convenience path,
> not the fidelity path. See [FIDELITY.md](FIDELITY.md).

## Where things live / stopping

Is it running?

```bash
docker ps                                      # look for the library container
docker compose -f docker/compose.yaml ps       # if you use compose
curl -s http://127.0.0.1:8123/ >/dev/null && echo running || echo "not running"
```

- **Status page (while running):** <http://127.0.0.1:8123/>
- **Status page (nothing running):** open [`web/status.html`](../web/status.html)
  in your browser — it pings the API and shows Running / Not running.

Games live in the volume `arcade-contract-sim-games`, at `/games/web/<Title>/`
inside Docker's VM (not a path you can open directly). Copy them out:

```bash
docker run --rm -v arcade-contract-sim-games:/games \
  -v "$PWD/games-export:/out" alpine \
  sh -c 'mkdir -p /out && cp -r /games/web /out/'
```

`--sync` is a one-shot run (downloads and exits); only `--library` /
`interactive` keep a container alive. Stop them with **Ctrl-C** (or
`docker compose -f docker/compose.yaml down`).

| Volume | Purpose |
|---|---|
| `arcade-contract-sim-games` | Synced game library (`/games`). |
| `arcade-contract-sim-cache` | Persistent Chromium shader/WASM cache. |

| Host port | What |
|---|---|
| `6080` | noVNC (the in-container kiosk). |
| `127.0.0.1:8123` | Arcade API (list/launch/exit). |
| `127.0.0.1:8124` | The currently loaded game (library mode only). |

Wipe them with `docker volume rm arcade-contract-sim-games` (library) or
`docker volume rm arcade-contract-sim-cache`.

## Performance knobs

The container is **maxed by default**; `--strict` restores the cabinet figure:

| Want | Do |
|---|---|
| Max the container can do (**default**) | `docker/run.sh --library` |
| Cabinet-faithful (4 cores / 4g / 720p) | `docker/run.sh --strict --library` |
| A specific figure | `ARCADE_CPU_QUOTA=… docker/run.sh --library` |

```bash
ARCADE_CPU_QUOTA=600000 docker/run.sh --library      # custom
ARCADE_KIOSK_RES=960x540 docker/run.sh --library     # intermediate resolution
```

Envs: `ARCADE_CPU_QUOTA`, `ARCADE_CPU_PERIOD` (default `100000` µs),
`ARCADE_MEMORY` (default `8g`), `ARCADE_KIOSK_RES` (default `640x360`),
`ARCADE_RENDERER` (`llvmpipe` default / `swiftshader`). The status page
(<http://127.0.0.1:8123/>) shows the CPU/RAM limits actually applied.

> Raise the Docker VM first — the container can't exceed it: `colima stop &&
> colima start --cpu 8 --memory 10`, or Docker Desktop → Settings → Resources.
> Why this is still only an approximation: [FIDELITY.md](FIDELITY.md).

## Windows / no bash (Docker Compose)

`run.sh` needs `bash`. On stock Windows use the OS-neutral Compose front-end:

```powershell
# PowerShell — use forward slashes in paths
$env:ITCH_API_KEY="ooCT9MSE...";  docker compose -f docker/compose.yaml run --rm sync
docker compose -f docker/compose.yaml up library
$env:BUILD_DIR="C:/path/to/build"; docker compose -f docker/compose.yaml run --rm check
```

Or put values in `docker/.env` (compose reads it automatically):

```
ITCH_API_KEY=ooCT9MSE...
BUILD_DIR=C:/path/to/build
# optional overrides — defaults are already maxed:
# ARCADE_CPU_QUOTA=400000
# ARCADE_KIOSK_RES=1280x720
```

| Compose command | Does |
|---|---|
| `docker compose -f docker/compose.yaml up library` | library menu + host API |
| `... run --rm sync` | pull the itch collection |
| `... run --rm list` | print installed titles |
| `BUILD_DIR=… ... run --rm check` | headless contract checks |
| `BUILD_DIR=… ... run --rm interactive` | play one build via noVNC |
| `--profile strict up library-strict` | cabinet-faithful profile |

The Compose services share the **same volumes** as `run.sh`.

## Build / distribute the image

`run.sh` builds for the host arch on first use. To publish a multi-arch image:

```bash
docker buildx build --platform linux/amd64,linux/arm64 \
  -f docker/Dockerfile -t <registry>/arcade-contract-sim:latest --push .
```

## Troubleshooting

- **"index.html not found"**: the build dir must have `index.html` at its root.
- **`--memory`/`--cpu-quota` fails**: the Docker VM has less than requested.
  Raise it in Docker Desktop → Settings → Resources (or `colima start --cpu 8
  --memory 10`), or lower `ARCADE_MEMORY` / `ARCADE_CPU_QUOTA`.
- **Ports refuse / "can't access 127.0.0.1:8124"**: `:8124` only listens *after*
  a game is launched (by design — one game at a time). Use `:8123/` first.
- **noVNC blank screen**: give it a few seconds; check
  `/tmp/webgame_server.log` and `/tmp/xvfb.log` inside the container.
- **`--sync` fails with "no itch.io API key"**: pass the key (see above).
- **`--library` shows "No games in the library yet"**: the volume is empty —
  run `docker/run.sh --library --sync` with a key.
- **Threaded build won't start**: run `--check`; if `crossOriginIsolated` is
  false the COOP/COEP headers aren't reaching the page.
- **`KEY_ARGS[@]: unbound variable`** on macOS: old `/bin/bash` 3.2 with `set -u`
  — already fixed; update `docker/run.sh`.
- **SwiftShader is slow**: expected — see [FIDELITY.md](FIDELITY.md).
