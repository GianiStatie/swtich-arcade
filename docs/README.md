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
- [Multi-player arcade panels](multi-controller-panels.md) — design/handoff for the two added USB-encoder panels (P1/P2 as standard gamepads); **implemented** — panels are remapped for web games by a shim injected into served pages.
- [Panel input investigation](panel-input-investigation.md) — field notes from fixing the panel inputs: what was tried (uinput, udev, shims), what failed and why, environment quirks, and the reusable test harness in `tools/padtest/`.
- [Arcade contract simulator](../docker/README.md) — Docker image to test a web build against the cabinet's software contract, and a library mode that syncs the itch collection into a browsable game menu (not a hardware emulator). How to run it: [`docker/docs/RUNNING.md`](../docker/docs/RUNNING.md).

## The two cabinets

Both units are identical Switch-based cabinets with the same hostname
(`tagap-laptop`), so mDNS (`tagap-laptop.local`) is ambiguous. They are told
apart by name:

| | **hardware mode** | **software mode** |
|---|---|---|
| Board serial (`/proc/device-tree/serial-number`) | `NXO-2EDABE7E-30080F` | `NXO-30D61FFC-30020F` |
| WiFi MAC (`/sys/class/net/wlp1s0/address`) | `98:b6:e9:25:41:83` | `98:b6:e9:29:e0:05` |
| WiFi IP (static, set 2026-10-16) | `192.168.50.219` | `192.168.50.75` |
| Panels (both docks since 2026-10-16) | 2× DragonRise encoders (USB `0079:0006`) on the dock hub; raw button order **scrambled** — remapped by the in-page web shim | 2× DragonRise encoders on the dock hub; raw button order **standard** — shim is still injected but does not remap (`panel-wiring.conf` = `standard`) |

The old way to tell the units apart was the presence of panels; since
2026-10-16 both cabinets have their two panels connected. What still differs
is the panels' raw button wiring (the two cabinets' encoder boards happen to
be different): the hardware cabinet's boards are scrambled and rely on the
shim, the software cabinet's are standard-ordered. See
[Multi-player arcade panels](multi-controller-panels.md) §13 and the
`panel-wiring.conf` entry below.

Identify whichever unit you're on in one line:

```bash
cat /proc/device-tree/serial-number; echo
cat /sys/class/net/wlp1s0/address
lsusb | grep 0079    # two hits = panels plugged in (docked; both cabinets)
```

### Connecting from a new PC

Both units are always reachable over the home WiFi at fixed addresses (made
static on the units themselves, so they no longer move with DHCP):

| Alias | Address | Unit |
|---|---|---|
| `switch-hw` | `192.168.50.219` | hardware mode |
| `switch-sw` | `192.168.50.75` | software mode |

Set up a new machine in two steps:

1. Add the aliases to `~/.ssh/config` (or just use the addresses directly):

   ```
   Host switch-hw
       HostName 192.168.50.219
       User tagap
   Host switch-sw
       HostName 192.168.50.75
       User tagap
   ```

2. Install your SSH key so you stop typing the password (asked once):

   ```bash
   ssh-copy-id switch-hw
   ssh-copy-id switch-sw
   ```

   Password auth also works: user `tagap`, same password as `sudo` on the
   cabinets. macOS needs no extra setup (`ssh-copy-id` ships with it).

If an address ever stops responding, the static profile may have been lost
(e.g. profile re-created); find the unit on the router by MAC
(`98:b6:e9:25:41:83` / `98:b6:e9:29:e0:05`) and re-apply the address. Adding
DHCP reservations for those two MACs on the router is a good belt-and-braces
option.

### WiFi fallback (mobile hotspot)

Both cabinets have a saved profile for the phone hotspot
(`Botocera`, added 2026-10-16) with `autoconnect-priority: -5`, so they join it
automatically whenever no better known network is in range (home `10` >
"Viata cu Digi" `0` > ClujStartupGuest `-1` > hotspot `-5`; the hotspot is
only used when it is the sole known network available). The SSID is
**case-sensitive** — the profile was first saved as `botocera` (as casually dictated) and had to be
corrected to the hotspot's actual `Botocera`. To repeat this on another unit:

```bash
echo 1234 | sudo -S -p "" nmcli connection add type wifi con-name Botocera \
  ssid Botocera wifi-sec.key-mgmt wpa-psk wifi-sec.psk '<hotspot password>' \
  connection.autoconnect yes connection.autoconnect-priority -5
```

Networking quirk on this image (Ubuntu 24.04 + netplan↔NM integration):
`/etc/NetworkManager/system-connections/` is empty by design — every NM
connection is mirrored into a root-only `/etc/netplan/90-NM-<uuid>.yaml`
(persists across reboots) and materialized at runtime into
`/run/NetworkManager/system-connections/`. So create/edit profiles with
`nmcli` and they persist automatically; `netplan generate` may warn if any
`/etc/netplan/*.yaml` isn't `600` (all are, as of 2026-10-16). For WiFi scans
use `nmcli dev wifi` (or `wpa_cli -i wlp1s0 scan`/`scan_results` for the raw
supplicant view) — note `iw` is **not installed** on the units. Both units
scan 2.4 GHz (incl. ch 12–13) and 5 GHz fine.

### WiFi: ClujStartupGuest (co-working space)

Added 2026-10-16 to **both** units with `autoconnect-priority: -1` (see the
priority order above). The AP is WPA2/WPA3 *mixed*, so the profile uses plain
`wpa-psk` — no SAE needed. Created with the same pattern as the hotspot:

```bash
echo 1234 | sudo -S -p "" nmcli connection add type wifi con-name ClujStartupGuest \
  ssid ClujStartupGuest wifi-sec.key-mgmt wpa-psk wifi-sec.psk 'CSGuest2025' \
  connection.autoconnect yes connection.autoconnect-priority -1
```

Addresses are DHCP (`192.168.11.x`, gateway `.1`) — nothing static, so they
drift. Live leases 2026-10-16: hardware mode `192.168.11.53`, software mode
`192.168.11.41`. SSH from the work PC is key-based (`id_ed25519_arcade`;
password `1234` still works as fallback) with aliases `switch-cluj`
(hardware) / `switch-cluj-sw` (software).

**USB caveat when both units are around:** they present the *same* gadget
network (`192.168.55.1`, PC side `192.168.55.100/24`) but with *different*
host keys. Cable them one at a time, and give the USB link its own throwaway
`UserKnownHostsFile` (or `accept-new` on a first connect) — otherwise the
known_hosts entry from one unit fails verification for the other.

## Deployed files

| Path (on this repo) | Deployed to (on Switch) | Purpose |
|---|---|---|
| `scripts/launch-es.sh` | `~/scripts/launch-es.sh` | Launch ES in kiosk mode (Konami code unlocks admin UI) |
| `scripts/uimode-watcher.py` | `~/scripts/uimode-watcher.py` | Forces ES restart on Konami unlock so the RetroPie menu reappears |
| `scripts/launch-web-game.sh` | `~/scripts/launch-web-game.sh` | Launch a web game in Chromium kiosk; each game gets a stable per-game port so Godot service workers/caches stay isolated |
| `scripts/webgame-server.py` | `~/scripts/webgame-server.py` | Per-game HTTP server (started by `launch-web-game.sh`): no-store, COOP/COEP, `.wasm` MIME, `.br`/`.gz` sidecar serving; injects the gamepad shim into every HTML page (see `panel-wiring.conf` below) |
| `scripts/arcade-pad-shim.js` | `~/scripts/arcade-pad-shim.js` | In-page gamepad shim: remaps arcade panel buttons on scrambled-wiring cabinets and hides the unused Combined Joy-Cons from the page (served/injected by `webgame-server.py`) |
| `scripts/exit-server.py` | `~/scripts/exit-server.py` | HTTP on `:8123`; powers in-game Quit buttons (`/exit`) |
| `scripts/exit-to-es.sh` | `~/scripts/exit-to-es.sh` | Kill Chromium + relaunch ES |
| `scripts/gamepad-bridge.py` | `~/scripts/gamepad-bridge.py` | Joy-Con → keyboard bridge + Start+Select force-quit + Start+Select+B panic reboot; also watches the arcade panels passively (no grab) for the same combos, with panel button codes selected by `panel-wiring.conf` |
| `scripts/sync-itch-games.sh` | `~/scripts/sync-itch-games.sh` | Manual re-sync of games from `itch-games.yaml` (fallback) |
| `scripts/download-from-itch.sh` | `~/scripts/download-from-itch.sh` | Fetch a named upload from itch.io via API |
| `scripts/itch-watcher.py` | `~/scripts/itch-watcher.py` | Poll the itch collection; auto-install updates / prune / restart ES |
| `config/systemd/user/itch-watcher.service` | `~/.config/systemd/user/itch-watcher.service` | User service running the watcher (enabled + linger) |
| `scripts/arcade-perf-mode.sh` | `~/scripts/arcade-perf-mode.sh` | nvpmodel + CPU governor to performance |
| `config/itch-games.yaml` | `~/arcade_games/itch-games.yaml` | List of games to pull |
| `config/openbox-autostart` | `~/.config/openbox/autostart` | Openbox session autostart (stale-session reaper + perf + exit-server + gamepad-bridge + uimode-watcher + HDMI volume + ES via launch-es.sh) |
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

### Per-cabinet state (not from repo)

| File | Purpose |
|---|---|
| `~/scripts/panel-wiring.conf` | One word selecting the panels' raw button order: `standard` on the software-mode cabinet (pads are already standard-ordered — the shim is injected but does not remap); the file is **absent** on the hardware-mode cabinet, which keeps the default `scrambled` (shim remaps). Read by `webgame-server.py` and `gamepad-bridge.py`; see [Multi-player arcade panels](multi-controller-panels.md) §13 |

## Quick reference

- **SSH:** over WiFi — `ssh switch-hw` (hardware mode) / `ssh switch-sw`
  (software mode), user `tagap`, key-based (password fallback). `ssh switch`
  (`192.168.55.1`) is the legacy USB gadget link and only exists while the unit
  is cabled to the PC in device mode.
  - At a co-working space: `ssh switch-cluj` (hardware) / `ssh switch-cluj-sw`
    (software) — DHCP leases, see the "ClujStartupGuest" WiFi section above.
  - USB link fix (Oct 6): the gadget interface name can change between ports
    (`enp7s0f3u2` on the current dock port); when a new default
    `Wired connection N` sticks in DHCP, set it static:
    `nmcli con mod "Wired connection 4" ipv4.method manual ipv4.addresses 192.168.55.100/24`
- **Add a game:** add it to the itch.io collection (e.g. *LimitTestArcade*,
  id 8014540) — the watcher installs it on the next idle poll (default
  ~5 minutes) and restarts ES. No SSH needed.
- **Update a game:** re-upload the web.zip on itch.io — same flow as adding.
- **Manual sync fallback:** edit `config/itch-games.yaml`, run
  `~/scripts/sync-itch-games.sh --restart-es` on the Switch.
- **Controls in games:** the Joy-Cons are read by `gamepad-bridge.py` and
  injected as keyboard keys (D-pad → arrows, A → Space, B → R). The page shim
  hides the unused Joy-Con gamepad, so Unity games do not log a device-creation
  error or open their development console. See
  [Web Games setup](web-games-setup.md) for the mapping. The arcade panels
  reach games as standard-mapped controllers — remapped in-page by the shim on
  the hardware cabinet, already standard-ordered on the software cabinet.
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
