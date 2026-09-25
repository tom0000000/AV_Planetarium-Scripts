#!/usr/bin/env python3
"""
compose.py — a plain-text pattern composer for sonify.py / unsonify.py.

Writes a small score file describing a sequence of colour blocks and/or
geometric patterns, and this turns it into a raw byte file (.bin) ready to
feed into sonify.py (--mode raw for the pattern as audio+image directly, or
--mode tone to hear it as notes). Think of it as notes_to_bin.py generalized
beyond MIDI pitches to arbitrary byte/colour values, plus 2D pattern
generators that are aware of the row width you'll render with.

Score commands (one per line; '#' starts a comment; blank lines ignored):

  WIDTH <n>
      Sets the row width (bytes per row) used by every pattern command
      below it, and by --preview. Required before any pattern command
      (SEQ doesn't need it). Should match the --width you'll pass to
      sonify.py so geometric patterns line up correctly.

  SEED <n>
      Seeds the RNG used by NOISE from this point on, for reproducible
      output. Optional — omit for a fresh random seed each run.

  SEQ <value>[:<ticks>] <value>[:<ticks>] ...
      Metronomic 1D sequence: each value is emitted for <ticks> bytes
      (default 1) before moving to the next — the same idea as
      notes_to_bin.py's NOTE:TICKS score format, but with arbitrary
      byte/colour values instead of MIDI notes. Under sonify.py --mode
      tone --ms-per-byte, each tick is one fixed time-slice, so this is a
      literal metronome. <value> is a byte 0-255, a colour name (see
      below), or REST/SILENCE.

  STRIPES <h|v> <thickness> <v1,v2,...> <rows>
      Alternating horizontal or vertical bands, <thickness> bytes/pixels
      wide, cycling through the given values, for <rows> rows of output.

  CHECKER <size> <v1,v2> <rows>
      Checkerboard of <size>x<size> cells alternating v1/v2, for <rows>
      rows.

  GRADIENT <h|v|radial> <start> <end> <rows>
      Smooth interpolation from <start> to <end>: left-to-right (h),
      top-to-bottom (v), or centre-to-edge (radial), for <rows> rows.

  RINGS <thickness> <v1,v2,...> <rows>
      Concentric rings from the centre, <thickness> pixels apart, cycling
      through the given values, for <rows> rows.

  DIAGONAL <fwd|back> <thickness> <v1,v2,...> <rows>
      Diagonal bands <thickness> pixels wide, cycling through values, for
      <rows> rows. fwd = "/" direction, back = "\" direction.

  NOISE <rows> [<low>-<high>]
      Random bytes, uniform over [low,high] (default 0-255), for <rows>
      rows. Seed with SEED for reproducible output.

  REPEAT <n>
      ...
  END
      Repeats the enclosed lines <n> times — for rhythmic loops, e.g. a
      4-block figure repeated 8 times.

  DEFINE <name>
      ...
  END
      Defines a reusable named block (a "motif") without emitting
      anything yet. Invoke it anywhere below with CALL <name>.

  CALL <name>
      Executes a previously DEFINEd block.

Values accept either a raw byte 0-255, or (except under --palette gray) a
colour name resolved to the byte that produces roughly that hue under the
composer's --palette: red, orange, yellow, chartreuse, green, spring,
cyan, azure, blue, violet, purple, magenta, pink — plus the neutrals
black, white, gray/grey, and the special names REST (255, sonify.py's
tone-mode rest marker) and SILENCE (128, the audio-silence/black-pixel
byte).

Usage:
  python3 compose.py score.txt pattern.bin
  python3 compose.py score.txt pattern.bin --preview pattern.png
  python3 sonify.py pattern.bin --width 64 --mode raw
"""

import argparse
import math
import os
import sys
import time

import numpy as np

REST_BYTE = 255      # matches sonify.py's tone-mode rest marker (note_map midi/scale)
SILENCE_BYTE = 128   # matches sonify.py/unsonify.py's audio-silence / black-pixel byte
CHUNK_BYTES_TARGET = 20_000_000  # row-chunk size cap for progress reporting, ~20MB/chunk


def _color_enabled():
    if os.environ.get("NO_COLOR"):
        return False
    try:
        return sys.stdout.isatty()
    except Exception:
        return False


_COLOR = _color_enabled()


class C:
    RESET = "\033[0m" if _COLOR else ""
    BOLD = "\033[1m" if _COLOR else ""
    DIM = "\033[2m" if _COLOR else ""
    RED = "\033[31m" if _COLOR else ""
    GREEN = "\033[32m" if _COLOR else ""
    YELLOW = "\033[33m" if _COLOR else ""
    CYAN = "\033[36m" if _COLOR else ""


def print_field(label, value):
    print(f"{C.BOLD}{C.GREEN}{label}:{C.RESET} {value}")


def print_note(msg):
    print(f"{C.CYAN}Note: {msg}{C.RESET}", file=sys.stderr)


def print_error(msg):
    print(f"{C.RED}{C.BOLD}Error: {msg}{C.RESET}", file=sys.stderr)


def format_hms(seconds):
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


def report_progress(ctx, force=False):
    """Prints a throttled, single-line progress update (elapsed/remaining/
    rate), the same style as unsonify.py's video-render progress line.
    No-op if the dry-run pass found no measurable work (ctx.total_bytes)."""
    if ctx.total_bytes <= 0:
        return
    now = time.time()
    if not force and now - ctx.last_print < 0.1:
        return
    ctx.last_print = now
    frac = min(1.0, ctx.bytes_done / ctx.total_bytes)
    elapsed = now - ctx.start_time
    rate = ctx.bytes_done / elapsed if elapsed > 0 else 0.0
    remaining = (elapsed / frac - elapsed) if frac > 0 else 0.0
    sys.stdout.write(
        f"\r{C.CYAN}composing{C.RESET} "
        f"({C.BOLD}{frac * 100:5.1f}%{C.RESET})  "
        f"elapsed={C.DIM}{format_hms(elapsed)}{C.RESET}  "
        f"remaining={C.YELLOW}{format_hms(remaining)}{C.RESET}  "
        f"rate={C.GREEN}{rate / 1e6:6.1f} MB/s{C.RESET}"
    )
    sys.stdout.flush()


class ScoreError(Exception):
    """Raised for anything wrong with the score itself (syntax, bad values,
    undefined macros, etc.) — reported to the user without a traceback."""


# ---- colour name resolution -------------------------------------------------

_HUE_NAMES = {  # name -> hue in [0,1), used for 'rainbow'/'rainbow-bw' palettes only
    "red": 0.0, "orange": 0.08, "yellow": 0.167, "chartreuse": 0.25,
    "green": 0.333, "spring": 0.417, "cyan": 0.5, "azure": 0.583,
    "blue": 0.667, "violet": 0.75, "purple": 0.75, "magenta": 0.833,
    "pink": 0.92,
}
# black/white/gray are NOT the same byte under every palette: 'gray' is a flat
# intensity ramp (0=black, 255=white genuinely); 'rainbow-bw' reserves exactly
# those two bytes as true black/white; but 'rainbow' never desaturates at all
# (always HSV saturation=value=1) so byte 0 and byte 255 are both fully-
# saturated red (hue wraps) -- neither is black or white. The only byte that
# renders black under 'rainbow' is 128, via the universal silence override in
# byte_to_color(), so that's what "black" resolves to there; "white"/"gray"
# have no equivalent under 'rainbow' and are refused rather than silently
# guessed.
_NEUTRAL_BY_PALETTE = {
    "gray": {"black": 0, "white": 255, "gray": 180, "grey": 180},
    "rainbow-bw": {"black": 0, "white": 255},
    "rainbow": {"black": SILENCE_BYTE},
}
_SPECIAL_NAMES = {"rest": REST_BYTE, "r": REST_BYTE, "silence": SILENCE_BYTE}


def resolve_value(token, palette):
    """Resolves one score token to a byte 0-255: a literal integer, the
    special names rest/silence, or a colour name mapped to the byte that
    produces roughly that colour under the given palette. Raises
    ValueError with a message meant to be shown to the user directly for
    anything unrecognized, out of range, or not representable under the
    chosen palette (e.g. 'white' under --palette rainbow, which never
    desaturates)."""
    key = token.strip().lower()
    if key in _SPECIAL_NAMES:
        return _SPECIAL_NAMES[key]

    try:
        v = int(token)
    except ValueError:
        v = None
    if v is not None:
        if not 0 <= v <= 255:
            raise ValueError(f"byte value {v} out of range 0-255 (token {token!r})")
        return v

    if key in ("black", "white", "gray", "grey"):
        table = _NEUTRAL_BY_PALETTE.get(palette, {})
        if key in table:
            return table[key]
        raise ValueError(
            f"colour name {token!r} isn't representable under --palette {palette} "
            f"({_neutral_hint(palette)}) — use a numeric byte, 'silence', or a different --palette")

    if key in _HUE_NAMES:
        if palette == "gray":
            raise ValueError(
                f"colour name {token!r} needs hue and isn't representable under --palette gray "
                f"(only black/white/gray/silence/rest are) — use a numeric byte or a different --palette")
        hue = _HUE_NAMES[key]
        if palette == "rainbow-bw":
            b = max(1, min(254, round(hue * 253) + 1))
        else:  # rainbow
            b = round(hue * 255)
        if b == SILENCE_BYTE:
            b += 1  # avoid the silence/black override that always renders byte 128 as pure black
        return b

    known = ", ".join(sorted(set(_HUE_NAMES) | {"black", "white", "gray", "grey"} | set(_SPECIAL_NAMES)))
    raise ValueError(f"unrecognized value {token!r} — expected a byte 0-255 or a colour name ({known})")


def _neutral_hint(palette):
    if palette == "rainbow":
        return "rainbow is always fully saturated — only 'black' is available, via the silence byte"
    if palette == "rainbow-bw":
        return "rainbow-bw only reserves 'black' (0) and 'white' (255); everything else is a hue"
    return "unknown palette"


def parse_value_ticks(tok, palette):
    if ":" in tok:
        val_tok, ticks_tok = tok.split(":", 1)
        try:
            ticks = int(ticks_tok)
        except ValueError:
            raise ValueError(f"tick count must be an integer: {tok!r}")
    else:
        val_tok, ticks = tok, 1
    if ticks < 1:
        raise ValueError(f"tick count must be >= 1: {tok!r}")
    return resolve_value(val_tok, palette), ticks


# ---- geometric pattern generators -------------------------------------------
#
# Each takes row_offset/chunk_rows (the [row_offset, row_offset+chunk_rows)
# slice to generate right now) rather than always generating from row 0, so
# emit_chunked() below can generate a large pattern in bounded-size pieces
# for live progress reporting -- the same windowed-rendering idea as
# unsonify.py's build_row_window(), applied here for the same reason: a
# single huge NOISE/GRADIENT/etc. shouldn't block silently until entirely
# done. Patterns centred/interpolated over the whole grid (GRADIENT v/radial,
# RINGS) additionally take total_rows, since their centre or interpolation
# range depends on the *full* extent, not just the current chunk.
# All return a (chunk_rows, width) uint8 array.

def gen_stripes(width, row_offset, chunk_rows, orientation, thickness, values):
    values = np.array(values, dtype=np.uint8)
    if orientation in ("h", "horizontal"):
        rows_idx = np.arange(row_offset, row_offset + chunk_rows)
        row_vals = values[(rows_idx // thickness) % len(values)]
        return np.repeat(row_vals[:, None], width, axis=1)
    if orientation in ("v", "vertical"):
        col_vals = values[(np.arange(width) // thickness) % len(values)]
        return np.tile(col_vals[None, :], (chunk_rows, 1))
    raise ValueError(f"STRIPES orientation must be h/horizontal or v/vertical, got {orientation!r}")


def gen_checker(width, row_offset, chunk_rows, size, v1, v2):
    rows_idx = np.arange(row_offset, row_offset + chunk_rows)
    row_band = (rows_idx // size) % 2
    col_band = (np.arange(width) // size) % 2
    cell = (row_band[:, None] + col_band[None, :]) % 2
    return np.where(cell == 0, v1, v2).astype(np.uint8)


def gen_gradient(width, row_offset, chunk_rows, total_rows, orientation, start, end):
    if orientation == "h":
        row = np.linspace(start, end, width)
        grid = np.tile(row, (chunk_rows, 1))
    elif orientation == "v":
        full_col = np.linspace(start, end, total_rows)
        col = full_col[row_offset:row_offset + chunk_rows]
        grid = np.tile(col[:, None], (1, width))
    elif orientation == "radial":
        cy, cx = (total_rows - 1) / 2.0, (width - 1) / 2.0
        yy, xx = np.mgrid[row_offset:row_offset + chunk_rows, 0:width]
        dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
        max_dist = math.hypot(cx, cy) or 1.0
        norm = np.clip(dist / max_dist, 0, 1)
        grid = start + (end - start) * norm
    else:
        raise ValueError(f"GRADIENT orientation must be h, v, or radial, got {orientation!r}")
    return np.clip(np.round(grid), 0, 255).astype(np.uint8)


def gen_rings(width, row_offset, chunk_rows, total_rows, thickness, values):
    values = np.array(values, dtype=np.uint8)
    cy, cx = (total_rows - 1) / 2.0, (width - 1) / 2.0
    yy, xx = np.mgrid[row_offset:row_offset + chunk_rows, 0:width]
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    ring_idx = (dist // thickness).astype(int)
    return values[ring_idx % len(values)]


def gen_diagonal(width, row_offset, chunk_rows, thickness, values, direction):
    values = np.array(values, dtype=np.uint8)
    yy, xx = np.mgrid[row_offset:row_offset + chunk_rows, 0:width]
    diag = (xx + yy) if direction == "back" else (xx - yy)
    band_idx = (diag // thickness).astype(int)
    return values[band_idx % len(values)]


def gen_noise(width, chunk_rows, low, high, rng):
    return rng.integers(low, high + 1, size=(chunk_rows, width), dtype=np.int64).astype(np.uint8)


def chunk_size_rows(width, total_rows):
    rows_per_chunk = max(1, CHUNK_BYTES_TARGET // max(1, width))
    return min(total_rows, rows_per_chunk)


def emit_chunked(ctx, total_rows, make_chunk):
    """Generates total_rows rows in bounded-size pieces via make_chunk(row_offset,
    chunk_rows), appending each to ctx.output and reporting progress after
    each -- rather than materializing and appending the whole pattern in one
    shot, which would make the progress bar jump straight from 0% to 100%
    for one big command."""
    row_offset = 0
    step = chunk_size_rows(ctx.width, total_rows)
    while row_offset < total_rows:
        chunk_rows = min(step, total_rows - row_offset)
        grid = make_chunk(row_offset, chunk_rows)
        ctx.output.extend(grid.tobytes())
        ctx.bytes_done += chunk_rows * ctx.width
        report_progress(ctx)
        row_offset += chunk_rows


# ---- score parsing (line-based, REPEAT/DEFINE...END blocks, '#' comments) --

def tokenize_lines(text):
    lines = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        content = raw.split("#", 1)[0].strip()
        if content:
            lines.append((lineno, content))
    return lines


def parse_block(lines, i, top=False, open_lineno=None, open_kind=None):
    stmts = []
    while i < len(lines):
        lineno, content = lines[i]
        cmd = content.split(None, 1)[0].upper()
        if cmd == "END":
            if top:
                raise ScoreError(f"line {lineno}: unexpected END with no matching REPEAT/DEFINE")
            return stmts, i + 1
        if cmd in ("REPEAT", "DEFINE"):
            parts = content.split(None, 1)
            arg = parts[1].strip() if len(parts) > 1 else ""
            body, i = parse_block(lines, i + 1, top=False, open_lineno=lineno, open_kind=cmd)
            stmts.append((cmd, lineno, arg, body))
            continue
        stmts.append(("STMT", lineno, content))
        i += 1
    if not top:
        raise ScoreError(f"line {open_lineno}: {open_kind} has no matching END")
    return stmts, i


class Context:
    def __init__(self, palette, dry_run=False):
        self.width = None
        self.palette = palette
        self.output = bytearray()
        self.macros = {}
        self.call_stack = []
        self.rng = np.random.default_rng()
        # dry_run walks the score identically (so WIDTH/REPEAT/DEFINE/CALL
        # behave exactly as the real pass will) but skips numpy grid
        # generation, just tallying total_bytes -- this gives the real pass
        # an accurate denominator for percent-complete before doing any of
        # the actual (potentially slow) work.
        self.dry_run = dry_run
        self.total_bytes = 0
        self.bytes_done = 0
        self.start_time = None
        self.last_print = 0.0


def require_width(ctx, lineno, cmd):
    if ctx.width is None:
        raise ScoreError(f"line {lineno}: {cmd} needs WIDTH set first (add a 'WIDTH <n>' line above it)")


def run_statement(lineno, content, ctx):
    parts = content.split()
    cmd = parts[0].upper()
    args = parts[1:]

    if cmd == "WIDTH":
        n = int(args[0])
        if n < 1:
            raise ValueError("WIDTH must be >= 1")
        ctx.width = n

    elif cmd == "SEED":
        ctx.rng = np.random.default_rng(int(args[0]))

    elif cmd == "CALL":
        name = args[0] if args else None
        if not name or name not in ctx.macros:
            raise ScoreError(f"line {lineno}: CALL to undefined macro {name!r} "
                              f"(use 'DEFINE {name or '<name>'} ... END' first)")
        if name in ctx.call_stack:
            raise ScoreError(f"line {lineno}: CALL {name!r} is recursive "
                              f"(call stack: {' -> '.join(ctx.call_stack + [name])})")
        ctx.call_stack.append(name)
        execute(ctx.macros[name], ctx)
        ctx.call_stack.pop()

    elif cmd == "SEQ":
        if not args:
            raise ValueError("SEQ needs at least one value")
        resolved = [parse_value_ticks(tok, ctx.palette) for tok in args]
        total_ticks = sum(ticks for _, ticks in resolved)
        if ctx.dry_run:
            ctx.total_bytes += total_ticks
            return
        for val, ticks in resolved:
            ctx.output.extend(bytes([val]) * ticks)
        ctx.bytes_done += total_ticks
        report_progress(ctx)

    elif cmd == "STRIPES":
        require_width(ctx, lineno, "STRIPES")
        orientation, thickness, value_list, rows = args[0].lower(), int(args[1]), args[2], int(args[3])
        values = [resolve_value(v, ctx.palette) for v in value_list.split(",")]
        if ctx.dry_run:
            ctx.total_bytes += rows * ctx.width
            return
        emit_chunked(ctx, rows, lambda r0, rc: gen_stripes(ctx.width, r0, rc, orientation, thickness, values))

    elif cmd == "CHECKER":
        require_width(ctx, lineno, "CHECKER")
        size, value_list, rows = int(args[0]), args[1], int(args[2])
        vals = value_list.split(",")
        if len(vals) != 2:
            raise ValueError(f"CHECKER needs exactly 2 comma-separated values, got {value_list!r}")
        v1, v2 = (resolve_value(v, ctx.palette) for v in vals)
        if ctx.dry_run:
            ctx.total_bytes += rows * ctx.width
            return
        emit_chunked(ctx, rows, lambda r0, rc: gen_checker(ctx.width, r0, rc, size, v1, v2))

    elif cmd == "GRADIENT":
        require_width(ctx, lineno, "GRADIENT")
        orientation = args[0].lower()
        start, end, rows = resolve_value(args[1], ctx.palette), resolve_value(args[2], ctx.palette), int(args[3])
        if ctx.dry_run:
            ctx.total_bytes += rows * ctx.width
            return
        emit_chunked(ctx, rows, lambda r0, rc: gen_gradient(ctx.width, r0, rc, rows, orientation, start, end))

    elif cmd == "RINGS":
        require_width(ctx, lineno, "RINGS")
        thickness, value_list, rows = int(args[0]), args[1], int(args[2])
        values = [resolve_value(v, ctx.palette) for v in value_list.split(",")]
        if ctx.dry_run:
            ctx.total_bytes += rows * ctx.width
            return
        emit_chunked(ctx, rows, lambda r0, rc: gen_rings(ctx.width, r0, rc, rows, thickness, values))

    elif cmd == "DIAGONAL":
        require_width(ctx, lineno, "DIAGONAL")
        direction, thickness, value_list, rows = args[0].lower(), int(args[1]), args[2], int(args[3])
        if direction not in ("fwd", "back"):
            raise ValueError(f"DIAGONAL direction must be fwd or back, got {args[0]!r}")
        values = [resolve_value(v, ctx.palette) for v in value_list.split(",")]
        if ctx.dry_run:
            ctx.total_bytes += rows * ctx.width
            return
        emit_chunked(ctx, rows, lambda r0, rc: gen_diagonal(ctx.width, r0, rc, thickness, values, direction))

    elif cmd == "NOISE":
        require_width(ctx, lineno, "NOISE")
        rows = int(args[0])
        low, high = 0, 255
        if len(args) > 1:
            low_tok, high_tok = args[1].split("-", 1)
            low, high = int(low_tok), int(high_tok)
            if not (0 <= low <= high <= 255):
                raise ValueError(f"NOISE range must satisfy 0 <= low <= high <= 255, got {args[1]!r}")
        if ctx.dry_run:
            ctx.total_bytes += rows * ctx.width
            return
        emit_chunked(ctx, rows, lambda r0, rc: gen_noise(ctx.width, rc, low, high, ctx.rng))

    else:
        raise ScoreError(f"line {lineno}: unknown command {cmd!r}")


def execute(stmts, ctx):
    for node in stmts:
        kind = node[0]
        if kind == "REPEAT":
            _, lineno, arg, body = node
            try:
                count = int(arg)
            except ValueError:
                raise ScoreError(f"line {lineno}: REPEAT needs an integer count, got {arg!r}")
            if count < 0:
                raise ScoreError(f"line {lineno}: REPEAT count must be >= 0")
            for _ in range(count):
                execute(body, ctx)
        elif kind == "DEFINE":
            _, lineno, arg, body = node
            name = arg.strip()
            if not name:
                raise ScoreError(f"line {lineno}: DEFINE requires a macro name")
            ctx.macros[name] = body
        elif kind == "STMT":
            _, lineno, content = node
            try:
                run_statement(lineno, content, ctx)
            except ScoreError:
                raise
            except (ValueError, IndexError, ZeroDivisionError) as e:
                raise ScoreError(f"line {lineno}: {e}") from e
        else:
            raise ScoreError(f"internal error: unknown node kind {kind!r}")


def main():
    parser = argparse.ArgumentParser(
        description="Compose a byte pattern for sonify.py/unsonify.py from a plain-text score.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    parser.add_argument("score", help="Path to the score file")
    parser.add_argument("output", help="Path to write the composed raw bytes (.bin)")
    parser.add_argument("--palette", choices=["gray", "rainbow", "rainbow-bw"], default="rainbow",
                         help="Palette used to resolve named colours, and for --preview "
                              "(default: rainbow, matches sonify.py's default)")
    parser.add_argument("--preview", metavar="PATH",
                         help="Also render a PNG preview of the composed pattern, using sonify.py's own "
                              "palette/image logic so it matches exactly what sonify.py would produce")
    parser.add_argument("--preview-pixel-size", type=int, default=8,
                         help="Pixel size for --preview (default: 8)")
    parser.add_argument("--preview-width", type=int, default=64,
                         help="Row width for --preview if the score never sets WIDTH (default: 64)")
    args = parser.parse_args()

    try:
        with open(args.score, "r") as f:
            text = f.read()
    except OSError as e:
        print_error(f"couldn't read score file: {e}")
        sys.exit(1)

    lines = tokenize_lines(text)
    ctx = Context(args.palette)
    try:
        stmts, _ = parse_block(lines, 0, top=True)

        # dry run: walks the score identically to size the progress bar
        # (ctx.total_bytes) before doing any of the actual generation work
        dry_ctx = Context(args.palette, dry_run=True)
        execute(stmts, dry_ctx)

        ctx.total_bytes = dry_ctx.total_bytes
        ctx.start_time = time.time()
        execute(stmts, ctx)
        if ctx.total_bytes > 0:
            report_progress(ctx, force=True)
            sys.stdout.write("\n")
    except ScoreError as e:
        print_error(str(e))
        sys.exit(1)

    data = bytes(ctx.output)
    with open(args.output, "wb") as f:
        f.write(data)
    print_field("Output", f"{args.output} ({len(data)} bytes)")

    if ctx.width:
        rows = math.ceil(len(data) / ctx.width) if data else 0
        print_field("Grid", f"{ctx.width} wide x {rows} rows")
        print_note(f"to render, match --width: python3 sonify.py {args.output} --width {ctx.width} --mode raw")
    else:
        print_note("score never set WIDTH — this is a flat 1D sequence with no fixed row layout")

    if args.preview:
        try:
            import sonify
        except ImportError as e:
            print_error(f"--preview needs sonify.py importable from the same directory as compose.py: {e}")
            sys.exit(1)
        preview_width = ctx.width or args.preview_width
        sonify.make_image(data, preview_width, args.preview_pixel_size, args.palette, args.preview)
        print_field("Preview", args.preview)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print_note("Cancelled.")
        sys.exit(130)
