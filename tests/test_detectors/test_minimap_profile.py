"""Tests for opt-in, dimension-validated minimap HUD profiles."""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from tests.fixtures.generate_synthetic_frame import generate_synthetic_frame
from valoscribe.detectors.cropper import Cropper


def make_cropper(tmp_path: Path, **overrides: object) -> Cropper:
    config: dict[str, object] = {
        "name": "synthetic-test-profile",
        "frame_width": 320,
        "frame_height": 180,
        "minimap": {"x": 40, "y": 34, "width": 18, "height": 18},
        "regions": {},
    }
    config.update(overrides)
    config_path = tmp_path / "hud-profile.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return Cropper(config_path=config_path)


def test_minimap_crop_matches_synthetic_anchor_geometry(tmp_path: Path) -> None:
    frame_path, _ = generate_synthetic_frame(tmp_path / "fixture")
    frame = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
    assert frame is not None

    crop = make_cropper(tmp_path).crop_minimap(frame)

    assert crop.shape == (18, 18, 3)
    # Synthetic red anchor is centered at source (48, 42), crop-local (8, 8).
    assert np.array_equal(crop[8, 8], [0, 0, 255])
    assert np.count_nonzero(np.all(crop == [0, 0, 255], axis=2)) == 121


@pytest.mark.parametrize(
    ("profile_overrides", "frame", "message"),
    [
        ({"frame_width": 321}, np.zeros((180, 320, 3), dtype=np.uint8), "do not match"),
        (
            {"minimap": {"x": 319, "y": 0, "width": 2, "height": 1}},
            np.zeros((180, 320, 3), dtype=np.uint8),
            "outside the configured frame",
        ),
        (
            {"minimap": {"x": 1, "y": 1, "width": 0, "height": 1}},
            np.zeros((180, 320, 3), dtype=np.uint8),
            "positive size",
        ),
        ({}, np.zeros((180, 320), dtype=np.uint8), "height-width-channel"),
    ],
)
def test_invalid_minimap_profile_or_frame_fails_safely(
    tmp_path: Path,
    profile_overrides: dict[str, object],
    frame: np.ndarray,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        make_cropper(tmp_path, **profile_overrides).crop_minimap(frame)


def test_profiles_without_new_minimap_crop_return_empty_crop(tmp_path: Path) -> None:
    cropper = make_cropper(tmp_path, minimap=None)

    crop = cropper.crop_minimap(np.zeros((180, 320, 3), dtype=np.uint8))

    assert crop.shape == (0, 0, 3)


def test_profile_requires_explicit_frame_dimensions(tmp_path: Path) -> None:
    cropper = make_cropper(tmp_path, frame_width=None)

    with pytest.raises(ValueError, match="positive integer frame dimensions"):
        cropper.crop_minimap(np.zeros((180, 320, 3), dtype=np.uint8))


def test_legacy_profile_without_minimap_still_loads_and_keeps_output_key(
    tmp_path: Path,
) -> None:
    config_path = Path(__file__).parents[2] / "src/valoscribe/config/champs2025.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    del config["regions"]["minimap"]
    legacy_path = tmp_path / "legacy-without-minimap.json"
    legacy_path.write_text(json.dumps(config), encoding="utf-8")
    cropper = Cropper(config_path=legacy_path)

    result = cropper.crop_all_regions(np.zeros((1080, 1920, 3), dtype=np.uint8))

    assert "minimap" in result
    assert result["minimap"].shape == (0, 0, 3)
