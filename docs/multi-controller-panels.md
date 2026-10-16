# Multi-Player Arcade Panels — Two More Controllers

**Status: DESIGNED, NOT IMPLEMENTED.** Discovery (reading the real device
names/codes off the Switch) has not been done yet, so no code changes exist.
This doc is a self-contained handoff so the work can resume on another machine.

Repo: `git@github.com:GianiStatie/swtich-arcade.git` (note the `swtich` typo —
it is the correct remote). Working tree is clean at commit `f861ee8`.

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

## 8. Implementation plan

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

- `evtest` against `arcade-p1` / `arcade-p2` to confirm the emitted codes.
- A browser gamepad-tester page: confirm the indices are standard and the
  P1/P2 order is stable across reboots / re-plugin.
- Target game: panel 1 = P1, panel 2 = P2, no R3/R4 mix-up.
- Confirm ES still navigates between games (it reads gamepads via SDL/evdev and
  must not be disturbed).

## 10. Risks / fallback

The one unverifiable-from-here question: whether Chromium applies a *standard*
mapping to a `uinput` gamepad. If indices come out wrong, options in order:

1. Tune the exposed capability set (which buttons/axes, their order/ranges).
2. Name the virtual device after a known pad (may or may not affect Chromium's
   mapping selection).
3. Last resort: keyboard-inject the panels too (panel 1 = P1 keys; panel 2 = a
   distinct P2 key set the game must support).

## 11. Open items / resume checklist

1. [ ] Run the discovery commands (section 7); record names, `phys`/`by-path`,
       and per-button codes for both panels.
2. [ ] Decide P1/P2 ordering from the two `by-path` entries (e.g. left/front
       USB port = P2/P1) and pin it in the bridge config.
3. [ ] Implement section 8.
4. [ ] Deploy and verify (section 9).
5. [ ] Update docs (section 8.3) and commit.

Deploy commands (from the repo root, once implemented):

```bash
scp scripts/gamepad-bridge.py switch:~/scripts/
scp config/10-ignore-joycons.conf switch:/tmp/
ssh switch 'chmod +x ~/scripts/gamepad-bridge.py'
ssh switch 'echo 1234 | sudo -S -p "" cp /tmp/10-ignore-joycons.conf /etc/X11/xorg.conf.d/10-ignore-joycons.conf'
# restart the bridge / session to pick up changes:
ssh switch 'pkill -f gamepad-bridge.py; sudo systemctl restart sddm'
```
