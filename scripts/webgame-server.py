#!/usr/bin/env python3
# webgame-server.py
# Minimal HTTP server for serving a single web game directory with correct
# cache headers. Replaces `python3 -m http.server` for game launches.
#
# Why: http.server sends no Cache-Control header, so Chromium applies
# heuristic caching (10% of file age) and can serve a stale index.pck/wasm
# for days after a game update — the arcade then plays an old build. This
# server marks every response uncacheable, so each launch fetches fresh.
#
# Usage: webgame-server.py <port> <game-dir>

import sys
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8124
ROOT = sys.argv[2] if len(sys.argv) > 2 else "."


class NoCacheHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def log_message(self, fmt, *args):
        pass  # keep the kiosk logs clean


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), NoCacheHandler).serve_forever()