#!/bin/bash
# download-from-itch.sh
# Downloads a named upload from your own itch.io game(s) into a target folder,
# using your itch.io API key. This is how the arcade pulls web.zip files
# without a browser session — the API key resolves the upload and fetches it.
#
# The API key is read from $ITCH_API_KEY, or from a key file
# (~/.config/itch_api_key). Treat it like a password; do not commit it.
#
# Usage:
#   ./download-from-itch.sh <game-slug> <upload-filename> [--out <dir>]
#
# Examples:
#   ./download-from-itch.sh dragon-jump dragon-jump-web.zip
#   ./download-from-itch.sh dragon-jump dragon-jump-web.zip --out ~/arcade_games/downloads

set -euo pipefail

API_BASE="https://itch.io/api/1"
KEY="${ITCH_API_KEY:-}"
if [[ -z "${KEY}" ]]; then
  KEY_FILE="${ITCH_API_KEY_FILE:-$HOME/.config/itch_api_key}"
  if [[ -f "${KEY_FILE}" ]]; then
    KEY="$(tr -d '[:space:]' < "${KEY_FILE}")"
  fi
fi
if [[ -z "${KEY}" ]]; then
  echo "ERROR: no itch.io API key. Set ITCH_API_KEY or write the key to ~/.config/itch_api_key" >&2
  exit 1
fi

GAME_SLUG="${1:-}"
UPLOAD_NAME="${2:-}"
TARGET_DIR=""

if [[ -n "${3:-}" ]]; then
  case "${3}" in
    --target|-o) TARGET_DIR="${4:-}";;
    *) TARGET_DIR="${3}" ;;
  esac
fi
TARGET_DIR="${TARGET_DIR:-$(pwd)}"

if [[ -z "${GAME_SLUG}" || -z "${UPLOAD_NAME}" ]]; then
  echo "Usage: $0 <game-slug> <upload-filename> [--target dir]" >&2
  exit 1
fi

# Resolve game slug -> id from the user's game list (older key-in-path API).
GAME_ID=$(curl -s "${API_BASE}/${KEY}/my-games" | python3 -c "
import sys, json
d = json.load(sys.stdin)
games = d.get('games', [])
slug = '${GAME_SLUG}'.rstrip('/')
for g in games:
    if g.get('url','').rstrip('/').endswith('/' + slug):
        print(g['id']); break
")
if [[ -z "${GAME_ID}" ]]; then
  echo "ERROR: could not find game '${GAME_SLUG}' under this API key" >&2
  exit 1
fi

# Find the upload id for the named file.
UPLOAD_ID=$(curl -s "${API_BASE}/${KEY}/game/${GAME_ID}/uploads" | python3 -c "
import sys, json
d = json.load(sys.stdin)
name = '${UPLOAD_NAME}'
for u in d.get('uploads', []):
    if u.get('filename') == name:
        print(u['id']); break
")
if [[ -z "${UPLOAD_ID}" ]]; then
  echo "ERROR: no upload named '${UPLOAD_NAME}' on ${GAME_SLUG}" >&2
  exit 1
fi

# Get the signed download URL (short-lived) and download the file.
SIGNED_URL=$(curl -s "${API_BASE}/${KEY}/upload/${UPLOAD_ID}/download" | python3 -c "import sys,json;print(json.load(sys.stdin)['url'])")

mkdir -p "${TARGET_DIR}"
OUT="${TARGET_DIR}/${UPLOAD_NAME}"
echo "Downloading ${UPLOAD_NAME} -> ${OUT}"
curl -fL -o "${OUT}" "${SIGNED_URL}"
echo "Saved ${OUT} ($(du -h "${OUT}" | cut -f1))"
