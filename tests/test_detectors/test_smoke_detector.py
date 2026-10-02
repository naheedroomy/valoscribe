import cv2
import numpy as np
import pytest

from valoscribe.detectors.smoke_detector import detect_smoke_candidates
from valoscribe.maps.config import SmokeDetectionConfig
from valoscribe.types.persistent import EvidenceRef, EvidenceSource


def config():
    return SmokeDetectionConfig(
        hsv_lower=(90, 100, 100), hsv_upper=(130, 255, 255),
        minimum_area_px=40, maximum_area_px=1000,
        minimum_radius_px=3, maximum_radius_px=20, minimum_circularity=0.9,
    )


_DEFAULT_CONFIG = object()


def run(image, *, valid_mask=None, live=True, detector_config=_DEFAULT_CONFIG):
    reference = EvidenceRef(
        match_id="m", map_id="map", round_id="r", vod_timestamp_s=1.0,
        source=EvidenceSource.MINIMAP, confidence=0.95,
    )
    return detect_smoke_candidates(
        image, np.full(image.shape[:2], 255, np.uint8) if valid_mask is None else valid_mask,
        config() if detector_config is _DEFAULT_CONFIG else detector_config,
        match_id="m", map_id="map", round_id="r", vod_timestamp_s=1.0,
        evidence=[reference], live_visible=live,
    )


def test_detects_circular_candidate_and_raw_frame_but_never_clear():
    image = np.zeros((100, 100, 3), np.uint8)
    cv2.circle(image, (48, 54), 10, (255, 0, 0), -1)
    result = run(image)
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.center.x == pytest.approx(0.48)
    assert candidate.center.y == pytest.approx(0.54)
    assert candidate.agent_type is None
    assert result.observation.candidates == result.candidates
    assert result.observation.active_region_clear is False
    assert np.any(result.overlay != image)


def test_non_circular_and_masked_occlusion_are_not_candidates_or_clear():
    image = np.zeros((100, 100, 3), np.uint8)
    cv2.rectangle(image, (20, 20), (40, 40), (255, 0, 0), -1)
    test_config = config().model_copy(update={"minimum_circularity": 0.99})
    result = run(image, detector_config=test_config)
    assert result.candidates == []
    assert result.observation.active_region_clear is False

    cv2.circle(image, (48, 54), 10, (255, 0, 0), -1)
    mask = np.zeros((100, 100), np.uint8)
    assert run(image, valid_mask=mask).candidates == []


def test_disabled_or_hidden_detection_fails_closed_and_never_attributes_agent():
    image = np.zeros((100, 100, 3), np.uint8)
    cv2.circle(image, (48, 54), 10, (255, 0, 0), -1)
    assert run(image, detector_config=None).candidates == []
    hidden = run(image, live=False)
    assert hidden.candidates == []
    assert not hidden.observation.live_visible
    assert not hidden.observation.active_region_clear


def test_invalid_detector_bounds_rejected():
    with pytest.raises(ValueError):
        SmokeDetectionConfig(
            hsv_lower=(130, 0, 0), hsv_upper=(90, 255, 255),
            minimum_area_px=100, maximum_area_px=10,
            minimum_radius_px=2, maximum_radius_px=1, minimum_circularity=0.5,
        )
