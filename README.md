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
