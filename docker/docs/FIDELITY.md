# Can the container simulate the Switch's hardware?

**Short answer: no — not faithfully.** Only real Tegra X1 hardware (the cabinet,
or a close ARM device) can. This page explains the walls, what the container
*does* enforce, and what to use instead — so the two paths aren't mistaken for
each other.

## The three walls

1. **GPU.** Docker Desktop / colima give the container **no GPU** on macOS, so
   WebGL runs on a **software rasterizer** — **llvmpipe** by default (~2× faster
   for 3D; `ARCADE_RENDERER=swiftshader` to fall back). There is no host-GPU
   passthrough here, and no Maxwell/Tegra driver emulator exists.
2. **CPU.** We can cap CPU **time** (cgroups) but not emulate 4× Cortex-A57 at
   1.02 GHz. The host cores are a different microarchitecture and clock, and the
   game is WebAssembly that JIT-compiles to the **host** ISA either way.
3. **OS / memory bandwidth / thermals.** The container shares the host kernel
   (no L4T Ubuntu + Xorg + EmulationStation stack), and there is no portable way
   to model 25.6 GB/s LPDDR4 or Tegra GPU clock throttling.

## What it does enforce

| Cabinet spec | How it's faked | How faithful |
|---|---|---|
| 4 GB LPDDR4 | `ARCADE_MEMORY` (default **8g**, i.e. max; `--strict` uses 4g) | Deliberately maxed by default; `--strict` for the cabinet figure. |
| 4× Cortex-A57 perf cluster | cgroup CPU quota; `ARCADE_CPU_QUOTA` default `800000` (~8 cores; `--strict`/`400000` = 4) | **Count/time only** — a throttle, not a clock. |
| Maxwell GPU | Software renderer (no GPU): **llvmpipe** in the kiosk, **SwiftShader** for headless checks | **Approximation.** Not a Maxwell, but llvmpipe runs PolyTrack ~30 fps at 360p. |
| 720p output | `ARCADE_KIOSK_RES` (default **640x360**, max; `--strict` uses 1280x720) + canvas assertion | Maxed by default for usability. |
| Offline cabinet | `--network=none` in `--check` | **Good.** |

**Max is the default:** `run.sh` and Compose run the container at its ceiling
(8 cores / 8g / 640×360, llvmpipe) so 3D games are usable; `--strict` (or
`--profile strict`) restores the cabinet profile. Env vars override either.

### Why a software renderer?

Docker Desktop (Mac/Windows) has no GPU passthrough, so the container always uses
a CPU rasterizer. **llvmpipe** (Mesa) is the kiosk default because it's ~2×
faster than SwiftShader for 3D; SwiftShader stays the default for the headless
checker.

### What is *not* faked

- Maxwell **driver behavior** — GPU-watchdog/context-loss quirks, ETC2 decoding,
  shader-compile stalls.
- CPU **clock/thermal** behavior. `ARCADE_CPU_QUOTA` limits CPU *time* (a
  throttle that stalls in bursts, not a 1.02 GHz clock). RAM and thread count
  are the reliable levers.
- **Memory bandwidth** (25.6 GB/s) — no portable cgroup lever.
- The A53 cluster and the ARM ISA (WASM compiles to the host ISA anyway).

## Measured gap (Apple M5, container on an 8-CPU / 10 GB VM)

With **llvmpipe** (the default) 3D becomes usable:

| Game | Kiosk 1280×720 | Kiosk 640×360 | Host browser (real GPU) |
|---|---|---|---|
| PolyTrack | ~10 fps | **~27–30 fps** | smooth (~60) |
| Dragon Jump | ~58 fps | ~60 fps | smooth (~60) |

Rendering **fewer pixels** is the main lever — software rasterization cost scales
with pixels. It's still not a Maxwell, but the 640×360 kiosk is a usable proxy
for the 3D games in the collection.

## What each path is good for

| Path | Good for | Not for |
|---|---|---|
| **Kiosk** `http://localhost:6080/` | Correctness: loads, COOP/COEP, threaded WASM, inputs, exit; **2D** games; CPU-bound behavior | 3D *feel* |
| **Host browser** `http://127.0.0.1:8123/` | Checking visuals / that it runs — your real GPU, unconstrained | Judging cabinet performance (no limits apply) |
| **The cabinet / a mid-range phone** | The real performance reference | — |

## The best proxy for *feel*: a mid-range phone

The [contributor checklist](../../docs/contributor-performance-checklist.md)
already says it: *"If it runs smoothly on a mid-range phone browser, it will run
here."* A phone's Adreno/Mali/PowerVR GPU is far closer to the Tegra X1's Maxwell
than a software rasterizer is. Serve the build on your LAN and open it on the
phone to *feel* the target better than either container path.

## Approximating (not simulating)

- **CPU**: calibrate `ARCADE_CPU_QUOTA` against the cabinet — run the cabinet's
  frame-time test ([perf plan](../../docs/switch-arcade-perf-plan.md)), then
  lower the quota until the container's numbers roughly match. It's a throttle,
  not a clock.
- **GPU**: not calibratable — llvmpipe/SwiftShader's gap varies per game and
  can't be mapped to Maxwell.
- **Responsiveness levers** (when the kiosk feels laggy):
  - The **noVNC stream** (input/display latency) competes with the renderer for
    CPU; it's tuned with `x11vnc -threads -noxdamage -ncache 0 -wait 5 -defer 5`
    and a fast noVNC landing page.
  - The **resolution** is the biggest lever (`ARCADE_KIOSK_RES`).
  - The **renderer** (`ARCADE_RENDERER`) and the **CPU/RAM** knobs add headroom.

## Pushing the ceiling (the best the container can do)

The container can never exceed the **Docker VM**. Raise the VM first:

```bash
# colima — restarts the VM (containers stop; image + volumes persist)
colima stop && colima start --cpu 8 --memory 10
# Docker Desktop: Settings → Resources → CPUs / Memory
```

Then run maxed (the default):

```bash
docker/run.sh --library                 # max by default
# cabinet-faithful instead:
docker/run.sh --strict --library
```

Even maxed, it's still a software rasterizer — this raises the *container's*
ceiling, not a Maxwell match. It's enough for PolyTrack ~30 fps (640×360) and
Dragon Jump ~60 fps.

## What's reused verbatim

| Path | Source |
|---|---|
| `webgame-server.py` | [`../scripts/webgame-server.py`](../../scripts/webgame-server.py) — COOP/COEP, `.wasm`/`.pck` MIME, `.br`/`.gz` sidecars, `no-store`. (One added line: a `WEBGAME_BIND` env var, default `127.0.0.1`, so the container can bind `0.0.0.0` in library mode.) |
| `exit-server.py` | [`../scripts/exit-server.py`](../../scripts/exit-server.py) — port `8123`; powers in-game Quit buttons. |
| `itch-watcher.py` | [`../scripts/itch-watcher.py`](../../scripts/itch-watcher.py) — the collection pull used by `--sync`. |
| Chromium flags | Ported from [`../scripts/launch-web-game.sh`](../../scripts/launch-web-game.sh). |

`gamepad-bridge.py` is **not** run (needs `/dev/uinput` + a physical Joy-Con).
Keyboard is what the game sees anyway, so typing in the noVNC window exercises
the same game-facing contract. An in-game Quit calling
`http://127.0.0.1:8123/exit` ends the session, because Chromium runs *inside* the
container.

## Bottom line

Use the container for **"does it behave on the cabinet"** (contract/2D), your
**host browser** for **"does it look right"**, and **real hardware** (cabinet or
a mid-range phone) for **"does it perform"**. The container is not, and cannot
be, a Switch emulator.
