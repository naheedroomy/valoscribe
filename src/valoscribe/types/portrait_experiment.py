"""Persistent outputs for opt-in raw portrait-ranking experiments."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from valoscribe.types.persistent import PersistentModel


class PortraitTemplateProvenance(PersistentModel):
    """A source window, not a foreground segmentation mask."""

    template_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    frame_index: int = Field(ge=0)
    source_pts: int = Field(ge=0)
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    source_crop_png_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_status: Literal["ai_reviewed_not_human_gold", "unreviewed_synthetic_test"]
    mask_policy: Literal["full_window_includes_background_diagnostic_only"] = (
        "full_window_includes_background_diagnostic_only"
    )

    @model_validator(mode="after")
    def window_is_inside_candidate_crop(self) -> PortraitTemplateProvenance:
        if self.width != 20 or self.height != 20:
            raise ValueError("fixed experiment templates must be 20x20 windows")
        if self.x + self.width > 360 or self.y + self.height > 400:
            raise ValueError("template window exceeds native candidate crop")
        return self


class PortraitRawRank(PersistentModel):
    """One uncalibrated spatial match score retained as raw evidence."""

    frame_index: int = Field(ge=0)
    source_pts: int = Field(ge=0)
    timestamp_seconds: str = Field(min_length=1)
    template_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    score: float = Field(ge=-1.0, le=1.0)
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    candidate_crop_png_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    seed_frame: bool
    side: Literal["unknown"] = "unknown"
    identity: Literal["unknown"] = "unknown"
    overlap_utility_status: Literal["unknown_not_evaluated"] = "unknown_not_evaluated"
    interpretation: Literal["uncalibrated_raw_spatial_template_similarity"] = (
        "uncalibrated_raw_spatial_template_similarity"
    )

    @model_validator(mode="after")
    def match_window_is_inside_candidate_crop(self) -> PortraitRawRank:
        if self.width != 20 or self.height != 20:
            raise ValueError("fixed experiment raw matches must be 20x20 windows")
        if self.x + self.width > 360 or self.y + self.height > 400:
            raise ValueError("raw match window exceeds native candidate crop")
        return self


class PortraitDebugFrame(PersistentModel):
    """Hash-indexed, relative output path for one source-backed overlay."""

    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PortraitFrameRanking(PersistentModel):
    """Top two spatial maxima for one source frame; neither resolves identity."""

    frame_index: int = Field(ge=0)
    source_pts: int = Field(ge=0)
    seed_frame: bool
    top_raw_match: PortraitRawRank
    runner_up_raw_match: PortraitRawRank
    resolution: Literal["unknown_uncalibrated_no_identity_assignment"]

    @model_validator(mode="after")
    def matches_belong_to_frame(self) -> PortraitFrameRanking:
        if any(
            rank.frame_index != self.frame_index or rank.source_pts != self.source_pts
            for rank in (self.top_raw_match, self.runner_up_raw_match)
        ):
            raise ValueError("frame ranking matches must belong to the enclosing frame/PTS")
        if self.top_raw_match.score < self.runner_up_raw_match.score:
            raise ValueError("top raw match score must be at least the runner-up")
        if self.top_raw_match.seed_frame != self.seed_frame:
            raise ValueError("frame ranking seed flag must match its raw match")
        if self.runner_up_raw_match.seed_frame != self.seed_frame:
            raise ValueError("frame ranking seed flag must match its raw match")
        return self


class PortraitExperimentDiagnostics(PersistentModel):
    """Derived summaries, hash-bound separately from raw rankings."""

    schema_version: Literal["1.0"]
    interpretation: Literal["diagnostic ranking only; not accuracy or identity predictions"]
    frame_count: int = Field(ge=1)
    raw_score_count: int = Field(ge=1)
    seed_frames_excluded_from_nonseed_distribution: int = Field(ge=1)
    nonseed_score_count: int = Field(ge=1)
    nonseed_score_min: float = Field(ge=-1.0, le=1.0)
    nonseed_score_median: float = Field(ge=-1.0, le=1.0)
    nonseed_score_max: float = Field(ge=-1.0, le=1.0)
    top_raw_matches_by_frame: list[PortraitFrameRanking]
    all_sides: Literal["unknown"]
    identity_resolution: Literal["none; calibration absent and templates incomplete"]
    map_coordinates: Literal["not_emitted"]
    full_window_templates_include_background: Literal[True]
    template_reviewer_status: Literal["ai_reviewed_not_human_gold", "unreviewed_synthetic_test"]
    debug_frame_count: int = Field(ge=1)
    debug_frames: list[PortraitDebugFrame]
    debug_frame_semantics: Literal["top four sliding-window matches; not player detections"]

    @model_validator(mode="after")
    def summaries_are_consistent(self) -> PortraitExperimentDiagnostics:
        if self.nonseed_score_min > self.nonseed_score_median:
            raise ValueError("nonseed score minimum must not exceed median")
        if self.nonseed_score_median > self.nonseed_score_max:
            raise ValueError("nonseed score median must not exceed maximum")
        if len(self.top_raw_matches_by_frame) != self.frame_count:
            raise ValueError("one ranked diagnostic is required per source frame")
        if len(self.debug_frames) != self.debug_frame_count:
            raise ValueError("debug frame count must match its hash index")
        if not 0 < self.seed_frames_excluded_from_nonseed_distribution < self.frame_count:
            raise ValueError("seed frame count must be positive and less than frame count")
        if self.raw_score_count != self.frame_count * 4:
            raise ValueError("raw score count must cover four templates per frame")
        expected_nonseed = (
            self.raw_score_count - 4 * self.seed_frames_excluded_from_nonseed_distribution
        )
        if self.nonseed_score_count != expected_nonseed:
            raise ValueError("nonseed score count must exclude every template score on seed frames")
        frame_ids = [item.frame_index for item in self.top_raw_matches_by_frame]
        if len(set(frame_ids)) != self.frame_count:
            raise ValueError("frame ranking rows must cover distinct source frames")
        if len({item.path for item in self.debug_frames}) != self.debug_frame_count:
            raise ValueError("debug frame paths must be unique")
        return self


class PortraitExperimentManifest(PersistentModel):
    """Read-back-verifiable binding for a frozen local experiment."""

    schema_version: Literal["1.0"] = "1.0"
    experiment_id: str = Field(min_length=1)
    source_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    template_bank_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_rankings_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    derived_diagnostics_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    debug_frames_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    frame_count: int = Field(ge=1)
    template_count: int = Field(ge=1)
    raw_rank_count: int = Field(ge=1)
    seed_frame_count: int = Field(ge=1)
    status: Literal["raw_diagnostic_only_uncalibrated_unaccepted"] = (
        "raw_diagnostic_only_uncalibrated_unaccepted"
    )
    prediction_exported: Literal[False] = False
    map_coordinates_emitted: Literal[False] = False
