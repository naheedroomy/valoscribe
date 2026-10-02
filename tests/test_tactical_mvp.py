"""Focused checks for the offline team-shape MVP seams."""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from valoscribe.tactical.config import load_config
from valoscribe.tactical.detection import crop_map_mask, detect_markers
from valoscribe.tactical.pipeline import (
    _crop,
    _process_round,
    assign_zone,
    create_run_directory,
)

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


def load_config_data(payload: dict) -> None:
    from valoscribe.tactical.config import TacticalConfig

    TacticalConfig.model_validate(payload)
