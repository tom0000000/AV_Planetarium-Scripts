# Changelog

All notable changes to `sonify.py` / `unsonify.py`, in the order they were
developed. Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

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
