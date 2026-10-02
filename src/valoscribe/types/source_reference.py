"""Typed contracts for frozen source labels and scoped identity evaluation."""

from __future__ import annotations

import math
from fractions import Fraction
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

_SHA256 = r"^[0-9a-f]{64}$"


class SourceReferenceFrame(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    frame_index: int = Field(ge=0)
    source_pts: int = Field(ge=0)


class SplitRoundRecord(BaseModel):
    """Reviewed source-bound allocation/custody declaration, not proof of external truth."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_video_sha256: str = Field(pattern=_SHA256)
    match_id: str = Field(min_length=1)
    round_id: str = Field(min_length=1)
    split: Literal["development", "validation", "test"]
    lifecycle: Literal["active", "retired"] = "active"
    start_frame_index: int = Field(ge=0)
    end_frame_index: int = Field(gt=0)
    start_source_pts: int = Field(ge=0)
    end_source_pts: int = Field(gt=0)
    timebase_numerator: int = Field(gt=0)
    timebase_denominator: int = Field(gt=0)
    inventory_digest: str = Field(pattern=_SHA256)
    prior_exposure: Literal["none", "development", "validation", "test", "unknown"]
    custody_record_sha256: str = Field(pattern=_SHA256)
    custody_review_evidence: list[str] = Field(min_length=1)
    allocation_reviewer_id: str = Field(min_length=1)
    independent_reviewer_id: str = Field(min_length=1)
    test_retirement_record_sha256: str | None = Field(default=None, pattern=_SHA256)

    @model_validator(mode="after")
    def valid_record(self) -> SplitRoundRecord:
        if (
            self.end_frame_index < self.start_frame_index
            or self.end_source_pts <= self.start_source_pts
        ):
            raise ValueError("split allocation interval bounds are invalid")
        if self.allocation_reviewer_id == self.independent_reviewer_id:
            raise ValueError("split custody review must be independent")
        if self.split == "test" and self.lifecycle == "active" and self.prior_exposure != "none":
            raise ValueError("test interval has prior exposure and must be retired")
        if (
            self.lifecycle == "retired"
            and self.split == "test"
            and self.test_retirement_record_sha256 is None
        ):
            raise ValueError("retired test interval requires retirement record")
        return self


class SourceSplitAllocation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rounds: list[SplitRoundRecord] = Field(min_length=6)
    retired_test_intervals: list[SplitRoundRecord] = Field(default_factory=list)

    @model_validator(mode="after")
    def disjoint_certified_intervals(self) -> SourceSplitAllocation:
        try:
            records = [
                SplitRoundRecord.model_validate(record.model_dump(mode="python"))
                for record in self.rounds
            ]
            retired = [
                SplitRoundRecord.model_validate(record.model_dump(mode="python"))
                for record in self.retired_test_intervals
            ]
        except (ValidationError, AttributeError, TypeError) as error:
            raise ValueError("invalid split interval record") from error
        if any(record.split != "test" or record.lifecycle != "retired" for record in retired):
            raise ValueError("retired test interval list accepts only retired test records")
        active = [record for record in records if record.lifecycle == "active"]
        identities_by_split = {
            split: {
                (record.match_id, record.round_id) for record in active if record.split == split
            }
            for split in ("development", "validation", "test")
        }
        counts = {split: len(identities) for split, identities in identities_by_split.items()}
        if counts != {"development": 3, "validation": 2, "test": 1} and not (
            counts["development"] >= 3 and counts["validation"] >= 2 and counts["test"] >= 1
        ):
            raise ValueError(
                "split allocation requires at least 3 development, 2 validation, 1 test rounds"
            )
        all_records = [*records, *retired]
        round_identities: set[tuple[str, str]] = set()
        for record in all_records:
            identity = (record.match_id, record.round_id)
            if identity in round_identities:
                raise ValueError("duplicate active round identity across split allocation")
            round_identities.add(identity)
        keys: set[tuple[str, str, str, int, int]] = set()
        for index, left in enumerate(all_records):
            key = (
                left.source_video_sha256,
                left.match_id,
                left.round_id,
                left.start_frame_index,
                left.end_frame_index,
            )
            if key in keys:
                raise ValueError("duplicate or reused split allocation record")
            keys.add(key)
            for right in all_records[index + 1 :]:
                if left.source_video_sha256 != right.source_video_sha256:
                    continue
                if (left.timebase_numerator, left.timebase_denominator) != (
                    right.timebase_numerator,
                    right.timebase_denominator,
                ):
                    raise ValueError("one source hash cannot have conflicting timebases")
                pts_overlap = max(left.start_source_pts, right.start_source_pts) < min(
                    left.end_source_pts, right.end_source_pts
                )
                frame_overlap = max(left.start_frame_index, right.start_frame_index) <= min(
                    left.end_frame_index, right.end_frame_index
                )
                if pts_overlap or frame_overlap:
                    raise ValueError(
                        "split source/frame/PTS intervals overlap or reuse test material"
                    )
        return self


class SourceJoinProtocol(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    algorithm: Literal["bbox_iou_exact_frame_v1"] = "bbox_iou_exact_frame_v1"
    threshold_iou: float = Field(gt=0, le=1)
    tie_policy: Literal["ambiguous_all_candidates"] = "ambiguous_all_candidates"
    approval_record_sha256: str = Field(pattern=_SHA256)
    approval_evidence: list[str] = Field(min_length=1)
    development_reference_digest: str = Field(pattern=_SHA256)
    reviewer_id: str = Field(min_length=1)
    independent_reviewer_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def independent_approval(self) -> SourceJoinProtocol:
        if self.reviewer_id == self.independent_reviewer_id:
            raise ValueError("join protocol approval requires independent development review")
        return self


class SourceReferenceManifest(BaseModel):
    """Source inventory, pre-prediction split, and pre-approved join protocol."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["2.0"] = "2.0"
    source_video_sha256: str = Field(pattern=_SHA256)
    match_id: str = Field(min_length=1)
    map_id: str = Field(min_length=1)
    round_id: str = Field(min_length=1)
    split: Literal["development", "validation", "test"]
    timestamp_kind: Literal["pts"]
    start_frame_index: int = Field(ge=0)
    end_frame_index: int = Field(gt=0)
    timebase_numerator: int = Field(gt=0)
    timebase_denominator: int = Field(gt=0)
    source_width: int = Field(gt=0)
    source_height: int = Field(gt=0)
    frames: list[SourceReferenceFrame] = Field(min_length=2)
    allocation: SourceSplitAllocation
    join_protocol: SourceJoinProtocol
    inventory_review_record_sha256: str = Field(pattern=_SHA256)
    inventory_review_evidence: list[str] = Field(min_length=1)
    inventory_reviewer: str = Field(min_length=1)
    inventory_independent_reviewer: str = Field(min_length=1)
    inventory_adjudicator: str = Field(min_length=1)
    live_frame_indices: list[int]
    reviewed_annotation_frame_indices: list[int]
    nonlive_frame_indices: list[int]
    unknown_context_frame_indices: list[int]

    @model_validator(mode="after")
    def inventory_and_split(self) -> SourceReferenceManifest:
        if self.end_frame_index < self.start_frame_index:
            raise ValueError("round frame bounds are reversed")
        expected_indices = list(range(self.start_frame_index, self.end_frame_index + 1))
        if [frame.frame_index for frame in self.frames] != expected_indices:
            raise ValueError("source inventory must be complete and sequential inside round bounds")
        pts = [frame.source_pts for frame in self.frames]
        if any(right <= left for left, right in zip(pts, pts[1:])):
            raise ValueError("source PTS inventory must be strictly increasing")
        contexts = [
            self.live_frame_indices,
            self.nonlive_frame_indices,
            self.unknown_context_frame_indices,
        ]
        flattened = [index for group in contexts for index in group]
        if len(flattened) != len(set(flattened)) or sorted(flattened) != expected_indices:
            raise ValueError("source context frame classification must be disjoint and exhaustive")
        if sorted(self.reviewed_annotation_frame_indices) != sorted(self.live_frame_indices):
            raise ValueError("visible-player annotation review must cover each reviewed live frame")
        inventory_reviewers = {
            self.inventory_reviewer,
            self.inventory_independent_reviewer,
            self.inventory_adjudicator,
        }
        if len(inventory_reviewers) != 3:
            raise ValueError("source inventory review and adjudication must be independent")
        key = (self.source_video_sha256, self.match_id, self.round_id, self.split)
        allocation_rows = [row for row in self.allocation.rounds if row.lifecycle == "active"]
        matches = [
            row
            for row in allocation_rows
            if (row.source_video_sha256, row.match_id, row.round_id, row.split) == key
        ]
        if len(matches) != 1:
            raise ValueError("round source/split allocation must have exactly one certified record")
        allocation = matches[0]
        if (
            allocation.start_frame_index,
            allocation.end_frame_index,
            allocation.start_source_pts,
            allocation.end_source_pts,
            allocation.timebase_numerator,
            allocation.timebase_denominator,
        ) != (
            self.start_frame_index,
            self.end_frame_index,
            self.frames[0].source_pts,
            self.frames[-1].source_pts,
            self.timebase_numerator,
            self.timebase_denominator,
        ):
            raise ValueError("manifest bounds do not match certified split allocation")
        return self


class SourcePlayerReferenceObservation(BaseModel):
    """Source-only marker claims with independent review and explicit uncertainty."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_video_sha256: str = Field(pattern=_SHA256)
    match_id: str = Field(min_length=1)
    map_id: str = Field(min_length=1)
    round_id: str = Field(min_length=1)
    frame_index: int = Field(ge=0)
    source_pts: int = Field(ge=0)
    interval_end_source_pts: int = Field(gt=0)
    timebase_numerator: int = Field(gt=0)
    timebase_denominator: int = Field(gt=0)
    annotation_id: str = Field(min_length=1)
    coordinate_frame: Literal["source_frame_normalized"]
    bbox: tuple[float, float, float, float]
    marker_class: Literal["player", "non_player", "class_uncertain"]
    marker_collision_resolution: Literal["none", "reviewed_distinct", "unresolved"] = "none"
    marker_collision_evidence: list[str] = Field(default_factory=list)
    expected_player_id: str | None = None
    identity_confidence: float | None = Field(default=None, ge=0, le=1)
    identity_evidence: list[str] = Field(default_factory=list)
    claim_confidence: float = Field(ge=0, le=1)
    claim_evidence: list[str] = Field(min_length=1)
    annotation_scope: Literal["source_only"]
    reviewer_kind: Literal["human", "ai"]
    reviewer_id: str = Field(min_length=1)
    reviewer_version: str = Field(min_length=1)
    independent_reviewer_kind: Literal["human", "ai"]
    independent_reviewer_id: str = Field(min_length=1)
    independent_reviewer_version: str = Field(min_length=1)
    adjudicator_kind: Literal["human", "ai"]
    adjudicator_id: str = Field(min_length=1)
    adjudicator_version: str = Field(min_length=1)
    adjudication_evidence: list[str] = Field(min_length=1)
    blind_review_record_sha256: str = Field(pattern=_SHA256)
    disagreement_disposition: Literal["agreement", "adjudicated", "unresolved"]
    continuity_before: Literal["continuous", "death", "replay", "unsupported_gap", "unknown"]
    continuity_evidence: list[str] = Field(min_length=1)
    reference_label_scope: Literal["ai_reviewed_not_human_gold"]

    @model_validator(mode="after")
    def valid_claim(self) -> SourcePlayerReferenceObservation:
        x, y, width, height = self.bbox
        if not all(math.isfinite(value) for value in self.bbox):
            raise ValueError("source reference bbox must be finite")
        if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > 1 or y + height > 1:
            raise ValueError("source reference bbox must be inside normalized frame bounds")
        if self.marker_class != "player" and self.expected_player_id is not None:
            raise ValueError("non-player or uncertain marker cannot establish player identity")
        if self.expected_player_id is not None and (
            self.identity_confidence is None or not self.identity_evidence
        ):
            raise ValueError("established identity claim requires confidence and evidence")
        if self.expected_player_id is None and self.identity_confidence is not None:
            raise ValueError("unknown identity cannot carry established-identity confidence")
        if len({self.reviewer_id, self.independent_reviewer_id, self.adjudicator_id}) != 3:
            raise ValueError("source review and adjudication provenance must be independent")
        if self.marker_collision_resolution != "none" and not self.marker_collision_evidence:
            raise ValueError("marker collision disposition requires review evidence")
        if self.disagreement_disposition == "unresolved" and self.expected_player_id is not None:
            raise ValueError("unresolved identity claim must remain unknown")
        return self

    @property
    def duration_seconds(self) -> Fraction:
        return Fraction(
            (self.interval_end_source_pts - self.source_pts) * self.timebase_numerator,
            self.timebase_denominator,
        )


class ReferenceCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_video_sha256: str = Field(pattern=_SHA256)
    frame_index: int = Field(ge=0)
    source_pts: int = Field(ge=0)
    timebase_numerator: int = Field(gt=0)
    timebase_denominator: int = Field(gt=0)
    coordinate_frame: Literal["source_frame_normalized"]
    candidate_id: str = Field(min_length=1)
    bbox: tuple[float, float, float, float]

    @model_validator(mode="after")
    def valid_bounds(self) -> ReferenceCandidate:
        x, y, width, height = self.bbox
        if (
            not all(math.isfinite(value) for value in self.bbox)
            or x < 0
            or y < 0
            or width <= 0
            or height <= 0
            or x + width > 1
            or y + height > 1
        ):
            raise ValueError("raw candidate bbox must be inside normalized frame bounds")
        return self


class ReferenceCandidateJoin(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    annotation_id: str = Field(min_length=1)
    frame_index: int = Field(ge=0)
    source_video_sha256: str = Field(pattern=_SHA256)
    source_reference_digest: str = Field(pattern=_SHA256)
    candidate_run_digest: str = Field(pattern=_SHA256)
    raw_candidate_digest: str = Field(pattern=_SHA256)
    join_protocol_digest: str = Field(pattern=_SHA256)
    candidate_id: str | None = None
    geometric_overlap: float | None = Field(default=None, ge=0, le=1)
    status: Literal["matched", "unmatched", "ambiguous"]


class FrozenSourceReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest: SourceReferenceManifest
    observations: list[SourcePlayerReferenceObservation]
    digest: str = Field(pattern=_SHA256)


class SourceJoinReview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    annotation_id: str = Field(min_length=1)
    disposition: Literal["matched", "unmatched", "ambiguous"]
    candidate_id: str | None = None
    primary_reviewer_id: str = Field(min_length=1)
    independent_reviewer_id: str = Field(min_length=1)
    adjudicator_id: str = Field(min_length=1)
    evidence: list[str] = Field(min_length=1)
    review_scope: Literal["source_candidate_geometry_only"]

    @model_validator(mode="after")
    def independent_review(self) -> SourceJoinReview:
        if len({self.primary_reviewer_id, self.independent_reviewer_id, self.adjudicator_id}) != 3:
            raise ValueError("candidate correspondence review must be independent")
        return self


class FrozenSourceJoinArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_reference_digest: str = Field(pattern=_SHA256)
    source_video_sha256: str = Field(pattern=_SHA256)
    candidate_run_digest: str = Field(pattern=_SHA256)
    raw_candidate_digest: str = Field(pattern=_SHA256)
    join_protocol_digest: str = Field(pattern=_SHA256)
    joins: list[ReferenceCandidateJoin]
    reviews: list[SourceJoinReview]
    digest: str = Field(pattern=_SHA256)


class SourceReferencePrediction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_video_sha256: str = Field(pattern=_SHA256)
    frame_index: int = Field(ge=0)
    source_pts: int = Field(ge=0)
    timebase_numerator: int = Field(gt=0)
    timebase_denominator: int = Field(gt=0)
    prediction_run_digest: str = Field(pattern=_SHA256)
    candidate_id: str = Field(min_length=1)
    assigned_player_id: str | None = Field(default=None, min_length=1)


class SourcePredictionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    source_reference_digest: str = Field(pattern=_SHA256)
    join_artifact_digest: str = Field(pattern=_SHA256)
    source_video_sha256: str = Field(pattern=_SHA256)
    prediction_run_digest: str = Field(pattern=_SHA256)
    predictions: list[SourceReferencePrediction]


class SourcePredictionRunManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    source_reference_digest: str = Field(pattern=_SHA256)
    join_artifact_digest: str = Field(pattern=_SHA256)
    source_video_sha256: str = Field(pattern=_SHA256)
    candidate_run_digest: str = Field(pattern=_SHA256)
    prediction_run_digest: str = Field(pattern=_SHA256)
    prediction_output_sha256: str = Field(pattern=_SHA256)
    configuration_digest: str = Field(pattern=_SHA256)
    code_digest: str = Field(pattern=_SHA256)
    digest: str = Field(pattern=_SHA256)


class FrozenSourcePredictionArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_reference_digest: str = Field(pattern=_SHA256)
    join_artifact_digest: str = Field(pattern=_SHA256)
    source_video_sha256: str = Field(pattern=_SHA256)
    candidate_run_digest: str = Field(pattern=_SHA256)
    prediction_run_digest: str = Field(pattern=_SHA256)
    run_manifest_sha256: str = Field(pattern=_SHA256)
    prediction_output_sha256: str = Field(pattern=_SHA256)
    configuration_digest: str = Field(pattern=_SHA256)
    code_digest: str = Field(pattern=_SHA256)
    predictions: list[SourceReferencePrediction]
    digest: str = Field(pattern=_SHA256)


class SourceReferenceReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    split: Literal["development", "validation", "test"]
    source_reference_digest: str = Field(pattern=_SHA256)
    candidate_run_digest: str | None = Field(default=None, pattern=_SHA256)
    raw_candidate_digest: str | None = Field(default=None, pattern=_SHA256)
    join_protocol_digest: str | None = Field(default=None, pattern=_SHA256)
    join_artifact_digest: str | None = Field(default=None, pattern=_SHA256)
    prediction_artifact_digest: str | None = Field(default=None, pattern=_SHA256)
    prediction_output_sha256: str | None = Field(default=None, pattern=_SHA256)
    prediction_run_manifest_sha256: str | None = Field(default=None, pattern=_SHA256)
    prediction_configuration_digest: str | None = Field(default=None, pattern=_SHA256)
    prediction_code_digest: str | None = Field(default=None, pattern=_SHA256)
    prediction_run_digest: str | None = Field(default=None, pattern=_SHA256)
    computable: bool
    target_eligible: bool
    reason: str | None = None
    visible_player_duration_seconds: Fraction = Fraction(0)
    visible_player_duration_lower_seconds: Fraction = Fraction(0)
    visible_player_duration_upper_seconds: Fraction = Fraction(0)
    established_identity_duration_seconds: Fraction = Fraction(0)
    verified_correct_duration_seconds: Fraction = Fraction(0)
    unknown_identity_duration_seconds: Fraction = Fraction(0)
    unassessed_unknown_identity_duration_seconds: Fraction = Fraction(0)
    unassessed_unknown_identity_count: int = Field(ge=0)
    class_uncertain_duration_seconds: Fraction = Fraction(0)
    marker_collision_uncertain_duration_seconds: Fraction = Fraction(0)
    nonlive_duration_seconds: Fraction = Fraction(0)
    unknown_context_duration_seconds: Fraction = Fraction(0)
    unmapped_duration_seconds: Fraction = Fraction(0)
    assigned_duration_seconds: Fraction = Fraction(0)
    switch_count: int = Field(ge=0)
    eligible_transition_count: int = Field(ge=0)
    excluded_transition_count: int = Field(ge=0)
    continuity_coverage: float | None = Field(default=None, ge=0, le=1)
    stability_scope: Literal["full_reviewed_scope", "partial_continuity", "no_eligible_transitions"]
    completeness_fraction: float | None = Field(default=None, ge=0, le=1)
    correct_fraction_of_visible: float | None = Field(default=None, ge=0, le=1)
    correct_fraction_lower_bound: float | None = Field(default=None, ge=0, le=1)
    correct_fraction_upper_bound: float | None = Field(default=None, ge=0, le=1)
    identity_coverage: float | None = Field(default=None, ge=0, le=1)
    assignment_coverage: float | None = Field(default=None, ge=0, le=1)
