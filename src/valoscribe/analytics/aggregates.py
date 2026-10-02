"""Deterministic aggregation and representative-round selection."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from typing import Literal

from pydantic import Field, field_validator

from valoscribe.analytics.scenarios import ScenarioSearchRecord
from valoscribe.types.persistent import (
    FormationObservationResult,
    PersistentModel,
    PhaseSegment,
)


class RoundFeature(PersistentModel):
    """Comparable structured fields for one round; absent values stay unknown."""

    schema_version: Literal["1.0"] = "1.0"
    round_id: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_ids: list[str] = Field(min_length=1)
    categorical: dict[str, str | None]
    numeric: dict[str, float | None]

    @field_validator("confidence", mode="before")
    @classmethod
    def confidence_is_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("confidence must be finite")
        return value

    @field_validator("evidence_ids")
    @classmethod
    def evidence_ids_nonempty(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("evidence IDs must be non-empty")
        return values

    @field_validator("numeric")
    @classmethod
    def numeric_values_are_finite(cls, values: dict[str, float | None]) -> dict[str, float | None]:
        if any(value is not None and not math.isfinite(value) for value in values.values()):
            raise ValueError("numeric feature values must be finite")
        return values


class RoundAggregate(PersistentModel):
    """Versioned aggregate with explicit sample and round selections."""

    schema_version: Literal["1.0"] = "1.0"
    sample_size: int = Field(ge=0)
    matching_round_ids: list[str]
    representative_round_ids: list[str]
    outlier_round_ids: list[str]
    categorical_distributions: dict[str, dict[str, int]]
    numeric_medians: dict[str, float]
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_ids: list[str]

    @field_validator("confidence", mode="before")
    @classmethod
    def aggregate_confidence_is_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("confidence must be finite")
        return value

    @field_validator("numeric_medians", mode="before")
    @classmethod
    def medians_are_finite(cls, values: dict[str, float]) -> dict[str, float]:
        if any(not math.isfinite(value) for value in values.values()):
            raise ValueError("numeric medians must be finite")
        return values


def round_feature(
    record: ScenarioSearchRecord,
    formations: Sequence[FormationObservationResult] = (),
    phases: Sequence[PhaseSegment] = (),
) -> RoundFeature:
    """Build fields supported by the scenario, formation, and phase contracts."""
    selected_formations = [
        item for item in formations
        if item.round_id == record.round_id
        and (record.team_id is None or item.team_id == record.team_id)
    ]
    selected_phases = [item for item in phases if item.round_id == record.round_id]
    selected_phases.sort(key=lambda item: (item.start_timestamp_s, item.end_timestamp_s,
                                           item.phase.value))
    categorical = {
        "map_id": record.map_id,
        "buy_class": record.buy_class,
        "spike_state": record.spike_state,
        "opening_duel_outcome": record.opening_duel_outcome,
        "formation": _mode(item.formation.value for item in selected_formations),
        "phase_sequence": ">".join(dict.fromkeys(
            item.phase.value for item in selected_phases
        )) or None,
    }
    numeric: dict[str, float | None] = {
        "display_clock_s": record.display_clock_s,
        "alive_attack": float(record.alive_attack) if record.alive_attack is not None else None,
        "alive_defense": float(record.alive_defense) if record.alive_defense is not None else None,
        "control_zone_count": float(len(record.control_zones)) if record.control_zones else None,
        "utility_count": float(len(record.utility_ids)) if record.utility_ids else None,
    }
    evidence = list(record.evidence_ids)
    evidence.extend(token for item in selected_formations for token in item.evidence)
    evidence.extend(token for item in selected_phases for token in item.evidence)
    confidences = [record.confidence, *(item.confidence for item in selected_formations),
                   *(item.confidence for item in selected_phases)]
    return RoundFeature(
        round_id=record.round_id,
        confidence=min(confidences),
        evidence_ids=list(dict.fromkeys(evidence)),
        categorical=categorical,
        numeric=numeric,
    )


def aggregate_rounds(
    features: Sequence[RoundFeature], *, outlier_threshold: float
) -> RoundAggregate:
    """Aggregate structured features with normalized mixed-field distance.

    Categorical mismatches cost 1; numeric fields use range-normalized absolute
    difference. Unknown fields are excluded. Pairs with no overlap do not inform
    medoid selection, and rounds with no comparable peers are not representatives.
    """
    if not math.isfinite(outlier_threshold) or outlier_threshold < 0:
        raise ValueError("outlier_threshold must be finite and non-negative")
    if len({item.round_id for item in features}) != len(features):
        raise ValueError("round feature IDs must be unique")
    ordered = sorted(features, key=lambda item: item.round_id)
    categorical_distributions: dict[str, dict[str, int]] = {}
    numeric_medians: dict[str, float] = {}
    cat_fields = sorted({key for item in ordered for key, value in item.categorical.items()
                         if value is not None})
    num_fields = sorted({key for item in ordered for key, value in item.numeric.items()
                         if value is not None})
    for field in cat_fields:
        counts = Counter(item.categorical[field] for item in ordered
                         if item.categorical.get(field) is not None)
        categorical_distributions[field] = dict(sorted(
            (value, count) for value, count in counts.items() if value is not None
        ))
    for field in num_fields:
        values = sorted(value for item in ordered
                        if (value := item.numeric.get(field)) is not None)
        numeric_medians[field] = _median(values)

    if not ordered:
        return RoundAggregate(sample_size=0, matching_round_ids=[], representative_round_ids=[],
                              outlier_round_ids=[], categorical_distributions={},
                              numeric_medians={}, confidence=0.0, evidence_ids=[])
    pair_distances: dict[tuple[str, str], float] = {}
    for index, left in enumerate(ordered):
        for right in ordered[index + 1:]:
            distance = _distance(left, right, cat_fields, num_fields, ordered)
            if distance is not None:
                pair_distances[(left.round_id, right.round_id)] = distance
    means: dict[str, float] = {}
    for item in ordered:
        distances = [distance for (left, right), distance in pair_distances.items()
                     if item.round_id in (left, right)]
        if distances:
            means[item.round_id] = sum(distances) / len(distances)
    representative = (
        min(means, key=lambda round_id: (means[round_id], round_id))
        if means else ordered[0].round_id if len(ordered) == 1 else None
    )
    outliers = [round_id for round_id, distance in means.items()
                if round_id != representative and distance > outlier_threshold]
    return RoundAggregate(
        sample_size=len(ordered), matching_round_ids=[item.round_id for item in ordered],
        representative_round_ids=[representative] if representative is not None else [],
        outlier_round_ids=outliers, categorical_distributions=categorical_distributions,
        numeric_medians=numeric_medians, confidence=min(item.confidence for item in ordered),
        evidence_ids=list(dict.fromkeys(token for item in ordered for token in item.evidence_ids)),
    )


def _distance(left: RoundFeature, right: RoundFeature, cat_fields: list[str],
              num_fields: list[str], features: Sequence[RoundFeature]) -> float | None:
    terms: list[float] = []
    for field in cat_fields:
        left_value, right_value = left.categorical.get(field), right.categorical.get(field)
        if left_value is not None and right_value is not None:
            terms.append(float(left_value != right_value))
    for field in num_fields:
        left_number, right_number = left.numeric.get(field), right.numeric.get(field)
        if left_number is not None and right_number is not None:
            values = [item.numeric.get(field) for item in features]
            present = [value for value in values if value is not None]
            span = max(present) - min(present)
            terms.append(abs(left_number - right_number) / span if span else 0.0)
    return sum(terms) / len(terms) if terms else None


def _median(values: list[float]) -> float:
    middle = len(values) // 2
    return values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2


def _mode(values) -> str | None:
    counts = Counter(values)
    return min(counts, key=lambda value: (-counts[value], value)) if counts else None
