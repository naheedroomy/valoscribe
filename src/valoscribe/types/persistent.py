"""Versioned persistent contracts for minimap-derived analysis data.

Raw observations (``PlayerDetection``) are separate from derived tracks and
fusion results. Changes to these persisted names or meanings require a schema
version bump; see ``docs/schema-compatibility.md``.
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer,
    model_validator,
)


class PersistentModel(BaseModel):
    """Strict base for versioned serialized contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    @model_serializer(mode="wrap")
    def validate_before_serializing(self, handler: SerializerFunctionWrapHandler) -> Any:
        """Revalidate nested mutable data at every persistence boundary."""
        type(self).model_validate(self.__dict__)
        return handler(self)


class PortraitStructureStatus(str, Enum):
    """Diagnostic state; none of these values implies identity evidence."""

    LOCALIZED = "localized"
    UNKNOWN = "unknown"
    CLIPPED = "clipped"
    OVERLAP = "overlap"
    REJECTED = "rejected"


class PortraitStructureROI(PersistentModel):
    """Native-pixel search envelope in the input image coordinate system."""

    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    coordinate_origin: Literal["image_top_left"] = "image_top_left"


class PortraitStructurePolicy(PersistentModel):
    """Uncalibrated synthetic construction settings for the diagnostic."""

    algorithm_version: Literal["closed-edge-enclosure-v1"] = "closed-edge-enclosure-v1"
    representation_version: Literal["supported-spatial-gradient-v1"] = (
        "supported-spatial-gradient-v1"
    )
    synthetic_only: Literal[True] = True
    canny_low: int = Field(default=35, ge=0, le=255)
    canny_high: int = Field(default=100, ge=1, le=255)
    closing_kernel: int = Field(default=3, ge=1, le=9)
    minimum_area_px: int = Field(default=36, ge=1)
    maximum_area_fraction: float = Field(default=0.8, gt=0.0, le=1.0)
    minimum_aspect_ratio: float = Field(default=0.45, gt=0.0, le=1.0)
    maximum_aspect_ratio: float = Field(default=1.8, ge=1.0)
    grid_rows: int = Field(default=4, ge=1, le=16)
    grid_columns: int = Field(default=4, ge=1, le=16)
    minimum_compactness: float = Field(default=0.76, gt=0.0, le=1.0)
    minimum_support_fraction: float = Field(default=0.25, gt=0.0, le=1.0)
    minimum_common_support_fraction: float = Field(default=0.25, gt=0.0, le=1.0)
    minimum_gradient_pixels: int = Field(default=8, ge=1)
    hud_profile_id: str | None = None
    map_profile_id: str | None = None

    @model_validator(mode="after")
    def structure_policy_is_valid(self) -> PortraitStructurePolicy:
        if self.canny_high <= self.canny_low:
            raise ValueError("canny_high must be greater than canny_low")
        if self.closing_kernel % 2 == 0:
            raise ValueError("closing_kernel must be odd")
        if self.maximum_aspect_ratio < self.minimum_aspect_ratio:
            raise ValueError("maximum_aspect_ratio must be >= minimum_aspect_ratio")
        return self


class PortraitStructureDiagnostic(PersistentModel):
    """Auditable localization and feature availability, never an identity prediction."""

    schema_version: Literal["1.0"] = "1.0"
    candidate_id: str = Field(min_length=1)
    context_image_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    roi: PortraitStructureROI
    status: PortraitStructureStatus
    policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    coordinate_origin: Literal["image_top_left"] = "image_top_left"
    proposed_boundary: PortraitStructureROI | None = None
    proposed_center_x: float | None = None
    proposed_center_y: float | None = None
    geometric_support_fraction: float = Field(ge=0.0, le=1.0)
    ambiguity_count: int = Field(ge=0)
    rejection_reasons: list[str] = Field(default_factory=list)
    feature_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    support_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    gradient_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    supported_gradient_pixels: int = Field(ge=0)
    metadata: Literal["uncalibrated_diagnostic_only"] = "uncalibrated_diagnostic_only"

    @field_validator("proposed_center_x", "proposed_center_y")
    @classmethod
    def structure_centers_are_finite(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("proposed centers must be finite")
        return value

    @model_validator(mode="after")
    def structure_result_is_consistent(self) -> PortraitStructureDiagnostic:
        success_fields = {
            "proposed_boundary": self.proposed_boundary,
            "proposed_center_x": self.proposed_center_x,
            "proposed_center_y": self.proposed_center_y,
            "feature_sha256": self.feature_sha256,
            "support_sha256": self.support_sha256,
            "gradient_sha256": self.gradient_sha256,
        }
        if self.status is PortraitStructureStatus.LOCALIZED:
            absent = [name for name, value in success_fields.items() if value is None]
            if absent:
                raise ValueError(f"localized diagnostics require all success fields: {absent}")
            boundary = self.proposed_boundary
            assert boundary is not None
            if (
                boundary.x < self.roi.x
                or boundary.y < self.roi.y
                or boundary.x + boundary.width > self.roi.x + self.roi.width
                or boundary.y + boundary.height > self.roi.y + self.roi.height
            ):
                raise ValueError("localized boundary must be contained by its search ROI")
            expected_center_x = boundary.x + (boundary.width - 1) / 2
            expected_center_y = boundary.y + (boundary.height - 1) / 2
            if (
                self.proposed_center_x != expected_center_x
                or self.proposed_center_y != expected_center_y
            ):
                raise ValueError("localized centers must match the proposed boundary")
            if self.supported_gradient_pixels <= 0 or self.geometric_support_fraction <= 0:
                raise ValueError("localized diagnostics require positive supported gradients")
        else:
            present = [name for name, value in success_fields.items() if value is not None]
            if present:
                raise ValueError(f"failure diagnostics forbid success fields: {present}")
            if self.supported_gradient_pixels != 0 or self.geometric_support_fraction != 0:
                raise ValueError("failure diagnostics must not report usable support")
            if not self.rejection_reasons:
                raise ValueError("failure diagnostics require a rejection reason")
        return self


class PortraitStructureComparison(PersistentModel):
    """Uncalibrated descriptor comparison with explicit support accounting."""

    schema_version: Literal["1.0"] = "1.0"
    status: Literal["available", "unknown", "policy_mismatch"]
    policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    shared_support_fraction: float = Field(ge=0.0, le=1.0)
    distance: float | None = Field(default=None, ge=0.0)
    metadata: Literal["uncalibrated_diagnostic_only"] = "uncalibrated_diagnostic_only"

    @model_validator(mode="after")
    def comparison_has_no_identity_probability(self) -> PortraitStructureComparison:
        if (self.status == "available") != (self.distance is not None):
            raise ValueError("only available comparisons contain a distance")
        return self


class RoundPhase(str, Enum):
    PREROUND = "PREROUND"
    OPENING = "OPENING"
    DEFAULT = "DEFAULT"
    PRESSURE = "PRESSURE"
    CONTACT = "CONTACT"
    REGROUP = "REGROUP"
    ROTATE = "ROTATE"
    EXECUTE = "EXECUTE"
    POST_PLANT = "POST_PLANT"
    RETAKE = "RETAKE"
    SAVE = "SAVE"
    CLUTCH = "CLUTCH"
    ROUND_END = "ROUND_END"
    UNKNOWN = "UNKNOWN"


class FormationLabel(str, Enum):
    FIVE_MAN_GROUP = "FIVE_MAN_GROUP"
    FOUR_ONE_LURK = "FOUR_ONE_LURK"
    THREE_TWO_SPLIT = "THREE_TWO_SPLIT"
    TWO_ONE_TWO_DEFAULT = "TWO_ONE_TWO_DEFAULT"
    THREE_ONE_ONE_DEFAULT = "THREE_ONE_ONE_DEFAULT"
    SITE_STACK = "SITE_STACK"
    SPREAD_DEFAULT = "SPREAD_DEFAULT"
    UNKNOWN_FORMATION = "UNKNOWN_FORMATION"


class FormationPlayerPosition(PersistentModel):
    """One identified player's raw, observed position and evidence."""

    schema_version: Literal["1.0"] = "1.0"
    player_id: str = Field(min_length=1)
    position: NormalizedPoint
    confidence: float = Field(gt=0.0, le=1.0)
    evidence: list[str] = Field(min_length=1)


class FormationObservation(PersistentModel):
    """One timestamped five-player snapshot for deterministic formation labeling."""

    schema_version: Literal["1.0"] = "1.0"
    match_id: str = Field(min_length=1)
    map_id: str = Field(min_length=1)
    round_id: str = Field(min_length=1)
    team_id: str = Field(min_length=1)
    vod_timestamp_s: float = Field(ge=0.0)
    players: list[FormationPlayerPosition]
    spike_position: NormalizedPoint | None = None
    spike_evidence: list[str] = Field(default_factory=list)
    conflicting_signals: list[str] = Field(default_factory=list)

    @field_validator("vod_timestamp_s")
    @classmethod
    def formation_timestamp_finite(cls, value: float) -> float:
        return _require_finite(value, "formation timestamp")


class FormationObservationResult(PersistentModel):
    schema_version: Literal["1.0"] = "1.0"
    match_id: str = Field(min_length=1)
    map_id: str = Field(min_length=1)
    round_id: str = Field(min_length=1)
    team_id: str = Field(min_length=1)
    vod_timestamp_s: float = Field(ge=0.0)
    formation: FormationLabel
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(min_length=1)
    diagnostics: list[str] = Field(default_factory=list)
    zone_occupancy: dict[str, int] = Field(default_factory=dict)
    occupied_lanes: list[str] = Field(default_factory=list)
    pairwise_distances: list[float] = Field(default_factory=list)
    spike_zone_id: str | None = None

    @field_validator("vod_timestamp_s", "confidence", "pairwise_distances")
    @classmethod
    def formation_numbers_finite(cls, value: Any) -> Any:
        if isinstance(value, list):
            return [_require_finite(item, "formation distance") for item in value]
        return _require_finite(value, "formation result value")


class PhaseObservation(PersistentModel):
    """Explicit timestamped tactical signals; broadcast color is not a side cue."""

    schema_version: Literal["1.0"] = "1.0"
    match_id: str = Field(min_length=1)
    map_id: str = Field(min_length=1)
    round_id: str = Field(min_length=1)
    vod_timestamp_s: float = Field(ge=0.0)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(min_length=1)
    explicit_phase: RoundPhase | None = None
    preround: bool = False
    opening: bool = False
    default: bool = False
    pressure: bool = False
    contact: bool = False
    regroup: bool = False
    rotate: bool = False
    execute: bool = False
    planted: bool = False
    retake: bool = False
    save: bool = False
    clutch: bool = False
    round_end: bool = False
    replay: bool = False
    conflicting_signals: list[str] = Field(default_factory=list)

    @field_validator("vod_timestamp_s", "confidence")
    @classmethod
    def phase_numbers_finite(cls, value: float) -> float:
        return _require_finite(value, "phase observation value")

    @field_validator("match_id", "map_id", "round_id")
    @classmethod
    def phase_identifiers_not_blank(cls, value: str, info: Any) -> str:
        return _require_identifier(value, info.field_name)

    @field_validator("evidence", "conflicting_signals")
    @classmethod
    def phase_text_not_blank(cls, values: list[str]) -> list[str]:
        return [_require_identifier(value, "phase evidence") for value in values]

    @property
    def signal_names(self) -> tuple[str, ...]:
        return (
            "round_end",
            "clutch",
            "planted",
            "retake",
            "save",
            "execute",
            "rotate",
            "regroup",
            "contact",
            "pressure",
            "default",
            "opening",
            "preround",
        )

    @property
    def signals(self) -> tuple[bool, ...]:
        return tuple(bool(getattr(self, signal)) for signal in self.signal_names)


class PhaseDiagnostic(PersistentModel):
    schema_version: Literal["1.0"] = "1.0"
    code: str = Field(min_length=1)
    evidence: list[str] = Field(min_length=1)


class PhaseSegment(PersistentModel):
    schema_version: Literal["1.0"] = "1.0"
    match_id: str = Field(min_length=1)
    map_id: str = Field(min_length=1)
    round_id: str = Field(min_length=1)
    phase: RoundPhase
    start_timestamp_s: float = Field(ge=0.0)
    end_timestamp_s: float = Field(ge=0.0)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(min_length=1)
    diagnostics: list[PhaseDiagnostic] = Field(default_factory=list)

    @model_validator(mode="after")
    def phase_segment_is_valid(self) -> PhaseSegment:
        if self.end_timestamp_s < self.start_timestamp_s:
            raise ValueError("phase segment end must not precede its start")
        if self.phase != RoundPhase.UNKNOWN and (self.confidence <= 0.0 or not self.evidence):
            raise ValueError("inferred phases require positive confidence and evidence")
        return self


class Side(str, Enum):
    ATTACK = "attack"
    DEFENSE = "defense"
    UNKNOWN = "unknown"


class EvidenceSource(str, Enum):
    MINIMAP = "minimap"
    PLAYER_HUD = "player_hud"
    KILLFEED = "killfeed"
    ROUND_STATE = "round_state"
    METADATA = "metadata"
    MAIN_FRAME = "main_frame"
    INFERENCE = "inference"


def _require_finite(value: float, field_name: str) -> float:
    if not math.isfinite(value):
        raise ValueError(f"{field_name} must be finite")
    return value


def _require_identifier(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} must not be blank")
    return value


def _validate_json_values(value: JsonValue, field_name: str) -> JsonValue:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{field_name} numbers must be finite")
    if isinstance(value, list):
        for item in value:
            _validate_json_values(item, field_name)
    elif isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{field_name} object keys must be strings")
            _validate_json_values(item, field_name)
    return value


class NormalizedPoint(PersistentModel):
    """Point normalized to the inclusive [0, 1] image/map coordinate range."""

    schema_version: Literal["1.0"] = "1.0"
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)

    @field_validator("x", "y")
    @classmethod
    def coordinates_are_finite(cls, value: float) -> float:
        return _require_finite(value, "coordinate")


class EvidenceRef(PersistentModel):
    schema_version: Literal["1.0"] = "1.0"
    match_id: str = Field(min_length=1)
    map_id: str = Field(min_length=1)
    round_id: str = Field(min_length=1)
    vod_timestamp_s: float = Field(ge=0.0)
    round_elapsed_s: float | None = Field(default=None, ge=0.0)
    source: EvidenceSource
    confidence: float = Field(ge=0.0, le=1.0)
    frame_path: str | None = None
    note: str | None = None

    @field_validator("match_id", "map_id", "round_id")
    @classmethod
    def identifiers_not_blank(cls, value: str, info: Any) -> str:
        return _require_identifier(value, info.field_name)

    @field_validator("vod_timestamp_s", "round_elapsed_s", "confidence")
    @classmethod
    def numeric_values_are_finite(cls, value: float | None, info: Any) -> float | None:
        if value is not None:
            return _require_finite(value, info.field_name)
        return value


class NormalizedBox(PersistentModel):
    """Axis-aligned box in normalized crop coordinates."""

    schema_version: Literal["1.0"] = "1.0"
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    width: float = Field(gt=0.0, le=1.0)
    height: float = Field(gt=0.0, le=1.0)

    @field_validator("x", "y", "width", "height")
    @classmethod
    def coordinates_are_finite(cls, value: float) -> float:
        return _require_finite(value, "box coordinate")

    @model_validator(mode="after")
    def box_is_inside_frame(self) -> NormalizedBox:
        if self.x + self.width > 1.0 + 1e-9 or self.y + self.height > 1.0 + 1e-9:
            raise ValueError("normalized box must fit inside the frame")
        return self


class RawMinimapColorCandidate(PersistentModel):
    """Unassigned color-mask observation; it does not imply team, side, or identity."""

    schema_version: Literal["1.0"] = "1.0"
    vod_timestamp_s: float = Field(ge=0.0)
    source_frame: int | None = Field(default=None, ge=0)
    source: EvidenceSource = EvidenceSource.MINIMAP
    color_profile_id: str = Field(min_length=1)
    broadcast_color: str = Field(min_length=1)
    crop_point: NormalizedPoint
    bounding_box: NormalizedBox
    contour_area_px: float = Field(gt=0.0)
    mask_pixel_count: int = Field(gt=0)
    detector_confidence: float = Field(ge=0.0, le=1.0)
    accepted: bool
    rejection_reasons: list[str] = Field(default_factory=list)

    @field_validator("color_profile_id", "broadcast_color")
    @classmethod
    def identifiers_not_blank(cls, value: str, info: Any) -> str:
        return _require_identifier(value, info.field_name)

    @field_validator("vod_timestamp_s", "contour_area_px", "detector_confidence")
    @classmethod
    def measurements_are_finite(cls, value: float, info: Any) -> float:
        return _require_finite(value, info.field_name)

    @model_validator(mode="after")
    def acceptance_matches_reasons(self) -> RawMinimapColorCandidate:
        if self.accepted and self.rejection_reasons:
            raise ValueError("accepted candidates cannot have rejection reasons")
        if not self.accepted and not self.rejection_reasons:
            raise ValueError("rejected candidates require a rejection reason")
        return self


class PortraitRosterMember(PersistentModel):
    """Metadata roster evidence linking one possible team and player."""

    schema_version: Literal["1.0"] = "1.0"
    team_id: str = Field(min_length=1)
    player_id: str = Field(min_length=1)

    @field_validator("team_id", "player_id")
    @classmethod
    def identifiers_not_blank(cls, value: str, info: Any) -> str:
        return _require_identifier(value, info.field_name)


class NeutralPortraitTemplate(PersistentModel):
    """Reviewed, provenance-bound neutral portrait asset declaration."""

    schema_version: Literal["1.0"] = "1.0"
    template_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_type: Literal["live", "replay"]
    frame_id: str = Field(min_length=1)
    frame_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    hud_profile_id: str = Field(min_length=1)
    frame_width: int = Field(gt=0)
    frame_height: int = Field(gt=0)
    crop_x: int = Field(ge=0)
    crop_y: int = Field(ge=0)
    crop_width: int = Field(gt=0)
    crop_height: int = Field(gt=0)
    image_path: str = Field(min_length=1)
    image_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    mask_path: str = Field(min_length=1)
    mask_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    acquisition_role: Literal["calibration", "heldout"]
    review_status: Literal["pending", "accepted", "rejected"] = "pending"
    reviewer_id: str | None = None
    side: Side = Side.UNKNOWN

    @field_validator(
        "template_id",
        "agent_id",
        "source_id",
        "frame_id",
        "hud_profile_id",
        "image_path",
        "mask_path",
    )
    @classmethod
    def neutral_template_identifiers_not_blank(cls, value: str, info: Any) -> str:
        return _require_identifier(value, info.field_name)

    @field_validator("reviewer_id")
    @classmethod
    def reviewer_not_blank(cls, value: str | None) -> str | None:
        return None if value is None else _require_identifier(value, "reviewer_id")

    @model_validator(mode="after")
    def accepted_template_has_review_evidence(self) -> NeutralPortraitTemplate:
        if self.crop_x + self.crop_width > self.frame_width:
            raise ValueError("template crop exceeds source frame width")
        if self.crop_y + self.crop_height > self.frame_height:
            raise ValueError("template crop exceeds source frame height")
        if self.review_status == "accepted" and self.reviewer_id is None:
            raise ValueError("accepted templates require reviewer_id")
        return self


class NeutralPortraitCalibration(PersistentModel):
    """Explicit calibration gate; pending is the safe default."""

    schema_version: Literal["1.0"] = "1.0"
    status: Literal["pending", "accepted", "rejected"] = "pending"
    template_set_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    required_agent_ids: list[str] = Field(min_length=1)
    training_frame_ids: list[str] = Field(min_length=1)
    heldout_frame_ids: list[str] = Field(min_length=1)
    negative_control_ids: list[str] = Field(min_length=1)
    minimum_confidence: float = Field(ge=0.0, le=1.0)
    distinct_agent_margin: float = Field(ge=0.0, le=1.0)
    calibration_measurements: dict[str, float] = Field(default_factory=dict)
    reviewer_id: str | None = None

    @field_validator(
        "required_agent_ids", "training_frame_ids", "heldout_frame_ids", "negative_control_ids"
    )
    @classmethod
    def calibration_identifiers_not_blank(cls, values: list[str], info: Any) -> list[str]:
        normalized = [_require_identifier(value, info.field_name) for value in values]
        if len(normalized) != len(set(normalized)):
            raise ValueError(f"{info.field_name} must be unique")
        return normalized

    @field_validator("calibration_measurements")
    @classmethod
    def calibration_measurements_are_finite(cls, values: dict[str, float]) -> dict[str, float]:
        return {
            _require_identifier(key, "measurement_name"): _require_finite(value, key)
            for key, value in values.items()
        }

    @field_validator("reviewer_id")
    @classmethod
    def calibration_reviewer_not_blank(cls, value: str | None) -> str | None:
        return None if value is None else _require_identifier(value, "reviewer_id")

    @model_validator(mode="after")
    def accepted_calibration_is_complete(self) -> NeutralPortraitCalibration:
        if set(self.training_frame_ids) & set(self.heldout_frame_ids):
            raise ValueError("calibration and heldout frames must be disjoint")
        if self.status == "accepted" and self.reviewer_id is None:
            raise ValueError("accepted calibration requires reviewer_id")
        if self.status == "accepted" and not self.calibration_measurements:
            raise ValueError("accepted calibration requires measurements")
        return self


class NeutralAgentEvidenceDecision(PersistentModel):
    """Raw neutral-template scores and explicit fail-closed resolution state."""

    schema_version: Literal["1.1"] = "1.1"
    template_set_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    calibration_policy_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    candidate_id: str | None = None
    source_crop_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    minimum_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    distinct_agent_margin: float | None = Field(default=None, ge=0.0, le=1.0)
    calibration_status: Literal["pending", "accepted", "rejected"]
    required_agent_coverage: list[str]
    observed_agent_coverage: list[str]
    raw_scores: list[AgentPortraitTemplateMatch] = Field(default_factory=list)
    best_score_by_agent: dict[str, float] = Field(default_factory=dict)
    resolved_agent_id: str | None = None
    accepted: bool = False
    rejection_reasons: list[str] = Field(default_factory=list)

    @field_validator("required_agent_coverage", "observed_agent_coverage")
    @classmethod
    def decision_agent_coverage_is_valid(cls, values: list[str], info: Any) -> list[str]:
        normalized = [_require_identifier(value, info.field_name) for value in values]
        if len(normalized) != len(set(normalized)):
            raise ValueError(f"{info.field_name} must be unique")
        return normalized

    @field_validator("best_score_by_agent")
    @classmethod
    def decision_agent_scores_are_valid(cls, values: dict[str, float]) -> dict[str, float]:
        for agent_id, score in values.items():
            _require_identifier(agent_id, "agent_id")
            if not math.isfinite(score) or not 0.0 <= score <= 1.0:
                raise ValueError("agent scores must be finite and between 0 and 1")
        return values

    @model_validator(mode="after")
    def decision_state_is_coherent(self) -> NeutralAgentEvidenceDecision:
        if self.accepted:
            if self.resolved_agent_id is None or self.rejection_reasons:
                raise ValueError("accepted decisions require a resolution and no rejection reasons")
            if self.calibration_status != "accepted":
                raise ValueError("accepted decisions require accepted calibration")
            if not self.required_agent_coverage or not self.observed_agent_coverage:
                raise ValueError("accepted decisions require non-empty agent coverage")
            if set(self.required_agent_coverage) - set(self.observed_agent_coverage):
                raise ValueError("accepted decisions require complete agent coverage")
            raw_agent_ids = {match.agent_id for match in self.raw_scores}
            if raw_agent_ids != set(self.observed_agent_coverage):
                raise ValueError("observed agent coverage must match raw score coverage")
            if raw_agent_ids != set(self.best_score_by_agent):
                raise ValueError("best agent scores must cover every raw scored agent")
            if (
                self.calibration_policy_sha256 is None
                or self.candidate_id is None
                or self.source_crop_sha256 is None
                or self.minimum_confidence is None
                or self.distinct_agent_margin is None
            ):
                raise ValueError("accepted decisions require policy and candidate provenance")
            ranked = sorted(self.best_score_by_agent.items(), key=lambda item: (-item[1], item[0]))
            if not ranked or ranked[0][0] != self.resolved_agent_id:
                raise ValueError("resolved agent must have the highest reported score")
            second_score = ranked[1][1] if len(ranked) > 1 else 0.0
            if ranked[0][1] < self.minimum_confidence:
                raise ValueError("resolved agent is below calibrated minimum confidence")
            if ranked[0][1] - second_score < self.distinct_agent_margin:
                raise ValueError("resolved agent does not meet calibrated margin")
            for agent_id, score in self.best_score_by_agent.items():
                raw_best = max(
                    (match.confidence for match in self.raw_scores if match.agent_id == agent_id),
                    default=None,
                )
                if raw_best is None or not math.isclose(score, raw_best, abs_tol=1e-9):
                    raise ValueError("best agent scores must match raw template scores")
        elif not self.rejection_reasons:
            raise ValueError("rejected decisions require a reason")
        if self.candidate_id is not None:
            _require_identifier(self.candidate_id, "candidate_id")
        return self


class NeutralPortraitProvenance(PersistentModel):
    """Opt-in candidate crop provenance, separate from legacy observations."""

    schema_version: Literal["1.0"] = "1.0"
    candidate_id: str = Field(min_length=1)
    source_crop_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("candidate_id")
    @classmethod
    def provenance_candidate_not_blank(cls, value: str) -> str:
        return _require_identifier(value, "candidate_id")


class AgentPortraitTemplateMatch(PersistentModel):
    """One roster-constrained template match, without identity assignment."""

    schema_version: Literal["1.0"] = "1.0"
    agent_id: str = Field(min_length=1)
    side: Side
    confidence: float = Field(ge=0.0, le=1.0)
    template_id: str = Field(min_length=1)
    roster_members: list[PortraitRosterMember] = Field(default_factory=list)
    evidence: list[str] = Field(min_length=1)

    @field_validator("agent_id", "template_id")
    @classmethod
    def identifiers_not_blank(cls, value: str, info: Any) -> str:
        return _require_identifier(value, info.field_name)

    @field_validator("confidence")
    @classmethod
    def confidence_is_finite(cls, value: float) -> float:
        return _require_finite(value, "confidence")

    @field_validator("evidence")
    @classmethod
    def evidence_not_blank(cls, values: list[str]) -> list[str]:
        return [_require_identifier(value, "evidence") for value in values]


class PlayerDetection(PersistentModel):
    """Raw, per-frame player-location candidates before temporal tracking."""

    schema_version: Literal["1.0"] = "1.0"
    vod_timestamp_s: float = Field(ge=0.0)
    team_id: str = Field(min_length=1)
    broadcast_slot: Literal["left", "right", "unknown"]
    broadcast_color: str | None = None
    side: Side
    candidate_player_ids: list[str]
    candidate_agent_ids: list[str]
    crop_point: NormalizedPoint
    canonical_point: NormalizedPoint
    detector_confidence: float = Field(ge=0.0, le=1.0)
    registration_confidence: float = Field(ge=0.0, le=1.0)
    source_frame: int | None = Field(default=None, ge=0)

    @field_validator("team_id")
    @classmethod
    def team_id_not_blank(cls, value: str) -> str:
        return _require_identifier(value, "team_id")

    @field_validator("candidate_player_ids", "candidate_agent_ids")
    @classmethod
    def candidate_ids_not_blank(cls, values: list[str], info: Any) -> list[str]:
        return [_require_identifier(value, info.field_name) for value in values]

    @field_validator("vod_timestamp_s", "detector_confidence", "registration_confidence")
    @classmethod
    def numeric_values_are_finite(cls, value: float, info: Any) -> float:
        return _require_finite(value, info.field_name)


def _validate_evidence_scope(
    match_id: str, map_id: str, round_id: str, evidence: list[EvidenceRef]
) -> None:
    for reference in evidence:
        if (reference.match_id, reference.map_id, reference.round_id) != (
            match_id,
            map_id,
            round_id,
        ):
            raise ValueError("evidence match, map, and round must match the record")


class AssignmentObservation(PersistentModel):
    """Registered raw icon observation with optional portrait evidence."""

    schema_version: Literal["1.0"] = "1.0"
    candidate_id: str = Field(min_length=1)
    team_id: str = Field(min_length=1)
    side: Side = Side.UNKNOWN
    canonical_point: NormalizedPoint
    detector_confidence: float = Field(ge=0.0, le=1.0)
    registration_confidence: float = Field(ge=0.0, le=1.0)
    portrait_matches: list[AgentPortraitTemplateMatch] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)

    @field_validator("candidate_id", "team_id")
    @classmethod
    def assignment_ids_not_blank(cls, value: str, info: Any) -> str:
        return _require_identifier(value, info.field_name)

    @field_validator("detector_confidence", "registration_confidence")
    @classmethod
    def assignment_confidence_is_finite(cls, value: float, info: Any) -> float:
        return _require_finite(value, info.field_name)

    @field_validator("evidence")
    @classmethod
    def assignment_evidence_not_blank(cls, values: list[str]) -> list[str]:
        return [_require_identifier(value, "evidence") for value in values]


class AssignmentTrack(PersistentModel):
    """Known roster player and optional previous map-space position."""

    schema_version: Literal["1.0"] = "1.0"
    player_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    team_id: str = Field(min_length=1)
    side: Side = Side.UNKNOWN
    previous_position: NormalizedPoint | None = None

    @field_validator("player_id", "agent_id", "team_id")
    @classmethod
    def track_ids_not_blank(cls, value: str, info: Any) -> str:
        return _require_identifier(value, info.field_name)


class CandidateAssignment(PersistentModel):
    """Assignment decision or explicit unassigned result for a known player."""

    schema_version: Literal["1.0"] = "1.0"
    player_id: str = Field(min_length=1)
    candidate_id: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    cost: float | None = Field(default=None, ge=0.0)
    alternate_player_ids: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    rejection_reason: str | None = None

    @field_validator("player_id", "candidate_id", "rejection_reason")
    @classmethod
    def assignment_strings_not_blank(cls, value: str | None, info: Any) -> str | None:
        return None if value is None else _require_identifier(value, info.field_name)

    @field_validator("confidence", "cost")
    @classmethod
    def assignment_values_are_finite(cls, value: float | None, info: Any) -> float | None:
        return None if value is None else _require_finite(value, info.field_name)

    @field_validator("alternate_player_ids", "evidence")
    @classmethod
    def assignment_lists_not_blank(cls, values: list[str], info: Any) -> list[str]:
        return [_require_identifier(value, info.field_name) for value in values]

    @model_validator(mode="after")
    def assignment_state_is_coherent(self) -> CandidateAssignment:
        if self.candidate_id is None:
            if self.cost is not None or self.confidence != 0.0 or self.rejection_reason is None:
                raise ValueError(
                    "unassigned results require zero confidence, no cost, and a reason"
                )
        elif self.cost is None or self.rejection_reason is not None:
            raise ValueError("assigned results require a cost and no rejection reason")
        return self


class MotionModelConfig(PersistentModel):
    """Explicit map and motion bounds; values must come from map configuration."""

    schema_version: Literal["1.0"] = "1.0"
    map_width_m: float = Field(gt=0.0)
    map_height_m: float = Field(gt=0.0)
    maximum_speed_mps: float = Field(gt=0.0)
    maximum_prediction_gap_s: float = Field(gt=0.0)
    minimum_detection_confidence: float = Field(ge=0.0, le=1.0)
    minimum_registration_confidence: float = Field(ge=0.0, le=1.0)

    @field_validator(
        "map_width_m",
        "map_height_m",
        "maximum_speed_mps",
        "maximum_prediction_gap_s",
        "minimum_detection_confidence",
        "minimum_registration_confidence",
    )
    @classmethod
    def motion_values_are_finite(cls, value: float) -> float:
        return _require_finite(value, "motion configuration")


class PlayerTrackEstimate(PersistentModel):
    """One observed, predicted, or explicitly unknown per-player track sample."""

    schema_version: Literal["1.0"] = "1.0"
    player_id: str = Field(min_length=1)
    vod_timestamp_s: float = Field(ge=0.0)
    source_frame: int | None = Field(default=None, ge=0)
    position: NormalizedPoint | None = None
    observed: bool
    predicted: bool
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(min_length=1)
    rejection_reason: str | None = None

    @field_validator("player_id")
    @classmethod
    def track_player_id_not_blank(cls, value: str) -> str:
        return _require_identifier(value, "player_id")

    @field_validator("vod_timestamp_s", "confidence")
    @classmethod
    def track_values_are_finite(cls, value: float, info: Any) -> float:
        return _require_finite(value, info.field_name)

    @field_validator("evidence")
    @classmethod
    def track_evidence_not_blank(cls, values: list[str]) -> list[str]:
        return [_require_identifier(value, "evidence") for value in values]

    @field_validator("rejection_reason")
    @classmethod
    def track_rejection_not_blank(cls, value: str | None) -> str | None:
        return None if value is None else _require_identifier(value, "rejection_reason")

    @model_validator(mode="after")
    def sample_state_is_coherent(self) -> PlayerTrackEstimate:
        if self.position is None:
            if (
                self.observed
                or self.predicted
                or self.confidence != 0.0
                or self.rejection_reason is None
            ):
                raise ValueError(
                    "unknown track samples require zero confidence and a rejection reason"
                )
        elif self.observed == self.predicted or self.rejection_reason is not None:
            raise ValueError("position samples must be observed or predicted, without rejection")
        return self


class PlayerTrackPoint(PersistentModel):
    """Derived player location after temporal association and smoothing."""

    schema_version: Literal["1.0"] = "1.0"
    match_id: str = Field(min_length=1)
    map_id: str = Field(min_length=1)
    round_id: str = Field(min_length=1)
    vod_timestamp_s: float = Field(ge=0.0)
    round_elapsed_s: float = Field(ge=0.0)
    player_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    team_id: str = Field(min_length=1)
    side: Side
    position: NormalizedPoint
    zone_id: str | None = None
    alive: bool
    observed: bool
    interpolated: bool = False
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[EvidenceRef] = Field(min_length=1)

    @field_validator("match_id", "map_id", "round_id", "player_id", "agent_id", "team_id")
    @classmethod
    def identifiers_not_blank(cls, value: str, info: Any) -> str:
        return _require_identifier(value, info.field_name)

    @field_validator("vod_timestamp_s", "round_elapsed_s", "confidence")
    @classmethod
    def numeric_values_are_finite(cls, value: float, info: Any) -> float:
        return _require_finite(value, info.field_name)

    @model_validator(mode="after")
    def interpolation_must_be_unobserved(self) -> PlayerTrackPoint:
        if self.interpolated and self.observed:
            raise ValueError("interpolated track points cannot be marked observed")
        _validate_evidence_scope(self.match_id, self.map_id, self.round_id, self.evidence)
        return self


class AliveState(str, Enum):
    ALIVE = "alive"
    DEAD = "dead"
    UNKNOWN = "unknown"


class HUDAliveObservation(PersistentModel):
    """Per-player alive/dead evidence from a player HUD crop."""

    schema_version: Literal["1.0"] = "1.0"
    player_id: str = Field(min_length=1)
    round_id: str = Field(min_length=1)
    vod_timestamp_s: float = Field(ge=0.0)
    state: AliveState
    confidence: float = Field(ge=0.0, le=1.0)
    visible: bool
    evidence: list[str] = Field(min_length=1)

    @field_validator("player_id", "round_id")
    @classmethod
    def alive_ids_not_blank(cls, value: str, info: Any) -> str:
        return _require_identifier(value, info.field_name)

    @field_validator("vod_timestamp_s", "confidence")
    @classmethod
    def alive_values_are_finite(cls, value: float, info: Any) -> float:
        return _require_finite(value, info.field_name)

    @field_validator("evidence")
    @classmethod
    def alive_evidence_not_blank(cls, values: list[str]) -> list[str]:
        return [_require_identifier(value, "evidence") for value in values]


class KillfeedIdentityEvidence(PersistentModel):
    """Killfeed agent recognition and roster candidates, without forced identity."""

    schema_version: Literal["1.0"] = "1.0"
    agent_id: str = Field(min_length=1)
    candidate_player_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("agent_id")
    @classmethod
    def killfeed_agent_not_blank(cls, value: str) -> str:
        return _require_identifier(value, "agent_id")

    @field_validator("candidate_player_ids")
    @classmethod
    def killfeed_candidates_not_blank(cls, values: list[str]) -> list[str]:
        return [_require_identifier(value, "candidate_player_ids") for value in values]

    @field_validator("confidence")
    @classmethod
    def killfeed_confidence_is_finite(cls, value: float) -> float:
        return _require_finite(value, "confidence")


class KillfeedKillObservation(PersistentModel):
    """Raw killfeed kill evidence with independently scored killer and victim IDs."""

    schema_version: Literal["1.0"] = "1.0"
    event_id: str = Field(min_length=1)
    round_id: str = Field(min_length=1)
    vod_timestamp_s: float = Field(ge=0.0)
    killer: KillfeedIdentityEvidence
    victim: KillfeedIdentityEvidence
    evidence: list[str] = Field(min_length=1)

    @field_validator("event_id", "round_id")
    @classmethod
    def killfeed_ids_not_blank(cls, value: str, info: Any) -> str:
        return _require_identifier(value, info.field_name)

    @field_validator("vod_timestamp_s")
    @classmethod
    def killfeed_timestamp_is_finite(cls, value: float) -> float:
        return _require_finite(value, "vod_timestamp_s")

    @field_validator("evidence")
    @classmethod
    def killfeed_evidence_not_blank(cls, values: list[str]) -> list[str]:
        return [_require_identifier(value, "evidence") for value in values]


class FusedAliveState(PersistentModel):
    """Derived alive state with evidence; unresolved conflicts remain unknown."""

    schema_version: Literal["1.0"] = "1.0"
    player_id: str = Field(min_length=1)
    round_id: str = Field(min_length=1)
    vod_timestamp_s: float = Field(ge=0.0)
    state: AliveState
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(min_length=1)
    rejection_reason: str | None = None

    @field_validator("player_id", "round_id")
    @classmethod
    def fused_alive_ids_not_blank(cls, value: str, info: Any) -> str:
        return _require_identifier(value, info.field_name)

    @field_validator("vod_timestamp_s", "confidence")
    @classmethod
    def fused_alive_values_are_finite(cls, value: float, info: Any) -> float:
        return _require_finite(value, info.field_name)

    @field_validator("evidence")
    @classmethod
    def fused_alive_evidence_not_blank(cls, values: list[str]) -> list[str]:
        return [_require_identifier(value, "evidence") for value in values]

    @model_validator(mode="after")
    def unknown_state_has_reason(self) -> FusedAliveState:
        if self.state == AliveState.UNKNOWN and not self.rejection_reason:
            raise ValueError("unknown alive states require a rejection reason")
        if self.state != AliveState.UNKNOWN and self.rejection_reason is not None:
            raise ValueError("known alive states cannot have a rejection reason")
        return self


class BroadcastPhase(str, Enum):
    LIVE = "live"
    REPLAY = "replay"
    PAUSED = "paused"
    HIDDEN = "hidden"
    UNKNOWN = "unknown"


class BroadcastFrameObservation(PersistentModel):
    """Raw broadcast-state evidence for one sampled VOD frame."""

    schema_version: Literal["1.0"] = "1.0"
    vod_timestamp_s: float = Field(ge=0.0)
    round_id: str | None = None
    phase: BroadcastPhase = BroadcastPhase.UNKNOWN
    minimap_visible: bool
    hud_visible: bool
    replay_cue: bool = False
    timer_continuous: bool = False
    score_continuous: bool = False
    historical_duplicate: bool = False
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)

    @field_validator("vod_timestamp_s", "confidence")
    @classmethod
    def broadcast_values_are_finite(cls, value: float, info: Any) -> float:
        return _require_finite(value, info.field_name)

    @field_validator("round_id")
    @classmethod
    def broadcast_round_id_not_blank(cls, value: str | None) -> str | None:
        return None if value is None else _require_identifier(value, "round_id")

    @field_validator("evidence")
    @classmethod
    def broadcast_evidence_not_blank(cls, values: list[str]) -> list[str]:
        return [_require_identifier(value, "evidence") for value in values]


class BroadcastInterval(PersistentModel):
    """Classified broadcast interval; rejected states carry explicit reasons."""

    schema_version: Literal["1.0"] = "1.0"
    vod_timestamp_s: float = Field(ge=0.0)
    round_id: str | None = None
    phase: BroadcastPhase
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(min_length=1)
    rejection_reason: str | None = None

    @model_validator(mode="after")
    def rejection_matches_phase(self) -> BroadcastInterval:
        if (self.phase == BroadcastPhase.LIVE) == (self.rejection_reason is not None):
            raise ValueError(
                "live intervals cannot have a rejection reason; rejected intervals require one"
            )
        return self


class TrackSmoothingInput(PersistentModel):
    """Raw track estimate with the verified context needed for safe smoothing."""

    schema_version: Literal["1.0"] = "1.0"
    estimate: PlayerTrackEstimate
    round_id: str | None = None
    alive: bool | None = None
    interval_state: Literal["live", "replay", "paused", "hidden", "unknown"] = "unknown"
    teleport_before: bool = False
    context_evidence: list[str] = Field(default_factory=list)

    @field_validator("round_id")
    @classmethod
    def smoothing_round_id_not_blank(cls, value: str | None) -> str | None:
        return None if value is None else _require_identifier(value, "round_id")

    @field_validator("context_evidence")
    @classmethod
    def smoothing_context_evidence_not_blank(cls, values: list[str]) -> list[str]:
        return [_require_identifier(value, "context_evidence") for value in values]


class ZoneTransitionEvent(PersistentModel):
    """Derived zone boundary event referencing one raw observed estimate."""

    schema_version: Literal["1.0"] = "1.0"
    map_id: str = Field(min_length=1)
    map_config_version: str = Field(min_length=1)
    player_id: str = Field(min_length=1)
    round_id: str = Field(min_length=1)
    vod_timestamp_s: float = Field(ge=0.0)
    event_type: Literal["enter", "leave"]
    zone_id: str = Field(min_length=1)
    position: NormalizedPoint
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(min_length=1)

    @field_validator("map_id", "map_config_version", "player_id", "round_id", "zone_id")
    @classmethod
    def zone_event_identifiers_not_blank(cls, value: str, info: Any) -> str:
        return _require_identifier(value, info.field_name)

    @field_validator("vod_timestamp_s", "confidence")
    @classmethod
    def zone_event_numbers_are_finite(cls, value: float, info: Any) -> float:
        return _require_finite(value, info.field_name)

    @field_validator("evidence")
    @classmethod
    def zone_event_evidence_not_blank(cls, values: list[str]) -> list[str]:
        return [_require_identifier(value, "evidence") for value in values]


class SmoothedTrackSample(PersistentModel):
    """Derived location that retains its raw estimate and smoothing evidence."""

    schema_version: Literal["1.0"] = "1.0"
    raw_estimate: PlayerTrackEstimate
    position: NormalizedPoint | None = None
    observed: bool
    interpolated: bool = False
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(min_length=1)
    rejection_reason: str | None = None

    @field_validator("confidence")
    @classmethod
    def smoothing_confidence_is_finite(cls, value: float) -> float:
        return _require_finite(value, "confidence")

    @field_validator("evidence")
    @classmethod
    def smoothing_evidence_not_blank(cls, values: list[str]) -> list[str]:
        return [_require_identifier(value, "evidence") for value in values]

    @model_validator(mode="after")
    def smoothing_state_is_coherent(self) -> SmoothedTrackSample:
        if self.position is None:
            if (
                self.observed
                or self.interpolated
                or self.confidence != 0.0
                or not self.rejection_reason
            ):
                raise ValueError("unknown smoothed samples require zero confidence and a reason")
        elif self.observed == self.interpolated or self.rejection_reason is not None:
            raise ValueError("smoothed positions must be observed or interpolated")
        if self.observed and not self.raw_estimate.observed:
            raise ValueError("smoothed observations must retain an observed raw estimate")
        if self.interpolated and self.raw_estimate.position is not None:
            raise ValueError("interpolated samples must retain a positionless raw estimate")
        return self


class PlayerTrackArtifactRow(PersistentModel):
    """Flattened Parquet row retaining both raw and derived track records."""

    schema_version: Literal["1.0"] = "1.0"
    match_id: str = Field(min_length=1)
    map_id: str = Field(min_length=1)
    round_id: str = Field(min_length=1)
    vod_timestamp_s: float = Field(ge=0.0)
    player_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    team_id: str = Field(min_length=1)
    side: Side
    x: float | None = Field(default=None, ge=0.0, le=1.0)
    y: float | None = Field(default=None, ge=0.0, le=1.0)
    observed: bool
    interpolated: bool
    confidence: float = Field(ge=0.0, le=1.0)
    rejection_reason: str | None = None
    raw_estimate_json: str
    raw_evidence_json: str
    derived_evidence_json: str

    @field_validator("match_id", "map_id", "round_id", "player_id", "agent_id", "team_id")
    @classmethod
    def artifact_identifiers_not_blank(cls, value: str, info: Any) -> str:
        return _require_identifier(value, info.field_name)

    @field_validator("vod_timestamp_s", "confidence", "x", "y")
    @classmethod
    def artifact_numbers_are_finite(cls, value: float | None, info: Any) -> float | None:
        return None if value is None else _require_finite(value, info.field_name)

    @model_validator(mode="after")
    def artifact_row_is_coherent(self) -> PlayerTrackArtifactRow:
        if (self.x is None) != (self.y is None):
            raise ValueError("track artifact coordinates must both be present or absent")
        if self.x is None and not self.rejection_reason:
            raise ValueError("positionless artifact rows require a rejection reason")
        if self.interpolated and self.observed:
            raise ValueError("interpolated artifact rows cannot be observed")
        return self


class TrackIdentityLabel(PersistentModel):
    """Reviewed ground-truth identity for one visible candidate at one frame."""

    schema_version: Literal["1.0"] = "1.0"
    match_id: str = Field(min_length=1)
    round_id: str = Field(min_length=1)
    vod_timestamp_s: float = Field(ge=0.0)
    candidate_id: str = Field(min_length=1)
    expected_player_id: str | None = None
    visible: bool

    @field_validator("match_id", "round_id", "candidate_id")
    @classmethod
    def label_identifiers_not_blank(cls, value: str, info: Any) -> str:
        return _require_identifier(value, info.field_name)

    @field_validator("vod_timestamp_s")
    @classmethod
    def label_timestamp_is_finite(cls, value: float) -> float:
        return _require_finite(value, "vod_timestamp_s")


class TrackIdentityPrediction(PersistentModel):
    """One evaluated identity output at a labeled candidate/frame."""

    schema_version: Literal["1.0"] = "1.0"
    match_id: str = Field(min_length=1)
    round_id: str = Field(min_length=1)
    vod_timestamp_s: float = Field(ge=0.0)
    candidate_id: str = Field(min_length=1)
    assigned_player_id: str | None = None

    @field_validator("match_id", "round_id", "candidate_id", "assigned_player_id")
    @classmethod
    def prediction_identifiers_not_blank(cls, value: str | None, info: Any) -> str | None:
        return None if value is None else _require_identifier(value, info.field_name)

    @field_validator("vod_timestamp_s")
    @classmethod
    def prediction_timestamp_is_finite(cls, value: float) -> float:
        return _require_finite(value, "vod_timestamp_s")


class TrackDiagnosticMetrics(PersistentModel):
    """Identity/coverage measurements or an explicit unavailable result."""

    schema_version: Literal["1.0"] = "1.0"
    available: bool
    labeled_visible_count: int | None = Field(default=None, ge=0)
    identity_accuracy: float | None = Field(default=None, ge=0.0, le=1.0)
    visible_player_coverage: float | None = Field(default=None, ge=0.0, le=1.0)
    identity_switches: int | None = Field(default=None, ge=0)
    reason: str | None = None

    @model_validator(mode="after")
    def metrics_match_availability(self) -> TrackDiagnosticMetrics:
        values = (
            self.labeled_visible_count,
            self.identity_accuracy,
            self.visible_player_coverage,
            self.identity_switches,
        )
        if self.available and (any(value is None for value in values) or self.reason is not None):
            raise ValueError("available metrics require values and no unavailable reason")
        if not self.available and (any(value is not None for value in values) or not self.reason):
            raise ValueError("unavailable metrics require a reason and no values")
        return self


class SmokeRegionState(str, Enum):
    CLEAR = "clear"
    OCCUPIED = "occupied"
    UNKNOWN = "unknown"


class SmokeRegionObservation(PersistentModel):
    """Raw, scoped observation of one fully or partially observed smoke region."""

    schema_version: Literal["1.0"] = "1.0"
    match_id: str = Field(min_length=1)
    map_id: str = Field(min_length=1)
    round_id: str = Field(min_length=1)
    vod_timestamp_s: float = Field(ge=0.0)
    center: NormalizedPoint
    approximate_radius: float = Field(gt=0.0, le=1.0)
    state: SmokeRegionState
    live_visible: bool
    fully_observable: bool
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[EvidenceRef] = Field(min_length=1)

    @field_validator("match_id", "map_id", "round_id")
    @classmethod
    def region_identifiers_not_blank(cls, value: str, info: Any) -> str:
        return _require_identifier(value, info.field_name)

    @field_validator("vod_timestamp_s", "approximate_radius", "confidence")
    @classmethod
    def region_measurements_are_finite(cls, value: float, info: Any) -> float:
        return _require_finite(value, info.field_name)

    @model_validator(mode="after")
    def evidence_matches_scope(self) -> SmokeRegionObservation:
        _validate_evidence_scope(self.match_id, self.map_id, self.round_id, self.evidence)
        if any(item.vod_timestamp_s != self.vod_timestamp_s for item in self.evidence):
            raise ValueError("smoke region evidence timestamp must match observation")
        return self


class SmokeFrameObservation(PersistentModel):
    """Raw live minimap frame with smoke candidates or verified clear regions."""

    schema_version: Literal["1.0"] = "1.0"
    match_id: str = Field(min_length=1)
    map_id: str = Field(min_length=1)
    round_id: str = Field(min_length=1)
    vod_timestamp_s: float = Field(ge=0.0)
    source: EvidenceSource = EvidenceSource.MINIMAP
    evidence: list[EvidenceRef] = Field(min_length=1)
    live_visible: bool
    active_region_clear: bool
    candidates: list[SmokeCandidate] = Field(default_factory=list)

    @model_validator(mode="after")
    def frame_evidence_matches_scope(self) -> SmokeFrameObservation:
        _validate_evidence_scope(self.match_id, self.map_id, self.round_id, self.evidence)
        if any(item.vod_timestamp_s != self.vod_timestamp_s for item in self.evidence):
            raise ValueError("smoke frame evidence timestamp must match observation")
        if any(
            (item.match_id, item.map_id, item.round_id, item.vod_timestamp_s)
            != (self.match_id, self.map_id, self.round_id, self.vod_timestamp_s)
            for item in self.candidates
        ):
            raise ValueError("smoke frame candidates must match frame scope and timestamp")
        if self.active_region_clear and self.candidates:
            raise ValueError("a clear smoke frame cannot contain candidates")
        return self


class SmokeCandidate(PersistentModel):
    """Raw circular-smoke appearance observation, independent of lifecycle inference."""

    schema_version: Literal["1.0"] = "1.0"
    match_id: str = Field(min_length=1)
    map_id: str = Field(min_length=1)
    round_id: str = Field(min_length=1)
    vod_timestamp_s: float = Field(ge=0.0)
    center: NormalizedPoint
    approximate_radius: float = Field(gt=0.0, le=1.0)
    agent_type: str | None = None
    source: EvidenceSource
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[EvidenceRef] = Field(min_length=1)
    live_visible: bool

    @field_validator("match_id", "map_id", "round_id", "agent_type")
    @classmethod
    def smoke_identifiers_not_blank(cls, value: str | None, info: Any) -> str | None:
        return None if value is None else _require_identifier(value, info.field_name)

    @field_validator("vod_timestamp_s", "approximate_radius", "confidence")
    @classmethod
    def smoke_measurements_are_finite(cls, value: float, info: Any) -> float:
        return _require_finite(value, info.field_name)

    @model_validator(mode="after")
    def evidence_matches_scope(self) -> SmokeCandidate:
        _validate_evidence_scope(self.match_id, self.map_id, self.round_id, self.evidence)
        if any(item.vod_timestamp_s != self.vod_timestamp_s for item in self.evidence):
            raise ValueError("smoke candidate evidence timestamp must match observation")
        return self


class SmokeEvent(PersistentModel):
    """Derived smoke lifecycle with observed active windows and overlap references."""

    schema_version: Literal["1.0"] = "1.0"
    event_id: str = Field(min_length=1)
    match_id: str = Field(min_length=1)
    map_id: str = Field(min_length=1)
    round_id: str = Field(min_length=1)
    center: NormalizedPoint
    approximate_radius: float = Field(gt=0.0, le=1.0)
    agent_type: str | None = None
    appeared_at_s: float = Field(ge=0.0)
    last_seen_at_s: float = Field(ge=0.0)
    disappeared_at_s: float | None = Field(default=None, ge=0.0)
    active_windows: list[list[float]] = Field(min_length=1)
    overlaps_event_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[EvidenceRef] = Field(min_length=1)

    @model_validator(mode="after")
    def lifecycle_is_consistent(self) -> SmokeEvent:
        _require_identifier(self.event_id, "event_id")
        _require_identifier(self.match_id, "match_id")
        _require_identifier(self.map_id, "map_id")
        _require_identifier(self.round_id, "round_id")
        if self.agent_type is not None:
            _require_identifier(self.agent_type, "agent_type")
        if self.last_seen_at_s < self.appeared_at_s:
            raise ValueError("last seen cannot precede appearance")
        if self.disappeared_at_s is not None and self.disappeared_at_s < self.last_seen_at_s:
            raise ValueError("disappearance cannot precede last seen")
        if any(len(window) != 2 or window[1] < window[0] for window in self.active_windows):
            raise ValueError("active windows must be ordered [start, end] pairs")
        _validate_evidence_scope(self.match_id, self.map_id, self.round_id, self.evidence)
        return self


class AbilityChargeDelta(PersistentModel):
    """Raw in-round HUD charge decrease observation, before utility association."""

    schema_version: Literal["1.0"] = "1.0"
    observation_id: str = Field(min_length=1)
    match_id: str | None = None
    map_id: str | None = None
    round_id: str | None = None
    vod_timestamp_s: float = Field(ge=0.0)
    ability_id: str = Field(min_length=1)
    previous_charges: int = Field(ge=0)
    current_charges: int = Field(ge=0)
    player_id: str | None = None
    agent_id: str | None = None
    team_id: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[EvidenceRef] = Field(min_length=1)
    previous_evidence: EvidenceRef | None = None

    @model_validator(mode="after")
    def charge_decreased_and_evidence_scoped(self) -> AbilityChargeDelta:
        _require_identifier(self.observation_id, "observation_id")
        _require_identifier(self.ability_id, "ability_id")
        if self.current_charges >= self.previous_charges:
            raise ValueError("charge observation must represent a decrease")
        if self.match_id is not None and self.map_id is not None and self.round_id is not None:
            _validate_evidence_scope(self.match_id, self.map_id, self.round_id, self.evidence)
        elif any(reference.source != EvidenceSource.PLAYER_HUD for reference in self.evidence):
            raise ValueError("unscoped charge evidence must come from player HUD")
        if any(reference.vod_timestamp_s != self.vod_timestamp_s for reference in self.evidence):
            raise ValueError("charge evidence timestamp must match observation")
        if self.previous_evidence is not None:
            if self.previous_evidence.source != EvidenceSource.PLAYER_HUD:
                raise ValueError("previous charge evidence must come from player HUD")
            if self.previous_evidence.vod_timestamp_s >= self.vod_timestamp_s:
                raise ValueError("previous charge evidence timestamp must precede observation")
            if self.match_id is not None and self.map_id is not None and self.round_id is not None:
                _validate_evidence_scope(
                    self.match_id, self.map_id, self.round_id, [self.previous_evidence]
                )
        return self


class UtilityAssociation(PersistentModel):
    """Derived relation between a charge decrease and spatial utility appearance."""

    schema_version: Literal["1.0"] = "1.0"
    association_id: str = Field(min_length=1)
    match_id: str = Field(min_length=1)
    map_id: str = Field(min_length=1)
    round_id: str = Field(min_length=1)
    observation_id: str = Field(min_length=1)
    utility_event_id: str = Field(min_length=1)
    ability_id: str = Field(min_length=1)
    player_id: str | None = None
    team_id: str = Field(min_length=1)
    observed: bool
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[EvidenceRef] = Field(min_length=2)
    diagnostic: str | None = None

    @model_validator(mode="after")
    def association_evidence_is_scoped(self) -> UtilityAssociation:
        _validate_evidence_scope(self.match_id, self.map_id, self.round_id, self.evidence)
        if self.observed == (self.diagnostic is not None):
            raise ValueError("observed associations must not have inference diagnostics")
        return self


class UtilityEvent(PersistentModel):
    """Observed or inferred utility event with supporting evidence."""

    schema_version: Literal["1.0"] = "1.0"
    match_id: str = Field(min_length=1)
    map_id: str = Field(min_length=1)
    round_id: str = Field(min_length=1)
    vod_timestamp_s: float = Field(ge=0.0)
    player_id: str | None = None
    agent_id: str | None = None
    team_id: str = Field(min_length=1)
    ability_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    center: NormalizedPoint | None = None
    geometry: dict[str, JsonValue] | None = None
    observed: bool
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[EvidenceRef] = Field(min_length=1)

    @field_validator(
        "match_id",
        "map_id",
        "round_id",
        "player_id",
        "agent_id",
        "team_id",
        "ability_id",
        "event_type",
    )
    @classmethod
    def identifiers_not_blank(cls, value: str | None, info: Any) -> str | None:
        if value is not None:
            return _require_identifier(value, info.field_name)
        return value

    @field_validator("vod_timestamp_s", "confidence")
    @classmethod
    def numeric_values_are_finite(cls, value: float, info: Any) -> float:
        return _require_finite(value, info.field_name)

    @field_validator("geometry")
    @classmethod
    def geometry_values_are_json_safe(
        cls, value: dict[str, JsonValue] | None
    ) -> dict[str, JsonValue] | None:
        if value is not None:
            _validate_json_values(value, "geometry")
        return value

    @model_validator(mode="after")
    def evidence_matches_event_scope(self) -> UtilityEvent:
        _validate_evidence_scope(self.match_id, self.map_id, self.round_id, self.evidence)
        return self


class ScenarioQuery(PersistentModel):
    """Deterministic structured filters for selecting round scenarios."""

    schema_version: Literal["1.0"] = "1.0"
    map_ids: list[str] = Field(default_factory=list)
    team_ids: list[str] = Field(default_factory=list)
    sides: list[Side] = Field(default_factory=list)
    round_numbers: list[int] = Field(default_factory=list)
    buy_classes: list[str] = Field(default_factory=list)
    min_display_clock_s: float | None = Field(default=None, ge=0.0)
    max_display_clock_s: float | None = Field(default=None, ge=0.0)
    alive_attack: int | None = Field(default=None, ge=0, le=5)
    alive_defense: int | None = Field(default=None, ge=0, le=5)
    required_control_zones: list[str] = Field(default_factory=list)
    excluded_control_zones: list[str] = Field(default_factory=list)
    spike_states: list[str] = Field(default_factory=list)
    opening_duel_outcomes: list[str] = Field(default_factory=list)
    required_utility_ids: list[str] = Field(default_factory=list)
    phases: list[str] = Field(default_factory=list)
    confidence_floor: float = Field(default=0.75, ge=0.0, le=1.0)

    @field_validator(
        "map_ids",
        "team_ids",
        "buy_classes",
        "required_control_zones",
        "excluded_control_zones",
        "spike_states",
        "opening_duel_outcomes",
        "required_utility_ids",
        "phases",
    )
    @classmethod
    def query_identifiers_not_blank(cls, values: list[str], info: Any) -> list[str]:
        return [_require_identifier(value, info.field_name) for value in values]

    @field_validator("round_numbers")
    @classmethod
    def round_numbers_positive(cls, values: list[int]) -> list[int]:
        if any(value < 1 for value in values):
            raise ValueError("round numbers must be positive")
        return values

    @field_validator("min_display_clock_s", "max_display_clock_s", "confidence_floor")
    @classmethod
    def query_numbers_finite(cls, value: float | None, info: Any) -> float | None:
        if value is not None:
            return _require_finite(value, info.field_name)
        return value

    @model_validator(mode="after")
    def display_clock_range_is_ordered(self) -> ScenarioQuery:
        if (
            self.min_display_clock_s is not None
            and self.max_display_clock_s is not None
            and self.min_display_clock_s > self.max_display_clock_s
        ):
            raise ValueError("minimum display clock exceeds maximum")
        return self


class PatternSummary(PersistentModel):
    """Structured analytical summary; narrative is supplemental, not primary."""

    schema_version: Literal["1.0"] = "1.0"
    pattern_id: str = Field(min_length=1)
    scenario_query: ScenarioQuery
    sample_size: int = Field(ge=0)
    matching_round_ids: list[str]
    representative_round_ids: list[str]
    outlier_round_ids: list[str]
    zone_occupancy_over_time: dict[str, JsonValue]
    common_transition_sequences: list[list[str]]
    rotation_timing_distribution: dict[str, JsonValue]
    utility_timing_distribution: dict[str, JsonValue]
    formation_distribution: dict[str, JsonValue]
    outcome_distribution: dict[str, JsonValue]
    confidence_summary: dict[str, JsonValue]
    evidence_refs: list[EvidenceRef] = Field(min_length=1)
    narrative: str | None = None

    @field_validator("pattern_id")
    @classmethod
    def pattern_id_not_blank(cls, value: str) -> str:
        return _require_identifier(value, "pattern_id")

    @field_validator(
        "zone_occupancy_over_time",
        "rotation_timing_distribution",
        "utility_timing_distribution",
        "formation_distribution",
        "outcome_distribution",
        "confidence_summary",
    )
    @classmethod
    def aggregate_values_are_json_safe(
        cls, value: dict[str, JsonValue], info: Any
    ) -> dict[str, JsonValue]:
        _validate_json_values(value, info.field_name)
        return value

    @field_validator("matching_round_ids", "representative_round_ids", "outlier_round_ids")
    @classmethod
    def round_ids_not_blank(cls, values: list[str], info: Any) -> list[str]:
        return [_require_identifier(value, info.field_name) for value in values]

    @model_validator(mode="after")
    def sample_size_matches_rounds(self) -> PatternSummary:
        if self.sample_size != len(self.matching_round_ids):
            raise ValueError("sample_size must match matching_round_ids length")
        if not set(self.representative_round_ids).issubset(self.matching_round_ids):
            raise ValueError("representative rounds must be matching rounds")
        if not set(self.outlier_round_ids).issubset(self.matching_round_ids):
            raise ValueError("outlier rounds must be matching rounds")
        return self
