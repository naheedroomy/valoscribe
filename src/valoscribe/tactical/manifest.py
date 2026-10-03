"""Typed contracts and loaders for VOD round manifests and broadcast profiles."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from valoscribe.tactical.config import CropConfig, HSVRange, StrictModel, TransformConfig


class ExcludedSpan(StrictModel):
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def interval_ordered(self) -> ExcludedSpan:
        if self.end_seconds <= self.start_seconds:
            raise ValueError("end_seconds must be greater than start_seconds")
        return self


class TeamManifestDefinition(StrictModel):
    team_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    starting_side: Literal["attack", "defense"]
    broadcast_slot: str = Field(min_length=1)
    broadcast_color_label: str = Field(min_length=1)


class RoundManifestEntry(StrictModel):
    map_round: int = Field(ge=1)
    round_id: str = Field(min_length=1)
    source_start_seconds: float = Field(ge=0)
    source_end_seconds: float = Field(gt=0)
    live_start_seconds: float = Field(ge=0)
    status: Literal["confirmed", "unresolved", "missing", "excluded"] = "confirmed"
    team_sides: dict[str, Literal["attack", "defense"]] = Field(default_factory=dict)
    boundary_evidence: str = Field(default="")
    excluded_spans: list[ExcludedSpan] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_round_intervals(self) -> RoundManifestEntry:
        if self.source_end_seconds <= self.source_start_seconds:
            raise ValueError("end_seconds must be greater than start_seconds")
        if not (self.source_start_seconds <= self.live_start_seconds <= self.source_end_seconds):
            raise ValueError(
                "live_start_seconds must fall within round interval "
                f"[{self.source_start_seconds}, {self.source_end_seconds}]"
            )
        for span in self.excluded_spans:
            if (
                span.start_seconds < self.source_start_seconds
                or span.end_seconds > self.source_end_seconds
            ):
                raise ValueError(
                    "excluded span must fall within round interval "
                    f"[{self.source_start_seconds}, {self.source_end_seconds}]"
                )
        return self


class VODRoundManifest(StrictModel):
    schema_version: int = 1
    source_video_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    match_id: str = Field(min_length=1)
    map_id: str = Field(min_length=1)
    map_name: str = Field(min_length=1)
    teams: dict[str, TeamManifestDefinition]
    halftime_after_round: int = 12
    rounds: list[RoundManifestEntry] = Field(default_factory=list)
    reviewer: str = Field(min_length=1)
    review_method: str = "manual"
    notes: str | None = None

    @model_validator(mode="after")
    def validate_manifest(self) -> VODRoundManifest:
        round_numbers = [r.map_round for r in self.rounds]
        if len(round_numbers) != len(set(round_numbers)):
            raise ValueError("round numbers must be unique")
        round_ids = [r.round_id for r in self.rounds]
        if len(round_ids) != len(set(round_ids)):
            raise ValueError("round IDs must be unique")
        for r in self.rounds:
            for team_id in r.team_sides:
                if team_id not in self.teams:
                    raise ValueError(
                        f"round {r.map_round} references unknown team "
                        f"{team_id!r} not in manifest teams"
                    )
        return self


class TeamColorCalibration(StrictModel):
    team_id: str = Field(min_length=1)
    color_ranges_hsv: list[HSVRange] = Field(min_length=1)


class VODBroadcastProfile(StrictModel):
    profile_id: str = Field(min_length=1)
    calibration_status: str = Field(min_length=1)
    minimap_crop: CropConfig
    transform: TransformConfig
    team_calibrations: dict[str, TeamColorCalibration] = Field(default_factory=dict)


def load_manifest(path: Path) -> VODRoundManifest:
    raw = path.read_bytes()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(f"manifest must be valid JSON: {error}") from error
    return VODRoundManifest.model_validate(data)


def load_profile(path: Path) -> VODBroadcastProfile:
    raw = path.read_bytes()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(f"profile must be valid JSON: {error}") from error
    return VODBroadcastProfile.model_validate(data)
