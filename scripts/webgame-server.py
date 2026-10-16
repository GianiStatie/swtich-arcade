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
# Every served HTML page gets the arcade pad shim injected: the arcade panels'
# raw DragonRise button order does not match the gamepad standard, and
# Chromium reports unknown pads in raw order, so the shim in the page remaps
# the panel buttons to standard indices for all games.
#
# Usage: webgame-server.py <port> <game-dir>

import io
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

SHIM_ROUTE = "/__arcade_pad_shim.js"
SHIM_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "arcade-pad-shim.js")
SHIM_TAG = b'<script src="' + SHIM_ROUTE.encode() + b'"></script>'


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
        if self.path.split("?")[0] == SHIM_ROUTE:
            return self._serve_shim()

        accept = self.headers.get("Accept-Encoding", "")
        path = self.translate_path(self.path)

        # HTML is always served injected (never from a compressed sidecar):
        # the shim script tag is inserted right after <head>.
        if path.endswith(".html") and os.path.isfile(path):
            try:
                with open(path, "rb") as f:
                    html = f.read()
            except OSError:
                return super().send_head()
            head = html.lower().find(b"<head")
            if head != -1:
                close = html.find(b">", head)
                if close != -1:
                    html = html[:close + 1] + SHIM_TAG + html[close + 1:]
            else:
                html = SHIM_TAG + html
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            return io.BytesIO(html)

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

    def _serve_shim(self):
        try:
            with open(SHIM_FILE, "rb") as f:
                data = f.read()
        except OSError:
            return None
        self.send_response(200)
        self.send_header("Content-Type", "application/javascript")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        return io.BytesIO(data)

    def log_message(self, fmt, *args):
        pass  # keep the kiosk logs clean


if __name__ == "__main__":
    ThreadingHTTPServer((BIND_HOST, PORT), NoCacheHandler).serve_forever()
