"""Synthetic unit tests for side-agnostic minimap color candidates."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from valoscribe.detectors.minimap_color_detector import (
    BroadcastColorMask,
    HSVRange,
    MinimapColorCandidateDetector,
    MinimapColorProfile,
)
from valoscribe.types.persistent import RawMinimapColorCandidate


def profile() -> MinimapColorProfile:
    return MinimapColorProfile(
        profile_id="synthetic-test",
        colors=[
            BroadcastColorMask(
                color_id="broadcast-cyan",
                ranges=[HSVRange(lower=(80, 150, 150), upper=(100, 255, 255))],
            )
        ],
        minimum_area_px=30,
        maximum_area_fraction=0.1,
        minimum_circularity=0.65,
        minimum_aspect_ratio=0.7,
        maximum_aspect_ratio=1.0,
    )


def synthetic_crop() -> np.ndarray:
    crop = np.zeros((100, 120, 3), dtype=np.uint8)
    cv2.circle(crop, (30, 35), 8, (255, 255, 0), -1)  # BGR cyan; accepted shape
    cv2.rectangle(crop, (70, 25), (91, 36), (255, 255, 0), -1)  # rejected shape
    cv2.circle(crop, (108, 80), 1, (255, 255, 0), -1)  # below minimum area
    return crop


def test_candidates_are_ranked_typed_and_have_no_inferred_team_or_side(
    tmp_path,
) -> None:
    detector = MinimapColorCandidateDetector(profile())
    result = detector.detect(synthetic_crop(), vod_timestamp_s=12.5, source_frame=750)

    assert len(result.candidates) == 3
    accepted = [candidate for candidate in result.candidates if candidate.accepted]
    assert len(accepted) == 1
    assert accepted[0].broadcast_color == "broadcast-cyan"
    assert accepted[0].crop_point.x == pytest.approx(0.25, abs=0.01)
    assert accepted[0].crop_point.y == pytest.approx(0.35, abs=0.01)
    rejected = [candidate for candidate in result.candidates if not candidate.accepted]
    assert any("aspect_ratio_out_of_range" in item.rejection_reasons for item in rejected)
    assert any("area_below_minimum" in item.rejection_reasons for item in rejected)
    assert all(isinstance(item, RawMinimapColorCandidate) for item in result.candidates)
    assert all(item.source_frame == 750 for item in result.candidates)
    assert all("side" not in type(item).model_fields for item in result.candidates)
    assert all("team_id" not in type(item).model_fields for item in result.candidates)
    assert accepted[0].model_dump_json()

    overlay_path = tmp_path / "candidate-debug-overlay.png"
    assert cv2.imwrite(str(overlay_path), result.debug_overlay)
    assert cv2.imread(str(overlay_path)) is not None
    assert result.debug_overlay.shape == synthetic_crop().shape


def test_excluded_background_pixels_do_not_produce_candidates() -> None:
    crop = synthetic_crop()
    excluded = np.zeros(crop.shape[:2], dtype=np.uint8)
    excluded[20:50, 15:45] = 255

    result = MinimapColorCandidateDetector(profile()).detect(crop, excluded_background=excluded)

    assert not any(item.accepted for item in result.candidates)


def test_empty_crop_and_mismatched_background_mask_fail_clearly() -> None:
    detector = MinimapColorCandidateDetector(profile())
    with pytest.raises(ValueError, match="non-empty"):
        detector.detect(np.zeros((0, 0, 3), dtype=np.uint8))
    with pytest.raises(ValueError, match="match crop dimensions"):
        detector.detect(synthetic_crop(), excluded_background=np.zeros((10, 10), dtype=np.uint8))


def test_checked_in_vta201_profile_loads_with_typed_evaluation_metadata() -> None:
    from pathlib import Path

    profile_path = (
        Path(__file__).parents[2]
        / "src/valoscribe/config/minimap_color_vta201_train_profile.json"
    )
    profile_data = profile_path.read_bytes()

    loaded = MinimapColorProfile.model_validate_json(profile_data)

    assert loaded.fit_split == (
        "calibration-300 only; selected on training F1 grid search; "
        "no heldout access during selection"
    )
    assert loaded.match_tolerance_px == 8
    assert loaded.minimum_area_px == 30
    assert loaded.maximum_area_fraction == 0.005


def test_profile_rejects_unknown_and_invalid_evaluation_metadata() -> None:
    profile_data = profile().model_dump()
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        MinimapColorProfile.model_validate({**profile_data, "unexpected": True})
    with pytest.raises(ValueError, match="fit_split must not be blank"):
        MinimapColorProfile.model_validate({**profile_data, "fit_split": "  "})
    with pytest.raises(ValueError, match="match_tolerance_px"):
        MinimapColorProfile.model_validate({**profile_data, "match_tolerance_px": -1})
    with pytest.raises(ValueError, match="match_tolerance_px"):
        MinimapColorProfile.model_validate({**profile_data, "match_tolerance_px": float("inf")})


def test_profile_rejects_invalid_hsv_and_even_morphology_kernel() -> None:
    with pytest.raises(ValueError, match="H 0..179"):
        HSVRange(lower=(180, 0, 0), upper=(180, 255, 255))
    with pytest.raises(ValueError, match="must be odd"):
        MinimapColorProfile(
            profile_id="bad",
            colors=[
                BroadcastColorMask(
                    color_id="cyan",
                    ranges=[HSVRange(lower=(80, 0, 0), upper=(100, 255, 255))],
                )
            ],
            minimum_area_px=1,
            maximum_area_fraction=0.2,
            minimum_circularity=0.0,
            minimum_aspect_ratio=0.1,
            maximum_aspect_ratio=1.0,
            morphology_kernel_size=2,
        )
