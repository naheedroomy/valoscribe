import math

import pytest
from pydantic import ValidationError

from valoscribe.analytics.aggregates import RoundFeature, aggregate_rounds


def feature(round_id, *, category="execute", value=1.0, evidence=None):
    return RoundFeature(round_id=round_id, confidence=0.8,
                        evidence_ids=evidence or [f"e:{round_id}"],
                        categorical={"phase": category}, numeric={"clock": value})


def test_empty_sample_has_explicit_zero_size():
    result = aggregate_rounds([], outlier_threshold=1)
    assert result.sample_size == 0
    assert result.representative_round_ids == []


def test_single_and_duplicate_features_select_single_medoid_deterministically():
    one = aggregate_rounds([feature("r1")], outlier_threshold=0)
    duplicate = aggregate_rounds([feature("r2"), feature("r1")], outlier_threshold=0)
    assert one.representative_round_ids == ["r1"]
    assert duplicate.representative_round_ids == ["r1"]


def test_ties_break_by_round_id_and_provenance_is_union():
    result = aggregate_rounds([feature("z"), feature("a")], outlier_threshold=1)
    assert result.representative_round_ids == ["a"]
    assert result.evidence_ids == ["e:a", "e:z"]


def test_unknown_fields_are_omitted_from_distance_and_summary():
    rows = [feature("a", category=None, value=None), feature("b", category="x", value=2)]
    result = aggregate_rounds(rows, outlier_threshold=0)
    assert result.categorical_distributions == {"phase": {"x": 1}}
    assert result.numeric_medians == {"clock": 2}
    assert result.outlier_round_ids == []


def test_mixed_outlier_is_separate_from_representative():
    rows = [feature("a", value=0), feature("b", value=0),
            feature("z", category="other", value=100)]
    result = aggregate_rounds(rows, outlier_threshold=0.8)
    assert result.representative_round_ids == ["a"]
    assert result.outlier_round_ids == ["z"]


def test_threshold_is_required_validated_and_duplicate_ids_rejected():
    with pytest.raises(ValueError):
        aggregate_rounds([feature("a")], outlier_threshold=float("nan"))
    with pytest.raises(ValueError):
        aggregate_rounds([feature("a"), feature("a")], outlier_threshold=1)


@pytest.mark.parametrize("updates", [
    {"schema_version": "2.0"},
    {"round_id": ""},
    {"confidence": float("nan")},
    {"confidence": 1.01},
    {"evidence_ids": []},
    {"evidence_ids": [""]},
    {"numeric": {"clock": float("inf")}},
])
def test_round_feature_rejects_invalid_persisted_values(updates):
    values = feature("a").model_dump()
    values.update(updates)
    with pytest.raises(ValidationError):
        RoundFeature.model_validate(values)


def test_numeric_summary_rejects_nonfinite_feature_value():
    with pytest.raises(ValidationError):
        feature("a", value=math.nan)


def test_no_overlap_produces_no_medoid_or_outliers():
    rows = [RoundFeature(round_id="a", confidence=0.8, evidence_ids=["a"],
                         categorical={"phase": None}, numeric={"clock": None}),
            RoundFeature(round_id="b", confidence=0.8, evidence_ids=["b"],
                         categorical={"phase": None}, numeric={"clock": None})]
    result = aggregate_rounds(rows, outlier_threshold=0)
    assert result.representative_round_ids == []
    assert result.outlier_round_ids == []


def test_unknown_only_round_is_excluded_from_medoid_and_permutation_is_stable():
    rows = [feature("a", category="x", value=1), feature("b", category="x", value=1),
            feature("z", category=None, value=None)]
    first = aggregate_rounds(rows, outlier_threshold=0)
    second = aggregate_rounds(list(reversed(rows)), outlier_threshold=0)
    assert first.model_dump() == second.model_dump()
    assert first.representative_round_ids == ["a"]
    assert first.outlier_round_ids == []


def test_empty_utility_and_zone_lists_remain_unknown():
    from valoscribe.analytics.aggregates import round_feature
    from valoscribe.analytics.scenarios import ScenarioSearchRecord

    record = ScenarioSearchRecord(round_id="r1", confidence=0.5, evidence_ids=["source"])
    result = round_feature(record)
    assert result.numeric["utility_count"] is None
    assert result.numeric["control_zone_count"] is None
    assert result.evidence_ids == ["source"]
