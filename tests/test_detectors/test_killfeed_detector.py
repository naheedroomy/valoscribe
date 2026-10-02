"""Tests for killfeed agent detection."""

from unittest.mock import Mock

import numpy as np

from valoscribe.detectors.killfeed_detector import KillfeedDetector


def test_detect_entry_sets_optional_weapon_to_none() -> None:
    detector = KillfeedDetector(Mock())
    candidates = iter(
        [
            [("Jett", "attack", 0.95)],
            [("Sova", "defense", 0.90)],
        ]
    )
    detector._match_all_templates_candidates = lambda crop, flipped=False: next(candidates)

    detections = detector._detect_entry(np.zeros((2, 2, 3), dtype=np.uint8), 3)

    assert len(detections) == 1
    entry_index, detection = detections[0]
    assert entry_index == 3
    assert detection.weapon is None
