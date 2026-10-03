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


class CorrectionDelta(Contract):
    """One immutable add/remove/move record against a stable marker identifier."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    correction_id: str
    run_id: str
    round_id: str
    sample_index: int = Field(ge=0)
    operation: Literal["add", "remove", "move"]
    target_observation_id: str | None = None
    original_canonical_x: float | None = None
    original_canonical_y: float | None = None
    corrected_canonical_x: float | None = None
    corrected_canonical_y: float | None = None
    confidence: float = Field(default=1.0, ge=0, le=1)
    reviewer: str = Field(min_length=1)
    note: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ReviewedFrame(Contract):
    """Inspection record; approval is explicit and defaults false for old records."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    round_id: str
    sample_index: int = Field(ge=0)
    reviewer: str = Field(min_length=1)
    approved: bool = False
    note: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RoundMovementSummary(Contract):
    run_id: str
    round_id: str
    selected_team: str
    side: str
    source_interval_seconds: tuple[float, float]
    live_start_seconds: float
    usable_time_seconds: float = Field(ge=0)
    opening_distribution: dict[str, int] | None
    opening_observed_samples: int = Field(ge=0)
    opening_sample_denominator: int = Field(ge=0)
    opening_confidence: str
    opening_completeness: Literal["unknown", "affirmed"]
    opening_evidence: dict = Field(default_factory=dict)
    first_major_shift_time: float | None = None
    first_major_shift_direction: str | None = None
    first_major_shift_evidence: dict | None = None
    regroup_direction: str | None = None
    regroup_evidence: dict | None = None
    apparent_commitment_site: str | None = None
    apparent_commitment_time: float | None = None
    commitment_evidence: dict | None = None
    opposite_side_presence: Literal["present", "not_observed", "unknown"]
    opposite_side_evidence: list[dict] = Field(default_factory=list)
    representative_timestamps: list[dict] = Field(default_factory=list)
    unknown_intervals: list[dict] = Field(default_factory=list)
    coverage_numerator: int = Field(ge=0)
    coverage_denominator: int = Field(ge=0)
    warnings: list[str] = Field(default_factory=list)
    rule_configuration: dict = Field(default_factory=dict)
    evidence_paths: dict[str, str] = Field(default_factory=dict)
    artifacts: dict[str, str] = Field(default_factory=dict)


class AggregateMovementSummary(Contract):
    run_id: str
    included_rounds: list[str]
    excluded_rounds: list[str]
    opening_pattern_counts: dict[str, int]
    apparent_commitment_counts: dict[str, int]
    regroup_direction_counts: dict[str, int]
    opposite_side_presence_counts: dict[str, int]
    approximate_commitment_time_distribution: dict[str, int]
    recurring_patterns: list[dict]
    representative_rounds: list[dict]
    feature_unknown_round_ids: list[str]
    feature_unknown_by_feature: dict[str, list[str]]
    correction_counts_by_round: dict[str, int]
    consumed_round_revisions: dict[str, str] = Field(default_factory=dict)
    pattern_denominators: dict[str, int]
    limitations: list[str]


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
