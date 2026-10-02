"""Typed loading and validation for the tactical MVP configuration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceConfig(StrictModel):
    video_path: Path
    expected_width: int = Field(gt=0)
    expected_height: int = Field(gt=0)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class MapConfig(StrictModel):
    id: str
    canonical_width: int = Field(gt=0)
    canonical_height: int = Field(gt=0)
    asset_path: Path
    asset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    zone_config: Path


class CropConfig(StrictModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    orientation: str = "identity"


class TransformConfig(StrictModel):
    method: str
    input_coordinates: str
    output_coordinates: str
    matrix: list[list[float]] = Field(min_length=2, max_length=2)
    training_points: int = Field(ge=0)
    training_residual_mean_rms_max_px: list[float] = Field(min_length=3, max_length=3)
    heldout_max_px: dict[str, float] = Field(default_factory=dict)
    calibration_status: str

    @model_validator(mode="after")
    def matrix_is_affine_2_by_3(self) -> TransformConfig:
        if any(len(row) != 3 for row in self.matrix):
            raise ValueError("affine transform matrix must have two rows and three columns")
        return self


class HSVRange(StrictModel):
    lower: tuple[int, int, int]
    upper: tuple[int, int, int]

    @model_validator(mode="after")
    def bounds_are_valid(self) -> HSVRange:
        if any(low > high for low, high in zip(self.lower, self.upper)):
            raise ValueError("HSV lower bounds must not exceed upper bounds")
        if not 0 <= self.lower[0] <= 179 or not 0 <= self.upper[0] <= 179:
            raise ValueError("HSV hue bounds must be in [0, 179]")
        if any(not 0 <= v <= 255 for v in (*self.lower[1:], *self.upper[1:])):
            raise ValueError("HSV saturation/value bounds must be in [0, 255]")
        return self


class BroadcastConfig(StrictModel):
    profile_id: str
    calibration_status: str
    minimap_crop: CropConfig
    transform: TransformConfig
    color_ranges_hsv_candidate_only: list[HSVRange] = Field(min_length=1)


class TeamConfig(StrictModel):
    name: str
    short_name: str
    side: str
    side_evidence: str
    broadcast_slot: str
    broadcast_color_label: str


class DetectorConfig(StrictModel):
    status: str
    min_area_px: float = Field(gt=0)
    max_area_px: float = Field(gt=0)
    min_confidence: float = Field(ge=0, le=1)
    morphology_kernel_px: int = Field(ge=1)
    merge_distance_px: float = Field(ge=0)
    min_circularity: float = Field(default=0.12, ge=0, le=1)
    min_aspect_ratio: float = Field(default=0.32, ge=0, le=1)
    max_contour_samples: int = Field(default=24, ge=0)

    @model_validator(mode="after")
    def area_ordered(self) -> DetectorConfig:
        if self.max_area_px < self.min_area_px:
            raise ValueError("max_area_px must be >= min_area_px")
        if self.morphology_kernel_px % 2 == 0:
            raise ValueError("morphology_kernel_px must be odd")
        return self


class ExcludedInterval(StrictModel):
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def interval_is_ordered(self) -> ExcludedInterval:
        if self.end_seconds <= self.start_seconds:
            raise ValueError("excluded interval end must follow start")
        return self


class RoundConfig(StrictModel):
    round_id: str
    source_start_seconds: float = Field(ge=0)
    source_end_seconds: float = Field(gt=0)
    side: str
    live_start_offset_seconds: float = Field(default=0, ge=0)
    analysis_end_offset_seconds: float | None = None
    selection_note: str
    excluded_intervals: list[ExcludedInterval] = Field(default_factory=list)

    @model_validator(mode="after")
    def interval_is_valid(self) -> RoundConfig:
        if self.source_end_seconds <= self.source_start_seconds:
            raise ValueError("round end must follow start")
        if self.live_start_offset_seconds >= (self.source_end_seconds - self.source_start_seconds):
            raise ValueError("live start offset must fall inside the round interval")
        for excluded in self.excluded_intervals:
            if (
                excluded.end_seconds <= self.source_start_seconds
                or excluded.start_seconds >= self.source_end_seconds
            ):
                continue
            if (
                excluded.start_seconds < self.source_start_seconds
                or excluded.end_seconds > self.source_end_seconds
            ):
                raise ValueError("excluded interval must be contained within round interval")
        return self


class RunConfig(StrictModel):
    run_id: str
    description: str
    sample_fps: float = Field(gt=0, le=5)
    output_root: Path
    debug_level: str
    opening_window_seconds: float = Field(ge=6, le=10)
    opening_window_definition: str


class TacticalConfig(StrictModel):
    schema_version: int = 1
    run: RunConfig
    source: SourceConfig
    map: MapConfig
    broadcast: BroadcastConfig
    team: TeamConfig
    marker_detection: DetectorConfig
    rounds: list[RoundConfig] = Field(min_length=1)
    excluded_rounds: list[dict[str, Any]] = Field(default_factory=list)
    evidence_paths: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def round_ids_unique(self) -> TacticalConfig:
        ids = [round_config.round_id for round_config in self.rounds]
        if len(ids) != len(set(ids)):
            raise ValueError("round IDs must be unique")
        crop = self.broadcast.minimap_crop
        if (
            crop.x + crop.width > self.source.expected_width
            or crop.y + crop.height > self.source.expected_height
        ):
            raise ValueError("minimap crop exceeds configured source dimensions")
        return self


def load_config(path: Path) -> tuple[TacticalConfig, bytes]:
    """Load JSON-compatible YAML; JSON is a valid YAML subset and avoids new deps."""
    raw = path.read_bytes()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError("config must be JSON-compatible YAML (valid JSON syntax)") from error
    config = TacticalConfig.model_validate(data)
    return config, raw


def load_map_config(path: Path) -> dict[str, Any]:
    """Read the JSON-compatible YAML map regions without moving map thresholds into code."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("map_id") != "ascent" or not isinstance(data.get("zones"), list):
        raise ValueError("map config must define Ascent zones")
    for zone in data["zones"]:
        if not zone.get("zone_id") or len(zone.get("vertices_px", [])) < 3:
            raise ValueError("each zone needs an id and at least three vertices")
        if zone.get("macro_group") not in {"A", "MID", "B", "SPAWN"}:
            raise ValueError("each zone needs a supported macro group")
    return cast(dict[str, Any], data)
