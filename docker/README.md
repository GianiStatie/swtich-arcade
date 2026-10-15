# Arcade Contract Simulator (Docker)

A container that reproduces the arcade cabinet's **software contract** so you can
verify an HTML5 web build before shipping it — without a Switch. It is **not** a
Switch/Tegra emulator; it can't fake the cabinet's CPU/GPU *performance*.

**Run it →** [docs/RUNNING.md](docs/RUNNING.md) ·
**Why it's not the cabinet →** [docs/FIDELITY.md](docs/FIDELITY.md)

## Quick start

```bash
# Play one build in a browser (needs index.html at the build root).
docker/run.sh /path/to/your/build          # -> open http://localhost:6080/

# Headless contract checks (CI-friendly; non-zero exit on failure).
docker/run.sh --check /path/to/your/build

# Browse the whole synced itch collection (menu + host API).
docker/run.sh --library
```

The image builds automatically on first use. Every run is **maxed by default**
(8 cores / 8 GB / 640×360, llvmpipe) so 3D games are usable; add `--strict` for
the cabinet-faithful profile (4 cores / 4 GB / 720p).

> No bash (Windows)? Use Compose — see
> [docs/RUNNING.md](docs/RUNNING.md#windows--no-bash-docker-compose).

Controls (keyboard, in the noVNC window):

| Arcade control | Key |
|---|---|
| Joystick / D-pad | Arrow keys |
| A | Space |
| B | R |
| X | Esc |
| Y | Tab |

## Commands

All run **from the repository root**.

| Command | What it does |
|---|---|
| `docker/run.sh <build-dir>` | Play one build (interactive, noVNC). |
| `docker/run.sh --check <build-dir>` | Headless contract checks; non-zero exit on failure. |
| `docker/run.sh --library` | Menu of every synced game + host API on `:8123`. |
| `docker/run.sh --library --sync` | Sync the collection first, then start the menu. |
| `docker/run.sh --sync` | Pull the whole itch collection into the games volume. |
| `docker/run.sh --list` | Print installed game titles. |
| `docker/run.sh --strict --library` | Cabinet-faithful instead (4 cores / 4g / 1280×720). |
| `docker/run.sh --help` | Usage. |

## What it checks

- `index.html` sits at the build root.
- The page loads with **no console or page errors**.
- **`crossOriginIsolated === true`** — proves COOP/COEP are in place, which
  threaded (SharedArrayBuffer) Godot/Unity builds require to boot.
- **WebGL 2.0** is available.
- **Nothing leaves loopback** — no CDN scripts, Google Fonts or hotlinked
  images (catches the "cabinet is offline → broken/hanging game" failure).
- The canvas backing store is **≤ 720p** (warning only).

## Files

| File | Purpose |
|---|---|
| `Dockerfile` | Image: Debian + Chromium + Xvfb/x11vnc/noVNC + the arcade servers. |
| `entrypoint.sh` | Modes: `interactive`, `check`, `library`, `sync`, `list`. |
| `exit-to-es.sh` | Container stand-in for the path `exit-server.py` hardcodes. |
| `run.sh` | Build/run wrapper with the constraint profile. |
| `compose.yaml` | OS-neutral front-end (no bash) — same modes/volumes as `run.sh`. |
| `servers/menu-server.py` | Library menu + per-game launcher (ES stand-in), port `8125`. |
| `servers/api-server.py` | Host-facing arcade API (`/`, `/play/<name>`, `/exit`), port `8123`. |
| `servers/library.py` | Shared library scan + launcher used by both servers. |
| `web/status.html` | Static status page (open anytime; live check via JSONP). |
| `web/novnc-index.html` | Tuned noVNC landing page (auto-connect) served on `:6080`. |
| `check/check.mjs` | Headless contract checker (puppeteer-core). |
| `check/package.json` | Checker dependency (`puppeteer-core`). |
| `docs/RUNNING.md` | Task-oriented "how to run" guide (commands, API key, Compose, troubleshooting). |
| `docs/FIDELITY.md` | Why a container can't simulate the Switch (+ the constraints). |

## More

- **How to run everything** — API key, library mode, host API, Compose, volumes,
  ports, troubleshooting: [docs/RUNNING.md](docs/RUNNING.md).
- **How faithful it is / why it's slow** — the constraints, the software
  renderer, measured numbers, and what to use instead:
  [docs/FIDELITY.md](docs/FIDELITY.md).
