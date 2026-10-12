# Native ARM Tier — Running Godot Web Exports Natively

Tier 3 of the [Tegra performance plan](switch-arcade-perf-plan.md). The arcade can
run a Godot web export **natively** — as an ARM64 Godot binary, no browser — by
reusing the `.pck` from the contributor's single HTML5 zip. Godot-only.

## What it is (and isn't)

- **Not a translator.** Nothing converts the wasm. The engine is *recompiled* as a
  native ARM64 export template, and the game's data (`index.pck`) is loaded as-is.
- The contributor contract is unchanged: **one HTML5 zip**. All of this is host-side.
- Scope: **Godot games only.** Unity/JS stay on Chromium (or an optional native
  upload, per tier 2). C# games can't be web-exported at all in Godot 4, so they
  never reach the arcade in the first place.

## How it works

1. Sync identifies Godot web exports (an `index.pck` + `index.wasm` next to
   `index.html`).
2. The launcher parses the pck header to pick the template. The header is
   **plaintext even when the pck is encrypted** (encryption starts after it):
   - `u32` magic `GDPC` (`0x43504447` little-endian)
   - `u32` pack format version (`PACK_FORMAT_VERSION_V2`/`V3`)
   - `u32` engine major, `u32` engine minor, `u32` engine patch
     (patch is informational; Godot validates major/minor)
   - `u32` pack flags (`PACK_DIR_ENCRYPTED` etc.), `u64` file base
   - V3: `u64` directory offset; V2: 16 reserved `u32`s, then the directory.
3. Match a template by **exact `major.minor`** under
   `templates/godot/<version>/linux_release.arm64`.
4. Run it. If no template matches or the game fails to boot → **Chromium fallback**,
   today's path, unchanged.

## Launching

- **`--main-pack` is disabled by default in template builds since Godot 4.6**
  ([PR #111909](https://github.com/godotengine/godot/pull/111909); the
  `disable_path_overrides` SCons option now defaults to on for templates; only the
  Web and Android templates are exempt). Official Linux ARM64 templates therefore
  will not accept `--main-pack`. Two options:
  - **Recommended: append the pck.** Copy the template binary, append the `.pck`
    after it, `chmod +x`, exec. This is exactly how Godot embeds data in exported
    Linux binaries (the engine searches for a pck header at the end of the
    executable), works with official *and* custom templates, and needs no flags.
  - Alternative: build custom templates with `disable_path_overrides=no` and use
    `--main-pack <file.pck>` (zero-copy, but every template must be custom-built).
- Renderer flags: `--rendering-method gl_compatibility --rendering-driver opengl3
  --fullscreen`. Web pcks are authored for the Compatibility renderer, and GL is the
  safe path on the Tegra X1 under L4T.

## Templates

- **Unencrypted pck → official templates.** The official `.tpz` ships
  `linux_release.arm64` for every 4.x version — zero compilation. The sync script
  collects the versions present in `itch-games.yaml`, downloads the matching `.tpz`
  once per version, and caches the template. The matrix is bounded by what the
  collection actually uses.
- **Encrypted pck → keyed template.** The PCK key is compiled into the template, so
  a custom ARM64 template must be built from source with the game's
  `SCRIPT_AES256_ENCRYPTION_KEY` (it must byte-match the key used when the pck was
  exported; official templates fail with `ERR_FILE_CORRUPT`). For Dragon Jump this
  is one custom Godot 4.6 template, published alongside `web.zip`/`windows.zip` in
  the `custom-templates` release; the rebuild recipe lives in the game repo's
  anti-piracy notes.

## Eligibility (contributor-visible)

- **Exact version match.** No forward compatibility: the engine refuses a pck from
  a newer version. Older pcks *may* load in a newer engine (the check allows it) but
  content/script compatibility is best-effort — never the default; a per-game
  "compat mode" is an experiment only.
- **GDScript only** (C# can't web-export in Godot 4).
- **No GDExtension**: the web pck carries no native extension binaries.
- `OS.has_feature("web")` branches flip to desktop behavior (native quit works,
  touch controls hide). Saves move from IndexedDB to `user://`.

## Verify on hardware

- **Texture variants:** web pcks may carry mobile (ETC2) variants; native desktop GL
  must decode them (Tegra supports ETC2). Check visuals before trusting.
- **Audio:** native template uses the system driver (PulseAudio/ALSA on L4T).
- **Input:** keyboard injection and Start+Select are unchanged; the window runs
  under Openbox/X11 like Chromium does.
- **Payoff measurement:** boot-to-menu time, `src/tests/test_frame_time.gd` frame
  time, memory. Startup + glue overhead is tier 3's main win over threaded web.

## Testing plan

1. Dragon Jump only — custom keyed 4.6 template, appended pck, compare against the
   Chromium build (boot time, frame time, audio, saves, leaderboards).
2. One unencrypted third-party Godot game from the collection — official template,
   no build work.
3. Then wire it into the sync script + ES launcher with Chromium fallback.

## Open questions

- Template cache location/size on the cabinet (one `linux_release.arm64` per
  version, ~60–100 MB each).
- ES `.sh` entry format for launching the game binary + the exit contract (native
  quit works; Start+Select force-quit remains the fallback).
- Auto-detection of the pck version and template fetch in `sync-itch-games.sh`.
