# Changelog

All notable changes to `sonify.py` / `unsonify.py`, in the order they were
developed. Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [1.5.0]

### Added: compose.py, a plain-text pattern composer
- New companion script that writes a raw byte file for `sonify.py` from a
  plain-text score, instead of relying on incidental data or hand-crafted
  bytes. Two kinds of content, freely mixable in one score:
  - **Metronomic sequencing** — `SEQ <value>[:<ticks>] ...` plays values
    one after another, each held for a chosen number of bytes, the same
    idea as `notes_to_bin.py`'s `NOTE:TICKS` format generalized beyond
    MIDI notes to arbitrary byte/colour values.
  - **Geometric patterns** — `STRIPES`, `CHECKER`, `GRADIENT` (linear or
    radial), `RINGS`, and `DIAGONAL`, all width-aware so they tile
    correctly once reshaped into an image, plus seeded `NOISE`.
  - `REPEAT n ... END` loops and `DEFINE name ... END` / `CALL name`
    reusable named motifs, with recursive `CALL` rejected outright rather
    than hanging.
- Values accept a raw byte 0-255, `REST`/`SILENCE`, or a colour name
  (`red`, `cyan`, `black`, ... ) resolved via `resolve_value()` to the
  byte that produces roughly that colour **under the chosen `--palette`**
  — deliberately palette-aware rather than a fixed table: `rainbow` never
  desaturates (byte 0 and 255 are both fully-saturated red), so `white`/
  `gray` are refused there with an explanatory error instead of silently
  picking the nearest available colour, and the hued names are refused
  under `--palette gray` for the same reason in reverse.
- `--preview PATH` renders a PNG via `sonify.make_image()`, imported
  directly from `sonify.py`, so the preview uses the exact same
  palette/image logic `sonify.py` itself would.
- Errors (unclosed `REPEAT`/`DEFINE`, undefined/recursive `CALL`,
  unknown commands, out-of-range/unrepresentable values, a geometric
  command before `WIDTH` is set) are reported with the offending line
  number, no raw traceback.
- Two example scores added under `examples/scores/` (`rhythm_demo.txt`,
  `geometry_demo.txt`), referenced from the README quick start.
- Documented in MANUAL.md (new "3. compose.py" section) and README.md.

## [1.4.0]

### Added: --color-gamma, to fix output clustering in a single hue
- Colour sensitivity normalization (on by default) only applies one
  **linear** factor sized to the file's loudest moment — it stretches the
  whole distribution uniformly but doesn't reshape it. Most real audio
  (e.g. a kick pattern) is mostly quiet with occasional peaks, so even at
  full normalization the bulk of the file still colours near byte 128's hue
  (cyan/blue in `rainbow`/`rainbow-bw`), with no way to spread it out.
- New `--color-gamma` (default `1.0`, no change) fixes this: the same
  expand-quiet-values technique `--amplitude-gamma` already applies to
  brightness, now applied to which byte gets looked up for hue instead.
  Values below `1.0` (e.g. `0.4`-`0.6`) push quiet-but-nonzero bytes further
  from the silence hue before the palette lookup, spreading output across
  more of the colour wheel. `--brightness-by-amplitude` brightness is
  computed from true (pre-`color_gamma`) loudness, so it's unaffected.
- Confirmed on a synthetic mostly-quiet-with-peaks byte stream: 7627/9080
  pixels landed in one hue bucket at `color_gamma=1.0` (default), spread
  across six buckets at `color_gamma=0.4`.
- `mono` colour space only, same as `--palette`/`--brightness-by-amplitude`/
  normalization — ignored (with a note) under `--colorspace rgb`/`yuv`.
- Documented in MANUAL.md (new "Colour spread" subsection) and README.md.

## [1.3.0]

### Fixed: video output was badly blurred, edges not sharp
- `make_video()` in both scripts previously handed ffmpeg no quality or
  bitrate control at all (`-c:v <codec> -pix_fmt yuv420p` and nothing else),
  leaving the encoder's own default rate control in charge. Flat, hard-edged
  colour blocks — exactly what this tool's output is made of — are close to
  worst-case content for H.264/H.265 compression at an uncontrolled/default
  bitrate, so output was visibly blurred/blocky even though `--scale-filter
  nearest` (the default) was correctly keeping the pre-encode frame sharp.
- New `--quality` flag (default `18`, range `0`-`51`, same scale as
  x264/x265 CRF — lower is better/larger) fixes this by pinning whichever
  encoder gets used to an explicit quality target via new `quality_args()`,
  mapped per vendor: `-crf` (CPU), `-cq`/VBR (nvenc), `-global_quality`
  (qsv), `-rc cqp`/`-qp_i`/`-qp_p` (amf), `-q:v` (videotoolbox). The default
  is near-visually-lossless; raise it only if file size matters more than
  crisp block edges.
- New `CODEC_TO_VENDOR` reverse-lookup so the right quality args are used
  even after a requested hardware encoder falls back to CPU.

## [1.2.0]

### Added: auto-numbered output filenames
- Both scripts now check each auto-generated output path (audio/image/video
  in `sonify.py`; image/WAV/video in `unsonify.py`) before writing, and
  insert a `_1`, `_2`, ... suffix before the extension if a file already
  exists there — e.g. `song_rainbow.png`, then `song_rainbow_1.png` on the
  next run against the same input/`--outdir`. Prevents a repeated or
  parameter-varying run from silently clobbering a previous run's output.
- New `unique_path()` helper in both scripts.
- Does not apply to explicitly-named output paths (`unsonify.py`'s
  `--save-bytes`) — those are still written exactly as given.

## [1.1.0]

### Added: colour spaces in unsonify.py
- `--colorspace {mono,rgb,yuv}` (default `mono`, unchanged behaviour):
  decides how decoded audio bytes become pixels, independent of `--palette`.
  - `mono` — existing 1-byte-per-pixel behaviour (`--palette` hue/brightness
    mapping).
  - `rgb` — 3 consecutive bytes used directly as one pixel's literal R, G, B
    channels, no palette lookup involved.
  - `yuv` — 3 consecutive bytes read as Y/U/V (BT.601) and converted to RGB.
  - `rgb`/`yuv` produce images/video with 3x fewer pixels than `mono` for
    the same input, since they consume 3 bytes per pixel instead of 1.
- New `bytes_to_pixels()` centralizes the byte-to-pixel-array conversion for
  all three colour spaces; `build_full_image()`, `build_row_window()`, and
  `make_video()` now route through it and are colour-space-aware.
- `--palette`, `--brightness-by-amplitude`/`--amplitude-gamma`, and colour
  sensitivity normalization remain `mono`-only (they depend on byte `128`
  meaning "silence"); passing them with `--colorspace rgb`/`yuv` now prints
  a note that they're ignored instead of silently having no effect.
- Output filenames for `rgb`/`yuv` are labelled by colour space
  (`<name>_rgb.png`, `<name>_yuv.mp4`, etc.) instead of by `--palette`.
- `unsonify.py`-only for now — `sonify.py`'s encode-side byte-mapping is
  unchanged.

## [1.0.0]

### sonify.py — initial version
- `--mode raw`: bytes used directly as 8-bit unsigned PCM audio samples.
- `--mode tone`: each byte rendered as a short sine tone, initially with a
  continuous linear frequency sweep (`--min-freq`/`--max-freq`).
- Colour byte-map image: each byte as one square block, `gray`/`rainbow`
  palettes, configurable `--width` (bytes per row) and `--pixel-size`.

### Added: video output
- MP4 generation scrolling through the byte-image in sync with the audio's
  actual duration (measured from the generated WAV, not assumed).
- `rainbow-bw` palette added (`0x00`/`0xFF` reserved as pure black/white).

### Added: unsonify.py (the reverse direction)
- Decodes any audio file (via ffmpeg) back to raw 8-bit unsigned PCM bytes
  at the source's native sample rate.
- Verified exact byte-for-byte round-trip with `sonify.py --mode raw` output.
- Same colour-mapping logic and video generation as `sonify.py`.

### Added: musical composition support
- `--note-map {linear,midi,scale}` for `sonify.py --mode tone`: quantized
  MIDI notes (12-tone equal temperament) instead of a raw frequency sweep,
  with optional snapping to a musical key/scale so arbitrary data still
  sounds tonal.
- `notes_to_bin.py`: converts a plain-text note score (scientific pitch
  notation, e.g. `C4:2 E4:2 G4:4 R:1`) into the raw byte file `sonify.py`
  expects, for deliberately composing rather than relying on incidental data.

### Added: GPU-accelerated video encoding
- `--encoder {auto,cpu,nvenc,qsv,amf,videotoolbox}`: detects available
  hardware encoders in the local ffmpeg build, then does a cheap 1-frame
  runtime test before committing to a full render — falls back to CPU
  automatically if the hardware encoder is only compiled-in but not
  actually backed by real hardware/drivers.
- `--codec {h264,hevc}`: HEVC support, since hardware H.264 encoders
  (including NVENC) cap out at 4096px on any single dimension.
- `--video-width`/`--video-height`: set an exact output resolution
  independent of the data grid, with aspect-ratio-preserving single-axis
  scaling.
- `--scale-filter {nearest,lanczos,bicubic}`, defaulting to `nearest`:
  keeps byte-square edges perfectly crisp rather than blurred/ringing,
  which is the objectively correct choice for this grid-of-flat-colour
  content (confirmed via a controlled black/white block test).

### Added: colour-coded console output
- `print_field`/`print_note`/`print_warning`/`print_error` helpers with
  ANSI colour, auto-disabled on non-TTY output or `NO_COLOR`, with a
  Windows `cmd.exe` ANSI-enable workaround.
- Live progress line during video rendering: frame count, percentage,
  elapsed/remaining time, render fps — each field individually coloured.

### Fixed: memory and performance
- **Critical fix:** the standalone PNG and video rendering previously
  built the *entire* byte-image in memory upfront. For a real audio file
  at default settings this could demand tens of gigabytes and crash with
  `MemoryError`. Fixed via:
  - `safe_pixel_size()`: automatically reduces the PNG's effective
    pixel-size if the full image would exceed a safety cap (configurable
    via `--max-image-pixels`; `--no-image` to skip the PNG entirely).
  - `build_row_window()`: video rendering now builds only the small
    window of rows needed for the current frame, bounding memory use by
    viewport size rather than total file length — scales to files of any
    length.
- Vectorized all byte-to-colour mapping with numpy (`palette_lut()`,
  precomputed 256×3 lookup table) instead of per-pixel Python loops —
  roughly 5-6x rendering speedup as a side effect of the memory fix.

### Added: clean interruption handling
- Ctrl+C during video rendering now terminates the ffmpeg subprocess
  cleanly (escalating to a hard kill if needed) and deletes the
  incomplete output file, rather than leaving a corrupt MP4 or an orphaned
  ffmpeg process. Clean `Cancelled.` message and exit code 130 instead of
  a raw traceback.
- ffmpeg crashing mid-encode (e.g. an invalid encoder/resolution
  combination) now gives a clear error message with the same cleanup,
  instead of an opaque `BrokenPipeError`.

### Added: unsonify.py-specific colour/volume features
- `--brightness-by-amplitude` (+ `--amplitude-gamma`): scales each byte's
  colour brightness by how loud that sample actually is (distance from
  128, the silence midpoint), instead of every non-silent byte rendering
  at full brightness regardless of volume.
- **Colour sensitivity normalization, on by default:** `unsonify.py` now
  analyzes the actual peak amplitude present in the decoded audio and
  stretches the colour mapping to that file's real dynamic range. Most
  real recordings never reach true digital full-scale, so without this,
  output tends to cluster in a narrow hue band near the silence colour
  (e.g. mostly cyan/blue in the `rainbow` palette). `--no-normalize` to
  disable and colour by raw byte values directly.

### Documentation
- `MANUAL.md`: full function-by-function and flag-by-flag reference for
  both scripts, plus the shared concepts (palettes, resolution handling,
  GPU encoding, memory/performance, colour-coded output, volume-to-
  brightness) that only make sense documented once, together.
