#!/usr/bin/env python3
"""Watch es_settings.cfg for a UIMode change to Full (Konami unlock) and force
a full ES restart so it re-reads es_systems.cfg with the RetroPie system shown.

Why: the Konami code sets UIMode=Full and reloads ES in-process, but that reload
does NOT re-read es_systems.cfg (the system list is loaded once at startup). So
the RetroPie system, whose <path> launch-es.sh points at an empty dir in kiosk
mode, stays hidden. This daemon detects the UIMode change, creates
/tmp/es-restart, and SIGTERMs the ES binary. launch-es.sh's restart loop then
re-runs, re-toggles the RetroPie path (UIMode=Full -> retropiemenu), and ES
starts fresh with the admin menu visible.

Reverting to kiosk is handled by the Openbox autostart on the next sddm restart
(it resets UIMode=kiosk and launch-es.sh points the path back at the empty dir).

Usage: uimode-watcher.py   (runs forever; SIGTERM/SIGINT to stop)
"""
import os
import re
import signal
import subprocess
import time

CFG = os.path.expanduser("~/.emulationstation/es_settings.cfg")
RESTART_MARKER = "/tmp/es-restart"
POLL_INTERVAL = 0.5  # seconds

_keep_running = True


def _handle_signal(signum, frame):
    global _keep_running
    _keep_running = False


def _read_uimode():
    try:
        with open(CFG) as f:
            for line in f:
                m = re.search(r'UIMode" value="([^"]*)"', line)
                if m:
                    return m.group(1)
    except (IOError, OSError):
        pass
    return "kiosk"


def _force_es_restart():
    """Create the restart marker and SIGTERM ES so launch-es.sh re-runs."""
    try:
        open(RESTART_MARKER, "w").close()
    except OSError:
        pass
    subprocess.run(
        ["pkill", "-TERM", "-f", "supplementary/emulationstation/emulationstation$"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    print("UIMode watcher started.", flush=True)

    last_mode = _read_uimode()
    while _keep_running:
        time.sleep(POLL_INTERVAL)
        mode = _read_uimode()
        if mode != last_mode:
            if mode == "Full":
                print("UIMode changed to Full; forcing ES restart.", flush=True)
                _force_es_restart()
            last_mode = mode

    print("UIMode watcher stopped.", flush=True)


if __name__ == "__main__":
    main()
