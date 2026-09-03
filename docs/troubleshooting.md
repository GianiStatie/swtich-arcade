# Troubleshooting

Common issues with the current web-games setup on the Switch.

## WebGL context lost / "please reload page"

**Symptom:** A web game shows "WebGL context lost, please reload page" shortly
after launching.

**Cause:** Chromium's GPU process crashed. On the Tegra X1 (Maxwell) the GPU
driver (`libnvidia-rmapi-tegra.so`, `libnvrm_gpu.so`) can hang or take too long,
and Chromium's GPU watchdog kills the process, dropping the WebGL context.

**Fix:** `launch-web-game.sh` includes `--disable-gpu-watchdog`, which stops
Chromium from killing the GPU process on a perceived hang. This is already
applied to all web games.

**Diagnose:**
```bash
# Crash dumps (2 = the pre-fix GPU crashes)
ls ~/.config/chromium/Crash\ Reports/pending/*.dmp
# GPU process alive?
pgrep -f "chrome --type=gpu-process"
```

If context loss persists after the fix, try tuning the GPU flags in
`launch-web-game.sh`:
- `--use-angle=gl-egl` instead of `--use-angle=gl`
- `--disable-gpu-driver-bug-workarounds`
- As a last resort, `--disable-gpu` (software rendering, much slower).

## Slow load after the progress bar fills

**Symptom:** The game's loading bar fills, then there's a long pause before the
game starts.

**Cause:** Shader compilation. The Tegra X1 compiles the game's WebGL shaders on
first load, which pegs the GPU process at ~50% CPU while the renderer idles.

**Fix:** The shader cache is now persisted at `~/.cache/arcade/` (shared across
all web games), so subsequent launches are faster once the cache is warm. The
first launch after a cache reset recompiles shaders once.

**Diagnose:**
```bash
du -sh ~/.cache/arcade/chrome_profile/ShaderCache
```

## Game doesn't appear in EmulationStation

- A system must have at least one game in its `path` directory or ES ignores it.
- Ensure a `.web` marker file exists next to the game folder:
  ```bash
  touch ~/arcade_games/web/<GameName>.web
  ```
- Refresh the gamelist (Start → UI Settings → Update Gamelist) or restart ES.

## itch.io game won't pull

- The itch API only lets you download uploads from games **you own**. If the
  game is from another developer, use a direct download URL in the `zip` field
  instead of the `itch` slug.
- Verify the API key: `~/scripts/download-from-itch.sh <slug> <file>`.
- The build must have `index.html` at the root of the zip.

## USB IP drops on reconnect

**Fixed (2026-09-03).** The IP is now static and survives reconnects and reboots
on both sides — no manual commands needed:

- **Switch side** is static by design: NVIDIA's `l4t-usb-device-mode` service
  always assigns `192.168.55.1` to the Switch, DHCP-leases exactly
  `192.168.55.100` to the PC (single-address pool in
  `/opt/nvidia/l4t-usb-device-mode/dhcpd.conf`), and auto-adds the default
  route via `.100`.
- **PC side** uses a static NetworkManager connection: `Wired connection 3` is
  bound to the USB interface with `ipv4.method=manual`,
  `ipv4.addresses=192.168.55.100/24` (set via
  `nmcli connection modify "Wired connection 3" ...`). Previously it was DHCP
  autoconnect, which wiped the manually added IP on every reconnect — that was
  the cause of this issue.

### Internet sharing for the Switch (OTA updates)

The Switch routes its traffic through the PC (`default via 192.168.55.100`),
so the PC must forward + NAT. Made persistent on 2026-09-03:

- `/etc/sysctl.d/99-arcade-usb-forward.conf` sets `net.ipv4.ip_forward = 1`.
- firewalld masquerade on the default zone:
  `firewall-cmd --permanent --zone=FedoraWorkstation --add-masquerade`.
  (Do NOT also add a manual `iptables -t nat` MASQUERADE rule — firewalld
  reloads wipe those; the firewalld-native setting survives.)

If the Switch has no internet, check on the PC:

```bash
sysctl net.ipv4.ip_forward                       # must be 1
firewall-cmd --zone=FedoraWorkstation --query-masquerade   # must be yes
nmcli -f ipv4.method,ipv4.addresses connection show "Wired connection 3"
```

Then on the Switch: `ping 8.8.8.8` and `curl -m 8 https://itch.io`.

## Can't exit a web game

The **primary exit method is Start + Select** (force-quit, works for any game).
There is also a plain-HTML Quit button path for simple games.

1. **Start + Select** (force-quit, any game — recommended) — works via the
   gamepad bridge reading evdev. If it doesn't work, check the bridge is running:
   ```bash
   pgrep -a -f gamepad-bridge.py
   cat /tmp/gamepad_bridge.log
   ```
   The bridge reads the Combined Joy-Cons (`/dev/input/event8`) continuously.
   evdev codes: `BTN_START=315`, `BTN_SELECT=314` on the Combined Joy-Cons.

2. **In-game Quit button** (plain HTML games only) — the game's Quit button
   must navigate to `http://127.0.0.1:8123/exit`. Verify the exit-server is
   listening:
   ```bash
   curl -s http://127.0.0.1:8123/exit   # should print OK
   ```

As a last resort, SSH in and run:
```bash
pkill -f "chromium-browser --kiosk"
```

## In-game QUIT button doesn't work (Godot web builds)

**This is a known Godot limitation, not an arcade bug.** When a Godot web build
calls `get_tree().quit()`, the game loop stops and the canvas freezes, but:

- The browser tab does **not** close or navigate (browsers forbid scripts from
  closing tabs they didn't open).
- No `beforeunload` / `unload` event fires (the page stays loaded).
- The Emscripten `onExit` callback may fire after an async IndexedDB sync, but
  it is unreliable and cannot be hooked from the host without modifying the
  game source (V8's code cache defeats serve-time JS injection).

There is **no reliable host-side signal** to detect the quit:
- The game does **not** print a specific "quit" message to the console — it
  just goes silent.
- The game is **naturally silent during normal play** (it only logs during
  boot), so watching for console silence would close the game unexpectedly
  (false positives).
- Canvas-idle / log-idle detection both suffer from this false-positive risk.

**Use Start + Select to exit Godot web games.** The only way to make the
in-game QUIT button return to ES is to modify the game's GDScript to call the
exit endpoint on quit:
```gdscript
func _on_quit_button_pressed() -> void:
    if OS.has_feature("web"):
        JavaScriptBridge.eval("fetch('http://127.0.0.1:8123/exit',{keepalive:true,mode:'no-cors'})")
    else:
        get_tree().quit()
```
This requires owning the game and re-exporting the web build — it is not a
host-side fix.

## ES runs on top of the desktop (Plasma showing behind it)

The Switch should boot into an Openbox session (black screen + ES only). If
Plasma is showing instead, check the sddm autologin config:
```bash
cat /etc/sddm.conf.d/10-arcade-openbox.conf   # Session=openbox.desktop
ls /usr/share/xsessions/openbox.desktop        # must exist
```
A reboot is required for the session change to take effect.

## Joy-Con controls wrong / doubled in Chromium

**Symptom:** In a web game, pressing D-pad **Up** also triggers **Right** (or
other phantom/mixed directions), or the sticks cause mouse cursor / keyboard
input in the browser.

**Cause:** Several input paths collided:

1. Chromium's W3C Gamepad API exposes the Combined Joy-Cons, but its button
   indices don't match what Godot web builds expect (D-pad lands on indices
   14-17 instead of the standard 12-15), producing phantom/mixed directions.
2. The L4T-Megascript installs `xserver-xorg-input-joystick` plus
   `50-joystick.conf` / `51-joystick-others.conf`, which tell the X server to
   translate Joy-Con buttons/axes into keyboard keys and mouse clicks. Its
   "accelerated" axis mapping fires repeated keys and bleeds analog-stick drift
   into phantom directions.
3. Running both the Gamepad API and the X joystick driver together caused each
   press to arrive twice.

**Fix (current):** The Joy-Cons are read by `gamepad-bridge.py` (evdev →
uinput), which injects clean keyboard keys **and** holds an exclusive grab
(`EVIOCGRAB`) on the controller while Chromium runs. That grab blocks
Chromium's Gamepad API and libinput from reading the Joy-Cons, so the bridge's
keyboard injection is the single input path. The X joystick driver is
**disabled** and must stay disabled; an X config (`10-ignore-joycons.conf`)
also tells libinput to ignore the Joy-Cons as a pointer/keyboard. The two
megascript configs are renamed to `.disabled`:
```bash
echo 1234 | sudo -S mv /usr/share/X11/xorg.conf.d/50-joystick.conf \
  /usr/share/X11/xorg.conf.d/50-joystick.conf.disabled
echo 1234 | sudo -S mv /usr/share/X11/xorg.conf.d/51-joystick-others.conf \
  /usr/share/X11/xorg.conf.d/51-joystick-others.conf.disabled
sudo systemctl restart sddm
```
Then confirm the bridge is running (it injects D-pad → arrow keys, A → Space,
B → R, etc.):
```bash
pgrep -a -f gamepad-bridge.py
```
`joycond` (pairing) is unaffected. Do **not** re-enable the X joystick driver
while the bridge is in use — they would double-inject every button press. To
use desktop-mode joystick-as-mouse, stop the bridge and rename the files back
to `.conf`, then restart sddm.

### Verifying the bridge mapping

With the bridge running, capture its injected keys:
```bash
# find the arcade-bridge event device, then
xinput test-xi2 3   # press D-pad/A/B and read the keys
```
Or check `/proc/bus/input/devices` for the `arcade-bridge` virtual device.
Edit the mapping in `/home/tagap/scripts/gamepad-bridge.py` (`BTN_TO_KEY`).

## Input lag when pressing buttons in Chromium

**Symptom:** Buttons register, but with a noticeable ~10-30 ms delay between a
press and the game reacting.

**Cause:** The bridge's event loop called `_chromium_running()` on every evdev
event. Each call does `subprocess.run(["pgrep", ...])` — a fork+exec that costs
~5-15 ms — and a single button press generates 2+ events (EV_KEY + EV_SYN), so
every press carried tens of milliseconds of overhead.

**Fix:** In `gamepad-bridge.py`, `_chromium_running()` now caches its result
with a 1 s TTL, and `_inject_events()` uses `select()` with a 0.5 s timeout and
batch-reads all pending events instead of using `read_loop()`. No process is
spawned in the hot path. If latency regresses, confirm the running bridge is the
updated one and has not been restarted from an old copy:
```bash
head -1 /proc/$(pgrep -f gamepad-bridge.py | head -1)/cmdline | tr '\0' ' '
grep -n "CHROMIUM_CACHE_TTL" /home/tagap/scripts/gamepad-bridge.py
```

## Cursor visible over a game (or in ES)

**Symptom:** A mouse cursor sits on top of the game in Chromium, or in the
EmulationStation menus.

**Cause / fix:** The cursor is hidden for the whole session by `unclutter`
(`unclutter-xfixes`), started from `/etc/X11/Xsession.d/90unclutter` (installed
by `unclutter-startup`), which sources `/etc/default/unclutter`. Verify it is
installed, enabled, and running:
```bash
command -v unclutter          # must be /usr/bin/unclutter
grep START_UNCLUTTER /etc/default/unclutter   # must be "true"
pgrep -af unclutter           # should list one process
```
`EXTRA_OPTS` in `/etc/default/unclutter` must use **xfixes flags**
(`--timeout 1 --start-hidden`). The classic flags `-idle 1 -root` are silently
ignored by `unclutter-xfixes` (the `/usr/bin/unclutter` alternative points to
xfixes), so the cursor stays visible — that is the usual regression. After
editing `/etc/default/unclutter`, restart the session:
```bash
sudo systemctl restart sddm
```
`xsetroot -cursor blank.xbm blank.xbm` will **not** work here — it only changes
the root-window cursor, and Chromium sets its own per-window cursor over the
page. Don't use it as a replacement.
