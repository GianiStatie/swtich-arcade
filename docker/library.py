#!/usr/bin/env python3
"""Shared helpers for the container's game menu and API servers.

Both menu-server.py (visual menu, :8125) and api-server.py (URL API, :8123)
scan the same library and swap the same single per-game HTTP server on :8124.
Keeping that logic here avoids two divergent launchers.
"""

import atexit
import os
import socket
import subprocess
import sys
import threading

GAMES_ROOT = os.environ.get("GAMES_ROOT", "/games")
WEB_DIR = os.path.join(GAMES_ROOT, "web")
GAME_PORT = int(os.environ.get("WEBGAME_PORT", "8124"))
WEBGAME_SERVER = os.environ.get("WEBGAME_SERVER", "/opt/arcade/webgame-server.py")

_lock = threading.Lock()
_game_proc = None


def installed_games():
    """Sorted game folder names that contain an index.html at their root."""
    try:
        entries = os.listdir(WEB_DIR)
    except FileNotFoundError:
        return []
    games = []
    for name in entries:
        if not os.path.isdir(os.path.join(WEB_DIR, name)):
            continue
        if os.path.isfile(os.path.join(WEB_DIR, name, "index.html")):
            games.append(name)
    return sorted(games, key=str.casefold)


def _port_open(host, port, timeout=0.2):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        return s.connect_ex((host, port)) == 0


def start_game(name):
    """Point the shared per-game server at <name>. Returns True once it is up.

    Only games present in installed_games() should be passed here (callers
    validate the name, which also prevents path traversal).
    """
    global _game_proc
    game_dir = os.path.join(WEB_DIR, name)

    with _lock:
        if _game_proc is not None and _game_proc.poll() is None:
            _game_proc.terminate()
            try:
                _game_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _game_proc.kill()
        _game_proc = subprocess.Popen(
            [sys.executable, WEBGAME_SERVER, str(GAME_PORT), game_dir],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    for _ in range(100):
        if _port_open("127.0.0.1", GAME_PORT):
            return True
        if _game_proc.poll() is not None:
            return False
        threading.Event().wait(0.1)
    return False


def _shutdown_child():
    if _game_proc is not None and _game_proc.poll() is None:
        _game_proc.terminate()


atexit.register(_shutdown_child)
