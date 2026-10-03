"""Small deterministic movement-rule and aggregation tests."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

import valoscribe.tactical.cli as cli_module
from valoscribe.tactical.config import ExcludedInterval, load_config, load_map_config
from valoscribe.tactical.contracts import RoundMovementSummary
from valoscribe.tactical.pipeline import analyze_config
from valoscribe.tactical.reporting import (
    build_round_summary,
    write_aggregate_report,
    write_round_report,
)

ROOT = Path(__file__).parents[1]


def _setup():
    config, _ = load_config(ROOT / "configs/examples/ascent-team-movement.example.yaml")
    round_config = config.rounds[0]
    map_data = {"commitment_zones": {"A": ["a_main", "a_site"], "B": ["b_main", "b_site"]}}
    return config, round_config, map_data


def _samples(config, round_config, *, gap_at=None, reverse_at=None):
    rows = []
    for sample in range(64):
        offset = sample / config.run.sample_fps
        status = "partial"
        if gap_at is not None and gap_at <= offset < gap_at + 0.75:
            status = "unknown"
        shifted = offset >= 9.0 and (reverse_at is None or offset < reverse_at)
        a_count = 3 if shifted else 1
        observed = 4
        rows.append(
            {
                "sample_index": sample,
                "source_timestamp_seconds": round(round_config.source_start_seconds + offset, 3),
                "coverage_status": status,
                "observed_marker_count": observed,
                "macro_counts": {
                    "A": a_count,
                    "MID": 1,
                    "B": 4 - a_count - 1,
                    "SPAWN": 0,
                    "OTHER": 0,
                },
                "zone_counts": {
                    "a_main": 3 if shifted else 0,
                    "a_site": 0,
                    "b_main": 0,
                    "b_site": 0,
                },
            }
        )
    return rows


def test_opening_and_sustained_shift_commitment_are_evidence_linked_candidates() -> None:
    config, round_config, map_data = _setup()
    rows = _samples(config, round_config)
    summary = build_round_summary(
        round_config.round_id,
        round_config,
        config,
        rows,
        report_root=Path("."),
        map_data=map_data,
    )

    assert summary.opening_distribution == {"A": 1, "MID": 1, "B": 2}
    assert summary.opening_observed_samples == summary.opening_sample_denominator
    assert summary.opening_confidence == "candidate_partial_coverage"
    assert summary.opening_evidence["modal_sample_count"] == 32
    assert len(summary.opening_evidence["samples"]) == 32
    assert summary.first_major_shift_direction == "A"
    assert summary.first_major_shift_evidence["after"]["sample_index"] == 44
    baseline = summary.first_major_shift_evidence["baseline_window"]
    assert (
        baseline["end_timestamp_seconds"]
        < summary.first_major_shift_evidence["persistence_window"]["start_timestamp_seconds"]
    )
    assert len(baseline["sample_indices"]) >= 8
    assert summary.commitment_evidence["sample"]["sample_index"] >= 44
    assert summary.opposite_side_presence == "unknown"
    assert summary.commitment_evidence["sample"]["coverage_status"] == "partial"


def test_unknown_live_samples_consume_bounded_opening_budget() -> None:
    config, round_config, map_data = _setup()
    rows = _samples(config, round_config)
    for row in rows[:8]:
        row["coverage_status"] = "unknown"
    summary = build_round_summary(
        round_config.round_id,
        round_config,
        config,
        rows,
        report_root=Path("."),
        map_data=map_data,
    )
    assert summary.opening_observed_samples == 24
    assert summary.opening_sample_denominator == 32
    assert summary.opening_completeness == "unknown"


def test_late_evidence_after_long_unknown_gap_is_not_opening_evidence() -> None:
    config, original_round, map_data = _setup()
    round_config = original_round.model_copy(
        update={"source_start_seconds": 790.0, "source_end_seconds": 870.0}
    )
    rows = [
        {
            "sample_index": 0,
            "source_timestamp_seconds": 790.0,
            "coverage_status": "unknown",
            "observed_marker_count": 0,
            "macro_counts": {},
        },
        {
            "sample_index": 296,
            "source_timestamp_seconds": 864.0,
            "coverage_status": "partial",
            "observed_marker_count": 4,
            "macro_counts": {"A": 4, "MID": 0, "B": 0},
        },
    ]
    summary = build_round_summary(
        round_config.round_id,
        round_config,
        config,
        rows,
        report_root=Path("."),
        map_data=map_data,
    )
    assert summary.opening_distribution is None
    assert summary.opening_sample_denominator == 1
    assert summary.opening_evidence["samples"] == []


def test_configured_excluded_start_defers_opening_window_by_gap_duration() -> None:
    config, original_round, map_data = _setup()
    start = original_round.source_start_seconds
    round_config = original_round.model_copy(
        update={
            "excluded_intervals": [
                ExcludedInterval(
                    start_seconds=start,
                    end_seconds=start + 2,
                    reason="explicit replay exclusion",
                )
            ]
        }
    )
    rows = _samples(config, round_config)
    for row in rows:
        offset = row["source_timestamp_seconds"] - start
        if offset < 2:
            row["coverage_status"] = "excluded"
        elif offset >= 10:
            row["coverage_status"] = "unknown"
    summary = build_round_summary(
        round_config.round_id,
        round_config,
        config,
        rows,
        report_root=Path("."),
        map_data=map_data,
    )
    assert summary.opening_sample_denominator == 40
    assert summary.opening_observed_samples == 32
    assert summary.opening_evidence["samples"][-1]["timestamp_seconds"] == pytest.approx(
        start + 9.75
    )


def test_opposite_presence_requires_positive_evidence_or_strong_coverage() -> None:
    config, round_config, map_data = _setup()
    four_marker_rows = _samples(config, round_config)
    for row in four_marker_rows:
        row["coverage_status"] = "good"
        if row["source_timestamp_seconds"] >= round_config.source_start_seconds + 9:
            row["macro_counts"]["B"] = 1
            row["macro_counts"]["MID"] = 0
    positive = build_round_summary(
        round_config.round_id,
        round_config,
        config,
        four_marker_rows,
        report_root=Path("."),
        map_data=map_data,
    )
    assert positive.opposite_side_presence == "present"
    assert positive.opposite_side_evidence

    four_marker_rows = _samples(config, round_config)
    for row in four_marker_rows:
        row["coverage_status"] = "good"
    four_marker_absence = build_round_summary(
        round_config.round_id,
        round_config,
        config,
        four_marker_rows,
        report_root=Path("."),
        map_data=map_data,
    )
    assert four_marker_absence.opposite_side_presence == "unknown"

    five_marker_rows = _samples(config, round_config)
    for row in five_marker_rows:
        row["coverage_status"] = "good"
        row["observed_marker_count"] = 5
        if row["source_timestamp_seconds"] >= round_config.source_start_seconds + 9:
            row["macro_counts"]["MID"] = 2
    strong_absence = build_round_summary(
        round_config.round_id,
        round_config,
        config,
        five_marker_rows,
        report_root=Path("."),
        map_data=map_data,
    )
    assert strong_absence.opposite_side_presence == "not_observed"


def test_unknown_gap_and_reversal_break_shift_and_commitment_persistence() -> None:
    config, round_config, map_data = _setup()
    gap_rows = _samples(config, round_config, gap_at=10.0, reverse_at=11.75)
    gap_summary = build_round_summary(
        round_config.round_id,
        round_config,
        config,
        gap_rows,
        report_root=Path("."),
        map_data=map_data,
    )
    assert gap_summary.first_major_shift_direction is None
    assert gap_summary.apparent_commitment_site is None
    assert gap_summary.unknown_intervals

    reversed_rows = _samples(config, round_config, reverse_at=10.75)
    reversed_summary = build_round_summary(
        round_config.round_id,
        round_config,
        config,
        reversed_rows,
        report_root=Path("."),
        map_data=map_data,
    )
    assert reversed_summary.first_major_shift_direction is None
    assert reversed_summary.apparent_commitment_site is None


def test_commitment_reversal_after_full_persistence_window_is_rejected() -> None:
    config, round_config, map_data = _setup()
    rows = _samples(config, round_config)
    for row in rows:
        offset = row["source_timestamp_seconds"] - round_config.source_start_seconds
        if offset >= 11.25:
            row["zone_counts"] = {"a_main": 0, "a_site": 0, "b_main": 3, "b_site": 0}
            row["macro_counts"].update({"A": 0, "B": 3, "MID": 1})
    summary = build_round_summary(
        round_config.round_id,
        round_config,
        config,
        rows,
        report_root=Path("."),
        map_data=map_data,
    )
    assert summary.first_major_shift_direction == "A"
    assert summary.apparent_commitment_site == "B"
    assert (
        summary.commitment_evidence["sample"]["timestamp_seconds"]
        >= round_config.source_start_seconds + 11.25
    )


def test_non_aligned_commitment_guard_includes_first_sample_after_endpoint() -> None:
    config, round_config, map_data = _setup()
    config = config.model_copy(
        update={"run": config.run.model_copy(update={"commitment_reversal_guard_seconds": 0.6})}
    )
    summary = build_round_summary(
        round_config.round_id,
        round_config,
        config,
        _samples(config, round_config),
        report_root=Path("."),
        map_data=map_data,
    )
    assert summary.apparent_commitment_site == "A"
    guard = summary.commitment_evidence["reversal_check_window"]
    guard_end = guard["end_timestamp_seconds"]
    expected_endpoint = (
        summary.commitment_evidence["persistence_window"]["end_timestamp_seconds"] + 0.6
    )
    assert guard_end >= expected_endpoint
    assert guard_end == pytest.approx(expected_endpoint + 0.15)


def test_back_site_continuation_passes_guard_but_cannot_initiate_commitment() -> None:
    config, round_config, map_data = _setup()
    map_data["commitment_continuation_zones"] = {
        "A": ["a_defensive_back_site"],
        "B": ["b_defensive_back_site"],
    }
    rows = _samples(config, round_config)
    for row in rows:
        offset = row["source_timestamp_seconds"] - round_config.source_start_seconds
        if 9.0 <= offset < 11.25:
            row["zone_counts"] = {
                "a_main": 2,
                "a_site": 1,
                "a_defensive_back_site": 0,
                "b_main": 0,
                "b_site": 0,
                "b_defensive_back_site": 0,
            }
        elif offset >= 11.25:
            row["zone_counts"] = {
                "a_main": 0,
                "a_site": 2,
                "a_defensive_back_site": 1,
                "b_main": 0,
                "b_site": 0,
                "b_defensive_back_site": 0,
            }
    summary = build_round_summary(
        round_config.round_id, round_config, config, rows, report_root=Path("."), map_data=map_data
    )
    assert summary.apparent_commitment_site == "A"
    assert summary.commitment_evidence["reversal_check_window"]["end_timestamp_seconds"] >= (
        summary.commitment_evidence["persistence_window"]["end_timestamp_seconds"]
        + config.run.commitment_reversal_guard_seconds
    )
    assert (
        summary.rule_configuration["commitment_continuation_zones"]
        == map_data["commitment_continuation_zones"]
    )
    legacy_map_data = {
        key: value for key, value in map_data.items() if key != "commitment_continuation_zones"
    }
    legacy = build_round_summary(
        round_config.round_id,
        round_config,
        config,
        rows,
        report_root=Path("."),
        map_data=legacy_map_data,
    )
    assert legacy.apparent_commitment_site is None

    # Without an initiation-zone observation, continuation zones cannot start the event.
    for row in rows:
        if row["source_timestamp_seconds"] >= round_config.source_start_seconds + 9.0:
            row["zone_counts"] = {
                "a_main": 0,
                "a_site": 0,
                "a_defensive_back_site": 3,
                "b_main": 0,
                "b_site": 0,
                "b_defensive_back_site": 0,
            }
    no_initiation = build_round_summary(
        round_config.round_id, round_config, config, rows, report_root=Path("."), map_data=map_data
    )
    assert no_initiation.apparent_commitment_site is None


def test_back_site_guard_still_requires_three_same_site_eligible_observations() -> None:
    config, round_config, map_data = _setup()
    map_data["commitment_continuation_zones"] = {"A": ["a_defensive_back_site"]}
    rows = _samples(config, round_config)
    for row in rows:
        offset = row["source_timestamp_seconds"] - round_config.source_start_seconds
        if offset >= 9.0:
            row["zone_counts"] = {
                "a_main": 0 if offset >= 11.25 else 3,
                "a_site": 0,
                "a_defensive_back_site": 2 if offset >= 11.25 else 0,
                "b_main": 0,
                "b_site": 0,
            }
            row["observed_marker_count"] = 3
    summary = build_round_summary(
        round_config.round_id, round_config, config, rows, report_root=Path("."), map_data=map_data
    )
    assert summary.apparent_commitment_site is None


@pytest.mark.parametrize(
    "guard_counts,unknown_at",
    [
        ({"a_site": 2, "a_lobby": 1}, None),
        ({"a_site": 2, "unknown": 1}, None),
        ({"a_site": 2, "b_site": 1}, None),
        ({"a_site": 2, "a_defensive_back_site": 1}, 11.5),
    ],
)
def test_continuation_does_not_accept_lobby_unmapped_opposite_or_gap(
    guard_counts, unknown_at
) -> None:
    config, round_config, map_data = _setup()
    map_data["commitment_continuation_zones"] = {
        "A": ["a_defensive_back_site"],
        "B": ["b_defensive_back_site"],
    }
    rows = _samples(config, round_config)
    for row in rows:
        offset = row["source_timestamp_seconds"] - round_config.source_start_seconds
        if 9.0 <= offset < 11.25:
            row["zone_counts"] = {
                "a_main": 3,
                "a_site": 0,
                "a_defensive_back_site": 0,
                "a_lobby": 0,
                "b_main": 0,
                "b_site": 0,
                "b_defensive_back_site": 0,
                "unknown": 0,
            }
        elif offset >= 11.25:
            row["zone_counts"] = {
                "a_main": 0,
                "a_site": guard_counts.get("a_site", 0),
                "a_defensive_back_site": guard_counts.get("a_defensive_back_site", 0),
                "a_lobby": guard_counts.get("a_lobby", 0),
                "b_main": 0,
                "b_site": guard_counts.get("b_site", 0),
                "b_defensive_back_site": 0,
                "unknown": guard_counts.get("unknown", 0),
            }
        if unknown_at is not None and offset == unknown_at:
            row["coverage_status"] = "unknown"
    summary = build_round_summary(
        round_config.round_id, round_config, config, rows, report_root=Path("."), map_data=map_data
    )
    assert summary.apparent_commitment_site is None


def test_zero_second_commitment_guard_is_explicitly_disabled() -> None:
    config, round_config, map_data = _setup()
    config = config.model_copy(
        update={"run": config.run.model_copy(update={"commitment_reversal_guard_seconds": 0})}
    )
    summary = build_round_summary(
        round_config.round_id,
        round_config,
        config,
        _samples(config, round_config),
        report_root=Path("."),
        map_data=map_data,
    )
    assert summary.apparent_commitment_site == "A"
    assert summary.commitment_evidence["reversal_check_window"] == {
        "disabled": True,
        "duration_seconds": 0.0,
        "sample_indices": [],
    }


def test_map_continuation_zone_validation_rejects_unknown_wrong_macro_and_bad_shape(
    tmp_path,
) -> None:
    source = json.loads((ROOT / "configs/maps/ascent.yaml").read_text(encoding="utf-8"))
    for continuation, expected_error in (
        ({"A": ["missing_zone"]}, "unknown zone"),
        ({"A": ["b_site"]}, "must belong to macro A"),
        ({"A": "a_defensive_back_site"}, "must map A/B to zone ID lists"),
    ):
        candidate = {**source, "commitment_continuation_zones": continuation}
        path = tmp_path / "map.json"
        path.write_text(json.dumps(candidate), encoding="utf-8")
        with pytest.raises(ValueError, match=expected_error):
            load_map_config(path)


def test_map_without_continuation_zones_keeps_legacy_guard_semantics(tmp_path) -> None:
    source = json.loads((ROOT / "configs/maps/ascent.yaml").read_text(encoding="utf-8"))
    source.pop("commitment_continuation_zones", None)
    path = tmp_path / "map.json"
    path.write_text(json.dumps(source), encoding="utf-8")
    assert load_map_config(path).get("commitment_continuation_zones", {}) == {}


def test_shift_requires_stable_adjacent_baseline_and_candidate_onset_persistence() -> None:
    config, round_config, map_data = _setup()
    rows = _samples(config, round_config)
    # A brief early increase fails persistence; the later stable level is only
    # one above its immediate stable baseline and cannot borrow the early peak.
    for row in rows:
        offset = row["source_timestamp_seconds"] - round_config.source_start_seconds
        if 6 <= offset < 6.5:
            row["macro_counts"].update({"A": 3, "B": 0})
        elif 6.5 <= offset < 12:
            row["macro_counts"].update({"A": 1, "B": 2})
        elif offset >= 12:
            row["macro_counts"].update({"A": 2, "B": 1})
    summary = build_round_summary(
        round_config.round_id,
        round_config,
        config,
        rows,
        report_root=Path("."),
        map_data=map_data,
    )
    assert summary.first_major_shift_evidence is None


def test_shift_persistence_cannot_borrow_a_later_streak_after_onset_fails() -> None:
    config, round_config, map_data = _setup()
    rows = _samples(config, round_config)
    for row in rows:
        offset = row["source_timestamp_seconds"] - round_config.source_start_seconds
        if 6 <= offset < 6.5:
            a_count = 3
        elif 6.5 <= offset < 12:
            a_count = 2
        elif offset >= 12:
            a_count = 3
        else:
            a_count = 1
        row["macro_counts"].update({"A": a_count, "B": 3 - a_count})
    summary = build_round_summary(
        round_config.round_id,
        round_config,
        config,
        rows,
        report_root=Path("."),
        map_data=map_data,
    )
    assert summary.first_major_shift_evidence is None


def test_first_shift_and_commitment_survive_unknown_gap_and_later_run() -> None:
    config, round_config, map_data = _setup()
    rows = _samples(config, round_config)
    for row in rows:
        offset = row["source_timestamp_seconds"] - round_config.source_start_seconds
        if 12.25 <= offset < 13.25:
            row["coverage_status"] = "unknown"
        elif offset >= 13.25:
            row["macro_counts"].update({"A": 1, "B": 2})
            row["zone_counts"] = {"a_main": 0, "a_site": 0, "b_main": 0, "b_site": 0}
    summary = build_round_summary(
        round_config.round_id,
        round_config,
        config,
        rows,
        report_root=Path("."),
        map_data=map_data,
    )
    assert summary.first_major_shift_direction == "A"
    assert (
        summary.commitment_evidence["sample"]["timestamp_seconds"]
        < round_config.source_start_seconds + 12.25
    )


def test_overcount_cannot_establish_absence_and_emits_specific_warning() -> None:
    config, round_config, map_data = _setup()
    rows = _samples(config, round_config)
    for row in rows:
        row["coverage_status"] = "good"
        row["observed_marker_count"] = 6
        if row["source_timestamp_seconds"] >= round_config.source_start_seconds + 9:
            row["macro_counts"].update({"A": 4, "MID": 2, "B": 0})
            row["zone_counts"] = {"a_main": 4, "a_site": 0, "b_main": 0, "b_site": 0}
    summary = build_round_summary(
        round_config.round_id,
        round_config,
        config,
        rows,
        report_root=Path("."),
        map_data=map_data,
    )
    assert summary.opposite_side_presence == "unknown"
    assert any(
        "exceeded the selected-team roster size of five" in item for item in summary.warnings
    )


def test_mid_shift_is_not_reported_as_a_site_regroup() -> None:
    config, round_config, map_data = _setup()
    rows = _samples(config, round_config)
    for row in rows:
        offset = row["source_timestamp_seconds"] - round_config.source_start_seconds
        if offset >= 9:
            row["macro_counts"].update({"A": 1, "MID": 3, "B": 0})
    summary = build_round_summary(
        round_config.round_id,
        round_config,
        config,
        rows,
        report_root=Path("."),
        map_data=map_data,
    )
    assert summary.first_major_shift_direction == "MID"
    assert summary.regroup_direction is None


@pytest.mark.parametrize("regroup_direction", ["A", "B"])
def test_mid_first_shift_regroup_evidence_survives_round_and_aggregate_json(
    tmp_path: Path, regroup_direction: str
) -> None:
    config, round_config, map_data = _setup()
    rows = _samples(config, round_config)
    for row in rows:
        offset = row["source_timestamp_seconds"] - round_config.source_start_seconds
        if 9 <= offset < 13:
            row["macro_counts"].update({"A": 1, "MID": 3, "B": 0})
        elif offset >= 13:
            row["macro_counts"].update(
                {
                    "A": 3 if regroup_direction == "A" else 1,
                    "MID": 1,
                    "B": 0 if regroup_direction == "A" else 2,
                }
            )
    summary = write_round_report(
        tmp_path,
        round_config.round_id,
        round_config,
        config,
        rows,
        map_data,
    )
    assert summary.first_major_shift_direction == "MID"
    assert summary.first_major_shift_time == round_config.source_start_seconds + 11
    assert summary.first_major_shift_evidence["after"]["sample_index"] == 44
    assert summary.first_major_shift_evidence["persistence_window"]["sample_indices"] == list(
        range(36, 45)
    )
    assert summary.regroup_direction == regroup_direction

    saved_round = RoundMovementSummary.model_validate_json(
        (tmp_path / "summary.json").read_text(encoding="utf-8")
    )
    regroup_evidence = saved_round.regroup_evidence
    assert set(regroup_evidence) == {
        "timestamp_seconds",
        "sample_index",
        "observed_marker_count",
        "macro_counts",
        "coverage_status",
        "source",
        "before",
        "baseline_window",
        "persistence_window",
    }
    assert regroup_evidence["sample_index"] == 60
    assert regroup_evidence["timestamp_seconds"] == round_config.source_start_seconds + 15
    assert regroup_evidence["before"]["sample_index"] == 51
    assert (
        regroup_evidence["before"]["timestamp_seconds"] == round_config.source_start_seconds + 12.75
    )
    assert regroup_evidence["baseline_window"]["sample_indices"] == list(range(44, 52))
    assert (
        regroup_evidence["baseline_window"]["start_timestamp_seconds"]
        == round_config.source_start_seconds + 11
    )
    assert (
        regroup_evidence["baseline_window"]["end_timestamp_seconds"]
        == round_config.source_start_seconds + 12.75
    )
    assert regroup_evidence["persistence_window"]["sample_indices"] == list(range(52, 61))
    assert (
        regroup_evidence["persistence_window"]["start_timestamp_seconds"]
        == round_config.source_start_seconds + 13
    )
    assert (
        regroup_evidence["persistence_window"]["end_timestamp_seconds"]
        == round_config.source_start_seconds + 15
    )

    aggregate_dir = tmp_path / "aggregate"
    write_aggregate_report(
        aggregate_dir,
        config.run.run_id,
        [saved_round],
        [round_config.round_id],
        [],
    )
    representatives = json.loads(
        (aggregate_dir / "representative_rounds.json").read_text(encoding="utf-8")
    )
    assert representatives[0]["shift"] == saved_round.first_major_shift_evidence
    assert representatives[0]["regroup"] == regroup_evidence


def test_aggregate_keeps_included_excluded_denominators_and_unknown_round_ids(
    tmp_path: Path,
) -> None:
    config, round_config, map_data = _setup()
    summary = build_round_summary(
        round_config.round_id,
        round_config,
        config,
        _samples(config, round_config),
        report_root=tmp_path,
        map_data=map_data,
    )
    aggregate = write_aggregate_report(
        tmp_path / "aggregate",
        config.run.run_id,
        [summary],
        [round_config.round_id, "round-with-unknown-feature"],
        ["excluded-round"],
    )
    assert aggregate.included_rounds == [round_config.round_id, "round-with-unknown-feature"]
    assert aggregate.excluded_rounds == ["excluded-round"]
    assert aggregate.pattern_denominators["included_round_count"] == 2
    assert aggregate.feature_unknown_round_ids == [
        round_config.round_id,
        "round-with-unknown-feature",
    ]
    assert aggregate.feature_unknown_by_feature["opening_completeness"] == [
        round_config.round_id,
        "round-with-unknown-feature",
    ]
    for feature in (
        "opening",
        "opening_completeness",
        "regroup",
        "commitment",
        "opposite_side_presence",
    ):
        assert "round-with-unknown-feature" in aggregate.feature_unknown_by_feature[feature]
    assert (tmp_path / "aggregate/pattern_table.csv").is_file()
    assert (tmp_path / "aggregate/representative_rounds.json").is_file()


def test_analyze_emits_round_and_aggregate_report_artifacts(tmp_path: Path, monkeypatch) -> None:
    from valoscribe.tactical import pipeline

    config, raw_config = load_config(ROOT / "configs/examples/ascent-team-movement.example.yaml")
    round_config = config.rounds[0].model_copy(
        update={
            "source_start_seconds": 0.0,
            "source_end_seconds": 8.0,
            "live_start_offset_seconds": 0.0,
        }
    )
    second_round = round_config.model_copy(update={"round_id": "map3-round5"})
    config = config.model_copy(
        update={
            "run": config.run.model_copy(update={"run_id": "report-e2e", "output_root": tmp_path}),
            "rounds": [round_config, second_round],
        }
    )
    raw_config = config.model_dump_json().encode("utf-8")
    map_path = ROOT / "configs/maps/ascent.yaml"
    asset = np.zeros((config.map.canonical_height, config.map.canonical_width, 3), dtype=np.uint8)
    map_data = {"zones": [], "commitment_zones": {"A": [], "B": []}}
    monkeypatch.setattr(
        pipeline,
        "validate_source",
        lambda _config: (Path("fixture.mp4"), "a" * 64, (1920, 1080), 30.0),
    )
    monkeypatch.setattr(
        pipeline,
        "load_assets",
        lambda _config: (map_path, Path("map.png"), map_data, asset, np.ones((2, 2), np.uint8)),
    )
    monkeypatch.setattr(
        pipeline,
        "_make_calibration_artifacts",
        lambda _source, _config, _fps, _map, _asset, _mask, output: output.mkdir(),
    )

    def fake_process(
        _source, run_id, selected_round, active_config, _fps, _map, _asset, _mask, output
    ):
        output.mkdir(parents=True)
        coverage = []
        for index in range(32):
            coverage.append(
                {
                    "run_id": run_id,
                    "round_id": selected_round.round_id,
                    "sample_index": index,
                    "source_timestamp_seconds": index / active_config.run.sample_fps,
                    "observed_marker_count": 1,
                    "coverage_status": "partial",
                    "warning": "fixture candidate",
                }
            )
        (output / "raw_observations.jsonl").write_text("")
        (output / "sample_coverage.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in coverage)
        )
        for name in ("minimap_playback.mp4", "canonical_playback.mp4"):
            (output / name).write_bytes(b"fixture-video")
        (output / "summary.json").write_text(json.dumps({"artifacts": {}}))
        return Counter({"partial": len(coverage)}), len(coverage), 0, 0.0, 7.75

    monkeypatch.setattr(pipeline, "_process_round", fake_process)
    run_dir, _result = analyze_config(tmp_path / "config.yaml", config, raw_config)
    round_dir = run_dir / "rounds" / round_config.round_id
    second_round_dir = run_dir / "rounds" / second_round.round_id
    for saved_round_dir in (round_dir, second_round_dir):
        saved_summary = json.loads((saved_round_dir / "summary.json").read_text())
        typed_summary = RoundMovementSummary.model_validate(saved_summary)
        assert typed_summary.artifacts["occupancy_csv"] == "occupancy.csv"
    for path in (
        round_dir / "occupancy.csv",
        second_round_dir / "summary.json",
        round_dir / "occupancy.parquet",
        round_dir / "summary.json",
        round_dir / "summary.md",
        round_dir / "minimap_playback.mp4",
        round_dir / "canonical_playback.mp4",
        run_dir / "aggregate/summary.json",
        run_dir / "aggregate/summary.md",
        run_dir / "aggregate/pattern_table.csv",
        run_dir / "aggregate/representative_rounds.json",
    ):
        assert path.is_file(), path

    (second_round_dir / "corrections.jsonl").write_text("new-but-unrebuilt-correction\n")

    def fake_rebuild(_run_dir, selected_round_id, _config):
        revision_dir = run_dir / "rounds" / selected_round_id / "derived/revision-001"
        revision_dir.mkdir(parents=True)
        summary = json.loads((run_dir / "rounds" / selected_round_id / "summary.json").read_text())
        (revision_dir / "summary.json").write_text(json.dumps(summary))
        (revision_dir / "revision.json").write_text(json.dumps({"correction_count": 3}))
        return {"revision_directory": str(revision_dir)}

    monkeypatch.setattr(cli_module, "rebuild_round", fake_rebuild)
    result = CliRunner().invoke(
        cli_module.app,
        ["rebuild", "--run-dir", str(run_dir), "--round-id", round_config.round_id],
    )
    assert result.exit_code == 0, result.output
    aggregate_path = run_dir / "aggregate/derived-revision-001/summary.json"
    aggregate = json.loads(aggregate_path.read_text())
    assert aggregate["correction_counts_by_round"] == {
        round_config.round_id: 3,
        second_round.round_id: 0,
    }
    assert aggregate["consumed_round_revisions"] == {
        round_config.round_id: f"rounds/{round_config.round_id}/derived/revision-001/summary.json",
        second_round.round_id: f"rounds/{second_round.round_id}/summary.json",
    }
