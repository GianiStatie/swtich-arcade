#!/usr/bin/env python3
"""itch.io collection watcher for the arcade.

Polls one itch.io collection and keeps the games on the cabinet in sync:

  * new game in the collection      -> download + install
  * re-uploaded build (md5 change)  -> download + install
  * game removed from the collection-> uninstall (prune)
  * EmulationStation restart        -> after a sync that changed something

Only ever touches games while no web game is running: the sync is skipped when
Chromium is running, and a change detected mid-game is applied at the next
idle poll. State lives in <GAMES_ROOT>/.itch-state.json; it is written only
after a successful install, so failed downloads simply retry next poll.
Prune deletes a local game only when it is actually absent from the
collection listing; a failed upload lookup (rate limit, network blip) keeps
the local copy and retries next poll.

API notes (probed 2026-10-06, from the Switch):
  * Modern API (api.itch.io, Bearer key) reads the collection. Pagination via
    ?page=N until an empty page.
  * Legacy API (itch.io/api/1/<key>/...) resolves uploads for games you don't
    own (free games), plus the signed download URL per upload.
  * Pick the web build by upload type == "html" (fallback: -web- filename).
  * HTTP 429 is honored: Retry-After/exponential backoff, and the rest of the
    cycle is skipped so the watcher does not keep hammering the API.

Config: <GAMES_ROOT>/itch-games.yaml (see config/itch-games.yaml in the repo):
  collection: 8014540     # itch.io collection id (required)
  prune: true             # uninstall games removed from the collection
  poll_seconds: 300       # seconds between polls (updates appear on the
                          # first idle poll after an upload)
  restart_es: true        # restart EmulationStation after a change
  games: []               # optional per-game overrides:
                          #   itch: <game id>   the game this applies to
                          #   name: <folder>    display name / folder name
                          #   exclude: true     never install
                          #   upload: <file>    specific upload filename

Usage: python3 itch-watcher.py [--once] [--force]
  --once    run a single poll cycle and exit (main loop does one per
            poll_seconds)
  --force   treat every game as changed (initial pull / repair)
"""

import json
import os
import random
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

try:
    import yaml
except ImportError:
    yaml = None

API_BASE = "https://api.itch.io"
LEGACY_BASE = "https://itch.io/api/1"
STATE_FILE = ".itch-state.json"

RATE_LIMIT_FLOOR = 30
RATE_LIMIT_CAP = 900
GAME_REQUEST_DELAY = 1.0
GAME_REQUEST_JITTER = 0.5

GAMES_ROOT = os.environ.get("GAMES_ROOT", "/home/tagap/arcade_games")
CONFIG_PATH = os.environ.get("CONFIG_PATH",
                             os.path.join(GAMES_ROOT, "itch-games.yaml"))
KEY_FILE = os.environ.get("ITCH_API_KEY_FILE",
                          os.path.expanduser("~/.config/itch_api_key"))

CHROME_PATTERNS = ("/opt/chromium.org/chromium/chrome",)
CHROME_CHECK_TTL = 5.0


class RateLimited(Exception):
    def __init__(self, retry_after=None, message="rate limited"):
        super().__init__(message)
        self.retry_after = retry_after


def _retry_after_seconds(value):
    if not value:
        return None
    try:
        return max(1, int(float(value)))
    except (TypeError, ValueError):
        pass
    try:
        when = parsedate_to_datetime(value)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return max(1, int((when - datetime.now(timezone.utc)).total_seconds()))
    except Exception:
        return None


def _rate_limit_backoff(retry_after, streak):
    if retry_after is not None:
        delay = retry_after
    else:
        delay = RATE_LIMIT_FLOOR * (2 ** min(streak, 6))
    delay = max(RATE_LIMIT_FLOOR, min(RATE_LIMIT_CAP, delay))
    return delay + random.uniform(0, min(30.0, delay * 0.1))


def _sleep_interruptible(seconds, running):
    deadline = time.monotonic() + seconds
    while running["flag"]:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return True
        time.sleep(min(0.25, remaining))
    return False


def _pace_requests():
    time.sleep(GAME_REQUEST_DELAY + random.uniform(0, GAME_REQUEST_JITTER))


def log(msg):
    print("[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg), flush=True)


def read_key():
    with open(KEY_FILE, "r") as f:
        key = f.read().strip()
    if not key:
        raise RuntimeError("itch API key missing in %s" % KEY_FILE)
    return key


def http_json(url, key=None, timeout=20):
    req = urllib.request.Request(url)
    if key and url.startswith(API_BASE):
        req.add_header("Authorization", "Bearer " + key)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise RateLimited(_retry_after_seconds(
                e.headers.get("Retry-After")), "HTTP 429") from e
        raise


def download_to(url, dest, timeout=600):
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, \
                open(dest, "wb") as f:
            shutil.copyfileobj(resp, f)
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise RateLimited(_retry_after_seconds(
                e.headers.get("Retry-After")), "HTTP 429") from e
        raise


# --------------------------------------------------------------------------
# game-running check (mirrors gamepad-bridge.py semantics)
# --------------------------------------------------------------------------

_chrome_cache = None
_chrome_cache_at = 0.0


def game_running():
    """True while a web game is running (Chromium kiosk process exists)."""
    global _chrome_cache, _chrome_cache_at
    now = time.monotonic()
    if _chrome_cache is not None and now - _chrome_cache_at < CHROME_CHECK_TTL:
        return _chrome_cache
    try:
        out = subprocess.run(
            ["pgrep", "-f", "|".join(CHROME_PATTERNS)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5
        ).stdout
        _chrome_cache = bool(out.strip())
    except Exception:
        _chrome_cache = False
    _chrome_cache_at = now
    return _chrome_cache


# --------------------------------------------------------------------------
# config + state
# --------------------------------------------------------------------------

def load_config():
    with open(CONFIG_PATH) as f:
        data = yaml.safe_load(f) or {}
    if not data.get("collection"):
        raise RuntimeError("no 'collection:' id in %s" % CONFIG_PATH)
    overrides = {}
    for g in data.get("games") or []:
        if isinstance(g, dict) and g.get("itch"):
            overrides[int(g["itch"])] = g
    return {
        "collection": int(data["collection"]),
        "prune": bool(data.get("prune", True)),
        "poll_seconds": int(data.get("poll_seconds", 60)),
        "restart_es": bool(data.get("restart_es", True)),
        "overrides": overrides,
    }


def load_state():
    path = os.path.join(GAMES_ROOT, STATE_FILE)
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    path = os.path.join(GAMES_ROOT, STATE_FILE)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=1, sort_keys=True)
    os.replace(tmp, path)


# --------------------------------------------------------------------------
# itch API
# --------------------------------------------------------------------------

def collection_games(collection_id, key):
    """All games in the collection: {game_id: {title, url}}"""
    games = {}
    page = 1
    while True:
        url = "%s/collections/%d/collection-games?page=%d" % (
            API_BASE, collection_id, page)
        data = http_json(url, key)
        batch = data.get("collection_games", [])
        if not batch:
            break
        for item in batch:
            g = item.get("game") or {}
            if g.get("id"):
                games[int(g["id"])] = {
                    "title": g.get("title") or ("Game %d" % g["id"]),
                    "url": g.get("url", ""),
                }
        if len(batch) < len(games) and page > 1:
            break  # safety; collections are small here
        page += 1
        if page > 50:
            break
    return games


def html_upload(game_id, key):
    """The web build upload for a game: highest-preference entry."""
    url = "%s/%s/game/%d/uploads" % (LEGACY_BASE, key, game_id)
    try:
        data = http_json(url)
    except RateLimited:
        raise
    except Exception as e:
        log("game %d: uploads fetch failed: %s" % (game_id, e))
        return None
    uploads = [u for u in data.get("uploads", [])
               if not (u.get("demo") or u.get("preorder"))]
    html = [u for u in uploads if u.get("type") == "html"]
    if not html:
        html = [u for u in uploads
                if "web" in (u.get("filename") or "").lower()
                and (u.get("filename") or "").lower().endswith(".zip")]
    if not html:
        log("game %d: no HTML upload on itch (not installable)" % game_id)
        return None
    html.sort(key=lambda u: (u.get("updated_at") or "", u.get("id") or 0),
              reverse=True)
    return html[0]


def download_upload_key(game_id, upload_id, key):
    """Legacy signed-URL route (works for free games we don't own)."""
    url = "%s/%s/upload/%d/download" % (LEGACY_BASE, key, upload_id)
    try:
        data = http_json(url)
    except RateLimited:
        raise
    except Exception:
        data = None
    if data and data.get("url"):
        return data["url"]
    return None


# --------------------------------------------------------------------------
# install
# --------------------------------------------------------------------------

def install_game(game_id, title, upload, key, web_dir, dl_dir):
    """Download + install one game. Returns the install marker to record."""
    name = title.strip() or ("Game %d" % game_id)
    dest = os.path.join(web_dir, name)
    marker = os.path.join(web_dir, name + ".web")

    signed = download_upload_key(game_id, upload["id"], key)
    if not signed:
        log("%s: could not get signed download URL" % name)
        return None

    with tempfile.TemporaryDirectory() as tmp:
        zpath = os.path.join(tmp, "web.zip")
        try:
            download_to(signed, zpath)
        except RateLimited:
            raise
        except Exception as e:
            log("%s: download failed: %s" % (name, e))
            return None

        src = os.path.join(tmp, "src")
        os.makedirs(src, exist_ok=True)
        try:
            with zipfile.ZipFile(zpath) as z:
                safe = lambda n: os.path.normpath(n).lstrip("/\\") and not os.path.normpath(n).startswith("..")  # noqa: E731
                for info in z.infolist():
                    if info.is_dir() or not safe(info.filename):
                        continue
                    z.extract(info, src)
        except zipfile.BadZipFile:
            log("%s: bad zip from itch" % name)
            return None

        # index.html must exist at the root; flatten a single wrapping folder.
        if not os.path.isfile(os.path.join(src, "index.html")):
            subs = [d for d in os.listdir(src)
                    if os.path.isdir(os.path.join(src, d))]
            for sub in sorted(subs):
                if os.path.isfile(os.path.join(src, sub, "index.html")):
                    src = os.path.join(src, sub)
                    break
            else:
                log("%s: no index.html in the upload zip" % name)
                return None

        # atomic-ish swap: new folder first, then replace.
        staging = os.path.join(web_dir, name + ".new")
        if os.path.exists(staging):
            shutil.rmtree(staging)
        shutil.move(src, staging)
        if os.path.exists(dest):
            shutil.rmtree(dest)
        os.rename(staging, dest)
        with open(marker, "w") as f:
            f.write("")

    build = upload.get("build") or {}
    md5 = upload.get("md5_hash")
    if md5:
        ident = "md5 %s..." % md5[:8]
    elif build.get("version") is not None:
        ident = "build v%s" % build["version"]
    else:
        ident = "no md5/build"
    log("%s: installed (%d bytes upload, %s)" % (
        name, upload.get("size", 0), ident))
    return {
        "md5": md5,
        "updated_at": upload.get("updated_at"),
        "upload_id": upload.get("id"),
        "build_id": build.get("id"),
        "build_version": build.get("version"),
        "title": title,
    }


def remove_game(name, web_dir):
    for path in (
            os.path.join(web_dir, name),
            os.path.join(web_dir, name + ".web")):
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            elif os.path.exists(path):
                os.remove(path)
        except Exception as e:
            log("prune %s: %s failed: %s" % (name, path, e))
    log("%s: pruned (removed from collection)" % name)


def restart_es():
    """Restart EmulationStation so the menu picks up the new library.

    When the ES wrapper (launch-es.sh) is running it owns a restart loop:
    creating /tmp/es-restart before ES exits makes the wrapper relaunch ES
    itself, keeping the kiosk-mode setup (UIMode, RetroPie toggle, TTY env)
    intact. Only without a wrapper do we launch the raw binary ourselves.
    """
    try:
        wrapper = subprocess.run(
            ["pgrep", "-f", "[l]aunch-es.sh"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=5).returncode == 0
        if wrapper:
            open("/tmp/es-restart", "w").close()
        subprocess.run(["pkill", "-f", "emulationstation"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=5)
        if wrapper:
            log("EmulationStation restart requested "
                "(launch-es.sh will relaunch it)")
            return
        time.sleep(2)
        env = dict(os.environ, DISPLAY=os.environ.get("DISPLAY", ":0"))
        subprocess.Popen(
            ["setsid", "emulationstation"],
            stdout=open("/tmp/es_watchdog_restart.log", "a"),
            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            env=env, start_new_session=True)
        log("EmulationStation restarted to show updated games")
    except Exception as e:
        log("ES restart failed: %s" % e)


# --------------------------------------------------------------------------
# main cycle
# --------------------------------------------------------------------------

def sync_once(cfg, key, state, force=False):
    web_dir = os.path.join(GAMES_ROOT, "web")
    dl_dir = os.path.join(GAMES_ROOT, "downloads")
    os.makedirs(web_dir, exist_ok=True)
    os.makedirs(dl_dir, exist_ok=True)

    games = collection_games(cfg["collection"], key)
    if not games:
        log("collection empty or unreadable; nothing to do")
        return False

    overrides = cfg["overrides"]
    changed = []            # [(name, game_id, upload, reason)]
    wanted = {}             # folder name -> state entry (if installable)
    unresolved = set()      # in the collection, upload lookup failed this cycle
    uploads_cache = {}

    for game_id, meta in sorted(games.items()):
        ov = overrides.get(game_id, {})
        name = (ov.get("name") or meta["title"]).strip()
        if ov.get("exclude"):
            continue
        up = html_upload(game_id, key) if ov.get("upload") is None else None
        if ov.get("upload"):
            # override names a specific upload filename: find it
            url = "%s/%s/game/%d/uploads" % (LEGACY_BASE, key, game_id)
            try:
                got = http_json(url).get("uploads", [])
            except RateLimited:
                raise
            except Exception:
                got = []
            match = [u for u in got
                     if (u.get("filename") or "") == ov["upload"]]
            up = match[0] if match else None
            if up is None:
                log("%s: override upload %r not found on itch" % (
                    name, ov["upload"]))
        _pace_requests()
        if up is None:
            unresolved.add(name)
            continue
        build = up.get("build") or {}
        uploads_cache[game_id] = up
        wanted[name] = {
            "md5": up.get("md5_hash"),
            "updated_at": up.get("updated_at"),
            "upload_id": up.get("id"),
            "build_id": build.get("id"),
            "build_version": build.get("version"),
            "title": meta["title"],
        }
        prev = state.get("games", {}).get(name)
        if force or prev is None or (not os.path.exists(
                os.path.join(web_dir, name, "index.html"))):
            changed.append((name, game_id, up, "new/missing"))
        elif (prev.get("md5") != up.get("md5_hash")
                or prev.get("updated_at") != up.get("updated_at")
                or (prev.get("build_id") is not None
                    and prev.get("build_id") != build.get("id"))):
            changed.append((name, game_id, up, "updated on itch"))

    # prune: installed games no longer in the collection
    removed = []
    if cfg["prune"]:
        for entry in state.get("games", {}):
            if entry not in wanted and entry not in unresolved:
                removed.append(entry)

    if not changed and not removed:
        return False

    if game_running():
        log("game running; deferring %d change(s) until idle" % len(changed))
        return False

    for name, game_id, up, reason in changed:
        if game_running():
            log("game started mid-sync; %s deferred to next cycle" % name)
            break
        log("%s: %s -> syncing" % (name, reason))
        got = install_game(game_id, name, up, key, web_dir, dl_dir)
        if got is None:
            log("%s: install failed; will retry next cycle" % name)
            continue
        state.setdefault("games", {})[name] = got
        save_state(state)

    for name in removed:
        if game_running():
            log("game running; prune deferred")
            break
        remove_game(name, web_dir)
        state.get("games", {}).pop(name, None)

    save_state(state)
    return True


def main():
    os.makedirs(GAMES_ROOT, exist_ok=True)
    cfg = load_config()
    key = read_key()
    state = load_state()

    run_once = "--once" in sys.argv
    force = "--force" in sys.argv
    running = {"flag": True}

    def _stop(_sig, _frm):
        running["flag"] = False

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    log("itch watcher: collection %d, poll %ds" % (
        cfg["collection"], cfg["poll_seconds"]))

    rate_limit_streak = 0
    while running["flag"]:
        try:
            did = sync_once(cfg, key, state, force=force)
            force = False
            rate_limit_streak = 0
            if did and cfg["restart_es"] and not game_running():
                restart_es()
        except RateLimited as e:
            rate_limit_streak += 1
            wait = _rate_limit_backoff(e.retry_after, rate_limit_streak)
            log("rate limited by itch; backing off %.0fs (%s)" % (wait, e))
            if run_once:
                break
            if not _sleep_interruptible(wait, running):
                break
            continue
        except RuntimeError as e:
            log("config error: %s" % e)
            break
        except Exception as e:
            log("cycle error: %r" % e)
        if run_once:
            break
        delay = cfg["poll_seconds"] + random.uniform(
            0, max(1.0, cfg["poll_seconds"] * 0.1))
        if not _sleep_interruptible(delay, running):
            break

    log("itch watcher stopped")


if __name__ == "__main__":
    main()