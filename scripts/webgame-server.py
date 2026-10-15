#!/usr/bin/env python3
# webgame-server.py
# Minimal HTTP server for serving a single web game directory with correct
# cache headers, cross-origin isolation and precompressed sidecar support.
# Replaces `python3 -m http.server` for game launches.
#
# Why: http.server sends no Cache-Control header, so Chromium applies
# heuristic caching (10% of file age) and can serve a stale index.pck/wasm
# for days after a game update — the arcade then plays an old build. This
# server marks every response uncacheable, so each launch fetches fresh.
#
# Threaded WASM builds (Godot `variant/thread_support`) only start when the
# page is cross-origin isolated, so every response carries COOP/COEP. CI also
# ships .br/.gz sidecars next to the game files: when the browser accepts the
# encoding they are served with Content-Encoding (the browser decompresses,
# not the Switch), with Vary: Accept-Encoding so nothing gets cached wrongly.
# .wasm is served as application/wasm so Chromium can stream-compile it.
#
# Usage: webgame-server.py <port> <game-dir>

import os
import sys
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8124
ROOT = sys.argv[2] if len(sys.argv) > 2 else "."

# Interface to bind. Defaults to loopback (the cabinet's behavior: the game
# server is reachable only from the Switch itself). The container sets
# WEBGAME_BIND=0.0.0.0 in library mode so a published port can reach it.
BIND_HOST = os.environ.get("WEBGAME_BIND", "127.0.0.1")

ENCODINGS = (("br", ".br"), ("gzip", ".gz"))


class NoCacheHandler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".wasm": "application/wasm",
        ".pck": "application/octet-stream",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Vary", "Accept-Encoding")
        super().end_headers()

    def send_head(self):
        accept = self.headers.get("Accept-Encoding", "")
        path = self.translate_path(self.path)
        for encoding, suffix in ENCODINGS:
            if encoding not in accept:
                continue
            sidecar = path + suffix
            if not os.path.isfile(sidecar):
                continue
            try:
                f = open(sidecar, "rb")
            except OSError:
                continue
            fs = os.fstat(f.fileno())
            self.send_response(200)
            self.send_header("Content-Type", self.guess_type(path))
            self.send_header("Content-Encoding", encoding)
            self.send_header("Content-Length", str(fs.st_size))
            self.send_header("Last-Modified", self.date_time_string(fs.st_mtime))
            self.end_headers()
            return f
        return super().send_head()

    def log_message(self, fmt, *args):
        pass  # keep the kiosk logs clean


if __name__ == "__main__":
    ThreadingHTTPServer((BIND_HOST, PORT), NoCacheHandler).serve_forever()
