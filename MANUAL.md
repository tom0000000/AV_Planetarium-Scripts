# sonify.py / unsonify.py — Manual

Two companion tools for turning data into sound-and-colour, and back again.

- **`sonify.py`** — reads any file's raw bytes → produces audio (WAV), a colour
  byte-map (PNG), and a scrolling video synced to the audio (MP4).
- **`unsonify.py`** — reads any audio file → decodes it back to raw bytes,
  producing the same colour byte-map (PNG) and scrolling video (MP4), plus
  optionally the raw bytes themselves (BIN).

They share the same colour-mapping logic, so an image/video from one lines up
visually with the other. Both require **ffmpeg** on your PATH for video output
(ffmpeg also provides `ffprobe`, used by `unsonify.py` for non-`.wav` inputs).

---

## Requirements

- Python 3
- `pip install pillow numpy`
- `ffmpeg` on PATH (video output and non-`.wav` decoding). Check with:
  ```
  ffmpeg -version
  ```

---

## 1. sonify.py

### What it does

Reads a file's bytes and turns them into sound two ways, plus a colour image
of the same bytes:

- **`--mode raw`** (default) — every byte is used directly as one 8-bit
  unsigned PCM audio sample. Fast, harsh, "data-bent"/glitch aesthetic — this
  is a literal one-to-one mapping, not a musical rendering.
- **`--mode tone`** — every byte becomes a short tone. How the byte picks a
  pitch is controlled by `--note-map`:
  - `linear` (default) — byte value slides continuously between
    `--min-freq` and `--max-freq`. No fixed notes, glissando-like.
  - `midi` — byte value modulo 128 is read as a standard MIDI note number
    (12-tone equal temperament, A440). Byte `255` is reserved as silence
    (rest). Deterministic: byte `60` is always middle C, `67` is always G4.
  - `scale` — same as `midi`, but every note is snapped to the nearest tone
    in a given `--key`/`--scale-mode` (e.g. C major), so arbitrary/noisy
    data still lands on in-key notes instead of sounding atonal.

Alongside the audio, it always renders a **colour byte-map image**: each byte
becomes one square block of colour, wrapping at `--width` bytes per row. By
default it also renders an **MP4** that scrolls down through that image in
sync with the audio's actual duration.

### Usage

```
python3 sonify.py input_file
python3 sonify.py input_file --mode tone --note-map scale --key C --scale-mode major
python3 sonify.py input_file --sample-rate 22050 --width 128 --outdir out/
python3 sonify.py input_file --video-width 6984 --encoder nvenc --codec hevc
python3 sonify.py input_file --video-width 6894 --video-height 1920 --scale-filter nearest
python3 sonify.py input_file --video-width 2328 --video-height 640 --quality 12
```

### CLI reference

| Flag | Default | Description |
|---|---|---|
| `input` | — | Path to any file (required, positional) |
| `--mode {raw,tone}` | `raw` | Audio generation mode |
| `--note-map {linear,midi,scale}` | `linear` | Pitch mapping for `tone` mode |
| `--key` | `C` | Key root for `--note-map scale` (any of `C C# Db D D# Eb E F F# Gb G G# Ab A A# Bb B`) |
| `--scale-mode` | `major` | Scale for `--note-map scale`: `major`, `minor`, `pentatonic_major`, `pentatonic_minor`, `chromatic` |
| `--min-freq` | `80` | Lowest frequency (Hz) for `--note-map linear` |
| `--max-freq` | `2000` | Highest frequency (Hz) for `--note-map linear` |
| `--ms-per-byte` | `15` | Duration of each tone in milliseconds, `tone` mode only |
| `--sample-rate` | `44100` | Audio sample rate |
| `--palette {gray,rainbow,rainbow-bw}` | `rainbow` | Colour mapping — see [Palettes](#palettes) below |
| `--width` | `64` | Bytes per row in the image/video data grid |
| `--pixel-size` | `64` | Pixels per byte-square |
| `--outdir` | `.` | Output directory |
| `--no-video` | off | Skip MP4 generation (audio + image only) |
| `--fps` | `30` | Video frame rate |
| `--viewport-height` | `480` | Height (px) of the scrolling window in the data grid |
| `--video-width` | none | Final output video width, overriding the grid-derived size — see [Resolution](#resolution) |
| `--video-height` | none | Final output video height, overriding `--viewport-height` |
| `--encoder {auto,cpu,nvenc,qsv,amf,videotoolbox}` | `auto` | Video encoder vendor — see [GPU encoding](#gpu-encoding) |
| `--codec {h264,hevc}` | `h264` | Video codec family — see [GPU encoding](#gpu-encoding) |
| `--scale-filter {nearest,lanczos,bicubic}` | `nearest` | Resampling used when resizing to `--video-width`/`--video-height` — see [Resolution](#resolution) |
| `--quality` | `18` | Video encoding quality, 0 (best/largest) to 51 (worst/smallest), same scale as x264/x265 CRF — see [Quality](#quality) |
| `--no-image` | off | Skip standalone PNG generation entirely — see [Memory & performance](#memory--performance) |
| `--max-image-pixels` | `50,000,000` | Safety cap (total pixels) for the standalone PNG before `--pixel-size` is auto-reduced — see [Memory & performance](#memory--performance) |

### Outputs (in `--outdir`)

- `<name>_<mode>.wav` — the audio
- `<name>_<palette>.png` — the full colour byte-map image (unless `--no-image`)
- `<name>_<mode>_<palette>.mp4` — the scrolling video (unless `--no-video`)

If a file already exists at one of these paths (e.g. from a previous run
against the same input/`--outdir`), a numeric suffix is inserted before the
extension — `test_raw.wav`, then `test_raw_1.wav`, `test_raw_2.wav`, etc. —
so repeated runs never silently overwrite prior output. See `unique_path()`.

### Function reference

| Function | Purpose |
|---|---|
| `midi_to_freq(note)` | Converts a MIDI note number to frequency (Hz) via 12-tone equal temperament, A440 |
| `snap_to_scale(note, key, scale_mode)` | Moves a MIDI note to the nearest pitch in a given key/scale, preserving register |
| `read_bytes(path)` | Reads a file's raw bytes |
| `unique_path(path)` | Returns `path` unchanged if free, otherwise inserts a `_1`, `_2`, ... suffix before the extension until an unused path is found — prevents repeated runs from overwriting prior output |
| `make_raw_audio(data, sample_rate, out_path)` | Writes bytes directly as 8-bit unsigned PCM (`--mode raw`) |
| `make_tone_audio(data, sample_rate, out_path, ...)` | Renders each byte as a tone per `--note-map` (`--mode tone`) |
| `byte_to_color(b, palette)` | Maps a single byte to an RGB colour under the given palette |
| `palette_lut(palette)` | Precomputes a 256×3 lookup table of `byte_to_color` results, so colouring a whole array of bytes is one numpy fancy-index lookup instead of per-pixel Python calls — see [Memory & performance](#memory--performance) |
| `build_full_image(data, width, pixel_size, palette)` | Builds the full byte-map image via vectorized numpy (LUT lookup + `repeat` upscale) |
| `safe_pixel_size(n, width, requested_pixel_size, max_total_pixels)` | Shrinks pixel-size for the standalone PNG if the full image would need unreasonable memory — see [Memory & performance](#memory--performance) |
| `make_image(data, width, pixel_size, palette, out_path, max_total_pixels)` | Applies `safe_pixel_size` and saves the byte-map image to disk |
| `build_row_window(data, width, pixel_size, palette, row_start, row_count)` | Renders only a small slice of rows, used by `make_video` so memory/render time is bounded by the viewport, not the whole file — see [Memory & performance](#memory--performance) |
| `wav_duration_seconds(wav_path)` | Reads a WAV's exact duration |
| `list_ffmpeg_encoders()` | Returns the list of encoders this ffmpeg build supports |
| `choose_encoder(preference, codec_family)` | Picks the ffmpeg video codec per `--encoder`/`--codec` (see [GPU encoding](#gpu-encoding)) |
| `test_encoder_runtime(codec, width, height)` | Confirms a hardware encoder actually works (not just compiled in) via a 1-frame test encode |
| `quality_args(vendor, quality)` | Maps `--quality` to the target encoder vendor's actual rate-control flags — see [Quality](#quality) |
| `format_hms(seconds)` | Formats seconds as `H:MM:SS` for the progress display |
| `resolve_output_size(grid_w, grid_h, video_width, video_height)` | Works out the final video resolution (see [Resolution](#resolution)) |
| `make_video(...)` | Renders the scrolling MP4 frame-by-frame via `build_row_window`, muxing video + audio via ffmpeg — resizes via `SCALE_FILTERS[scale_filter]` when `--video-width`/`--video-height` require it |
| `print_field/print_note/print_warning/print_error` | Colour-coded console output helpers — see [Colour-coded output](#colour-coded-output) |
| `main()` | CLI entry point — parses args, calls the above in order |

---

## 2. unsonify.py

### What it does

The reverse of `sonify.py`: takes **any audio file** ffmpeg can decode (wav,
mp3, flac, aiff, etc.) and converts it to raw 8-bit unsigned mono PCM — i.e.
every audio sample becomes exactly one byte, 0–255 — at the file's **native**
sample rate (no resampling, so nothing is altered beyond bit-depth/channel
reduction).

If the input was originally produced by `sonify.py --mode raw`, this recovers
the **exact original bytes** (verified byte-for-byte in testing). Fed an
arbitrary audio file instead, it still works — it just decodes whatever PCM
samples are actually present, without an "original file" to recover.

Those bytes are then rendered with the same colour-block logic as
`sonify.py` (`gray`/`rainbow`/`rainbow-bw`), plus by default an MP4 that
scrolls through the byte-image in sync with the audio. The audio track used
for that video is a **freshly rebuilt WAV from the extracted bytes** (not the
original input file), which guarantees the video and its audio come from the
exact same underlying byte data, frame-accurate, regardless of the input's
original format/codec.

### Usage

```
python3 unsonify.py input.wav
python3 unsonify.py song.mp3 --palette rainbow-bw --width 128 --pixel-size 4
python3 unsonify.py input.wav --no-video --save-bytes recovered.bin
python3 unsonify.py long_recording.wav --no-image
python3 unsonify.py long_recording.wav --max-image-pixels 500000000
python3 unsonify.py drone.wav --brightness-by-amplitude --amplitude-gamma 0.5
python3 unsonify.py song.mp3 --colorspace rgb
python3 unsonify.py song.mp3 --colorspace yuv --width 96
python3 unsonify.py kick-pattern.wav --video-width 2328 --video-height 640 --quality 12
python3 unsonify.py kick-pattern.wav --palette rainbow-bw --color-gamma 0.4
```

### CLI reference

| Flag | Default | Description |
|---|---|---|
| `input` | — | Path to any audio file (required, positional) |
| `--palette {gray,rainbow,rainbow-bw}` | `rainbow` | Colour mapping — see [Palettes](#palettes) |
| `--width` | `64` | Bytes per row in the image/video data grid |
| `--pixel-size` | `64` | Pixels per byte-square |
| `--outdir` | `.` | Output directory |
| `--save-bytes PATH` | none | Also save the extracted raw bytes to this `.bin` file |
| `--no-video` | off | Skip MP4 generation (image only) |
| `--fps` | `30` | Video frame rate |
| `--viewport-height` | `480` | Height (px) of the scrolling window in the data grid |
| `--video-width` | none | Final output video width, overriding the grid-derived size |
| `--video-height` | none | Final output video height, overriding `--viewport-height` |
| `--encoder {auto,cpu,nvenc,qsv,amf,videotoolbox}` | `auto` | Video encoder vendor — see [GPU encoding](#gpu-encoding) |
| `--codec {h264,hevc}` | `h264` | Video codec family — see [GPU encoding](#gpu-encoding) |
| `--scale-filter {nearest,lanczos,bicubic}` | `nearest` | Resampling used when resizing to `--video-width`/`--video-height` — see [Resolution](#resolution) |
| `--quality` | `18` | Video encoding quality, 0 (best/largest) to 51 (worst/smallest), same scale as x264/x265 CRF — see [Quality](#quality) |
| `--brightness-by-amplitude` | off | Scale colour brightness by loudness (distance from silence) instead of every non-silent byte rendering at full brightness — see [Volume-to-brightness](#volume-to-brightness) |
| `--amplitude-gamma` | `0.6` | Only with `--brightness-by-amplitude`. Gamma curve lifting quiet-but-audible sounds above near-black — see [Volume-to-brightness](#volume-to-brightness) |
| `--no-normalize` | off | Disable peak-based colour normalization (on by default) and colour bytes by their raw value directly — see [Colour spread](#colour-spread---color-gamma) |
| `--color-gamma` | `1.0` | Reshapes which byte gets looked up for hue, spreading output across more of the colour wheel for mostly-quiet audio — see [Colour spread](#colour-spread---color-gamma) |
| `--no-image` | off | Skip standalone PNG generation entirely — see [Memory & performance](#memory--performance) |
| `--max-image-pixels` | `50,000,000` | Safety cap (total pixels) for the standalone PNG before `--pixel-size` is auto-reduced — see [Memory & performance](#memory--performance) |
| `--colorspace {mono,rgb,yuv}` | `mono` | How bytes become pixels — see [Colour spaces](#colour-spaces) |

### Outputs (in `--outdir`)

- `<name>_<palette-or-colorspace>.png` — the byte-map image (unless `--no-image`); named by `--palette` under `mono`, by `--colorspace` under `rgb`/`yuv`
- `<name>_audio.wav` — the WAV rebuilt from extracted bytes (only if generating video)
- `<name>_<palette-or-colorspace>.mp4` — the scrolling video (unless `--no-video`)
- the file at `--save-bytes`, if given — raw extracted bytes (written as given, not auto-numbered — see below)

If a file already exists at one of the auto-generated paths above (e.g. from
a previous run against the same input/`--outdir`), a numeric suffix is
inserted before the extension — `song_rainbow.png`, then
`song_rainbow_1.png`, `song_rainbow_2.png`, etc. — so repeated runs never
silently overwrite prior output. See `unique_path()`. This does **not**
apply to `--save-bytes`, since that path is explicitly chosen by the caller.

### Function reference

| Function | Purpose |
|---|---|
| `get_sample_rate(audio_path)` | Reads the input's native sample rate — via Python's `wave` module for `.wav` (no external tool needed), via `ffprobe` for other formats |
| `decode_to_bytes(audio_path, sample_rate)` | Uses ffmpeg to decode any audio file to raw 8-bit unsigned mono PCM bytes at the given rate |
| `write_wav(data, sample_rate, out_path)` | Writes bytes as an 8-bit unsigned mono WAV |
| `unique_path(path)` | Same as in `sonify.py` — prevents repeated runs from overwriting prior auto-named output |
| `wav_duration_seconds(wav_path)` | Reads a WAV's exact duration |
| `byte_to_color(b, palette)` | Same as in `sonify.py` — maps a byte to an RGB colour, used by the `mono` colour space |
| `bytes_to_pixels(data, colorspace, palette, brightness_by_amplitude, amplitude_gamma, normalize_scale)` | Turns raw bytes into an `(N, 3)` RGB pixel array under the selected colour space — see [Colour spaces](#colour-spaces) |
| `pixel_count_for(n_bytes, colorspace)` | Pixel count for a given byte count under a colour space — `n_bytes` for `mono`, `n_bytes // 3` for `rgb`/`yuv` |
| `palette_lut(palette, brightness_by_amplitude, amplitude_gamma, normalize_scale, color_gamma)` / `build_full_image(...)` | Vectorized numpy colour lookup and full byte-map image build — colour-space-aware via `bytes_to_pixels()`, with optional amplitude-based brightness scaling and hue-spread reshaping (`mono` only), see [Volume-to-brightness](#volume-to-brightness) and [Colour spread](#colour-spread---color-gamma) |
| `safe_pixel_size(...)` | Same as in `sonify.py` — see [Memory & performance](#memory--performance); takes a pixel count (via `pixel_count_for`), not a raw byte count |
| `build_row_window(...)` | Same as in `sonify.py`, now also amplitude-brightness-aware and colour-space-aware — used by `make_video` for bounded-memory frame rendering |
| `list_ffmpeg_encoders()` / `choose_encoder()` / `test_encoder_runtime()` / `quality_args()` | Same as in `sonify.py`, codec-family-aware — see [GPU encoding](#gpu-encoding) |
| `format_hms(seconds)` | Same as in `sonify.py` |
| `resolve_output_size(...)` | Same as in `sonify.py` — see [Resolution](#resolution) |
| `make_video(...)` | Same approach as in `sonify.py` (windowed rendering, `scale_filter`-aware resize, amplitude-brightness-aware), but the audio track is a WAV rebuilt from the decoded bytes rather than the original input |
| `print_field/print_note/print_warning/print_error` | Same as in `sonify.py` — see [Colour-coded output](#colour-coded-output) |
| `main()` | CLI entry point |

### Volume-to-brightness

This is `unsonify.py`-specific, not shared with `sonify.py` — it relies on
the audio-specific fact that byte `128` means silence (the zero-amplitude
midpoint in 8-bit unsigned PCM), which only holds when the bytes actually
came from decoded audio.

By default, hue changes with byte value but brightness (HSV "value") is
always maxed at 1.0 regardless of how loud that sample actually was — so a
byte just barely off from silence (e.g. `132`, a very quiet sound) renders
exactly as vivid as a full-scale peak (`0` or `255`). Only the colour
differs, not the intensity, which makes it hard to visually read volume from
the output at all.

`--brightness-by-amplitude` fixes this: `palette_lut()` additionally scales
each colour's brightness by `abs(byte - 128) / 128`, so quiet passages
render dim and loud passages render bright, on top of the existing
hue-per-byte-value mapping. `--amplitude-gamma` (default `0.6`) applies a
power curve to that scaling — `1.0` is linear and crushes quiet-but-audible
sound toward near-black quickly (most real audio spends most of its time
near silence); lower values lift quiet sound so it stays visible rather than
disappearing. Confirmed effect on a real byte, palette `rainbow`:

| Byte | Meaning | Colour without `--brightness-by-amplitude` | Colour with it (`gamma=0.6`) |
|---|---|---|---|
| `132` | Barely audible | `(0, 227, 255)` — fully bright | `(0, 28, 31)` — dim |
| `255` | Full-scale peak | `(255, 0, 0)` — fully bright | `(253, 0, 0)` — still fully bright |

### Colour spread (--color-gamma)

Also `unsonify.py`-specific, `--colorspace mono` only. Normalization
(`--no-normalize` off, the default) only applies a single **linear** factor
sized to the file's loudest moment — it stretches the whole distribution
uniformly, it doesn't reshape it. Most real audio (a kick pattern especially)
is mostly quiet with occasional peaks, so even at full normalization the
bulk of the file still sits close to byte `128` and renders in whichever
single hue lives there (cyan/blue in `rainbow`/`rainbow-bw`) — normalization
alone can't fix that, since it scales quiet and loud parts by the same
factor.

`--color-gamma` (default `1.0`, no change) fixes this by reshaping *which
byte gets looked up for hue* — the same expand-quiet-values technique
`--amplitude-gamma` already applies to brightness, applied to hue position
instead: `magnitude = (abs(byte-128)/128) ** color_gamma`, re-centred around
128. Values below `1.0` (e.g. `0.4`-`0.6`) push quiet-but-nonzero bytes
further from the silence hue before the palette lookup, spreading the output
across more of the colour wheel instead of clustering in one hue. Brightness
(`--brightness-by-amplitude`) is computed from the true, pre-`color_gamma`
loudness, so it isn't affected — only hue diversity changes.

Confirmed effect on a synthetic "mostly-quiet-with-peaks" byte stream (9080
bytes, `rainbow-bw`, normalized): at the default `color_gamma=1.0`, 7627 of
9080 pixels landed in a single 1/12th hue bucket; at `color_gamma=0.4`, the
same data spread across six hue buckets instead.

```
python3 unsonify.py kick-pattern.wav --palette rainbow-bw --color-gamma 0.4
```

### Colour spaces

Also `unsonify.py`-specific. `--colorspace` decides what a "pixel" *is*,
independent of `--palette`:

| Colour space | Bytes per pixel | How | Notes |
|---|---|---|---|
| `mono` (default) | 1 | Each byte is one pixel, coloured via `--palette`'s hue/brightness mapping (`byte_to_color`) | The only mode `--palette`, `--brightness-by-amplitude`, and colour normalization apply to |
| `rgb` | 3 | Three consecutive bytes are used directly as one pixel's literal R, G, B channel values — no lookup, no hue mapping | Same direct byte-to-channel technique as the binary-waterfall project's "rgb" format |
| `yuv` | 3 | Three consecutive bytes are read as Y (luma), U, V (chroma) and converted to RGB via the standard BT.601 formula, treating U/V as signed offsets from 128 | Chroma-heavy byte patterns produce saturated colour; near-128 U/V (common in quiet/uniform data) reads close to grayscale |

Because `rgb`/`yuv` consume 3 bytes per pixel instead of 1, images and video
are correspondingly **3x smaller** (fewer total pixels) than the same file
under `mono`. A trailing 1–2 byte remainder that doesn't complete a final
pixel is dropped.

`--palette`, `--brightness-by-amplitude`/`--amplitude-gamma`, and colour
sensitivity normalization are all `mono`-only concepts (they rely on byte
`128` meaning "silence," which only applies to the single-byte
interpretation) — passing them alongside `--colorspace rgb`/`yuv` prints a
note that they're being ignored rather than silently doing nothing.

---

## Shared concepts

### Palettes

Both scripts use the same `byte_to_color(b, palette)` logic:

| Palette | Byte `0x00` | Byte `0xFF` | In between | Byte `0x80` (128) |
|---|---|---|---|---|
| `gray` | black | white | linear greyscale ramp | **black** (silence override) |
| `rainbow` | red | red (full hue wrap) | full HSV hue sweep, saturation/value = 1.0 | **black** (silence override) |
| `rainbow-bw` | **pure black** (reserved) | **pure white** (reserved) | hue sweep over remaining 254 values | **black** (silence override) |

**Silence override:** byte value `128` — the zero-amplitude midpoint in 8-bit
unsigned PCM audio — always renders as pure black, in every palette. This
applies globally, not just to audio-derived data: if you sonify an arbitrary
non-audio file and a byte happens to equal `128`, it renders black too, since
the script can't distinguish "silence" from "just the value 128" in
arbitrary data.

### Resolution

By default, video resolution is **derived** from the data grid:
`width_px = --width × --pixel-size`, `height_px = --viewport-height`. This
couples resolution to how bytes are grouped per row.

To set an exact resolution independent of that grid, use `--video-width` /
`--video-height` (`resolve_output_size()`):
- Both given → exact target size (frame is resized/stretched to fit)
- Only one given → the other scales automatically to preserve aspect ratio
- Neither given → unchanged, grid-derived size

Odd dimensions are bumped to the nearest even number automatically (required
by `libx264`/`yuv420p`).

**`--scale-filter`** controls *how* that resize happens, via `SCALE_FILTERS`:

| Value | Behaviour |
|---|---|
| `nearest` (default) | Point sampling — no blending at all. Every byte-square's edge stays a perfectly hard cut. |
| `lanczos` | Windowed-sinc interpolation — sharp and high quality for photographic/continuous-tone images, but rings and blurs across the hard edges this content is made of. |
| `bicubic` | Smoother still than lanczos, same edge-blurring problem for this content. |

This matters because the content is fundamentally a grid of flat colour
blocks, not a continuous image — algorithms designed to reconstruct smooth
gradients actively work against that. A controlled test (scaling a
black/white block pattern 8x) shows the difference starkly: `nearest`
produces `(0,0,0)` sitting directly against `(255,255,255)` with nothing in
between, while `lanczos` produces a ~16-pixel-wide grey ramp straddling every
edge. `nearest` is also noticeably faster to compute, as a side effect of
being a much simpler algorithm — roughly 1.5–2x the frames/second of
`lanczos` in testing. Reach for `lanczos`/`bicubic` only if you deliberately
want a softened, anti-aliased look rather than crisp blocks.

### GPU encoding

Two flags together control how the MP4 is encoded: `--encoder` picks the
**vendor**, `--codec` picks the **codec family**.

`--encoder`:

| Value | Vendor |
|---|---|
| `auto` (default) | first available of nvenc → qsv → amf → videotoolbox, else CPU |
| `cpu` | software encoding (no GPU) |
| `nvenc` | NVIDIA |
| `qsv` | Intel Quick Sync |
| `amf` | AMD |
| `videotoolbox` | Apple Silicon / macOS |

`--codec`:

| Value | Effect |
|---|---|
| `h264` (default) | most widely compatible, but hardware H.264 encoders (including `h264_nvenc`) cap out at **4096px** on any single dimension |
| `hevc` | H.265 — no such cap, needed for wider/taller GPU-encoded output. Uses `libx265` on CPU, or the vendor's `hevc_*` encoder on GPU. HEVC output is tagged `hvc1` in the MP4 container automatically, for wider player compatibility (untagged HEVC-in-MP4 often fails to play in QuickTime/Apple software) |

The two combine into the actual ffmpeg codec via `ENCODER_CODECS`, e.g.
`--encoder nvenc --codec hevc` → `hevc_nvenc`; `--encoder cpu --codec hevc` →
`libx265`.

Selection happens in two steps: `choose_encoder()` checks which encoders this
ffmpeg *build* supports (compiled-in support only), then `test_encoder_runtime()`
does a cheap one-frame test encode to confirm real hardware actually responds
before committing to the full render. If the hardware encoder fails either
check, it falls back to the CPU encoder for that codec family (`libx264` or
`libx265`) with a printed warning — rendering should never hard-fail just
because a GPU isn't present or a specific encoder isn't available.

If you request `--codec h264` together with a GPU `--encoder` and a
resolution over 4096px in either dimension, both scripts print an advisory
up front suggesting `--codec hevc`, since that combination is essentially
guaranteed to fail the runtime test and silently fall back to slower CPU
encoding otherwise.

#### Quality

`--quality` (default `18`, range `0`-`51`, same scale as x264/x265 CRF —
lower is better/larger) pins the chosen encoder to a target quality via
`quality_args()`, instead of leaving rate control at that encoder's own
default. This matters a lot for this tool's output specifically: flat,
hard-edged colour blocks are close to worst-case content for H.264/H.265's
DCT-based compression, and an uncontrolled default bitrate (tuned for
natural video, which has far less high-frequency detail) visibly blurs and
blocks the byte-square edges. The default of `18` is near-visually-lossless;
raise it (e.g. `30`-`40`) only if file size matters more than crisp edges.

`quality_args()` maps the same `--quality` value to each vendor's actual
flags:

| Vendor | Args |
|---|---|
| `cpu` | `-preset medium -crf <quality>` |
| `nvenc` | `-preset p5 -rc vbr -cq <quality> -b:v 0` |
| `qsv` | `-global_quality <quality>` |
| `amf` | `-rc cqp -qp_i <quality> -qp_p <quality> -quality quality` |
| `videotoolbox` | `-q:v <100 - quality*2>` (videotoolbox has no CRF; approximated on its 1-100, higher-is-better scale) |

The vendor is looked up from the final, already-fallback-resolved codec via
`CODEC_TO_VENDOR` (the reverse of `ENCODER_CODECS`), so the right quality
args are used even when a requested hardware encoder fell back to CPU.

**Progress display:** during rendering, both scripts print a live-updating
line: frame count, percentage, elapsed time, estimated remaining time, and
frames-per-second — this measures the Python/numpy frame-rendering loop, not
ffmpeg's own encoding speed, since that loop is almost always the actual
bottleneck (ffmpeg just receives finished frames).

### Colour-coded output

Console output from both scripts is colour-coded via a small set of shared
helpers:

| Helper | Colour | Used for |
|---|---|---|
| `print_field(label, value)` | bold green label | Output paths — `Input:`, `Audio:`, `Image:`, `Video:`, `Bytes:`, `Encoder:` |
| `print_note(msg)` | cyan | Informational notes — e.g. pixel-size reduced, resolution exceeds a codec limit |
| `print_warning(msg)` | bold yellow | Recoverable problems — e.g. a requested hardware encoder fell back to CPU |
| `print_error(msg)` | bold red | Fatal errors (caught at the top level in `if __name__ == "__main__"`, printed, then exit code 1) |

The live progress line also colours its own fields individually: percentage
(bold), elapsed (dim), remaining (yellow), fps (green).

Colour is applied only when it will actually render correctly:
- Automatically disabled if stdout isn't a real terminal (e.g. output is
  piped or redirected to a file) or if the `NO_COLOR` environment variable
  is set.
- On Windows, `_enable_windows_ansi()` turns on ANSI escape processing for
  older `cmd.exe` consoles that don't support it by default (a best-effort
  `SetConsoleMode` call; silently does nothing if it fails or doesn't apply
  — colour just stays off in that case rather than printing garbled escape
  codes).

### Memory & performance

Rendering a byte-map at `--pixel-size` scales with **file size**, not just
image dimensions — a long audio file at the default settings can otherwise
demand tens of gigabytes of RAM. Both scripts guard against this in two
different ways, for the two different outputs:

**Standalone PNG** — `build_full_image` still materializes the whole image
at once (there's no way around this for a single static image file), so
`safe_pixel_size()` automatically shrinks the *effective* pixel-size used for
this specific output — never below 1px per byte — if the full-resolution
version would exceed `--max-image-pixels` (default 50,000,000, ~150MB as raw
RGB). When this triggers, a note is printed explaining the reduction; video
generation is unaffected and always uses your requested `--pixel-size`
directly, for the reason below. Two ways to get more resolution back:
- Raise `--max-image-pixels` if your machine has the RAM for it — this is a
  direct memory tradeoff, not a trick: a genuinely full-resolution image of
  a large file needs that much memory to exist, so set this based on what
  your machine can actually handle rather than maximizing it blindly.
- Pass `--no-image` to skip the PNG entirely and only pay the (much smaller,
  bounded) memory cost of the video.

**Video** — rather than building one giant image and cropping a window out
of it per frame, `make_video` calls `build_row_window()` to render only the
small slice of rows needed for the current frame (roughly
`viewport_height / pixel_size` rows, plus a small margin). This bounds
memory use — and, since less data needs colouring, render time — by the
*viewport size*, not the total file length, so video generation scales to
files of any length without needing a cap or a flag.

**Vectorization:** both `build_full_image` and `build_row_window` colour
bytes via `palette_lut()` — a precomputed 256×3 numpy lookup table — plus
`numpy.repeat` to upscale to the final pixel size, rather than looping over
individual pixels in Python. This is what makes `numpy` a requirement, and
gave roughly a 5–6x rendering speedup over the earlier pure-Python approach.

---

## Composing music (tone mode)

Since `tone` mode's `linear` mapping gives a continuous pitch sweep (no fixed
notes), composing an actual melody means writing a file where each byte is a
deliberately chosen note. The companion script **`notes_to_bin.py`** does
this: it takes a plain-text score and writes the corresponding raw byte file.

**Score format:** whitespace-separated tokens:
- `NOTE` (e.g. `C4`, `F#3`, `Bb5`) — scientific pitch notation, `C4` = middle C
- `NOTE:TICKS` (e.g. `C4:4`) — holds the note for 4 ticks instead of 1
- `R` or `R:TICKS` — a rest (silence) for that many ticks

One "tick" = one byte = one fixed time-slice in `sonify.py`'s tone mode,
whose duration is set by `--ms-per-byte`.

```
python3 notes_to_bin.py score.txt melody.bin
python3 sonify.py melody.bin --mode tone --note-map midi --ms-per-byte 150
```

For **arbitrary data** you didn't author note-by-note, use `--note-map scale`
instead — it snaps every byte to the nearest in-key note, so noisy/incidental
data still comes out tonal rather than atonal.

---

## Round-tripping

Because both scripts share identical colour and byte-mapping logic, they form
a closed loop:

```
python3 sonify.py somefile.bin --mode raw --no-video
python3 unsonify.py somefile_raw.wav --save-bytes recovered.bin
cmp somefile.bin recovered.bin   # identical, byte-for-byte
```

This only holds exactly for `--mode raw` output (bytes used directly as PCM
samples). `--mode tone` output can still be decoded by `unsonify.py`, but
what you get back is the *tone waveform's* raw samples, not the original
byte sequence.
