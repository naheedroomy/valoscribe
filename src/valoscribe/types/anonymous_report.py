"""Typed inputs and summaries for the anonymous diagnostic round CLI."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from valoscribe.types.anonymous_tracking import (
    AnonymousFrameContext,
    AnonymousRoundBounds,
)


class AnonymousRoundInput(BaseModel):
    """Externally reviewed round boundaries and whichever frame contexts were reviewed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    bounds: AnonymousRoundBounds
    context_by_frame: tuple[AnonymousFrameContext, ...] = ()

    @model_validator(mode="after")
    def contexts_bind_to_unique_frames(self) -> AnonymousRoundInput:
        frame_indices = [context.frame_index for context in self.context_by_frame]
        if len(frame_indices) != len(set(frame_indices)):
            raise ValueError("reviewed context contains duplicate frame indices")
        if any(
            not self.bounds.start_frame_index <= index <= self.bounds.end_frame_index
            for index in frame_indices
        ):
            raise ValueError("reviewed context frame is outside externally reviewed bounds")
        return self


class AnonymousConfidenceRange(BaseModel):
    """Observed detector or adjacent-association confidence range."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    minimum: float = Field(ge=0, le=1)
    maximum: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def ordered_and_finite(self) -> AnonymousConfidenceRange:
        if not math.isfinite(self.minimum) or not math.isfinite(self.maximum):
            raise ValueError("confidence range must be finite")
        if self.maximum < self.minimum:
            raise ValueError("confidence range is reversed")
        return self


class AnonymousDiagnosticReport(BaseModel):
    """Evidence inventory; deliberately excludes identities and tactical conclusions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    report_kind: Literal["anonymous_minimap_diagnostic"] = "anonymous_minimap_diagnostic"
    inference_scope: Literal["diagnostic_tracklet_only"] = "diagnostic_tracklet_only"
    run_id: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    source_video_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    map_id: str = Field(min_length=1)
    map_number: int = Field(gt=0)
    round_number: int = Field(gt=0)
    start_frame_index: int = Field(ge=0)
    end_frame_index: int = Field(ge=0)
    start_source_pts: int = Field(ge=0)
    end_source_pts: int = Field(ge=0)
    timebase_numerator: int = Field(gt=0)
    timebase_denominator: int = Field(gt=0)
    requested_frame_count: int = Field(gt=0)
    decoded_frame_count: int = Field(ge=0)
    context_live_frame_count: int = Field(ge=0)
    context_nonlive_frame_count: int = Field(ge=0)
    context_unknown_frame_count: int = Field(ge=0)
    candidate_count: int = Field(ge=0)
    accepted_candidate_count: int = Field(ge=0)
    rejected_candidate_count: int = Field(ge=0)
    observed_sample_count: int = Field(ge=0)
    anonymous_tracklet_count: int = Field(ge=0)
    frames_without_tracklet_sample: int = Field(ge=0)
    detector_confidence: AnonymousConfidenceRange | None
    association_confidence: AnonymousConfidenceRange | None
    hud_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    color_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    map_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    map_asset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifacts: dict[str, str]
    player_identity: Literal["unavailable"] = "unavailable"
    canonical_map_coordinates: Literal["unavailable"] = "unavailable"
    tactical_claims: Literal["not_made"] = "not_made"
    quality_metrics: Literal["unavailable_without_independent_ground_truth"] = (
        "unavailable_without_independent_ground_truth"
    )

    @model_validator(mode="after")
    def count_consistency(self) -> AnonymousDiagnosticReport:
        if self.end_frame_index < self.start_frame_index:
            raise ValueError("report frame bounds are reversed")
        if self.end_source_pts < self.start_source_pts:
            raise ValueError("report source PTS bounds are reversed")
        if self.decoded_frame_count != self.requested_frame_count:
            raise ValueError("diagnostic report requires complete reviewed frame coverage")
        context_total = (
            self.context_live_frame_count
            + self.context_nonlive_frame_count
            + self.context_unknown_frame_count
        )
        if context_total != self.decoded_frame_count:
            raise ValueError("context counts do not add up to decoded frame count")
        if self.candidate_count != self.accepted_candidate_count + self.rejected_candidate_count:
            raise ValueError("candidate counts do not add up")
        if self.observed_sample_count > self.accepted_candidate_count:
            raise ValueError("tracklet samples exceed accepted raw candidates")
        return self
