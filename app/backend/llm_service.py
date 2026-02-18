from __future__ import annotations

import asyncio
import ast
import json
import os
import re
import shlex
import shutil
from typing import Any


SYSTEM_PROMPT = """You are an AI DJ assistant for Renardo live coding.
Return ONLY JSON with this shape: {\"commands\": [PatchCommand, ...]}.
Never return Python code, markdown, or prose.
Allowed PatchCommand ops: set_global, player_assign, player_set, player_stop, clock_clear.
For player_set, valid params include: amp, dur, sus, oct, lpf, hpf, pan, room, mix, echo, delay, chop, sample, rate, detune, drive, shape, blur, formant, coarse, spin.
Keep commands short, musical, and safe. Max 12 commands.
"""


class LLMService:
    def __init__(self) -> None:
        self.backend = os.getenv("AI_DJ_LLM_BACKEND", "auto").strip().lower()
        self.api_key = os.getenv("OPENAI_API_KEY", "")
        self.model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        codex_command = os.getenv("CODEX_CLI_COMMAND", "codex exec")
        self.codex_command = shlex.split(codex_command) if codex_command.strip() else []
        self.codex_model = os.getenv("CODEX_MODEL", self.model)
        self.codex_available = bool(self.codex_command) and shutil.which(self.codex_command[0]) is not None

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

        backend = self._resolve_backend()
        try:
            if backend == "openai-api":
                return await self._generate_openai(user_content)
            if backend == "codex-cli":
                return await self._generate_codex_cli(user_content)
        except Exception:
            if self.backend != "auto":
                raise
            return self._fallback_patch(prompt, intent), "fallback-local"

        return self._fallback_patch(prompt, intent), "fallback-local"

    def _resolve_backend(self) -> str:
        if self.backend in {"openai-api", "codex-cli"}:
            return self.backend
        if self.api_key:
            return "openai-api"
        if self.codex_available:
            return "codex-cli"
        return "fallback-local"

    async def _generate_openai(self, user_content: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is required for openai-api backend")
        try:
            from openai import AsyncOpenAI
        except Exception as exc:
            raise RuntimeError("openai package is unavailable") from exc

        client = AsyncOpenAI(api_key=self.api_key)

        response = await client.responses.create(
            model=self.model,
            temperature=0.3,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(user_content)},
            ],
            text={"format": {"type": "json_object"}},
        )

        commands = self._extract_commands(response.output_text)
        return commands, self.model

    async def _generate_codex_cli(self, user_content: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
        if not self.codex_command:
            raise ValueError("CODEX_CLI_COMMAND is empty")
        if not self.codex_available:
            raise RuntimeError(f"codex CLI binary not found: {self.codex_command[0]}")

        prompt = (
            f"{SYSTEM_PROMPT}\n\n"
            "Return ONLY JSON.\n\n"
            f"{json.dumps(user_content)}"
        )
        process = await asyncio.create_subprocess_exec(
            *self.codex_command,
            "--model",
            self.codex_model,
            prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise RuntimeError(
                f"codex CLI failed with exit code {process.returncode}: {stderr.decode().strip()}"
            )
        output = stdout.decode().strip()
        commands = self._extract_commands(output)
        return commands, f"codex-cli:{self.codex_model}"

    def _extract_commands(self, text: str) -> list[dict[str, Any]]:
        payload = self._extract_json_payload(text)
        if isinstance(payload, list):
            commands = payload
        elif isinstance(payload, dict):
            commands = payload.get("commands", [])
        else:
            raise ValueError("model returned a non-JSON payload")
        if not isinstance(commands, list):
            raise ValueError("model returned invalid commands payload")
        return self._normalize_commands(commands)

    def _extract_json_payload(self, text: str) -> Any:
        stripped = text.strip()
        if not stripped:
            raise ValueError("model returned empty output")
        try:
            return json.loads(stripped)
        except Exception:
            pass

        decoder = json.JSONDecoder()
        for idx, ch in enumerate(stripped):
            if ch not in "{[":
                continue
            try:
                value, _ = decoder.raw_decode(stripped[idx:])
                return value
            except Exception:
                continue
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
                target = command.get("target")
                if target is None:
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
        if node.args:
            pattern_value = ast.unparse(node.args[0])
        else:
            pattern_value = "[0,2,4,7]"

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
