"""Versioned input and output contracts for evidence-bounded round analysis."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import Field, field_validator, model_validator

from valoscribe.types.anonymous_report import AnonymousConfidenceRange
from valoscribe.types.persistent import EvidenceRef, PersistentModel


class HUDRoundEvent(PersistentModel):
    """One original upstream event, bound to a reviewed round interval and source clock."""

    schema_version: Literal["1.0"] = "1.0"
    source_id: str = Field(min_length=1, max_length=200)
    source_line_number: int = Field(gt=0)
    match_id: str = Field(min_length=1)
    map_id: str = Field(min_length=1)
    round_id: str = Field(min_length=1)
    round_number: int = Field(gt=0)
    source_timestamp: float = Field(ge=0)
    clock_domain: str = Field(min_length=1, max_length=100)
    event_type: str = Field(min_length=1, max_length=100)
    detail_text: str = Field(max_length=500)
    upstream_confidence: float | None = Field(ge=0, le=1)
    confidence_availability: Literal["source_reported", "not_provided", "unsupported"]
    upstream_evidence: list[EvidenceRef]
    evidence_availability: Literal["source_reported", "not_provided", "unsupported"]
    evidence_reference_count: int = Field(ge=0)
    original_event: dict[str, object]

    @field_validator("source_timestamp")
    @classmethod
    def timestamp_is_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("source timestamp must be finite")
        return value

    @model_validator(mode="after")
    def original_fields_match_binding(self) -> HUDRoundEvent:
        if self.original_event.get("round_number", self.round_number) != self.round_number:
            raise ValueError("upstream event round_number disagrees with bundle binding")
        if self.original_event.get("type") != self.event_type:
            raise ValueError("upstream event type disagrees with binding")
        if self.original_event.get("timestamp") != self.source_timestamp:
            raise ValueError("upstream event timestamp disagrees with binding")
        if self.original_event.get("clock_domain", self.clock_domain) != self.clock_domain:
            raise ValueError("upstream event clock_domain disagrees with source")
        return self


class RoundEventSource(PersistentModel):
    """Path and scope needed to bind legacy HUD JSONL without inventing a clock."""

    schema_version: Literal["1.0"] = "1.0"
    source_id: str = Field(min_length=1, max_length=200)
    event_log_path: str = Field(min_length=1)
    match_id: str = Field(min_length=1)
    map_id: str = Field(min_length=1)
    round_id: str = Field(min_length=1)
    round_number: int = Field(gt=0)
    clock_domain: str = Field(min_length=1, max_length=100)
    bounds_evidence_reference: str = Field(min_length=1, max_length=500)
    start_timestamp: float = Field(ge=0)
    end_timestamp: float = Field(ge=0)

    @field_validator("start_timestamp", "end_timestamp")
    @classmethod
    def bounds_are_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("event bounds must be finite")
        return value

    @model_validator(mode="after")
    def bounds_are_ordered(self) -> RoundEventSource:
        if self.end_timestamp < self.start_timestamp:
            raise ValueError("event timestamp bounds are reversed")
        return self


class DiagnosticAvailability(PersistentModel):
    """Anonymous diagnostic summary inventory; never promoted to tactical evidence."""

    schema_version: Literal["1.0"] = "1.0"
    report_path: str = Field(min_length=1)


class RoundAnalysisBundle(PersistentModel):
    """One requested round plus explicitly scoped local upstream source artifacts."""

    schema_version: Literal["1.0"] = "1.0"
    match_id: str = Field(min_length=1)
    map_id: str = Field(min_length=1)
    round_id: str = Field(min_length=1)
    round_number: int = Field(gt=0)
    hud_source: RoundEventSource | None = None
    diagnostics: list[DiagnosticAvailability] = Field(default_factory=list)

    @model_validator(mode="after")
    def source_scope_matches_bundle(self) -> RoundAnalysisBundle:
        if self.hud_source is not None and (
            self.hud_source.match_id,
            self.hud_source.map_id,
            self.hud_source.round_id,
            self.hud_source.round_number,
        ) != (self.match_id, self.map_id, self.round_id, self.round_number):
            raise ValueError("HUD source scope does not match round-analysis bundle")
        return self


class RoundAnalysisFact(PersistentModel):
    """Locally rendered source event observation with an exact JSONL line reference."""

    schema_version: Literal["1.0"] = "1.0"
    fact_id: str = Field(min_length=1)
    text: str = Field(min_length=1, max_length=700)
    event_type: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_line_number: int = Field(gt=0)
    timestamp: float = Field(ge=0)
    clock_domain: str = Field(min_length=1)
    evidence_id: str = Field(min_length=1)
    upstream_confidence: float | None = Field(ge=0, le=1)
    confidence_availability: Literal["source_reported", "not_provided", "unsupported"]
    upstream_evidence: list[EvidenceRef]
    evidence_availability: Literal["source_reported", "not_provided", "unsupported"]
    evidence_reference_count: int = Field(ge=0)


class RoundAnalysisCitation(PersistentModel):
    """A fact reference resolved from the local source record, never model supplied."""

    schema_version: Literal["1.0"] = "1.0"
    fact_id: str = Field(min_length=1)
    evidence_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_line_number: int = Field(gt=0)
    timestamp: float = Field(ge=0)
    clock_domain: str = Field(min_length=1)


class RoundAnalysisHypothesis(PersistentModel):
    """Tentative single-round interpretation, explicitly not an observed fact."""

    schema_version: Literal["1.0"] = "1.0"
    text: str = Field(min_length=1, max_length=300)
    confidence: float = Field(ge=0, le=1)
    fact_ids: list[str] = Field(min_length=1, max_length=4)
    citations: list[RoundAnalysisCitation] = Field(min_length=1, max_length=4)

    @field_validator("text")
    @classmethod
    def hypothesis_is_one_nonblank_line(cls, value: str) -> str:
        if not value.strip() or any(ord(char) < 32 for char in value):
            raise ValueError("hypothesis text must be a nonblank single line")
        return value

    @field_validator("confidence", mode="before")
    @classmethod
    def confidence_is_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("hypothesis confidence must be finite")
        return value


class RoundAnalysisRecommendation(PersistentModel):
    """Optional tentative coaching practice with locally resolved evidence links."""

    schema_version: Literal["1.0"] = "1.0"
    text: str = Field(min_length=1, max_length=300)
    confidence: float = Field(ge=0, le=1)
    fact_ids: list[str] = Field(min_length=1, max_length=4)
    citations: list[RoundAnalysisCitation] = Field(min_length=1, max_length=4)

    @field_validator("text")
    @classmethod
    def recommendation_is_one_nonblank_line(cls, value: str) -> str:
        if not value.strip() or any(ord(char) < 32 for char in value):
            raise ValueError("recommendation text must be a nonblank single line")
        return value

    @field_validator("confidence", mode="before")
    @classmethod
    def confidence_is_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("recommendation confidence must be finite")
        return value


class DiagnosticSummary(PersistentModel):
    """Diagnostic counts and provenance in JSON as well as Markdown; never tactics."""

    schema_version: Literal["1.0"] = "1.0"
    report_path: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
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


_AnalysisClaim = RoundAnalysisHypothesis | RoundAnalysisRecommendation


def _validate_claim_references(claim: _AnalysisClaim, facts: dict[str, RoundAnalysisFact]) -> None:
    if len(set(claim.fact_ids)) != len(claim.fact_ids):
        raise ValueError("claim fact IDs must be unique")
    if not set(claim.fact_ids).issubset(facts):
        raise ValueError("claim references unknown fact IDs")
    if len(claim.citations) != len(claim.fact_ids) or {
        citation.fact_id for citation in claim.citations
    } != set(claim.fact_ids):
        raise ValueError("claim citations do not match referenced fact IDs")
    for citation in claim.citations:
        fact = facts[citation.fact_id]
        if (
            citation.evidence_id != fact.evidence_id
            or citation.source_id != fact.source_id
            or citation.source_line_number != fact.source_line_number
            or citation.timestamp != fact.timestamp
            or citation.clock_domain != fact.clock_domain
        ):
            raise ValueError("claim citation disagrees with locally resolved fact")


class RoundAnalysisOutput(PersistentModel):
    """Source inventory plus separately typed hypotheses and tentative advice."""

    schema_version: Literal["1.0"] = "1.0"
    analysis_kind: Literal["single_round_evidence_inventory"] = "single_round_evidence_inventory"
    match_id: str = Field(min_length=1)
    map_id: str = Field(min_length=1)
    round_id: str = Field(min_length=1)
    round_number: int = Field(gt=0)
    sample_round_count: int = Field(ge=0)
    events_by_source: dict[str, int]
    source_artifacts: dict[str, str]
    source_clock_domains: dict[str, str]
    source_bounds_references: dict[str, str]
    observations: list[RoundAnalysisFact]
    selected_observation_ids: list[str]
    interpretations: list[RoundAnalysisHypothesis]
    recommendations: list[RoundAnalysisRecommendation]
    diagnostics: list[DiagnosticSummary]
    limitations: list[str]

    @model_validator(mode="after")
    def references_are_known(self) -> RoundAnalysisOutput:
        facts = {fact.fact_id: fact for fact in self.observations}
        if len(facts) != len(self.observations):
            raise ValueError("observation fact IDs must be unique")
        if len(set(self.selected_observation_ids)) != len(self.selected_observation_ids):
            raise ValueError("selected observation IDs must be unique")
        if not set(self.selected_observation_ids).issubset(facts):
            raise ValueError("selected observation ID is unknown")
        for claim in self.interpretations:
            _validate_claim_references(claim, facts)
        for recommendation in self.recommendations:
            _validate_claim_references(recommendation, facts)
        return self
