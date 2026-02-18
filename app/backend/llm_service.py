from __future__ import annotations

import json
import os
from typing import Any


SYSTEM_PROMPT = """You are an AI DJ assistant for Renardo live coding.
Return ONLY JSON with this shape: {\"commands\": [PatchCommand, ...]}.
Never return Python code, markdown, or prose.
Allowed PatchCommand ops: set_global, player_assign, player_set, player_stop, clock_clear.
Keep commands short, musical, and safe. Max 12 commands.
"""


class LLMService:
    def __init__(self) -> None:
        self.api_key = os.getenv("OPENAI_API_KEY", "")
        self.model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

    async def generate_patch(
        self,
        prompt: str,
        intent: str,
        state: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], str]:
        if not self.api_key:
            return self._fallback_patch(prompt, intent), "fallback-local"

        try:
            from openai import AsyncOpenAI
        except Exception:
            return self._fallback_patch(prompt, intent), "fallback-local"

        client = AsyncOpenAI(api_key=self.api_key)
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

        response = await client.responses.create(
            model=self.model,
            temperature=0.3,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(user_content)},
            ],
            text={"format": {"type": "json_object"}},
        )

        text = response.output_text
        payload = json.loads(text)
        commands = payload.get("commands", [])
        if not isinstance(commands, list):
            raise ValueError("model returned invalid commands payload")
        return commands, self.model

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
