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
  * Chromium's W3C Gamepad API does NOT expose the Joy-Cons (numpads=0), so
    injecting keyboard keys is the only input path and the game needs no
    gamepad mapping.

Usage: gamepad-bridge.py   (runs forever; SIGTERM/SIGINT to stop)
Requires: python3-evdev, /dev/uinput writable (tagap is in the 'input' group).
"""
import select
import signal
import subprocess
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
QUIT_SCRIPT = "/home/tagap/scripts/exit-to-es.sh"

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


def _exit_game():
    subprocess.Popen([QUIT_SCRIPT],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


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


def _process_event(event, ui, held_keys, start_held, select_held):
    """Handle one event; returns (changed_start_held, changed_select_held)."""
    if event.type == ecodes.EV_KEY:
        code, value = event.code, event.value
        # Quit combo: Start + Select together.
        if code == START_BUTTON:
            start_held = (value == 1)
        elif code == SELECT_BUTTON:
            select_held = (value == 1)
        if value == 1 and start_held and select_held:
            print("Quit combo pressed; exiting game.", flush=True)
            _exit_game()
            return start_held, select_held, True

        key = BTN_TO_KEY.get(code)
        if key is not None:
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
            return start_held, select_held, False
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

    return start_held, select_held, False


def _inject_events(ui, dev):
    """Read events from `dev` (exclusively grabbed) and inject keyboard keys.
    Uses select() with a short timeout so Chromium exit is noticed even when no
    events arrive; batches all pending events per wakeup (no per-event fork).
    Runs until Chromium exits or Start+Select is pressed."""
    held_keys = set()
    start_held = False
    select_held = False

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
            start_held, select_held, quit = _process_event(
                event, ui, held_keys, start_held, select_held)
            if quit:
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
                dev.grab()   # exclusive grab: blocks Chromium's gamepad API
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
