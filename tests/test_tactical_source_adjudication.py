"""Source adjudications restrict tactical evidence without hiding review candidates."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import pytest

from valoscribe.tactical.config import load_config
from valoscribe.tactical.contracts import MarkerAdjudication, SourceAdjudicationMode
from valoscribe.tactical.corrections import (
    _effective_coverage,
    append_adjudications,
    corrected_rows,
    observation_id,
    rebuild_round,
    validate_adjudication,
)
from valoscribe.tactical.reporting import build_round_summary

ROOT = Path(__file__).parents[1]


def _config():
    config, _ = load_config(ROOT / "configs/examples/ascent-team-movement.example.yaml")
    return config.model_copy(update={"run": config.run.model_copy(update={"run_id": "fixture"})})


def _adjudication(
    target: str, disposition: Literal["supported", "deferred"] = "supported", **changes
):
    return MarkerAdjudication(
        adjudication_id=changes.pop("adjudication_id", f"adj-{target}"),
        run_id="fixture",
        round_id="map3-round4",
        sample_index=0,
        target_observation_id=target,
        disposition=disposition,
        reviewer="analyst",
        source_locator="vod://fixture/frame/100",
        source_timestamp_seconds=2.5,
        source_frame_index=changes.pop("source_frame_index", 100),
        confidence=0.9,
        **changes,
    )


def test_partial_adjudication_keeps_all_candidates_but_only_supports_selected_ids(
    tmp_path: Path,
) -> None:
    config = _config()
    round_dir = tmp_path / "round"
    round_dir.mkdir()
    coverage = [{"sample_index": 0, "source_timestamp_seconds": 2.5, "coverage_status": "partial"}]
    raw = [
        {
            "run_id": "fixture",
            "round_id": "map3-round4",
            "sample_index": 0,
            "source_timestamp_seconds": 2.5,
            "source_frame_index": 100,
            "canonical_x": i * 10.0,
            "canonical_y": 20.0,
            "confidence": 0.8,
        }
        for i in range(3)
    ]
    targets = [observation_id("map3-round4", 0, i) for i in range(3)]
    adjudications = [
        _adjudication(targets[0]),
        _adjudication(targets[1], "deferred"),
    ]

    rows, approved = corrected_rows(
        round_dir,
        "map3-round4",
        config,
        raw_history=raw,
        correction_history=[],
        review_history=[],
        adjudication_history=[item.model_dump(mode="json") for item in adjudications],
        coverage_history=coverage,
    )

    assert [row["observation_id"] for row in rows] == targets
    assert [row["tactical_eligible"] for row in rows] == [True, False, False]
    assert rows[1]["adjudication_disposition"] == "deferred"
    status, _ = _effective_coverage(
        {"sample_index": 0, "coverage_status": "good"}, rows, approved,
        source_adjudication_mode=True, eligible_count=1,
    )
    assert status == "partial"
    assert approved == set()
    assert all(row["source"] == "raw" for row in rows)
    assert all(row["source_adjudication_mode"] for row in rows)


def test_adjudication_rejects_cross_sample_target_binding(tmp_path: Path) -> None:
    config = _config()
    round_dir = tmp_path / "round"
    round_dir.mkdir()
    coverage = [
        {"sample_index": 0, "source_timestamp_seconds": 2.5, "coverage_status": "partial"},
        {"sample_index": 1, "source_timestamp_seconds": 2.75, "coverage_status": "partial"},
    ]
    raw = [{"round_id": "map3-round4", "sample_index": 1, "source_timestamp_seconds": 2.75,
            "canonical_x": 10.0, "canonical_y": 20.0}]
    misplaced = _adjudication(observation_id("map3-round4", 1, 0))
    with pytest.raises(ValueError, match="target observation"):
        corrected_rows(
            round_dir, "map3-round4", config, raw_history=raw, coverage_history=coverage,
            correction_history=[], review_history=[],
            adjudication_history=[misplaced.model_dump(mode="json")],
        )


def test_adjudication_requires_current_frame_evidence_and_unique_ids() -> None:
    config = _config()
    raw = [
        {
            "round_id": "map3-round4",
            "sample_index": 0,
            "source_frame_index": 100,
            "canonical_x": 10.0,
            "canonical_y": 20.0,
        }
    ]
    coverage = [{"sample_index": 0, "source_timestamp_seconds": 2.5, "coverage_status": "partial"}]
    item = _adjudication(observation_id("map3-round4", 0, 0))

    validate_adjudication(item, raw, coverage, config, [])
    with pytest.raises(ValueError, match="timestamp"):
        validate_adjudication(
            item.model_copy(update={"source_timestamp_seconds": 3.0}), raw, coverage, config, []
        )
    with pytest.raises(ValueError, match="duplicate"):
        validate_adjudication(item, raw, coverage, config, [item.model_dump(mode="json")])


def test_latest_appended_disposition_reverses_support_and_empty_mode_is_unknown(
    tmp_path: Path,
) -> None:
    config = _config()
    round_dir = tmp_path / "run" / "rounds" / "map3-round4"
    round_dir.mkdir(parents=True)
    target = observation_id("map3-round4", 0, 0)
    (round_dir / "raw_observations.jsonl").write_text(
        '{"round_id":"map3-round4","sample_index":0,"source_frame_index":100,'
        '"source_timestamp_seconds":2.5,"canonical_x":10.0,"canonical_y":20.0}\n'
    )
    (round_dir / "sample_coverage.jsonl").write_text(
        '{"sample_index":0,"source_timestamp_seconds":2.5,"coverage_status":"good"}\n'
    )
    append_adjudications(round_dir, [_adjudication(target)], config, "map3-round4")
    mode = SourceAdjudicationMode.model_validate_json(
        (tmp_path / "run" / "source_adjudication_mode.json").read_text()
    )
    assert mode.round_ids == ("map3-round4",)
    reversal = _adjudication(target, "deferred", adjudication_id="later-decision")
    append_adjudications(round_dir, [reversal], config, "map3-round4")
    rows, _ = corrected_rows(round_dir, "map3-round4", config)
    assert rows[0]["tactical_eligible"] is False
    assert rows[0]["adjudication_disposition"] == "deferred"
    assert len((round_dir / "marker_adjudications.jsonl").read_text().splitlines()) == 2

    (round_dir / "marker_adjudications.jsonl").write_text("")
    rows, _ = corrected_rows(round_dir, "map3-round4", config)
    assert rows[0]["source_adjudication_mode"] is True
    assert rows[0]["tactical_eligible"] is False
    status, _ = _effective_coverage(
        {"sample_index": 0, "coverage_status": "good"},
        rows,
        set(),
        source_adjudication_mode=True,
        eligible_count=0,
    )
    assert status == "unknown"
    (round_dir / "marker_adjudications.jsonl").unlink()
    with pytest.raises(ValueError, match="missing its adjudication sidecar"):
        rebuild_round(tmp_path / "run", "map3-round4", config)


def test_zero_source_supported_markers_cannot_create_tactical_events(tmp_path: Path) -> None:
    config = _config()
    round_config = config.rounds[0].model_copy(
        update={
            "round_id": "map3-round4",
            "source_start_seconds": 0.0,
            "source_end_seconds": 4.0,
            "live_start_offset_seconds": 0.0,
        }
    )
    occupancy = [
        {
            "sample_index": 0,
            "source_timestamp_seconds": 1.0,
            "observed_marker_count": 0,
            "zone_counts": {},
            "macro_counts": {"A": 0, "MID": 0, "B": 0, "SPAWN": 0, "OTHER": 0},
            "coverage_status": "unknown",
            "source_adjudication_mode": True,
            "supported_observation_ids": [],
            "adjudication_evidence": [],
        }
    ]
    summary = build_round_summary(
        "map3-round4",
        round_config,
        config,
        occupancy,
        report_root=tmp_path,
        map_data={"commitment_zones": {"A": ["a"], "B": ["b"]}},
    )
    assert summary.opening_distribution is None
    assert summary.first_major_shift_time is None
    assert summary.regroup_direction is None
    assert summary.apparent_commitment_site is None


def test_invalid_jsonl_sidecar_cannot_publish_a_derived_revision(tmp_path: Path) -> None:
    config = _config()
    run_dir = tmp_path / "run"
    round_dir = run_dir / "rounds" / "map3-round4"
    round_dir.mkdir(parents=True)
    (round_dir / "raw_observations.jsonl").write_text(
        '{"round_id":"map3-round4","sample_index":0,"source_timestamp_seconds":2.5,'
        '"canonical_x":10.0,"canonical_y":20.0}\n'
    )
    (round_dir / "sample_coverage.jsonl").write_text(
        '{"sample_index":0,"source_timestamp_seconds":2.5,"coverage_status":"partial"}\n'
    )
    raw_before = (round_dir / "raw_observations.jsonl").read_bytes()
    mode = SourceAdjudicationMode(run_id="fixture", round_ids=("map3-round4",))
    (run_dir / "source_adjudication_mode.json").write_text(mode.model_dump_json())

    with pytest.raises(ValueError, match="missing its adjudication sidecar"):
        rebuild_round(run_dir, "map3-round4", config)
    assert not list((round_dir / "derived").glob("revision-*"))

    (round_dir / "marker_adjudications.jsonl").write_text('{"partial":')
    with pytest.raises(ValueError, match="invalid JSONL"):
        rebuild_round(run_dir, "map3-round4", config)

    assert not list((round_dir / "derived").glob("revision-*"))
    assert (round_dir / "raw_observations.jsonl").read_bytes() == raw_before


def test_supported_invalid_position_is_inspectable_but_not_tactically_eligible() -> None:
    config = _config()
    raw = [
        {
            "round_id": "map3-round4", "sample_index": 0, "source_frame_index": 100,
            "source_timestamp_seconds": 2.5, "canonical_x": 0.0, "canonical_y": 0.0,
        },
        {
            "round_id": "map3-round4", "sample_index": 0, "source_frame_index": 100,
            "source_timestamp_seconds": 2.5, "canonical_x": None, "canonical_y": None,
        },
        {
            "round_id": "map3-round4", "sample_index": 0, "source_frame_index": 100,
            "source_timestamp_seconds": 2.5, "canonical_x": float("inf"), "canonical_y": 1.0,
        },
        {
            "round_id": "map3-round4", "sample_index": 0, "source_frame_index": 100,
            "source_timestamp_seconds": 2.5, "canonical_x": config.map.canonical_width,
            "canonical_y": 1.0,
        },
    ]
    targets = [observation_id("map3-round4", 0, index) for index in range(len(raw))]
    coverage = [{"sample_index": 0, "source_timestamp_seconds": 2.5, "coverage_status": "partial"}]
    rows, _ = corrected_rows(
        Path("."), "map3-round4", config, raw_history=raw, correction_history=[],
        review_history=[],
        adjudication_history=[_adjudication(target).model_dump(mode="json") for target in targets],
        coverage_history=coverage,
    )
    assert [row["observation_id"] for row in rows] == targets
    assert [row["adjudication_disposition"] for row in rows] == ["supported"] * len(raw)
    assert [row["tactical_eligible"] for row in rows] == [True, False, False, False]
    assert rows[0]["canonical_x"] == rows[0]["canonical_y"] == 0.0


def test_add_or_move_correction_id_cannot_reuse_raw_or_historical_id() -> None:
    from valoscribe.tactical.contracts import CorrectionDelta

    config = _config()
    raw = [{
        "round_id": "map3-round4", "sample_index": 0,
        "source_timestamp_seconds": 2.5, "canonical_x": 10.0, "canonical_y": 20.0,
    }]
    raw_id = observation_id("map3-round4", 0, 0)
    from valoscribe.tactical.corrections import validate_delta

    add = CorrectionDelta(
        correction_id=raw_id, run_id="fixture", round_id="map3-round4", sample_index=0,
        operation="add", corrected_canonical_x=12.0, corrected_canonical_y=22.0,
        reviewer="analyst",
    )
    move = add.model_copy(update={
        "operation": "move", "target_observation_id": raw_id,
        "original_canonical_x": 10.0, "original_canonical_y": 20.0,
    })
    for delta in (add, move):
        with pytest.raises(ValueError, match="correction id"):
            validate_delta(delta, raw, config, [])

    historical_add = add.model_copy(update={"correction_id": "historical-id"})
    removed = CorrectionDelta(
        correction_id="remove-record", run_id="fixture", round_id="map3-round4",
        sample_index=0, operation="remove", target_observation_id="historical-id",
        original_canonical_x=12.0, original_canonical_y=22.0, reviewer="analyst",
    )
    reused = add.model_copy(update={"correction_id": "historical-id"})
    history = [historical_add.model_dump(mode="json"), removed.model_dump(mode="json")]
    with pytest.raises(ValueError, match="correction id"):
        validate_delta(reused, raw, config, history)
    with pytest.raises(ValueError, match="correction id"):
        validate_delta(
            reused.model_copy(update={
                "operation": "move", "target_observation_id": raw_id,
                "original_canonical_x": 10.0, "original_canonical_y": 20.0,
            }), raw, config, history,
        )
    with pytest.raises(ValueError, match="correction id"):
        corrected_rows(
            Path("."), "map3-round4", config, raw_history=raw,
            correction_history=[*history, reused.model_dump(mode="json")],
            review_history=[], adjudication_history=[],
            coverage_history=[{"sample_index": 0, "source_timestamp_seconds": 2.5,
                               "coverage_status": "partial"}],
        )
    first_batch_delta = add.model_copy(update={"correction_id": "batch-id"})
    duplicate_batch_delta = first_batch_delta.model_copy()
    validate_delta(first_batch_delta, raw, config, [])
    with pytest.raises(ValueError, match="correction id"):
        validate_delta(duplicate_batch_delta, raw, config,
                       [first_batch_delta.model_dump(mode="json")])


def test_moved_or_removed_historical_targets_do_not_transfer_support() -> None:
    """Resolution is by current stable ID; corrections create distinct effective IDs."""
    config = _config()
    raw = [
        {
            "round_id": "map3-round4",
            "sample_index": 0,
            "source_frame_index": 100,
            "canonical_x": 10.0,
            "canonical_y": 20.0,
        }
    ]
    coverage = [{"sample_index": 0, "source_timestamp_seconds": 2.5, "coverage_status": "partial"}]
    original = observation_id("map3-round4", 0, 0)
    from valoscribe.tactical.contracts import CorrectionDelta

    move = CorrectionDelta(
        correction_id="new-position",
        run_id="fixture",
        round_id="map3-round4",
        sample_index=0,
        operation="move",
        target_observation_id=original,
        original_canonical_x=10.0,
        original_canonical_y=20.0,
        corrected_canonical_x=12.0,
        corrected_canonical_y=22.0,
        reviewer="analyst",
    )
    with pytest.raises(ValueError, match="target observation"):
        validate_adjudication(
            _adjudication(original), raw, coverage, config, [],
            [move.model_dump(mode="json")],
        )
    rows, _ = corrected_rows(
        Path("."),
        "map3-round4",
        config,
        raw_history=raw,
        correction_history=[move.model_dump(mode="json")],
        review_history=[],
        adjudication_history=[_adjudication(original).model_dump(mode="json")],
        coverage_history=coverage,
    )
    assert len(rows) == 1
    assert rows[0]["observation_id"] == "new-position"
    assert rows[0]["tactical_eligible"] is False
    assert rows[0]["source_adjudication_mode"] is True

    fresh_disposition = _adjudication("new-position", source_frame_index=None)
    revised_rows, _ = corrected_rows(
        Path("."),
        "map3-round4",
        config,
        raw_history=raw,
        correction_history=[move.model_dump(mode="json")],
        review_history=[],
        adjudication_history=[
            _adjudication(original).model_dump(mode="json"),
            fresh_disposition.model_dump(mode="json"),
        ],
        coverage_history=coverage,
    )
    assert revised_rows[0]["tactical_eligible"] is True
