"""Small deterministic movement-rule and aggregation tests."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import numpy as np

from valoscribe.tactical.config import load_config
from valoscribe.tactical.pipeline import analyze_config
from valoscribe.tactical.reporting import build_round_summary, write_aggregate_report

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
    assert summary.commitment_evidence["sample"]["sample_index"] >= 44
    assert summary.opposite_side_presence == "unknown"
    assert summary.commitment_evidence["sample"]["coverage_status"] == "partial"


def test_opening_window_counts_usable_samples_across_unknown_coverage() -> None:
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
    assert summary.opening_observed_samples == 32
    assert summary.opening_sample_denominator == 40
    assert summary.opening_completeness == "unknown"


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
    assert reversed_summary.first_major_shift_direction == "B"
    assert reversed_summary.apparent_commitment_site is None


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
    config = config.model_copy(
        update={
            "run": config.run.model_copy(update={"run_id": "report-e2e", "output_root": tmp_path}),
            "rounds": [round_config],
        }
    )
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
    for path in (
        round_dir / "occupancy.csv",
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
