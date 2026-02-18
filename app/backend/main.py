from __future__ import annotations

import ast
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
    ChatTroubleshootRequest,
    ChatTurnRequest,
    LLMSettingsRequest,
    LLMSettingsResponse,
    PatchApplyRequest,
    PatchUndoRequest,
    RuntimeLoadSongRequest,
    is_allowed_player_name,
)

ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = ROOT / "app" / "frontend"
DATA_DIR = ROOT / ".appdata"
DB_PATH = DATA_DIR / "ai_dj.sqlite3"
LLM_SETTINGS_PATH = DATA_DIR / "llm_settings.json"


@dataclass
class SessionState:
    globals: dict[str, Any] = field(default_factory=dict)
    players: dict[str, dict[str, Any]] = field(default_factory=dict)
    song_path: str | None = None
    clock_started_at: float | None = None


class AppState:
    def __init__(self) -> None:
        self.store = Store(DB_PATH)
        self.llm = LLMService()
        self.event_queues: list[asyncio.Queue[str]] = []
        self.runtime = RenardoRuntime(ROOT, self.publish_event)
        self.current_session_id = str(uuid.uuid4())
        self.store.ensure_session(self.current_session_id)
        self.session_state = SessionState()
        self.troubleshoot_usage: dict[str, int] = {}
        self._load_llm_settings()

    def _load_llm_settings(self) -> None:
        if not LLM_SETTINGS_PATH.exists():
            return
        try:
            payload = json.loads(LLM_SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(payload, dict):
            return
        self.llm.apply_settings(
            backend=payload.get("backend"),
            model=payload.get("model"),
            api_key=payload.get("api_key"),
            codex_command=payload.get("codex_command"),
            codex_model=payload.get("codex_model"),
        )

    def save_llm_settings(self, payload: LLMSettingsRequest) -> dict[str, Any]:
        next_backend = payload.backend if payload.backend is not None else self.llm.backend
        next_model = payload.model if payload.model is not None else self.llm.model
        next_key = payload.api_key if payload.api_key is not None else self.llm.api_key
        next_codex_command = (
            payload.codex_command
            if payload.codex_command is not None
            else " ".join(self.llm.codex_command)
        )
        next_codex_model = (
            payload.codex_model if payload.codex_model is not None else self.llm.codex_model
        )

        persisted = {
            "backend": next_backend,
            "model": next_model,
            "api_key": next_key,
            "codex_command": next_codex_command,
            "codex_model": next_codex_model,
        }
        LLM_SETTINGS_PATH.write_text(json.dumps(persisted, indent=2), encoding="utf-8")
        self.llm.apply_settings(
            backend=next_backend,
            model=next_model,
            api_key=next_key,
            codex_command=next_codex_command,
            codex_model=next_codex_model,
        )
        return self.llm.settings_payload()

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


@app.get("/sequencer")
async def sequencer_page() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "sequencer.html")


app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIR)), name="assets")
TROUBLESHOOT_LIMIT_PER_SESSION = 3


def _extract_literal_or_source(song_source: str, node: ast.AST) -> Any:
    try:
        parsed = ast.literal_eval(node)
        if isinstance(parsed, (bool, int, float, str)):
            return parsed
    except Exception:
        pass
    source = ast.get_source_segment(song_source, node)
    return source.strip() if source else ""


def _extract_call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return "play"


def _extract_song_session_state(song_path: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    song_source = song_path.read_text(encoding="utf-8")
    tree = ast.parse(song_source)
    globals_state: dict[str, Any] = {}
    players_state: dict[str, dict[str, Any]] = {}

    for node in tree.body:
        if isinstance(node, ast.Assign):
            if len(node.targets) != 1:
                continue
            target = node.targets[0]
            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
                full_target = f"{target.value.id}.{target.attr}"
                if full_target in {"Clock.bpm", "Scale.default", "Root.default"}:
                    globals_state[full_target] = _extract_literal_or_source(song_source, node.value)
            continue

        if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.BinOp):
            continue
        if not isinstance(node.value.op, ast.RShift):
            continue
        if not isinstance(node.value.left, ast.Name):
            continue
        player = node.value.left.id
        if not is_allowed_player_name(player):
            continue
        if not isinstance(node.value.right, ast.Call):
            continue

        call = node.value.right
        synth = _extract_call_name(call.func)
        pattern = ""
        if call.args:
            pattern = ast.get_source_segment(song_source, call.args[0]) or ""
        kwargs: dict[str, Any] = {}
        for kwarg in call.keywords:
            if kwarg.arg is None:
                continue
            kwargs[kwarg.arg] = _extract_literal_or_source(song_source, kwarg.value)

        player_state: dict[str, Any] = {
            "synth": synth,
            "pattern": pattern.strip(),
            "kwargs": kwargs,
            "last_assign_at": time.time(),
        }
        for k, v in kwargs.items():
            player_state[k] = v
        players_state[player] = player_state

    return globals_state, players_state


def _runtime_state_payload() -> dict[str, Any]:
    return {
        "session_id": state.current_session_id,
        "is_running": state.runtime.is_running(),
        "song_path": state.session_state.song_path,
        "clock_started_at": state.session_state.clock_started_at,
        "server_ts": time.time(),
        "globals": state.session_state.globals,
        "players": state.session_state.players,
    }


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
            player_kwargs = player_state.setdefault("kwargs", {})
            if isinstance(player_kwargs, dict):
                player_kwargs[param] = cmd["value"]
            player_state[param] = cmd["value"]
        elif op == "player_assign":
            player = cmd["player"]
            previous_state = state.session_state.players.get(player, {})
            previous_synth = previous_state.get("synth")
            previous_pattern = previous_state.get("pattern")
            previous_kwargs = previous_state.get("kwargs")
            if previous_synth and previous_pattern:
                revert.append(
                    {
                        "op": "player_assign",
                        "player": player,
                        "synth": previous_synth,
                        "pattern": previous_pattern,
                        "kwargs": previous_kwargs if isinstance(previous_kwargs, dict) else {},
                    }
                )
            else:
                revert.append({"op": "player_stop", "player": player})

            player_kwargs = cmd.get("kwargs", {})
            player_state = {
                "synth": cmd["synth"],
                "pattern": cmd["pattern"],
                "kwargs": player_kwargs if isinstance(player_kwargs, dict) else {},
                "last_assign_at": time.time(),
            }
            for k, v in player_state["kwargs"].items():
                player_state[k] = v
            state.session_state.players[player] = player_state
            if state.session_state.clock_started_at is None:
                state.session_state.clock_started_at = time.time()
        elif op == "clock_clear":
            # Clear isn't generally reversible; no automatic revert command.
            state.session_state.clock_started_at = None
            continue
        elif op == "player_stop":
            player = cmd["player"]
            previous_state = state.session_state.players.get(player, {})
            previous_synth = previous_state.get("synth")
            previous_pattern = previous_state.get("pattern")
            previous_kwargs = previous_state.get("kwargs")
            if previous_synth and previous_pattern:
                revert.append(
                    {
                        "op": "player_assign",
                        "player": player,
                        "synth": previous_synth,
                        "pattern": previous_pattern,
                        "kwargs": previous_kwargs if isinstance(previous_kwargs, dict) else {},
                    }
                )
            state.session_state.players.pop(player, None)
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
    song_path = Path(request.path)
    if not song_path.is_absolute():
        song_path = ROOT / song_path

    try:
        await state.runtime.ensure_running()
        await state.runtime.load_song(request.path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        globals_state, players_state = _extract_song_session_state(song_path)
        state.session_state.globals = globals_state
        state.session_state.players = players_state
    except Exception as exc:
        state.publish_event(
            "runtime",
            "warning",
            "Loaded song but failed to parse sequence state",
            {"song_path": str(song_path), "error": str(exc)},
        )
        state.session_state.players = {}
    state.session_state.song_path = request.path
    state.session_state.clock_started_at = time.time()

    state.store.update_session_song(state.current_session_id, request.path)
    state.store.record_snapshot(state.current_session_id, request.path, notes="manual load")
    return {"ok": True, "path": request.path}


@app.post("/api/runtime/stop")
async def runtime_stop() -> dict[str, Any]:
    await state.runtime.ensure_running()
    await state.runtime.clear_clock()
    state.session_state.clock_started_at = None
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


@app.get("/api/settings/llm", response_model=LLMSettingsResponse)
async def llm_settings_get() -> LLMSettingsResponse:
    return LLMSettingsResponse(**state.llm.settings_payload())


@app.post("/api/settings/llm", response_model=LLMSettingsResponse)
async def llm_settings_update(request: LLMSettingsRequest) -> LLMSettingsResponse:
    payload = state.save_llm_settings(request)
    state.publish_event("system", "info", "LLM settings updated", payload)
    return LLMSettingsResponse(**payload)


@app.post("/api/chat/turn")
async def chat_turn(request: ChatTurnRequest) -> dict[str, Any]:
    state.store.ensure_session(request.session_id)
    started = time.perf_counter()
    normalized = False
    normalization_notes: list[str] = []
    direct_json = False
    backend_failure: str | None = None

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
            commands = []
            model_name = "llm-failed"
            backend_failure = str(exc)
            normalization_notes.append(f"LLM backend failed: {exc}")
            normalized = True

    effective_commands = commands
    if not direct_json:
        effective_commands, normalize_notes = normalize_commands(commands)
        normalization_notes.extend(normalize_notes)
        normalized = normalized or bool(normalization_notes) or effective_commands != commands

    validation_status = "valid"
    apply_status = "pending"
    errors: list[str] = []
    emitted_code = ""
    revert_commands: list[dict[str, Any]] = []

    if not effective_commands:
        validation_status = "invalid"
        apply_status = "skipped"
        errors = [backend_failure or "LLM returned no commands"]
    else:
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
            if errors:
                validation_status = "invalid"
                emitted_code = ""
                apply_status = "skipped"
                normalization_notes.append(
                    "Model output failed validation. Edit your prompt and retry to self-heal."
                )
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
        "model": model_name,
        "latency_ms": latency_ms,
        "commands": commands,
        "effective_commands": effective_commands,
        "normalized": normalized,
        "normalization_notes": normalization_notes,
        "validation": {"valid": len(errors) == 0, "errors": errors},
        "apply_status": apply_status,
        "emitted_code": emitted_code,
        "needs_user_input": apply_status != "applied",
    }


@app.post("/api/chat/troubleshoot")
async def chat_troubleshoot(request: ChatTroubleshootRequest) -> dict[str, Any]:
    state.store.ensure_session(request.session_id)
    used = state.troubleshoot_usage.get(request.session_id, 0)
    if used >= TROUBLESHOOT_LIMIT_PER_SESSION:
        raise HTTPException(
            status_code=429,
            detail=f"troubleshoot budget exhausted ({TROUBLESHOOT_LIMIT_PER_SESSION} per session)",
        )

    repaired_commands, model_name, reason, confidence = await state.llm.generate_repair_commands(
        prompt=request.prompt,
        intent=request.intent.value,
        state={
            "globals": state.session_state.globals,
            "players": state.session_state.players,
        },
        failed_commands=request.failed_commands,
        validation_errors=request.validation_errors,
    )

    effective_commands, normalization_notes = normalize_commands(repaired_commands)
    _, emitted_code, errors = validate_and_emit(effective_commands)
    if errors:
        raise HTTPException(
            status_code=422,
            detail=f"repair output still invalid: {'; '.join(errors)}",
        )

    used += 1
    state.troubleshoot_usage[request.session_id] = used

    return {
        "ok": True,
        "model": model_name,
        "reason": reason,
        "confidence": confidence,
        "fixed_commands": effective_commands,
        "emitted_code_preview": emitted_code,
        "normalization_notes": normalization_notes,
        "budget": {
            "used": used,
            "limit": TROUBLESHOOT_LIMIT_PER_SESSION,
            "remaining": max(0, TROUBLESHOOT_LIMIT_PER_SESSION - used),
        },
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
            "song_path": state.session_state.song_path,
            "clock_started_at": state.session_state.clock_started_at,
        },
    }
    return payload


@app.get("/api/runtime/state")
async def runtime_state() -> dict[str, Any]:
    return _runtime_state_payload()


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
