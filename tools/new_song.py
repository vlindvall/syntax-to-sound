#!/usr/bin/env python3
"""Generate a new Renardo song file from a local template."""

from __future__ import annotations

import argparse
import datetime as dt
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SONGS_DIR = ROOT / "songs"
TEMPLATE_PATH = SONGS_DIR / "_template.py"


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", name.strip().lower()).strip("_")
    if not slug:
        raise ValueError("Song name cannot be empty after normalization.")
    return slug


def create_song_file(song_name: str) -> Path:
    if not TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Missing template file: {TEMPLATE_PATH}")

    slug = slugify(song_name)
    filename = f"{dt.date.today().isoformat()}_{slug}.py"
    destination = SONGS_DIR / filename

    if destination.exists():
        raise FileExistsError(f"Song already exists: {destination}")

    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    content = template.format(
        song_title=song_name.strip(),
        created_at=dt.datetime.now().isoformat(timespec="seconds"),
    )
    destination.write_text(content, encoding="utf-8")
    return destination


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a new Renardo song file under songs/."
    )
    parser.add_argument("name", help="Song name, e.g. 'Neon Rain'")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    new_file = create_song_file(args.name)
    print(f"Created {new_file.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
