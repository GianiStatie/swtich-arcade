#!/bin/bash
# sync-itch-games.sh
# Pulls web builds from itch.io (or any direct web.zip URL) onto the arcade.
# Reads ~/arcade_games/itch-games.yaml and downloads each listed web.zip,
# unzips it into ~/arcade_games/web/<Name>/ with an index.html at its root.
#
# A game with no downloadable web build is skipped — it is not supported.
#
# Usage: ./sync-itch-games.sh [--force] [--restart-es]
#   --force      Re-download and replace every game, even if already present.
#   --restart-es Restart EmulationStation after a successful sync so newly
#                pulled games appear immediately.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

GAMES_ROOT="${GAMES_ROOT:-/home/tagap/arcade_games}"
CONFIG="${CONFIG:-${GAMES_ROOT}/itch-games.yaml}"
WEB_DIR="${WEB_DIR:-${GAMES_ROOT}/web}"
DL_DIR="${DL_DIR:-${GAMES_ROOT}/downloads}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

FORCE=0
RESTART_ES=0
for arg in "$@"; do
  case "${arg}" in
    --force) FORCE=1 ;;
    --restart-es) RESTART_ES=1 ;;
  esac
done

if ! command -v curl >/dev/null 2>&1; then
  echo "ERROR: curl is required (apt install curl)" >&2
  exit 1
fi
if ! command -v unzip >/dev/null 2>&1; then
  echo "ERROR: unzip is required (apt install unzip)" >&2
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 is required" >&2
  exit 1
fi
if ! python3 -c 'import yaml' >/dev/null 2>&1; then
  echo "ERROR: PyYAML is required (apt install python3-yaml)" >&2
  exit 1
fi

mkdir -p "${WEB_DIR}"

# Parse the YAML with python3 (PyYAML). Each entry must have name + zip.
while IFS=$'\t' read -r name url slug; do
  [[ -z "${name}" || -z "${url}" ]] && continue
  echo "========================================"
  echo "Game: ${name}"
  echo "Zip:  ${url}"
  dest="${WEB_DIR}/${name}"
  if [[ -f "${dest}/index.html" && "${FORCE}" -eq 0 ]]; then
    echo "  Already installed (${dest}/index.html exists). Use --force to re-pull."
    continue
  fi

  dl="${TMP_DIR}/${name}.zip"
  # The zip value may be a direct URL or a glob matched against DL_DIR.
  # If it looks like a local path/glob, resolve it first.
  if [[ ! "${url}" =~ ^https?:// ]]; then
    # Expand glob against DL_DIR; pick the newest matching file.
    matches=(${DL_DIR}/${url})
    local_found=0
    [[ ${#matches[@]} -gt 0 && -f "${matches[0]}" ]] && local_found=1
    # With --force and an itch slug present, always re-fetch from itch so we
    # pick up the latest upload rather than reusing a stale cached zip.
    if [[ "${FORCE}" -eq 1 && -n "${slug}" ]]; then
      echo "  --force with itch slug; fetching '${url}' from itch game '${slug}'..."
      if ! "$SCRIPT_DIR/download-from-itch.sh" "${slug}" "${url}" --target "${DL_DIR}"; then
        echo "  SKIP: could not fetch '${url}' from itch game '${slug}' for ${name}" >&2
        continue
      fi
      matches=(${DL_DIR}/${url})
      local_found=1
    elif [[ "${local_found}" -eq 0 && -n "${slug}" ]]; then
      echo "  No local match for '${url}' in ${DL_DIR}; fetching '${url}' from itch game '${slug}'..."
      if ! "$SCRIPT_DIR/download-from-itch.sh" "${slug}" "${url}" --target "${DL_DIR}"; then
        echo "  SKIP: could not fetch '${url}' from itch game '${slug}' for ${name}" >&2
        continue
      fi
      matches=(${DL_DIR}/${url})
      local_found=1
    fi
    if [[ "${local_found}" -eq 0 ]]; then
      echo "  SKIP: no local file matching '${url}' in ${DL_DIR} for ${name}" >&2
      continue
    fi
    newest=""
    for m in "${matches[@]}"; do
      if [[ -f "${m}" ]] && [[ -z "${newest}" || "${m}" -nt "${newest}" ]]; then
        newest="${m}"
      fi
    done
    cp "${newest}" "${dl}"
    echo "  Using local file: ${newest}"
  else
    echo "  Downloading..."
    if ! curl -fL --retry 3 --retry-delay 2 -o "${dl}" "${url}"; then
      echo "  SKIP: download failed for ${name}" >&2
      continue
    fi
  fi

  unzip_dir="${TMP_DIR}/${name}_src"
  mkdir -p "${unzip_dir}"
  if ! unzip -q -o "${dl}" -d "${unzip_dir}"; then
    echo "  SKIP: web.zip failed to unzip for ${name}" >&2
    continue
  fi

  # The build must have index.html at the root. Handle the common case where
  # the zip wraps everything in a single folder (find it and flatten).
  if [[ ! -f "${unzip_dir}/index.html" ]]; then
    sub=$(find "${unzip_dir}" -maxdepth 1 -type d -mindepth 1 | head -1)
    if [[ -n "${sub}" && -f "${sub}/index.html" ]]; then
      unzip_dir="${sub}"
    else
      echo "  SKIP: no index.html found in web.zip for ${name}" >&2
      continue
    fi
  fi

  echo "  Installing to ${dest}"
  rm -rf "${dest}"
  mv "${unzip_dir}" "${dest}"

  # Marker so EmulationStation detects the game.
  : > "${WEB_DIR}/${name}.web"
  echo "  Done."
done < <(python3 -c "
import sys, yaml
with open('${CONFIG}') as f:
    data = yaml.safe_load(f) or {}
for g in data.get('games', []) or []:
    if not isinstance(g, dict):
        continue
    name = (g.get('name') or '').strip()
    url  = (g.get('zip') or '').strip()
    slug = (g.get('itch') or '').strip()
    if name and url:
        print(name + '\t' + url + '\t' + slug)
")

echo "========================================"
echo "Sync complete."

# Restart EmulationStation so newly pulled games appear immediately.
if [[ "${RESTART_ES}" -eq 1 ]]; then
  echo "Restarting EmulationStation..."
  if ! pkill -x emulationstation 2>/dev/null; then
    pkill -f emulationstation 2>/dev/null || true
  fi
  if pgrep -f emulationstation >/dev/null 2>&1; then
    sudo -n pkill -f emulationstation 2>/dev/null || true
  fi
  sleep 2
  DISPLAY="${DISPLAY:-:0}" setsid emulationstation >/tmp/es_launch.log 2>&1 </dev/null &
  disown 2>/dev/null || true
  echo "EmulationStation restarted."
else
  echo "Restart EmulationStation or refresh the gamelist to see new games."
  echo "Tip: re-run with --restart-es to auto-restart."
fi
