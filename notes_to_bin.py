#!/usr/bin/env python3
"""
notes_to_bin.py — write a plain-text melody as a raw byte file for sonify.py.

Score format: whitespace-separated tokens, each one of:
  NOTE            e.g. C4, F#3, Bb5   (scientific pitch notation, C4 = middle C)
  NOTE:TICKS      e.g. C4:4           (holds the note for 4 ticks instead of 1)
  R  or  R:TICKS  a rest (silence) for that many ticks

One "tick" = one byte = one fixed time-slice in sonify.py's tone mode,
controlled there by --ms-per-byte (e.g. --ms-per-byte 125 = 125ms/tick).
A held note is just the same byte repeated for TICKS ticks, so note length
is entirely about how many ticks you give it.

Example score (twinkle-twinkle opening, quarter note = 2 ticks):
  C4:2 C4:2 G4:2 G4:2 A4:2 A4:2 G4:4 R:1

Usage:
  python3 notes_to_bin.py score.txt melody.bin
  python3 sonify.py melody.bin --mode tone --note-map midi --ms-per-byte 125 --no-video
"""

import sys

PITCH_CLASS = {
    "C": 0, "C#": 1, "DB": 1, "D": 2, "D#": 3, "EB": 3, "E": 4, "F": 5,
    "F#": 6, "GB": 6, "G": 7, "G#": 8, "AB": 8, "A": 9, "A#": 10, "BB": 10, "B": 11,
}

REST_BYTE = 255


def note_name_to_midi(name):
    name = name.strip()
    # split into letter+accidental vs octave digits (handles negative octaves like C-1)
    i = 1
    if len(name) > 1 and name[1] in "#bB" and name[1] != "-":
        i = 2
    pitch_key = name[:i].upper()
    octave_str = name[i:]
    if pitch_key not in PITCH_CLASS:
        raise ValueError(f"Unrecognized note name: {name!r}")
    octave = int(octave_str)
    midi = (octave + 1) * 12 + PITCH_CLASS[pitch_key]
    if not (0 <= midi <= 127):
        raise ValueError(f"Note {name!r} (MIDI {midi}) is out of the 0-127 range")
    return midi


def parse_score(text):
    out = bytearray()
    for token in text.split():
        if ":" in token:
            note_part, ticks_part = token.split(":", 1)
            ticks = int(ticks_part)
        else:
            note_part, ticks = token, 1

        if note_part.upper() == "R":
            byte_val = REST_BYTE
        else:
            byte_val = note_name_to_midi(note_part)

        out.extend([byte_val] * ticks)
    return bytes(out)


def main():
    if len(sys.argv) != 3:
        print("Usage: python3 notes_to_bin.py score.txt output.bin")
        sys.exit(1)

    with open(sys.argv[1], "r") as f:
        text = f.read()

    data = parse_score(text)

    with open(sys.argv[2], "wb") as f:
        f.write(data)

    print(f"Wrote {len(data)} bytes ({len(data)} ticks) to {sys.argv[2]}")


if __name__ == "__main__":
    main()
