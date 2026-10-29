# Arcade Panel Input — Investigation Notes (2026-10-16)

Field notes from fixing the two generic arcade-panel controllers on the
**hardware mode** cabinet: what we tried, what worked, what didn't, and why.
Written so a future session can repeat this without re-living the dead ends.
The shipped solution is documented in
[`multi-controller-panels.md`](multi-controller-panels.md) §12.

> **Update (2026-10-16, later):** these notes are specific to the
> *hardware-mode* cabinet. On the *software-mode* cabinet the same-model
> panels turned out to be wired in standard order (no remap needed) — see
> [`multi-controller-panels.md`](multi-controller-panels.md) §13 for the
> per-cabinet `panel-wiring.conf` switch.

**Outcome in one line:** the panels' raw button order is non-standard, Chromium
reports it verbatim, and no host-side trick fixed that reliably — so the remap
was moved **into the served web page** (a shim injected by `webgame-server.py`)
and verified working.

## TL;DR — the lessons that would save the most time

1. **Identify the cabinet first.** Both units share the hostname
   `tagap-laptop`; mDNS is ambiguous. Use the board serial
   (`/proc/device-tree/serial-number`) or WiFi MAC. Hours were lost probing
   the wrong unit. See `README.md`, "The two cabinets" (hardware mode =
   serial `NXO-2EDABE7E-30080F`, software mode = `NXO-30D61FFC-30020F`).
2. **The ES input wizard already captured the button mapping.** When the
   panels were configured in EmulationStation, the wizard wrote every raw
   button id to `~/.emulationstation/es_temporaryinput.cfg`. That file *is* a
   press-capture session — no buttons need pressing. Look there first.
3. **Chromium exposes unknown pads in raw evdev code order.** For the
   DragonRise boards that scrambles every button (physical A is the *last*
   raw button → index 11 = R3). This is the whole root cause.
4. **Do not try to fix it with uinput virtual gamepads on this stack.**
   Chromium's Linux gamepad provider will not reliably enumerate them:
   coldplug skips them, hotplug is racy, it usually opens only the evdev node
   (not the joydev one), and re-emitting udev "add" events can make it drop
   *all* gamepads. Details in §4.
5. **The winning lever is the layer we own:** every web game is served by
   `webgame-server.py`, so the remap lives in the page (shim). Zero Chromium,
   udev, or uinput involvement.
6. **Keep the test harness.** A gamepad-tester page + a tiny beacon logger let
   us read Chromium's gamepad state remotely (no screen-peeking). Saved in
   `tools/padtest/` (§7).
7. **Useful forensics:** `ls -l /proc/$(pgrep -f chrome)/fd | grep /dev/input`
   shows exactly which input devices Chromium has open; `udevadm info -q
   property -n /dev/input/eventN` shows what its rules decided.
8. **`pkill -f` footgun:** the pattern matches the invoking shell's own command
   line (which contains the pattern text), killing the SSH session mid-script.
   Use the bracket trick (`pkill -f "[g]amepad-bridge.py"`) and keep the plain
   string out of the same command. Bit us 3 times.

## 1. Symptom and root cause

- Web games read gamepads via the Gamepad API. The panels worked (d-pad moved)
  but face/shoulder buttons landed on wrong actions ("R3 is X", "R4 is O").
- The panels report 12 buttons as `BTN_TRIGGER`..`BTN_BASE6` (evdev 288–299),
  none with standard names. Chromium has no mapping for this knockoff encoder
  and exposes buttons **in ascending raw code order** ("STANDARD GAMEPAD"
  label, `m="standard"`). Physical A (code 299) therefore appears as index 11
  (R3), and everything lands wrong.
- The Joy-Cons are handled by `gamepad-bridge.py` (keyboard injection) and are
  hidden from the page Gamepad API by the same shim. Chromium can still see the
  paired `js` node, so the grab alone is not enough to keep them out of a page.

**Raw order (js id = code − 288):**

`0=customR 1=customL 2=Select 3=Start 4=LT 5=RT 6=LB 7=RB 8=Y 9=X 10=B 11=A`

(matches the ES wizard capture; the joystick is on `ABS_X`/`ABS_Y`, 0–255,
center ~127, plus an unused, constantly jittering `ABS_Z`).

## 2. What we tried, in order

### 2.1 Extended `gamepad-bridge.py` with virtual uinput gamepads (built, tested, abandoned)

Plan (still preserved in `multi-controller-panels.md` §6/§8): grab both raw
panels while Chromium runs and re-emit each as `arcade-p1`/`arcade-p2` uinput
gamepads exposing exactly the standard button/axis set, so Chromium would map
standard indices. The Joy-Con keyboard path stayed unchanged.

**What worked:**
- Discovery/ordering by `dev.phys` (`usb-70090000.xusb-1.2` = P1,
  `:1.3` = P2) — stable.
- Grabbing the raw panels and forwarding events into the uinput pads —
  verified with a second reader on `arcade-p1`: a physical A press produced
  `KEY code=304` (BTN_SOUTH). The bridge logic was correct.
- Hotplug tolerance (drop dead devices, re-discover) — the bridge survived
  panel unplugging (which crashes ES, see §6).

**What failed — Chromium would not reliably expose the uinput pads:**

1. **Coldplug skip.** A freshly started Chromium did *not* open pads that
   already existed. Evidence: `/proc/<browser>/fd` held only the raw pads
   (`event6/7` + `js0/1`), never the uinput pads, even though
   `udevadm info` showed `ID_INPUT_JOYSTICK=1` on them.
2. **Racy hotplug.** Creating the pads while Chromium ran sometimes made it
   open one of the two (e.g. only `arcade-p2`), sometimes neither. The udev
   "add" arrives, Chromium opens the evdev node — often *not* the paired
   `/dev/input/jsN` node, while for real pads it opens both. (Chromium's
   Linux gamepad provider pairs evdev/joydev nodes by parent syspath;
   [reports](https://github.com/medusalix/xow/issues/182) say it even reads
   input values from the joydev nodes.)
3. **`udevadm trigger --action=add` nudges** (passwordless sudo) made
   Chromium open a missed pad *sometimes*. Spamming them every 2 s made
   Chromium drop **all** gamepads after ~8–10 s (observed: page went from 3
   pads to none until browser restart). Bounded nudges (first ~10 s of a
   session) were still not reliable.
4. **Page "engagement" oddities.** Pads appeared in `getGamepads()` only after
   receiving input, and even then inconsistently; listing state differed
   between otherwise identical experiments. Synthetic held presses engaged
   pads once, then a later release or nudge could remove everything.
5. **Unique vendor/product per pad** (`1234:0001` / `1234:0002` via UInput) did
   not change the behavior (and is worth keeping if uinput is ever revisited).

Attempts made: lazy vs persistent pad creation; synthetic presses; unique
device ids; udev nudges; browser warm/cold starts; `/proc/fd` verification at
every step. Never reached a state that could ship.

**Verdict:** uinput gamepads are second-class citizens in this Chromium on
this stack. Abandoned. (The extended bridge was reverted to the original.)

### 2.2 udev / hwdb angles

- `ID_INPUT_JOYSTICK=1` is present on the pads (required by Chromium; fine).
- `ID_INPUT_JOYSTICK_INTEGRATION` is **absent** on virtual pads. Chromium
  hides pads tagged `INTEGRATION=internal` (anti-fingerprinting; see
  [systemd #42629](https://github.com/systemd/systemd/issues/42629)), so a
  rule setting it to `external` should be harmless — but it did not appear to
  change the outcome, and with the property absent the "internal" filter
  shouldn't apply anyway. Unresolved thread; worth one retest if uinput is
  ever revisited.
- `/dev/input/jsN` nodes for the pads existed and mapped correctly
  (`js5 → arcade-p1`, `js6 → arcade-p2`); Chromium just didn't open them.

### 2.3 Other dead ends

- Chromium verbose logging (`--enable-logging=stderr -v --vmodule=*gamepad*`)
  produced **no** gamepad-module lines on this build — useless for this.
- Waiting for a "user gesture" (keyboard event from a Joy-Con press) did not
  make pads appear.
- Making the virtual pads mimic real USB ids (Xbox `045e:028e`) — considered,
  not pursued because coldplug skipped uinput devices regardless of ids and
  the shim path won first.
- The hardware itself was a recurring blocker: the Switch's single USB-C port
  is either a host (for the panels, via the dock) **or** a device (for the PC
  gadget link) — never both. A passive hub cannot change that. All work was
  done over WiFi instead (see §6).

## 3. What worked — the in-page shim

Since `webgame-server.py` serves every game page, it now injects
`arcade-pad-shim.js` into every HTML response (right after `<head>`). The shim:

- wraps `navigator.getGamepads()` and replaces each DragonRise pad's
  `buttons` array with the standard order
  (`RAW_TO_STD = [11,10,9,8,6,7,4,5,2,3,1,0]` = A,B,X,Y,LB,RB,LT,RT,
  Select,Start,L3,R3),
- also normalizes the `gamepadconnected` event for engines that use it,
- leaves axes untouched (the joystick already arrives as the left stick).

No uinput, no udev, no grabbing; the panels stay untouched for ES, and the
shim only affects pages served by `webgame-server.py`. HTML is always served
injected (never from a compressed sidecar).

**Verified end-to-end on the hardware-mode cabinet** with the tester page:
physical A → button 0 on index 0 (Panel 1 = Player 1), Panel 2 → index 1,
Start/Select → indices 9/8 matching their ES roles.

## 4. Environment facts (the hardware-mode cabinet, 2026-10-16)

| | |
|---|---|
| Userspace | Ubuntu 24.04, systemd 255 |
| Kernel | `4.9.140-l4t` (L4T/Tegra X1) |
| Chromium | 126.0.6478.234 (kiosk flags in `launch-web-game.sh`) |
| python-evdev | 1.7.0 |
| Panels | 2× `DragonRise Inc.   Generic   USB  Joystick  ` (`0079:0006`) on dock hub ports `xusb 1.2` / `1.3` |
| Pads' quirk | unused `ABS_Z` (code 2) jitters ~131–136 constantly — harmless, ignore it |
| ES quirk | crashes when panels are unplugged while running (log stops at `Removed joystick …`); `launch-es.sh` does not relaunch after an unexpected exit → black screen. Recovery: `sudo systemctl restart sddm` (see `troubleshooting.md`) |
| Networking | both units WiFi via profile "Netul Femeilor Puternice"; IPs made static (`192.168.50.219` hw / `.75` sw) in `/etc/netplan/90-NM-<uuid>.yaml`; SSH aliases `switch-hw` / `switch-sw` |

## 5. Test harness (saved in the repo)

`tools/padtest/`:

- `index.html` — a gamepad-tester page that renders `getGamepads()` and
  beacons every change to `http://127.0.0.1:8130/r?d=...`.
- `log_server.py` — tiny HTTP logger appending beacons to `/tmp/padlog.txt`.

On the Switch it was temporarily installed as an ES "game"
(`~/arcade_games/web/PadTest/` + `PadTest.web` marker, launched through the
normal web-game flow) with `log_server.py` running detached. It was removed
from the cabinets afterwards (2026-10-16) and now lives only in this repo;
redeploy it with the commands below when needed:

```bash
scp tools/padtest/index.html tools/padtest/log_server.py switch-hw:/tmp/
ssh switch-hw 'mkdir -p ~/arcade_games/web/PadTest
  cp /tmp/index.html ~/arcade_games/web/PadTest/
  touch ~/arcade_games/web/PadTest.web
  setsid nohup python3 -u /tmp/log_server.py >/dev/null 2>&1 </dev/null &'
# then read results over SSH:
ssh switch-hw 'cat /tmp/padlog.txt'
```

**Footgun — stale servers hijack the game port (hit for real, 2026-10-16).**
Forgetting to kill a manually started `webgame-server.py` leaves port 8124
occupied. `launch-web-game.sh` then starts a server that cannot bind
(`Address already in use` in `/tmp/webgame_server.log`), and the kiosk is
answered by the stale server — so *every* launched game shows that server's
page (in our case the tester, looking like a controller debug screen). Guards
added: `launch-web-game.sh` now reaps stale servers on its port before
starting and fails loudly if its own server dies; `exit-to-es.sh` also kills
`webgame-server.py`. Still: always kill manual test servers when done.

Also used (ad-hoc, not saved): a raw evdev event logger to capture presses
(`EV_KEY` value 1 with `dev.phys`), and `tools/padtest`-style readers on the
uinput pads during the abandoned experiment.

## 6. If doing this again

1. Confirm which unit you're on (serial/MAC) and reach it over **WiFi** —
   the USB port is needed for the panels.
2. Read `~/.emulationstation/es_temporaryinput.cfg` for the raw-button
   mapping; skip any press-capture session.
3. Go **straight** to the in-page shim (`arcade-pad-shim.js` +
   `webgame-server.py` injection). Do not build a uinput gamepad bridge for
   Chromium on this stack; it cannot be made reliable here (§2.1).
4. Verify with `tools/padtest/` — one real button press per question.
5. When done with a manual test server, kill it and remove the PadTest game —
   see the footgun in §5.
6. Remember the `pkill` bracket trick and `/proc/<pid>/fd` forensics.
