"""Exploratory source-crop smoke replay for the single VTA-502 event."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import cv2
import numpy as np

from valoscribe.analytics.smoke_source_observation import decoded_crop_sha256
from valoscribe.detectors.smoke_detector import detect_smoke_candidates
from valoscribe.maps.config import SmokeDetectionConfig
from valoscribe.types.persistent import EvidenceRef, EvidenceSource
from valoscribe.types.smoke_source_observation import (
    SmokeIndependentVisualReview,
    SmokeSourceObservation,
)

PROFILE = SmokeDetectionConfig(
    hsv_lower=(0, 0, 80),
    hsv_upper=(179, 25, 100),
    minimum_area_px=300,
    maximum_area_px=500,
    minimum_radius_px=9,
    maximum_radius_px=14,
    minimum_circularity=0.70,
)


def evaluate(video_path: Path, manifest_path: Path) -> dict[str, object]:
    """Validate source hashes and evaluate fixed train/holdout sample frames."""
    observation = SmokeSourceObservation.model_validate_json(manifest_path.read_text())
    review = observation.independent_visual_review
    if review is None:
        raise ValueError("independent visual review is required for candidate-only scoring")
    # Persistent models are mutable; validate reviewer evidence again at the
    # evaluation boundary before it is indexed by frame number.
    review = SmokeIndependentVisualReview.model_validate(review.model_dump())
    if review.smoke_identity != "UNRESOLVED":
        raise ValueError("unresolved smoke identity cannot establish smoke evaluation labels")
    if observation.center_tolerance_px is None:
        raise ValueError("center_tolerance_px is required for candidate scoring")
    samples = {sample.frame_index: sample for sample in observation.samples}
    scoring_frames = (149400, 149220, 150300, 150360)
    scoring_splits = {
        149400: "train",
        149220: "train",
        150300: "holdout",
        150360: "holdout",
    }
    for frame_index in scoring_frames:
        if frame_index not in samples:
            raise ValueError(f"candidate scoring requires reviewed frame {frame_index}")
    if video_path.name != observation.source_filename:
        raise ValueError("source video filename does not match observation")
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise ValueError(f"cannot open source video: {video_path}")
    try:
        dims = (
            int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
            int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        )
        if dims != (observation.source_frame_width, observation.source_frame_height):
            raise ValueError("source video dimensions do not match observation")
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        if not np.isfinite(fps) or abs(fps - observation.nominal_fps) > 0.05:
            raise ValueError("source video FPS does not match observation")
        expected_hashes = {
            frame_index: samples[frame_index].decoded_crop_sha256
            for frame_index in scoring_frames
        }
        expected_hashes.update(
            {evidence.frame_index: evidence.decoded_crop_sha256 for evidence in review.evidence}
        )
        if any(digest is None for digest in expected_hashes.values()):
            raise ValueError("missing hashed source observation for candidate scoring frame")
        verify_frames = sorted(expected_hashes)
        decoded: dict[int, tuple[np.ndarray, np.ndarray]] = {}
        for frame_index in verify_frames:
            if not capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index):
                raise ValueError(f"could not seek to expected frame {frame_index}")
            before = float(capture.get(cv2.CAP_PROP_POS_FRAMES))
            if not np.isfinite(before) or abs(before - frame_index) > 0.5:
                raise ValueError(f"seek position mismatch before frame {frame_index}")
            ok, frame = capture.read()
            after = float(capture.get(cv2.CAP_PROP_POS_FRAMES))
            if not np.isfinite(after) or abs(after - (frame_index + 1)) > 0.5:
                raise ValueError(f"seek position mismatch after frame {frame_index}")
            if not ok or frame.shape[:2] != (dims[1], dims[0]):
                raise ValueError(f"could not decode expected frame {frame_index}")
            image = cast(np.ndarray, frame).astype(np.uint8, copy=False)
            if decoded_crop_sha256(image, observation.crop) != expected_hashes[frame_index]:
                raise ValueError(f"decoded crop hash mismatch for frame {frame_index}")
            crop = image[
                observation.crop.y : observation.crop.y + observation.crop.height,
                observation.crop.x : observation.crop.x + observation.crop.width,
            ]
            decoded[frame_index] = (image, crop)
        records: list[dict[str, object]] = []
        for frame_index in scoring_frames:
            sample = samples[frame_index]
            _image, crop = decoded[frame_index]
            valid_mask = np.full(crop.shape[:2], 255, dtype=np.uint8)
            result = detect_smoke_candidates(
                crop,
                valid_mask,
                PROFILE,
                match_id="vta502-exploratory",
                map_id="source-crop",
                round_id="unknown",
                vod_timestamp_s=sample.timestamp_s,
                evidence=[
                    EvidenceRef(
                        match_id="vta502-exploratory",
                        map_id="source-crop",
                        round_id="unknown",
                        vod_timestamp_s=sample.timestamp_s,
                        source=EvidenceSource.MAIN_FRAME,
                        confidence=1.0,
                        note=f"decoded source crop frame {frame_index}",
                    )
                ],
                live_visible=True,
            )
            target_x, target_y = observation.center_source_crop_px
            tolerance = observation.center_tolerance_px
            near_footprint = [
                candidate for candidate in result.candidates
                if abs(candidate.center.x * crop.shape[1] - target_x) <= tolerance
                and abs(candidate.center.y * crop.shape[0] - target_y) <= tolerance
            ]
            records.append(
                {
                    "frame_index": frame_index,
                    "split": scoring_splits[frame_index],
                    "candidate_count": len(result.candidates),
                    "near_visual_footprint_center_count": len(near_footprint),
                    "centers_source_crop_px": [
                        [round(c.center.x * crop.shape[1], 2), round(c.center.y * crop.shape[0], 2)]
                        for c in result.candidates
                    ],
                }
            )
        return {
            "evaluation": "EXPLORATORY_VISUAL_FOOTPRINT_CANDIDATE_SCORING",
            "smoke_identity": review.smoke_identity,
            "production_acceptance": False,
            "smoke_precision_recall": "NOT_ESTABLISHED_IDENTITY_UNRESOLVED",
            "smoke_timing": "NOT_ESTABLISHED_IDENTITY_UNRESOLVED",
            "profile": PROFILE.model_dump(mode="json"),
            "samples": records,
            "locked_split": {"train_frames": [149400, 149220], "holdout_frames": [150300, 150360]},
            "candidate_counts_by_split": {
                split: {
                    "frames_scored": sum(r["split"] == split for r in records),
                    "candidates": sum(
                        int(cast(int, r["candidate_count"]))
                        for r in records
                        if r["split"] == split
                    ),
                    "near_visual_footprint_center": sum(
                        int(cast(int, r["near_visual_footprint_center_count"]))
                        for r in records
                        if r["split"] == split
                    ),
                }
                for split in ("train", "holdout")
            },
            "verified_independent_review_frames": sorted(
                {evidence.frame_index for evidence in review.evidence}
            ),
        }
    finally:
        capture.release()
