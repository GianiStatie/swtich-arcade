# Web build size: lessons from Dragon Jump and Töténkerkăr

This note collects what we learned about web-build size on the cabinets. It
started with Dragon Jump, then a third-party Godot game (Töténkerkăr) showed the
same traps at a much larger scale. The short version: **the cabinet can serve
precompressed files and report sizes, but it cannot re-encode a game's assets.
Most of the win has to happen in the game's export/CI.**

For gameplay/performance guidance, see the
[contributor performance checklist](contributor-performance-checklist.md). For
the host-side plan, see the
[switch arcade performance plan](switch-arcade-perf-plan.md).

## The case study

| | Dragon Jump | Töténkerkăr |
|---|---:|---:|
| Engine | Godot 4.7.2 | Godot 4.7.0 |
| `index.pck` | 7.1 MB (encrypted, custom build) | 58.5 MB (unencrypted) |
| `index.wasm` | 27.2 MB raw / 4.6 MB `.br` | 39.5 MB raw / no `.br` |
| `index.js` | 286 KB / 59 KB `.br` | 280 KB / no `.br` |
| Threads | on | off |
| Approx. bytes served to Chromium | ~11.7 MB | ~98.3 MB |
| Installed size on disk | 38 MiB | 94 MiB |

Both are single-zip HTML5 games. The gap is not the cabinet: Dragon Jump's zip
ships `.wasm.br`/`.js.br` sidecars, uses a custom stripped engine template, and
its pck is only 7 MB. Töténkerkăr's zip ships no sidecars, uses a
stock/non-stripped Godot web template, and its pck is mostly uncompressed audio
and textures.

### Where Töténkerkăr's 58.5 MB pck goes

Parsed from the pck directory (it is unencrypted, so the file table is
readable):

| Content | Size | Files | Notes |
|---|---:|---:|---|
| Imported audio (`.sample`) | 32.1 MiB (33.6 MB) | 63 | WAV/PCM, not Ogg. Music tracks are 1.5–3 MB each. |
| Textures (`.ctex`) | 22.1 MiB (23.1 MB) | 268 | Mix of S3TC and larger lossless textures. |
| Scripts/scenes/other | ~1.5 MiB | ~1,075 | `.gdc`, `.scn`, `.res`, import metadata. |

That is ~97% audio + textures. The engine wasm is another 39.5 MB.

A stock Godot web export is not "small"; a 3D game with voice acting will be
larger than Dragon Jump. But 32 MiB of PCM audio is avoidable, and the stock
wasm is much larger than a stripped template.

## What the arcade can do after pulling

The watcher (`scripts/itch-watcher.py`) installs the HTML upload without
optimizing the build. The server (`scripts/webgame-server.py`) serves
`.br`/`.gz` sidecars if they are next to the requested file, but it never
compresses on the fly.

Safe to automate:

- **Brotli/gzip sidecars for `.wasm` and `.js`.** The cabinet image has Python
  `brotli` available (verified on the hardware cabinet). Measured on
  Töténkerkăr: 37.7 MiB wasm → 7.9 MiB at
  quality 5 in ~8 s; the server already supports it. Caveats: it only saves
  bytes on disk/network; Chromium still decompresses and compiles the same
  wasm, and the sidecar adds disk usage. On a loopback server the load-time
  win is small.
- **A build audit**: report pck/wasm/js sizes, sidecar presence, thread flag,
  and (for unencrypted Godot pcks) the audio/texture/code breakdown. Warn when
  a build is over budget.
- **Prune obvious junk** (source maps, `.pdb`, `__MACOSX`) if a zip contains it.

Not worth automating by default:

- **Brotli the whole `.pck`.** Töténkerkăr's pck went 55.8 MiB → 38.8 MiB
  (~70%) in ~8 s, but the browser still decompresses the same 58.5 MB, the
  sidecar adds ~39 MiB of disk, and an encrypted pck is incompressible. Leave
  it to game builds that know their pck is compressible.
- **`wasm-opt` / Binaryen.** Not installed; can break engine builds; slow and
  memory-hungry on the Switch. Test per game, not as a blanket pass.

Cannot be done reliably after export:

- **WAV/PCM → Ogg.** The audio is inside the pck as imported `.sample`
  resources with `.import`/UID metadata. Re-encoding requires the Godot
  project and a re-export; editing the pck in place risks breaking references.
- **Texture recompression/replacement.** Same reason: `.ctex` is tied to
  import settings and UIDs.
- **Stripping the engine wasm.** A compile-time template decision, per engine
  version/threads/encryption.
- **Native ARM template.** A separate runtime path, per engine version; see
  [native ARM tier](native-arm-tier.md). Not a generic post-pull pass.

If a game is third-party, the cabinet cannot fix its assets. Send the
developer this page and the
[checklist](contributor-performance-checklist.md).

## What to do at export time

These are the size-related lessons from Dragon Jump, plus the Töténkerkăr case
study. The full performance list is in the
[checklist](contributor-performance-checklist.md).

- [ ] **Ogg Vorbis audio at 64–96 kbps** for music and voice. This is the
  biggest single win. Töténkerkăr's 32 MiB of PCM would likely become a few MB.
- [ ] **Keep non-game files out of the build.** Dragon Jump once shipped ~21 MB
  of marketing art; a `marketing/` folder with `.gdignore` plus an export
  filter removed it. Check the pck contents, not just the project tree.
- [ ] **Use VRAM texture compression for desktop, not mobile.** The Switch's
  GPU is desktop-class (S3TC/BPTC); "For Mobile" only bloats the build. Resize
  oversized textures and atlas loose sprites.
- [ ] **Export Release, not Debug.**
- [ ] **Threads ON** if you can. It needs COOP/COEP (the arcade sends them) and
  a threaded template. Non-threaded works, but it is slower and uses "Sample"
  audio.
- [ ] **Use a custom stripped engine template** if the wasm is large. Strip
  only what you do not use, keep both threaded/nothreads templates, and test
  textures: stripping the WebP module breaks Lossless 2D textures unless
  `force_png` is set and assets are reimported.
- [ ] **Ship `.wasm.br` and `.js.br` sidecars.** The arcade serves them. Do not
  bother with an encrypted pck; it is incompressible.
- [ ] **Measure before upload.** Check `index.*` sizes, `.br` sidecars,
  `GODOT_THREADS_ENABLED` in `index.html`, and (for an unencrypted pck) the
  file table. As a rule of thumb, if the served total is above ~30 MB, look at
  audio first, then the wasm template.
- [ ] **Test on a cabinet.** The first launch after an update is cold (shader
  and WASM caches); later launches reuse the cache, but a slow first load is
  still a useful signal.

## Quick audit commands

On a cabinet:

```bash
cd ~/arcade_games/web/"Game Name"
du -sh .
ls -lh index.*
find . -maxdepth 1 \( -name '*.br' -o -name '*.gz' \) -printf '%f %s\n'
grep -o 'GODOT_THREADS_ENABLED[^;]*' index.html
```

There is no supported "shrink the pck" command on the cabinet. If the pck is
unencrypted and you need a breakdown, parse its directory with a small script
or ask the host to add the audit to the watcher.

## References

- [Contributor performance checklist](contributor-performance-checklist.md)
- [Switch arcade performance plan](switch-arcade-perf-plan.md)
- [Native ARM tier](native-arm-tier.md)
- [Web Games setup](web-games-setup.md)
- [Docker contract simulator](../docker/README.md)
