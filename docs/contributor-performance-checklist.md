# Contributor Performance Checklist

So you want your game running nicely on the arcade cabinets. They're modded
Nintendo Switches: a Tegra X1, four Cortex-A57 cores, an old Maxwell GPU,
running Linux with a Chromium kiosk. Nobody expects you to build for it — the
arcade serves your files locally, controls the HTTP server, and tunes the
browser for you. So most of this page is just "don't fight the platform".

The golden rule: **one self-contained HTML5 zip**. Everything else here is
optional tuning that makes your game faster or friendlier.

## 1. What every game has to do

- [ ] Your zip extracts so `index.html` sits at the root. The launcher and the menu both depend on it.
- [ ] Relative paths only, zero external assets. No CDN scripts, no Google Fonts, no hotlinked images — a cabinet can be offline, and an external asset turns into a broken or hanging game.
- [ ] Everything playable with the keyboard alone. No mouse, no touch (mapping is below).
- [ ] No browser dialogs (`alert`, `confirm`). There's nobody there to click them.

## 2. What the controllers actually send

The arcade's bridge reads the Joy-Cons and types keyboard keys at your game. If
you support these, the cabinets work for free:

| Arcade input | Key it sends | Typical use |
|---|---|---|
| D-pad | Arrow keys | move |
| A (south) | Space | jump / accept |
| B (east) | R | reset |
| X (north) | Esc | back / cancel |
| Y (west) | Tab | menu |
| Start + Select | — | force-quit (handled by the arcade itself, always works) |

Still ship a quit button, though — section 5.

## 3. Make it fast (applies to any engine)

- [ ] **Render small.** 720p is the ceiling; lower is better. Internal resolution is the single biggest lever you have. Dragon Jump renders at 640×360 and lets the canvas upscale — at arcade distance you can't tell, and it holds a locked 60.
- [ ] **No MSAA, no real-time shadows, no post-processing.** Old GPU, screen across the room: expensive effects you can hardly see. Skip them.
- [ ] **Allocate nothing in the per-frame loop** — no fresh objects, strings or lists. GC hitches are the number-one cause of stutter in web builds on weak CPUs.
- [ ] **Cap your FPS** at 30 or 60 (the display is 60 Hz). A rock-solid 30 beats a flaky 60 every time. Dragon Jump ran at 120 for a while; going to 60 changed nothing visually and freed up headroom.
- [ ] **Keep non-game files out of the build.** Marketing art, reference photos, unused audio — none of it belongs in the pck. Dragon Jump accidentally shipped ~21 MB of it; moving those files to a `marketing/` folder with a `.gdignore` (plus an exclude filter in the export preset) dropped all of it.
- [ ] **Audio: OGG/Vorbis at 64–96 kbps.** Don't decode everything to PCM and hold it in memory.
- [ ] **Few, bigger sprite atlases** instead of lots of loose images. And never base64-embed big assets into the HTML.
- [ ] **Hide level switches behind a cover.** Loading, tearing down and rebuilding a level (terrain, objects, secrets, pathfinding) all happen on the main thread — threads don't parallelize it, so an uncovered switch is a visible multi-frame freeze. We measured this on the Tegra. Dragon Jump runs in-place switches behind the transition wipe and it's smooth.
- [ ] **Test the way it's played:** 720p canvas, keyboard only, no mouse.
- [ ] Don't panic about the **first launch after an update being slow** — shaders and the WASM code cache start cold. The arcade pre-warms new games after installing them, so players normally never see that run.

## 4. Engine-specific settings

### Godot 4.x

- [ ] **Compatibility renderer (WebGL2) — the only renderer web supports.** Set it explicitly:
  ```
  rendering/renderer/rendering_method.web = "gl_compatibility"
  ```
  If your game was written for Forward+, expect the visuals to differ — tune the lighting so compatibility mode looks right, because compatibility is what every web player gets.
- [ ] **Thread Support: ON.** Threaded exports let Godot use all four cores, and audio can use low-latency `Stream` playback (without threads, web falls back to "Sample" audio and effects like reverb, doppler and procedural audio don't work).
  - A threaded export needs a **threaded export template**. Official templates are threaded; if you use a custom template, rebuild it with threads enabled (below).
  - It also needs the server to send **COOP/COEP** cross-origin isolation headers. The arcade's server sends them, and a threaded build simply refuses to start without them — if you're targeting a cabinet that hasn't had that update yet, ship the single-threaded build or hold off.
  - Hosting the same build on itch? Tick *Edit game → Embed options → SharedArrayBuffer support*. Note that it moves the game to `html.itch.zone`, so existing local saves don't follow.
  - If none of that is available, the single-threaded export runs everywhere and still plays fine — just slower, with "Sample" audio.
- [ ] **Building a custom template?** (Pck encryption, engine stripping, or both.) A few things we learned the hard way:
  - The template has to match your settings — engine version, threads, encryption key. Change any of them and it's a rebuild. Do it once in CI, publish the result as a release asset, and let game builds download it. Dragon Jump's `build-web-template.yml` is a decent reference to steal from.
  - **Stripped templates eat texture codecs.** Godot stores Lossless 2D textures as WebP inside the imported `.ctex`, so if you strip the webp module, every sprite disappears. Keep `rendering/textures/lossless_compression/force_png=true`, keep texture imports on Lossless (a *Lossy* import is still WebP), and reimport after changing it — delete `.godot/imported/` or hit Reimport All. We hit this on the canary Switch, sprites and all.
  - **Keep both templates installed** — threaded and nothreads. If threads misbehave, `variant/thread_support=false` is a one-line rollback instead of a rebuild.
- [ ] **Load scenes in the background, properly.** On a threaded export use `ResourceLoader.load_threaded_request()` and poll it while the wipe covers the screen. The trap: on a **nothreads** web build threaded loads never complete (godotengine/godot#109148) — gate on `OS.has_feature("threads")` and fall back to a plain `load()` inside the opaque phase. Two extra tricks from Dragon Jump: start loading the next scene *during* the fade-in, and warm your first gameplay scene from the main menu so the first Play doesn't pay the cold load.
- [ ] **VRAM Texture Compression: For Desktop ON, For Mobile OFF.** The Switch's GPU is desktop-class (S3TC/BPTC); "For Mobile" only bloats the build. (If nothing in your game uses VRAM-compressed textures it's a no-op — check before obsessing over it.)
- [ ] **Export as Release**, not Debug. Debug builds carry extra data and run slower.
- [ ] **Want a smaller download?**
  - The **Minimize Web Build** addon (Asset Library, Godot 4.3+) recompresses `.pck`/`.wasm`. The arcade server serves precompressed `.br`/`.gz` sidecars straight from your zip.
  - If you ship sidecars, compress `.wasm` and `.js` — that's where the money is (Dragon Jump's wasm: 25.8 MB → 4.3 MB). Don't bother with an encrypted `.pck`: encryption makes it incompressible, ours grew by 12 bytes.
  - Advanced: a custom template with unused engine modules stripped cuts the wasm dramatically (Godot's "Optimizing a build for size" doc).
- [ ] **Branch on feature tags for heavy effects**, but keep both paths working:
  ```gdscript
  if OS.has_feature("web"):
      # reduced settings
  ```

#### Optional: running natively on the cabinet

The arcade can run a Godot web export **natively** — a Linux ARM64 Godot
template plus the same `.pck` from your zip — when its template cache has your
exact engine version. You still ship one HTML5 zip like everyone else. To make
your game eligible:

- [ ] **Tell the host your exact version** (e.g. `4.6.stable`). Templates are exact-match — Godot has no forward compatibility. Official ARM64 templates are fetched per version, so common versions are free.
- [ ] **Unencrypted pck works out of the box.** If you encrypt it, the native template has to be compiled with your key — share it with the host or stay on the web path.
- [ ] **GDScript only.** C# can't export to web at all in Godot 4, and GDExtension games need native extension binaries the web pck doesn't contain — those stay on Chromium.
- [ ] **Keep your `OS.has_feature("web")` branches safe.** On the native path they take the desktop branch: native quit works, touch controls hide. Both paths should behave.

See the [native ARM tier design](native-arm-tier.md) for the host-side details.

### Unity (WebGL)

Unity's own web-optimization docs cover most of this; these are the settings that
matter here:

- [ ] **Managed Stripping Level: High** (Other Settings). Smaller and faster, and you don't need the code it throws away.
- [ ] **Compression Format: Brotli**, **Decompression Fallback: OFF** (Publishing Settings). Fallback exists for servers you can't configure — the arcade's server is configured and sends the right `Content-Encoding`, so fallback would only add `.unityweb` overhead and double decompression.
- [ ] **Data Caching: ON.** Repeat launches stay fast because the browser keeps build data in the persistent profile directory the arcade provides.
- [ ] **Multi-threading: ON.** Unity calls it experimental, but the arcade sends the COOP/COEP headers it needs and the extra threads genuinely help those four cores.
- [ ] **Strip Engine Code: ON** (it's the default — just don't turn it off).
- [ ] **WebGL 2 only** — disable Auto Graphics API and target WebGL 2.
- [ ] **Exceptions: off in release** so stack traces aren't generated (size + speed). Turn them back on when you're debugging.
- [ ] Textures: compressed/crunched at sensible sizes. Audio: Vorbis, low bitrate. Delete unused plugins and analytics.
- [ ] Content: avoid big shadow-heavy scenes and MSAA in the Universal pipeline.

### Plain JavaScript (Phaser, custom engines, etc.)

- [ ] Ship a minified bundle — no dev builds, no sourcemaps.
- [ ] One sprite atlas, not dozens of separate image requests.
- [ ] Clamp the canvas backing-store resolution (≤720p) no matter how big the CSS size is — don't render at the device's full resolution.
- [ ] Use `requestAnimationFrame`, and keep per-frame work light (no layout thrash, no `getContext` reallocations, no per-frame `new`).

## 5. Your quit button

In-game Quit buttons should tell the arcade to return to the menu by calling:

```
http://127.0.0.1:8123/exit
```

**Godot**: `get_tree().quit()` in a web build just freezes the canvas — browsers
won't let a script close a tab it didn't open. Hit the endpoint instead:

```gdscript
func _on_quit_button_pressed() -> void:
    if OS.has_feature("web"):
        JavaScriptBridge.eval(
            "fetch('http://127.0.0.1:8123/exit',{keepalive:true,mode:'no-cors'})")
    else:
        get_tree().quit()
```

**Unity**: `Application.Quit()` has the same limitation in WebGL. A small
`.jslib` plugin does the job:

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

**Plain JS games** can just fetch the endpoint.

Nobody can ever get stuck: **Start + Select** force-quits any game host-side. So
this section isn't about rescuing people — it's about making exits smooth.

## 6. The short version

If you're skimming, this is the whole page:

- [ ] `index.html` at the zip root, relative paths, no external assets.
- [ ] Keyboard controls: arrows, Space, R, Esc, Tab.
- [ ] ≤720p internal render; no MSAA/shadows/post; nothing allocated per frame; FPS capped.
- [ ] Level switches covered; non-game files out of the build.
- [ ] Godot: Compatibility renderer + Threads ON (keep the nothreads template around); Unity: stripping High + Brotli (no fallback) + Data Caching + multithreading.
- [ ] Godot: VRAM compression For Desktop; Unity: WebGL2 only.
- [ ] A quit that hits `127.0.0.1:8123/exit` (Start + Select covers you anyway).
- [ ] Godot: safe `OS.has_feature("web")` branches if you want the native path later.
