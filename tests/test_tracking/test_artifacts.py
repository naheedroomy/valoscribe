from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from valoscribe.tracking.artifacts import (
    ParquetUnavailableError,
    build_track_rows,
    evaluate_identity_labels,
    read_player_tracks_parquet,
    render_track_overlay,
    write_player_tracks_parquet,
    write_track_debug_playback,
)
from valoscribe.types.persistent import (
    NormalizedPoint,
    PlayerTrackEstimate,
    Side,
    SmoothedTrackSample,
    TrackIdentityLabel,
    TrackIdentityPrediction,
    TrackSmoothingInput,
)


def _sample(timestamp: float, *, observed: bool = True) -> TrackSmoothingInput:
    estimate = PlayerTrackEstimate(
        player_id="p1",
        vod_timestamp_s=timestamp,
        source_frame=int(timestamp * 30),
        position=NormalizedPoint(x=0.25, y=0.5) if observed else None,
        observed=observed,
        predicted=False,
        confidence=0.8 if observed else 0.0,
        evidence=["synthetic_detection" if observed else "detection_missing"],
        rejection_reason=None if observed else "not_detected",
    )
    return TrackSmoothingInput(
        estimate=estimate,
        round_id="r1",
        alive=True,
        interval_state="live",
        context_evidence=["synthetic_live_round"],
    )


def test_build_track_rows_preserves_raw_and_derived_values() -> None:
    raw = _sample(3.0)
    derived = SmoothedTrackSample(
        raw_estimate=raw.estimate,
        position=NormalizedPoint(x=0.3, y=0.5),
        observed=True,
        confidence=0.8,
        evidence=["synthetic_smoothed"],
    )

    rows = build_track_rows(
        [raw],
        (derived,),
        match_id="match-1",
        map_id="ascent",
        agent_by_player={"p1": "jett"},
        team_by_player={"p1": "alpha"},
        side_by_player={"p1": Side.ATTACK},
    )

    assert len(rows) == 1
    assert rows[0].x == 0.3
    assert rows[0].observed
    assert '"x":0.25' in rows[0].raw_estimate_json
    assert "synthetic_smoothed" in rows[0].derived_evidence_json


def test_build_track_rows_rejects_dropped_raw_estimate_and_missing_metadata() -> None:
    raw = _sample(1.0)
    unrelated = PlayerTrackEstimate(
        player_id="other",
        vod_timestamp_s=1.0,
        position=NormalizedPoint(x=0.1, y=0.2),
        observed=True,
        predicted=False,
        confidence=0.9,
        evidence=["synthetic"],
    )
    derived = SmoothedTrackSample(
        raw_estimate=unrelated,
        position=unrelated.position,
        observed=True,
        confidence=0.9,
        evidence=["synthetic"],
    )
    with pytest.raises(ValueError, match="corresponding raw"):
        build_track_rows(
            [raw],
            (derived,),
            match_id="m",
            map_id="ascent",
            agent_by_player={"p1": "jett"},
            team_by_player={"p1": "alpha"},
            side_by_player={"p1": Side.ATTACK},
        )
    with pytest.raises(ValueError, match="missing roster metadata"):
        build_track_rows(
            [raw],
            (
                SmoothedTrackSample(
                    raw_estimate=raw.estimate,
                    position=raw.estimate.position,
                    observed=True,
                    confidence=0.8,
                    evidence=["raw"],
                ),
            ),
            match_id="m",
            map_id="ascent",
            agent_by_player={},
            team_by_player={"p1": "alpha"},
            side_by_player={"p1": Side.ATTACK},
        )


def test_unlabeled_frame_metrics_fail_closed() -> None:
    metrics = evaluate_identity_labels([], [])
    assert not metrics.available
    assert metrics.reason == "labeled_identity_frames_unavailable"
    assert metrics.identity_accuracy is None


def test_labeled_metrics_report_accuracy_coverage_and_identity_switches() -> None:
    labels = [
        TrackIdentityLabel(
            match_id="m",
            round_id="r",
            vod_timestamp_s=time,
            candidate_id=f"c{int(time)}",
            expected_player_id="p1",
            visible=True,
        )
        for time in (1.0, 2.0, 3.0)
    ]
    predictions = [
        TrackIdentityPrediction(
            match_id="m",
            round_id="r",
            vod_timestamp_s=1.0,
            candidate_id="c1",
            assigned_player_id="p1",
        ),
        TrackIdentityPrediction(
            match_id="m",
            round_id="r",
            vod_timestamp_s=2.0,
            candidate_id="c2",
            assigned_player_id="p2",
        ),
    ]

    metrics = evaluate_identity_labels(labels, predictions)

    assert metrics.available
    assert metrics.labeled_visible_count == 3
    assert metrics.identity_accuracy == 0.5
    assert metrics.visible_player_coverage == pytest.approx(2 / 3)
    assert metrics.identity_switches == 1


def test_writer_fails_closed_when_pyarrow_is_not_installed(tmp_path: Path) -> None:
    import importlib.util

    if importlib.util.find_spec("pyarrow") is not None:
        pytest.skip("pyarrow available; optional dependency failure path does not apply")
    with pytest.raises(ParquetUnavailableError, match="no output was written"):
        write_player_tracks_parquet(tmp_path / "player_tracks.parquet", [])
    assert not (tmp_path / "player_tracks.parquet").exists()
    with pytest.raises(ParquetUnavailableError):
        read_player_tracks_parquet(tmp_path / "player_tracks.parquet")


def test_parquet_round_trip_when_optional_dependency_is_available(tmp_path: Path) -> None:
    import importlib.util

    if importlib.util.find_spec("pyarrow") is None:
        pytest.skip("install the parquet extra to exercise Apache Parquet round-trip")
    import cv2
    import pyarrow.parquet as parquet

    inputs = [_sample(2.0), _sample(3.0)]
    outputs = tuple(
        SmoothedTrackSample(
            raw_estimate=raw.estimate,
            position=raw.estimate.position,
            observed=True,
            confidence=0.8,
            evidence=["synthetic"],
        )
        for raw in inputs
    )
    rows = build_track_rows(
        inputs,
        outputs,
        match_id="synthetic-match",
        map_id="ascent",
        agent_by_player={"p1": "jett"},
        team_by_player={"p1": "synthetic-team"},
        side_by_player={"p1": Side.UNKNOWN},
    )
    output = tmp_path / "player_tracks.parquet"

    write_player_tracks_parquet(output, rows)

    contents = output.read_bytes()
    assert contents[:4] == b"PAR1"
    assert contents[-4:] == b"PAR1"
    schema = parquet.read_schema(output)
    assert schema.metadata[b"valoscribe.schema"] == b"player_tracks/1.0"
    assert set(schema.names) == set(type(rows[0]).model_fields)
    decoded_rows = read_player_tracks_parquet(output)
    assert decoded_rows == rows
    assert [row.vod_timestamp_s for row in decoded_rows] == [2.0, 3.0]

    playback = write_track_debug_playback(
        tmp_path / "playback", np.zeros((64, 64, 3), dtype=np.uint8), decoded_rows
    )
    assert [path.name for path in playback] == [
        "frame_000000_00000002.000.png",
        "frame_000001_00000003.000.png",
    ]
    assert all(path.is_file() and cv2.imread(str(path)) is not None for path in playback)


def test_debug_playback_draws_stable_ids_for_positioned_rows() -> None:
    raw = _sample(1.0)
    derived = SmoothedTrackSample(
        raw_estimate=raw.estimate,
        position=raw.estimate.position,
        observed=True,
        confidence=0.8,
        evidence=["synthetic"],
    )
    rows = build_track_rows(
        [raw],
        (derived,),
        match_id="m",
        map_id="ascent",
        agent_by_player={"p1": "jett"},
        team_by_player={"p1": "alpha"},
        side_by_player={"p1": Side.ATTACK},
    )

    overlay = render_track_overlay(np.zeros((64, 64, 3), dtype=np.uint8), rows)

    assert overlay.shape == (64, 64, 3)
    assert np.any(overlay != 0)


def test_debug_playback_writes_ordered_independent_timestamp_frames(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import cv2

    import valoscribe.tracking.artifacts as artifacts

    rows = []
    for timestamp, player_id in ((2.0, "p2"), (1.0, "p1")):
        raw = _sample(timestamp)
        estimate = raw.estimate.model_copy(update={"player_id": player_id})
        raw = raw.model_copy(update={"estimate": estimate})
        derived = SmoothedTrackSample(
            raw_estimate=estimate,
            position=estimate.position,
            observed=True,
            confidence=0.8,
            evidence=["synthetic"],
        )
        rows.extend(
            build_track_rows(
                [raw],
                (derived,),
                match_id="m",
                map_id="ascent",
                agent_by_player={player_id: "jett"},
                team_by_player={player_id: "alpha"},
                side_by_player={player_id: Side.ATTACK},
            )
        )

    seen: list[list[str]] = []
    render = artifacts.render_track_overlay

    def capture(image: np.ndarray, frame_rows: list) -> np.ndarray:
        seen.append([row.player_id for row in frame_rows])
        return render(image, frame_rows)

    monkeypatch.setattr(artifacts, "render_track_overlay", capture)
    paths = write_track_debug_playback(
        tmp_path / "playback", np.zeros((64, 64, 3), dtype=np.uint8), rows
    )

    assert seen == [["p1"], ["p2"]]
    assert len(paths) == 2
    assert paths[0].name == "frame_000000_00000001.000.png"
    assert paths[1].name == "frame_000001_00000002.000.png"
    assert all(cv2.imread(str(path)) is not None for path in paths)


def test_debug_playback_rejects_empty_and_mixed_context(tmp_path: Path) -> None:
    import valoscribe.tracking.artifacts as artifacts

    image = np.zeros((16, 16, 3), dtype=np.uint8)
    with pytest.raises(ValueError, match="at least one row"):
        write_track_debug_playback(tmp_path, image, [])

    raw = _sample(1.0)
    derived = SmoothedTrackSample(
        raw_estimate=raw.estimate,
        position=raw.estimate.position,
        observed=True,
        confidence=0.8,
        evidence=["synthetic"],
    )
    rows = build_track_rows(
        [raw], (derived,), match_id="m", map_id="ascent",
        agent_by_player={"p1": "jett"}, team_by_player={"p1": "alpha"},
        side_by_player={"p1": Side.ATTACK},
    )
    other_round = rows[0].model_copy(update={"round_id": "r2"})
    with pytest.raises(ValueError, match="one match and round"):
        artifacts.write_track_debug_playback(tmp_path, image, [rows[0], other_round])
    assert list(tmp_path.iterdir()) == []
