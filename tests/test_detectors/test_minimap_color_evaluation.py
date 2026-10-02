from __future__ import annotations

import hashlib

import numpy as np
import pytest

from tests.test_detectors.test_minimap_color_detector import profile, synthetic_crop
from valoscribe.detectors.minimap_color_detector import MinimapColorCandidateDetector
from valoscribe.detectors.minimap_color_evaluation import (
    LabeledMinimapFrame,
    LabeledMinimapFrameSet,
    ReviewedIconCenter,
    ReviewedIgnoreRegion,
    _maximum_cardinality_matches,
    evaluate_labeled_frames,
)


def frame(labels: list[ReviewedIconCenter]) -> LabeledMinimapFrameSet:
    return LabeledMinimapFrameSet(
        frames=[
            LabeledMinimapFrame(
                sample_id="reviewed-001",
                source_frame=750,
                vod_timestamp_s=12.5,
                image_path="reviewed/frame-750.png",
                width_px=120,
                height_px=100,
                reviewed_icons=labels,
            )
        ]
    )


def test_scores_reviewed_broadcast_color_centers_and_retains_provenance() -> None:
    labels = [ReviewedIconCenter(broadcast_color="broadcast-cyan", center_px=(30, 35))]
    result = evaluate_labeled_frames(
        MinimapColorCandidateDetector(profile()),
        frame(labels),
        {"reviewed-001": synthetic_crop()},
        match_tolerance_px=2,
    )
    assert (result.true_positive, result.false_positive, result.false_negative) == (1, 0, 0)
    assert result.precision == 1 and result.recall == 1
    assert result.frames[0].source_frame == 750
    assert result.frames[0].sample_id == "reviewed-001"


def test_one_to_one_matching_avoids_greedy_miss_and_threshold_is_inclusive() -> None:
    assert len(_maximum_cardinality_matches([[0.1, 1.0], [0.2, 9.0]], 1.0)) == 2
    assert _maximum_cardinality_matches([[1.01]], 1.0) == []


def test_empty_labels_and_detections_have_defined_counts_and_rates() -> None:
    result = evaluate_labeled_frames(
        MinimapColorCandidateDetector(profile()),
        frame([]),
        {"reviewed-001": np.zeros((100, 120, 3), dtype=np.uint8)},
        match_tolerance_px=3,
    )
    assert (result.true_positive, result.false_positive, result.false_negative) == (0, 0, 0)
    assert result.precision is None and result.recall is None


def test_ignore_region_excludes_only_inclusive_bounds_from_scoring() -> None:
    item = frame([
        ReviewedIconCenter(broadcast_color="broadcast-cyan", center_px=(30, 35)),
        ReviewedIconCenter(broadcast_color="broadcast-cyan", center_px=(38, 35)),
        ReviewedIconCenter(broadcast_color="broadcast-cyan", center_px=(39, 35)),
    ]).frames[0].model_copy(update={
        "ignore_regions": [ReviewedIgnoreRegion(
            reason="unresolved marker", bounds_px=(30, 30, 38, 40)
        )]
    })
    result = evaluate_labeled_frames(
        MinimapColorCandidateDetector(profile()),
        LabeledMinimapFrameSet(frames=[item]),
        {"reviewed-001": synthetic_crop()},
        match_tolerance_px=2,
    )
    assert (result.true_positive, result.false_positive, result.false_negative) == (0, 0, 1)
    assert result.frames[0].ignored_candidate_count == 1
    assert result.frames[0].unmatched_label_centers == (("broadcast-cyan", 39.0, 35.0),)


def test_decoded_hash_and_dimensions_are_checked() -> None:
    image = synthetic_crop()
    item = frame([]).frames[0].model_copy(update={
        "sha256_decoded_bgr": hashlib.sha256(image.tobytes()).hexdigest()
    })
    detector = MinimapColorCandidateDetector(profile())
    with pytest.raises(ValueError, match="decoded image hash"):
        evaluate_labeled_frames(
            detector, LabeledMinimapFrameSet(frames=[item]),
            {"reviewed-001": np.zeros_like(image)}, match_tolerance_px=2,
        )
    with pytest.raises(ValueError, match="dimensions do not match"):
        evaluate_labeled_frames(
            detector, frame([]), {"reviewed-001": np.zeros((90, 120, 3), dtype=np.uint8)},
            match_tolerance_px=2,
        )


def test_vta201_review_manifest_has_corrected_labels_regions_and_pinned_hashes() -> None:
    import json
    from pathlib import Path

    manifest = json.loads(
        (Path(__file__).parents[2] / "docs/minimap_color_review_vta201.json").read_text()
    )
    frames = manifest["frames"]
    assert [frame["split"] for frame in frames] == ["train", "heldout"]
    assert [len(frame["reviewed_icons"]) for frame in frames] == [6, 7]
    assert all(len(frame["sha256_decoded_bgr"]) == 64 for frame in frames)
    assert [frame["ignore_regions"][-1]["bounds_px"] for frame in frames] == [
        [247, 254, 265, 272], [247, 254, 265, 272]
    ]
    train = frames[0]
    assert [68, 194, 85, 211] in [
        region["bounds_px"] for region in train["ignore_regions"]
    ]
    assert all(
        icon["center_px"] != [75, 202] for icon in train["reviewed_icons"]
    )


def test_duplicate_sample_ids_and_missing_image_are_rejected() -> None:
    item = frame([]).frames[0]
    with pytest.raises(ValueError, match="sample_id values must be unique"):
        LabeledMinimapFrameSet(frames=[item, item])
    with pytest.raises(ValueError, match="missing image"):
        evaluate_labeled_frames(
            MinimapColorCandidateDetector(profile()), frame([]), {}, match_tolerance_px=2
        )
