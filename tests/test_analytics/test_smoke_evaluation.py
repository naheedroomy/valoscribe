import itertools
import json

import pytest
from pydantic import ValidationError
from pydantic_core import PydanticSerializationError

from valoscribe.analytics.smoke_evaluation import evaluate_smokes, evaluate_supported_smokes
from valoscribe.types.persistent import EvidenceRef, EvidenceSource, NormalizedPoint, SmokeEvent
from valoscribe.types.smoke_evaluation import (
    ReviewedSmokeLabel,
    SmokeEvaluation,
    SupportedReviewedSmokeLabel,
    SupportedSmokeEvaluation,
)


def prediction(event_id: str, *, x: float = 0.2, start: float = 10, end: float | None = 20,
               round_id: str = "r1", agent_type: str | None = None) -> SmokeEvent:
    evidence = EvidenceRef(
        match_id="m1", map_id="map1", round_id=round_id, vod_timestamp_s=start,
        source=EvidenceSource.MINIMAP, confidence=0.9,
    )
    return SmokeEvent(
        event_id=event_id, match_id="m1", map_id="map1", round_id=round_id,
        center=NormalizedPoint(x=x, y=0.5), approximate_radius=0.1, agent_type=agent_type,
        appeared_at_s=start, last_seen_at_s=start,
        disappeared_at_s=end, active_windows=[[start, start]], confidence=0.9,
        evidence=[evidence],
    )


def label(label_id: str, *, x: float = 0.2, start: float = 10, end: float | None = 20,
          round_id: str = "r1") -> ReviewedSmokeLabel:
    return ReviewedSmokeLabel(
        label_id=label_id, match_id="m1", map_id="map1", round_id=round_id,
        center=NormalizedPoint(x=x, y=0.5), appeared_at_s=start, disappeared_at_s=end,
    )


def supported_label(
    label_id: str, agent_type: str = "omen", **kwargs
) -> SupportedReviewedSmokeLabel:
    base = label(label_id, **kwargs)
    return SupportedReviewedSmokeLabel(
        **{**base.model_dump(), "schema_version": "2.0"}, agent_type=agent_type,
        attribution_evidence=[EvidenceRef(
            match_id=base.match_id, map_id=base.map_id, round_id=base.round_id,
            vod_timestamp_s=base.appeared_at_s, source=EvidenceSource.MAIN_FRAME,
            confidence=0.9, frame_path="review/frame-100.png",
        )],
    )


def test_event_metrics_are_one_to_one_allow_overlap_and_measure_timing():
    result = evaluate_smokes(
        [prediction("a", start=11, end=22), prediction("b", x=0.5)],
        [label("a", start=10, end=20), label("b", x=0.5)],
        spatial_tolerance=0.05, temporal_tolerance_s=2,
    )
    assert (result.true_positives, result.false_positives, result.false_negatives) == (2, 0, 0)
    assert result.precision == result.recall == 1.0
    assert result.appearance_timing_error_mean_s == 0.5
    assert result.disappearance_timing_error_mean_s == 1.0
    assert result.appearance_timing_error_median_s == 0.5
    assert result.disappearance_timing_error_median_s == 1.0


def test_duplicate_prediction_is_false_positive_and_unmatched_label_is_false_negative():
    result = evaluate_smokes(
        [prediction("first"), prediction("duplicate", start=10.01)], [label("reviewed")],
        spatial_tolerance=0.01, temporal_tolerance_s=0.1,
    )
    assert (result.true_positives, result.false_positives, result.false_negatives) == (1, 1, 0)


def test_tied_nearest_candidate_for_prediction_is_unmatched_in_any_permutation():
    p = prediction("p")
    labels = [label("first"), label("second")]
    outcomes = {
        (result.true_positives, result.false_positives, result.false_negatives)
        for perm in itertools.permutations(labels)
        for result in [evaluate_smokes([p], list(perm), spatial_tolerance=0.1,
                                       temporal_tolerance_s=1)]
    }
    assert outcomes == {(0, 1, 2)}


def test_tied_nearest_candidate_for_label_is_unmatched_in_any_permutation():
    predictions = [prediction("first"), prediction("second")]
    truth = [label("truth")]
    outcomes = {
        (result.true_positives, result.false_positives, result.false_negatives)
        for p_perm in itertools.permutations(predictions)
        for l_perm in itertools.permutations(truth)
        for result in [evaluate_smokes(list(p_perm), list(l_perm), spatial_tolerance=0.1,
                                       temporal_tolerance_s=1)]
    }
    assert outcomes == {(0, 2, 1)}


def test_ambiguous_endpoint_quarantines_all_incident_edges_in_both_directions():
    truth = [label("near-a", x=0.25), label("near-b", x=0.25), label("far", x=0.5)]
    pred = [prediction("p", x=0.25)]
    outcome = evaluate_smokes(
        pred, truth, spatial_tolerance=0.3, temporal_tolerance_s=1,
    )
    assert (outcome.true_positives, outcome.false_positives, outcome.false_negatives) == (0, 1, 3)

    predictions = [prediction("near-a", x=0.25), prediction("near-b", x=0.25),
                   prediction("far", x=0.5)]
    outcome = evaluate_smokes(
        predictions, [label("truth", x=0.25)], spatial_tolerance=0.3,
        temporal_tolerance_s=1,
    )
    assert (outcome.true_positives, outcome.false_positives, outcome.false_negatives) == (0, 3, 1)


def test_ambiguous_edges_do_not_block_unambiguous_one_to_one_match():
    result = evaluate_smokes(
        [prediction("tie", x=0.2), prediction("clear", x=0.8),
         prediction("separate", round_id="r2")],
        [label("left", x=0.2), label("right", x=0.2), label("separate", round_id="r2")],
        spatial_tolerance=0.1, temporal_tolerance_s=1,
    )
    assert (result.true_positives, result.false_positives, result.false_negatives) == (1, 2, 2)


def test_undetermined_disappearance_is_excluded_from_timing_error():
    result = evaluate_smokes(
        [prediction("unknown", end=None)], [label("unknown", end=None)],
        spatial_tolerance=0.1, temporal_tolerance_s=1,
    )
    assert result.true_positives == 1
    assert result.disappearance_timing_error_mean_s is None
    assert result.disappearance_timing_error_median_s is None


def test_even_and_odd_medians_are_calculated_for_each_timing_metric():
    odd = evaluate_smokes(
        [prediction("p1", x=0.1, start=11, end=20), prediction("p2", x=0.3, start=12, end=23),
         prediction("p3", x=0.5, start=13, end=24)],
        [label("l1", x=0.1, start=10, end=20), label("l2", x=0.3, start=10, end=20),
         label("l3", x=0.5, start=10, end=20)],
        spatial_tolerance=0.1, temporal_tolerance_s=5,
    )
    even = evaluate_smokes(
        [prediction("p1", x=0.1, start=11, end=20), prediction("p2", x=0.3, start=12, end=23),
         prediction("p3", x=0.5, start=13, end=24), prediction("p4", x=0.7, start=14, end=26)],
        [label("l1", x=0.1, start=10, end=20), label("l2", x=0.3, start=10, end=20),
         label("l3", x=0.5, start=10, end=20), label("l4", x=0.7, start=10, end=20)],
        spatial_tolerance=0.1, temporal_tolerance_s=5,
    )
    assert odd.appearance_timing_error_median_s == 2
    assert odd.disappearance_timing_error_median_s == 3
    assert even.appearance_timing_error_median_s == 2.5
    assert even.disappearance_timing_error_median_s == 3.5


def test_metrics_are_unavailable_without_reviewed_label_denominators():
    no_labels = evaluate_smokes(
        [prediction("p")], [], spatial_tolerance=0.1, temporal_tolerance_s=1,
    )
    empty = evaluate_smokes([], [], spatial_tolerance=0.1, temporal_tolerance_s=1)
    assert no_labels.precision == 0.0 and no_labels.recall is None
    assert empty.precision is None and empty.recall is None
    assert empty.appearance_timing_error_mean_s is None
    assert empty.appearance_timing_error_median_s is None


def test_v1_evaluation_and_legacy_labels_remain_readable():
    legacy = {
        "schema_version": "1.0", "reviewed_label_count": 0, "prediction_count": 0,
        "true_positives": 0, "false_positives": 0, "false_negatives": 0,
    }
    parsed = SmokeEvaluation.model_validate(legacy)
    assert parsed.schema_version == "2.0"
    assert parsed.appearance_timing_error_median_s is None
    assert ReviewedSmokeLabel.model_validate(label("legacy").model_dump()).label_id == "legacy"
    assert supported_label("supported").schema_version == "2.0"


def test_median_metrics_must_be_finite():
    with pytest.raises(ValidationError):
        SmokeEvaluation(
            reviewed_label_count=0, prediction_count=0, true_positives=0,
            false_positives=0, false_negatives=0,
            appearance_timing_error_median_s=float("nan"),
        )


def test_supported_evaluation_excludes_ineligible_cohorts_and_scores_eligible_unmatched():
    labels = [
        supported_label("eligible", agent_type="omen"),
        supported_label("anonymous", agent_type="UNKNOWN"),
        supported_label("unsupported", agent_type="astra"),
        label("no-attribution"),
    ]
    predictions = [
        prediction("eligible", agent_type="omen"),
        prediction("anonymous", agent_type=None),
        prediction("unsupported", agent_type="astra"),
        prediction("eligible-unmatched", x=0.8, agent_type="omen"),
    ]
    result = evaluate_supported_smokes(
        predictions, labels, supported_agents=frozenset({"omen"}),
        spatial_tolerance=0.1, temporal_tolerance_s=1,
    )
    assert result.scope == "supported_agents"
    assert (result.reviewed_label_count, result.prediction_count) == (1, 2)
    assert (result.true_positives, result.false_positives, result.false_negatives) == (1, 1, 0)
    assert result.excluded_reviewed_anonymous_count == 1
    assert result.excluded_reviewed_unsupported_agent_count == 1
    assert result.excluded_reviewed_missing_attribution_count == 1
    assert result.excluded_prediction_anonymous_count == 1
    assert result.excluded_prediction_unsupported_agent_count == 1


def test_supported_evaluation_requires_known_same_agent_and_fails_closed_without_attribution():
    result = evaluate_supported_smokes(
        [prediction("wrong-agent", agent_type="brimstone")],
        [supported_label("wrong-agent", agent_type="omen")],
        supported_agents=frozenset({"omen", "brimstone"}),
        spatial_tolerance=0.1, temporal_tolerance_s=1,
    )
    assert (result.true_positives, result.false_positives, result.false_negatives) == (0, 1, 1)

    missing = evaluate_supported_smokes(
        [prediction("missing", agent_type="omen")], [label("missing")],
        supported_agents=frozenset({"omen"}), spatial_tolerance=0.1,
        temporal_tolerance_s=1,
    )
    assert missing.reviewed_label_count == 0
    assert missing.excluded_reviewed_missing_attribution_count == 1
    assert missing.false_positives == 1


def test_supported_label_requires_independent_attribution_evidence():
    with pytest.raises(ValidationError):
        SupportedReviewedSmokeLabel(**label("no-evidence").model_dump(), agent_type="omen")


def test_duplicate_scoped_ids_are_rejected_independent_of_input_order():
    duplicate_predictions = [prediction("duplicate", x=0.5),
                            prediction("duplicate", x=0.75), prediction("third", x=0.6875)]
    labels = [label("first", x=0.625), label("second", x=0.6875)]
    for order in (duplicate_predictions, list(reversed(duplicate_predictions))):
        with pytest.raises(ValueError, match="duplicate scoped prediction ID"):
            evaluate_smokes(order, labels, spatial_tolerance=0.125, temporal_tolerance_s=1)
    duplicate_labels = [label("duplicate"), label("duplicate", x=0.75)]
    for order in (duplicate_labels, list(reversed(duplicate_labels))):
        with pytest.raises(ValueError, match="duplicate scoped reviewed label ID"):
            evaluate_smokes([prediction("only")], order, spatial_tolerance=1,
                            temporal_tolerance_s=1)

    # IDs are scoped: reusing one in a distinct round remains valid.
    result = evaluate_smokes(
        [prediction("same", round_id="r1"), prediction("same", round_id="r2")],
        [label("same", round_id="r1"), label("same", round_id="r2")],
        spatial_tolerance=0.1, temporal_tolerance_s=1,
    )
    assert result.true_positives == 2


def test_supported_contract_rejects_missing_scope_unknown_and_duplicate_agents():
    base = SmokeEvaluation(
        reviewed_label_count=0, prediction_count=0, true_positives=0,
        false_positives=0, false_negatives=0,
    ).model_dump()
    with pytest.raises(ValidationError):
        SupportedSmokeEvaluation(**base, supported_agents=["omen"],
                                  excluded_reviewed_anonymous_count=0,
                                  excluded_reviewed_unsupported_agent_count=0,
                                  excluded_reviewed_missing_attribution_count=0,
                                  excluded_prediction_anonymous_count=0,
                                  excluded_prediction_unsupported_agent_count=0)
    required = {**base, "scope": "supported_agents", "supported_agents": [" Omen "]}
    required.update({key: 0 for key in (
        "excluded_reviewed_anonymous_count", "excluded_reviewed_unsupported_agent_count",
        "excluded_reviewed_missing_attribution_count", "excluded_prediction_anonymous_count",
        "excluded_prediction_unsupported_agent_count",
    )})
    for agents in ([" Omen "], (" Omen ",), {" Omen "}, frozenset({" Omen "})):
        assert SupportedSmokeEvaluation(
            **{**required, "supported_agents": agents}
        ).supported_agents == ["omen"]
    for agents in (
        ["unknown"], ("UNKNOWN",), {"UNKNOWN"}, frozenset({"UNKNOWN"}),
        ["Omen", "omen"], ("Omen", "omen"), {"Omen", " omen"},
        frozenset({"Omen", " omen"}), ["   "], ("   ",), {"   "},
        frozenset({"   "}),
    ):
        with pytest.raises(ValidationError):
            SupportedSmokeEvaluation(**{**required, "supported_agents": agents})


def test_supported_agents_mutation_is_normalized_at_serialization_and_revalidated():
    base = SmokeEvaluation(
        reviewed_label_count=0, prediction_count=0, true_positives=0,
        false_positives=0, false_negatives=0,
    ).model_dump()
    supported = SupportedSmokeEvaluation(
        **{
            **base,
            "scope": "supported_agents",
            "supported_agents": ["omen", "brimstone"],
            **{key: 0 for key in (
                "excluded_reviewed_anonymous_count",
                "excluded_reviewed_unsupported_agent_count",
                "excluded_reviewed_missing_attribution_count",
                "excluded_prediction_anonymous_count",
                "excluded_prediction_unsupported_agent_count",
            )},
        }
    )
    supported.supported_agents[:] = [" Omen ", " Brimstone "]

    assert supported.model_dump()["supported_agents"] == ["omen", "brimstone"]
    assert json.loads(supported.model_dump_json())["supported_agents"] == ["omen", "brimstone"]
    assert supported.model_dump(exclude={"supported_agents": {1}})[
        "supported_agents"
    ] == ["omen"]
    assert json.loads(supported.model_dump_json(exclude={"supported_agents": {1}}))[
        "supported_agents"
    ] == ["omen"]
    assert supported.model_dump(include={"supported_agents": {1}})[
        "supported_agents"
    ] == ["brimstone"]
    assert json.loads(supported.model_dump_json(include={"supported_agents": {1}}))[
        "supported_agents"
    ] == ["brimstone"]

    for invalid_agents, message in (
        (["UNKNOWN", "brimstone"], "exclude UNKNOWN"),
        ([" ", "brimstone"], "must not be blank"),
        (["omen", " Omen "], "must not contain duplicates"),
    ):
        supported.supported_agents[:] = invalid_agents
        with pytest.raises(PydanticSerializationError, match=message):
            supported.model_dump()
        with pytest.raises(PydanticSerializationError, match=message):
            supported.model_dump_json()


def test_supported_attribution_requires_matching_scope_and_valid_mutable_evidence():
    base = label("scoped")
    wrong_scope = EvidenceRef(
        match_id="other", map_id=base.map_id, round_id=base.round_id,
        vod_timestamp_s=10, source=EvidenceSource.MAIN_FRAME, confidence=0.9,
    )
    with pytest.raises(ValidationError, match="scope must match"):
        SupportedReviewedSmokeLabel(
            **{**base.model_dump(), "schema_version": "2.0"}, agent_type="omen",
            attribution_evidence=[wrong_scope],
        )
    with pytest.raises(ValidationError):
        EvidenceRef(match_id="m1", map_id="map1", round_id="r1", vod_timestamp_s=10,
                    source=EvidenceSource.MAIN_FRAME, confidence=float("inf"))
    with pytest.raises(ValidationError, match="positive-confidence"):
        SupportedReviewedSmokeLabel(
            **{**base.model_dump(), "schema_version": "2.0"}, agent_type="omen",
            attribution_evidence=[EvidenceRef(
                match_id="m1", map_id="map1", round_id="r1", vod_timestamp_s=10,
                source=EvidenceSource.INFERENCE, confidence=0.9,
            )],
        )
    with pytest.raises(ValidationError, match="frame path or note"):
        SupportedReviewedSmokeLabel(
            **{**base.model_dump(), "schema_version": "2.0"}, agent_type="omen",
            attribution_evidence=[EvidenceRef(
                match_id="m1", map_id="map1", round_id="r1", vod_timestamp_s=10,
                source=EvidenceSource.MAIN_FRAME, confidence=0.9,
            )],
        )
    valid = supported_label("mutated")
    valid.attribution_evidence.clear()
    with pytest.raises(ValueError, match="failed attribution revalidation"):
        evaluate_supported_smokes(
            [prediction("mutated", agent_type="omen")], [valid],
            supported_agents=frozenset({"omen"}), spatial_tolerance=0.1,
            temporal_tolerance_s=1,
        )


def test_tolerances_must_be_finite_and_nonnegative():
    with pytest.raises(ValueError):
        evaluate_smokes([], [], spatial_tolerance=-1, temporal_tolerance_s=1)
    with pytest.raises(ValueError):
        evaluate_smokes([], [], spatial_tolerance=1, temporal_tolerance_s=float("nan"))
