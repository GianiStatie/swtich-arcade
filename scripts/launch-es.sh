#!/bin/bash
# Launch EmulationStation in kiosk mode, hiding the RetroPie admin system.
#
# The Konami code (up up down down left right left right B A) entered on the
# Joy-Cons anywhere in ES temporarily unlocks the full (admin) UI mode. This
# wrapper runs its own restart loop (replicating RetroPie's emulationstation.sh)
# and re-toggles the RetroPie system's visibility on every restart, so the
# Konami-triggered restart (which sets UIMode=Full and /tmp/es-restart) shows
# the admin menu, while a fresh session (UIMode=kiosk) hides it.
#
#   * UIMode=kiosk (default) -> hide the RetroPie system (point its <path> at
#     an empty directory so ES finds no games and ignores it).
#   * UIMode=Full  (Konami)  -> restore the RetroPie system's <path> so it
#     reappears for admin access.
#
# The Openbox autostart resets UIMode to kiosk before calling this, so a fresh
# session always starts locked down; the Konami restart (which does NOT go
# through the autostart) preserves UIMode=Full so the admin menu stays visible.
#
# Why not `emulationstation --force-kiosk`? That flag forces kiosk on every ES
# (re)start, overriding the Konami code's switch to FullUI. Editing UIMode in
# es_settings.cfg instead lets the code take effect.
#
# Why not the `hidden=true` gamelist filter? It is broken on this ES build
# (2.11.2rp) - verified: a hidden game is still counted, so the filter cannot
# hide a system. Pointing the system's <path> at an empty directory in
# es_systems.cfg is the reliable way to hide/show the RetroPie system.

CFG="${HOME}/.emulationstation/es_settings.cfg"
ES_SYSTEMS="/etc/emulationstation/es_systems.cfg"
RETROPIE_PATH="/home/tagap/RetroPie/retropiemenu"
HIDDEN_PATH="/home/tagap/RetroPie/roms/empty"
ES_BIN="/opt/retropie/supplementary/emulationstation/emulationstation"

# Replicate the env setup from /usr/bin/emulationstation (tty + SDL driver).
TTY=$(tty)
export TTY="${TTY:8:1}"
if [[ "$WAYLAND_DISPLAY" == wayland* ]]; then
  [[ "$XDG_CURRENT_DESKTOP" == *GNOME ]] || export SDL_VIDEODRIVER=wayland
fi

toggle_retropie() {
  local mode="kiosk"
  if [ -f "${CFG}" ]; then
    mode="$(sed -n 's/.*<string name="UIMode" value="\([^"]*\)".*/\1/p' "${CFG}" | head -1)"
    [ -n "${mode}" ] || mode="kiosk"
  fi
  if [ "${mode}" = "Full" ]; then
    echo "1234" | sudo -S -p "" sed -i "s#<path>${HIDDEN_PATH}</path>#<path>${RETROPIE_PATH}</path>#" "${ES_SYSTEMS}" 2>/dev/null
  else
    echo "1234" | sudo -S -p "" sed -i "s#<path>${RETROPIE_PATH}</path>#<path>${HIDDEN_PATH}</path>#" "${ES_SYSTEMS}" 2>/dev/null
  fi
}

# Restart loop (mirrors RetroPie's emulationstation.sh). Re-toggles on each
# iteration so a Konami restart (UIMode=Full) shows the admin menu.
while true; do
  rm -f /tmp/es-restart /tmp/es-sysrestart /tmp/es-shutdown
  toggle_retropie
  "${ES_BIN}" "$@"
  ret=$?
  [ -f /tmp/es-restart ] && continue
  if [ -f /tmp/es-sysrestart ]; then
    rm -f /tmp/es-sysrestart
    sudo reboot
    break
  fi
  if [ -f /tmp/es-shutdown ]; then
    rm -f /tmp/es-shutdown
    sudo poweroff
    break
  fi
  break
done
exit $ret
