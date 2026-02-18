# syntax-to-sound

Vibe coding for music with Python + Renardo.

## What this repo is

A playground for composing and experimenting with generative music ideas in code.

## Stack

- Python 3.10+
- Renardo
- SuperCollider (audio engine used by Renardo)
- FastAPI + vanilla web UI (AI DJ MVP)

## Quick start

```bash
make venv
make install
```

## AI DJ Web App (MVP)

Run local app:

```bash
make app
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000).

Optional for cloud LLM responses:

```bash
export OPENAI_API_KEY="your_key_here"
export OPENAI_MODEL="gpt-4.1-mini"
```

Without `OPENAI_API_KEY`, the app uses a local fallback patch generator so chat controls still work.

### LLM backend modes

The app now supports two LLM invocation paths:

1. `openai-api` (existing): use `OPENAI_API_KEY`
2. `codex-cli` (new): shell out to a local Codex CLI process

Backend selection:

```bash
export AI_DJ_LLM_BACKEND="auto"      # default: openai-api if key exists, else codex-cli if available, else fallback-local
export AI_DJ_LLM_BACKEND="openai-api"
export AI_DJ_LLM_BACKEND="codex-cli"
```

Codex CLI configuration (only needed for `codex-cli`):

```bash
export CODEX_CLI_COMMAND="codex exec"
export CODEX_MODEL="gpt-5-codex"
```

Start a fresh Codex CLI session directly:

```bash
make codex
```

### API surface

- `POST /api/runtime/boot`
- `POST /api/runtime/load-song`
- `POST /api/runtime/stop`
- `POST /api/chat/turn`
- `POST /api/patch/apply`
- `POST /api/patch/undo`
- `GET /api/events/stream`
- `GET /api/session/{session_id}`

### Local persistence

App state persists in:

- `.appdata/ai_dj.sqlite3`

## Start Renardo directly (existing flow)

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

## Tests

```bash
make test-app
```
