"""Persisted MVP run, raw marker, and per-sample coverage contracts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RawMarkerObservation(Contract):
    run_id: str
    round_id: str
    sample_index: int = Field(ge=0)
    source_frame_index: int | None = Field(default=None, ge=0)
    source_timestamp_seconds: float = Field(ge=0)
    crop_x: float
    crop_y: float
    canonical_x: float | None = None
    canonical_y: float | None = None
    confidence: float = Field(ge=0, le=1)
    detector_version: str
    quality_flags: list[str] = Field(default_factory=list)


class TeamFrameState(Contract):
    """One sampled frame, including explicit zero-candidate and excluded states."""

    run_id: str
    round_id: str
    sample_index: int = Field(ge=0)
    source_timestamp_seconds: float = Field(ge=0)
    observed_marker_count: int = Field(ge=0)
    coverage_status: Literal["good", "partial", "unknown", "excluded"]
    warning: str | None = None


class RunManifest(Contract):
    schema_version: Literal[1] = 1
    run_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    project_commit: str
    source_identifier: str
    source_video_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_dimensions: tuple[int, int]
    configuration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    map_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    code_version: str
    sample_fps: float
    round_ids: list[str]
    output_paths: dict[str, str]
    warnings: list[str] = Field(default_factory=list)
