#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ -z "${SONG:-}" ]; then
  echo "Usage: SONG=songs/your_song.py bash tools/live_play.sh"
  exit 1
fi

if [ ! -f ".venv/bin/activate" ]; then
  python3 -m venv .venv
fi

. .venv/bin/activate
export PATH="/Applications/SuperCollider.app/Contents/MacOS:$PATH"

if ! command -v renardo >/dev/null 2>&1; then
  pip install -U pip
  pip install renardo
fi

# Ensure SC integration files exist and local compatibility patches are applied.
renardo -c -N >/dev/null
python tools/prepare_renardo.py

# Clear stale processes from previous runs.
pkill -f 'renardo|sclang|scsynth|python.*renardo' >/dev/null 2>&1 || true

SONG_INFO_RAW="$(python - "$SONG" <<'PY'
import sys
from pathlib import Path

song_arg = sys.argv[1].strip()
root = Path.cwd()
p = Path(song_arg)

candidates = []
if p.is_absolute():
    candidates.append(p)
else:
    candidates.extend([root / p, root / "songs" / p])
    if p.suffix == "":
        candidates.extend([root / f"{song_arg}.py", root / "songs" / f"{song_arg}.py"])

chosen = None
for c in candidates:
    if c.exists() and c.is_file():
        chosen = c.resolve()
        break

if chosen is None:
    print(f"Song not found: {song_arg}", file=sys.stderr)
    print("Tried:", file=sys.stderr)
    for c in candidates:
        print(f"  - {c}", file=sys.stderr)
    raise SystemExit(2)

try:
    rel = chosen.relative_to(root)
    target = rel.as_posix()
except ValueError:
    target = chosen.as_posix()

print(chosen.as_posix())
print(f"exec(open({target!r}).read())")
PY
)"

SONG_PATH="$(printf '%s\n' "$SONG_INFO_RAW" | sed -n '1p')"
LOAD_CMD="$(printf '%s\n' "$SONG_INFO_RAW" | sed -n '2p')"

FIFO_PATH="/tmp/renardo-live-${USER}-$$.fifo"
mkfifo "$FIFO_PATH"

cleanup() {
  kill "${WATCHER_PID:-}" >/dev/null 2>&1 || true
  rm -f "$FIFO_PATH"
}
trap cleanup EXIT INT TERM

# Auto-reload song file on save.
(
  last_mtime=""
  while true; do
    mtime="$(stat -f %m "$SONG_PATH" 2>/dev/null || echo 0)"
    if [ "$mtime" != "$last_mtime" ]; then
      printf '%s\n\n' "$LOAD_CMD" > "$FIFO_PATH"
      last_mtime="$mtime"
    fi
    sleep 1
  done
) &
WATCHER_PID=$!

echo "Live mode started for: $SONG_PATH"
echo "Auto-reload: ON (polling every 1s)"
echo "Edit the song file; playback will reload automatically."

{ cat "$FIFO_PATH" -; } | renardo -p -b
