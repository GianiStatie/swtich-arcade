# How to run the arcade simulator

A practical, copy-paste guide. For *what* it is and *why*, see
[README.md](README.md).

- [Prerequisites](#prerequisites)
- [Command reference](#command-reference)
- [Passing your itch.io API key](#passing-your-itchio-api-key)
- [Test one build](#test-one-build)
- [Library mode: sync + browse + play](#library-mode-sync--browse--play)
- [The host API (:8123)](#the-host-api-8123)
- [Windows / no bash (Docker Compose)](#windows--no-bash-docker-compose)
- [Volumes, ports, stopping](#volumes-ports-stopping)
- [Troubleshooting](#troubleshooting)

## Prerequisites

- **Docker** running (Docker Desktop, colima, or the Docker engine).
- A terminal. macOS/Linux use `docker/run.sh` (needs `bash`); Windows can use
  Docker Compose instead (see below).
- For `--sync`: an **itch.io API key** and network access.

Check Docker is up:

```bash
docker info >/dev/null && echo "docker ok" || echo "docker not running"
```

## Command reference

All commands are run **from the repository root**.

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

The image is built automatically on first use. By default every run uses the
**maxed profile** — more CPU/RAM and a 640×360 kiosk with **llvmpipe**, so 3D
games run ~30 fps (see [README.md](README.md#the-constraints-it-applies-on-by-default)).
Use `--strict` for the cabinet-faithful profile
(**4 cores, 4 GB, 720p**); env vars override either.

## Passing your itch.io API key

Only `--sync` needs the key (and `--library`'s auto-sync, if the library is
empty). Pick whichever you prefer:

```bash
# 1. Inline, for a single command:
ITCH_API_KEY=ooCT9MSE... docker/run.sh --sync

# 2. Exported for the session:
export ITCH_API_KEY=ooCT9MSE...
docker/run.sh --sync

# 3. A key file (best for reuse):
mkdir -p ~/.config
printf '%s' 'ooCT9MSE...' > ~/.config/itch_api_key
chmod 600 ~/.config/itch_api_key
docker/run.sh --sync          # run.sh mounts the file read-only automatically
```

The key is never written to the repo. The container writes it to
`/root/.config/itch_api_key` **inside the container** and it's passed to Docker
only as `-e ITCH_API_KEY`. Treat the key like a password; rotate it if it leaks.

## Test one build

Your build directory must contain **`index.html` at its root**.

```bash
# Interactive: opens a browser you can play in.
docker/run.sh /path/to/your/build

# -> open http://localhost:6080/vnc.html and click "Connect"

# Headless checks (CI-friendly):
docker/run.sh --check /path/to/your/build
```

Interactive mode prints the noVNC URL. Controls (keyboard):

| Arcade control | Key |
|---|---|
| Joystick / D-pad | Arrow keys |
| A | Space |
| B | R |
| X | Esc |
| Y | Tab |

## Library mode: sync + browse + play

```bash
# First time: pull the collection (needs a key), then start.
docker/run.sh --library --sync

# Later: library is cached in a volume; no key needed.
docker/run.sh --library
```

Two ways to browse, both started by `--library`:

- **Kiosk (inside the container):** open <http://localhost:6080/vnc.html>.
  A menu of game tiles; click one to play. The in-game Quit button returns to
  the menu.
- **Host API (recommended for your own machine):** see the next section.

`--sync` installs each game to `<games volume>/web/<Title>/` with `index.html`
at the root, exactly like the cabinet; games with no HTML upload are skipped
(the watcher logs why).

## The host API (:8123)

In library mode a small API is published **host-local** at `127.0.0.1:8123`,
so you can list and launch games from your host browser or a script:

```bash
curl http://127.0.0.1:8123/                 # clickable HTML list
open http://127.0.0.1:8123/                # (macOS) open it in a browser
curl 'http://127.0.0.1:8123/?format=json'  # {"games":[{"name","play"}]}
curl 'http://127.0.0.1:8123/?format=text'  # one URL per line
curl -L http://127.0.0.1:8123/play/PolyTrack   # start + load a game
```

| Route | Purpose |
|---|---|
| `GET /` | HTML list of clickable play links (`?format=json` / `?format=text`). |
| `GET /play/<name>` | Points the shared `:8124` server at that game, then redirects the browser to `http://<host>:8124/index.html`. |
| `GET /exit` | Returns `OK` and kills Chromium (games' in-game Quit button). |

> Opening **http://127.0.0.1:8123/** gives a **status page**: a "Running" banner,
> uptime, the library path + volume, the clickable game list, and the exact
> sync/run/copy commands.

> Playing from the host uses **your** GPU at full resolution — none of the
> SwiftShader / 720p / 4 GB constraints apply. It's a convenience path; use
> `--check` or noVNC to test against the cabinet's constraints.

`:8124` serves **one game at a time**, so it only responds *after* you launch a
game (via `/play/<name>` or the kiosk menu). Hitting `:8124` cold will refuse.

## Check status / where the games live

**`--sync` is a one-shot run** — it downloads the games and exits (the container
is removed). Only `--library` / `interactive` keep a container alive.

Is it running?

```bash
docker ps                                          # look for arcade-contract-sim-library-1
docker compose -f docker/compose.yaml ps           # if you use compose
curl -s http://127.0.0.1:8123/ >/dev/null && echo running || echo "not running"
```

**Status page (works while running):** open <http://127.0.0.1:8123/>.
**Status page (works even when nothing is running):** open
[`status.html`](status.html) in your browser — it pings the API and shows
Running / Not running plus the commands and locations.

Where the games are:

- **In the container/volume:** `/games/web/<Title>/` inside the Docker volume
  `arcade-contract-sim-games`.
- **On the host:** the volume lives inside Docker's VM, so it's not a path you
  can open directly. Copy the files out:

  ```bash
  docker run --rm -v arcade-contract-sim-games:/games \
    -v "$PWD/games-export:/out" alpine \
    sh -c 'mkdir -p /out && cp -r /games/web /out/'
  ```

- **Easiest:** start `docker/run.sh --library`, then browse
  <http://127.0.0.1:8123/>.

## Responsiveness & the CPU knob

Two different things feel "slow" here: the **noVNC stream** (input/display
latency) and the **game** (SwiftShader + CPU). If the kiosk feels laggy, that's
mostly the stream, and it competes with SwiftShader for the container's CPU.

- **The stream** is tuned for latency: `x11vnc` with
  `-threads -noxdamage -ncache 0 -wait 5 -defer 5`, and a noVNC landing page at
  <http://localhost:6080/> that auto-connects with fast compression.
- **The renderer** is **llvmpipe** (Mesa) by default — ~2× faster than
  SwiftShader for 3D. `ARCADE_RENDERER=swiftshader` to fall back.
- **The resolution** is the biggest lever (software rasterization cost scales
  with pixels). The default `ARCADE_KIOSK_RES=640x360` runs PolyTrack at
  ~30 fps and Dragon Jump at ~60 fps in the kiosk.
- **The CPU** knob gives the container headroom so the simulator isn't the
  bottleneck. It's **maxed by default**; `--strict` restores the cabinet figure:

  | Want | Do |
  |---|---|
  | Max the container can do (**default**) | `docker/run.sh --library` |
  | Cabinet-faithful (4 cores / 4g / 720p) | `docker/run.sh --strict --library` |
  | A specific figure | `ARCADE_CPU_QUOTA=… docker/run.sh --library` |

  ```bash
  docker/run.sh --library                              # maxed by default
  docker/run.sh --strict --library                     # cabinet figure
  ARCADE_CPU_QUOTA=600000 docker/run.sh --library      # custom
  ARCADE_KIOSK_RES=960x540 docker/run.sh --library     # intermediate resolution
  ```
  Other envs: `ARCADE_CPU_PERIOD` (default `100000` µs), `ARCADE_MEMORY`
  (default `8g`), `ARCADE_KIOSK_RES` (default `640x360`), `ARCADE_RENDERER`.
  The live status page (<http://127.0.0.1:8123/>) shows the **CPU limit / RAM
  limit** actually applied, read from cgroup.

  > **First, raise the Docker VM** (the container can't exceed it):
  > `colima stop && colima start --cpu 8 --memory 10`, or Docker Desktop →
  > Settings → Resources. See [FIDELITY.md](FIDELITY.md).

  > **Caveat:** this is CPU *time* + a software renderer, not a 1.02 GHz clock or
  > a Maxwell GPU. It's enough to hit ~30 fps for PolyTrack, but it's still an
  > approximation. The only true performance gauge is the frame-time test on the
  > cabinet.

## Windows / no bash (Docker Compose)

`run.sh` needs `bash`. On stock Windows, use the OS-neutral Compose front-end
(Docker Desktop bundles `docker compose`):

```powershell
# PowerShell — use forward slashes in paths
$env:ITCH_API_KEY="ooCT9MSE..." ;  docker compose -f docker/compose.yaml run --rm sync
docker compose -f docker/compose.yaml up library
$env:BUILD_DIR="C:/path/to/build"; docker compose -f docker/compose.yaml run --rm check
```

Or drop the values in `docker/.env` (compose reads it automatically):

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

The Compose services share the **same volumes** as `run.sh`, so a library
synced either way is visible to both.

## Volumes, ports, stopping

| Name | Purpose |
|---|---|
| `arcade-contract-sim-games` | Synced game library (`/games`). |
| `arcade-contract-sim-cache` | Persistent Chromium shader/WASM cache. |

| Host port | What |
|---|---|
| `6080` | noVNC (the in-container kiosk). |
| `127.0.0.1:8123` | Arcade API (list/launch/exit). |
| `127.0.0.1:8124` | The currently loaded game (library mode only). |

- **Stop an interactive/library run:** press **Ctrl-C** in the terminal.
- **Stop a Compose run:** `docker compose -f docker/compose.yaml down`.
- **Wipe the library:** `docker volume rm arcade-contract-sim-games`.
- **Wipe the cache:** `docker volume rm arcade-contract-sim-cache`.

## Troubleshooting

- **`KEY_ARGS[@]: unbound variable`** on macOS: old `/bin/bash` 3.2 with `set -u`.
  Already fixed — update to the latest `docker/run.sh`.
- **"index.html not found"**: the build dir must have `index.html` at its root.
- **`--memory`/`--cpu-quota` fails**: the Docker VM has less than requested.
  Raise it in Docker Desktop → Settings → Resources (or `colima start --cpu 8
  --memory 10`), or lower `ARCADE_MEMORY` / `ARCADE_CPU_QUOTA`.
- **Ports refuse / "can't access 127.0.0.1:8124"**: `:8124` only listens *after*
  a game is launched (by design — one game at a time). Use `:8123/` first.
- **noVNC blank screen**: give it a few seconds; check
  `/tmp/webgame_server.log` and `/tmp/xvfb.log` inside the container.
- **`--sync` fails with "no itch.io API key"**: pass the key (see above).
- **Threaded build won't start**: run `--check`; if `crossOriginIsolated` is
  false the COOP/COEP headers aren't reaching the page.
- **SwiftShader is slow**: expected — it's the pessimistic lower bound, not
  the cabinet's real GPU.
