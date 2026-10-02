"""Typed outputs for a development-only supervised crop-space diagnostic."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import Field, field_validator, model_validator

from valoscribe.types.persistent import PersistentModel


class CropDiagnosticPolicy(PersistentModel):
    """Frozen crop-space association settings; not a canonical tracking policy."""

    schema_version: Literal["2.0"] = "2.0"
    detector: Literal["MinimapColorCandidateDetector/1.0"] = "MinimapColorCandidateDetector/1.0"
    assignment: Literal["tracking.assignment._hungarian/1.0"] = "tracking.assignment._hungarian/1.0"
    coordinate_frame: Literal["configured_minimap_crop_pixels"] = "configured_minimap_crop_pixels"
    seed_radius_px: float = Field(default=14.0, gt=0)
    max_motion_px_per_s: float = Field(default=70.0, gt=0)
    max_gap_s: float = Field(default=1.0, gt=0)
    ambiguity_margin_px: float = Field(default=4.0, ge=0)
    maximum_cost_px: float = Field(default=70.0, gt=0)


class CropDiagnosticSeedBinding(PersistentModel):
    """Required measured binding between a visual seed and its source raster."""

    schema_version: Literal["1.0"] = "1.0"
    source_video_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    frame_index: int = Field(ge=0)
    timestamp_s: float = Field(ge=0, allow_inf_nan=False)
    crop_x: int = Field(ge=0)
    crop_y: int = Field(ge=0)
    crop_width: int = Field(gt=0)
    crop_height: int = Field(gt=0)
    coordinate_frame: Literal["configured_minimap_crop_pixels"]
    decoded_frame_bgr_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decoded_crop_bgr_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    uncertainty_px_each_axis: float = Field(gt=0, allow_inf_nan=False)

    @field_validator("timestamp_s", "uncertainty_px_each_axis")
    @classmethod
    def finite_values(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("seed binding values must be finite")
        return value


class CropDiagnosticPrediction(PersistentModel):
    """Versioned crop-local association with evidence and uncalibrated uncertainty."""

    schema_version: Literal["2.0"] = "2.0"
    frame_index: int = Field(ge=0)
    timestamp_s: float = Field(ge=0, allow_inf_nan=False)
    player_id: str = Field(min_length=1)
    candidate_id: str | None = None
    center_crop_px: tuple[float, float] | None = None
    status: Literal["seeded", "associated", "abstained", "missed"]
    reason: str | None = None
    selected_evidence_candidate_id: str | None = None
    motion_cost_px: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    competitor_margin_px: float | None = Field(default=None, allow_inf_nan=False)
    seed_uncertainty_px_each_axis: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    identity_confidence: Literal["uncalibrated", "unknown"] = "unknown"

    @field_validator("center_crop_px")
    @classmethod
    def finite_center(cls, value: tuple[float, float] | None) -> tuple[float, float] | None:
        if value is not None and any(not math.isfinite(item) for item in value):
            raise ValueError("prediction center must be finite")
        return value

    @field_validator("competitor_margin_px")
    @classmethod
    def finite_margin(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("competitor margin must be finite")
        return value

    @model_validator(mode="after")
    def coherent_result(self) -> CropDiagnosticPrediction:
        success = self.status in {"seeded", "associated"}
        if success and (self.candidate_id is None or self.center_crop_px is None):
            raise ValueError("seeded/associated predictions require candidate and center")
        if not success and (self.candidate_id is not None or self.center_crop_px is not None):
            raise ValueError("abstentions and misses forbid candidate and center")
        if success and self.selected_evidence_candidate_id != self.candidate_id:
            raise ValueError("successful predictions require matching selected raw evidence")
        if self.status == "associated" and self.motion_cost_px is None:
            raise ValueError("associated predictions require a motion cost")
        if self.status in {"abstained", "missed"} and not self.reason:
            raise ValueError("abstentions and misses require a reason")
        return self


class CropDiagnosticEvaluationBlinding(PersistentModel):
    """Developer exposure is distinct from whether code accepts gold inputs."""

    strict_freeze_before_gold: Literal[False] = False
    developer_gold_exposure: Literal[True] = True
    programmatic_input_separation: Literal[True] = True


class CropDiagnosticAcceptance(PersistentModel):
    """The run is evidence only; no acceptance assessment is asserted."""

    status: Literal["diagnostic_only"] = "diagnostic_only"
    assessment: Literal["not_assessed"] = "not_assessed"


class CropDiagnosticProvenance(PersistentModel):
    """Source/config/dependency/seed/policy/output hashes for one diagnostic run."""

    schema_version: Literal["2.0"] = "2.0"
    source_video_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    diagnostic_code_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dependency_file_sha256: dict[str, str]
    algorithm_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime_provenance: dict[str, str]
    color_profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    hud_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    crop_coordinate_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    seed_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    predictions_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_detections_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    diagnostic_only: Literal[True] = True
    canonical_coordinates_emitted: Literal[False] = False
    gold_reference_read_for_prediction: Literal[False] = False
    evaluation_blinding: CropDiagnosticEvaluationBlinding = Field(
        default_factory=CropDiagnosticEvaluationBlinding
    )
    acceptance: CropDiagnosticAcceptance = Field(default_factory=CropDiagnosticAcceptance)
