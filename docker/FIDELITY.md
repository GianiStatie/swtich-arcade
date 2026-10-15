# Can the container simulate the Switch's hardware?

**Short answer: no — not faithfully.** Only real Tegra X1 hardware (the cabinet
itself, or a close ARM device) can. This page explains the walls and what to use
instead, so the two paths aren't mistaken for each other.

## The three walls

1. **GPU.** Docker Desktop / colima give the container **no GPU** on macOS, so
   WebGL runs on a **software rasterizer** — **llvmpipe** by default (~2× faster
   for 3D; `ARCADE_RENDERER=swiftshader` to fall back). There is no host-GPU
   passthrough here, and no Maxwell/Tegra driver emulator exists.

2. **CPU.** We can cap CPU **time** (cgroups) but not emulate a 4× Cortex-A57 at
   1.02 GHz. The host cores are a different microarchitecture and clock, and the
   game is WebAssembly that JIT-compiles to the **host** ISA either way.

3. **OS / memory bandwidth / thermals.** The container shares the host kernel
   (no L4T Ubuntu + Xorg + EmulationStation stack), and there is no portable way
   to model 25.6 GB/s LPDDR4 or Tegra GPU clock throttling.

## Measured gap (Apple M5, container on an 8-CPU / 10 GB VM)

The kiosk now uses **llvmpipe** (Mesa) by default — ~2× faster than SwiftShader
for 3D. That's what makes 3D usable:

| Game | Kiosk 1280×720 | Kiosk 640×360 | Host browser (real GPU) |
|---|---|---|---|
| PolyTrack | ~10 fps | **~27–30 fps** | smooth (~60) |
| Dragon Jump | ~58 fps | ~60 fps | smooth (~60) |

So with llvmpipe the kiosk is close to the Switch's ~30 fps for PolyTrack at
640×360 (and Dragon Jump is smooth either way). Rendering **fewer pixels** is
the main lever — software rasterization cost scales with pixels. It's still not
a Maxwell, but it's a usable proxy for the 3D games in the collection.

## What each path is actually good for

| Path | Good for | Not for |
|---|---|---|
| **Kiosk** `http://localhost:6080/` | Correctness: loads, COOP/COEP, threaded WASM, inputs, exit; **2D** games; CPU-bound behavior | 3D *feel* (SwiftShader is far too slow) |
| **Host browser** `http://127.0.0.1:8123/` | Checking visuals / that it runs — on your real GPU, unconstrained | Judging cabinet performance (no limits apply) |
| **The cabinet / a mid-range phone** | The real performance reference | — |

## The best proxy for *feel*: a mid-range phone

The [contributor checklist](../docs/contributor-performance-checklist.md) already
says it: *"If it runs smoothly on a mid-range phone browser, it will run here."*
A phone's Adreno/Mali/PowerVR GPU is far closer to the Tegra X1's Maxwell than
SwiftShader is. Point the phone's browser at the same build (serve it on your
LAN) to *feel* the target far better than either container path.

## Approximating (not simulating)

- **CPU**: you can get close on CPU-bound work by *calibrating* `ARCADE_CPU_QUOTA`
  against the cabinet — run the cabinet's frame-time test
  ([perf plan](../docs/switch-arcade-perf-plan.md)), then lower the quota until
  the container's numbers roughly match. It's a throttle, not a clock.
- **GPU**: not calibratable. SwiftShader's gap varies per game and can't be
  mapped to Maxwell.

## Pushing the ceiling (the best the container can do)

The container can never exceed the **Docker VM**. Raise the VM first:

```bash
# colima — restarts the VM (containers stop; image + volumes persist)
colima stop && colima start --cpu 8 --memory 10
# Docker Desktop: Settings → Resources → CPUs / Memory
```

Then run the kiosk — **maxed is the default** (more CPU/RAM + a 640×360 kiosk):

```bash
docker/run.sh --library                 # max by default
# or: docker compose up library
# cabinet-faithful instead:
docker/run.sh --strict --library
# or: docker compose --profile strict up library-strict
```

Individual knobs: `ARCADE_CPU_QUOTA`, `ARCADE_MEMORY`, `ARCADE_KIOSK_RES`
(e.g. `ARCADE_KIOSK_RES=960x540`), `ARCADE_RENDERER` (`llvmpipe` default /
`swiftshader`). The live status page (<http://127.0.0.1:8123/>) shows the limits
actually applied.

Even maxed, it's still a software rasterizer (no GPU) — this raises the
*container's* ceiling, not a Maxwell match. But it's enough to run PolyTrack at
~30 fps (640×360) and Dragon Jump at ~60 fps.

## Bottom line

Use the container for **"does it behave on the cabinet"** (contract/2D), use your
**host browser** for **"does it look right"**, and use **real hardware** (cabinet
or a mid-range phone) for **"does it perform"**. The container is not, and cannot
be, a Switch emulator.
