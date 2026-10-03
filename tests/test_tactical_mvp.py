"""Focused checks for the offline team-shape MVP seams."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from valoscribe.tactical.cli import app as tactical_app
from valoscribe.tactical.config import load_config
from valoscribe.tactical.contracts import CorrectionDelta, ReviewedFrame
from valoscribe.tactical.corrections import (
    corrected_rows,
    observation_id,
    rebuild_round,
    validate_delta,
)
from valoscribe.tactical.detection import crop_map_mask, detect_markers
from valoscribe.tactical.pipeline import (
    _crop,
    _process_round,
    assign_zone,
    create_run_directory,
)
from valoscribe.tactical.review import ReviewController

ROOT = Path(__file__).parents[1]


def test_real_example_config_is_typed_and_contains_five_round_intervals() -> None:
    config, _ = load_config(ROOT / "configs/examples/ascent-team-movement.example.yaml")

    assert config.run.sample_fps == 4.0
    assert len(config.rounds) == 5
    r9 = next(
        round_config for round_config in config.rounds if round_config.round_id == "map3-round9"
    )
    assert r9.excluded_intervals[0].start_seconds == 971
    assert r9.live_start_offset_seconds == 4


def test_crop_rejects_out_of_bounds_and_preserves_configured_region() -> None:
    config, _ = load_config(ROOT / "configs/examples/ascent-team-movement.example.yaml")
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    crop = _crop(frame, config)
    assert crop is not None and crop.shape == (400, 360, 3)

    frame[50:450, 70:430] = (1, 2, 3)
    assert np.all(_crop(frame, config) == (1, 2, 3))


def test_affine_map_mask_and_marker_detection_return_unforced_candidates() -> None:
    matrix = [[2.0, 0.0, 10.0], [0.0, 2.0, 20.0]]
    canonical_mask = np.full((100, 100), 255, dtype=np.uint8)
    crop_mask = crop_map_mask(canonical_mask, matrix, 40, 40)
    assert crop_mask.shape == (40, 40)
    assert crop_mask[5, 5] > 0

    config, _ = load_config(ROOT / "configs/examples/ascent-team-movement.example.yaml")
    settings = config.marker_detection.model_copy(
        update={"min_area_px": 4, "max_area_px": 100, "min_confidence": 0.0}
    )
    crop = np.zeros((40, 40, 3), dtype=np.uint8)
    cv2.circle(crop, (20, 20), 4, (0, 0, 255), -1)
    ranges = [
        type(config.broadcast.color_ranges_hsv_candidate_only[0])(
            lower=(0, 100, 80), upper=(10, 255, 255)
        )
    ]
    result = detect_markers(crop, ranges, settings, np.full((40, 40), 255, dtype=np.uint8))
    assert len(result.markers) == 1
    assert all("no_identity_assigned" in marker.flags for marker in result.markers)
    assert result.markers[0].crop_x == pytest.approx(20.5)


def test_zone_assignment_keeps_gaps_overlap_and_boundaries_unknown() -> None:
    map_data = {
        "zones": [
            {
                "zone_id": "a",
                "macro_group": "A",
                "vertices_px": [[0, 0], [10, 0], [10, 10], [0, 10]],
            },
            {
                "zone_id": "b",
                "macro_group": "B",
                "vertices_px": [[20, 0], [30, 0], [30, 10], [20, 10]],
            },
            {
                "zone_id": "overlap",
                "macro_group": "MID",
                "vertices_px": [[4, 4], [8, 4], [8, 8], [4, 8]],
            },
        ],
        "zone_assignment": {"boundary_tolerance_px": 2.0},
    }
    assert assign_zone(3, 3, map_data) == ("a", "A")
    assert assign_zone(5, 5, map_data) == ("unknown", "OTHER")
    assert assign_zone(10, 5, map_data) == ("unknown", "OTHER")
    assert assign_zone(15, 5, map_data) == ("unknown", "OTHER")
    assert assign_zone(5, 5, {**map_data, "floorplan_mask": np.zeros((40, 40), np.uint8)}) == (
        "unknown",
        "OTHER",
    )


def test_small_video_run_writes_raw_samples_coverage_and_playback(tmp_path: Path) -> None:
    config, _ = load_config(ROOT / "configs/examples/ascent-team-movement.example.yaml")
    config = config.model_copy(update={"run": config.run.model_copy(update={"run_id": "fixture"})})
    video_path = tmp_path / "fixture.mp4"
    writer = cv2.VideoWriter(str(video_path), cv2.VideoWriter.fourcc(*"mp4v"), 60.0, (1920, 1080))
    assert writer.isOpened()
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    cv2.circle(frame, (250, 250), 6, (0, 0, 255), -1)
    for _ in range(60):
        writer.write(frame)
    writer.release()
    asset = cv2.imread(
        str(ROOT / "src/valoscribe/config/maps/ascent_public_content_13_06.png"),
        cv2.IMREAD_COLOR,
    )
    assert asset is not None
    round_config = config.rounds[0].model_copy(
        update={
            "source_start_seconds": 0.0,
            "source_end_seconds": 1.0,
            "live_start_offset_seconds": 0.0,
        }
    )
    round_dir = tmp_path / "round"
    result = _process_round(
        video_path,
        "fixture",
        round_config,
        config,
        60.0,
        {"zones": [], "zone_assignment": {"boundary_tolerance_px": 2.0}},
        asset,
        np.full((2048, 2048), 255, dtype=np.uint8),
        round_dir,
    )

    assert result[1] == 4
    assert result[2] >= 1
    assert (round_dir / "raw_observations.jsonl").stat().st_size > 0
    assert len((round_dir / "sample_coverage.jsonl").read_text().splitlines()) == 4
    assert (round_dir / "minimap_playback.mp4").stat().st_size > 0
    assert (round_dir / "canonical_playback.mp4").stat().st_size > 0


def test_run_directory_creation_never_overwrites_existing_output(tmp_path: Path) -> None:
    run_dir = create_run_directory(tmp_path, "run-a")
    (run_dir / "marker").write_text("preserve")

    with pytest.raises(FileExistsError):
        create_run_directory(tmp_path, "run-a")

    assert (run_dir / "marker").read_text() == "preserve"


def test_config_rejects_invalid_crop_or_hsv() -> None:
    payload = json.loads((ROOT / "configs/examples/ascent-team-movement.example.yaml").read_text())
    payload["broadcast"]["minimap_crop"]["width"] = 0
    with pytest.raises(ValueError):
        load_config_data(payload)
    payload = json.loads((ROOT / "configs/examples/ascent-team-movement.example.yaml").read_text())
    payload["broadcast"]["minimap_crop"]["x"] = 1900
    with pytest.raises(ValueError, match="exceeds configured source dimensions"):
        load_config_data(payload)
    payload = json.loads((ROOT / "configs/examples/ascent-team-movement.example.yaml").read_text())
    payload["broadcast"]["color_ranges_hsv_candidate_only"][0]["lower"] = [20, 255, 255]
    payload["broadcast"]["color_ranges_hsv_candidate_only"][0]["upper"] = [10, 0, 0]
    with pytest.raises(ValueError, match="HSV lower bounds"):
        load_config_data(payload)


def test_correction_add_remove_move_and_reject_mismatched_targets(tmp_path: Path) -> None:
    config, _ = load_config(ROOT / "configs/examples/ascent-team-movement.example.yaml")
    config = config.model_copy(update={"run": config.run.model_copy(update={"run_id": "fixture"})})
    raw = [
        {
            "round_id": "map3-round4",
            "sample_index": 0,
            "canonical_x": 100.0,
            "canonical_y": 200.0,
            "source_timestamp_seconds": 5.0,
        }
    ]
    target = observation_id("map3-round4", 0, 0)
    move = CorrectionDelta(
        correction_id="move-1",
        run_id="fixture",
        round_id="map3-round4",
        sample_index=0,
        operation="move",
        target_observation_id=target,
        original_canonical_x=100,
        original_canonical_y=200,
        corrected_canonical_x=120,
        corrected_canonical_y=220,
        reviewer="test",
    )
    validate_delta(move, raw, config)
    delta_path = tmp_path / "round" / "corrections.jsonl"
    delta_path.parent.mkdir()
    delta_path.write_text(move.model_dump_json() + "\n")
    raw_path = delta_path.parent / "raw_observations.jsonl"
    raw_path.write_text(json.dumps(raw[0]) + "\n")
    (delta_path.parent / "sample_coverage.jsonl").write_text(
        json.dumps(
            {
                "sample_index": 0,
                "source_timestamp_seconds": 5.0,
            }
        )
        + "\n"
    )
    corrected, _ = corrected_rows(delta_path.parent, "map3-round4", config)
    assert len(corrected) == 1
    assert corrected[0]["canonical_x"] == 120
    with pytest.raises(ValueError, match="original position"):
        validate_delta(move.model_copy(update={"original_canonical_x": 101}), raw, config)
    add = move.model_copy(
        update={
            "operation": "add",
            "target_observation_id": None,
            "original_canonical_x": None,
            "original_canonical_y": None,
        }
    )
    validate_delta(add, raw, config)
    remove = move.model_copy(
        update={
            "operation": "remove",
            "corrected_canonical_x": None,
            "corrected_canonical_y": None,
        }
    )
    validate_delta(remove, raw, config)
    assert raw_path.read_text() == json.dumps(raw[0]) + "\n"


def test_add_correction_is_supported_for_a_sample_with_zero_raw_candidates(tmp_path: Path) -> None:
    config, _ = load_config(ROOT / "configs/examples/ascent-team-movement.example.yaml")
    config = config.model_copy(update={"run": config.run.model_copy(update={"run_id": "fixture"})})
    round_dir = tmp_path / "round"
    round_dir.mkdir()
    (round_dir / "raw_observations.jsonl").write_text("")
    (round_dir / "sample_coverage.jsonl").write_text(
        json.dumps(
            {
                "sample_index": 3,
                "source_timestamp_seconds": 10.75,
            }
        )
        + "\n"
    )
    delta = CorrectionDelta(
        correction_id="added",
        run_id="fixture",
        round_id="map3-round4",
        sample_index=3,
        operation="add",
        corrected_canonical_x=200,
        corrected_canonical_y=300,
        reviewer="test",
    )
    (round_dir / "corrections.jsonl").write_text(delta.model_dump_json() + "\n")
    corrected, _ = corrected_rows(round_dir, "map3-round4", config)
    assert len(corrected) == 1
    assert corrected[0]["source_timestamp_seconds"] == 10.75


def test_review_and_rebuild_commands_are_exposed() -> None:
    from typer.testing import CliRunner

    runner = CliRunner()
    assert runner.invoke(tactical_app, ["review", "--help"]).exit_code == 0
    assert runner.invoke(tactical_app, ["rebuild", "--help"]).exit_code == 0


def test_review_controller_blocks_navigation_until_staged_edits_are_saved_or_discarded() -> None:
    controller = ReviewController([4, 9])
    controller.select("observation")
    controller.stage({"operation": "add"})
    assert controller.dirty and controller.sample_index == 4
    assert controller.move(1) is False
    assert controller.sample_index == 4
    controller.discard()
    assert controller.move(1) is True
    assert controller.sample_index == 9 and controller.selected_id is None
    controller.saved()
    assert not controller.dirty and controller.staged == []


@pytest.mark.parametrize(
    ("scenario", "keys", "clicks", "has_raw"),
    [
        ("add-navigation-save", [ord("d"), ord("s"), ord("q")], [(20, 20), None, None], False),
        ("approve-save", [ord("v"), ord("s"), ord("q")], [None, None, None], False),
        (
            "remove-navigation-save",
            [127, ord("d"), ord("s"), ord("q")],
            [(10, 10), None, None, None],
            True,
        ),
        (
            "add-save-remove-save",
            [ord("s"), 127, ord("s"), ord("q")],
            [(20, 20), (10, 10), None, None],
            False,
        ),
        (
            "add-cancel-save",
            [ord("z"), 127, ord("s"), ord("q")],
            [(20, 20), (10, 10), None, None],
            False,
        ),
        (
            "add-discard-approve-save",
            [ord("x"), ord("v"), ord("s"), ord("q")],
            [(20, 20), None, None, None],
            False,
        ),
        (
            "remove-discard-edit-approve-save",
            [127, ord("x"), 127, ord("v"), ord("s"), ord("q")],
            [(10, 10), None, (10, 10), None, None, None],
            True,
        ),
    ],
)
def test_review_round_preserves_frame_binding_and_staged_marker_ids(
    tmp_path: Path, monkeypatch, scenario, keys, clicks, has_raw
) -> None:
    from valoscribe.tactical.review import review_round

    config, _ = load_config(ROOT / "configs/examples/ascent-team-movement.example.yaml")
    config = config.model_copy(
        update={"run": config.run.model_copy(update={"run_id": "fixture"})}
    )
    round_id = "map3-round4"
    round_dir = tmp_path / "run" / "rounds" / round_id
    round_dir.mkdir(parents=True)
    raw = (
        {
            "run_id": "fixture",
            "round_id": round_id,
            "sample_index": 0,
            "canonical_x": 100.0,
            "canonical_y": 100.0,
            "source_timestamp_seconds": 0.0,
            "confidence": 0.8,
        },
    ) if has_raw else ()
    (round_dir / "raw_observations.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in raw)
    )
    (round_dir / "sample_coverage.jsonl").write_text(
        "".join(
            json.dumps(
                {
                    "sample_index": index,
                    "source_timestamp_seconds": float(index),
                    "coverage_status": "partial",
                }
            )
            + "\n"
            for index in (0, 1)
        )
    )

    class Capture:
        def isOpened(self):  # noqa: N802
            return True

        def set(self, *_args):
            return True

        def read(self):
            return True, np.zeros((1080, 1920, 3), dtype=np.uint8)

        def release(self):
            pass

    callback = None
    call_index = 0

    def set_mouse_callback(_window, handler):
        nonlocal callback
        callback = handler

    def wait_key(_delay):
        nonlocal call_index
        x_y = clicks[call_index]
        if x_y is not None:
            callback(cv2.EVENT_LBUTTONDOWN, *x_y, 0, None)
        result = keys[call_index]
        call_index += 1
        return result

    monkeypatch.setattr(cv2, "VideoCapture", lambda _source: Capture())
    monkeypatch.setattr(cv2, "namedWindow", lambda *_args: None)
    monkeypatch.setattr(cv2, "setMouseCallback", set_mouse_callback)
    monkeypatch.setattr(cv2, "imshow", lambda *_args: None)
    monkeypatch.setattr(cv2, "waitKey", wait_key)
    monkeypatch.setattr(cv2, "destroyWindow", lambda *_args: None)
    monkeypatch.setattr(
        "valoscribe.tactical.review._display_points",
        lambda rows, _matrix: [(key, 10.0, 10.0, 1.0) for key, _row in rows],
    )

    review_round(tmp_path / "run", round_id, config)
    persisted = [
        json.loads(line)
        for line in (round_dir / "corrections.jsonl").read_text().splitlines()
    ] if (round_dir / "corrections.jsonl").exists() else []
    assert all(item["sample_index"] == 0 for item in persisted)
    if scenario == "approve-save":
        reviewed = [
            json.loads(line)
            for line in (round_dir / "reviewed_frames.jsonl").read_text().splitlines()
        ]
        assert reviewed[0]["approved"] is True
        assert persisted == []
    elif scenario == "add-navigation-save":
        assert [item["operation"] for item in persisted] == ["add"]
    elif scenario == "remove-navigation-save":
        assert [item["operation"] for item in persisted] == ["remove"]
    elif scenario == "add-save-remove-save":
        assert [item["operation"] for item in persisted] == ["add", "remove"]
        assert persisted[1]["target_observation_id"] == persisted[0]["correction_id"]
    elif scenario != "remove-discard-edit-approve-save":
        assert persisted == []
    if scenario == "remove-discard-edit-approve-save":
        assert [item["operation"] for item in persisted] == ["remove"]
        assert persisted[0]["target_observation_id"] == f"{round_id}:0:0"
        reviewed = [
            json.loads(line)
            for line in (round_dir / "reviewed_frames.jsonl").read_text().splitlines()
        ]
        assert reviewed[-1]["approved"] is True
        corrected, approved = corrected_rows(round_dir, round_id, config)
        assert approved == {0}
        assert corrected == []
    if scenario == "add-discard-approve-save":
        reviewed = [
            json.loads(line)
            for line in (round_dir / "reviewed_frames.jsonl").read_text().splitlines()
        ]
        assert reviewed[-1]["approved"] is True
        corrected, approved = corrected_rows(round_dir, round_id, config)
        assert approved == {0}
        assert corrected == []


def test_review_inspection_is_not_approval_and_approval_requires_eligible_coverage(
    tmp_path: Path,
) -> None:
    config, _ = load_config(ROOT / "configs/examples/ascent-team-movement.example.yaml")
    config = config.model_copy(update={"run": config.run.model_copy(update={"run_id": "fixture"})})
    round_id = "map3-round4"
    round_dir = tmp_path / "round"
    round_dir.mkdir()
    (round_dir / "raw_observations.jsonl").write_text("")
    coverage_path = round_dir / "sample_coverage.jsonl"
    coverage_path.write_text(
        "".join(
            json.dumps(
                {"sample_index": index, "source_timestamp_seconds": 1.0, "coverage_status": status}
            )
            + "\n"
            for index, status in ((0, "partial"), (1, "unknown"), (2, "excluded"), (3, "good"))
        )
    )
    review_path = round_dir / "reviewed_frames.jsonl"
    review_path.write_text(
        "".join(
            ReviewedFrame(
                run_id="fixture",
                round_id=round_id,
                sample_index=index,
                reviewer="reviewer",
                approved=index != 0,
            ).model_dump_json()
            + "\n"
            for index in (0, 3)
        )
    )
    _, approved = corrected_rows(round_dir, round_id, config)
    assert approved == {3}
    with review_path.open("a", encoding="utf-8") as stream:
        stream.write(
            ReviewedFrame(
                run_id="fixture", round_id=round_id, sample_index=3,
                reviewer="reviewer", approved=False,
            ).model_dump_json()
            + "\n"
        )
    _, approved = corrected_rows(round_dir, round_id, config)
    assert approved == set()
    legacy_review = ReviewedFrame.model_validate(
        {"run_id": "fixture", "round_id": round_id, "sample_index": 0, "reviewer": "old"}
    )
    assert legacy_review.approved is False
    for index in (1, 2):
        review_path.write_text(
            ReviewedFrame(
                run_id="fixture",
                round_id=round_id,
                sample_index=index,
                reviewer="reviewer",
                approved=True,
            ).model_dump_json()
            + "\n"
        )
        with pytest.raises(ValueError, match="only good or partial"):
            corrected_rows(round_dir, round_id, config)

    review_path.write_text(
        ReviewedFrame(
            run_id="fixture", round_id=round_id, sample_index=3,
            reviewer="reviewer", approved=True,
        ).model_dump_json()
        + "\n"
    )
    raw = {
        "run_id": "fixture",
        "round_id": round_id,
        "sample_index": 3,
        "canonical_x": None,
        "canonical_y": None,
        "confidence": 0.5,
        "source_timestamp_seconds": 1.0,
    }
    (round_dir / "raw_observations.jsonl").write_text(json.dumps(raw) + "\n")
    with pytest.raises(ValueError, match="missing canonical coordinates"):
        corrected_rows(round_dir, round_id, config)


def test_rebuild_generates_corrected_occupancy_without_detection(
    tmp_path: Path, monkeypatch
) -> None:
    import valoscribe.tactical.detection as detector

    config, raw_config = load_config(ROOT / "configs/examples/ascent-team-movement.example.yaml")
    source = tmp_path / "source.mp4"
    writer = cv2.VideoWriter(str(source), cv2.VideoWriter.fourcc(*"mp4v"), 30.0, (1920, 1080))
    assert writer.isOpened()
    for _ in range(10):
        writer.write(np.zeros((1080, 1920, 3), dtype=np.uint8))
    writer.release()
    config = config.model_copy(
        update={
            "run": config.run.model_copy(update={"run_id": "fixture"}),
            "source": config.source.model_copy(update={"video_path": source}),
            "rounds": [config.rounds[0].model_copy(update={"round_id": "map3-round4"})],
        }
    )
    run_dir = tmp_path / "run"
    round_dir = run_dir / "rounds" / "map3-round4"
    round_dir.mkdir(parents=True)
    (run_dir / "config.snapshot.yaml").write_bytes(raw_config)
    raw_row = {
        "run_id": "fixture",
        "round_id": "map3-round4",
        "sample_index": 0,
        "source_timestamp_seconds": 0.0,
        "canonical_x": 1100.0,
        "canonical_y": 800.0,
        "crop_x": 1.0,
        "crop_y": 1.0,
        "confidence": 0.7,
    }
    null_row = {
        **raw_row,
        "sample_index": 1,
        "canonical_x": None,
        "canonical_y": None,
        "quality_flags": ["transform_out_of_bounds"],
    }
    raw_path = round_dir / "raw_observations.jsonl"
    raw_payload = json.dumps(raw_row) + "\n" + json.dumps(null_row) + "\n"
    raw_path.write_text(raw_payload)
    (round_dir / "sample_coverage.jsonl").write_text(
        json.dumps(
            {
                "sample_index": 0,
                "source_timestamp_seconds": 0.0,
                "coverage_status": "partial",
                "observed_marker_count": 1,
                "warning": "unreviewed",
            }
        )
        + "\n"
        + json.dumps(
            {
                "sample_index": 1,
                "source_timestamp_seconds": 0.0,
                "coverage_status": "partial",
                "observed_marker_count": 1,
            }
        )
        + "\n"
    )
    (round_dir / "reviewed_frames.jsonl").write_text(
        ReviewedFrame(
            run_id="fixture", round_id="map3-round4", sample_index=0, reviewer="reviewer"
        ).model_dump_json()
        + "\n"
    )
    monkeypatch.setattr(detector, "detect_markers", lambda *args: pytest.fail("detector invoked"))
    import valoscribe.tactical.corrections as correction_module

    original_playbacks = correction_module._write_playbacks
    appended = False

    def append_after_snapshot(*args, **kwargs):
        nonlocal appended
        original_playbacks(*args, **kwargs)
        if not appended:
            late_delta = CorrectionDelta(
                correction_id="late-append",
                run_id="fixture",
                round_id="map3-round4",
                sample_index=0,
                operation="remove",
                target_observation_id="map3-round4:0:0",
                original_canonical_x=1100.0,
                original_canonical_y=800.0,
                reviewer="concurrent-reviewer",
            )
            with (round_dir / "corrections.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(late_delta.model_dump_json() + "\n")
            appended = True

    monkeypatch.setattr(correction_module, "_write_playbacks", append_after_snapshot)
    original_put_text = cv2.putText
    playback_captions: list[str] = []

    def capture_caption(image, text, *args, **kwargs):
        playback_captions.append(str(text))
        return original_put_text(image, text, *args, **kwargs)

    monkeypatch.setattr(cv2, "putText", capture_caption)
    first = rebuild_round(run_dir, "map3-round4", config)
    second = rebuild_round(run_dir, "map3-round4", config)
    assert first["detector_invoked"] is False
    assert first["correction_count"] == 0
    assert (
        first["corrections_sha256"]
        == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )
    assert second["correction_count"] == 1
    assert first["revision_directory"] != second["revision_directory"]
    revision = Path(first["revision_directory"])
    assert (revision / "corrected_observations.jsonl").is_file()
    assert (revision / "occupancy.csv").is_file()
    assert (revision / "occupancy.parquet").stat().st_size > 0
    assert (revision / "corrected_minimap.mp4").stat().st_size > 0
    assert (revision / "corrected_canonical.mp4").stat().st_size > 0
    manifest = json.loads((revision / "revision.json").read_text())
    assert manifest["reviewed_frame_count"] == 1
    with (revision / "occupancy.csv").open(encoding="utf-8") as stream:
        occupancy = list(csv.DictReader(stream))
    assert occupancy[0]["coverage_status"] == "partial"
    assert json.loads(occupancy[0]["warnings"]) == ["unreviewed"]
    assert occupancy[1]["coverage_status"] == "unknown"
    assert "lack canonical coordinates" in occupancy[1]["warnings"]
    assert raw_path.read_text() == raw_payload
    corrected = [
        json.loads(line)
        for line in (revision / "corrected_observations.jsonl").read_text().splitlines()
    ]
    assert corrected[1]["canonical_x"] is None
    second_corrected = [
        json.loads(line)
        for line in (Path(second["revision_directory"]) / "corrected_observations.jsonl")
        .read_text()
        .splitlines()
    ]
    assert not any(row["sample_index"] == 0 for row in second_corrected)
    with (Path(second["revision_directory"]) / "occupancy.csv").open(encoding="utf-8") as stream:
        second_occupancy = list(csv.DictReader(stream))
    assert second_occupancy[0]["corrected"] == "True"
    assert any("CORRECTED" in caption for caption in playback_captions)


def test_corrected_playback_captions_use_derived_coverage_and_warnings(
    tmp_path: Path, monkeypatch
) -> None:
    import valoscribe.tactical.corrections as corrections

    config, _ = load_config(ROOT / "configs/examples/ascent-team-movement.example.yaml")
    captured: list[str] = []

    class Capture:
        def isOpened(self):  # noqa: N802
            return True

        def set(self, *_args):
            return True

        def read(self):
            return True, np.zeros((1080, 1920, 3), dtype=np.uint8)

        def release(self):
            pass

    class Writer:
        def isOpened(self):  # noqa: N802
            return True

        def write(self, _frame):
            pass

        def release(self):
            pass

    class WriterFactory:
        fourcc = staticmethod(cv2.VideoWriter.fourcc)

        def __new__(cls, *_args):
            return Writer()

    monkeypatch.setattr(cv2, "VideoCapture", lambda _source: Capture())
    monkeypatch.setattr(cv2, "VideoWriter", WriterFactory)
    monkeypatch.setattr(cv2, "putText", lambda _image, text, *_args: captured.append(text))
    monkeypatch.setattr(cv2, "circle", lambda *_args: None)
    monkeypatch.setattr(cv2, "polylines", lambda *_args: None)
    monkeypatch.setattr(cv2, "solve", lambda *_args: np.eye(2))

    frames = [
        {
            "sample_index": 0,
            "source_timestamp_seconds": 1.0,
            "coverage_status": "partial",
            "warning": "detector warning",
        },
        {"sample_index": 1, "source_timestamp_seconds": 2.0, "coverage_status": "partial"},
    ]
    corrections._write_playbacks(
        tmp_path,
        "round",
        tmp_path,
        config,
        np.zeros((64, 64, 3), dtype=np.uint8),
        {"zones": []},
        {
            0: [
                {"canonical_x": 100.0, "canonical_y": 100.0},
                {"canonical_x": None, "canonical_y": None},
            ],
            1: [{"canonical_x": None, "canonical_y": None}],
        },
        frames,
        set(),
    )

    assert sum("coverage=partial" in text for text in captured) == 2
    assert sum("coverage=unknown" in text for text in captured) == 2
    assert sum("1 observation(s) lack canonical coordinates" in text for text in captured) == 4
    assert sum("detector warning" in text for text in captured) == 2


def load_config_data(payload: dict) -> None:
    from valoscribe.tactical.config import TacticalConfig

    TacticalConfig.model_validate(payload)
