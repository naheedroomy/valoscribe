"""Persistent raw same-location spatial-proposal diagnostic contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from valoscribe.types.persistent import PersistentModel


class SameLocationTemplateScore(PersistentModel):
    """One raw template similarity measured at a proposal's unchanged location."""

    template_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    similarity: float = Field(ge=-1.0, le=1.0)
    interpretation: Literal["uncalibrated_raw_same_location_similarity"] = (
        "uncalibrated_raw_same_location_similarity"
    )


class SameLocationProposal(PersistentModel):
    """Raw broadcast-color geometry and anonymous fixed-window comparison."""

    proposal_id: str = Field(min_length=1)
    frame_index: int = Field(ge=0)
    source_pts: int = Field(ge=0)
    timestamp_seconds: str = Field(min_length=1)
    source_crop_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    broadcast_color: str = Field(min_length=1)
    color_candidate_accepted: bool
    color_candidate_rejection_reasons: list[str]
    color_candidate_box_xywh: tuple[int, int, int, int]
    neighborhood_box_xywh: tuple[int, int, int, int]
    status: Literal["scored", "clipped", "empty_support"]
    support_kind: Literal["color_threshold_geometry_not_foreground"] = (
        "color_threshold_geometry_not_foreground"
    )
    support_pixel_count: int = Field(ge=0)
    support_mask_path: str | None = None
    support_mask_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    neighborhood_crop_path: str | None = None
    neighborhood_crop_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    scores: list[SameLocationTemplateScore]
    rejection_reasons: list[str]
    identity: Literal["unknown"] = "unknown"
    side: Literal["unknown"] = "unknown"
    map_position: Literal["not_emitted"] = "not_emitted"
    prediction_exported: Literal[False] = False

    @model_validator(mode="after")
    def evidence_matches_status(self) -> SameLocationProposal:
        if self.status == "scored":
            if len(self.scores) != 4 or len({score.template_id for score in self.scores}) != 4:
                raise ValueError("scored proposal requires all four unique template similarities")
            if self.support_pixel_count <= 0:
                raise ValueError("scored proposal requires non-empty synthetic color support")
            if any(
                item is None
                for item in (
                    self.support_mask_path,
                    self.support_mask_sha256,
                    self.neighborhood_crop_path,
                    self.neighborhood_crop_sha256,
                )
            ):
                raise ValueError("scored proposal requires hash-bound crop and support mask")
        elif self.scores:
            raise ValueError("unscored proposal cannot contain partial similarities")
        if self.status == "empty_support":
            if (
                self.support_pixel_count != 0
                or "same_location_color_support_mask_is_empty" not in self.rejection_reasons
            ):
                raise ValueError("empty support proposal requires its explicit reason")
        if self.status == "clipped":
            if (
                self.support_pixel_count != 0
                or "same_location_neighborhood_clipped_at_source_crop_edge"
                not in self.rejection_reasons
            ):
                raise ValueError("clipped proposal requires its explicit reason")
            if any(
                item is not None
                for item in (
                    self.support_mask_path,
                    self.support_mask_sha256,
                    self.neighborhood_crop_path,
                    self.neighborhood_crop_sha256,
                )
            ):
                raise ValueError("clipped proposal must not claim an incomplete local image crop")
        return self


class SameLocationProposalDiagnostics(PersistentModel):
    """Derived proposal counts, separately persisted from raw proposals."""

    schema_version: Literal["1.0"] = "1.0"
    status: Literal["diagnostic_only_uncalibrated"] = "diagnostic_only_uncalibrated"
    source_frame_count: int = Field(ge=1)
    proposal_count: int = Field(ge=0)
    scored_proposal_count: int = Field(ge=0)
    clipped_proposal_count: int = Field(ge=0)
    empty_support_proposal_count: int = Field(ge=0)
    raw_similarity_count: int = Field(ge=0)
    all_identities: Literal["unknown"] = "unknown"
    all_sides: Literal["unknown"] = "unknown"
    player_detections_exported: Literal[False] = False
    map_positions_emitted: Literal[False] = False
    accuracy_claimed: Literal[False] = False

    @model_validator(mode="after")
    def validate_counts(self) -> SameLocationProposalDiagnostics:
        if self.proposal_count != (
            self.scored_proposal_count
            + self.clipped_proposal_count
            + self.empty_support_proposal_count
        ):
            raise ValueError("proposal status counts must sum to proposal count")
        if self.raw_similarity_count != self.scored_proposal_count * 4:
            raise ValueError("every scored proposal must contain four raw similarities")
        return self


class SameLocationProposalManifest(PersistentModel):
    """Hash and count joins for one replayed source packet."""

    schema_version: Literal["1.0"] = "1.0"
    experiment_id: Literal["vta304-same-location-proposals-v1"] = (
        "vta304-same-location-proposals-v1"
    )
    source_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_review_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    template_bank_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    color_profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_proposals_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    derived_diagnostics_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    debug_index_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    frame_count: int = Field(ge=1)
    proposal_count: int = Field(ge=0)
    raw_similarity_count: int = Field(ge=0)
    template_count: Literal[4] = 4
    prediction_exported: Literal[False] = False
    map_coordinates_emitted: Literal[False] = False
