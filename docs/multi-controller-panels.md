# Multi-Player Arcade Panels — Two More Controllers

**Status: IMPLEMENTED & VERIFIED (2026-10-16).** The panels are remapped for
web games by a small shim injected into every served page by
`webgame-server.py` — see the final implementation in §12, which supersedes the
original uinput plan (§6, §8). Discovery results are in §7.1.

Repo: `git@github.com:GianiStatie/swtich-arcade.git` (note the `swtich` typo —
it is the correct remote). The panels live on the **hardware mode** cabinet
(see `docs/README.md`, "The two cabinets"); all work was done on it over WiFi.

## 1. What we're trying to do

The cabinet originally had just the built-in Joy-Cons. Two arcade control
panels (USB HID encoders) were then added — one for Player 1, one for Player 2.
The goal:

- Panel 1 → Player 1 (same as the Joy-Cons; "duplicates P1").
- Panel 2 → Player 2.
- Both panels should reach the web game as **controllers with corrected
  mappings** (the user's preferred outcome), not as raw mis-mapped devices.

## 2. Background — how input works today

The only Switch-side input path is `scripts/gamepad-bridge.py`. It is
**single-device by design**:

- `_find_controller()` (`scripts/gamepad-bridge.py:83`) enumerates
  `evdev.list_devices()` and returns the **first** device whose name contains
  `"Combined Joy-Cons"`. Everything else is ignored and closed.
- While Chromium runs it takes an exclusive grab, `dev.grab()`
  (`scripts/gamepad-bridge.py:273`), i.e. `EVIOCGRAB`. That grab is the only
  thing that keeps a device out of Chromium's W3C Gamepad API — **an X config
  cannot do this** (see `docs/troubleshooting.md:192`).
- It translates the Joy-Cons to **keyboard** keys via `/dev/uinput`
  (`BTN_TO_KEY`, `scripts/gamepad-bridge.py:39`) and injects them. Games are
  expected to read keyboard only.
- The injected virtual device is named `arcade-bridge` and exposes only
  `EV_KEY`.
- "Is Chromium running?" is polled with `pgrep -f
  /opt/chromium.org/chromium/chrome`, cached 1 s (`_chromium_running()`,
  `scripts/gamepad-bridge.py:118`).
- The main loop is `_inject_events()` (`scripts/gamepad-bridge.py:211`): a
  `select()` on one fd, batch-read, dispatch via `_process_event()`
  (`scripts/gamepad-bridge.py:136`).
- Start+Select = force-quit; Start+Select+B = panic reboot.

Existing Joy-Con mapping (`BTN_TO_KEY`):

| Joy-Con input | evdev code | Injected key |
|---|---|---|
| A (`BTN_SOUTH`) | 304 | `KEY_SPACE` |
| B (`BTN_EAST`) | 305 | `KEY_R` |
| X (`BTN_NORTH`) | 307 | `KEY_ESC` |
| Y (`BTN_WEST`) | 308 | `KEY_TAB` |
| D-pad up/down/left/right | 544/545/546/547 | `KEY_UP/DOWN/LEFT/RIGHT` |
| Start / Select | 315 / 314 | (exit combo) |

`config/10-ignore-joycons.conf` tells libinput to `Ignore` the Joy-Cons as an X
pointer/keyboard, but that does **not** hide them from Chromium — only the
`EVIOCGRAB` does. `config/openbox-autostart` and `scripts/launch-web-game.sh`
both start exactly one bridge instance.

The arcade control-panel hardware is described in `docs/event-specs.md:48`:
1× 8-way joystick + 8 buttons (A, B, X, Y, RB, LB, RT, LT) + Start, Select + 2
custom buttons, per player, two players.

## 3. The problem / symptom

In a specific web game: the new panels' D-pad works, but the panel face/shoulder
buttons land on the wrong game actions — reported as **"R3 is X and R4 is O"**
(on a PS4-style layout). The Joy-Cons (keyboard-injected) control that game fine,
so the game does accept keyboard.

## 4. Root cause

The panels are not `"Combined Joy-Cons"`, so `_find_controller()` never finds
them and the bridge never grabs them. They therefore leak straight into
Chromium's **W3C Gamepad API**, which assigns button indices by the device's HID
report order. The panel's button order is non-standard, so Chromium/game
indices are wrong. The D-pad happens to land on standard indices, which is why
only some buttons are wrong. This is the exact category of bug documented for
the Joy-Cons at `docs/troubleshooting.md:181`.

The two panels are **identical boards**, so they cannot be told apart by name —
they must be ordered by USB topology (`dev.phys` / `/dev/input/by-path/`).

## 5. Decisions made this session

- Extra controllers = **arcade-panel USB encoders** (generic HID gamepads).
- Desired: panel 1 duplicates P1, panel 2 is P2.
- The target game **reads keyboard** (Joy-Cons work in it) and also reads
  gamepads (the panels currently drive it).
- The user wants the panels to remain **controllers** ("seen as controllers with
  the mappings corrected"), rather than being converted to keyboard.
- The two encoders are **identical models**.

Consequent design: keep the Joy-Cons on keyboard (unchanged), and re-emit each
panel as a **virtual gamepad via uinput with standard codes**, while grabbing
the physical panels so Chromium never sees the raw, mis-mapped devices.

Options considered and rejected for now:

- ES / RetroArch / SDL input mapping (`es_input.cfg`, `SDL_GAMECONTROLLERCONFIG`,
  `jstest-gtk`) — only affects ES/RetroArch, **not Chromium**. No effect.
- Fixing the mapping inside the game (re-export) — possible but requires owning
  the game; not chosen.
- Third-party remappers (`input-remapper`, `evremap`, `hid-remapper`,
  `xboxdrv`, `antimicrox`) — same uinput concept but an extra component, and
  they do not integrate with the Start+Select exit logic. The bridge extension
  keeps everything in one place.

## 6. Proposed architecture

```
Joy-Cons  ──grab──► keyboard uinput ───────────────► Chromium (P1 keyboard)   [unchanged]
Panel #1  ──grab──► remap ──► gamepad uinput "arcade-p1" ─┐
Panel #2  ──grab──► remap ──► gamepad uinput "arcade-p2" ─┴► Chromium Gamepad API (P1, P2)
```

Both physical panels are grabbed (removing the raw, mis-indexed versions), and
re-emitted as virtual gamepads that expose the **standard** button/axis set:

`BTN_SOUTH/EAST/NORTH/WEST`, `BTN_TL/TR/TL2/TR2`, `BTN_SELECT/START/MODE`,
`BTN_THUMBL/THUMBR`, `BTN_DPAD_*`, plus `ABS_X/Y` and `ABS_HAT0X/Y`.

Rationale for correctness: Chromium selects a standard mapping by USB
vendor/product ID; a `uinput` device has none, so it uses its fallback mapping,
which assigns indices from the exposed button/axis set. Exposing exactly the
standard set should yield standard indices 0–15.

## 7. Prerequisite — discovery on the Switch (NOT DONE YET)

Run on the Switch (SSH: `ssh switch`, user `tagap`). Nothing here modifies the
system.

```bash
# Names, USB topology (phys), and the button/axis codes of every input device.
python3 - <<'PY'
import evdev
for p in sorted(evdev.list_devices()):
    d = evdev.InputDevice(p)
    c = d.capabilities(absinfo=False)
    print(p, repr(d.name), "phys=%r uniq=%r" % (d.phys, d.uniq))
    print("   BTN:", sorted(c.get(1, [])), "ABS:", sorted(c.get(3, [])))
PY

# Stable ordering: identical boards get distinct by-path entries (USB port).
ls -l /dev/input/by-path/ /dev/input/by-id/

# Per-button codes: pick each encoder, press each labelled button, note BTN_*.
sudo apt-get install -y evtest
sudo evtest
```

Record, per encoder:

1. Exact `name` (probably `"USB Gamepad"` or similar).
2. `phys` / `by-path` for each of the two boards → decides P1 vs P2 ordering.
3. Which raw `BTN_*` code each labelled panel button emits, and how the joystick
   is reported (ABS_X/Y vs ABS_HAT0X/Y).

These three records are what the remap table and the P1/P2 ordering depend on.

### 7.1 Discovery results (2026-10-16, hardware mode)

Recorded over WiFi on the hardware-mode cabinet with both panels attached:

| Property | Value |
|---|---|
| Input device name | `DragonRise Inc.   Generic   USB  Joystick  ` (note the padding spaces) |
| USB IDs | `0079:0006` ("PC TWIN SHOCK Gamepad") |
| Panel A | `platform-70090000.xusb-usb-0:1.2:1.0-event-joystick` → `/dev/input/event6` (dock hub port 2) |
| Panel B | `platform-70090000.xusb-usb-0:1.3:1.0-event-joystick` → `/dev/input/event7` (dock hub port 3) |
| Buttons | `BTN_TRIGGER`..`BTN_BASE6` = codes 288–299 (12 buttons, no standard names) |
| Axes | `ABS_X/Y/Z/RX/RZ` 0–255 (flat=15), `ABS_HAT0X/ABS_HAT0Y` −1..1 |

- Both boards are identical and have no `uniq`/serial, so P1/P2 come from their
  USB port order: **`:1.2` (dock port 2) = Player 1, `:1.3` = Player 2**
  (verified: Chromium enumerates them as gamepad index 0 / 1 in this order).
- The labelled-button ↔ raw-code table came from the ES input-wizard capture
  (`~/.emulationstation/es_temporaryinput.cfg`, written when the panels were
  configured in ES). Raw js-id → role: `0=customR 1=customL 2=Select 3=Start
  4=LT 5=RT 6=LB 7=RB 8=Y 9=X 10=B 11=A` (js ids are evdev codes 288+id; the
  joystick is `ABS_X`/`ABS_Y`). Note the roles match ES behavior on this
  cabinet: raw 291 (js 3) is the button ES uses as Start (opens the menu).
- ES log (`~/.emulationstation/es_log.txt`) shows both as
  `DragonRise Inc. Generic USB Joystick`, instance IDs 1 and 2.

**Notable side effect:** ES crashes if the panels are unplugged while it runs
(its log stops right at the `Removed joystick …` lines) and stays black because
`launch-es.sh` does not relaunch ES after an unexpected exit — see
`docs/troubleshooting.md`.

## 8. Original implementation plan (SUPERSEDED by §12)

> Kept for reference. This uinput-based plan was built and tested end-to-end,
> but Chromium on this box does not reliably expose uinput gamepads to pages
> (coldplug skips them, hotplug is racy, udev "add" nudges only sometimes work),
> so the shipped solution remaps inside the page instead — see §12.

### 8.1 `scripts/gamepad-bridge.py` (main work)

- **Config block at top** (same style as the existing `BTN_TO_KEY`):
  - `JOYCON_NAME = "Combined Joy-Cons"`, `PANEL_NAME = "<from discovery>"`, and
    a panel ordering keyed by `phys` / `by-path` suffix (boards are identical).
  - Keep `BTN_TO_KEY_P1` / `STICK_MAP_P1` for the Joy-Cons unchanged.
  - `PANEL_BTN_TO_STD` and `PANEL_AXIS_TO_STD`: raw panel codes → standard codes.
- **Replace `_find_controller()`** (`scripts/gamepad-bridge.py:83`) with
  `_discover()` returning `(role, dev)` for `joycon`, `panel1`, `panel2`.
  Order the two identical panels by `dev.phys`; skip our own virtual devices
  by name to avoid a feedback loop.
- **uinput factories**: keep the P1 keyboard device; add
  `_make_gamepad(name)` exposing the standard `EV_KEY` buttons and `EV_ABS`
  (`ABS_X/Y` range `-32768..32767`; `ABS_HAT0X/Y` range `-1..1`), named
  `arcade-p1` / `arcade-p2`.
- **`_inject_events()`** (`scripts/gamepad-bridge.py:211`): `select()` on all
  fds; dispatch per role (Joy-Con → keyboard, panel → remapped gamepad, with a
  small axis deadzone); `EV_SYN` after each device's batch. Keep per-key
  reference counting so nothing releases a key still held by another source.
- **Grab/release every physical device** while Chromium runs. **Hotplug**: on a
  read error, ungrab and re-run discovery so a re-plugged panel recovers.
- **Panic combos** stay on the Joy-Cons.
- Optional: log every discovered device + mapped codes at game start
  (invaluable for debugging / verifying discovery).

### 8.2 `config/10-ignore-joycons.conf`

Add an `InputClass` for the encoder product name so libinput doesn't also turn
the panels into an X pointer/keyboard (stray cursor) between games. Our virtual
pads use different names, so they stay visible to Chromium.

```ini
Section "InputClass"
    Identifier "Ignore arcade panels"
    MatchProduct "<encoder name from discovery>"
    Option "Ignore" "on"
EndSection
```

### 8.3 Docs

- Update `docs/event-specs.md` (two-player panel wiring + remap table), and
  `docs/web-games-setup.md` / `docs/troubleshooting.md` (bridge now handles
  panels; discovery + verification commands).
- Update `docs/README.md` index + deployed-files table once implemented.

`config/openbox-autostart` and `scripts/launch-web-game.sh` need **no** change
(they already start exactly one bridge).

## 9. Verification

Verified on the hardware-mode cabinet on 2026-10-16, with a temporary
gamepad-tester page served through `webgame-server.py`:

- Panel 1 = gamepad index 0, Panel 2 = gamepad index 1 (stable).
- Physical A (Panel 1) → standard button 0 (a); physical A on Panel 2 → the
  same, on index 1.
- The two middle buttons → standard Start (9) and Select (8), matching their
  ES roles.
- The joystick arrives on the standard left-stick axes (axis 0/1); it needs no
  remap and stays untouched by the shim.

## 10. Risks / fallback

Resolved: the uinput approach's open question (does Chromium apply a standard
mapping to a uinput gamepad?) turned out moot — on this stack Chromium will not
reliably enumerate uinput gamepads at all. The shipped shim sidesteps Chromium's
device handling entirely by remapping inside the served page; no fallback is
needed.

## 11. Open items / resume checklist

1. [x] Run the discovery commands (section 7); record names, `phys`/`by-path`,
       and per-button codes for both panels. *(see §7.1)*
2. [x] P1/P2 ordering: `xusb-usb-0:1.2` = P1, `:1.3` = P2 (Chromium index 0/1).
3. [x] Labelled-button ↔ raw-code table (from the ES wizard capture, verified
       with a press test: A → button 0).
4. [x] Implemented — via the in-page shim (§12), not the uinput plan (§8).
5. [x] Deployed to both cabinets and verified on hardware mode (§9).
6. [x] Docs updated (`event-specs.md` input section, this doc, `README.md`
       deployed files).

## 12. Final implementation (2026-10-16)

**How it works.** Chromium exposes the raw DragonRise panels to pages with
button indices in raw code order, which scrambles every button. Instead of
fighting Chromium's device handling, the remap happens *in the page*:
`webgame-server.py` injects a small script into every served HTML page, and
that shim wraps `navigator.getGamepads()` (and normalizes the
`gamepadconnected` event), replacing the panels' `buttons` array with the
standard order. Axes pass through untouched.

Files:

| File | Role |
|---|---|
| `scripts/arcade-pad-shim.js` | The in-page remap (raw→standard button table; `RAW_TO_STD`). |
| `scripts/webgame-server.py` | Injects `<script src="/__arcade_pad_shim.js">` after `<head>` in every `.html` it serves, and serves the shim. HTML is never served from a compressed sidecar, so the tag is always present. |
| `scripts/gamepad-bridge.py` | Unchanged (original): Joy-Cons → keyboard only; it does not touch the panels. |

Mapping (physical → standard index): A→0, B→1, X→2, Y→3, LB→4, RB→5, LT→6,
RT→7, Select→8, Start→9, customL→10 (L3), customR→11 (R3); joystick → left
stick axes 0/1.

Notes:

- Both panels are wired identically, so the same table applies to both; the
  game sees them as gamepad index 0 (Player 1, dock port `:1.2`) and index 1
  (Player 2, `:1.3`).
- Start + Select on **either panel** exits the running game (and Start+Select+B
  reboots), same as the Joy-Cons: `gamepad-bridge.py` watches the encoders
  passively — it never grabs them, so Chromium keeps its Gamepad API view (the
  shim depends on it). Panel raw codes: Start=291, Select=290, B=298. Added and
  verified 2026-10-16 (`Quit combo pressed (panel)` in the bridge log).
- The panels stay visible to EmulationStation as before (its own raw
  `es_input.cfg` profiles still apply); the shim only affects pages served by
  `webgame-server.py`.
- A temporary `PadTest` game (a live gamepad-tester page + logger) was used
  for verification on the hardware-mode cabinet and then removed from the
  cabinets; it lives in the repo as `tools/padtest/` (see
  `panel-input-investigation.md`).

Deploy (both cabinets; from the repo root):

```bash
scp scripts/webgame-server.py scripts/arcade-pad-shim.js switch-hw:~/scripts/
scp scripts/webgame-server.py scripts/arcade-pad-shim.js switch-sw:~/scripts/
ssh switch-hw 'chmod +x ~/scripts/webgame-server.py'
ssh switch-sw 'chmod +x ~/scripts/webgame-server.py'
```

The web game server restarts on every game launch, so the next game picks up
the shim automatically (an already-running game keeps the old page until
relaunch).

## 13. Software-mode cabinet (2026-10-16): different panel wiring, per-cabinet switch

When the two arcade panels were connected to the **software-mode** cabinet
(dock ports `xusb 1.2` / `1.3`; same USB IDs `0079:0006`, same device names),
Chromium enumerated them cold as usual (both panels' `event` + `js` nodes open
in `/proc/<chrome>/fd`), but their **raw button order turned out to differ from
the hardware cabinet's**: these boards are wired in standard order, so the §12
shim — built for the hardware cabinet's scramble — *scrambled* this cabinet's
buttons instead (physical A is raw 0 here; the shim reported it as index 11,
Start as 3).

Raw capture (passive python-evdev reader on panel 1, one press per labelled
button, A→Start in order):

| press | code | raw idx | | press | code | raw idx |
|---|---|---|---|---|---|---|
| A | 288 | 0 | | LT | 294 | 6 |
| B | 289 | 1 | | RT | 295 | 7 |
| X | 290 | 2 | | Select | 296 | 8 |
| Y | 291 | 3 | | Start | 297 | 9 |
| LB | 292 | 4 | | | | |
| RB | 293 | 5 | | | | |

That is exactly the standard Gamepad layout. Cross-check: this cabinet's own
ES wizard capture (`~/.emulationstation/es_temporaryinput.cfg`, Oct 6) has
`a=0, b=1, x=2, y=3` — consistent. The two cabinets' panels are different
encoder boards that happen to share IDs and names.

Side by side (evdev code = 288 + raw index; the shim's `RAW_TO_STD` maps raw
index → standard index on the hardware cabinet):

| button | hardware cabinet: raw / code | software cabinet: code | standard index |
|---|---|---|---|
| A | 11 / 299 | 288 | 0 |
| B | 10 / 298 | 289 | 1 |
| X | 9 / 297 | 290 | 2 |
| Y | 8 / 296 | 291 | 3 |
| LB | 6 / 294 | 292 | 4 |
| RB | 7 / 295 | 293 | 5 |
| LT | 4 / 292 | 294 | 6 |
| RT | 5 / 293 | 295 | 7 |
| Select | 2 / 290 | 296 | 8 |
| Start | 3 / 291 | 297 | 9 |
| customL | 1 / 289 | not captured (presumably 298) | 10 (L3) |
| customR | 0 / 288 | not captured (presumably 299) | 11 (R3) |

Where the numbers live if a cabinet or panel ever changes:

- the wiring selector: one word in `~/scripts/panel-wiring.conf`
  (`standard` | `scrambled`; missing file = `scrambled`),
- the hardware-mode remap table: `RAW_TO_STD` in `scripts/arcade-pad-shim.js`
  (only injected on scrambled cabinets),
- the bridge's panel combo codes: the per-wiring block in
  `scripts/gamepad-bridge.py` (`PANEL_SELECT` / `PANEL_START` / `PANEL_RESET`).

Re-derive the numbers for an unknown panel set with the passive evdev capture
used above (one labelled press per code), or read the ES wizard capture
`~/.emulationstation/es_temporaryinput.cfg`.

**Per-cabinet switch — `~/scripts/panel-wiring.conf`** (one word):

| value | cabinet | web shim | bridge panel codes (Select / Start / B) |
|---|---|---|---|
| `scrambled` (**default when the file is missing**) | hardware mode | injected (§12) | 290 / 291 / 298 |
| `standard` | software mode | **not injected** — the raw order is already standard, remapping would break it | 296 / 297 / 289 |

Both scripts read the file on startup (`gamepad-bridge.py` when the process
starts, `webgame-server.py` at every game launch). The updated scripts were
deployed to both cabinets on 2026-10-16; only the software cabinet carries the
file.

**Verified on the software cabinet** with the PadTest page after the change:
no shim (`DIAG shim_own_prop=false shim_tag_count=0`), raw indices visible —
A → `b=0` (was 11 with the shim applied), Select → `b=8`, and holding
Start+Select → `b=8,9` → the bridge exited the game. Chromium held both panels
open throughout (`/proc/<chrome>/fd`: `event6`+`js0` for `:1.2`,
`event7`+`js1` for `:1.3` on this boot).

**Side observation (same evening):** the Start+Select exit left ES running
but its window `Iconic` → black screen. Recovery is documented in
`docs/troubleshooting.md` ("Cabinet screen is black", case (b)).
