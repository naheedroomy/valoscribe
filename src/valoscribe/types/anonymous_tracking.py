"""Diagnostic-only contracts for anonymous, crop-frame round tracklets."""

from __future__ import annotations

import math
from fractions import Fraction
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from valoscribe.types.persistent import RawMinimapColorCandidate
from valoscribe.types.tracking_provenance import TrackingObservationProvenance, TrackingRunManifest

_SHA256 = r"^[0-9a-f]{64}$"


class AnonymousRoundBounds(BaseModel):
    """Externally reviewed inclusive frame/PTS bounds; never inferred from video rate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    map_number: int = Field(gt=0)
    round_number: int = Field(gt=0)
    map_id: str = Field(min_length=1)
    start_frame_index: int = Field(ge=0)
    end_frame_index: int = Field(ge=0)
    start_source_pts: int = Field(ge=0)
    end_source_pts: int = Field(ge=0)
    reviewer_id: str = Field(min_length=1)
    evidence_reference: str = Field(min_length=1)
    review_status: Literal["externally_reviewed"]

    @model_validator(mode="after")
    def ordered(self) -> AnonymousRoundBounds:
        if self.end_frame_index < self.start_frame_index:
            raise ValueError("round frame bounds are reversed")
        if self.end_source_pts < self.start_source_pts:
            raise ValueError("round PTS bounds are reversed")
        return self


class AnonymousFrameContext(BaseModel):
    """Externally reviewed live/nonlive context; omitted frames are unknown."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    frame_index: int = Field(ge=0)
    state: Literal["live", "nonlive", "unknown"]
    reviewer_id: str = Field(min_length=1)
    evidence_reference: str = Field(min_length=1)
    review_status: Literal["externally_reviewed"]


class AnonymousDecoderProvenance(BaseModel):
    """Decoder-domain identity, explicitly distinct from legacy OpenCV pixel hashes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reader: Literal["SequentialPtsVideoSource"] = "SequentialPtsVideoSource"
    ffmpeg_version: str = Field(min_length=1)
    ffprobe_version: str = Field(min_length=1)
    pixel_format: Literal["bgr24"] = "bgr24"
    timestamp_kind: Literal["pts", "best_effort_timestamp"]
    timestamp_timebase_numerator: int = Field(gt=0)
    timestamp_timebase_denominator: int = Field(gt=0)
    decoded_pixel_hash_domain: Literal["not_hashed"] = "not_hashed"


class AnonymousCandidateObservation(BaseModel):
    """A raw accepted or rejected detector candidate bound to one source frame."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str = Field(min_length=1)
    candidate: RawMinimapColorCandidate


class AnonymousRawFrameObservation(BaseModel):
    """Raw candidate set in the explicitly labeled configured HUD crop frame."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    provenance: TrackingObservationProvenance
    runner_manifest_sha256: str = Field(pattern=_SHA256)
    crop_x: int = Field(ge=0)
    crop_y: int = Field(ge=0)
    crop_width: int = Field(gt=0)
    crop_height: int = Field(gt=0)
    coordinate_frame: Literal["configured_minimap_crop_pixels_normalized"]
    context: Literal["live", "nonlive", "unknown"]
    context_evidence: AnonymousFrameContext | None = None
    candidates: tuple[AnonymousCandidateObservation, ...]
    debug_png_sha256: str = Field(pattern=_SHA256)


class AnonymousTrackSample(BaseModel):
    """Observed anonymous association only; no predicted or interpolated samples."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    manifest_sha256: str = Field(pattern=_SHA256)
    runner_manifest_sha256: str = Field(pattern=_SHA256)
    frame_index: int = Field(ge=0)
    source_pts: int = Field(ge=0)
    timebase_numerator: int = Field(gt=0)
    timebase_denominator: int = Field(gt=0)
    timestamp_s: float = Field(ge=0)
    tracklet_id: str = Field(pattern=r"^anon-[A-Za-z0-9._-]+-[0-9]{4,}$")
    candidate_id: str = Field(min_length=1)
    broadcast_color: str = Field(min_length=1)
    crop_x_normalized: float = Field(ge=0, le=1)
    crop_y_normalized: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    association_confidence: float = Field(ge=0, le=1)
    evidence_candidate_ids: tuple[str, ...] = Field(min_length=1)
    motion_distance_crop_fraction: float = Field(ge=0)
    observed: Literal[True] = True
    inference_scope: Literal["diagnostic_tracklet_only"] = "diagnostic_tracklet_only"

    @field_validator(
        "timestamp_s",
        "crop_x_normalized",
        "crop_y_normalized",
        "confidence",
        "association_confidence",
        "motion_distance_crop_fraction",
    )
    @classmethod
    def finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("anonymous sample values must be finite")
        return value

    @model_validator(mode="after")
    def timestamp_matches_observed_pts(self) -> AnonymousTrackSample:
        expected = Fraction(self.source_pts * self.timebase_numerator, self.timebase_denominator)
        if abs(self.timestamp_s - float(expected)) > 1e-9:
            raise ValueError("sample timestamp disagrees with source PTS/timebase")
        return self


class AnonymousMetricsAvailability(BaseModel):
    """Metric absence is explicit unless independently reviewed ground truth exists."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    available: Literal[False] = False
    reason: Literal["independent_ground_truth_unavailable"] = "independent_ground_truth_unavailable"


class AnonymousRunManifest(BaseModel):
    """Versioned wrapper binding decoder provenance to the frozen shared manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    mode: Literal["diagnostic_only", "synthetic"]
    tracking_manifest: TrackingRunManifest
    tracking_manifest_sha256: str = Field(pattern=_SHA256)
    decoder: AnonymousDecoderProvenance
    bounds: AnonymousRoundBounds
    metrics: AnonymousMetricsAvailability = AnonymousMetricsAvailability()
    max_step_crop_fraction: float = Field(gt=0, le=1)
    max_gap_seconds: float = Field(gt=0)
    ambiguity_margin: float = Field(ge=0, lt=1)
    runner_thresholds_validated_for_production: Literal[False] = False

    @model_validator(mode="after")
    def wrapper_binds_manifest(self) -> AnonymousRunManifest:
        import hashlib
        import json

        payload = json.dumps(
            self.tracking_manifest.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        if hashlib.sha256(payload).hexdigest() != self.tracking_manifest_sha256:
            raise ValueError("tracking manifest digest does not match wrapper")
        manifest = self.tracking_manifest
        bounds = self.bounds
        if (
            manifest.map_id,
            manifest.map_number,
            manifest.round_number,
            manifest.start_frame_index,
            manifest.end_frame_index,
            manifest.start_source_pts,
            manifest.end_source_pts,
        ) != (
            bounds.map_id,
            bounds.map_number,
            bounds.round_number,
            bounds.start_frame_index,
            bounds.end_frame_index,
            bounds.start_source_pts,
            bounds.end_source_pts,
        ):
            raise ValueError("wrapper bounds do not match tracking manifest")
        if (manifest.timebase_numerator, manifest.timebase_denominator) != (
            self.decoder.timestamp_timebase_numerator,
            self.decoder.timestamp_timebase_denominator,
        ):
            raise ValueError("decoder timebase does not match tracking manifest")
        return self

    def exact_start(self) -> Fraction:
        return Fraction(
            self.bounds.start_source_pts * self.decoder.timestamp_timebase_numerator,
            self.decoder.timestamp_timebase_denominator,
        )
