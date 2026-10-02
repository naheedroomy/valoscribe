"""Offline conventions for deterministic synthetic image fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import cv2

from tests.fixtures.generate_synthetic_frame import COLORS_BGR, generate_synthetic_frame

GOLDEN_PATH = Path(__file__).parent / "expected" / "golden" / "synthetic_anchor_frame.json"


def _semantic_output(frame_path: Path, metadata_path: Path) -> dict[str, Any]:
    metadata = cast(
        dict[str, Any], json.loads(metadata_path.read_text(encoding="utf-8"))
    )
    frame = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
    assert frame is not None
    anchors = metadata["anchors"]
    for name, anchor in anchors.items():
        x, y = anchor["center_px"]
        anchor["color_bgr"] = frame[y, x].tolist()
        assert anchor["color_bgr"] == COLORS_BGR[name]
    return metadata


def test_synthetic_fixture_is_repeatable_small_and_matches_semantic_golden(
    tmp_path: Path,
) -> None:
    first_frame, first_metadata = generate_synthetic_frame(tmp_path / "first")
    second_frame, second_metadata = generate_synthetic_frame(tmp_path / "second")

    assert first_frame.read_bytes() == second_frame.read_bytes()
    assert first_metadata.read_bytes() == second_metadata.read_bytes()
    assert first_frame.stat().st_size < 20_000

    actual = _semantic_output(first_frame, first_metadata)
    expected = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    assert actual == expected
