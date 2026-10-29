#!/bin/bash
set -u

if [[ "$(id -un)" != "tagap" ]]; then
  exec sudo -u tagap -H "$0" "$@"
fi

export HOME=/home/tagap
export DISPLAY=:0
export XAUTHORITY=/home/tagap/.Xauthority

ES_BIN="/opt/retropie/supplementary/emulationstation/emulationstation"
ES_PATTERN="supplementary/[e]mulationstation/emulationstation"
WRAPPER_PATTERN="scripts/[l]aunch-es.sh"

/home/tagap/scripts/exit-to-es.sh >/dev/null 2>&1 || true

old_pid="$(pgrep -f "$ES_PATTERN" | head -1 || true)"
if [ -z "$old_pid" ]; then
  setsid "$ES_BIN" >/tmp/es_launch.log 2>&1 </dev/null &
  disown 2>/dev/null || true
  exit 0
fi

touch /tmp/es-restart
kill -TERM "$old_pid" 2>/dev/null || true

for _ in $(seq 1 20); do
  sleep 0.5
  new_pid="$(pgrep -f "$ES_PATTERN" | head -1 || true)"
  if [ -n "$new_pid" ] && [ "$new_pid" != "$old_pid" ]; then
    xset dpms force on 2>/dev/null || true
    exit 0
  fi
done

pkill -KILL -f "$ES_PATTERN" 2>/dev/null || true
pkill -TERM -f "$WRAPPER_PATTERN" 2>/dev/null || true
rm -f /tmp/es-restart
setsid /home/tagap/scripts/launch-es.sh >/tmp/es_launch.log 2>&1 </dev/null &
disown 2>/dev/null || true
xset dpms force on 2>/dev/null || true
exit 0
