# Switch Arcade — Tegra Performance Plan (Three Tiers)

How games are made to run as well as possible on the DIY arcade
([GianiStatie/swtich-arcade](https://github.com/GianiStatie/swtich-arcade)):
RetroPie/L4T Linux brain on a Switch, web builds served in Chromium kiosk,
pulled from itch.io.

## Context & goals

- Contributors ship **one HTML5 zip** (Unity WebGL, Godot web, plain JS — engine-agnostic).
- Games run on the Switch's L4T Linux side in Chromium kiosk; contributors must **not**
  have to install toolchains, devkits, or export extra platforms.
- Goals: use the hardware (Tegra X1: 4× Cortex-A57 + Maxwell GPU) at full potential,
  keep the export process as easy as it is today (single HTML5 zip).

## The three tiers

| Tier | Scope | Implemented in | Effort | Status |
|---|---|---|---|---|
| **1. Game build** | What the exported game does (resolution, threading, flags, exit path) | Each game's repo (for us: `dragon-jump-remaster`) | Contributor-side; some steps need a template rebuild | Quit path + threads implemented (2026-10-12); cabinet verification pending |
| **2. Arcade launch** | Hardware clocks, local server, Chromium flags, cache warm-up | This repo (scripts + config) | Host-side, ~a day | Server patch implemented; deploy to cabinet pending (see below) |
| **3. Native ARM tier** | Run Godot web exports on a native ARM64 Godot template (reused `.pck`) | This repo (launcher + template cache) | Multi-day, Godot-only | Design: [native-arm-tier.md](native-arm-tier.md) |

Sequencing: **2 → 1 → 3.** Tier 2's server headers unblock tier 1's threads; tier 1
measurements then tell us whether tier 3 is worth it (threads already recovers most of
the multi-core win — tier 3's remaining edge is startup and glue overhead).

## Why "convert the HTML build to native" isn't a thing

A web build is not just WASM. It is WASM + the browser-side JS glue
(Emscripten runtime: WebGL context negotiation, FS shims, audio workers, etc.).
AOT-compiling the `.wasm` to ARM64 would still require re-implementing every
browser-side import the game calls — that's a browser, not a script. There is no
general-purpose HTML→native translator; the web build *is* the portable contract.

Tier 3 is not a translator: it **recompiles the engine** as a native ARM64 template
and reuses the web export's `.pck` data. See [native-arm-tier.md](native-arm-tier.md).

---

## Tier 1 — The game build

What makes an export fast is documented as a shareable checklist:
[contributor-performance-checklist.md](contributor-performance-checklist.md)
(internal resolution, threading, audio, per-frame allocations, engine-specific
export settings, the quit contract).

Worked example — Dragon Jump (Godot 4.6, encrypted web export):

- **Already good:** 360p internal render upscaled to 720p; Compatibility renderer
  (`rendering_method.web`); `max_fps=60`; marketing assets excluded from the pck;
  custom HTML shell; input contract mapped (arrows / Space / R / Esc / Tab); exit
  endpoint implemented 2026-10-12 (`main_menu.gd` fetches `127.0.0.1:8123/exit` on web).
- **Threads ON** (2026-10-12). The threaded custom web template is built once by CI
  (`build-web-template.yml`: stripped, encrypted, Emscripten 4.0.11) and published as
  `web_release.zip`; `build.yml` injects it and `variant/thread_support=true`. The
  remaining chain:
  1. Deploy the tier-2 server patch to the cabinet (COOP/COEP are what make threads boot).
  2. itch.io build: Embed Options → SharedArrayBuffer support (moves it to
     `html.itch.zone`; old local saves don't follow).
  3. Verify: boot + frame time on the cabinet.
  Rollback: flip `variant/thread_support=false` — the nothreads template is still injected.
- **VRAM texture compression flags** (`for_desktop=false, for_mobile=true`): a no-op
  for this game — no texture uses VRAM-compressed import mode. (The checklist's
  recommendation of Desktop ON / Mobile OFF stands for future VRAM-compressed art.)

Measurement: `src/tests/test_frame_time.gd` (avg/max frame time over 30 s of
gameplay, 1-1) run on the cabinet, plus boot-to-menu timing. Run before/after each
change; keep the numbers in the relevant PR/commit.

---

## Tier 2 — Arcade launch (host-side)

All items must gracefully fall back to today's behavior if anything fails.

### Already done

- `nvpmodel -m 5` (Perf All, no overclock) + CPU governor pinned to `performance`
  (`scripts/arcade-perf-mode.sh`). Note: mode 6 (overclock) hard-froze the system
  and stays off.
- Chromium kiosk with persistent profile/cache (`~/.cache/arcade/`), so shader and
  WASM caches survive reboots (`launch-web-game.sh`).
- `--disable-gpu-watchdog`, `--use-angle=gl`, `--enable-gpu-rasterization`,
  `--ignore-gpu-blocklist`.
- Exit server (`exit-server.py`, port 8123) + Joy-Con → keyboard bridge with
  Start+Select force-quit (`gamepad-bridge.py`).
- Per-game HTTP server with `no-store` headers (`webgame-server.py`) — deliberate:
  it fixed stale pck/wasm after game updates.
- Cross-origin isolation + sidecar serving in `webgame-server.py` (2026-10-12):
  every response sends COOP/COEP, `.wasm`/`.pck` get correct MIME types, and
  `.br`/`.gz` sidecar files (shipped inside the game's zip by the game repo's CI —
  the Switch never compresses anything) are served with `Content-Encoding` +
  `Vary: Accept-Encoding`. Implemented; pending deploy to the cabinet.

### Open items

1. **Full hardware unlock** (`scripts/arcade-perf-mode.sh`)
   - GPU devfreq governor to `performance` / max frequency.
   - EMC/memory clock maxed for the session.
   - Probe the actual devfreq/EMC paths at runtime (they differ per L4T build) and
     log results to a file; add findings to `troubleshooting.md`.

2. **Smart local server — remaining parts**
   - Range request support (big `.paks`).
   - **Cache-header redesign (design decision needed).** `no-store` fixed staleness
     but also throws away the warm V8/HTTP caches on every launch. Preferred:
     `Cache-Control: no-cache` + `ETag` revalidation (cheap 304s, caches survive), or
     an immutable versioned directory per sync. Verify the stale-update scenario
     explicitly before switching away from `no-store`.

3. **Chromium launch tuning** (`scripts/launch-web-game.sh`)
   - `--disable-gpu-vsync` (arcades don't care about tearing).
   - Compare `--use-angle=gl` vs `--use-angle=gl-egl`.
   - Optional: `--canvas-oop-rasterization`.
   - `--autoplay-policy=no-user-gesture-required` (removes the click-to-enable-audio
     splash requirement for every engine).
   - V8/WASM experiment: `--js-flags` (e.g. `--no-liftoff` trades slower startup for
     better peak code on long sessions) — measure before keeping.
   - **Per-game flag overrides** via `itch-games.yaml` (`chromium_flags: [...]`).

4. **Cache warm-up** — new `scripts/warmup-games.sh`
   - After each sync, auto-launch each new game once for ~30–45 s, then kill it.
   - Pre-fills the shared shader cache and the V8/WASM code cache, so the first
     real launch has no mid-load stall.
   - Must run on-screen (real GL; xvfb won't warm the Tegra driver) — a
     maintenance-window step, documented in `web-games-setup.md`.

5. **Docs/ops**
   - Mark tier-2 items 1–3 as "do once per cabinet" in `web-games-setup.md`.
   - Document the warm-up step and the new server behavior in
     `troubleshooting.md` / `README.md`.

### Risks / to verify on hardware

- Exact GPU devfreq + EMC paths for the L4T build (probe at runtime).
- `--disable-gpu-vsync` stability; best ANGLE mode per engine.
- Godot/Unity threaded-WASM stability per engine version.
- Whether ETag revalidation fully prevents stale pck/wasm (test an update cycle).

---

## Tier 3 — Native ARM tier (Godot only)

Run a Godot web export's `.pck` on a **natively compiled ARM64 Godot template** of
the exact same engine version — no browser, no WASM. Contributor-visible behavior
(version match, encryption, engine limits) is in the
[contributor checklist](contributor-performance-checklist.md); full host-side
design is in [native-arm-tier.md](native-arm-tier.md).

---

## Open

- Tier 2 implementation lives here (scripts + config + deploy doc), not in the game repo.
- Tier 1's threads step needs the threaded custom web template; its build recipe is
  documented in the game repo's anti-piracy notes.
- Contributor-side guidance lives in
  [contributor-performance-checklist.md](contributor-performance-checklist.md) —
  a shareable, link-ready checklist for people exporting games
  (itch page blurb / link, covering the input contract, engine-specific export
  settings for Godot 4 and Unity, the exit-endpoint pattern, and the optional
  native path).
