"""Offline one-to-one evaluation of predicted smoke events against reviewed labels."""

from __future__ import annotations

import math
from collections.abc import Sequence
from statistics import median

from pydantic_core import PydanticSerializationError

from valoscribe.types.persistent import SmokeEvent
from valoscribe.types.smoke_evaluation import (
    ReviewedSmokeLabel,
    SmokeEvaluation,
    SupportedReviewedSmokeLabel,
    SupportedSmokeEvaluation,
)


def evaluate_smokes(
    predictions: list[SmokeEvent],
    reviewed_labels: list[ReviewedSmokeLabel],
    *,
    spatial_tolerance: float,
    temporal_tolerance_s: float,
) -> SmokeEvaluation:
    """Evaluate generic smoke lifecycle geometry, without agent eligibility claims."""
    return _evaluate_smokes(
        predictions, reviewed_labels, spatial_tolerance=spatial_tolerance,
        temporal_tolerance_s=temporal_tolerance_s,
    )


def evaluate_supported_smokes(
    predictions: list[SmokeEvent],
    reviewed_labels: list[ReviewedSmokeLabel],
    *,
    supported_agents: frozenset[str],
    spatial_tolerance: float,
    temporal_tolerance_s: float,
) -> SupportedSmokeEvaluation:
    """Evaluate only explicitly attributed labels and predictions for supported agents."""
    normalized_agents = frozenset(agent.strip().lower() for agent in supported_agents)
    if not normalized_agents or "unknown" in normalized_agents:
        raise ValueError("supported_agents must be a non-empty set excluding UNKNOWN")
    if any(not agent for agent in normalized_agents):
        raise ValueError("supported_agents must not contain blank values")

    _reject_duplicate_scoped_ids(predictions, reviewed_labels)

    eligible_predictions: list[SmokeEvent] = []
    prediction_anonymous = 0
    prediction_unsupported = 0
    for prediction in predictions:
        agent_type = (prediction.agent_type or "").strip().lower()
        if not agent_type or agent_type == "unknown":
            prediction_anonymous += 1
        elif agent_type not in normalized_agents:
            prediction_unsupported += 1
        else:
            eligible_predictions.append(prediction)

    eligible_labels: list[SupportedReviewedSmokeLabel] = []
    label_anonymous = 0
    label_unsupported = 0
    label_missing_attribution = 0
    for label in reviewed_labels:
        if not isinstance(label, SupportedReviewedSmokeLabel):
            label_missing_attribution += 1
            continue
        # Lists nested in frozen Pydantic models remain mutable. Revalidate the
        # serialized payload before trusting attribution provenance.
        try:
            label = SupportedReviewedSmokeLabel.model_validate(label.model_dump())
        except PydanticSerializationError as exc:
            raise ValueError("supported smoke label failed attribution revalidation") from exc
        agent_type = label.agent_type.strip().lower()
        if not agent_type or agent_type == "unknown":
            label_anonymous += 1
        elif agent_type not in normalized_agents:
            label_unsupported += 1
        else:
            eligible_labels.append(label)

    result = _evaluate_smokes(
        eligible_predictions, eligible_labels, spatial_tolerance=spatial_tolerance,
        temporal_tolerance_s=temporal_tolerance_s, require_same_agent=True,
    )
    return SupportedSmokeEvaluation(
        **result.model_dump(),
        scope="supported_agents",
        supported_agents=sorted(normalized_agents),
        excluded_reviewed_anonymous_count=label_anonymous,
        excluded_reviewed_unsupported_agent_count=label_unsupported,
        excluded_reviewed_missing_attribution_count=label_missing_attribution,
        excluded_prediction_anonymous_count=prediction_anonymous,
        excluded_prediction_unsupported_agent_count=prediction_unsupported,
    )


def _evaluate_smokes(
    predictions: Sequence[SmokeEvent],
    reviewed_labels: Sequence[ReviewedSmokeLabel],
    *,
    spatial_tolerance: float,
    temporal_tolerance_s: float,
    require_same_agent: bool = False,
) -> SmokeEvaluation:
    _reject_duplicate_scoped_ids(predictions, reviewed_labels)
    if not math.isfinite(spatial_tolerance) or spatial_tolerance < 0:
        raise ValueError("spatial_tolerance must be finite and non-negative")
    if not math.isfinite(temporal_tolerance_s) or temporal_tolerance_s < 0:
        raise ValueError("temporal_tolerance_s must be finite and non-negative")

    edges: dict[tuple[int, int], tuple[float, float]] = {}
    prediction_edges: dict[int, list[tuple[float, float, int]]] = {}
    label_edges: dict[int, list[tuple[float, float, int]]] = {}
    for prediction_index, prediction in enumerate(predictions):
        for label_index, label in enumerate(reviewed_labels):
            if (prediction.match_id, prediction.map_id, prediction.round_id) != (
                label.match_id, label.map_id, label.round_id
            ):
                continue
            prediction_agent = (prediction.agent_type or "").strip().lower()
            label_agent = getattr(label, "agent_type", "").strip().lower()
            if require_same_agent and prediction_agent != label_agent:
                continue
            distance = math.dist(
                (prediction.center.x, prediction.center.y),
                (label.center.x, label.center.y),
            )
            time_delta = abs(prediction.appeared_at_s - label.appeared_at_s)
            if distance <= spatial_tolerance and time_delta <= temporal_tolerance_s:
                edges[(prediction_index, label_index)] = (distance, time_delta)
                prediction_edges.setdefault(prediction_index, []).append(
                    (distance, time_delta, label_index)
                )
                label_edges.setdefault(label_index, []).append(
                    (distance, time_delta, prediction_index)
                )

    # Any endpoint with tied nearest edges is quarantined with every incident edge.
    ambiguous_predictions: set[int] = set()
    ambiguous_labels: set[int] = set()
    for prediction_index, options in prediction_edges.items():
        best = min((distance, time_delta) for distance, time_delta, _ in options)
        nearest = [
            index for distance, time_delta, index in options
            if (distance, time_delta) == best
        ]
        if len(nearest) > 1:
            ambiguous_predictions.add(prediction_index)
    for label_index, options in label_edges.items():
        best = min((distance, time_delta) for distance, time_delta, _ in options)
        nearest = [
            index for distance, time_delta, index in options
            if (distance, time_delta) == best
        ]
        if len(nearest) > 1:
            ambiguous_labels.add(label_index)

    ranked_edges = sorted(
        (
            score[0], score[1], predictions[prediction_index].event_id,
            reviewed_labels[label_index].label_id, prediction_index, label_index,
        )
        for (prediction_index, label_index), score in edges.items()
        if prediction_index not in ambiguous_predictions
        and label_index not in ambiguous_labels
    )
    matches: list[tuple[int, int]] = []
    used_predictions: set[int] = set()
    used_labels: set[int] = set()
    for _, _, _, _, prediction_index, label_index in ranked_edges:
        if prediction_index not in used_predictions and label_index not in used_labels:
            matches.append((prediction_index, label_index))
            used_predictions.add(prediction_index)
            used_labels.add(label_index)

    true_positives = len(matches)
    prediction_count, label_count = len(predictions), len(reviewed_labels)
    appearance_errors = [
        abs(predictions[i].appeared_at_s - reviewed_labels[j].appeared_at_s)
        for i, j in matches
    ]
    disappearance_errors: list[float] = []
    for prediction_index, label_index in matches:
        predicted_disappearance = predictions[prediction_index].disappeared_at_s
        reviewed_disappearance = reviewed_labels[label_index].disappeared_at_s
        if predicted_disappearance is not None and reviewed_disappearance is not None:
            disappearance_errors.append(
                abs(predicted_disappearance - reviewed_disappearance)
            )
    return SmokeEvaluation(
        reviewed_label_count=label_count,
        prediction_count=prediction_count,
        true_positives=true_positives,
        false_positives=prediction_count - true_positives,
        false_negatives=label_count - true_positives,
        precision=true_positives / prediction_count if prediction_count else None,
        recall=true_positives / label_count if label_count else None,
        appearance_timing_error_mean_s=(
            sum(appearance_errors) / len(appearance_errors) if appearance_errors else None
        ),
        disappearance_timing_error_mean_s=(
            sum(disappearance_errors) / len(disappearance_errors)
            if disappearance_errors else None
        ),
        appearance_timing_error_median_s=median(appearance_errors) if appearance_errors else None,
        disappearance_timing_error_median_s=(
            median(disappearance_errors) if disappearance_errors else None
        ),
    )


def _reject_duplicate_scoped_ids(
    predictions: Sequence[SmokeEvent],
    reviewed_labels: Sequence[ReviewedSmokeLabel],
) -> None:
    """Reject ambiguous IDs within each match/map/round namespace."""
    for records, identifier_name, kind in (
        (predictions, "event_id", "prediction"),
        (reviewed_labels, "label_id", "reviewed label"),
    ):
        seen: set[tuple[str, str, str, str]] = set()
        for record in records:
            scoped_id = (
                record.match_id, record.map_id, record.round_id,
                getattr(record, identifier_name),
            )
            if scoped_id in seen:
                raise ValueError(f"duplicate scoped {kind} ID: {scoped_id!r}")
            seen.add(scoped_id)
