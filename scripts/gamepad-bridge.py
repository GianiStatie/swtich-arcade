#!/usr/bin/env python3
"""Arcade gamepad-to-keyboard bridge.

Reads the Combined Joy-Cons directly via evdev and injects clean keyboard
events into the kernel via /dev/uinput. This replaces the X server's joystick
driver (xserver-xorg-input-joystick) for games, because that driver is a
desktop tool whose "accelerated" axis mapping produces repeated/phantom keys
and bleeds analog-stick drift into wrong directions.

Key design:
  * One key event per physical button press (no "accelerated" repeat spam).
  * Analog stick mapped to directions only past a deadzone, so drift never
    produces a phantom direction.
  * Start + SELECT together calls exit-to-es.sh (returns to EmulationStation).
  * Chromium can still enumerate the Joy-Cons through the paired joydev node
    even while the evdev node is grabbed. The injected page shim hides that
    unused gamepad from games, so injecting keyboard keys remains the input
    path and the game needs no gamepad mapping.

Usage: gamepad-bridge.py   (runs forever; SIGTERM/SIGINT to stop)
Requires: python3-evdev, /dev/uinput writable (tagap is in the 'input' group).

Panic combos (work even when the game/X are frozen):
  Start + Select     exit game back to EmulationStation
  Start + Select + B reboot the cabinet

On cabinets with arcade panels (see panel-wiring.conf for the per-cabinet raw
order) the same combos also work from either arcade panel: a second, passive
watcher reads the DragonRise encoders without grabbing them (Chromium must
keep them for the in-page gamepad shim).
"""
import os
import select
import signal
import subprocess
import threading
import time

try:
    import evdev
    from evdev import UInput, ecodes
except ImportError:
    raise SystemExit("python3-evdev is required: apt install python3-evdev")

# --- Mapping table (edit here for a different game) -------------------------
# evdev BTN code -> kernel KEY code to inject.
BTN_TO_KEY = {
    304: ecodes.KEY_SPACE,  # BTN_SOUTH (A)  -> jump
    305: ecodes.KEY_R,      # BTN_EAST  (B)  -> reset
    307: ecodes.KEY_ESC,    # BTN_NORTH (X)  -> back / cancel
    308: ecodes.KEY_TAB,    # BTN_WEST  (Y)  -> menu
    544: ecodes.KEY_UP,     # BTN_DPAD_UP
    545: ecodes.KEY_DOWN,   # BTN_DPAD_DOWN
    546: ecodes.KEY_LEFT,   # BTN_DPAD_LEFT
    547: ecodes.KEY_RIGHT,  # BTN_DPAD_RIGHT
}

# Analog stick -> digital direction keys. Keyed by (axis, polarity) where
# polarity is -1 or +1. Only active past STICK_DEADZONE so drift is ignored.
STICK_MAP = {
    (0, -1): ecodes.KEY_LEFT,    # ABS_X negative -> Left
    (0, +1): ecodes.KEY_RIGHT,   # ABS_X positive -> Right
    (1, -1): ecodes.KEY_UP,      # ABS_Y negative -> Up
    (1, +1): ecodes.KEY_DOWN,    # ABS_Y positive -> Down
}
# Only translate the left stick; the right stick is left unmapped by default.
STICK_AXES = {0, 1}
STICK_DEADZONE = 0.30   # fraction of full range (32767) before a direction fires
STICK_RANGE = 32767

START_BUTTON = 315  # BTN_START
SELECT_BUTTON = 314 # BTN_SELECT
RESET_BUTTON = 305  # BTN_EAST (B) — also the third panic button
QUIT_SCRIPT = "/home/tagap/scripts/exit-to-es.sh"

# --- Arcade panel panic combos ----------------------------------------------
# The DragonRise encoders must stay readable by Chromium (the in-page gamepad
# shim relies on it), so the panel watcher is passive — it never grabs.
# The two cabinets' panels share USB IDs but not their raw button order;
# panel-wiring.conf next to this script selects the right raw codes
# ("scrambled" default = hardware mode, "standard" = software mode).
# Code = 288 + raw index; see docs/panel-input-investigation.md.
PANEL_NAME = "DragonRise"


def _panel_wiring():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "panel-wiring.conf")
    try:
        with open(path) as f:
            value = f.read().strip().lower()
    except OSError:
        value = ""
    return value if value in ("standard", "scrambled") else "scrambled"


if _panel_wiring() == "standard":
    # Software-mode cabinet: physical Select/Start/B are raw 8/9/1.
    PANEL_SELECT = 296
    PANEL_START = 297
    PANEL_RESET = 289
else:
    # Hardware-mode cabinet (scrambled raw order): Select/Start/B = raw 2/3/10.
    PANEL_SELECT = 290
    PANEL_START = 291
    PANEL_RESET = 298

# Panic combos (state-based; work even when the game/X/GPU are frozen,
# because we read evdev directly):
#   Start + Select      -> exit the game to EmulationStation (exit-to-es.sh)
#   Start + Select + B  -> reboot the cabinet (sudo -n systemctl reboot)

# ----------------------------------------------------------------------------

_keep_running = True


def _handle_signal(signum, frame):
    global _keep_running
    _keep_running = False


def _find_controller():
    for path in evdev.list_devices():
        dev = evdev.InputDevice(path)
        if "Combined Joy-Cons" in (dev.name or ""):
            return dev
        dev.close()
    return None


def _find_panels():
    """Return the arcade panel encoder devices present right now.

    The panels only exist on the hardware-mode cabinet; an empty list is
    normal elsewhere, and on a fresh plug-in.
    """
    panels = []
    for path in evdev.list_devices():
        dev = evdev.InputDevice(path)
        if PANEL_NAME in (dev.name or ""):
            panels.append(dev)
        else:
            dev.close()
    return panels


def _exit_game():
    subprocess.Popen([QUIT_SCRIPT],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _reboot():
    """Hard escape: reboot the cabinet (passwordless sudo drop-in installed)."""
    print("Panic reboot combo (Start+Select+B); rebooting cabinet.", flush=True)
    subprocess.Popen(
        ["sudo", "-n", "systemctl", "reboot"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _panel_watch():
    """Watch the arcade panels for the panic combos, passively (no grab).

    Same combos as the Joy-Cons, gated on a game running:
      Start + Select      -> exit the game (exit-to-es.sh)
      Start + Select + B  -> reboot the cabinet
    Panels can be unplugged/replugged; on read errors we rediscover them.
    """
    while _keep_running:
        panels = _find_panels()
        if not panels:
            time.sleep(3)
            continue
        fds = {p.fd: p for p in panels}
        states = {p.fd: {"start": False, "select": False} for p in panels}
        try:
            while _keep_running:
                ready, _, _ = select.select(list(fds), [], [], 0.5)
                for fd in ready:
                    for event in fds[fd].read():
                        if event.type != ecodes.EV_KEY:
                            continue
                        st = states[fd]
                        if event.code == PANEL_START:
                            st["start"] = (event.value == 1)
                        elif event.code == PANEL_SELECT:
                            st["select"] = (event.value == 1)
                        elif event.code == PANEL_RESET:
                            if event.value == 1 and st["start"] and st["select"]:
                                _reboot()
                                return
                            continue
                        if event.value == 1 and st["start"] and st["select"]:
                            if _chromium_running():
                                print("Quit combo pressed (panel); "
                                      "exiting game.", flush=True)
                                _exit_game()
                                # Require a fresh Start+Select hold to avoid
                                # re-firing while the pair is still held.
                                st["start"] = st["select"] = False
        except (OSError, IOError):
            pass  # panel unplugged; rediscover below
        finally:
            for p in panels:
                try:
                    p.close()
                except (OSError, IOError):
                    pass


def _emit_key(ui, keycode, value):
    """value: 1 = press, 0 = release, 2 = repeat."""
    if keycode is None:
        return
    ui.write(ecodes.EV_KEY, keycode, value)
    ui.syn()


_chromium_cache = None
_chromium_cache_at = 0.0
CHROMIUM_CACHE_TTL = 1.0  # seconds; re-check pgrep at most this often


def _chromium_running():
    """Return whether Chromium is running, caching the result briefly so the
    hot input path never spawns a pgrep process per event."""
    global _chromium_cache, _chromium_cache_at
    now = time.monotonic()
    if _chromium_cache is not None and now - _chromium_cache_at < CHROMIUM_CACHE_TTL:
        return _chromium_cache
    try:
        out = subprocess.run(
            ["pgrep", "-f", "/opt/chromium.org/chromium/chrome"],
            capture_output=True).stdout.strip()
        _chromium_cache = bool(out)
    except Exception:
        _chromium_cache = False
    _chromium_cache_at = now
    return _chromium_cache


def _process_event(event, ui, held_keys, buttons):
    """Handle one event; returns True when the game session should end.

    `buttons` is a dict of the panic-combo button hold states:
    start / select / reset (True while physically held).
    Combos:
      Start+Select        (on the press that completes the pair)
      Start+Select+B      (B press while the pair is held -> hard reboot)
    """
    if event.type == ecodes.EV_KEY:
        code, value = event.code, event.value
        if code == START_BUTTON:
            buttons["start"] = (value == 1)
        elif code == SELECT_BUTTON:
            buttons["select"] = (value == 1)
        elif code == RESET_BUTTON:
            buttons["reset"] = (value == 1)
            # B is also the games' reset key — only block it while a panic
            # combo is armed (Start+Select held), otherwise pass it through.
            if value == 1 and buttons["start"] and buttons["select"]:
                _reboot()
                return True
        if value == 1 and buttons["start"] and buttons["select"] \
                and code != RESET_BUTTON:
            print("Quit combo pressed; exiting game.", flush=True)
            _exit_game()
            return True

        key = BTN_TO_KEY.get(code)
        if key is not None:
            # While Start+Select are held (combo armed) suppress normal keys
            # so the menu doesn't receive spurious input mid-combo.
            if buttons["start"] and buttons["select"]:
                return False
            if value == 1:
                if key not in held_keys:
                    _emit_key(ui, key, 1)
                    held_keys.add(key)
            elif value == 0 and key in held_keys:
                _emit_key(ui, key, 0)
                held_keys.discard(key)

    elif event.type == ecodes.EV_ABS:
        code, value = event.code, event.value
        if code not in STICK_AXES:
            return False
        # Determine the digital direction this axis value maps to.
        target = None
        if value < -STICK_DEADZONE * STICK_RANGE:
            target = STICK_MAP.get((code, -1))
        elif value > STICK_DEADZONE * STICK_RANGE:
            target = STICK_MAP.get((code, +1))

        # For this axis, find which keys we currently hold (both
        # polarities of the same axis share a key pair).
        axis_keys = [STICK_MAP[(code, s)] for s in (-1, +1)
                     if (code, s) in STICK_MAP]
        currently = held_keys & set(axis_keys)

        if target is None:
            # Returned to center: release whatever direction is held.
            for k in currently:
                _emit_key(ui, k, 0)
                held_keys.discard(k)
        elif target not in currently:
            # New direction on this axis: release the old, press new.
            for k in currently:
                _emit_key(ui, k, 0)
                held_keys.discard(k)
            _emit_key(ui, target, 1)
            held_keys.add(target)

    return False


def _inject_events(ui, dev):
    """Read events from `dev` (exclusively grabbed) and inject keyboard keys.
    Uses select() with a short timeout so Chromium exit is noticed even when no
    events arrive; batches all pending events per wakeup (no per-event fork).
    Runs until Chromium exits or a panic combo ends the session."""
    held_keys = set()
    buttons = {"start": False, "select": False, "reset": False}

    while _keep_running and _chromium_running():
        # Block up to 0.5s for events; also lets us re-check Chromium state.
        ready, _, _ = select.select([dev.fd], [], [], 0.5)
        if not ready:
            continue

        # Batch-read everything currently available from the kernel buffer.
        events = dev.read()
        for event in events:
            if not _keep_running:
                return
            if _process_event(event, ui, held_keys, buttons):
                return

    # Release anything still held before returning to the menu watch.
    for k in held_keys:
        try:
            _emit_key(ui, k, 0)
        except OSError:
            pass


def main():
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    print("Arcade gamepad bridge started.", flush=True)

    # Register every key we may emit. uinput requires this up front.
    ui = UInput(events={
        evdev.ecodes.EV_KEY: sorted(set(BTN_TO_KEY.values())
                                    | set(STICK_MAP.values())),
    }, name="arcade-bridge")

    # Passive panel watcher for the panic combos (hardware-mode cabinet);
    # never grabs, so Chromium keeps its Gamepad API view of the panels.
    threading.Thread(target=_panel_watch, daemon=True).start()

    try:
        while _keep_running:
            # Wait for a game (Chromium) to start. While no game is running
            # (EmulationStation navigating), do NOT grab the controller so ES
            # can use the Joy-Cons via SDL.
            while _keep_running and not _chromium_running():
                time.sleep(0.5)
            if not _keep_running:
                break

            dev = _find_controller()
            if dev is None:
                print("Controller not found; waiting.", flush=True)
                while _keep_running and dev is None:
                    time.sleep(1)
                    dev = _find_controller()
                if not _keep_running:
                    break

            print("Game detected; grabbing controller.", flush=True)
            try:
                dev.grab()   # keep the keyboard bridge as the input path
                _inject_events(ui, dev)
            except (OSError, IOError) as exc:
                print("grab/inject error: %s" % exc, flush=True)
            finally:
                try:
                    dev.ungrab()
                except (OSError, IOError):
                    pass
                dev.close()
            print("Game ended; releasing controller.", flush=True)
    finally:
        ui.close()
        print("Arcade gamepad bridge stopped.", flush=True)


if __name__ == "__main__":
    main()
