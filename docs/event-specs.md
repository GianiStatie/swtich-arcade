# Event Specs — TAGAP Games Arcade

What to expect from the arcade cabinets at the event. This is the info for
people bringing games, so they know what the hardware can run, how input works,
and how to test their build.

## Hardware (per unit)

| Component | Spec |
|---|---|
| SoC | NVIDIA Tegra X1 (T210) |
| CPU | 4× ARM Cortex-A57 @ 1.02 GHz + 4× ARM Cortex-A53 |
| GPU | Maxwell, 256 CUDA cores, up to 768 MHz |
| RAM | 4 GB LPDDR4 (25.6 GB/s) |
| Display | 720p native (up to 1080p output) |
| OS | L4T Ubuntu + RetroPie/EmulationStation, Chromium kiosk |
| Graphics API | WebGL 2.0 (Chromium, GPU accelerated) |

Two cabinets will be at the event, both identical.

## Game compatibility

**Format: HTML5 web builds only.** The arcade runs games in a Chromium kiosk
browser. Bring a web export — no native/desktop builds, no executables.

Supported engines / formats:

- Godot (HTML5 export)
- Unity (WebGL export)
- Construct / Phaser / plain JS / HTML5 canvas

### 2D games

Essentially unlimited. Any 2D web game runs well at 60fps.

### 3D games

WebGL 2.0, mobile-tier hardware. Think PS3 / Vita / mobile quality. Target
**720p** and 60fps. To stay safe:

- Low-poly meshes, simple materials/shaders
- Textures ≤ 2048px
- Avoid heavy post-processing, MSAA, and complex lighting
- Keep draw calls low; prefer batching

If it runs smoothly on a mid-range phone browser, it will run here.

## Input (per player)

Each player gets a custom control panel:

- **1× 8-way joystick**
- **8 buttons:** A, B, X, Y, RB, LB, RT, LT
- **4 custom buttons:** Start, Select, + 2 unassigned (available per-game)

Two players supported.

**Arcade panels → standard gamepads.** The web game server injects a small
remap shim into every page, so games can read the panels with the plain
Gamepad API and the standard button layout: Player 1 is gamepad index 0,
Player 2 is index 1.

| Panel control | Standard gamepad button |
|---|---|
| A / B / X / Y | 0 / 1 / 2 / 3 |
| LB / RB / LT / RT | 4 / 5 / 6 / 7 |
| Select / Start | 8 / 9 |
| custom L / custom R | 10 (L3) / 11 (R3) |
| Joystick | left stick axes 0 / 1 |

**Joy-Cons → keyboard.** The built-in Joy-Cons are read by a gamepad bridge
and injected as keyboard keys, so games can also (or instead) use standard
keyboard input. The page shim hides the unused Combined Joy-Cons from the
Gamepad API, so engines such as Unity do not try to create an unsupported
device and open a native development console:

| Control | Key |
|---|---|
| D-pad | Arrow keys |
| A | Space |
| B | R |
| X | Esc |
| Y | Tab |
| Start + Select | Exit game (returns to menu) |
| Start + Select + B | Panic reboot (if the game is frozen) |

The 2 extra custom buttons are unassigned by default — they can be mapped to
any key per game if needed.

## Testing your build

### 1. Test locally

Serve your web build over HTTP (Godot/Unity builds need HTTP, not `file://`):

```bash
python3 -m http.server 8124 --directory /path/to/your/build
```

Open `http://127.0.0.1:8124/index.html` in Chromium and verify it loads and
runs. Confirm the build has `index.html` at the root of the zip.

### 2. Add it to the arcade

Add the game to the itch.io collection (e.g. *LimitTestArcade*). The cabinet
polls the collection every minute and installs new/updated builds
automatically whenever nobody is playing; no SSH or manual sync is needed.

Manual fallback: add an entry to `config/itch-games.yaml` (or a direct zip
URL), then sync to both units:

```bash
~/scripts/sync-itch-games.sh --restart-es
```

The game appears in the **TAGAP Games** section of EmulationStation.

### 3. Verify input + exit

- Controls: joystick/buttons should map per the table above.
- Exit: **Start + Select** returns to the menu (works for any game).

> **Godot web builds:** the in-game QUIT button does **not** return to the menu
> (a Godot web-export limitation). Use **Start + Select** to exit.

## Quick reference

- **Add a game:** add it to the itch.io collection (auto-installs ≤1 min,
  while idle). Or: edit `itch-games.yaml`, run `sync-itch-games.sh --restart-es`.
- **Exit a game:** Start + Select (any game).
- **Troubleshooting:** see `docs/troubleshooting.md` (WebGL context loss, input
  lag, cursor, exit issues).
- **Full setup:** see `docs/web-games-setup.md`.
