from __future__ import annotations

import asyncio
import ast
import json
import os
import re
import shlex
import shutil
import tempfile
from pathlib import Path
from typing import Any


SYSTEM_PROMPT = """You are an AI DJ assistant for Renardo live coding.
Return ONLY JSON with this shape: {\"commands\": [PatchCommand, ...]}.
Never return Python code, markdown, or prose.
Allowed PatchCommand ops: set_global, player_assign, player_set, player_stop, clock_clear.
For player_set, valid params include: amp, dur, sus, oct, lpf, hpf, pan, room, mix, echo, delay, chop, sample, rate, detune, drive, shape, blur, formant, coarse, spin.
Keep commands short, musical, and safe. Max 12 commands.
"""

REPAIR_SYSTEM_PROMPT = """You repair invalid Renardo patch commands for an AI DJ system.
Return ONLY JSON: {\"commands\": [PatchCommand, ...], \"reason\": \"...\", \"confidence\": 0.0}.
Do not explain anything outside JSON.
Preserve the user's musical intent.
Repair only what is needed to pass validation and safety checks.
Prefer the smallest safe command list. Max 6 commands.
"""


class LLMService:
    def __init__(self) -> None:
        self.backend = os.getenv("AI_DJ_LLM_BACKEND", "auto").strip().lower()
        self.api_key = os.getenv("OPENAI_API_KEY", "")
        self.model = os.getenv("OPENAI_MODEL", "gpt-5.2-codex")
        timeout = os.getenv("CODEX_TIMEOUT_SECONDS", "45").strip()
        try:
            self.codex_timeout_seconds = max(1.0, float(timeout))
        except ValueError:
            self.codex_timeout_seconds = 45.0

        codex_command = os.getenv("CODEX_CLI_COMMAND", "codex exec")
        self.codex_command = shlex.split(codex_command) if codex_command.strip() else []
        self.codex_model = os.getenv("CODEX_MODEL", self.model)
        self.codex_available = False
        self._refresh_codex_availability()

    def apply_settings(
        self,
        backend: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        codex_command: str | None = None,
        codex_model: str | None = None,
    ) -> None:
        if backend is not None:
            self.backend = backend.strip().lower()
        if model is not None:
            self.model = model.strip()
        if api_key is not None:
            self.api_key = api_key.strip()
        if codex_command is not None:
            parsed = shlex.split(codex_command) if codex_command.strip() else []
            self.codex_command = parsed
        if codex_model is not None:
            self.codex_model = codex_model.strip()

        if not self.codex_model:
            self.codex_model = self.model
        self._refresh_codex_availability()

    def _refresh_codex_availability(self) -> None:
        self.codex_available = False
        if not self.codex_command:
            return

        resolved = self._resolve_executable(self.codex_command[0])
        if not resolved:
            return

        self.codex_command = [resolved, *self.codex_command[1:]]
        self.codex_available = True

    def _resolve_executable(self, executable: str) -> str | None:
        if not executable:
            return None
        if os.path.isabs(executable):
            return executable if os.access(executable, os.X_OK) else None

        resolved = shutil.which(executable)
        if resolved:
            return resolved

        home = str(Path.home())
        extra_paths = [
            "/opt/homebrew/bin",
            "/usr/local/bin",
            "/usr/bin",
            "/bin",
            f"{home}/.local/bin",
        ]
        path_entries = [os.environ.get("PATH", ""), *extra_paths]
        search_path = os.pathsep.join(entry for entry in path_entries if entry)
        return shutil.which(executable, path=search_path)

    def settings_payload(self) -> dict[str, Any]:
        api_key_hint = None
        if self.api_key:
            tail = self.api_key[-4:] if len(self.api_key) >= 4 else self.api_key
            api_key_hint = f"...{tail}"
        return {
            "backend": self.backend,
            "model": self.model,
            "has_api_key": bool(self.api_key),
            "api_key_hint": api_key_hint,
            "codex_command": " ".join(self.codex_command),
            "codex_model": self.codex_model,
        }

    async def generate_patch(
        self,
        prompt: str,
        intent: str,
        state: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], str]:
        user_content = {
            "intent": intent,
            "prompt": prompt,
            "state": state or {},
            "schema_hint": {
                "commands": [
                    {
                        "op": "player_set",
                        "player": "p1",
                        "param": "amp",
                        "value": 0.7,
                    }
                ]
            },
        }

        if self.backend == "openai-api":
            return await self._generate_openai(user_content)
        if self.backend == "codex-cli":
            return await self._generate_codex_cli(user_content)
        if self.backend == "fallback-local":
            raise RuntimeError("fallback-local backend is disabled")

        failures: list[str] = []
        for backend in self._resolve_backend_chain():
            try:
                if backend == "codex-cli":
                    return await self._generate_codex_cli(user_content)
                if backend == "openai-api":
                    return await self._generate_openai(user_content)
            except Exception as exc:
                failures.append(f"{backend}: {exc}")
                continue

        if failures:
            raise RuntimeError("all LLM backends failed: " + "; ".join(failures))
        raise RuntimeError("no LLM backend is configured or available")

    async def generate_repair_commands(
        self,
        *,
        prompt: str,
        intent: str,
        state: dict[str, Any],
        failed_commands: list[dict[str, Any]],
        validation_errors: list[str],
    ) -> tuple[list[dict[str, Any]], str, str, float]:
        user_content = {
            "intent": intent,
            "prompt": prompt,
            "state": state,
            "failed_commands": failed_commands[:12],
            "validation_errors": validation_errors[:8],
            "goal": "Return corrected commands that validate and are safe to apply.",
        }

        failures: list[str] = []
        for backend in self._resolve_backend_chain():
            try:
                if backend == "codex-cli":
                    payload, model = await self._generate_codex_payload(
                        user_content=user_content,
                        system_prompt=REPAIR_SYSTEM_PROMPT,
                    )
                elif backend == "openai-api":
                    payload, model = await self._generate_openai_payload(
                        user_content=user_content,
                        system_prompt=REPAIR_SYSTEM_PROMPT,
                        max_output_tokens=220,
                    )
                else:
                    continue

                commands = self._extract_commands_from_payload(payload)
                reason = str(payload.get("reason", "")).strip() if isinstance(payload, dict) else ""
                confidence_raw = payload.get("confidence", 0.0) if isinstance(payload, dict) else 0.0
                try:
                    confidence = float(confidence_raw)
                except Exception:
                    confidence = 0.0
                confidence = min(1.0, max(0.0, confidence))
                return commands, model, reason, confidence
            except Exception as exc:
                failures.append(f"{backend}: {exc}")
                continue

        if failures:
            raise RuntimeError("repair failed across backends: " + "; ".join(failures))
        raise RuntimeError("no LLM backend is configured or available for repair")

    def _resolve_backend_chain(self) -> list[str]:
        self._refresh_codex_availability()
        chain: list[str] = []
        if self.codex_available:
            chain.append("codex-cli")
        if self.api_key:
            chain.append("openai-api")
        return chain

    async def _generate_openai(self, user_content: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
        payload, model = await self._generate_openai_payload(
            user_content=user_content,
            system_prompt=SYSTEM_PROMPT,
            max_output_tokens=360,
        )
        commands = self._extract_commands_from_payload(payload)
        return commands, model

    async def _generate_openai_payload(
        self,
        *,
        user_content: dict[str, Any],
        system_prompt: str,
        max_output_tokens: int,
    ) -> tuple[Any, str]:
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is required for openai-api backend")

        try:
            from openai import AsyncOpenAI
        except Exception as exc:
            raise RuntimeError("openai package is unavailable") from exc

        client = AsyncOpenAI(api_key=self.api_key)

        response = await client.responses.create(
            model=self.model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_content)},
            ],
            text={"format": {"type": "json_object"}},
            max_output_tokens=max_output_tokens,
        )
        payload = self._extract_json_payload(response.output_text)
        return payload, self.model

    async def _generate_codex_cli(self, user_content: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
        payload, model = await self._generate_codex_payload(
            user_content=user_content,
            system_prompt=SYSTEM_PROMPT,
        )
        commands = self._extract_commands_from_payload(payload)
        return commands, model

    async def _generate_codex_payload(
        self,
        *,
        user_content: dict[str, Any],
        system_prompt: str,
    ) -> tuple[Any, str]:
        if not self.codex_command:
            raise ValueError("CODEX_CLI_COMMAND is empty")
        self._refresh_codex_availability()
        if not self.codex_available:
            raise RuntimeError(f"codex CLI binary not found: {self.codex_command[0]}")

        prompt = (
            f"{system_prompt}\n\n"
            "Return ONLY JSON.\n\n"
            f"{json.dumps(user_content)}"
        )
        fd, output_path = tempfile.mkstemp(prefix="codex-last-", suffix=".txt")
        os.close(fd)
        try:
            process = await asyncio.create_subprocess_exec(
                *self.codex_command,
                "--model",
                self.codex_model,
                "--output-last-message",
                output_path,
                prompt,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=self.codex_timeout_seconds
                )
            except asyncio.TimeoutError as exc:
                process.kill()
                await process.communicate()
                raise RuntimeError(
                    f"codex CLI timed out after {self.codex_timeout_seconds:.1f}s"
                ) from exc

            if process.returncode != 0:
                raise RuntimeError(
                    f"codex CLI failed with exit code {process.returncode}: {stderr.decode(errors='replace').strip()}"
                )

            output = ""
            try:
                with open(output_path, "r", encoding="utf-8", errors="replace") as handle:
                    output = handle.read().strip()
            except Exception:
                output = ""
        finally:
            try:
                os.remove(output_path)
            except OSError:
                pass

        if not output:
            output = stdout.decode(errors="replace").strip()
        payload = self._extract_json_payload(output)
        return payload, f"codex-cli:{self.codex_model}"

    def _extract_commands_from_payload(self, payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            commands = payload
        elif isinstance(payload, dict):
            commands = payload.get("commands", [])
        else:
            raise ValueError("model returned a non-JSON payload")

        if not isinstance(commands, list):
            raise ValueError("model returned invalid commands payload")
        normalized = self._normalize_commands(commands)
        if not normalized:
            raise ValueError("model returned empty commands payload")
        return normalized

    def _extract_commands(self, text: str) -> list[dict[str, Any]]:
        payload = self._extract_json_payload(text)
        return self._extract_commands_from_payload(payload)

    def _extract_json_payload(self, text: str) -> Any:
        payloads = self._extract_json_payloads(text)
        for payload in payloads:
            if isinstance(payload, (list, dict)):
                return payload
        raise ValueError("model returned invalid JSON payload")

    def _extract_json_payloads(self, text: str) -> list[Any]:
        stripped = text.strip()
        if not stripped:
            raise ValueError("model returned empty output")

        payloads: list[Any] = []
        # Prefer whole-line JSON first; Codex CLI prints assistant messages line-by-line.
        for line in stripped.splitlines():
            candidate = line.strip()
            if not candidate:
                continue
            if candidate[0] not in "{[":
                start = min(
                    (idx for idx in (candidate.find("{"), candidate.find("[")) if idx >= 0),
                    default=-1,
                )
                if start < 0:
                    continue
                candidate = candidate[start:]
            try:
                payloads.append(json.loads(candidate))
            except Exception:
                pass

        try:
            payloads.append(json.loads(stripped))
        except Exception:
            pass

        decoder = json.JSONDecoder()
        for idx, ch in enumerate(stripped):
            if ch not in "{[":
                continue
            try:
                value, _ = decoder.raw_decode(stripped[idx:])
                payloads.append(value)
            except Exception:
                continue

        if payloads:
            return payloads
        raise ValueError("model output did not contain valid JSON")

    def generate_fallback_patch(self, prompt: str, intent: str) -> list[dict[str, Any]]:
        return self._fallback_patch(prompt, intent)

    def _normalize_commands(self, commands: list[Any]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for raw in commands:
            if not isinstance(raw, dict):
                continue

            op = str(raw.get("op", "")).strip()
            if not op:
                continue

            command = dict(raw)

            if op == "set_global":
                if "value" not in command and "val" in command:
                    command["value"] = command["val"]

                if command.get("target") is None:
                    alias = str(command.get("param", command.get("name", ""))).strip().lower()
                    target_map = {
                        "bpm": "Clock.bpm",
                        "tempo": "Clock.bpm",
                        "clock.bpm": "Clock.bpm",
                        "scale": "Scale.default",
                        "scale.default": "Scale.default",
                        "root": "Root.default",
                        "root.default": "Root.default",
                    }
                    mapped = target_map.get(alias)
                    if mapped:
                        command["target"] = mapped

            elif op == "player_assign":
                if "synth" not in command and "voice" in command:
                    command["synth"] = command["voice"]

                if "kwargs" not in command:
                    kwargs = command.get("kwargs", {})
                    if not isinstance(kwargs, dict):
                        kwargs = {}
                    command["kwargs"] = kwargs

                parsed = self._parse_player_assign_pattern(command.get("pattern"))
                if parsed:
                    synth, pattern, kwargs = parsed
                    if "synth" not in command:
                        command["synth"] = synth
                    command["pattern"] = pattern
                    command["kwargs"].update(kwargs)

                if "synth" not in command:
                    command["synth"] = "pluck"
                if "pattern" not in command:
                    command["pattern"] = "[0,2,4,7]"

            elif op == "player_set":
                param_alias = str(command.get("param", "")).strip().lower()
                param_map = {
                    "cutoff": "lpf",
                    "filter": "lpf",
                    "tempo": "dur",
                }
                mapped = param_map.get(param_alias)
                if mapped:
                    command["param"] = mapped

            normalized.append(command)

        return normalized

    def _parse_player_assign_pattern(self, pattern: Any) -> tuple[str, str, dict[str, Any]] | None:
        if not isinstance(pattern, str):
            return None

        source = pattern.strip()
        if not re.match(r"^[A-Za-z_]\w*\(.*\)$", source):
            return None

        try:
            node = ast.parse(source, mode="eval").body
        except Exception:
            return None

        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            return None

        synth = node.func.id
        pattern_value = ast.unparse(node.args[0]) if node.args else "[0,2,4,7]"

        kwargs: dict[str, Any] = {}
        for kw in node.keywords:
            if not kw.arg:
                continue
            try:
                kwargs[kw.arg] = ast.literal_eval(kw.value)
            except Exception:
                kwargs[kw.arg] = ast.unparse(kw.value)

        return synth, pattern_value, kwargs

    def _fallback_patch(self, prompt: str, intent: str) -> list[dict[str, Any]]:
        p = prompt.lower()
        try:
            parsed = json.loads(prompt)
            if isinstance(parsed, list):
                return parsed[:12]
        except Exception:
            pass

        commands: list[dict[str, Any]] = []

        if "stop" in p or "pause" in p:
            return [{"op": "clock_clear"}]

        if "major" in p:
            commands.append(
                {"op": "set_global", "target": "Scale.default", "value": "major"}
            )
        elif "minor" in p:
            commands.append(
                {"op": "set_global", "target": "Scale.default", "value": "minor"}
            )

        if "slower" in p or "slow" in p:
            commands.append({"op": "set_global", "target": "Clock.bpm", "value": 108})
        elif "faster" in p or "fast" in p:
            commands.append({"op": "set_global", "target": "Clock.bpm", "value": 132})
        elif "bpm" in p:
            digits = "".join(ch for ch in p if ch.isdigit())
            if digits:
                bpm = max(50, min(220, int(digits)))
                commands.append(
                    {"op": "set_global", "target": "Clock.bpm", "value": bpm}
                )

        if "dark" in p or "darker" in p:
            commands.extend(
                [
                    {"op": "player_set", "player": "p1", "param": "lpf", "value": 1300},
                    {"op": "player_set", "player": "p1", "param": "amp", "value": 0.55},
                ]
            )

        if "drum" in p:
            commands.append(
                {
                    "op": "player_assign",
                    "player": "d1",
                    "synth": "play",
                    "pattern": "'x-o-'",
                    "kwargs": {"dur": 0.5, "amp": 0.8},
                }
            )

        if "new song" in p or "new scene" in p:
            commands = [
                {"op": "clock_clear"},
                {"op": "set_global", "target": "Clock.bpm", "value": 124},
                {
                    "op": "player_assign",
                    "player": "p1",
                    "synth": "pluck",
                    "pattern": "[0,2,4,7]",
                    "kwargs": {"dur": 0.25, "amp": 0.7},
                },
                {
                    "op": "player_assign",
                    "player": "d1",
                    "synth": "play",
                    "pattern": "'x-o-'",
                    "kwargs": {"dur": 0.5, "amp": 0.8},
                },
            ]

        if not commands:
            commands = [
                {
                    "op": "player_assign",
                    "player": "p1",
                    "synth": "pluck",
                    "pattern": "[0,2,4,7]",
                    "kwargs": {"dur": 0.25, "amp": 0.7},
                }
            ]

        return commands[:12]
