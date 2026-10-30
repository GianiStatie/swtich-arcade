#!/bin/bash
# Kill the active Chromium kiosk and return to EmulationStation.
# Called by the gamepad bridge (Start+Select), the in-game Quit button
# (via exit-server.py), or manually.
# Place in /home/tagap/scripts/exit-to-es.sh and chmod +x.

# Force-run as tagap with the correct HOME so EmulationStation reads its real
# config from /home/tagap/.emulationstation/, not from a privileged HOME path
# like /root, which would crash with "we cannot find any systems".
if [[ "$(id -un)" != "tagap" ]]; then
  exec sudo -u tagap -H /home/tagap/scripts/exit-to-es.sh "$@"
fi

# Kill the local web-game HTTP server (launched by launch-web-game.sh) so it
# doesn't hold the game directory or leave a stale port open. The port is
# per-game now, so match the server by name rather than a fixed number.
pkill -f "[w]ebgame-server.py" 2>/dev/null || true
pkill -f "[-]m http.server" 2>/dev/null || true
pkill -f "[b]usybox httpd -f -p" 2>/dev/null || true

# Force-kill Chromium (kiosk instance). Using -9 (SIGKILL) avoids the graceful
# window-close that can trigger an "Exit Openbox?" prompt. The real binary is
# /opt/chromium.org/chromium/chrome with --kiosk, not "chromium-browser".
pkill -9 -f "/opt/chromium.org/chromium/chrome.*--kiosk" 2>/dev/null || true
pkill -9 -f "chromium-browser.*--kiosk" 2>/dev/null || true

# Give it a moment to release the display
sleep 1

# EmulationStation is the parent session; if it's still running it will
# regain focus. If not, relaunch it as tagap on :0 with the correct HOME.
if ! pgrep -f "/opt/retropie/supplementary/emulationstation/emulationstation" >/dev/null 2>&1; then
  export HOME=/home/tagap
  export DISPLAY=:0
  setsid emulationstation >/tmp/es_launch.log 2>&1 </dev/null &
  disown 2>/dev/null || true
fi

exit 0
