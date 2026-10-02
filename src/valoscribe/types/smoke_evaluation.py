"""Persisted reviewed labels and evaluation results for smoke lifecycle events."""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import (
    Field,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer,
    model_validator,
)

from valoscribe.types.persistent import (
    EvidenceRef,
    EvidenceSource,
    NormalizedPoint,
    PersistentModel,
)


class ReviewedSmokeLabel(PersistentModel):
    """Human-reviewed expected smoke interval; null end means not determined."""

    schema_version: Literal["1.0"] = "1.0"
    label_id: str = Field(min_length=1)
    match_id: str = Field(min_length=1)
    map_id: str = Field(min_length=1)
    round_id: str = Field(min_length=1)
    center: NormalizedPoint
    appeared_at_s: float = Field(ge=0.0)
    disappeared_at_s: float | None = Field(default=None, ge=0.0)

    @field_validator("match_id", "map_id", "round_id", "label_id")
    @classmethod
    def identifiers_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("smoke label identifiers must not be blank")
        return value

    @field_validator("appeared_at_s", "disappeared_at_s")
    @classmethod
    def label_times_finite(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("smoke label times must be finite")
        return value

    @model_validator(mode="after")
    def interval_ordered(self) -> ReviewedSmokeLabel:
        if self.disappeared_at_s is not None and self.disappeared_at_s < self.appeared_at_s:
            raise ValueError("smoke label disappearance cannot precede appearance")
        return self


class SupportedReviewedSmokeLabel(ReviewedSmokeLabel):
    """V2 reviewed label with independently sourced, scoped agent attribution."""

    schema_version: Literal["2.0"] = "2.0"  # type: ignore[assignment]
    agent_type: str = Field(min_length=1)
    attribution_evidence: list[EvidenceRef] = Field(min_length=1)

    @field_validator("agent_type")
    @classmethod
    def agent_type_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("smoke label agent_type must not be blank")
        return value.strip()

    @model_validator(mode="after")
    def attribution_is_independent_and_scoped(self) -> SupportedReviewedSmokeLabel:
        scope = (self.match_id, self.map_id, self.round_id)
        for evidence in self.attribution_evidence:
            if (evidence.match_id, evidence.map_id, evidence.round_id) != scope:
                raise ValueError("smoke attribution evidence scope must match its label")
            if evidence.source == EvidenceSource.INFERENCE or evidence.confidence <= 0:
                raise ValueError("smoke attribution requires positive-confidence observed evidence")
            if not any(value and value.strip() for value in (evidence.frame_path, evidence.note)):
                raise ValueError("smoke attribution evidence requires a frame path or note")
        return self


class SmokeEvaluation(PersistentModel):
    """Generic event counts and timing errors; unavailable metrics are null."""

    schema_version: Literal["2.0"] = "2.0"
    reviewed_label_count: int = Field(ge=0)
    prediction_count: int = Field(ge=0)
    true_positives: int = Field(ge=0)
    false_positives: int = Field(ge=0)
    false_negatives: int = Field(ge=0)
    precision: float | None = Field(default=None, ge=0.0, le=1.0)
    recall: float | None = Field(default=None, ge=0.0, le=1.0)
    appearance_timing_error_mean_s: float | None = Field(default=None, ge=0.0)
    disappearance_timing_error_mean_s: float | None = Field(default=None, ge=0.0)
    appearance_timing_error_median_s: float | None = Field(default=None, ge=0.0)
    disappearance_timing_error_median_s: float | None = Field(default=None, ge=0.0)

    @model_validator(mode="before")
    @classmethod
    def migrate_v1_evaluation(cls, values: object) -> object:
        """Keep reading V1 stored results after adding median fields in V2."""
        if isinstance(values, dict) and values.get("schema_version") == "1.0":
            values = {**values, "schema_version": "2.0"}
        return values

    @field_validator(
        "precision", "recall", "appearance_timing_error_mean_s",
        "disappearance_timing_error_mean_s", "appearance_timing_error_median_s",
        "disappearance_timing_error_median_s",
    )
    @classmethod
    def metrics_finite(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("smoke evaluation metrics must be finite")
        return value

    @model_validator(mode="after")
    def counts_and_metrics_consistent(self) -> SmokeEvaluation:
        if self.true_positives + self.false_positives != self.prediction_count:
            raise ValueError("smoke prediction counts are inconsistent")
        if self.true_positives + self.false_negatives != self.reviewed_label_count:
            raise ValueError("smoke reviewed-label counts are inconsistent")
        if self.precision is not None and not self.prediction_count:
            raise ValueError("precision requires a prediction denominator")
        if self.recall is not None and not self.reviewed_label_count:
            raise ValueError("recall requires a reviewed-label denominator")
        if self.reviewed_label_count == 0 and self.false_negatives:
            raise ValueError("false negatives require reviewed labels")
        return self


class SupportedSmokeEvaluation(SmokeEvaluation):
    """Supported-agent-only evaluation with explicit excluded cohort counts."""

    scope: Literal["supported_agents"]
    supported_agents: list[str] = Field(min_length=1)
    excluded_reviewed_anonymous_count: int = Field(ge=0)
    excluded_reviewed_unsupported_agent_count: int = Field(ge=0)
    excluded_reviewed_missing_attribution_count: int = Field(ge=0)
    excluded_prediction_anonymous_count: int = Field(ge=0)
    excluded_prediction_unsupported_agent_count: int = Field(ge=0)

    @field_validator("supported_agents", mode="before")
    @classmethod
    def coerce_supported_agents(cls, values: object) -> object:
        if isinstance(values, (list, tuple, set, frozenset)):
            return list(values)
        return values

    @field_validator("supported_agents")
    @classmethod
    def normalize_supported_agents(cls, values: list[str]) -> list[str]:
        normalized = [agent.strip().lower() for agent in values]
        if any(not agent for agent in normalized):
            raise ValueError("supported agents must not be blank")
        if "unknown" in normalized:
            raise ValueError("supported agents must exclude UNKNOWN")
        if len(set(normalized)) != len(normalized):
            raise ValueError("supported agents must not contain duplicates")
        return normalized

    @model_serializer(mode="wrap")
    def serialize_normalized_supported_agents(
        self, handler: SerializerFunctionWrapHandler
    ) -> Any:
        validated = type(self).model_validate(self.__dict__)
        return handler(validated)
