#!/usr/bin/env python3
"""Arcade API + status server (library mode), bound to :8123.

Exposes the installed library, a status page, and launches games, so the whole
thing is drivable from outside the container:

  GET /                     -> status page: running banner, API/uptime, library
                               path + volume, clickable game links, how-to
  GET /?format=json         -> {"games": [{"name", "play"}]}
  GET /?format=text         -> one play URL per line
  GET /?callback=<fn>       -> JSONP (for file:// pages that can't fetch)
  GET /play/<name>          -> (re)start the shared :8124 server for <name>,
                               then 302-redirect to http://<host>:8124/index.html
  GET /exit                 -> same contract as the arcade's exit-server.py:
                               returns OK (CORS *) and kills Chromium (games'
                               in-game Quit button).

In library mode this replaces scripts/exit-server.py (kept verbatim for
single-game interactive mode). Play URLs are selector URLs: :8124 serves one
game at a time, so every play link swaps the server first.
"""

import html
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from library import GAME_PORT, WEB_DIR, installed_games, start_game  # noqa: E402

API_HOST = os.environ.get("API_HOST", "0.0.0.0")
API_PORT = int(os.environ.get("API_PORT", "8123"))
EXIT_SCRIPT = os.environ.get("EXIT_SCRIPT", "/home/tagap/scripts/exit-to-es.sh")
GAMES_VOLUME_NAME = os.environ.get("GAMES_VOLUME_NAME", "arcade-contract-sim-games")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _base_url(handler):
    """Absolute base URL for links, derived from the request's Host header."""
    host = handler.headers.get("Host") or "127.0.0.1:{}".format(API_PORT)
    return "http://{}".format(host)


def _play_host(handler):
    """Hostname to use for the :GAME_PORT redirect (drop the API port)."""
    host = handler.headers.get("Host") or "127.0.0.1"
    name = host.rsplit(":", 1)[0] if ":" in host else host
    return name or "127.0.0.1"


def _json_str(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _uptime_str():
    """Container uptime from /proc/uptime, or None."""
    try:
        with open("/proc/uptime") as f:
            secs = int(float(f.read().split()[0]))
    except Exception:
        return None
    m, s = divmod(secs, 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    if d:
        return "{}d {}h {}m".format(d, h, m)
    if h:
        return "{}h {}m".format(h, m)
    return "{}m {}s".format(m, s)


def _cgroup_cpu_cores():
    """Effective CPU limit from cgroup v2 cpu.max, as a core count, or None."""
    try:
        with open("/sys/fs/cgroup/cpu.max") as f:
            quota, period = f.read().split()
        if quota == "max":
            return None
        return int(quota) / int(period)
    except Exception:
        return None


def _cgroup_mem_gb():
    """Memory limit from cgroup v2 memory.max, in GiB, or None."""
    try:
        with open("/sys/fs/cgroup/memory.max") as f:
            val = f.read().strip()
        if val == "max":
            return None
        return int(val) / (1024 ** 3)
    except Exception:
        return None


def _fmt_cores(cores):
    if cores is None:
        return "unlimited"
    txt = "{:.2f}".format(cores).rstrip("0").rstrip(".")
    return txt + (" core" if txt == "1" else " cores")


def _fmt_gb(gb):
    if gb is None:
        return "unlimited"
    txt = "{:.2f}".format(gb).rstrip("0").rstrip(".")
    return txt + " GiB"


def _games_json(handler, games):
    base = _base_url(handler)
    items = ",\n".join(
        '  {{"name": {n}, "play": {p}}}'.format(
            n=_json_str(name),
            p=_json_str("{}/play/{}".format(base, urllib.parse.quote(name))),
        )
        for name in games
    )
    return '{{"games": [\n{}\n]}}\n'.format(items)


# --------------------------------------------------------------------------
# HTML status page
# --------------------------------------------------------------------------

PAGE_CSS = """
:root{color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:#0b0d12;color:#e8ecf1;
     font:16px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
.wrap{max-width:860px;margin:0 auto;padding:32px 24px 60px}
h1{margin:0;font-size:24px;display:flex;align-items:center;gap:12px}
h2{font-size:14px;text-transform:uppercase;letter-spacing:.08em;color:#8b95a5;
   margin:34px 0 10px}
.pill{display:inline-flex;align-items:center;gap:8px;padding:4px 12px;border-radius:999px;
      font-size:13px;font-weight:600;background:#0f2a1a;color:#4ade80;border:1px solid #1c3d29}
.dot{width:9px;height:9px;border-radius:50%;background:#4ade80;
     box-shadow:0 0 0 4px rgba(74,222,128,.15)}
.meta{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-top:18px}
.card{background:#12161d;border:1px solid #232a36;border-radius:12px;padding:14px 16px}
.card .k{color:#6b7484;font-size:12px;text-transform:uppercase;letter-spacing:.06em}
.card .v{margin-top:6px;font-size:15px;word-break:break-word}
ul.games{list-style:none;margin:0;padding:0}
ul.games li{margin:8px 0}
ul.games a{color:#7cb2ff;text-decoration:none;font-size:17px}
ul.games a:hover{text-decoration:underline}
.empty{padding:20px;border:1px dashed #2b3342;border-radius:12px;color:#9aa4b2}
pre{background:#12161d;border:1px solid #232a36;border-radius:10px;padding:14px 16px;
    overflow:auto;font-size:13px;line-height:1.5;color:#cbd5e1}
code{background:#1a1f29;padding:2px 6px;border-radius:6px;font-size:13px}
.links a{color:#7cb2ff;text-decoration:none;margin-right:16px}
.links a:hover{text-decoration:underline}
.muted{color:#8b95a5;font-size:14px}
"""


def render_html(handler, games):
    base = _base_url(handler)
    uptime = _uptime_str()

    if games:
        items = "\n".join(
            '<li><a href="{base}/play/{q}">{n}</a></li>'.format(
                base=html.escape(base), q=urllib.parse.quote(name), n=html.escape(name)
            )
            for name in games
        )
        games_block = '<ul class="games">\n{}\n</ul>'.format(items)
        count = "{} game{}".format(len(games), "" if len(games) == 1 else "s")
    else:
        games_block = (
            '<div class="empty">No games installed yet. Pull the collection with '
            "<code>docker/run.sh --library --sync</code> (needs an itch.io API key).</div>"
        )
        count = "0 games"

    meta = [
        ("Status", '<span class="pill"><span class="dot"></span>Running</span>'),
        ("API", html.escape(base)),
        ("Uptime", html.escape(uptime) if uptime else "&mdash;"),
        ("CPU limit", html.escape(_fmt_cores(_cgroup_cpu_cores()))),
        ("RAM limit", html.escape(_fmt_gb(_cgroup_mem_gb()))),
        ("Games", html.escape(count)),
        ("Library", "<code>{}</code>".format(html.escape(WEB_DIR))),
        ("Volume", "<code>{}</code>".format(html.escape(GAMES_VOLUME_NAME))),
    ]
    meta_html = "\n".join(
        '<div class="card"><div class="k">{k}</div><div class="v">{v}</div></div>'.format(
            k=html.escape(k), v=v
        )
        for k, v in meta
    )

    howto = (
        "# pull / update the collection (needs an itch.io API key)\n"
        "ITCH_API_KEY=... docker/run.sh --library --sync\n\n"
        "# start this page (library menu + API)\n"
        "docker/run.sh --library\n\n"
        "# list installed titles on the host\n"
        "docker/run.sh --list\n\n"
        "# copy the game files to your machine instead of browsing:\n"
        'docker run --rm -v arcade-contract-sim-games:/games \\\n'
        '  -v "$PWD/games-export:/out" alpine \\\n'
        "  sh -c 'mkdir -p /out && cp -r /games/web /out/'"
    )

    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Arcade simulator — status</title><style>{css}</style></head>"
        "<body><div class='wrap'>"
        "<h1>Arcade simulator <span class='pill'><span class='dot'></span>Running</span></h1>"
        "<div class='meta'>{meta}</div>"
        "<h2>Games</h2>"
        "<p class='muted'>These links open the game in <b>your</b> browser "
        "(fast, <b>unconstrained</b>). For cabinet-like constraints "
        "(SwiftShader, 720p, RAM/CPU caps) run it in the noVNC kiosk at "
        "<a href='http://localhost:6080/'>:6080</a>.</p>"
        "{games_block}"
        "<h2>Links</h2><div class='links'>"
        "<a href='http://localhost:6080/vnc.html'>noVNC kiosk</a>"
        "<a href='{base}?format=json'>JSON</a>"
        "<a href='{base}?format=text'>Text</a>"
        "</div>"
        "<h2>How to run / sync / get the files</h2><pre>{howto}</pre>"
        "<p class='muted'>This page is served by the running library container. "
        "If it stopped loading, the container is down — start it with "
        "<code>docker/run.sh --library</code>. Open <code>docker/web/status.html</code> "
        "for a status page that works even when nothing is running.</p>"
        "</div></body></html>".format(
            css=PAGE_CSS,
            meta=meta_html,
            games_block=games_block,
            base=html.escape(base),
            howto=html.escape(howto),
        )
    ).encode("utf-8")


def render_text(handler, games):
    base = _base_url(handler)
    return (
        "\n".join(
            "{}/play/{}".format(base, urllib.parse.quote(name)) for name in games
        )
        + ("\n" if games else "")
    ).encode("utf-8")


_CALLBACK_RE = re.compile(r"^[A-Za-z_$][\w$.]*$")


class Handler(BaseHTTPRequestHandler):
    server_version = "ArcadeAPI/1.0"

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parts = urllib.parse.urlsplit(self.path)
        path = parts.path
        query = urllib.parse.parse_qs(parts.query)

        if path in ("/", "/index.html"):
            games = installed_games()
            callback = query.get("callback", [None])[0]
            fmt = (query.get("format", [""])[0] or "").lower()

            if callback:
                if not _CALLBACK_RE.match(callback):
                    self._send(400, "text/plain; charset=utf-8", b"invalid callback\n")
                    return
                payload = _games_json(self, games).replace("</", "<\\/")
                body = "{} ({});\n".format(callback, payload).encode("utf-8")
                self._send(200, "application/javascript; charset=utf-8", body)
                return
            if fmt in ("json", "jsonp"):
                self._send(200, "application/json; charset=utf-8",
                           _games_json(self, games).encode("utf-8"))
                return
            if fmt == "text":
                self._send(200, "text/plain; charset=utf-8", render_text(self, games))
                return
            self._send(200, "text/html; charset=utf-8", render_html(self, games))
            return

        if path.startswith("/play/"):
            name = urllib.parse.unquote(path[len("/play/"):])
            if name not in installed_games():
                self._send(404, "text/plain; charset=utf-8", b"no such game\n")
                return
            if not start_game(name):
                self._send(502, "text/plain; charset=utf-8", b"failed to start game server\n")
                return
            self.send_response(302)
            self.send_header(
                "Location", "http://{}:{}/index.html".format(_play_host(self), GAME_PORT)
            )
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return

        if path == "/exit":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(b"OK")
            threading.Thread(target=self._exit, daemon=True).start()
            return

        self._send(404, "text/plain; charset=utf-8", b"not found\n")

    def _exit(self):
        time.sleep(0.5)
        subprocess.run([EXIT_SCRIPT], check=False)

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def main():
    server = ThreadingHTTPServer((API_HOST, API_PORT), Handler)
    print("api-server listening on {}:{} (library)".format(API_HOST, API_PORT), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
