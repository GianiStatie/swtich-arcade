# Arcade Contract Simulator (Docker)

A container that reproduces the arcade cabinet's **software contract** so you can
verify an HTML5 web build before shipping it to the event — without a Switch.

> **Just want to run it?** See the copy-paste **[RUNNING.md](RUNNING.md)** guide
> (commands, API key, library mode, Windows/Compose).
>
> **Why it never feels like the cabinet?** See **[FIDELITY.md](FIDELITY.md)** —
> what a container can and can't simulate, and what to use instead.

> **This is not a Switch/Tegra emulator.** It replays the *setup* the cabinet
> runs (Ubuntu-ish Chromium kiosk, the arcade's own HTTP/exit servers, COOP/COEP,
> 720p, keyboard input). It cannot fake the Tegra X1's CPU/GPU/memory
> *performance*. Container frame rates are **not** cabinet frame rates. For
> real performance numbers, run the frame-time test on the cabinet
> ([`../docs/switch-arcade-perf-plan.md`](../docs/switch-arcade-perf-plan.md)).

## What it checks

- `index.html` sits at the build root.
- The page loads with **no console or page errors**.
- **`crossOriginIsolated === true`** — proves COOP/COEP are in place, which
  threaded (SharedArrayBuffer) Godot/Unity builds require to boot.
- **WebGL 2.0** is available.
- **Nothing leaves loopback** — no CDN scripts, Google Fonts or hotlinked
  images (catches the "cabinet is offline → broken/hanging game" failure).
- The canvas backing store is **≤ 720p** (warning only).

## Quick start

```bash
# Interactive: play it in a browser tab.
docker/run.sh /path/to/your/build

# Headless contract checks (CI-friendly, non-zero exit on failure).
docker/run.sh --check /path/to/your/build
```

Your build directory must contain `index.html` at its root. It is mounted
read-only at `/game`.

Interactive mode prints a URL — open **<http://localhost:6080/vnc.html>** and
play with the keyboard:

| Arcade control | Key |
|---|---|
| Joystick / D-pad | Arrow keys |
| A | Space |
| B | R |
| X | Esc |
| Y | Tab |

### Don't have bash? Use Docker Compose (Windows / any OS)

`run.sh` needs a bash shell. Where that isn't available (stock Windows), use
the OS-neutral Compose front-end — Docker Desktop bundles `docker compose`:

```powershell
# PowerShell (use forward slashes in paths)
$env:ITCH_API_KEY="...";           docker compose -f docker/compose.yaml up library
$env:BUILD_DIR="C:/path/to/build"; docker compose -f docker/compose.yaml run --rm check
docker compose -f docker/compose.yaml run --rm interactive
```

Or drop the values in `docker/.env` (compose reads it automatically):

```
ITCH_API_KEY=...
BUILD_DIR=C:/path/to/build
# optional overrides — defaults are already maxed:
# ARCADE_CPU_QUOTA=400000
# ARCADE_KIOSK_RES=1280x720
```

| Compose command | Does |
|---|---|
| `docker compose -f docker/compose.yaml up library` | library menu (noVNC `:6080`) + host API (`:8123`) |
| `... run --rm sync` | pull the itch collection |
| `... run --rm list` | print installed titles |
| `BUILD_DIR=… ... run --rm check` | headless contract checks |
| `BUILD_DIR=… ... run --rm interactive` | play one build via noVNC |

The Compose services share the **same volumes** as `run.sh`
(`arcade-contract-sim-games` / `-cache`), so a library synced either way is
visible to both.

> **Caveat:** the Compose front-end was exercised on macOS/Linux only — the
> Windows path is provided but **not tested here**. If `docker compose` is
> missing on Linux, install the Compose plugin (or use the standalone
> `docker-compose` binary, replacing `docker compose` with `docker-compose`).

## Library mode — browse and launch every game

Instead of testing one build, the simulator can pull the whole itch.io
collection and show a menu of everything synced — a lightweight stand-in for
EmulationStation.

```bash
# First time: pull the collection (needs an itch.io API key), then browse.
docker/run.sh --library --sync

# Later runs: library is cached in a volume; just start the menu.
docker/run.sh --library

# Just sync (headless), or list what's installed:
docker/run.sh --sync
docker/run.sh --list
```

Open **<http://localhost:6080/vnc.html>**. You get a menu of game titles; click
one to play. **Menu → game → in-game Quit returns to the menu** (the quit
endpoint kills Chromium and the supervisor reopens the menu).

How faithful it is to the cabinet:

- Each game is launched **at the root path on `:8124`** by the repo's own
  `webgame-server.py`, exactly like `launch-web-game.sh` does on the Switch — not
  from a subpath.
- The pull reuses [`../scripts/itch-watcher.py`](../scripts/itch-watcher.py)
  unchanged (`--once --force`), so the install layout, `.web` markers and prune
  behavior match the cabinet.
- Games live in a Docker volume (`arcade-contract-sim-games`), not the image, and
  persist across runs.

**Credentials & network:** sync needs network access and an itch.io API key.
`export ITCH_API_KEY=…` before running `run.sh`, or keep a key file at
`~/.config/itch_api_key` — `run.sh` mounts it read-only. The key is never baked
into the image. Because it needs the network, sync/library can't run under
`--network=none` (only `--check` does).

**Limits:** not every collection game is pullable (free/owned constraints; games
with no HTML upload are skipped, as the watcher logs). The menu shows titles
only — no ES cover art. The menu is *a stand-in for ES*, nothing more.

## Playing from your host browser (the arcade API)

In library mode the container also exposes a small **arcade API on
`127.0.0.1:8123`** (published host-local), so you can list and launch games
without the noVNC window:

```bash
# A clickable list of every game:
curl http://127.0.0.1:8123/            # -> HTML with <a> links
open http://127.0.0.1:8123/          # or just open it in a browser

# Machine-readable forms:
curl 'http://127.0.0.1:8123/?format=json'
curl 'http://127.0.0.1:8123/?format=text'
```

| Route | What it does |
|---|---|
| `GET /` | HTML page of clickable links to each game (`?format=json` / `?format=text` for scripts). |
| `GET /play/<name>` | Points the shared `:8124` server at that game, then `302`-redirects the browser to `http://<host>:8124/index.html`. |
| `GET /exit` | Same contract as the cabinet's exit server: returns `OK` (CORS `*`) and kills Chromium. |

The links use selector URLs (`/play/<name>`) because `:8124` serves **one game
at a time** — every play link swaps the server first, so all of them end up at
the same `:8124/index.html`.

> **This is a convenience path, not the fidelity path.** Playing from your host
> uses *your* GPU at full resolution — none of the SwiftShader / 720p / 4 GB
> constraints apply. Use `--check` or the noVNC session to test against the
> cabinet's constraints. Also, a game's in-game Quit button returns `OK` here
> but can't close your host tab (the server kills the container's Chromium, a
> different browser).

## The constraints it applies (on by default)

| Cabinet spec | How it's faked | How faithful |
|---|---|---|
| 4 GB LPDDR4 | `ARCADE_MEMORY` (default **8g**, i.e. max; `--strict` uses 4g) | Deliberately maxed by default; `--strict` for the cabinet figure. |
| 4× Cortex-A57 perf cluster | cgroup CPU quota; `ARCADE_CPU_QUOTA` default `800000` (~8 cores; `--strict`/`400000` = 4) | **Count/time only** — see the fidelity note below. |
| Maxwell GPU | Software renderer (no GPU in the container): **llvmpipe** in the kiosk, **SwiftShader** for headless checks | **Approximation.** Not a Maxwell, but llvmpipe runs PolyTrack ~30 fps at 360p. |
| 720p output | `ARCADE_KIOSK_RES` (default **640x360**, max; `--strict` uses 1280x720) + canvas assertion | Maxed by default for usability. |
| Offline cabinet | `--network=none` in `--check` | **Good.** |

> **Max is the default.** `docker/run.sh` and `compose` run the container at its
> ceiling (8 cores / 8g / 640×360, llvmpipe) so 3D games are usable. Add
> `--strict` (or `--profile strict` on compose) for the cabinet-faithful
> profile. Env vars override either way.

### Why a software renderer?

Docker Desktop (Mac/Windows) has no GPU passthrough, so the container always uses
a CPU rasterizer. **llvmpipe** (Mesa) is the default in the kiosk because it's
~2× faster than SwiftShader for 3D; SwiftShader remains the default for the
headless checker. See [FIDELITY.md](FIDELITY.md).

### What is *not* faked

- Maxwell **driver behavior**: the GPU-watchdog/context-loss quirks that
  `--disable-gpu-watchdog` exists for, ETC2 decoding, shader-compile stalls.
- CPU **clock/thermal** behavior. The `ARCADE_CPU_QUOTA` knob limits CPU *time*
  (so you can dial it down), but it stalls in bursts rather than running
  uniformly slower — it's a throttle, not a 1.02 GHz clock. RAM and thread
  count are the reliable levers.
- **Memory bandwidth** (25.6 GB/s) — no portable cgroup lever.
- The A53 cluster and the ARM ISA (WASM compiles to the host ISA anyway).

> Net effect: even with the constraints, a container run (and especially a
> host-browser run, which applies **none** of them) feels faster than the
> cabinet. This image is for **contract/correctness**, not for judging
> performance — measure that on the cabinet
> ([`../docs/switch-arcade-perf-plan.md`](../docs/switch-arcade-perf-plan.md)).

## Which arcade behavior is reused verbatim

| Path | Source |
|---|---|
| `webgame-server.py` | [`../scripts/webgame-server.py`](../scripts/webgame-server.py) — COOP/COEP, `.wasm`/`.pck` MIME, `.br`/`.gz` sidecars, `no-store`. (One added line: a `WEBGAME_BIND` env var, default `127.0.0.1`, so the container can bind `0.0.0.0` in library mode; the Switch behavior is unchanged.) |
| `exit-server.py` | [`../scripts/exit-server.py`](../scripts/exit-server.py) — port `8123`; powers in-game Quit buttons. |
| `itch-watcher.py` | [`../scripts/itch-watcher.py`](../scripts/itch-watcher.py) — the collection pull used by `--sync`. |
| Chromium flags | Ported from [`../scripts/launch-web-game.sh`](../scripts/launch-web-game.sh) (plus the constraint flags above). |

`gamepad-bridge.py` is **not** run: it needs `/dev/uinput` and a physical
Joy-Con, which a container doesn't have. Keyboard is exactly what the game sees
anyway (the bridge injects keys), so typing in the noVNC window exercises the
same game-facing contract.

An in-game Quit button calling `http://127.0.0.1:8123/exit` will end the
interactive session, because Chromium runs *inside* the container — same
loopback semantics as the cabinet.

## Multi-arch / distributing the image

Mac (Apple Silicon) gets a native `arm64` image and Windows/Linux an `amd64`
one. `run.sh` builds for the host arch on first use. To publish a multi-arch
image:

```bash
docker buildx build --platform linux/amd64,linux/arm64 \
  -f docker/Dockerfile -t <registry>/arcade-contract-sim:latest --push .
```

## Files

| File | Purpose |
|---|---|
| `Dockerfile` | Image: Debian + Chromium + Xvfb/x11vnc/noVNC + the arcade servers. |
| `entrypoint.sh` | Modes: `interactive`, `check`, `library`, `sync`, `list`. |
| `menu-server.py` | Library menu + per-game launcher (ES stand-in), port `8125`. |
| `api-server.py` | Host-facing arcade API (`/`, `/play/<name>`, `/exit`), port `8123`. |
| `status.html` | Static status page (open anytime; live check via JSONP). |
| `library.py` | Shared library scan + launcher used by both servers. |
| `exit-to-es.sh` | Container stand-in for the path `exit-server.py` hardcodes. |
| `check.mjs` | Headless contract checker (puppeteer-core). |
| `run.sh` | Build/run wrapper with the constraint profile. |
| `compose.yaml` | OS-neutral front-end (no bash) — same modes/volumes as `run.sh`. |
| `RUNNING.md` | Task-oriented "how to run" guide (commands, API key, Compose). |
| `FIDELITY.md` | What a container can/can't simulate vs. the Switch, and the best proxies. |
| `package.json` | Checker dependency (`puppeteer-core`). |

## Troubleshooting

- **`--memory=4g` fails**: Docker Desktop's VM has less than 4 GB assigned.
  Raise it in Docker Desktop → Settings → Resources, or edit `CONSTRAINTS` in
  `run.sh`.
- **noVNC shows a blank screen**: give the game a few seconds; check
  `/tmp/webgame_server.log` and `/tmp/xvfb.log` inside the container.
- **Threaded build won't start**: run `--check`; if `crossOriginIsolated` is
  false, the COOP/COEP headers aren't reaching the page.
- **SwiftShader is too slow to be usable**: expected — it's the pessimistic
  bound. Play your game natively for fun; use this for correctness.
- **`--library` shows "No games in the library yet"**: the volume is empty —
  run `docker/run.sh --sync` (or `--library --sync`) with an itch.io API key.
- **`--sync` fails with "no itch.io API key"**: set `ITCH_API_KEY`, or place a
  key at `~/.config/itch_api_key` and re-run.
