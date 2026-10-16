# Switch Arcade Brain — Current Setup

Notes for the current, working setup on the Switch. This documents what was
configured in the latest session (SSH, USB internet, RetroPie, Web Games
system, itch.io pull pipeline, WebGL fix, shader cache persistence, Openbox
kiosk, force-quit mechanism).

> The older planning/archive material lives in `archive/`. This folder is the
> live, current state.

## Contents

- [Web Games setup](web-games-setup.md) — what was set up and how to reproduce it.
- [Troubleshooting](troubleshooting.md) — WebGL context loss, shader-cache delay, exit issues, and other fixes.
- [Performance plan](switch-arcade-perf-plan.md) — the three tiers: game build, arcade launch, native ARM.
- [Native ARM tier](native-arm-tier.md) — running Godot web exports natively (design).
- [Contributor performance checklist](contributor-performance-checklist.md) — shareable guidance for people shipping games.
- [Multi-player arcade panels](multi-controller-panels.md) — design/handoff for the two added USB-encoder panels (P1/P2 as corrected virtual controllers); **not implemented**, discovery pending.
- [Arcade contract simulator](../docker/README.md) — Docker image to test a web build against the cabinet's software contract, and a library mode that syncs the itch collection into a browsable game menu (not a hardware emulator). How to run it: [`docker/docs/RUNNING.md`](../docker/docs/RUNNING.md).

## Deployed files

| Path (on this repo) | Deployed to (on Switch) | Purpose |
|---|---|---|
| `scripts/launch-es.sh` | `~/scripts/launch-es.sh` | Launch ES in kiosk mode (Konami code unlocks admin UI) |
| `scripts/uimode-watcher.py` | `~/scripts/uimode-watcher.py` | Forces ES restart on Konami unlock so the RetroPie menu reappears |
| `scripts/launch-web-game.sh` | `~/scripts/launch-web-game.sh` | Launch a web game in Chromium kiosk |
| `scripts/webgame-server.py` | `~/scripts/webgame-server.py` | Per-game HTTP server (started by `launch-web-game.sh`): no-store, COOP/COEP, `.wasm` MIME, `.br`/`.gz` sidecar serving |
| `scripts/exit-server.py` | `~/scripts/exit-server.py` | HTTP on `:8123`; powers in-game Quit buttons (`/exit`) |
| `scripts/exit-to-es.sh` | `~/scripts/exit-to-es.sh` | Kill Chromium + relaunch ES |
| `scripts/gamepad-bridge.py` | `~/scripts/gamepad-bridge.py` | Joy-Con → keyboard bridge + Start+Select force-quit + Start+Select+B panic reboot |
| `scripts/sync-itch-games.sh` | `~/scripts/sync-itch-games.sh` | Manual re-sync of games from `itch-games.yaml` (fallback) |
| `scripts/download-from-itch.sh` | `~/scripts/download-from-itch.sh` | Fetch a named upload from itch.io via API |
| `scripts/itch-watcher.py` | `~/scripts/itch-watcher.py` | Poll the itch collection; auto-install updates / prune / restart ES |
| `config/systemd/user/itch-watcher.service` | `~/.config/systemd/user/itch-watcher.service` | User service running the watcher (enabled + linger) |
| `scripts/arcade-perf-mode.sh` | `~/scripts/arcade-perf-mode.sh` | nvpmodel + CPU governor to performance |
| `config/itch-games.yaml` | `~/arcade_games/itch-games.yaml` | List of games to pull |
| `config/openbox-autostart` | `~/.config/openbox/autostart` | Openbox session autostart (perf + exit-server + gamepad-bridge + uimode-watcher + ES via launch-es.sh) |
| `config/10-ignore-joycons.conf` | `/etc/X11/xorg.conf.d/10-ignore-joycons.conf` | libinput: ignore Joy-Cons as X pointer/keyboard (bridge handles input) |
| `config/themes/carbon-2021/TAGAP Games/theme.xml` | `/etc/emulationstation/themes/carbon-2021/TAGAP Games/theme.xml` | TAGAP Games theme overlay (badge logo, hides text) |
| `config/themes/carbon-2021/TAGAP Games/art/tagap.png` | `/etc/emulationstation/themes/carbon-2021/TAGAP Games/art/tagap.png` | TAGAP badge logo (8-bit transparent PNG) |

### Runtime packages

| Package | Purpose |
|---|---|
| `unclutter-xfixes` (+ `unclutter-startup`) | Hides the mouse cursor for the whole session via `/etc/X11/Xsession.d/90unclutter`; see [web-games-setup](web-games-setup.md#hiding-the-cursor-whole-session) |

### Session config edited in place (not from repo)

| File | Purpose |
|---|---|
| `/etc/default/unclutter` | `START_UNCLUTTER="true"`, `EXTRA_OPTS="--timeout 1 --start-hidden"` |

## Quick reference

- **SSH:** `ssh switch` (user `tagap`, key-based, over USB gadget networking).
  - USB link fix (Oct 6): the gadget interface name can change between ports
    (`enp7s0f3u2` on the current dock port); when a new default
    `Wired connection N` sticks in DHCP, set it static:
    `nmcli con mod "Wired connection 4" ipv4.method manual ipv4.addresses 192.168.55.100/24`
- **Add a game:** add it to the itch.io collection (e.g. *LimitTestArcade*,
  id 8014540) — the watcher installs it within ~1 minute of the next idle
  poll and restarts ES. No SSH needed.
- **Update a game:** re-upload the web.zip on itch.io — same flow as adding.
- **Manual sync fallback:** edit `config/itch-games.yaml`, run
  `~/scripts/sync-itch-games.sh --restart-es` on the Switch.
- **Controls in games:** the Joy-Cons are read by `gamepad-bridge.py` and
  injected as keyboard keys (D-pad → arrows, A → Space, B → R). See
  [Web Games setup](web-games-setup.md) for the mapping.
- **Exit a game:** press **Start + Select** (handled by the gamepad bridge,
  works for any game). If the game is frozen solid, **Start + Select + B**
  reboots the cabinet. The in-game QUIT button does **not** work for Godot web
  builds — see [Troubleshooting](troubleshooting.md) for why.
- **Shader cache:** persisted at `~/.cache/arcade/` (shared across all web games).
- **Display:** sddm autologin → Openbox → ES (no desktop shell).

## Updating the logo

The TAGAP Games badge is a transparent PNG at
`config/themes/carbon-2021/TAGAP Games/art/tagap.png` (deployed to
`/etc/emulationstation/themes/carbon-2021/TAGAP Games/art/tagap.png`).

To change it:

1. **Edit the source** `TAGAP_Badge.svg` (in the repo root) in Inkscape, or
   replace it with your own artwork.
2. **Rasterize to an 8-bit transparent PNG** (ES's SDL_image can silently fail
   on 16-bit PNGs, and its SVG renderer can't handle complex clip-paths):
   ```bash
   magick -background none -density 600 TAGAP_Badge.svg \
     -resize 1024x512 -depth 8 \
     "config/themes/carbon-2021/TAGAP Games/art/tagap.png"
   ```
   Keep it roughly **2:1** aspect (the carousel logo slot is `576×134`).
3. **Deploy** to the Switch:
   ```bash
   scp "config/themes/carbon-2021/TAGAP Games/art/tagap.png" switch:/tmp/tagap.png
   ssh switch 'echo 1234 | sudo -S -p "" cp /tmp/tagap.png \
     "/etc/emulationstation/themes/carbon-2021/TAGAP Games/art/tagap.png"'
   ```
4. **Restart ES** to pick it up:
   ```bash
   ssh switch 'echo 1234 | sudo -S -p "" systemctl restart sddm'
   ```

The theme overlay (`config/themes/carbon-2021/TAGAP Games/theme.xml`) already
points at `./art/tagap.png`, so no theme edit is needed for a logo swap.
