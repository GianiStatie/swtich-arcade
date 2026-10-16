#!/usr/bin/env python3
"""Tiny logger for the PadTest page beacons (listens on 127.0.0.1:8130)."""
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

LOG = "/tmp/padlog.txt"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/r":
            data = urllib.parse.parse_qs(parsed.query).get("d", [""])[0]
            with open(LOG, "a") as f:
                f.write("%.2f %s\n" % (time.time(), data))
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 8130), Handler).serve_forever()
