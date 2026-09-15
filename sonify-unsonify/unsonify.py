#!/usr/bin/env python3
"""
unsonify.py — the reverse of sonify.py: take an audio file, get a byte map.

Any audio format ffmpeg can decode (wav, mp3, flac, aiff, etc.) is converted
to raw 8-bit unsigned mono PCM — i.e. each audio sample becomes exactly one
byte, 0-255 — at the file's native sample rate (no resampling, so nothing
is lost or altered beyond bit-depth/channel reduction). If your file was
originally produced by sonify.py's --mode raw, this recovers the exact
original bytes.

Those bytes are then rendered using the same colour-block image logic as
sonify.py (gray / rainbow / rainbow-bw). By default it also outputs an MP4
that scrolls through the byte-image in sync with the audio (a WAV is
rebuilt from the extracted bytes so the video and audio are guaranteed to
come from the exact same data — use --no-video to skip this and get an
image only).

Requires ffmpeg (and ffprobe, which ships alongside it) on PATH.

Usage:
  python3 unsonify.py input.wav
  python3 unsonify.py song.mp3 --palette rainbow-bw --width 128 --pixel-size 4
  python3 unsonify.py input.wav --no-video --save-bytes recovered.bin
"""

import argparse
import colorsys
import math
import os
import shutil
import subprocess
import sys
import time
import wave

import numpy as np
from PIL import Image


def _enable_windows_ansi():
    """Best-effort: turns on ANSI escape processing on Windows consoles that
    don't have it by default (older cmd.exe). Silently does nothing if it
    doesn't apply or fails — colour just stays off in that case."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:
        pass


def _color_enabled():
    if os.environ.get("NO_COLOR"):
        return False
    try:
        return sys.stdout.isatty()
    except Exception:
        return False


_enable_windows_ansi()
_COLOR = _color_enabled()


class C:
    """ANSI colour codes, or empty strings if colour is disabled (piped
    output, NO_COLOR set, or a terminal that doesn't support it)."""
    RESET = "\033[0m" if _COLOR else ""
    BOLD = "\033[1m" if _COLOR else ""
    DIM = "\033[2m" if _COLOR else ""
    RED = "\033[31m" if _COLOR else ""
    GREEN = "\033[32m" if _COLOR else ""
    YELLOW = "\033[33m" if _COLOR else ""
    BLUE = "\033[34m" if _COLOR else ""
    MAGENTA = "\033[35m" if _COLOR else ""
    CYAN = "\033[36m" if _COLOR else ""


def print_note(msg):
    print(f"{C.CYAN}Note: {msg}{C.RESET}", file=sys.stderr)


def print_warning(msg):
    print(f"{C.YELLOW}{C.BOLD}Warning: {msg}{C.RESET}", file=sys.stderr)


def print_error(msg):
    print(f"{C.RED}{C.BOLD}Error: {msg}{C.RESET}", file=sys.stderr)


def print_field(label, value):
    print(f"{C.BOLD}{C.GREEN}{label}:{C.RESET} {value}")


def get_sample_rate(audio_path):
    """Reads the input file's native sample rate. For .wav files this uses
    Python's built-in wave module directly — no external tool involved, so
    it can't be broken by a stray or misconfigured ffprobe on PATH. Other
    formats (mp3, flac, etc.) fall back to ffprobe."""
    if audio_path.lower().endswith(".wav"):
        try:
            with wave.open(audio_path, "rb") as wf:
                return wf.getframerate()
        except wave.Error:
            pass  # fall through to ffprobe for unusual/non-standard wav variants

    if shutil.which("ffprobe") is None:
        raise RuntimeError(
            "ffprobe not found on PATH (needed to read the sample rate of "
            "non-.wav files). Install ffmpeg, which includes ffprobe, and "
            "make sure it's on PATH."
        )

    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "stream=sample_rate", "-of", "default=nw=1:nk=1",
        audio_path,
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    rate = result.stdout.strip().splitlines()[0].strip() if result.stdout.strip() else ""
    if not rate:
        raise RuntimeError(
            f"Could not determine sample rate of {audio_path!r} via ffprobe. "
            f"ffprobe stderr: {result.stderr.strip()!r}"
        )
    return int(rate)


def decode_to_bytes(audio_path, sample_rate):
    """Uses ffmpeg to decode any audio file to raw 8-bit unsigned mono PCM
    bytes, at the given sample rate (the source's native rate, so nothing
    is resampled)."""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "ffmpeg not found on PATH. Install it (e.g. `apt install ffmpeg`, "
            "`brew install ffmpeg`) and try again."
        )

    cmd = [
        "ffmpeg", "-y", "-i", audio_path,
        "-f", "u8", "-acodec", "pcm_u8", "-ac", "1", "-ar", str(sample_rate),
        "pipe:1",
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if result.returncode != 0 or not result.stdout:
        raise RuntimeError(f"ffmpeg failed to decode {audio_path!r}")
    return result.stdout


def write_wav(data, sample_rate, out_path):
    with wave.open(out_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(1)
        wf.setframerate(sample_rate)
        wf.writeframes(data)


def wav_duration_seconds(wav_path):
    with wave.open(wav_path, "rb") as wf:
        return wf.getnframes() / float(wf.getframerate())


SILENCE_BYTE = 128  # zero-amplitude midpoint in 8-bit unsigned PCM


def byte_to_color(b, palette):
    if b == SILENCE_BYTE:
        return (0, 0, 0)
    if palette == "gray":
        return (b, b, b)
    if palette == "rainbow-bw":
        if b == 0:
            return (0, 0, 0)
        if b == 255:
            return (255, 255, 255)
        h = (b - 1) / 253.0
        r, g, bl = colorsys.hsv_to_rgb(h, 1.0, 1.0)
        return (int(r * 255), int(g * 255), int(bl * 255))
    h = b / 255.0
    r, g, bl = colorsys.hsv_to_rgb(h, 1.0, 1.0)
    return (int(r * 255), int(g * 255), int(bl * 255))


def compute_peak_amplitude(data):
    """Returns the largest deviation from SILENCE_BYTE (128) actually present
    in the data — i.e. how loud the loudest moment in the file really is, out
    of a possible 127 (full digital scale). Most real recordings never reach
    true 0/255, so this is almost always well under 127."""
    if not data:
        return 0
    arr = np.frombuffer(data, dtype=np.uint8).astype(np.int16)
    return int(np.abs(arr - SILENCE_BYTE).max())


def normalization_scale(peak_amplitude, target_peak=127):
    """Factor to stretch (byte - 128) by so the file's actual peak amplitude
    reaches target_peak (full scale). 1.0 (no change) if the file is silent
    or already at/above full scale."""
    if peak_amplitude <= 0 or peak_amplitude >= target_peak:
        return 1.0
    return target_peak / peak_amplitude


def palette_lut(palette, brightness_by_amplitude=False, amplitude_gamma=0.6, normalize_scale=1.0):
    """Precomputes a 256x3 lookup table (byte value -> RGB) for the given
    palette, so colouring a whole array of bytes is one numpy fancy-index
    lookup instead of 256 x N per-pixel Python calls.

    normalize_scale stretches each byte's distance from 128 (silence) by
    this factor before colouring — computed once per file from its actual
    peak amplitude via normalization_scale(), so a quiet recording that
    never reaches true digital full-scale still uses the full hue and
    brightness range instead of being squashed into a narrow band around
    128 (which reads as mostly one colour, e.g. cyan/blue in the rainbow
    palette). 1.0 = no change, colours reflect raw byte values directly.

    brightness_by_amplitude, when True, additionally scales each colour's
    brightness by how far the (normalized) byte sits from 128 — without
    this, hue changes with byte value but brightness stays maxed regardless
    of loudness, so a very quiet sample looks exactly as vivid as a
    full-scale peak. amplitude_gamma < 1 lifts quiet-but-audible samples
    above near-black so they stay visible rather than being crushed too
    quickly (0.6 is a reasonable perceptual default; 1.0 = linear, no lift)."""
    raw = np.arange(256, dtype=np.float64)
    normalized = np.clip(SILENCE_BYTE + (raw - SILENCE_BYTE) * normalize_scale, 0, 255)
    normalized_bytes = normalized.round().astype(np.uint8)

    lut = np.array([byte_to_color(int(b), palette) for b in normalized_bytes], dtype=np.float64)
    if brightness_by_amplitude:
        amplitude = np.abs(normalized - SILENCE_BYTE) / 128.0
        amplitude = np.clip(amplitude, 0.0, 1.0) ** amplitude_gamma
        lut = lut * amplitude[:, None]
    return lut.astype(np.uint8)


def build_full_image(data, width, pixel_size, palette, brightness_by_amplitude=False,
                     amplitude_gamma=0.6, normalize_scale=1.0):
    n = len(data)
    height = math.ceil(n / width)
    lut = palette_lut(palette, brightness_by_amplitude, amplitude_gamma, normalize_scale)

    grid = np.zeros(height * width, dtype=np.uint8)
    grid[:n] = np.frombuffer(data, dtype=np.uint8)
    grid = grid.reshape(height, width)

    rgb = lut[grid]
    if pixel_size > 1:
        rgb = rgb.repeat(pixel_size, axis=0).repeat(pixel_size, axis=1)
    return Image.fromarray(rgb, "RGB")


MAX_IMAGE_PIXELS = 50_000_000  # safety cap for the standalone PNG (~150MB as raw RGB)


def safe_pixel_size(n, width, requested_pixel_size, max_total_pixels=MAX_IMAGE_PIXELS):
    """Shrinks pixel_size if rendering the full byte-image at the requested
    size would need an unreasonable amount of memory (this scales with file
    size, so a long audio file at the default --pixel-size can otherwise
    demand tens of gigabytes). Returns requested_pixel_size unchanged if it's
    already within the cap."""
    height = max(1, math.ceil(n / width))
    total = (width * requested_pixel_size) * (height * requested_pixel_size)
    if total <= max_total_pixels:
        return requested_pixel_size
    scale = math.sqrt(max_total_pixels / total)
    return max(1, int(requested_pixel_size * scale))


def build_row_window(data, width, pixel_size, palette, row_start, row_count,
                     brightness_by_amplitude=False, amplitude_gamma=0.6, normalize_scale=1.0):
    """Renders only rows [row_start, row_start+row_count) of the byte grid,
    instead of materializing the entire (potentially huge) image. Rows
    beyond the available data are left black. This is what keeps video
    rendering's memory use (and, via numpy vectorization, render time)
    bounded by the viewport size rather than the total file size."""
    row_start = max(0, row_start)
    lut = palette_lut(palette, brightness_by_amplitude, amplitude_gamma, normalize_scale)

    grid = np.zeros(row_count * width, dtype=np.uint8)
    start_idx = row_start * width
    end_idx = min(len(data), start_idx + row_count * width)
    if start_idx < end_idx:
        chunk = np.frombuffer(data[start_idx:end_idx], dtype=np.uint8)
        grid[:len(chunk)] = chunk
    grid = grid.reshape(row_count, width)

    rgb = lut[grid]
    if pixel_size > 1:
        rgb = rgb.repeat(pixel_size, axis=0).repeat(pixel_size, axis=1)
    return Image.fromarray(rgb, "RGB")


ENCODER_CODECS = {
    "nvenc": {"h264": "h264_nvenc", "hevc": "hevc_nvenc"},                # NVIDIA
    "qsv": {"h264": "h264_qsv", "hevc": "hevc_qsv"},                      # Intel Quick Sync
    "amf": {"h264": "h264_amf", "hevc": "hevc_amf"},                      # AMD
    "videotoolbox": {"h264": "h264_videotoolbox", "hevc": "hevc_videotoolbox"},  # Apple Silicon / macOS
    "cpu": {"h264": "libx264", "hevc": "libx265"},
}


def list_ffmpeg_encoders():
    result = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    return result.stdout


def choose_encoder(preference="auto", codec_family="h264"):
    """Returns the ffmpeg video codec name to use, for the given codec_family
    ('h264' or 'hevc'). 'auto' picks the first available hardware encoder
    this ffmpeg build supports (in the order nvenc, qsv, amf, videotoolbox),
    falling back to the CPU encoder for that family (libx264/libx265) if
    none are found. A specific preference falls back to the CPU encoder
    with a warning if that hardware encoder isn't available in this ffmpeg
    build. Note: this only confirms the encoder is compiled into ffmpeg, not
    that matching hardware is actually present — see the runtime fallback
    in make_video."""
    cpu_codec = ENCODER_CODECS["cpu"][codec_family]

    if preference == "cpu":
        return cpu_codec

    available = list_ffmpeg_encoders()

    if preference == "auto":
        for key in ("nvenc", "qsv", "amf", "videotoolbox"):
            codec = ENCODER_CODECS[key][codec_family]
            if codec in available:
                return codec
        return cpu_codec

    codec = ENCODER_CODECS.get(preference, {}).get(codec_family)
    if codec and codec in available:
        return codec

    print_warning(f"encoder '{preference}' ({codec}) not found in this ffmpeg build; "
                  f"using {cpu_codec} (CPU) instead.")
    return cpu_codec


def test_encoder_runtime(codec, width, height):
    """Cheaply confirms a hardware encoder actually works at runtime (not
    just that ffmpeg was compiled with support for it) by encoding a single
    dummy frame to a null sink, before committing to the full render loop."""
    test_frame = bytes(3 * width * height)  # one black frame
    cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}", "-r", "1",
        "-i", "-",
        "-frames:v", "1", "-c:v", codec, "-pix_fmt", "yuv420p",
        "-f", "null", "-",
    ]
    result = subprocess.run(cmd, input=test_frame,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return result.returncode == 0


def format_hms(seconds):
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


def resolve_output_size(grid_w, grid_h, video_width, video_height):
    """Decides the final output resolution. With no override, output size
    equals the grid-derived size exactly. With one override given, the other
    dimension scales to preserve aspect ratio. With both given, uses them as
    an exact (stretched) target. Dimensions are rounded to even numbers,
    since libx264 with yuv420p requires it."""
    if video_width is None and video_height is None:
        out_w, out_h = grid_w, grid_h
    elif video_width is not None and video_height is not None:
        out_w, out_h = video_width, video_height
    elif video_width is not None:
        out_w = video_width
        out_h = round(grid_h * (video_width / grid_w))
    else:
        out_h = video_height
        out_w = round(grid_w * (video_height / grid_h))

    out_w += out_w % 2
    out_h += out_h % 2
    return out_w, out_h


def _kill_ffmpeg(proc):
    """Terminates an in-progress ffmpeg subprocess, escalating to kill if it
    doesn't exit promptly. Never raises — this runs during error/interrupt
    cleanup, where a second failure shouldn't mask the original one."""
    try:
        proc.stdin.close()
    except Exception:
        pass
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass


def _remove_partial(path):
    """Deletes a partially-written output file after an aborted/failed
    encode — an MP4 cut off mid-write has no valid moov atom and won't
    play, so leaving it behind is more confusing than removing it."""
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


SCALE_FILTERS = {
    "nearest": Image.NEAREST,   # hard block edges, no blending — best for this grid-of-solid-blocks content
    "lanczos": Image.LANCZOS,   # sharp, high quality for photographic content, but can ring/blur block edges
    "bicubic": Image.BICUBIC,   # smooth, softer than lanczos, also blends block edges
}


def make_video(data, width, pixel_size, palette, audio_path, out_path,
               fps=30, viewport_height=480, video_width=None, video_height=None,
               encoder="auto", codec_family="h264", scale_filter="nearest",
               brightness_by_amplitude=False, amplitude_gamma=0.6, normalize_scale=1.0):
    """Renders an MP4 that scrolls through the byte-image in sync with the
    audio's actual duration. Requires ffmpeg on PATH.

    video_width / video_height optionally set the final output resolution
    independently of --width/--pixel-size/--viewport-height, which otherwise
    only control the data grid layout. See resolve_output_size().

    encoder selects the video codec vendor: 'auto' (default) uses a GPU
    encoder if this ffmpeg build supports one, else CPU; or force one of
    'cpu'/'nvenc'/'qsv'/'amf'/'videotoolbox' explicitly.

    codec_family selects 'h264' (default, widely compatible, but hardware
    encoders cap out at 4096px on any one dimension) or 'hevc' (H.265; no
    such cap, needed for wider/taller output on GPU encoders).

    scale_filter controls the resampling used when video_width/video_height
    require resizing the rendered frame: 'nearest' (default) keeps byte
    blocks perfectly crisp with no blending — the right choice for this
    grid-of-solid-colour content; 'lanczos'/'bicubic' are smoother and more
    appropriate for photographic footage, but will blur/ring at the hard
    block edges this data produces.

    brightness_by_amplitude / amplitude_gamma / normalize_scale: see
    palette_lut()."""
    n = len(data)
    W = width * pixel_size
    total_rows = max(1, math.ceil(n / width))
    total_height = total_rows * pixel_size
    vp_h = min(viewport_height, total_height) if total_height > 0 else viewport_height
    # if the whole clip is shorter than the viewport, treat it as one padded
    # window rather than materializing a padded copy of the image
    total_height = max(total_height, vp_h)

    out_w, out_h = resolve_output_size(W, vp_h, video_width, video_height)
    needs_resize = (out_w, out_h) != (W, vp_h)

    if codec_family == "h264" and encoder != "cpu" and (out_w > 4096 or out_h > 4096):
        print_note(f"{out_w}x{out_h} exceeds the 4096px H.264 hardware-encoder limit; "
                   f"if a GPU encoder is selected it will likely fail the runtime check below "
                   f"and fall back to slower CPU encoding. Pass --codec hevc to encode on GPU "
                   f"at this size instead.")

    cpu_codec = ENCODER_CODECS["cpu"][codec_family]
    codec = choose_encoder(encoder, codec_family)
    if codec != cpu_codec and not test_encoder_runtime(codec, out_w, out_h):
        print_warning(f"'{codec}' is supported by this ffmpeg build but failed to actually "
                      f"run (no matching GPU/driver, or resolution exceeds its limits?); "
                      f"using {cpu_codec} (CPU) instead.")
        codec = cpu_codec
    print_field("Encoder", codec)

    duration = wav_duration_seconds(audio_path)
    total_frames = max(1, round(duration * fps))

    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{out_w}x{out_h}", "-r", str(fps),
        "-i", "-",
        "-i", audio_path,
        "-c:v", codec, "-pix_fmt", "yuv420p",
    ]
    if codec_family == "hevc":
        ffmpeg_cmd += ["-tag:v", "hvc1"]
    ffmpeg_cmd += [
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        out_path,
    ]
    proc = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    max_scroll = max(0, total_height - vp_h)
    # rows needed to cover one viewport, plus a small margin either side so
    # a fractional crop offset always has enough pixels above/below it
    rows_per_window = math.ceil(vp_h / pixel_size) + 4
    start_time = time.time()
    last_print = 0.0

    try:
        for frame_idx in range(total_frames):
            t = frame_idx / fps
            progress = min(1.0, t / duration) if duration > 0 else 0.0
            byte_index = progress * n
            row_progress = byte_index / width
            y_center = row_progress * pixel_size

            y0 = max(0, min(max_scroll, y_center - vp_h / 2))
            row_start = max(0, int(y0 // pixel_size) - 1)
            window_img = build_row_window(data, width, pixel_size, palette, row_start, rows_per_window,
                                           brightness_by_amplitude, amplitude_gamma, normalize_scale)
            local_y0 = y0 - row_start * pixel_size

            frame = window_img.crop((0, int(local_y0), W, int(local_y0) + vp_h))
            if needs_resize:
                frame = frame.resize((out_w, out_h), SCALE_FILTERS[scale_filter])

            proc.stdin.write(frame.tobytes())

            now = time.time()
            if now - last_print >= 0.1 or frame_idx == total_frames - 1:
                last_print = now
                elapsed = now - start_time
                frac = (frame_idx + 1) / total_frames
                render_fps = (frame_idx + 1) / elapsed if elapsed > 0 else 0.0
                remaining = (elapsed / frac - elapsed) if frac > 0 else 0.0
                sys.stdout.write(
                    f"\r{C.CYAN}rendering frame {frame_idx + 1}/{total_frames}{C.RESET} "
                    f"({C.BOLD}{frac * 100:5.1f}%{C.RESET})  "
                    f"elapsed={C.DIM}{format_hms(elapsed)}{C.RESET}  "
                    f"remaining={C.YELLOW}{format_hms(remaining)}{C.RESET}  "
                    f"fps={C.GREEN}{render_fps:5.1f}{C.RESET}"
                )
                sys.stdout.flush()
    except KeyboardInterrupt:
        sys.stdout.write("\n")
        print_warning("Aborted (Ctrl+C) — stopping ffmpeg and removing the incomplete output file...")
        _kill_ffmpeg(proc)
        _remove_partial(out_path)
        raise
    except BrokenPipeError:
        sys.stdout.write("\n")
        _kill_ffmpeg(proc)
        _remove_partial(out_path)
        raise RuntimeError(
            "ffmpeg exited unexpectedly while receiving frames. This usually means the requested "
            "encoder/resolution/codec combination is invalid on this system — try --encoder cpu."
        )

    sys.stdout.write("\n")
    proc.stdin.close()
    proc.wait()


def main():
    parser = argparse.ArgumentParser(description="Convert an audio file into a byte-map image/video.")
    parser.add_argument("input", help="Path to any audio file (wav, mp3, flac, etc.)")
    parser.add_argument("--palette", choices=["gray", "rainbow", "rainbow-bw"], default="rainbow",
                         help="Colour mapping for the image/video (default: rainbow)")
    parser.add_argument("--width", type=int, default=64, help="Bytes per row in the image (default: 64)")
    parser.add_argument("--pixel-size", type=int, default=64, help="Pixels per byte-square (default: 64)")
    parser.add_argument("--outdir", default=".", help="Output directory (default: current directory)")
    parser.add_argument("--save-bytes", metavar="PATH",
                         help="Also save the extracted raw bytes to this .bin file")
    parser.add_argument("--no-video", action="store_true", help="Skip MP4 generation (image only)")
    parser.add_argument("--no-image", action="store_true",
                         help="Skip standalone PNG generation. Useful for very large audio files where "
                              "you only want the video, which renders at full --pixel-size regardless "
                              "of file length (the PNG doesn't, without raising --max-image-pixels).")
    parser.add_argument("--max-image-pixels", type=int, default=MAX_IMAGE_PIXELS,
                         help=f"Safety cap (total pixels) for the standalone PNG before --pixel-size is "
                              f"automatically reduced (default: {MAX_IMAGE_PIXELS:,}, ~150MB as raw RGB). "
                              f"Raise this if your machine has the RAM for a full-resolution image of a "
                              f"large audio file; set very high (e.g. 999999999999) to effectively "
                              f"disable it.")
    parser.add_argument("--fps", type=int, default=30, help="Video frame rate (default: 30)")
    parser.add_argument("--viewport-height", type=int, default=480,
                         help="Height in pixels of the scrolling window in the data grid (default: 480)")
    parser.add_argument("--video-width", type=int, default=None,
                         help="Final output video width in pixels, overriding the grid-derived size "
                              "(e.g. --width/--pixel-size). If only one of --video-width/--video-height "
                              "is given, the other scales to preserve aspect ratio.")
    parser.add_argument("--video-height", type=int, default=None,
                         help="Final output video height in pixels, overriding --viewport-height. "
                              "See --video-width.")
    parser.add_argument("--encoder", choices=["auto", "cpu", "nvenc", "qsv", "amf", "videotoolbox"],
                         default="auto",
                         help="Video encoder: auto uses a GPU encoder if available (default), "
                              "cpu forces the CPU encoder, or force a specific vendor's hardware "
                              "encoder (nvenc=NVIDIA, qsv=Intel, amf=AMD, videotoolbox=Apple Silicon/macOS)")
    parser.add_argument("--codec", choices=["h264", "hevc"], default="h264",
                         help="Video codec family: h264 (default, most compatible, but hardware "
                              "encoders cap at 4096px on any dimension) or hevc/H.265 (no such cap, "
                              "needed for wider/taller GPU-encoded output)")
    parser.add_argument("--scale-filter", choices=["nearest", "lanczos", "bicubic"], default="nearest",
                         help="Resampling used when --video-width/--video-height require resizing: "
                              "nearest (default) keeps byte blocks perfectly crisp with no blending — "
                              "the right choice for this grid content; lanczos/bicubic are smoother and "
                              "suit photographic footage, but blur/ring at hard block edges here")
    parser.add_argument("--brightness-by-amplitude", action="store_true",
                         help="Scale each colour's brightness by how loud that sample is (distance from "
                              "128, the silence midpoint), instead of every non-silent byte rendering at "
                              "full brightness regardless of volume. Makes quiet passages visibly dim and "
                              "loud passages visibly bright, rather than only hue varying with byte value.")
    parser.add_argument("--amplitude-gamma", type=float, default=0.6,
                         help="Only with --brightness-by-amplitude. Gamma curve applied to the amplitude-"
                              "to-brightness mapping: 1.0 is linear (quiet sounds get crushed dark very "
                              "quickly); lower values (default 0.6) lift quiet-but-audible sounds so they "
                              "stay visible rather than reading as near-black.")
    parser.add_argument("--no-normalize", action="store_true",
                         help="Colour sensitivity is normalized to the file's actual peak amplitude by "
                              "default, so a recording that never reaches true digital full-scale (most "
                              "real audio) still uses the full hue/brightness range instead of being "
                              "squashed into a narrow band around silence (often reading as mostly one "
                              "colour, e.g. blue/cyan). Pass this flag to disable it and colour bytes by "
                              "their raw value directly.")
    args = parser.parse_args()

    base = os.path.splitext(os.path.basename(args.input))[0]
    os.makedirs(args.outdir, exist_ok=True)

    sample_rate = get_sample_rate(args.input)
    data = decode_to_bytes(args.input, sample_rate)

    print_field("Input", f"{args.input} ({len(data)} bytes decoded @ {sample_rate}Hz)")

    normalize_scale = 1.0
    if not args.no_normalize:
        peak = compute_peak_amplitude(data)
        normalize_scale = normalization_scale(peak)
        if normalize_scale != 1.0:
            print_note(f"colour sensitivity normalized: peak amplitude in this file is {peak}/127 "
                       f"of full digital scale — colours stretched {normalize_scale:.2f}x so the "
                       f"loudest moment reads as fully saturated/bright rather than the whole file "
                       f"sitting in a narrow band near one colour. Use --no-normalize to colour by "
                       f"raw byte values instead.")

    if not args.no_image:
        image_path = os.path.join(args.outdir, f"{base}_{args.palette}.png")
        image_pixel_size = safe_pixel_size(len(data), args.width, args.pixel_size, args.max_image_pixels)
        if image_pixel_size != args.pixel_size:
            print_note(f"reduced pixel-size from {args.pixel_size} to {image_pixel_size} for the "
                       f"saved PNG ({len(data)} bytes would otherwise need an enormous image); "
                       f"video rendering is unaffected and uses --pixel-size {args.pixel_size} directly. "
                       f"Raise --max-image-pixels (or pass --no-image to skip the PNG) if you have "
                       f"the RAM for the full resolution.")
        build_full_image(data, args.width, image_pixel_size, args.palette,
                          args.brightness_by_amplitude, args.amplitude_gamma,
                          normalize_scale).save(image_path)
        print_field("Image", image_path)

    if args.save_bytes:
        with open(args.save_bytes, "wb") as f:
            f.write(data)
        print_field("Bytes", args.save_bytes)

    if not args.no_video:
        # rebuild a clean WAV from the extracted bytes so the audio track and
        # the image are guaranteed to be built from the exact same byte data
        wav_path = os.path.join(args.outdir, f"{base}_audio.wav")
        write_wav(data, sample_rate, wav_path)

        video_path = os.path.join(args.outdir, f"{base}_{args.palette}.mp4")
        make_video(data, args.width, args.pixel_size, args.palette,
                   wav_path, video_path, fps=args.fps,
                   viewport_height=args.viewport_height,
                   video_width=args.video_width, video_height=args.video_height,
                   encoder=args.encoder, codec_family=args.codec,
                   scale_filter=args.scale_filter,
                   brightness_by_amplitude=args.brightness_by_amplitude,
                   amplitude_gamma=args.amplitude_gamma,
                   normalize_scale=normalize_scale)
        print_field("Video", video_path)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print_warning("Cancelled.")
        sys.exit(130)
    except (RuntimeError, FileNotFoundError, OSError) as e:
        print_error(str(e))
        sys.exit(1)
