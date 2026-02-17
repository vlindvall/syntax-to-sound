# syntax-to-sound

Vibe coding for music with Python + Renardo.

## What this repo is

A playground for composing and experimenting with generative music ideas in code.

## Stack

- Python 3.11+
- Renardo
- SuperCollider (audio engine used by Renardo)

## Quick start

```bash
make venv
make install
```

## Start Renardo

```bash
make renardo
```

Deterministic startup (recommended on this machine):

```bash
make renardo-boot
```

This command:
- ensures SC extension files exist
- reapplies local compatibility patches
- clears stale `renardo` / `sclang` / `scsynth` processes
- boots `renardo -p -b` ready for song loading

Auto-boot and auto-load a specific song:

```bash
make play SONG=songs/2026-02-17_boten_anna_handsup.py
```

`SONG` also accepts:
- a bare song file in `songs/`, e.g. `SONG=2026-02-17_switch_angel_trance.py`
- a name without extension, e.g. `SONG=2026-02-17_switch_angel_trance`

Live coding mode with auto-reload on file save:

```bash
make live SONG=songs/2026-02-17_boten_anna_handsup.py
```

In live mode, the song file is re-executed automatically when it changes, so I can edit the file from chat and you hear updates immediately.

If `renardo` is not on your PATH, use:

```bash
source .venv/bin/activate
python -m renardo
```

## Create a new song sketch

```bash
make new-song NAME="Neon Rain"
```

This generates a file in `songs/` from `songs/_template.py` with a date-prefixed name, for example:

`songs/2026-02-17_neon_rain.py`

Then open that file and start composing by adding player lines (`p1`, `p2`, etc.).
