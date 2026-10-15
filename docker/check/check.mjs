#!/usr/bin/env node
// Headless contract checker for Switch Arcade web builds.
//
// Drives the system Chromium (puppeteer-core) against a locally-served build
// and asserts the things the arcade depends on:
//   * page loads with no console/page errors
//   * crossOriginIsolated === true  (COOP/COEP -> threaded WASM can boot)
//   * WebGL 2.0 context is available
//   * no requests leave loopback (no CDNs / fonts / hotlinked assets)
//   * canvas backing store is <= 720p (warning only)
//
// Usage: check.mjs <url-to-index.html>

import puppeteer from "puppeteer-core";

const TARGET_URL = process.argv[2];
if (!TARGET_URL) {
  console.error("usage: check.mjs <url>");
  process.exit(2);
}

const EXECUTABLE = process.env.CHROMIUM_PATH || "/usr/bin/chromium";
const SETTLE_MS = Number(process.env.CHECK_SETTLE_MS || 6000);
const NAV_TIMEOUT_MS = Number(process.env.CHECK_NAV_TIMEOUT_MS || 45000);

const failures = [];
const warnings = [];
const fail = (m) => failures.push(m);
const warn = (m) => warnings.push(m);

const LOOPBACK_HOSTS = new Set(["127.0.0.1", "localhost", "::1", "[::1]"]);

function hostOf(url) {
  const m = /^[a-zA-Z][a-zA-Z0-9+.-]*:\/\/([^/?#]*)/.exec(url);
  if (!m) return "";
  const authority = m[1];
  const hostport = authority.slice(authority.lastIndexOf("@") + 1);
  return hostport.replace(/:\d+$/, "").toLowerCase();
}

async function main() {
  const env = { ...process.env };
  delete env.DISPLAY; // headless SwiftShader; never reach for an X server

  const browser = await puppeteer.launch({
    executablePath: EXECUTABLE,
    headless: true,
    env,
    protocolTimeout: NAV_TIMEOUT_MS + 30000,
    args: [
      "--no-sandbox",
      "--disable-gpu-watchdog",
      "--ignore-gpu-blocklist",
      "--use-gl=angle",
      "--use-angle=swiftshader",
      "--enable-unsafe-swiftshader",
      "--window-size=1280,720",
      "--disable-background-networking",
    ],
  });

  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1280, height: 720 });

    const external = new Set();
    const consoleErrors = [];
    const pageErrors = [];

    page.on("console", (msg) => {
      if (msg.type() !== "error") return;
      const loc = msg.location()?.url || "";
      // The arcade's server 404s /favicon.ico; that's not a game defect.
      if (/favicon/i.test(loc) || /favicon/i.test(msg.text())) return;
      consoleErrors.push(msg.text());
    });
    page.on("pageerror", (err) => pageErrors.push(String(err)));
    page.on("request", (req) => {
      try {
        const host = hostOf(req.url());
        if (host && !LOOPBACK_HOSTS.has(host)) external.add(req.url());
      } catch {
        /* non-http(s) URL, ignore */
      }
    });
    try {
      await page.goto(TARGET_URL, { waitUntil: "load", timeout: NAV_TIMEOUT_MS });
    } catch (err) {
      fail(`navigation failed: ${err.message}`);
    }

    // Give the game time to boot, negotiate WebGL and settle.
    await new Promise((r) => setTimeout(r, SETTLE_MS));

    const info = await page.evaluate(() => {
      const canvases = [...document.querySelectorAll("canvas")].map((c) => ({
        w: c.width,
        h: c.height,
      }));
      let webgl2 = false;
      try {
        webgl2 = !!document.createElement("canvas").getContext("webgl2");
      } catch {
        webgl2 = false;
      }
      return {
        title: document.title,
        crossOriginIsolated: !!self.crossOriginIsolated,
        webgl2,
        canvases,
        readyState: document.readyState,
      };
    });

    // --- assertions ---
    if (pageErrors.length) fail(`page errors: ${pageErrors.join(" | ")}`);
    if (consoleErrors.length)
      fail(`console errors: ${consoleErrors.slice(0, 5).join(" | ")}`);

    if (!info.crossOriginIsolated) {
      fail(
        "crossOriginIsolated is false: COOP/COEP headers are missing. " +
          "Threaded (SharedArrayBuffer) builds will refuse to boot."
      );
    }
    if (external.size) {
      fail(
        `non-loopback requests (cabinet may be offline): ` +
          [...external].slice(0, 5).join(", ")
      );
    }

    if (!info.webgl2) fail("WebGL 2.0 context is unavailable.");

    const oversized = info.canvases.filter((c) => c.w > 1280 || c.h > 720);
    if (oversized.length) {
      warn(
        `canvas backing store exceeds 720p: ` +
          oversized.map((c) => `${c.w}x${c.h}`).join(", ") +
          " (render smaller; it's the biggest perf lever)"
      );
    }

    // --- report ---
    console.log("");
    console.log("Arcade contract check");
    console.log("  url:      " + TARGET_URL);
    console.log("  title:    " + (info.title || "(none)"));
    console.log("  ready:    " + info.readyState);
    console.log(
      "  canvas:   " +
        (info.canvases.length
          ? info.canvases.map((c) => `${c.w}x${c.h}`).join(", ")
          : "(none found)")
    );
    console.log("  xorigin:  isolated=" + info.crossOriginIsolated);
    console.log("  webgl2:   " + info.webgl2);
    console.log("");

    for (const w of warnings) console.log("  WARN  " + w);
    for (const f of failures) console.log("  FAIL  " + f);

    if (failures.length) {
      console.log(`\nRESULT: FAIL (${failures.length} issue(s))`);
      return 1;
    }
    console.log(
      `\nRESULT: PASS${warnings.length ? ` (${warnings.length} warning(s))` : ""}`
    );
    return 0;
  } finally {
    await browser.close().catch(() => {});
  }
}

main()
  .then((code) => process.exit(code))
  .catch((err) => {
    console.error("checker crashed: " + (err?.stack || err));
    process.exit(2);
  });
