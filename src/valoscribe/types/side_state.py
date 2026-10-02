"""Evidence-backed, match-contextual broadcast side state."""

from __future__ import annotations

import math
from enum import Enum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from valoscribe.types.persistent import PersistentModel, Side, _require_identifier


class HalfState(str, Enum):
    FIRST = "first"
    SECOND = "second"
    OVERTIME = "overtime"
    UNKNOWN = "unknown"


class TeamSideEvidence(PersistentModel):
    """Per-match team identity, first-half anchor, and current HUD color evidence."""

    schema_version: Literal["1.0"] = "1.0"
    team_id: str = Field(min_length=1)
    first_half_side: Side
    side_confidence: float = Field(ge=0.0, le=1.0)
    side_evidence: list[str] = Field(min_length=1)
    overtime_starting_side: Side | None = None
    overtime_side_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    overtime_side_evidence: list[str] = Field(default_factory=list)
    broadcast_color: str | None = None
    color_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    color_evidence: list[str] = Field(default_factory=list)

    @field_validator("team_id")
    @classmethod
    def team_id_not_blank(cls, value: str) -> str:
        return _require_identifier(value, "team_id")

    @field_validator("broadcast_color")
    @classmethod
    def color_not_blank(cls, value: str | None) -> str | None:
        return None if value is None else _require_identifier(value, "broadcast_color")

    @field_validator("side_confidence", "overtime_side_confidence", "color_confidence")
    @classmethod
    def confidences_are_finite(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("confidence must be finite")
        return value

    @field_validator("side_evidence", "overtime_side_evidence", "color_evidence")
    @classmethod
    def evidence_not_blank(cls, values: list[str]) -> list[str]:
        return [_require_identifier(value, "evidence") for value in values]

    @model_validator(mode="after")
    def overtime_evidence_is_complete(self) -> TeamSideEvidence:
        supplied = (
            self.overtime_starting_side is not None,
            self.overtime_side_confidence is not None,
            bool(self.overtime_side_evidence),
        )
        if any(supplied) and not all(supplied):
            raise ValueError("overtime side, confidence, and evidence must be supplied together")
        if self.overtime_starting_side not in (None, Side.ATTACK, Side.DEFENSE):
            raise ValueError("overtime starting side must be attack or defense")
        return self


class TeamSideState(PersistentModel):
    """Resolved or explicitly unknown side for one team and round."""

    schema_version: Literal["1.0"] = "1.0"
    round_number: int = Field(ge=1)
    half: HalfState
    team_id: str = Field(min_length=1)
    broadcast_color: str | None = None
    side: Side
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    rejection_reason: str | None = None

    @field_validator("team_id")
    @classmethod
    def team_id_not_blank(cls, value: str) -> str:
        return _require_identifier(value, "team_id")

    @field_validator("confidence")
    @classmethod
    def confidence_is_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("confidence must be finite")
        return value

    @field_validator("broadcast_color", "rejection_reason")
    @classmethod
    def optional_strings_not_blank(cls, value: str | None) -> str | None:
        return None if value is None else _require_identifier(value, "value")

    @field_validator("evidence")
    @classmethod
    def evidence_not_blank(cls, values: list[str]) -> list[str]:
        return [_require_identifier(value, "evidence") for value in values]
