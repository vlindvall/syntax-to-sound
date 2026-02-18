# syntax-to-sound

Vibe coding for music with Python + Renardo, plus an AI DJ web app for live control.

## What this repo is
A local music playground where natural-language edits are converted into safe Renardo commands and applied live.

## Stack
- Python 3.10+
- Renardo + SuperCollider
- FastAPI backend
- Vanilla HTML/CSS/JS frontend

## Quickstart: First Sound in 3 Minutes

1. Install and set up:
```bash
make venv
make install
```

2. Start app:
```bash
make app
```

3. Open:
[http://127.0.0.1:8000](http://127.0.0.1:8000)

4. In UI:
- Click `Boot` (if not already ready)
- Click `Load Song` (default path works)
- Type prompt like `make it darker and slower`
- Click `Send`

If no cloud key is configured, the app still works using local fallback command generation.

## UI Overview (Current MVP)
The current UI has four panels:

1. `Transport`
- Boot runtime
- Stop (`Clock.clear()`)
- Undo last reversible patch
- Load song path
- Set BPM
- Configure LLM backend/settings

2. `DJ Chat`
- Prompt + intent selector (`edit`, `new_scene`, `mix_fix`)
- Send natural-language requests to `/api/chat/turn`
- See status messages for apply/reject/failure

3. `Command Trace`
- Per-turn detail view:
  - Input
  - API request body
  - Model raw commands
  - Normalized effective commands
  - Emitted Renardo Python
  - Outcome metadata
- Copy last/all trace to clipboard

4. `Mixer`
- P1 amp/lpf/hpf/pan sliders
- Applies via direct JSON command list through chat endpoint

5. `Events`
- Live SSE feed from backend runtime and patch events

## Typical Live Session Flow

1. Boot runtime (`Boot`).
2. Load target song file (`Load Song`).
3. Make incremental edits in chat (`Send`).
4. Use mixer sliders for immediate P1 shaping.
5. If result is wrong, use `Undo Last`.
6. Use Trace only when debugging model/normalizer behavior.

## LLM Backend Configuration

### Recommended default
Use `auto` backend in UI settings. It tries available backends in order and returns actionable failure feedback if they fail.

### Optional environment configuration
```bash
export AI_DJ_LLM_BACKEND="auto"
export OPENAI_API_KEY="your_key_here"
export OPENAI_MODEL="gpt-5.2-codex"
export CODEX_CLI_COMMAND="codex exec"
export CODEX_MODEL="gpt-5.2-codex"
```

### Backend modes
- `auto`: resolve backend chain automatically
- `openai-api`: force OpenAI API usage
- `codex-cli`: force local Codex CLI shellout

## Runtime and Safety Model

`/api/chat/turn` flow:
1. Parse direct JSON list if provided, else call selected LLM backend.
2. Normalize malformed command structures.
3. Validate against schema + safety emitter.
4. Emit constrained Renardo Python.
5. Apply to runtime and persist turn/patch/event data.
6. Compute revert commands for undo where possible.

Validation failure handling:
- If a turn is skipped due to invalid commands, the Create view offers `Diagnose & Fix`.
- This runs `POST /api/chat/troubleshoot` with a strict per-session budget.
- The user can explicitly apply returned repaired commands; no automatic retry loop is performed.

Persistence:
- SQLite DB: `.appdata/ai_dj.sqlite3`
- LLM settings JSON: `.appdata/llm_settings.json`

## API Surface
- `POST /api/runtime/boot`
- `POST /api/runtime/load-song`
- `POST /api/runtime/stop`
- `POST /api/runtime/ping-sound`
- `GET /api/settings/llm`
- `POST /api/settings/llm`
- `POST /api/chat/turn`
- `POST /api/chat/troubleshoot`
- `POST /api/patch/apply`
- `POST /api/patch/undo`
- `GET /api/session/{session_id}`
- `GET /api/events/stream`

## Troubleshooting

### App opens but no sound
- Verify SuperCollider is installed.
- Ensure Renardo boot path works on your machine.
- Follow `RENARDO_PLAYBACK_RUNBOOK.md`.

### `codex-cli` backend selected but requests fail
- Confirm binary exists on PATH.
- Verify `CODEX_CLI_COMMAND` value (example: `codex exec`).
- Use `auto` so OpenAI API can be used if configured.

### OpenAI backend fails
- Confirm valid `OPENAI_API_KEY`.
- Confirm model exists and is accessible.
- Switch backend to `auto` for continuity when codex-cli is available.

### Patch rejected or skipped
- Use `Diagnose & Fix` first (bounded troubleshoot budget).
- Open `Command Trace` to compare raw commands vs normalized commands.
- Check validation errors in outcome stage.
- Retry manually if needed after reviewing fix details.

### Undo fails with "patch is not reversible"
- Some operations (for example `clock_clear`) are not auto-reversible.
- Retry by issuing a corrective prompt or reloading the song state.

## Start Renardo Directly (No Web UI)
```bash
make renardo
```

Deterministic startup path on this machine:
```bash
make renardo-boot
```

Auto boot + auto load song:
```bash
make play SONG=songs/2026-02-17_boten_anna_handsup.py
```

Live reload while editing file:
```bash
make live SONG=songs/2026-02-17_boten_anna_handsup.py
```

## Create a New Song Sketch
```bash
make new-song NAME="Neon Rain"
```

## Tests
```bash
make test-app
```

## Redesign Planning Docs
- UI rethink plan: `docs/ui-first-principles-plan.md`
