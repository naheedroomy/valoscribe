"""Versioned reviewer observations in source-cropped video coordinates."""

from __future__ import annotations

import math
from enum import Enum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from valoscribe.types.persistent import PersistentModel


class SmokeSourceSampleKind(str, Enum):
    PRESENT = "present"
    ABSENT = "absent"
    UNSETTLED = "unsettled"


class SmokeVisualReviewEvidence(PersistentModel):
    timestamp_s: float = Field(ge=0.0)
    frame_index: int = Field(ge=0)
    description: str = Field(min_length=1)
    center_source_crop_px: tuple[int, int] | None = None
    decoded_crop_sha256: str

    @field_validator("decoded_crop_sha256")
    @classmethod
    def digest_is_sha256(cls, value: str) -> str:
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError("decoded crop digest must be a lowercase SHA-256 hex digest")
        return value


class SmokeIndependentVisualReview(PersistentModel):
    """Independent visual reconciliation that explicitly does not identify smoke."""

    review_status: Literal["VISUAL_APPEARANCE_ONLY_IDENTITY_UNRESOLVED"]
    smoke_identity: Literal["UNRESOLVED"]
    smoke_plausibility: Literal["MODERATE"]
    caster_attribution: Literal["UNKNOWN"]
    interpretation: Literal["EXPLORATORY_VISUAL_FOOTPRINT_CANDIDATE_ONLY"]
    evidence: list[SmokeVisualReviewEvidence] = Field(min_length=1)
    caveats: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def reject_duplicate_frame_indices(self) -> SmokeIndependentVisualReview:
        frame_indices = [item.frame_index for item in self.evidence]
        if len(frame_indices) != len(set(frame_indices)):
            raise ValueError("visual review evidence frame indices must be unique")
        return self


class SmokeSourceCrop(PersistentModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class SmokeSourceSample(PersistentModel):
    timestamp_s: float = Field(ge=0.0)
    frame_index: int = Field(ge=0)
    kind: SmokeSourceSampleKind
    review_note: str = Field(min_length=1)
    decoded_crop_sha256: str | None = None

    @field_validator("timestamp_s")
    @classmethod
    def timestamp_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("source sample timestamp must be finite")
        return value

    @field_validator("decoded_crop_sha256")
    @classmethod
    def digest_is_sha256(cls, value: str | None) -> str | None:
        if value is not None and (
            len(value) != 64 or any(char not in "0123456789abcdef" for char in value)
        ):
            raise ValueError("decoded crop digest must be a lowercase SHA-256 hex digest")
        return value


class SmokeSourceObservation(PersistentModel):
    """Evidence about smoke appearance without a canonical map-space label."""

    schema_version: Literal["1.0"] = "1.0"
    source_filename: str = Field(min_length=1)
    source_frame_width: int = Field(gt=0)
    source_frame_height: int = Field(gt=0)
    nominal_fps: float = Field(gt=0.0)
    crop: SmokeSourceCrop
    first_present_timestamp_s: float = Field(ge=0.0)
    last_present_timestamp_s: float = Field(ge=0.0)
    first_absent_after_present_timestamp_s: float = Field(ge=0.0)
    boundary_uncertainty_s: float = Field(gt=0.0)
    onset_last_unsettled_timestamp_s: float
    onset_first_persistent_timestamp_s: float
    end_last_present_timestamp_s: float
    end_first_clearly_absent_timestamp_s: float
    maximum_timing_uncertainty_s: float = Field(gt=0.0)
    center_source_crop_px: tuple[int, int]
    center_tolerance_px: int | None = Field(default=None, ge=0)
    center_is_approximate: Literal[True] = True
    agent_attribution: Literal["UNKNOWN"] = "UNKNOWN"
    independent_visual_review: SmokeIndependentVisualReview | None = None
    canonical_map_point: None = None
    canonical_registration_status: Literal["pending"] = "pending"
    samples: list[SmokeSourceSample] = Field(min_length=1)

    @field_validator(
        "nominal_fps",
        "boundary_uncertainty_s",
        "first_present_timestamp_s",
        "last_present_timestamp_s",
        "first_absent_after_present_timestamp_s",
        "onset_last_unsettled_timestamp_s",
        "onset_first_persistent_timestamp_s",
        "end_last_present_timestamp_s",
        "end_first_clearly_absent_timestamp_s",
        "maximum_timing_uncertainty_s",
    )
    @classmethod
    def finite_source_values(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("source observation numeric values must be finite")
        return value

    @model_validator(mode="after")
    def validate_source_bounds_and_order(self) -> SmokeSourceObservation:
        if self.independent_visual_review is not None:
            for evidence in self.independent_visual_review.evidence:
                expected_timestamp = evidence.frame_index / self.nominal_fps
                if abs(evidence.timestamp_s - expected_timestamp) > 0.5 / self.nominal_fps + 1e-6:
                    raise ValueError(
                        "visual review evidence frame and timestamp disagree with nominal fps"
                    )
        if self.crop.x + self.crop.width > self.source_frame_width:
            raise ValueError("source crop exceeds frame width")
        if self.crop.y + self.crop.height > self.source_frame_height:
            raise ValueError("source crop exceeds frame height")
        center_x, center_y = self.center_source_crop_px
        if not (0 <= center_x < self.crop.width and 0 <= center_y < self.crop.height):
            raise ValueError("source-space center must be inside the crop")
        if not (
            self.first_present_timestamp_s
            <= self.last_present_timestamp_s
            < self.first_absent_after_present_timestamp_s
        ):
            raise ValueError("smoke source observation interval is not ordered")
        if not (
            0
            <= self.onset_last_unsettled_timestamp_s
            < self.onset_first_persistent_timestamp_s
            <= self.first_present_timestamp_s
        ):
            raise ValueError("onset interval is not ordered")
        if not (
            self.last_present_timestamp_s
            <= self.end_last_present_timestamp_s
            < self.end_first_clearly_absent_timestamp_s
        ):
            raise ValueError("end interval is not ordered")
        onset_uncertainty = (
            self.onset_first_persistent_timestamp_s - self.onset_last_unsettled_timestamp_s
        )
        end_uncertainty = (
            self.end_first_clearly_absent_timestamp_s - self.end_last_present_timestamp_s
        )
        if max(onset_uncertainty, end_uncertainty) > self.maximum_timing_uncertainty_s:
            raise ValueError("timing interval exceeds maximum uncertainty")
        if self.boundary_uncertainty_s > self.maximum_timing_uncertainty_s:
            raise ValueError("boundary uncertainty exceeds maximum timing uncertainty")
        tolerance = 0.5 / self.nominal_fps + 1e-6
        for sample in self.samples:
            expected_timestamp = sample.frame_index / self.nominal_fps
            if abs(sample.timestamp_s - expected_timestamp) > tolerance:
                raise ValueError("sample frame index and timestamp disagree with nominal fps")
        present = [
            sample.timestamp_s
            for sample in self.samples
            if sample.kind == SmokeSourceSampleKind.PRESENT
        ]
        unsettled = [
            sample.timestamp_s
            for sample in self.samples
            if sample.kind == SmokeSourceSampleKind.UNSETTLED
        ]
        absent = [
            sample.timestamp_s
            for sample in self.samples
            if sample.kind == SmokeSourceSampleKind.ABSENT
        ]
        if not present or not unsettled or not absent:
            raise ValueError("samples must include present, unsettled, and absent evidence")
        if any(
            sample.kind == SmokeSourceSampleKind.ABSENT
            and min(present) <= sample.timestamp_s <= max(present)
            for sample in self.samples
        ):
            raise ValueError("absent sample inside persistent smoke segment")
        if (
            self.first_present_timestamp_s != min(present)
            or self.last_present_timestamp_s != max(present)
            or self.first_absent_after_present_timestamp_s
            != min(t for t in absent if t > max(present))
        ):
            raise ValueError("summary timestamps disagree with reviewed samples")
        if (
            self.onset_last_unsettled_timestamp_s != max(t for t in unsettled if t < min(present))
            or self.onset_first_persistent_timestamp_s != min(present)
            or self.end_last_present_timestamp_s != max(present)
            or self.end_first_clearly_absent_timestamp_s
            != min(t for t in absent if t > max(present))
        ):
            raise ValueError("transition bounds disagree with reviewed samples")
        if any(
            first.timestamp_s >= second.timestamp_s or first.frame_index >= second.frame_index
            for first, second in zip(self.samples, self.samples[1:])
        ):
            raise ValueError("source samples must be strictly ordered by timestamp and frame index")
        if any(sample.timestamp_s < 0 for sample in self.samples):
            raise ValueError("source sample timestamp cannot be negative")
        if self.independent_visual_review is not None:
            samples_by_frame = {sample.frame_index: sample for sample in self.samples}
            for evidence in self.independent_visual_review.evidence:
                source_sample = samples_by_frame.get(evidence.frame_index)
                if (
                    source_sample is not None
                    and source_sample.decoded_crop_sha256 is not None
                    and source_sample.decoded_crop_sha256 != evidence.decoded_crop_sha256
                ):
                    raise ValueError("visual review digest disagrees with source sample digest")
        return self
