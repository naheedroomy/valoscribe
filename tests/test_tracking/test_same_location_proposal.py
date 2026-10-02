from __future__ import annotations

import hashlib

import cv2
import numpy as np
import pytest

from valoscribe.detectors.minimap_color_detector import MinimapColorProfile
from valoscribe.tracking.same_location_proposal import (
    _color_support_mask,
    _ordered_candidates,
    _same_location_box,
    _score_same_location,
    run_same_location_proposal_diagnostic,
)
from valoscribe.types.persistent import NormalizedBox, NormalizedPoint, RawMinimapColorCandidate

PROFILE_PATH = "src/valoscribe/config/minimap_color_vta201_train_profile.json"


def _profile() -> MinimapColorProfile:
    from pathlib import Path

    return MinimapColorProfile.model_validate_json(Path(PROFILE_PATH).read_bytes())


def _candidate(x: int, y: int, width: int = 16, height: int = 16) -> RawMinimapColorCandidate:
    return RawMinimapColorCandidate(
        vod_timestamp_s=1.0,
        source_frame=1,
        color_profile_id="frozen-test-profile",
        broadcast_color="teal",
        crop_point=NormalizedPoint(x=(x + width / 2) / 80, y=(y + height / 2) / 80),
        bounding_box=NormalizedBox(x=x / 80, y=y / 80, width=width / 80, height=height / 80),
        contour_area_px=50.0,
        mask_pixel_count=60,
        detector_confidence=0.5,
        accepted=True,
    )


def _templates() -> list[tuple[str, str, np.ndarray]]:
    rng = np.random.default_rng(304)
    return [
        (f"template-{index}", f"agent-{index}", rng.integers(0, 256, (20, 20, 3), dtype=np.uint8))
        for index in range(4)
    ]


def test_same_location_scores_all_templates_on_exact_same_patch() -> None:
    image = np.zeros((50, 60, 3), dtype=np.uint8)
    patch = np.random.default_rng(51).integers(0, 256, (20, 20, 3), dtype=np.uint8)
    image[10:30, 20:40] = patch
    templates = _templates()
    templates[0] = (templates[0][0], templates[0][1], patch.copy())

    scores = _score_same_location(patch, templates, "fixture")

    assert [score.template_id for score in scores] == [item[0] for item in templates]
    assert [score.similarity for score in scores] == [
        float(cv2.matchTemplate(patch, template, cv2.TM_CCOEFF_NORMED)[0, 0])
        for _, _, template in templates
    ]
    assert scores[0].similarity == 1.0
    assert _score_same_location(patch, templates, "fixture") == scores


def test_overlapping_and_rejected_candidate_geometry_is_not_suppressed() -> None:
    accepted = _candidate(20, 20)
    rejected = RawMinimapColorCandidate(
        **{
            **accepted.model_dump(),
            "bounding_box": NormalizedBox(x=25 / 80, y=20 / 80, width=16 / 80, height=16 / 80),
            "crop_point": NormalizedPoint(x=33 / 80, y=28 / 80),
            "accepted": False,
            "rejection_reasons": ["area_below_minimum"],
        }
    )

    ordered = _ordered_candidates((rejected, accepted), 80, 80)

    assert ordered == [accepted, rejected]
    a, b = ordered
    ax, ay, aw, ah = (
        round(a.bounding_box.x * 80),
        round(a.bounding_box.y * 80),
        round(a.bounding_box.width * 80),
        round(a.bounding_box.height * 80),
    )
    bx, by, bw, bh = (
        round(b.bounding_box.x * 80),
        round(b.bounding_box.y * 80),
        round(b.bounding_box.width * 80),
        round(b.bounding_box.height * 80),
    )
    assert ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def test_border_neighborhood_is_clipped_not_clamped() -> None:
    box = _same_location_box(0, 0, 5, 5)
    assert box == (-8, -8, 20, 20)
    assert box[0] < 0 and box[1] < 0


def test_empty_color_support_is_explicit_and_not_foreground_claim() -> None:
    image = np.zeros((40, 40, 3), dtype=np.uint8)
    support = _color_support_mask(image, _profile(), "teal")
    assert support.shape == image.shape[:2]
    assert cv2.countNonZero(support) == 0
    # The persisted support label names only the frozen color threshold geometry.
    assert hashlib.sha256(support.tobytes()).hexdigest()


def test_wrong_packet_hash_and_missing_input_fail_before_processing(tmp_path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "manifest.json").write_text("{}", encoding="utf-8")
    absent_readback = tmp_path / "absent-readback"
    with pytest.raises(ValueError, match="pinned proposal packet"):
        run_same_location_proposal_diagnostic(
            source, tmp_path / "out", readback_root=absent_readback
        )
    with pytest.raises(FileNotFoundError):
        run_same_location_proposal_diagnostic(
            tmp_path / "missing", tmp_path / "out", readback_root=absent_readback
        )


def test_existing_output_directory_and_symlink_are_refused(tmp_path) -> None:
    missing_source = tmp_path / "missing-source"
    absent_readback = tmp_path / "absent-readback"
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        run_same_location_proposal_diagnostic(
            missing_source, existing, readback_root=absent_readback
        )
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        run_same_location_proposal_diagnostic(missing_source, link, readback_root=absent_readback)
