from __future__ import annotations

import ast
from typing import Any

from pydantic import ValidationError

from app.shared.contracts import PatchCommand, PatchEnvelope

ALLOWED_AST_NODES: tuple[type[ast.AST], ...] = (
    ast.Module,
    ast.Assign,
    ast.Expr,
    ast.Name,
    ast.Load,
    ast.Store,
    ast.Constant,
    ast.Call,
    ast.BinOp,
    ast.UnaryOp,
    ast.List,
    ast.Tuple,
    ast.Dict,
    ast.Subscript,
    ast.Attribute,
    ast.Slice,
    ast.Index,
    ast.keyword,
    ast.Mult,
    ast.RShift,
    ast.Add,
    ast.Sub,
    ast.Div,
    ast.Pow,
    ast.USub,
    ast.UAdd,
)

FORBIDDEN_TOKENS = {
    "import",
    "open(",
    "exec(",
    "eval(",
    "__",
    "subprocess",
    "os.",
    "sys.",
    "socket",
    "requests",
}


class SafetyError(Exception):
    pass


def validate_commands(raw_commands: list[dict[str, Any]]) -> list[PatchCommand]:
    envelope = PatchEnvelope(commands=raw_commands)
    return envelope.commands


def _to_literal(value: Any) -> str:
    if isinstance(value, str):
        return repr(value)
    return str(value)


def _to_pattern_expr(pattern: str) -> str:
    source = pattern.strip()
    if not source:
        return repr(pattern)
    try:
        ast.parse(source, mode="eval")
        return source
    except SyntaxError:
        return repr(pattern)


def emit_python(commands: list[PatchCommand]) -> str:
    lines: list[str] = []
    for command in commands:
        op = command.op
        if op == "set_global":
            lines.append(f"{command.target.value} = {_to_literal(command.value)}")
        elif op == "player_assign":
            pattern_expr = _to_pattern_expr(command.pattern)
            kwargs = ", ".join(
                f"{k}={_to_literal(v)}" for k, v in sorted(command.kwargs.items())
            )
            if kwargs:
                lines.append(
                    f"{command.player} >> {command.synth}({pattern_expr}, {kwargs})"
                )
            else:
                lines.append(f"{command.player} >> {command.synth}({pattern_expr})")
        elif op == "player_set":
            lines.append(
                f"{command.player}.{command.param.value} = {_to_literal(command.value)}"
            )
        elif op == "player_stop":
            lines.append(f"{command.player}.stop()")
        elif op == "clock_clear":
            lines.append("Clock.clear()")
        else:
            raise SafetyError(f"unsupported operation: {op}")
    emitted = "\n".join(lines)
    validate_emitted_python(emitted)
    return emitted


def validate_emitted_python(source: str) -> None:
    lowered = source.lower()
    for token in FORBIDDEN_TOKENS:
        if token in lowered:
            raise SafetyError(f"forbidden token found in emitted source: {token}")

    tree = ast.parse(source, mode="exec")
    for node in ast.walk(tree):
        if not isinstance(node, ALLOWED_AST_NODES):
            raise SafetyError(f"forbidden AST node: {type(node).__name__}")

        if isinstance(node, ast.Attribute):
            attr = node.attr
            if attr.startswith("__"):
                raise SafetyError("dunder attribute access is forbidden")

        if isinstance(node, ast.Name):
            if node.id.startswith("__"):
                raise SafetyError("dunder names are forbidden")


def validate_and_emit(raw_commands: list[dict[str, Any]]) -> tuple[list[PatchCommand], str, list[str]]:
    errors: list[str] = []
    try:
        commands = validate_commands(raw_commands)
    except ValidationError as exc:
        errors.extend(err["msg"] for err in exc.errors())
        return [], "", errors
    except Exception as exc:  # pragma: no cover
        return [], "", [str(exc)]

    try:
        emitted = emit_python(commands)
    except SafetyError as exc:
        errors.append(str(exc))
        return [], "", errors

    return commands, emitted, errors
