# Renardo Playback Runbook (macOS)

This is the exact sequence that worked on this machine to get Renardo + SuperCollider live playback running.
Assumption: you are already in the repo root.

## 1) Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -U pip
pip install renardo
brew install --cask supercollider
```

## 2) Ensure SuperCollider binary is reachable

Renardo expects `sclang` on `PATH`:

```bash
export PATH="/Applications/SuperCollider.app/Contents/MacOS:$PATH"
```

## 3) Create Renardo SC extension files

```bash
. .venv/bin/activate
renardo -c -N
```

## 4) Download the default Renardo sample pack

Without this, playback crashes with missing `_loop_` samples.

```bash
. .venv/bin/activate
python - <<'PY'
from renardo_gatherer.collections import ensure_renardo_samples_directory, download_default_sample_pack

class Logger:
    def write_line(self, msg):
        print(msg)

ensure_renardo_samples_directory()
download_default_sample_pack(logger=Logger())
PY
```

## 5) Compatibility patches (required here)

### Patch A: use headless sclang interface (`emacs`) instead of `scqt`

Edit (resolve path dynamically):
```bash
python - <<'PY'
import inspect, renardo.supercollider_mgt.sclang_instances_mgt as m
print(inspect.getsourcefile(m))
PY
```

Change:
```python
self.sclang_exec = ["sclang", '-i', 'scqt']
```
To:
```python
self.sclang_exec = ["sclang", '-i', 'emacs']
```

Reason: `scqt` failed on this machine with `Incompatible processor ... neon`.

### Patch B: boot loop wait condition

Edit (resolve path dynamically):
```bash
python - <<'PY'
import inspect, renardo.RenardoApp as m
print(inspect.getsourcefile(m))
PY
```

Renardo waits for `"Welcome to"`, but this `sclang` build does not emit that line. Accept `"Class tree inited"` too and keep a timeout.

## 6) Start live Renardo pipe session

```bash
export PATH="/Applications/SuperCollider.app/Contents/MacOS:$PATH"
. .venv/bin/activate
renardo -p -b
```

## 7) Load and play a song in the live session

At the Renardo stdin prompt, run:

```python
exec(open('songs/2026-02-17_switch_angel_trance.py').read())
```

Stop playback:

```python
Clock.clear()
```

## 8) Known musical compatibility note

`Scale.gMinor` failed in this Renardo build. Equivalent working config:

```python
Scale.default = Scale.minor
Root.default = "G"
```

## 9) Live mix tweak example (works while running)

```python
p1.amp = P[0.18,0.72,0.78,0.85]
p1.lpf = 3200
p1.mix = 0.26
p1.room = 0.34

b1.amp = 0.88
b1.hpf = 70
b1.lpf = 1200
b1.detune = 0.18

n1.amp = linvar([0.0,0.35],32)
d1.amp = 1.1
```

## Troubleshooting quick checks

- If `No module named renardo`: activate `.venv` and reinstall `renardo`.
- If `sclang not found`: export SuperCollider app path.
- If missing samples / `_loop_`: run sample downloader step.
- If boot appears stuck: apply compatibility patches above.
