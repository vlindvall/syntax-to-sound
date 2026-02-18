from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, field_validator


class Intent(str, Enum):
    EDIT = "edit"
    NEW_SCENE = "new_scene"
    MIX_FIX = "mix_fix"


class SetGlobalTarget(str, Enum):
    CLOCK_BPM = "Clock.bpm"
    SCALE_DEFAULT = "Scale.default"
    ROOT_DEFAULT = "Root.default"


class PlayerParam(str, Enum):
    AMP = "amp"
    DUR = "dur"
    SUS = "sus"
    OCT = "oct"
    LPF = "lpf"
    HPF = "hpf"
    PAN = "pan"
    ROOM = "room"
    MIX = "mix"
    ECHO = "echo"
    DELAY = "delay"
    CHOP = "chop"
    SAMPLE = "sample"
    RATE = "rate"
    DETUNE = "detune"
    DRIVE = "drive"
    SHAPE = "shape"
    BLUR = "blur"
    FORMANT = "formant"
    COARSE = "coarse"
    SPIN = "spin"


ALLOWED_PLAYERS = [
    *(f"p{i}" for i in range(1, 9)),
    *(f"b{i}" for i in range(1, 5)),
    *(f"d{i}" for i in range(1, 5)),
    *(f"n{i}" for i in range(1, 5)),
]


class SetGlobalCommand(BaseModel):
    op: Literal["set_global"]
    target: SetGlobalTarget
    value: int | float | str


class PlayerAssignCommand(BaseModel):
    op: Literal["player_assign"]
    player: str
    synth: str = Field(min_length=1, max_length=32)
    pattern: str = Field(min_length=1, max_length=256)
    kwargs: dict[str, int | float | str | bool] = Field(default_factory=dict)

    @field_validator("player")
    @classmethod
    def validate_player(cls, v: str) -> str:
        if v not in ALLOWED_PLAYERS:
            raise ValueError(f"player {v} is not allowed")
        return v


class PlayerSetCommand(BaseModel):
    op: Literal["player_set"]
    player: str
    param: PlayerParam
    value: int | float | str

    @field_validator("player")
    @classmethod
    def validate_player(cls, v: str) -> str:
        if v not in ALLOWED_PLAYERS:
            raise ValueError(f"player {v} is not allowed")
        return v


class PlayerStopCommand(BaseModel):
    op: Literal["player_stop"]
    player: str

    @field_validator("player")
    @classmethod
    def validate_player(cls, v: str) -> str:
        if v not in ALLOWED_PLAYERS:
            raise ValueError(f"player {v} is not allowed")
        return v


class ClockClearCommand(BaseModel):
    op: Literal["clock_clear"]


PatchCommand = Annotated[
    Union[
        SetGlobalCommand,
        PlayerAssignCommand,
        PlayerSetCommand,
        PlayerStopCommand,
        ClockClearCommand,
    ],
    Field(discriminator="op"),
]


class ChatTurnRequest(BaseModel):
    session_id: str
    prompt: str = Field(min_length=1, max_length=2000)
    intent: Intent = Intent.EDIT


class RuntimeLoadSongRequest(BaseModel):
    path: str


class PatchApplyRequest(BaseModel):
    patch_id: int


class PatchUndoRequest(BaseModel):
    session_id: str


class BootResponse(BaseModel):
    status: Literal["ready", "starting", "error"]
    session_id: str


class ValidationReport(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)


class PatchEnvelope(BaseModel):
    commands: list[PatchCommand]

    @field_validator("commands")
    @classmethod
    def validate_limits(cls, v: list[PatchCommand]) -> list[PatchCommand]:
        if len(v) > 12:
            raise ValueError("at most 12 commands are allowed per turn")
        return v
