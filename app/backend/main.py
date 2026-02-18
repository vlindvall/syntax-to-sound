from __future__ import annotations

import asyncio
import contextlib
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.backend.llm_service import LLMService
from app.backend.command_normalizer import normalize_commands
from app.backend.renardo_runtime import RenardoRuntime
from app.backend.safety import validate_and_emit
from app.backend.store import Store
from app.shared.contracts import (
    BootResponse,
    ChatTurnRequest,
    PatchApplyRequest,
    PatchUndoRequest,
    RuntimeLoadSongRequest,
)

ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = ROOT / "app" / "frontend"
DATA_DIR = ROOT / ".appdata"
DB_PATH = DATA_DIR / "ai_dj.sqlite3"


@dataclass
class SessionState:
    globals: dict[str, Any] = field(default_factory=dict)
    players: dict[str, dict[str, Any]] = field(default_factory=dict)


class AppState:
    def __init__(self) -> None:
        self.store = Store(DB_PATH)
        self.llm = LLMService()
        self.event_queues: list[asyncio.Queue[str]] = []
        self.runtime = RenardoRuntime(ROOT, self.publish_event)
        self.current_session_id = str(uuid.uuid4())
        self.store.ensure_session(self.current_session_id)
        self.session_state = SessionState()

    def publish_event(self, source: str, level: str, message: str, payload: dict[str, Any]) -> None:
        event_payload = {
            "source": source,
            "level": level,
            "message": message,
            "payload": payload,
            "ts": time.time(),
        }
        self.store.log_event(self.current_session_id, source, level, message, payload)
        serialized = f"data: {json.dumps(event_payload)}\n\n"
        for queue in list(self.event_queues):
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(serialized)


app = FastAPI(title="AI DJ MVP", version="0.1.0")
state = AppState()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIR)), name="assets")


def _compute_revert(commands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    revert: list[dict[str, Any]] = []
    for cmd in commands:
        op = cmd["op"]
        if op == "set_global":
            target = cmd["target"]
            previous = state.session_state.globals.get(target)
            if previous is not None:
                revert.append({"op": "set_global", "target": target, "value": previous})
            state.session_state.globals[target] = cmd["value"]
        elif op == "player_set":
            player = cmd["player"]
            param = cmd["param"]
            player_state = state.session_state.players.setdefault(player, {})
            previous = player_state.get(param)
            if previous is not None:
                revert.append(
                    {
                        "op": "player_set",
                        "player": player,
                        "param": param,
                        "value": previous,
                    }
                )
            player_state[param] = cmd["value"]
        elif op == "player_assign":
            revert.append({"op": "player_stop", "player": cmd["player"]})
            player_state = state.session_state.players.setdefault(cmd["player"], {})
            player_state["synth"] = cmd["synth"]
            player_state["pattern"] = cmd["pattern"]
            for k, v in cmd.get("kwargs", {}).items():
                player_state[k] = v
        elif op == "clock_clear":
            # Clear isn't generally reversible; no automatic revert command.
            continue
        elif op == "player_stop":
            continue
    return revert


async def _apply_commands(raw_commands: list[dict[str, Any]]) -> tuple[str, list[str], list[dict[str, Any]]]:
    commands, emitted, errors = validate_and_emit(raw_commands)
    if errors:
        return "", errors, []

    await state.runtime.send_lines(emitted)
    state.publish_event("patch", "info", "Applied patch", {"code": emitted})
    revert = _compute_revert(raw_commands)
    return emitted, [], revert


@app.post("/api/runtime/boot", response_model=BootResponse)
async def runtime_boot() -> BootResponse:
    try:
        await state.runtime.ensure_running()
    except Exception as exc:
        state.publish_event("runtime", "error", "Boot failed", {"error": str(exc)})
        return BootResponse(status="error", session_id=state.current_session_id)
    return BootResponse(status="ready", session_id=state.current_session_id)


@app.post("/api/runtime/load-song")
async def runtime_load_song(request: RuntimeLoadSongRequest) -> dict[str, Any]:
    try:
        await state.runtime.ensure_running()
        await state.runtime.load_song(request.path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    state.store.update_session_song(state.current_session_id, request.path)
    state.store.record_snapshot(state.current_session_id, request.path, notes="manual load")
    return {"ok": True, "path": request.path}


@app.post("/api/runtime/stop")
async def runtime_stop() -> dict[str, Any]:
    await state.runtime.ensure_running()
    await state.runtime.clear_clock()
    return {"ok": True}


@app.post("/api/runtime/ping-sound")
async def runtime_ping_sound() -> dict[str, Any]:
    await state.runtime.ensure_running()
    source = "\n".join(
        [
            "Clock.clear()",
            "Clock.bpm = 120",
            "p1 >> pluck([0,2,4,7], dur=0.25, amp=1)",
        ]
    )
    await state.runtime.send_lines(source)
    return {"ok": True}


@app.post("/api/chat/turn")
async def chat_turn(request: ChatTurnRequest) -> dict[str, Any]:
    state.store.ensure_session(request.session_id)
    started = time.perf_counter()
    normalized = False
    normalization_notes: list[str] = []
    direct_json = False

    try:
        parsed = json.loads(request.prompt)
        if isinstance(parsed, list):
            commands = parsed
            model_name = "direct-json"
            direct_json = True
        else:
            raise ValueError("prompt JSON was not a command list")
    except Exception:
        try:
            commands, model_name = await state.llm.generate_patch(
                prompt=request.prompt,
                intent=request.intent.value,
                state={
                    "globals": state.session_state.globals,
                    "players": state.session_state.players,
                },
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"LLM failure: {exc}") from exc

    effective_commands = commands
    if not direct_json:
        effective_commands, normalization_notes = normalize_commands(commands)
        normalized = bool(normalization_notes) or effective_commands != commands

    validation_status = "valid"
    apply_status = "pending"
    used_fallback_repair = False

    try:
        await state.runtime.ensure_running()
        emitted_code, errors, revert_commands = await _apply_commands(effective_commands)
        if (
            errors
            and direct_json
            and request.intent.value != "mix_fix"
            and isinstance(commands, list)
        ):
            retry_commands, retry_notes = normalize_commands(commands)
            if retry_commands != effective_commands or retry_notes:
                emitted_code, errors, revert_commands = await _apply_commands(retry_commands)
                effective_commands = retry_commands
                normalization_notes.extend(retry_notes)
                normalized = bool(normalization_notes) or effective_commands != commands
        if errors and model_name != "direct-json":
            fallback_commands = state.llm.generate_fallback_patch(
                prompt=request.prompt,
                intent=request.intent.value,
            )
            fallback_effective, fallback_notes = normalize_commands(fallback_commands)
            fallback_emitted_code, fallback_errors, fallback_revert = await _apply_commands(
                fallback_effective
            )
            if not fallback_errors:
                commands = fallback_commands
                effective_commands = fallback_effective
                normalization_notes.extend(
                    ["Used fallback-local command repair after model output failed validation"]
                )
                normalization_notes.extend(fallback_notes)
                normalized = bool(normalization_notes) or effective_commands != commands
                emitted_code = fallback_emitted_code
                errors = []
                revert_commands = fallback_revert
                apply_status = "applied"
                validation_status = "valid"
                used_fallback_repair = True
        if errors:
            validation_status = "invalid"
            emitted_code = ""
            apply_status = "skipped"
        else:
            apply_status = "applied"
    except Exception as exc:
        emitted_code = ""
        errors = [str(exc)]
        apply_status = "failed"

    latency_ms = int((time.perf_counter() - started) * 1000)
    turn_id = state.store.create_turn(request.session_id, request.prompt, model_name, latency_ms)
    patch_id = state.store.create_patch(
        turn_id=turn_id,
        json_commands=commands,
        effective_commands=effective_commands,
        normalized=normalized,
        normalization_notes=normalization_notes,
        emitted_code=emitted_code,
        validation_status=validation_status,
        apply_status=apply_status,
        revert_commands=revert_commands if apply_status == "applied" else [],
    )

    return {
        "session_id": request.session_id,
        "turn_id": turn_id,
        "patch_id": patch_id,
        "model": f"{model_name}+fallback-local" if used_fallback_repair else model_name,
        "latency_ms": latency_ms,
        "commands": commands,
        "effective_commands": effective_commands,
        "normalized": normalized,
        "normalization_notes": normalization_notes,
        "validation": {"valid": len(errors) == 0, "errors": errors},
        "apply_status": apply_status,
        "emitted_code": emitted_code,
    }


@app.post("/api/patch/apply")
async def patch_apply(request: PatchApplyRequest) -> dict[str, Any]:
    patch = state.store.get_patch(request.patch_id)
    if patch is None:
        raise HTTPException(status_code=404, detail="patch not found")

    await state.runtime.ensure_running()
    emitted_code, errors, _ = await _apply_commands(patch["effective_commands"])
    if errors:
        return {"ok": False, "errors": errors}
    return {"ok": True, "emitted_code": emitted_code}


@app.post("/api/patch/undo")
async def patch_undo(request: PatchUndoRequest) -> dict[str, Any]:
    patch = state.store.get_last_applied_patch(request.session_id)
    if patch is None:
        raise HTTPException(status_code=404, detail="no applied patch found")
    if not patch["revert_commands"]:
        raise HTTPException(status_code=400, detail="patch is not reversible")

    await state.runtime.ensure_running()
    emitted_code, errors, _ = await _apply_commands(patch["revert_commands"])
    if errors:
        return {"ok": False, "errors": errors}
    return {"ok": True, "reverted_patch_id": patch["id"], "emitted_code": emitted_code}


@app.get("/api/session/{session_id}")
async def session_detail(session_id: str) -> dict[str, Any]:
    payload = state.store.get_session(session_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="session not found")
    payload["runtime"] = {
        "is_running": state.runtime.is_running(),
        "state": {
            "globals": state.session_state.globals,
            "players": state.session_state.players,
        },
    }
    return payload


@app.get("/api/events/stream")
async def events_stream() -> StreamingResponse:
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=500)
    state.event_queues.append(queue)

    async def generator() -> Any:
        try:
            yield "data: {\"source\":\"system\",\"level\":\"info\",\"message\":\"events connected\"}\n\n"
            while True:
                event = await queue.get()
                yield event
        finally:
            with contextlib.suppress(ValueError):
                state.event_queues.remove(queue)

    return StreamingResponse(generator(), media_type="text/event-stream")
