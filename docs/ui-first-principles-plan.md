# AI DJ UI First-Principles Redesign Plan

## Scope
This document defines:
- What the current UI does today
- Why it feels overloaded
- A redesigned information architecture and interaction model
- A phased implementation plan

This plan targets the existing FastAPI + vanilla JS app.

## Product Goal
Help a performer safely and quickly shape live audio with AI assistance, while keeping deep debugging tools available but out of the way.

## Current UI Specification (As Implemented)

### Entry and startup
- `GET /` serves a single-page UI.
- On page load, frontend immediately:
  - connects to SSE (`/api/events/stream`)
  - ensures trace container exists
  - calls `boot()` (`POST /api/runtime/boot`)
- Successful boot sets one session id in frontend memory and fetches LLM settings.

### Transport panel
- Buttons:
  - `Boot`: starts/ensures runtime, refreshes settings.
  - `Stop`: calls `/api/runtime/stop` (clock clear only).
  - `Undo Last`: calls `/api/patch/undo` using current session.
- Song loading:
  - text input for path
  - `Load Song`: calls `/api/runtime/load-song`.
- BPM:
  - numeric input (50..220)
  - `Set`: converts to natural language prompt (`Set bpm to X`) and routes through chat endpoint.

### LLM settings block
- Fields:
  - backend (`auto`, `openai-api`, `codex-cli`)
  - model
  - api key (write-only in UI)
  - codex command/model in advanced disclosure block
- `Refresh Settings` -> `GET /api/settings/llm`
- `Save Settings` -> `POST /api/settings/llm`
- Disclosure behavior is backend-dependent (show/hide key + codex controls).
- Persisted on backend in `.appdata/llm_settings.json`.

### Chat panel
- Message log (`user` and `system` only).
- Prompt input + intent selector (`edit`, `new_scene`, `mix_fix`) + `Send`.
- `Send` behavior:
  - autoboot if session missing
  - POST `/api/chat/turn`
  - append result status message and optional normalization notes
- Command trace:
  - per-turn expandable entry with six stages
  - copy last / copy all / clear trace controls

### Mixer panel
- Sliders for `p1`: amp/lpf/hpf/pan.
- `Apply Mixer` constructs direct JSON command list and submits via `/api/chat/turn` with `intent=mix_fix`.
- Changes apply immediately.

### Events panel
- Appends SSE lines with local timestamp into a scrolling `<pre>` log.

### Backend behavior exposed in UI
- `chat/turn` pipeline:
  - direct-json fast path for JSON prompt list
  - else LLM generation via selected backend chain
  - normalization pass
  - safety validation + python emission
  - runtime apply
  - when invalid/failure, return actionable feedback (no silent fallback repair)
- Response includes:
  - raw commands
  - normalized effective commands
  - emitted code
  - apply status, validation, normalization notes, latency
- Undo depends on stored computed revert commands.

## Problems (First-Principles Diagnosis)
1. No dominant workflow.
The UI mixes setup, performance, debugging, and backend tuning at equal visual priority.

2. High cognitive load at first glance.
Advanced controls (LLM/backend internals + trace ops) are present before the user can make sound.

3. State visibility is fragmented.
Status appears in multiple surfaces (`statusLine`, messages, events, trace), with no single source of truth.

4. Risky operations are under-signaled.
Actions that alter live output apply immediately without “review before commit” mode.

5. Error messages are technically accurate but not operationally actionable.
Raw API errors are shown in chat stream without guided recovery.

6. Debug power is good but default density is too high.
Trace opens fully by default and competes with creative flow.

## Design Principles
1. Sound first in under 60 seconds.
2. Safe-by-default during live operation.
3. Progressive disclosure for complexity.
4. Single, legible system status model.
5. Fast reversible actions (undo, panic stop, clear outcomes).
6. Keep expert controls, but isolate them in Inspect paths.

## New Information Architecture

### Modes
1. Perform
- Primary live controls only.
- Prominent system status, panic stop, undo, BPM, quick macro prompts.

2. Create
- Prompt composer + intent + optional assisted controls.
- Result summary cards: what changed, was it normalized, applied or skipped.

3. Inspect
- Trace, events, emitted code, backend settings, diagnostics.
- Export/copy features live here.

### Top-level layout
- Header: session/running state, active song, backend chip, latency chip.
- Left rail (or segmented control on mobile): `Perform | Create | Inspect`.
- Main content swaps by mode.
- Persistent bottom action bar on mobile for `Send`, `Undo`, `Panic Stop`.

## Interaction Specification

### System status model
Single runtime state object in frontend:
- `runtime`: disconnected | booting | ready | error
- `audio`: stopped | playing | changing
- `last_action`: success | warning | failure + message
- `connectivity`: sse_connected | reconnecting

All status surfaces render from this model.

### Action safety levels
- Safe: load settings refresh, trace copy
- Review: chat-generated multi-command patch in Perform mode
- Risky: clock clear, bulk stop, direct-json patch apply

Risky actions require explicit confirmation in Perform mode (can be disabled in Inspect).

### Progressive disclosure map
Default visible:
- minimal transport
- prompt + send
- concise result card

Hidden by default, one click away:
- raw commands
- normalization notes full list
- emitted python
- codex command/model
- event stream raw view

### Error UX
For each failure, show:
- human-readable summary
- probable cause bucket (runtime/validation/backend/network)
- one next action button
Examples:
- Runtime not running -> `Boot Runtime`
- Validation failure -> `Open Command Diff`
- LLM backend failure -> `Open LLM Settings`

### Troubleshoot-and-fix flow (token-bounded)
- Trigger only when validation fails (`apply_status=skipped`, invalid commands).
- CTA: `Diagnose & Fix (1 credit)`.
- Backend endpoint analyzes failed commands + validation errors and returns corrected command JSON.
- User intent prompt remains unchanged; only command payload is repaired.
- User must explicitly click `Apply Fix` (no auto-apply loop).
- Budget is enforced per session (default limit: 3 troubleshoot calls).

### Undo semantics in UI
- Always show whether last patch is reversible.
- Show “what undo will revert” summary when possible.
- Disable button with reason text when not reversible.

### Trace redesign
- Default collapsed list with one-line summaries.
- Expand shows stages in tabs: Input, Commands, Normalize, Emit, Outcome.
- Highlight changed values between raw and effective commands.

## Accessibility and Interaction Quality Baseline
- Keyboard reachable controls and visible focus.
- Chat/events rendered as proper live regions.
- Color contrast >= WCAG AA.
- All icon-only controls include labels.
- Reduced motion support for non-essential animations.

## API and Frontend Refactor Plan

### Keep existing endpoints
- `/api/runtime/*`, `/api/chat/turn`, `/api/settings/llm`, `/api/patch/undo`, `/api/events/stream`

### Additions (recommended)
1. `GET /api/runtime/status`
- canonical runtime status for initial hydration and reconnection.

2. `GET /api/session/{id}/last-patch-summary`
- small payload for reversible state + changed targets.

3. Optional dry-run mode on `/api/chat/turn`
- `apply=false` to preview in Perform mode before commit.

### Frontend internal refactor
- Introduce centralized state store object.
- Split large `app.js` into modules:
  - `api.js`
  - `state.js`
  - `views/perform.js`
  - `views/create.js`
  - `views/inspect.js`
  - `trace.js`
  - `a11y.js`

## Phased Delivery

### Phase 1: IA and status consolidation
- Mode shell + shared status model
- move settings and trace to Inspect
- preserve all current backend behavior

### Phase 2: safer change application
- optional review/preview step
- richer action confirmations and error recovery prompts

### Phase 3: inspect tooling quality
- trace diffing
- filtered events
- export session debug bundle

### Phase 4: polish and metrics
- keyboard pass
- accessibility pass
- latency and success metrics in UI

## Success Metrics
- Time to first successful sound
- Prompt-to-applied success rate
- Undo usage success rate
- Validation failure recovery rate
- User path concentration (Perform vs Inspect leakage)

## README Redesign Plan
README should follow a user-needs structure:
1. 3-minute quickstart (first sound)
2. Live session workflow (performing)
3. UI mode guide (Perform/Create/Inspect)
4. LLM backend configuration matrix
5. Troubleshooting by symptom
6. API reference (compact)
7. Development and tests

## Research References
- Microsoft Human-AI Guidelines: https://www.microsoft.com/en-us/research/publication/guidelines-for-human-ai-interaction/
- W3C ARIA technique for logs: https://www.w3.org/WAI/WCAG21/Techniques/aria/ARIA23.html
- MDN ARIA live regions: https://developer.mozilla.org/en-US/docs/Web/Accessibility/ARIA/ARIA_Live_Regions
- USWDS Accordion guidance (progressive disclosure tradeoffs): https://designsystem.digital.gov/components/accordion/
- GitHub Docs writing best practices: https://docs.github.com/en/contributing/writing-for-github-docs/best-practices-for-github-docs
- Diataxis framework: https://diataxis.fr/start-here/
