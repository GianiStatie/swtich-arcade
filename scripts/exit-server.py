#!/usr/bin/env python3
"""Local HTTP exit server for web games.

Web games can call: fetch('http://localhost:8123/exit')
to quit Chromium and return to EmulationStation.

Run from Openbox autostart or launch-web-game.sh.
"""
import http.server
import subprocess
import threading
import time

HOST = "127.0.0.1"
PORT = 8123

class ExitHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/exit":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(b"OK")
            threading.Thread(target=self._exit, daemon=True).start()
        else:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _exit(self):
        time.sleep(0.5)
        subprocess.run(["/home/tagap/scripts/exit-to-es.sh"], check=False)

    def log_message(self, format, *args):
        pass

if __name__ == "__main__":
    server = http.server.HTTPServer((HOST, PORT), ExitHandler)
    print("Exit server listening on http://%s:%d/exit" % (HOST, PORT))
    server.serve_forever()
