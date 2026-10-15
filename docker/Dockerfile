# Arcade contract simulator
#
# Reproduces the arcade cabinet's *software contract* (Ubuntu-ish Chromium
# kiosk, the repo's webgame-server.py/exit-server.py, COOP/COEP, 720p, keyboard
# input, exit endpoint) so contributors can verify an HTML5 zip before shipping.
#
# This is NOT a Switch/Tegra hardware emulator. Build it multi-arch so Mac,
# Windows and Linux contributors all get a native image:
#
#   docker buildx build --platform linux/amd64,linux/arm64 \
#     -f docker/Dockerfile -t arcade-contract-sim .
#
# Build context is the repository root (so we can copy scripts/).

FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        chromium \
        python3 \
        python3-yaml \
        curl \
        unzip \
        xvfb \
        x11vnc \
        novnc \
        websockify \
        nodejs \
        npm \
        procps \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Tuned noVNC landing page (auto-connects with low-latency params) so
# http://localhost:6080/ works without picking vnc.html by hand.
COPY docker/novnc-index.html /usr/share/novnc/index.html

# Reuse the arcade's real servers + collection watcher verbatim.
COPY scripts/webgame-server.py scripts/exit-server.py scripts/itch-watcher.py \
     /opt/arcade/
# Library-mode servers: shared launcher helper + menu + URL API (ES stand-in).
COPY docker/library.py docker/menu-server.py docker/api-server.py /opt/arcade/
# Default collection config (overridable by mounting /games/itch-games.yaml).
COPY config/itch-games.yaml /opt/arcade/itch-games.yaml

RUN chmod +x /opt/arcade/webgame-server.py /opt/arcade/menu-server.py \
    /opt/arcade/api-server.py /opt/arcade/itch-watcher.py

# Headless contract checker (puppeteer-core drives the system chromium).
COPY docker/package.json docker/check.mjs /opt/arcade/
RUN cd /opt/arcade && npm install --omit=dev --no-audit --no-fund \
    && npm cache clean --force

COPY docker/entrypoint.sh docker/exit-to-es.sh /opt/arcade/
RUN chmod +x /opt/arcade/entrypoint.sh /opt/arcade/exit-to-es.sh

# exit-server.py hardcodes this path; provide the container stand-in there.
RUN install -d /home/tagap/scripts \
    && install -m 0755 /opt/arcade/exit-to-es.sh /home/tagap/scripts/exit-to-es.sh

WORKDIR /opt/arcade
ENTRYPOINT ["/opt/arcade/entrypoint.sh"]
CMD ["interactive"]
