from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ASSIGN_PATTERN_PARAMS = {"pattern", "degree", "note"}
ASSIGN_KWARG_PARAMS = {"dur", "oct", "amp", "lpf", "hpf", "pan", "room", "mix"}


@dataclass
class PendingAssign:
    player: str
    synth: str | None = None
    pattern: str | None = None
    kwargs: dict[str, Any] = field(default_factory=dict)


def normalize_commands(raw_commands: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    normalized: list[dict[str, Any]] = []
    notes: list[str] = []
    pending: dict[str, PendingAssign] = {}
    pending_order: list[str] = []

    def get_pending(player: str) -> PendingAssign:
        if player not in pending:
            pending[player] = PendingAssign(player=player)
            pending_order.append(player)
        return pending[player]

    for i, raw in enumerate(raw_commands):
        if not isinstance(raw, dict):
            notes.append(f"Dropped command #{i + 1}: expected object, got {type(raw).__name__}")
            continue

        command = dict(raw)
        op = command.get("op")

        if op == "set_global" and command.get("param") == "bpm" and "target" not in command:
            repaired = {
                "op": "set_global",
                "target": "Clock.bpm",
                "value": command.get("value", 120),
            }
            normalized.append(repaired)
            notes.append(f"Repaired command #{i + 1}: set_global.param=bpm -> target=Clock.bpm")
            continue

        if op == "player_assign":
            player = command.get("player")
            if not isinstance(player, str):
                notes.append(f"Dropped command #{i + 1}: player_assign missing valid player")
                continue

            synth = command.get("synth")
            if not synth and isinstance(command.get("value"), str):
                synth = command["value"]
                notes.append(f"Repaired command #{i + 1}: player_assign.value -> synth")

            pattern = command.get("pattern")
            kwargs = command.get("kwargs")
            kwargs_payload = kwargs if isinstance(kwargs, dict) else {}

            if isinstance(synth, str) and isinstance(pattern, str):
                repaired_assign = {
                    "op": "player_assign",
                    "player": player,
                    "synth": synth,
                    "pattern": pattern,
                    "kwargs": kwargs_payload,
                }
                normalized.append(repaired_assign)
                continue

            if isinstance(synth, str):
                acc = get_pending(player)
                acc.synth = acc.synth or synth
                if isinstance(pattern, str):
                    acc.pattern = pattern
                if kwargs_payload:
                    acc.kwargs.update(kwargs_payload)
                notes.append(
                    f"Queued malformed player_assign for {player} and waiting for missing pattern/kwargs"
                )
                continue

            notes.append(f"Dropped command #{i + 1}: player_assign missing usable synth")
            continue

        if op == "player_set":
            player = command.get("player")
            param = command.get("param")
            value = command.get("value")

            if param == "cutoff":
                command["param"] = "lpf"
                param = "lpf"
                notes.append(f"Repaired command #{i + 1}: player_set.param cutoff -> lpf")

            if isinstance(player, str) and player in pending and isinstance(param, str):
                acc = pending[player]
                if param in ASSIGN_PATTERN_PARAMS:
                    acc.pattern = str(value)
                    notes.append(f"Folded command #{i + 1}: {player}.{param} into player_assign.pattern")
                    continue
                if param in ASSIGN_KWARG_PARAMS:
                    acc.kwargs[param] = value
                    notes.append(f"Folded command #{i + 1}: {player}.{param} into player_assign.kwargs")
                    continue

            normalized.append(command)
            continue

        normalized.append(command)

    for player in pending_order:
        acc = pending[player]
        if not acc.synth:
            notes.append(f"Dropped pending assign for {player}: missing synth")
            continue

        pattern = acc.pattern
        if not pattern:
            pattern = "[0]"
            notes.append(f"Applied default pattern for {player}: [0]")

        assign_cmd: dict[str, Any] = {
            "op": "player_assign",
            "player": player,
            "synth": acc.synth,
            "pattern": pattern,
            "kwargs": acc.kwargs,
        }
        normalized.append(assign_cmd)
        notes.append(f"Synthesized player_assign for {player} from malformed command group")

    return normalized, notes
