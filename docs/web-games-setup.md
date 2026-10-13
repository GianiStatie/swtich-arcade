# Web Games Setup

How the Switch was configured to pull HTML5 web builds from itch.io and play
them in Chromium kiosk mode via EmulationStation.

## What was set up

1. **SSH restored** — `openssh-server` was missing on the Switch; reinstalled so
   `ssh switch` works over USB gadget networking.
2. **Internet over USB** — the Switch has no Wi-Fi; internet is shared from the
   PC over the USB link (NAT + default route + DNS).
3. **RetroPie installed** — via the L4T-Megascript (EmulationStation + RetroArch).
4. **TAGAP Games system** — a new `TAGAP Games` section in `es_systems.cfg` that
   launches HTML5 builds in Chromium kiosk.
5. **itch.io pull pipeline** — `sync-itch-games.sh` + `download-from-itch.sh` +
   `itch-games.yaml` + API key.
6. **WebGL context-loss fix** — added `--disable-gpu-watchdog` to the Chromium
   launch flags.
7. **Persistent shader cache** — moved the Chromium profile/cache from `/tmp`
   to `~/.cache/arcade/` so shaders survive reboots and are shared across games.

## Files deployed on the Switch

| Path | Purpose |
|---|---|
| `~/scripts/launch-web-game.sh` | Launch a web build in Chromium kiosk |
| `~/scripts/launch-es.sh` | Launch ES in kiosk mode; Konami code unlocks admin UI |
| `~/scripts/uimode-watcher.py` | Forces ES restart on Konami unlock so the RetroPie menu reappears |
| `~/scripts/exit-server.py` | HTTP on `:8123`; powers in-game Quit buttons (`/exit`) |
| `~/scripts/exit-to-es.sh` | Kill Chromium + http server, relaunch ES if needed |
| `~/scripts/gamepad-bridge.py` | Reads Joy-Cons via evdev → injects keyboard keys via uinput; grabs the device while a game runs; Start+Select force-quit |
| `~/scripts/sync-itch-games.sh` | Pull games from `itch-games.yaml` |
| `~/scripts/download-from-itch.sh` | Fetch a named upload from itch.io via API |
| `~/scripts/arcade-perf-mode.sh` | nvpmodel + CPU governor to performance |
| `~/arcade_games/itch-games.yaml` | List of games to pull |
| `~/arcade_games/web/<Name>/` | Extracted game builds (with `index.html`) |
| `~/arcade_games/downloads/` | Cached zips |
| `~/.config/itch_api_key` | itch.io API key (chmod 600) |
| `~/.config/openbox/autostart` | Openbox session: black bg, perf-mode, exit-server, gamepad-bridge, uimode-watcher, ES via launch-es.sh |
| `/etc/X11/xorg.conf.d/10-ignore-joycons.conf` | libinput: ignore Joy-Cons as X pointer/keyboard (bridge handles input) |
| `/etc/default/unclutter` + `unclutter-xfixes` | Hides the cursor for the whole session (`--timeout 1 --start-hidden`); see "Hiding the cursor (whole session)" |
| `/etc/emulationstation/es_systems.cfg` | Added the `TAGAP Games` system |
| `/etc/sddm.conf.d/10-arcade-openbox.conf` | sddm autologin to Openbox |
| `/usr/share/xsessions/openbox.desktop` | Openbox session entry |
| `/usr/share/X11/xorg.conf.d/50-joystick.conf.disabled` | Megascript X joystick→keyboard mapper (renamed to disable; see Troubleshooting) |
| `/usr/share/X11/xorg.conf.d/51-joystick-others.conf.disabled` | Megascript X joystick→keyboard mapper (renamed to disable; see Troubleshooting) |

## How to reproduce

### 1. Connect over USB

The Switch boots into L4T and connects to the PC via USB gadget networking.
The link is **fully static and persistent** (see
[Troubleshooting](troubleshooting.md#usb-ip-drops-on-reconnect) for details):
Switch = `192.168.55.1`, PC = `192.168.55.100` (NetworkManager connection
`Wired connection 3`, manual method). No manual IP setup needed. Quick check:

```bash
ping 192.168.55.1
```

SSH alias (`~/.ssh/config`):

```
Host switch
    HostName 192.168.55.1
    User tagap
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
```

### 2. Install openssh-server (if missing)

```bash
ssh switch 'sudo apt-get update && sudo apt-get install -y openssh-server && sudo systemctl enable --now ssh'
```

### 3. Share internet over USB

Done persistently (see
[Troubleshooting](troubleshooting.md#usb-ip-drops-on-reconnect) — sysctl
drop-in + firewalld masquerade on the PC). Only needed if rebuilding a PC
from scratch:

```bash
printf 'net.ipv4.ip_forward = 1\n' | sudo tee /etc/sysctl.d/99-arcade-usb-forward.conf
sudo firewall-cmd --permanent --zone=FedoraWorkstation --add-masquerade
sudo firewall-cmd --reload
```

On the Switch (default route + DNS):

```bash
sudo ip route add default via 192.168.55.100
echo "nameserver 1.1.1.1" | sudo tee /etc/resolv.conf
```

Verify: `ping 8.8.8.8` on the Switch.

### 4. Install RetroPie (via L4T-Megascript)

The Megascript is preinstalled on L4T Ubuntu. Run it and select **RetroPie**:

```bash
bash <( wget -O - https://raw.githubusercontent.com/cobalt2727/L4T-Megascript/master/core_refactor2.sh ) "gui"
```

### 5. Deploy the scripts + config

Copy the scripts to `~/scripts/` on the Switch and `chmod +x`:

```bash
scp scripts/*.sh scripts/*.py switch:~/scripts/
ssh switch 'chmod +x ~/scripts/*.sh ~/scripts/*.py'
```

Copy `config/itch-games.yaml` to `~/arcade_games/itch-games.yaml`.

Write the itch.io API key:

```bash
printf '%s' 'YOUR_API_KEY' > ~/.config/itch_api_key && chmod 600 ~/.config/itch_api_key
```

Install the evdev dependency for the gamepad bridge and (historically) the quit-watcher:

```bash
ssh switch 'sudo apt-get install -y python3-evdev'
```

### 6. Replace the desktop with Openbox

The Switch boots into KDE Plasma by default. To make ES the sole occupant of
the screen (no desktop behind it), switch the sddm session to Openbox.

Create `/usr/share/xsessions/openbox.desktop`:

```ini
[Desktop Entry]
Name=Openbox
Comment=Log in using the Openbox window manager
Exec=/usr/bin/openbox-session
Type=Application
```

Configure sddm to autologin to Openbox — `/etc/sddm.conf.d/10-arcade-openbox.conf`:

```ini
[Autologin]
User=tagap
Session=openbox.desktop
Relogin=true
```

Create `~/.config/openbox/autostart` (see `config/openbox-autostart`). It uses an
idempotent `start_once` helper so helpers are only started if not already
running (prevents duplicates across sddm restarts):

```bash
# Openbox autostart for arcade brain
xsetroot -solid black &

start_once() {
  local script="$1"; shift
  if ! pgrep -f "[s]cripts/${script}" >/dev/null 2>&1; then
    setsid "$@" "/home/tagap/scripts/${script}" </dev/null >/dev/null 2>&1 &
    disown 2>/dev/null || true
  fi
}

/home/tagap/scripts/arcade-perf-mode.sh &
start_once exit-server.py python3 -u
start_once gamepad-bridge.py python3 -u
emulationstation
```

On reboot: black screen → ES, no desktop shell.

### 7. Add the `TAGAP Games` system

Append to `/etc/emulationstation/es_systems.cfg`:

```xml
<system>
  <name>TAGAP Games</name>
  <fullname>TAGAP Games</fullname>
  <path>/home/tagap/arcade_games/web</path>
  <extension>.web .sh</extension>
  <command>/home/tagap/scripts/launch-web-game.sh %ROM%</command>
  <platform>ignore</platform>
  <theme>TAGAP Games</theme>
</system>
```

The system is displayed as **TAGAP Games** with the TAGAP badge logo. The theme
overlay lives at
`/etc/emulationstation/themes/carbon-2021/TAGAP Games/theme.xml` (includes the
base carbon-2021 theme and overrides the logo with `art/tagap.png`). The
gamelist lives at `~/.emulationstation/gamelists/TAGAP Games/gamelist.xml`.

> Note: the `<theme>` value must be **`TAGAP Games`** (matching the overlay
> folder name), not `carbon-2021` — ES resolves per-system themes at
> `themes/[ThemeSet]/[system.theme]/theme.xml`. If it's `carbon-2021`, ES looks
> for `carbon-2021/carbon-2021/theme.xml` (missing) and falls back to the base
> theme, showing the system name as text instead of the badge.

> Note: the logo is a **PNG** (`art/tagap.png`), not the raw SVG. ES's built-in
> SVG renderer can't handle the badge's complex clip-paths/transforms and draws
> nothing; ImageMagick rasterizes it to a transparent **8-bit** PNG first
> (`magick -background none -density 600 TAGAP_Badge.svg -resize 1024x512 -depth 8 ...`).
> 16-bit PNGs can also fail to load in SDL_image, so keep it 8-bit.

### 8. Add games and sync

Edit `itch-games.yaml`:

```yaml
games:
  - name: "Dragon Jump"
    zip: "dragon-jump-web.zip"
    itch: "dragon-jump"
```

Pull and restart ES:

```bash
~/scripts/sync-itch-games.sh --restart-es
```

## Key config snippets

### Chromium launch flags (`launch-web-game.sh`)

```bash
CACHE_DIR="/home/tagap/.cache/arcade"
mkdir -p "${CACHE_DIR}"

chromium-browser \
  --no-sandbox \
  --disable-gpu-watchdog \
  --kiosk \
  --start-fullscreen \
  --app="http://127.0.0.1:${PORT}/index.html" \
  --noerrdialogs \
  --disable-infobars \
  --disable-session-crashed-bubble \
  --disable-features=TranslateUI \
  --ozone-platform=x11 \
  --use-angle=gl \
  --enable-gpu-rasterization \
  --ignore-gpu-blocklist \
  --enable-accelerated-2d-canvas \
  --no-first-run \
  --disk-cache-dir=${CACHE_DIR}/chrome_cache \
  --user-data-dir=${CACHE_DIR}/chrome_profile \
  --disable-restore-session-state \
  --disable-background-networking
```

- `--disable-gpu-watchdog` prevents Chromium from killing the GPU process on a
  perceived hang (the cause of WebGL context loss on the Tegra X1).
- `--user-data-dir` / `--disk-cache-dir` point at `~/.cache/arcade/` so the
  shader cache and wasm persist across reboots and are shared across all games.

### Hiding the cursor (whole session)

There is never a real mouse on this cabinet (the Joy-Cons are ignored by X), so
a cursor would just float over ES and the games. The cursor is hidden for the
**whole Openbox session** by `unclutter` (`unclutter-xfixes`), started from the
X session init script `/etc/X11/Xsession.d/90unclutter` (installed by the
`unclutter-startup` package), which sources `/etc/default/unclutter`:
```
START_UNCLUTTER="true"
EXTRA_OPTS="--timeout 1 --start-hidden"
```
`--start-hidden` hides the cursor immediately on login; `--timeout 1` re-hides
it 1 s after any movement. Because it uses the XFixes extension, it works over
Chromium's own window too. With no mouse the cursor never reappears; plug a
mouse in and move it and it shows up for maintenance, then re-hides after 1 s.

> Use **xfixes flags** (`--timeout` / `--start-hidden`). The classic unclutter
> flags `-idle 1 -root` are NOT accepted by `unclutter-xfixes` (the 
> `/usr/bin/unclutter` alternative points to xfixes), so they are ignored and
> the cursor is not hidden. Don't put them in `EXTRA_OPTS`.

No per-game handling is needed in `launch-web-game.sh` — one session-wide
instance covers both ES and games.

### itch.io API key

The itch API only lets you download uploads from games **you own**. If a game
is from another developer, use a direct download URL in the `zip` field instead
of the `itch` slug.

## Auto-update watcher (itch collection)

`itch-watcher.py` runs as a user service on the Switch and mirrors an itch.io
collection onto the cabinet. Adding a game to the collection, re-uploading a
build, or removing it are all picked up automatically — the yaml list no
longer needs manual edits for day-to-day changes.

### How it works

1. Every `poll_seconds` (60 s default) it fetches
   `https://api.itch.io/collections/<id>/collection-games` (Bearer = the API
   key in `~/.config/itch_api_key`), paginated.
2. For each game it fetches uploads from the legacy v1 API
   (`itch.io/api/1/<key>/game/<id>/uploads`) — this works for **free games
   you don't own**, no download keys needed. It picks the HTML build
   (`type == "html"`, fallback `-web` in the filename; newest by
   `updated_at` if several exist).
3. Change detection is per-upload `md5_hash`/`updated_at` (and install-folder
   existence) vs `~/arcade_games/.itch-state.json`. State is written only
   after a successful install, so failures retry next poll.
4. **Idle gate:** if Chromium is running (a game is being played), the sync
   (and prune, and the ES restart) is deferred to the next cycle. A game in
   progress is never touched.
5. Install = signed URL download → unzip → flatten so `index.html` sits at
   the root → atomic swap into `~/arcade_games/web/<Title>/` + `.web` marker
   (same contract EmulationStation already scans).
6. `prune: true` removes games deleted from the collection (folder + marker).
   Only actual absence from the collection listing prunes: if a game's upload
   lookup fails (rate limit, network blip) the local copy is kept and retried
   next poll.
7. When something changed, it restarts EmulationStation so the menu
   refreshes — through the `launch-es.sh` wrapper (`/tmp/es-restart`) when the
   wrapper is running, so its kiosk-mode handling (UIMode, RetroPie toggle,
   TTY env) survives; without the wrapper it launches the raw binary itself.

### Config (`~/arcade_games/itch-games.yaml`)

```yaml
collection: 8014540      # LimitTestArcade
prune: true
poll_seconds: 60
restart_es: true
games: []                # optional overrides (pin/exclude/rename by itch id)
```

The **collection id** comes from the collection URL
(`itch.io/c/8014540/limittestarcade`) or
`https://api.itch.io/profile/collections`.

Per-game overrides (`games:` list, matched by `itch:` game id):

- `name:` folder/display name override
- `upload:` pin a specific upload filename (e.g. when itch has several web
  builds and the wrong one would be picked)
- `exclude: true` never install this game

### Service

Deployed as a **user** unit (`~/.config/systemd/user/itch-watcher.service`,
enabled, linger on):

```bash
scp config/systemd/user/itch-watcher.service switch:/tmp/
scp scripts/itch-watcher.py switch:~/scripts/
ssh switch 'mkdir -p ~/.config/systemd/user && cp /tmp/itch-watcher.service ~/.config/systemd/user/ && systemctl --user daemon-reload && systemctl --user enable --now itch-watcher'
ssh switch 'echo 1234 | sudo -S -p "" loginctl enable-linger tagap'
```

Management: `systemctl --user status itch-watcher` (logs appear in
`systemctl --user status` output; journal files for user services are not
persisted on this image). Run one poll by hand with
`python3 ~/scripts/itch-watcher.py --once` and repair/initial-pull with
`--force`.

### Notes

- A game that can't be auto-pulled (paid, not owned, not claimable) logs a
  warning each cycle and is skipped; install it manually via
  `sync-itch-games.sh` with a direct URL.
- The itch API only allows reading one's own collections; the API key's
  account must own (or follow/curate) the collection.
- Legacy v1 endpoints handle uploads+downloads for free third-party games;
  `api.itch.io` (Bearer) is only used for the collection listing.

## Kiosk mode + admin access (the Konami code)

EmulationStation boots in **kiosk mode**, which hides the system-destructive
menu items (RetroPie setup, terminal, file manager, edit metadata, scraper, most
configuration). `launch-es.sh` resets `UIMode` to `kiosk` in
`~/.emulationstation/es_settings.cfg` before every launch, so kiosk is restored
on each session start.

To temporarily unlock the full (admin) UI, enter the **Konami code** on the
Joy-Cons anywhere in ES:

```
Up, Up, Down, Down, Left, Right, Left, Right, B, A
```

ES flashes and restarts in **Full** mode. Admin access lasts until the next
reboot / sddm restart, when the wrapper resets kiosk again — a deliberate
temporary escape hatch, not a permanent unlock.

**RetroPie menu:** Kiosk mode does *not* hide the RetroPie system card by
itself (a known ES limitation), and the `hidden=true` gamelist filter is broken
on this ES build (2.11.2rp) — verified: a hidden game is still counted. So
`launch-es.sh` hides the RetroPie system by pointing its `<path>` in
`/etc/emulationstation/es_systems.cfg` at an empty directory
(`~/RetroPie/roms/empty`) in kiosk mode, and restoring it to
`~/RetroPie/retropiemenu` in Full mode. ES ignores a system whose path has no
games, so the RetroPie card disappears from the ribbon in kiosk and reappears
for admin after the Konami code.

`launch-es.sh` runs its own restart loop (mirroring RetroPie's
`emulationstation.sh`) against the raw binary, re-toggling the path on every
restart. A fresh session starts locked down (kiosk).

**Why the Konami code needs a watcher:** the Konami code sets `UIMode=Full` and
reloads ES **in-process** — it does not exit the process, and that reload does
not re-read `es_systems.cfg` (the system list is loaded once at startup). So the
RetroPie system, whose path was pointed at the empty dir at boot, stays hidden
even after the Konami code. `uimode-watcher.py` (started from the Openbox
autostart) polls `es_settings.cfg` for `UIMode` changing to `Full`; when it
detects the Konami unlock, it creates `/tmp/es-restart` and SIGTERMs the ES
binary. `launch-es.sh`'s restart loop then re-runs, re-toggles the path to
`retropiemenu`, and ES starts fresh with the admin menu visible. The user sees
ES flash/restart — the expected Konami behavior.

Reverting to kiosk is handled by the Openbox autostart on the next sddm restart
(it resets `UIMode=kiosk` and `launch-es.sh` points the path back at the empty
dir).

Notes:
- If the D-pad doesn't register the code (some controller/HAT setups), use the
  **left analog stick** for the directions instead — it's mapped to
  up/down/left/right in `es_input.cfg`.
- The passkey can be customized in `es_settings.cfg` (key `UIMode`'s companion
  setting), but the default Konami sequence is fine for an arcade.
- Do **not** use `emulationstation --force-kiosk`: it forces kiosk on every ES
  restart, overriding the Konami code's switch to FullUI. Editing `UIMode` in
  the config (as `launch-es.sh` does) is what lets the code work.

## Gamepad input (the bridge)

Chromium's W3C Gamepad API **does** expose the Combined Joy-Cons in the real
kiosk browser, but its button indices don't match what Godot web builds expect
(the D-pad lands on indices 14-17, not the standard 12-15), so games see
phantom directions. The megascript's X joystick driver
(`xserver-xorg-input-joystick`) *also* translates them to keyboard/mouse, but it
is a desktop tool whose "accelerated" axis mapping produces repeated keys and
bleeds analog-stick drift into phantom directions. Either path alone is messy;
both together cause double input.

Instead, `gamepad-bridge.py` reads the Joy-Cons directly via evdev
(`/dev/input/event8`) and injects clean keyboard events through `/dev/uinput`.
It replaces both the X joystick driver and the old `quit-watcher.py`. It starts
from the Openbox autostart (idempotently) and is also started as a fallback by
`launch-web-game.sh`.

**Exclusive grab:** while Chromium is running, the bridge holds an `EVIOCGRAB`
on event8, which blocks *every other reader* — Chromium's Gamepad API and
libinput — from receiving Joy-Con events. This makes the bridge's keyboard
injection the single, clean input path (no double input). When the game exits,
the bridge releases the grab and the Joy-Cons return to EmulationStation (which
uses SDL). An X config (`10-ignore-joycons.conf`) also tells libinput to ignore
the Joy-Cons entirely, so they never become a pointer/keyboard in X.

Mapping table (edit the `BTN_TO_KEY` dict in the script):

| Joy-Con input | evdev code | Injected key | Purpose |
|---|---|---|---|
| D-pad Up | 544 | `KEY_UP` | move up |
| D-pad Down | 545 | `KEY_DOWN` | move down |
| D-pad Left | 546 | `KEY_LEFT` | move left |
| D-pad Right | 547 | `KEY_RIGHT` | move right |
| A (`BTN_SOUTH`) | 304 | `KEY_SPACE` | jump / accept |
| B (`BTN_EAST`) | 305 | `KEY_R` | reset |
| X (`BTN_NORTH`) | 307 | `KEY_ESC` | back / cancel |
| Y (`BTN_WEST`) | 308 | `KEY_TAB` | menu |
| Start + Select | 315 + 314 | (exit) | returns to ES |
| Start + Select + B | 315 + 314 + 305 | (reboot) | panic reboot (frozen game) |

The left analog stick can also be mapped to directions past a deadzone
(`STICK_MAP`, disabled by default so stick drift never produces a phantom
direction). uinput is writable by `tagap` (in the `input` group), so no sudo is
needed. Requirement: `python3-evdev`.

### Input latency

Input is kept low-latency by never doing anything slow in the hot event path:

- The Chromium-running check (`_chromium_running()`) is **cached with a 1 s
  TTL**. It spawns a `pgrep` process at most once per second, never per event.
- `_inject_events()` uses `select()` with a 0.5 s timeout and batch-reads all
  pending events per wakeup, instead of `read_loop()` (which forked `pgrep` for
  every button press and added ~10-30 ms of overhead per press).

Remaining latency is just Chromium's inherent keyboard pipeline (X server →
browser process → renderer → JS), which is unavoidable for injected keys.

## Quit / exit mechanisms

1. **Start + Select** (force-quit, any game — **the primary exit method**) —
   `gamepad-bridge.py` reads the Combined Joy-Cons via evdev and, while running,
   detects Start + Select pressed together → calls `exit-to-es.sh` → kills
   Chromium → back to ES. evdev codes: `BTN_START=315`, `BTN_SELECT=314`.

2. **Start + Select + B** (panic reboot) — if a game froze so hard the exit
   didn't work (e.g. GPU hang leaving Chromium uninterruptible), hold Start +
   Select and press B: the bridge calls `sudo -n systemctl reboot`
   (passwordless sudo drop-in `/etc/sudoers.d/arcade-panic`). This is read at
   the evdev level, so it works even when X/the game are completely frozen.

3. **In-game Quit button** (plain HTML games only) — a game's own Quit button
   can navigate to `http://127.0.0.1:8123/exit` directly. The `exit-server.py`
   handles the rest.

> **Godot web builds: the in-game QUIT button does NOT return to ES.** This is
> a known Godot limitation — `get_tree().quit()` on a web export just stops the
> game loop (the canvas freezes) but produces no browser event, no page
> unload, and no reliable JS signal. There is no host-side way to detect it
> without false positives (the game goes silent during normal play too, so
> idle-detection would close the game unexpectedly). Use **Start + Select** to
> exit Godot web games. See [Troubleshooting](troubleshooting.md) for details.

### `exit-to-es.sh`

Kills the http server (port 8124) + force-kills Chromium kiosk, then relaunches
EmulationStation if it died. The gamepad bridge's Start+Select and the
exit-server both funnel through this script.
