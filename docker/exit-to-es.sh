#!/usr/bin/env bash
# Container stand-in for the arcade's exit-to-es.sh.
#
# The repo's exit-server.py hardcodes /home/tagap/scripts/exit-to-es.sh and runs
# it when a game hits http://127.0.0.1:8123/exit. On the cabinet that script
# kills Chromium and relaunches EmulationStation. In the container there is no
# EmulationStation, so "exit" just means "end this session": kill Chromium and
# let entrypoint.sh tear the container down.
#
# Deployed by entrypoint.sh to /home/tagap/scripts/exit-to-es.sh.
set -e
pkill -f "chromium-browser" 2>/dev/null || true
pkill -f "/usr/lib/chromium" 2>/dev/null || true
pkill -x chromium 2>/dev/null || true
exit 0
