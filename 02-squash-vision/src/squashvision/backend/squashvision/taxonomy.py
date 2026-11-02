from __future__ import annotations

from enum import StrEnum


class ShotKind(StrEnum):
    UNKNOWN = "unknown"
    SERVE = "serve"
    DRIVE = "drive"
    BOAST = "boast"
    DROP = "drop"
    LOB = "lob"
    KILL = "kill"


class ShotOutcomeKind(StrEnum):
    UNKNOWN = "unknown"
    IN_PLAY = "in_play"
    WINNER = "winner"
    ERROR = "error"
    STROKE = "stroke"
    LET = "let"


_SHOT_TYPE_ALIASES = {
    "straight_drive": ShotKind.DRIVE,
    "crosscourt_drive": ShotKind.DRIVE,
}
_OUTCOME_ALIASES = {
    "continuation": ShotOutcomeKind.IN_PLAY,
    "continues": ShotOutcomeKind.IN_PLAY,
    "terminal": ShotOutcomeKind.UNKNOWN,
}


def canonical_shot_kind(value: object) -> ShotKind:
    raw = str(getattr(value, "value", value))
    try:
        return ShotKind(raw)
    except ValueError:
        return _SHOT_TYPE_ALIASES.get(raw, ShotKind.UNKNOWN)


def canonical_shot_outcome(value: object) -> ShotOutcomeKind:
    raw = str(getattr(value, "value", value))
    try:
        return ShotOutcomeKind(raw)
    except ValueError:
        return _OUTCOME_ALIASES.get(raw, ShotOutcomeKind.UNKNOWN)
