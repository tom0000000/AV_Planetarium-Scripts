# sonify / unsonify

Turn any file's raw bytes into sound and colour, and back again.

- **`sonify.py`** — reads any file's bytes → audio (WAV), a colour byte-map
  image (PNG), and a scrolling video synced to the audio (MP4).
- **`unsonify.py`** — reads any audio file → decodes it back to raw bytes,
  producing the same colour byte-map (PNG), a scrolling video (MP4), and
  optionally the raw bytes themselves (BIN).
- **`notes_to_bin.py`** — companion tool: write a plain-text musical score,
  get back a raw byte file you can feed into `sonify.py --mode tone` to
  compose an actual melody rather than relying on incidental data.

Full documentation, every flag, every function, and the concepts behind the
colour/audio mappings: see **[MANUAL.md](MANUAL.md)**.

## Quick start

```bash
pip install -r requirements.txt
# ffmpeg must also be on PATH: https://ffmpeg.org/download.html

python3 sonify.py somefile.bin
python3 unsonify.py somefile_raw.wav
```

## Requirements

- Python 3
- [ffmpeg](https://ffmpeg.org/) on PATH (video output, and non-WAV decoding
  in `unsonify.py`)
- Python packages in `requirements.txt` (Pillow, numpy)

## Highlights

- **GPU-accelerated video encoding** (NVIDIA/Intel/AMD/Apple Silicon) with
  automatic detection and CPU fallback
- **HEVC support** for output wider/taller than H.264's 4096px hardware
  encoder limit
- **Memory-safe** at any file size — video rendering uses bounded-memory
  windowed rendering; the standalone PNG auto-scales down rather than
  attempting a multi-gigabyte allocation
- **Musical composition mode** — map bytes to actual MIDI notes/scales
  instead of a raw frequency sweep
- **Auto-normalized colour sensitivity** — `unsonify.py` stretches colour
  mapping to the audio file's actual peak amplitude by default, so quiet
  recordings still use the full colour range instead of clustering around
  one hue
- Clean Ctrl+C handling — aborts kill ffmpeg and remove incomplete output
  rather than leaving a corrupt file behind

See [MANUAL.md](MANUAL.md) for the full flag reference and the reasoning
behind each design choice, and [CHANGELOG.md](CHANGELOG.md) for how this
came together.

## License

MIT — see [LICENSE](LICENSE).
