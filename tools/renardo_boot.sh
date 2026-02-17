#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

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

if [ -n "${SONG:-}" ]; then
  auto_cmd="$(python - "$SONG" <<'PY'
import sys
from pathlib import Path

song_arg = sys.argv[1].strip()
root = Path.cwd()
p = Path(song_arg)

candidates = []
if p.is_absolute():
    candidates.append(p)
else:
    candidates.extend([
        root / p,
        root / "songs" / p,
    ])
    if p.suffix == "":
        candidates.extend([
            root / f"{song_arg}.py",
            root / "songs" / f"{song_arg}.py",
        ])

chosen = None
for c in candidates:
    if c.exists() and c.is_file():
        chosen = c
        break

if chosen is None:
    print(f"Song not found: {song_arg}", file=sys.stderr)
    print("Tried:", file=sys.stderr)
    for c in candidates:
        print(f"  - {c}", file=sys.stderr)
    raise SystemExit(2)

try:
    target = str(chosen.relative_to(root))
except ValueError:
    target = str(chosen)

print(f"exec(open({target!r}).read())")
PY
)"
  echo "Auto-loading song: $SONG"
  { printf '%s\n\n' "$auto_cmd"; cat; } | renardo -p -b
  exit $?
fi

exec renardo -p -b
