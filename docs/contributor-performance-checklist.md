# Contributor Performance Checklist

How to ship builds that run at their best on the arcade Switches (Tegra X1, L4T
Linux, Chromium kiosk). The arcade serves your files locally, controls the HTTP
server, and tunes the browser for you — so most of the work below is just "don't
fight the platform".

The golden rule: **one self-contained HTML5 zip**. Everything else is optional
tuning that makes your game faster or friendlier.

## 1. The universal contract (required)

- The zip must extract to `index.html` at its root — the arcade launcher and ES
  listing both rely on it.
- **Relative paths only, zero external assets.** No CDN scripts, no Google
  Fonts, no hotlinked images. The cabinets may be offline (internet is a
  USB-tether workaround); an external asset becomes a broken or hanging game.
- Everything must work with **no mouse and keyboard only** (see input contract).
- Nothing should pop browser dialogs (`alert`, `confirm`) — there's no one to
  click them.

## 2. The input contract (required)

Joy-Cons are read by the arcade's bridge and injected as keyboard keys:

| Arcade input | Injected key | Typical use |
|---|---|---|
| D-pad | Arrow keys | move |
| A (south) | Space | jump / accept |
| B (east) | R | reset |
| X (north) | Esc | back / cancel |
| Y (west) | Tab | menu |
| Start + Select | — | force-quit (handled host-side, always works) |

Support these mappings for keyboard play and the cabinets work for free.
Start + Select exits any game even if your exit button is broken — but do ship a
quit path too (§5).

## 3. Performance basics (all engines)

- **Render internally at ≤720p** and let the canvas upscale. The GPU is old;
  internal resolution is the single biggest lever for 60→30 FPS problems.
- No MSAA, minimal shadows, no post-processing. Arcade cabinets are viewed at a
  distance; these effects cost a lot and read barely.
- **Never allocate in the per-frame loop** (JS objects, strings, lists). GC
  hitches are the #1 cause of stutter in web builds on weak CPUs.
- Ship compressed audio (OGG/Vorbis ~64–96 kbps). Don't hold everything in
  memory as decoded PCM.
- Few, small sprite atlases instead of many individual images; don't embed big
  assets as base64 in the HTML.
- Cap your FPS target if the game logic permits (a solid 30 beats a flaky 60).
- **Scene/level switches are synchronous on the main thread** — loading, unloading,
  and instantiating a level does not parallelize across threads. Hide heavy rebuilds
  behind a cover (a wipe/fade) and/or chunk the work across frames; otherwise the
  player sees a multi-frame freeze on every switch. (Measured on the arcade's Tegra:
  threads alone do not fix this.)
- Test the way it will be played: 720p canvas, keyboard-only, no mouse.
- Expect the **first launch after an update to be slower** — shaders and the
  browser's WASM code cache start cold. The arcade pre-warms new games after
  installing them, so players normally never see that first run.

## 4. Engine-specific export settings

### Godot 4.x

Export preset (Web platform) + project settings:

- Web only supports the **Compatibility** renderer (WebGL2). Set it explicitly in
  project settings — Forward+/Mobile do not exist on the web platform:
  ```
  rendering/renderer/rendering_method.web = "gl_compatibility"
  ```
  If your game was written for Forward+, expect visuals to differ; tune lighting
  so compatibility mode looks fine (it's what every player gets).
- Export preset → **Thread Support: ON** (multi-threaded export). Benefits: Godot
  can use all CPU cores, and audio can use low-latency `Stream` playback. Without
  threads, web exports fall back to "Sample" audio, where effects (reverb, doppler,
  procedural audio) are unsupported.
  - Threaded exports require the server to send cross-origin isolation headers
    (`COOP`/`COEP`). The arcade's local server sends them (implemented 2026-10-12;
    live on the test Switch, production rollout pending) — without them a threaded
    build refuses to start.
  - A threaded export also needs a **threaded export template**. Official templates
    are threaded; if you use a custom template (e.g. an encrypted build), rebuild it
    with threads enabled. Godot exports automatically pick the matching template
    from your preset's Thread Support setting.
  - Hosting the same build on **itch.io**: tick *Edit game → Embed options →
    SharedArrayBuffer support*. Note this moves the game to `html.itch.zone`, so
    players' existing local saves do not follow.
  - If neither is available, the single-threaded export (Godot 4.3+ default) runs
    everywhere and still plays fine — just slower and with "Sample" audio.
- **VRAM Texture Compression: For Desktop ON, For Mobile OFF.** The Switch's GPU
  is desktop-class (S3TC/BPTC); enabling "For Mobile" only bloats the build.
- Export as **Release** (not debug). Debug exports carry extra data and run slower.
- Optional, to shrink the engine payload:
  - The built-in presets have no compression option, but the **"Minimize Web
    Build" addon** (Asset Library, Godot 4.3+) recompresses `.pck`/`.wasm`.
    The arcade server serves pre-compressed `.br`/`.gz` sidecars if your zip ships
    them (compressing arbitrary games arcade-side is still an open tier-2 item), so
    this is a nice-to-have.
  - Advanced: a custom export template compiled with unused engine features
    disabled can cut the WASM size dramatically (see the Godot docs,
    "Optimizing a build for size").
- Low-end branching: use feature tags in GDScript to skip heavy effects on web:
  ```gdscript
  if OS.has_feature("web"):
      # reduced settings
  ```

#### Optional: native execution on the cabinet

The arcade can run a Godot web export **natively** (a Linux ARM64 Godot template
plus the same `.pck` from your zip) when its template cache has your exact engine
version — you still only ship one HTML5 zip. To make your game eligible:

- **Engine version matters.** Templates are exact-match; Godot has no forward
  compatibility. Tell the arcade host your version (e.g. `4.6.stable`); official
  ARM64 templates are fetched per version, so common versions are free.
- **Unencrypted pck** works out of the box. If you encrypt your pck, the native
  template must be compiled with your key — share it with the arcade host or stay
  on the web path.
- **GDScript only.** C# cannot export to web at all in Godot 4, and GDExtension
  games need native extension binaries the web pck does not contain — those stay
  on Chromium.
- **Web-only branches are skipped natively:** `OS.has_feature("web")` code takes
  the desktop path (native quit works, touch controls hide). Keep both paths safe.

See the [native ARM tier design](native-arm-tier.md) for how it works host-side.

### Unity (WebGL)

Player / Publishing settings recommended by Unity's own web-optimization docs:

- **Managed Stripping Level: High** (Other Settings) — strips unused code from
  managed DLLs; smallest and faster builds.
- **Compression Format: Brotli**, **Decompression Fallback: OFF** (Publishing
  Settings). Normally fallback is for servers you can't configure — the arcade
  server is configured (it sends the right `Content-Encoding`), and fallback
  adds `.unityweb` overhead plus double decompression.
- **Data Caching: ON.** The browser caches build data in the persistent profile
  directory the arcade provides, so repeat launches stay fast.
- **Multi-threading: ON.** Marked experimental by Unity, but the arcade serves
  the required COOP/COEP headers, and the extra threads genuinely help on the 4
  cores.
- **Strip Engine Code: ON** (default — don't disable it).
- Disable **Auto Graphics API** and target **WebGL 2** only.
- Exceptions: set so stack traces aren't generated in release (size + speed).
  Only enable when debugging a problem.
- Textures: compressed/crunched formats, sensible resolutions. Audio: Vorbis,
  low bitrate. Remove unused plugins and analytics.
- Content: no big shadow-heavy scenes, avoid MSAA in the Universal pipeline.

### Plain JavaScript (Phaser, custom engines, etc.)

- Ship a minified bundle; don't serve dev builds or sourcemaps.
- Use a single sprite atlas; avoid dozens of separate image requests.
- Clamp the canvas backing-store resolution (≤720p) regardless of CSS size —
  don't render at the device's full resolution.
- Use `requestAnimationFrame` and avoid heavy per-frame work (layout thrash,
  `getContext` reallocations, per-frame `new` allocations).

## 5. The quit / exit contract

In-game Quit buttons should tell the arcade to return to the menu by calling:

```
http://127.0.0.1:8123/exit
```

**Godot**: `get_tree().quit()` in a web build just freezes the canvas — it can't
close the page. Use this instead on web targets:

```gdscript
func _on_quit_button_pressed() -> void:
    if OS.has_feature("web"):
        JavaScriptBridge.eval(
            "fetch('http://127.0.0.1:8123/exit',{keepalive:true,mode:'no-cors'})")
    else:
        get_tree().quit()
```

**Unity**: `Application.Quit()` has the same limitation in WebGL builds. Add a
small `.jslib` plugin and call it from your quit handler:

```javascript
mergeInto(LibraryManager.library, {
  ArcadeExit: function() {
    fetch('http://127.0.0.1:8123/exit', {keepalive: true, mode: 'no-cors'});
  }
});
```

```csharp
using System.Runtime.InteropServices;
[DllImport("__Internal")] private static extern void ArcadeExit();
```

**Plain JS games** can fetch the endpoint directly.

Players can always exit with **Start + Select** (host-side force-quit), so a
missing quit button never traps anyone — this section just makes exits smooth.

## 6. Quick reference

| Priority | Do this |
|---|---|
| Must | `index.html` at zip root, relative paths, no external assets |
| Must | Keyboard contract (arrows/Space/R/Esc/Tab) |
| High | ≤720p internal render, no MSAA/shadows/post |
| High | No allocations in the per-frame loop |
| High | Godot: Thread Support ON (threaded template + server headers — see §4); Unity: stripping High + Brotli + Data Caching |
| Medium | Godot: VRAM compression "For Desktop"; Unity: WebGL2-only + multithreading |
| Medium | Working in-game quit via the exit endpoint |
| Medium | Godot: keep `OS.has_feature("web")` branches safe for the optional native path |
| Nice | Smaller payload (Godot addon/custom template), compressed audio |