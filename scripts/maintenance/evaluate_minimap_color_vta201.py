#!/usr/bin/env python3
"""Reproduce VTA-201 scored crops, hash checks, diagnostics, and debug overlays."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from valoscribe.detectors.minimap_color_detector import (
    BroadcastColorMask,
    HSVRange,
    MinimapColorCandidateDetector,
    MinimapColorProfile,
)
from valoscribe.detectors.minimap_color_evaluation import (
    LabeledMinimapFrame,
    LabeledMinimapFrameSet,
    evaluate_labeled_frames,
)

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "docs/minimap_color_review_vta201.json"
PROFILE = ROOT / "src/valoscribe/config/minimap_color_vta201_train_profile.json"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--profile", type=Path, default=PROFILE)
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--crops-dir", type=Path, help="Directory containing crop PNGs by sample ID"
    )
    source.add_argument(
        "--video", type=Path, help="Local original VOD; indexed at manifest source_frame"
    )
    parser.add_argument("--output-dir", type=Path, default=Path("/tmp/vta201-minimap-color"))
    return parser


def _read_manifest(path: Path) -> tuple[dict[str, Any], LabeledMinimapFrameSet]:
    manifest = json.loads(path.read_text())
    if manifest.get("schema_version") != "1.0":
        raise ValueError("unsupported reviewer manifest schema_version")
    frames = [
        LabeledMinimapFrame.model_validate({
            key: value for key, value in row.items()
            if key in LabeledMinimapFrame.model_fields
        })
        for row in manifest["frames"]
    ]
    return manifest, LabeledMinimapFrameSet(frames=frames)


def _profile(path: Path) -> tuple[MinimapColorProfile, float]:
    raw = json.loads(path.read_text())
    profile_data = {
        "profile_id": raw["profile_id"],
        "colors": [
            BroadcastColorMask(
                color_id=color["color_id"],
                ranges=[HSVRange.model_validate(value) for value in color["ranges"]],
            )
            for color in raw["colors"]
        ],
        **{key: raw[key] for key in (
            "minimum_area_px", "maximum_area_fraction", "minimum_circularity",
            "minimum_aspect_ratio", "maximum_aspect_ratio", "morphology_kernel_size",
        )},
    }
    return MinimapColorProfile.model_validate(profile_data), float(raw["match_tolerance_px"])


def _load_video_crop(video: Path, frame_index: int, crop: dict[str, int]) -> np.ndarray:
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise ValueError(f"cannot open local video: {video}")
    try:
        capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = capture.read()
        if not ok:
            raise ValueError(f"cannot decode source frame {frame_index} from {video}")
    finally:
        capture.release()
    x, y, width, height = crop["x"], crop["y"], crop["width_px"], crop["height_px"]
    if frame.shape[0] < y + height or frame.shape[1] < x + width:
        raise ValueError("decoded source frame is smaller than configured crop extent")
    return frame[y : y + height, x : x + width].copy()


def _load_images(
    manifest: dict[str, Any],
    dataset: LabeledMinimapFrameSet,
    crops_dir: Path | None,
    video: Path | None,
) -> dict[str, np.ndarray]:
    loaded: dict[str, np.ndarray] = {}
    if video is not None:
        crop = manifest["crop_provenance"]
        for frame in dataset.frames:
            loaded[frame.sample_id] = _load_video_crop(video, frame.source_frame, crop)
        return loaded
    for frame in dataset.frames:
        image_path = (
            crops_dir / f"{frame.sample_id}.png"
            if crops_dir is not None
            else Path(frame.image_path)
        )
        if not image_path.is_file():
            raise ValueError(
                f"missing crop for {frame.sample_id}: {image_path}; supply --crops-dir or --video"
            )
        image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError(f"cannot decode crop image: {image_path}")
        loaded[frame.sample_id] = image
    return loaded


def main() -> int:
    args = _parser().parse_args()
    manifest, dataset = _read_manifest(args.manifest)
    profile, tolerance = _profile(args.profile)
    images = _load_images(manifest, dataset, args.crops_dir, args.video)
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)

    detector = MinimapColorCandidateDetector(profile)
    for frame in dataset.frames:
        image = images[frame.sample_id]
        result = detector.detect(
            image, vod_timestamp_s=frame.vod_timestamp_s, source_frame=frame.source_frame
        )
        if not cv2.imwrite(str(output / f"{frame.sample_id}-overlay.png"), result.debug_overlay):
            raise ValueError(f"failed to write overlay for {frame.sample_id}")

    evaluation = evaluate_labeled_frames(
        detector, dataset, images, match_tolerance_px=tolerance
    )
    frame_results = []
    for result in evaluation.frames:
        accepted, rejected = _candidate_counts(detector, dataset, images, result.sample_id)
        frame_results.append({
            "sample_id": result.sample_id,
            "split": next(f.split for f in dataset.frames if f.sample_id == result.sample_id),
            "tp": result.true_positive,
            "fp": result.false_positive,
            "fn": result.false_negative,
            "accepted_candidates": accepted,
            "rejected_candidates": rejected,
            "ignored_candidates": result.ignored_candidate_count,
            "unmatched_candidates_color_x_y": result.unmatched_candidate_centers,
            "unmatched_labels_color_x_y": result.unmatched_label_centers,
            "matched_distances_px": result.matched_distances_px,
        })
    split_metrics = {}
    for split in {frame.split for frame in dataset.frames}:
        selected = [
            result
            for result in evaluation.frames
            if next(
                frame.split
                for frame in dataset.frames
                if frame.sample_id == result.sample_id
            )
            == split
        ]
        tp = sum(result.true_positive for result in selected)
        fp = sum(result.false_positive for result in selected)
        fn = sum(result.false_negative for result in selected)
        split_metrics[split] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
        }
    report = {
        "profile_id": profile.profile_id,
        "match_tolerance_px": tolerance,
        "split_metrics": split_metrics,
        "tp": evaluation.true_positive,
        "fp": evaluation.false_positive,
        "fn": evaluation.false_negative,
        "precision": evaluation.precision,
        "recall": evaluation.recall,
        "frames": frame_results,
    }
    (output / "evaluation.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


def _candidate_counts(
    detector: MinimapColorCandidateDetector,
    dataset: LabeledMinimapFrameSet,
    images: dict[str, np.ndarray],
    sample_id: str,
) -> tuple[int, int]:
    frame = next(item for item in dataset.frames if item.sample_id == sample_id)
    result = detector.detect(images[sample_id])
    accepted = [candidate for candidate in result.candidates if candidate.accepted]
    ignored = sum(
        any(
            left <= candidate.crop_point.x * frame.width_px <= right
            and top <= candidate.crop_point.y * frame.height_px <= bottom
            for region in frame.ignore_regions
            for left, top, right, bottom in [region.bounds_px]
        )
        for candidate in accepted
    )
    rejected_count = sum(not candidate.accepted for candidate in result.candidates)
    return len(accepted) - ignored, rejected_count


if __name__ == "__main__":
    raise SystemExit(main())
