#!/usr/bin/env python3
"""Menu + launcher server for the arcade contract simulator's library mode.

Stands in for EmulationStation: it lists the games installed in the library and
launches one at a time through the repo's own webgame-server.py, so every game
runs at the *root* path on :8124 exactly like the cabinet (no subpath).

Routes:
  GET /                 -> the game menu (scans the library on every request)
  GET /play/<name>      -> (re)start the per-game server for <name>, then
                           302-redirect the browser to :8124/index.html

The scanning + launcher logic is shared with api-server.py via library.py. The
per-game server, the exit server and the Chromium supervisor live in
entrypoint.sh.
"""

import html
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from library import GAME_PORT, installed_games, start_game  # noqa: E402

MENU_PORT = int(os.environ.get("MENU_PORT", "8125"))


MENU_CSS = """
:root{color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;background:#0b0d12;color:#e8ecf1;
     font:16px/1.4 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
header{padding:28px 32px 8px}
h1{margin:0;font-size:26px;letter-spacing:.5px}
.sub{color:#8b95a5;margin-top:6px;font-size:14px}
.grid{display:grid;gap:16px;padding:24px 32px 40px;
      grid-template-columns:repeat(auto-fill,minmax(240px,1fr))}
a.card{display:block;padding:20px;border-radius:14px;text-decoration:none;
       color:inherit;background:#161a22;border:1px solid #232a36;
       transition:transform .08s ease,border-color .08s ease}
a.card:hover{transform:translateY(-2px);border-color:#3b82f6}
a.card .t{font-size:18px;font-weight:600}
a.card .k{color:#6b7484;font-size:12px;margin-top:8px;text-transform:uppercase}
.empty{margin:40px 32px;padding:28px;border:1px dashed #2b3342;border-radius:14px;
       color:#9aa4b2}
.empty code{color:#e8ecf1;background:#161a22;padding:2px 6px;border-radius:6px}
"""


def render_menu(games):
    if games:
        cards = "\n".join(
            '<a class="card" href="/play/{q}"><div class="t">{n}</div>'
            '<div class="k">play</div></a>'.format(
                q=urllib.parse.quote(name), n=html.escape(name)
            )
            for name in games
        )
        body = '<div class="grid">\n{}\n</div>'.format(cards)
        count = "{} game{}".format(len(games), "" if len(games) == 1 else "s")
    else:
        body = (
            '<div class="empty">No games in the library yet.<br><br>'
            "Sync the collection from the host with "
            "<code>docker/run.sh --sync</code>, or "
            "<code>docker/run.sh --library --sync</code>.</div>"
        )
        count = "empty"

    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>TAGAP Games</title><style>{css}</style></head>"
        "<body><header><h1>TAGAP Games</h1>"
        "<div class='sub'>{count}</div></header>{body}</body></html>".format(
            css=MENU_CSS, count=count, body=body
        )
    ).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path

        if path in ("/", "/index.html"):
            payload = render_menu(installed_games())
            self._send(200, "text/html; charset=utf-8", payload)
            return

        if path.startswith("/play/"):
            name = urllib.parse.unquote(path[len("/play/"):])
            if name not in installed_games():
                self._send(404, "text/plain", b"no such game\n")
                return
            if not start_game(name):
                self._send(502, "text/plain", b"failed to start game server\n")
                return
            self.send_response(302)
            self.send_header("Location",
                             "http://127.0.0.1:{}/index.html".format(GAME_PORT))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return

        self._send(404, "text/plain", b"not found\n")

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def main():
    server = ThreadingHTTPServer(("0.0.0.0", MENU_PORT), Handler)
    print("menu-server listening on :{}".format(MENU_PORT), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
