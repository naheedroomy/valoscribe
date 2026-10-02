"""Offline scoring of minimap color candidates against reviewed center labels."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Literal

import numpy as np
from pydantic import Field, field_validator

from valoscribe.detectors.minimap_color_detector import (
    MinimapColorCandidateDetector,
)
from valoscribe.types.persistent import PersistentModel


class ReviewedIconCenter(PersistentModel):
    """Human-reviewed visible icon center; color is a broadcast label, never a side."""

    broadcast_color: str = Field(min_length=1)
    center_px: tuple[float, float]

    @field_validator("center_px")
    @classmethod
    def finite_center(cls, value: tuple[float, float]) -> tuple[float, float]:
        if not all(math.isfinite(coordinate) for coordinate in value):
            raise ValueError("reviewed center coordinates must be finite")
        return value


class ReviewedIgnoreRegion(PersistentModel):
    """Pixel-aligned region whose unresolved contents are excluded from scoring."""

    reason: str = Field(min_length=1)
    bounds_px: tuple[int, int, int, int]

    @field_validator("bounds_px")
    @classmethod
    def valid_bounds(cls, value: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        if value[0] < 0 or value[1] < 0 or value[2] < value[0] or value[3] < value[1]:
            raise ValueError(
                "ignore bounds must be ordered non-negative inclusive pixel coordinates"
            )
        return value


class LabeledMinimapFrame(PersistentModel):
    """A frame image and reviewed icon centers, with reproducible provenance."""

    sample_id: str = Field(min_length=1)
    source_frame: int = Field(ge=0)
    vod_timestamp_s: float = Field(ge=0.0)
    image_path: str = Field(min_length=1)
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)
    split: Literal["train", "heldout"] = "train"
    sha256_decoded_bgr: str | None = None
    reviewed_icons: list[ReviewedIconCenter]
    ignore_regions: list[ReviewedIgnoreRegion] = Field(default_factory=list)

    @field_validator("sha256_decoded_bgr")
    @classmethod
    def valid_sha256(cls, value: str | None) -> str | None:
        if value is not None and re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise ValueError("sha256_decoded_bgr must be a lowercase SHA-256 hex digest")
        return value


class LabeledMinimapFrameSet(PersistentModel):
    """Reviewed labeled frames; duplicate sample IDs are rejected."""

    schema_version: Literal["1.0"] = "1.0"
    frames: list[LabeledMinimapFrame]

    @field_validator("frames")
    @classmethod
    def unique_sample_ids(cls, frames: list[LabeledMinimapFrame]) -> list[LabeledMinimapFrame]:
        ids = [frame.sample_id for frame in frames]
        if len(ids) != len(set(ids)):
            raise ValueError("sample_id values must be unique")
        return frames


@dataclass(frozen=True)
class FrameEvaluation:
    sample_id: str
    source_frame: int
    vod_timestamp_s: float
    true_positive: int
    false_positive: int
    false_negative: int
    matched_distances_px: tuple[float, ...]
    ignored_candidate_count: int = 0
    unmatched_candidate_centers: tuple[tuple[str, float, float], ...] = ()
    unmatched_label_centers: tuple[tuple[str, float, float], ...] = ()


@dataclass(frozen=True)
class MinimapColorEvaluation:
    frames: tuple[FrameEvaluation, ...]

    @property
    def true_positive(self) -> int:
        return sum(frame.true_positive for frame in self.frames)

    @property
    def false_positive(self) -> int:
        return sum(frame.false_positive for frame in self.frames)

    @property
    def false_negative(self) -> int:
        return sum(frame.false_negative for frame in self.frames)

    @property
    def precision(self) -> float | None:
        denominator = self.true_positive + self.false_positive
        return self.true_positive / denominator if denominator else None

    @property
    def recall(self) -> float | None:
        denominator = self.true_positive + self.false_negative
        return self.true_positive / denominator if denominator else None


def evaluate_labeled_frames(
    detector: MinimapColorCandidateDetector,
    dataset: LabeledMinimapFrameSet,
    images: dict[str, np.ndarray],
    *,
    match_tolerance_px: float,
) -> MinimapColorEvaluation:
    """Score accepted detections using maximum-cardinality one-to-one matching.

    Images are supplied by sample ID so callers can keep image loading and the
    reviewed fixture manifest separate. Missing images and dimension mismatches
    fail rather than silently dropping samples.
    """
    if not math.isfinite(match_tolerance_px) or match_tolerance_px < 0:
        raise ValueError("match_tolerance_px must be finite and non-negative")
    results: list[FrameEvaluation] = []
    for frame in dataset.frames:
        if frame.sample_id not in images:
            raise ValueError(f"missing image for sample_id {frame.sample_id!r}")
        image = images[frame.sample_id]
        if not isinstance(image, np.ndarray) or image.ndim != 3 or image.shape[2] != 3:
            raise ValueError(
                f"image must be a three-channel array for sample_id {frame.sample_id!r}"
            )
        if image.shape[:2] != (frame.height_px, frame.width_px):
            raise ValueError(f"image dimensions do not match sample_id {frame.sample_id!r}")
        if frame.sha256_decoded_bgr is not None:
            actual_hash = hashlib.sha256(np.ascontiguousarray(image).tobytes()).hexdigest()
            if actual_hash != frame.sha256_decoded_bgr:
                raise ValueError(f"decoded image hash does not match sample_id {frame.sample_id!r}")
        if any(
            region.bounds_px[2] >= frame.width_px or region.bounds_px[3] >= frame.height_px
            for region in frame.ignore_regions
        ):
            raise ValueError(
                f"ignore region exceeds image dimensions for sample_id {frame.sample_id!r}"
            )
        detection = detector.detect(
            image, vod_timestamp_s=frame.vod_timestamp_s, source_frame=frame.source_frame
        )
        candidates = [c for c in detection.candidates if c.accepted]
        all_points = [
            (c.crop_point.x * frame.width_px, c.crop_point.y * frame.height_px, c.broadcast_color)
            for c in candidates
        ]
        ignored = [
            _inside_ignore_region(x, y, frame.ignore_regions)
            for x, y, _ in all_points
        ]
        points = [point for point, is_ignored in zip(all_points, ignored) if not is_ignored]
        labels = [
            label
            for label in frame.reviewed_icons
            if not _inside_ignore_region(
                label.center_px[0], label.center_px[1], frame.ignore_regions
            )
        ]
        costs = []
        for px, py, color in points:
            costs.append(
                [
                    math.hypot(px - label.center_px[0], py - label.center_px[1])
                    if color == label.broadcast_color
                    else math.inf
                    for label in labels
                ]
            )
        matches = _maximum_cardinality_matches(costs, match_tolerance_px)
        distances = tuple(costs[candidate][label] for candidate, label in matches)
        matched_candidates = {candidate for candidate, _ in matches}
        matched_labels = {label for _, label in matches}
        tp = len(matches)
        results.append(
            FrameEvaluation(
                sample_id=frame.sample_id,
                source_frame=frame.source_frame,
                vod_timestamp_s=frame.vod_timestamp_s,
                true_positive=tp,
                false_positive=len(points) - tp,
                false_negative=len(labels) - tp,
                matched_distances_px=distances,
                ignored_candidate_count=sum(ignored),
                unmatched_candidate_centers=tuple(
                    (color, x, y) for index, (x, y, color) in enumerate(points)
                    if index not in matched_candidates
                ),
                unmatched_label_centers=tuple(
                    (label.broadcast_color, *label.center_px)
                    for index, label in enumerate(labels) if index not in matched_labels
                ),
            )
        )
    return MinimapColorEvaluation(tuple(results))


def _inside_ignore_region(
    x: float, y: float, regions: list[ReviewedIgnoreRegion]
) -> bool:
    return any(
        left <= x <= right and top <= y <= bottom
        for region in regions
        for left, top, right, bottom in [region.bounds_px]
    )


def _maximum_cardinality_matches(
    costs: list[list[float]], tolerance: float
) -> list[tuple[int, int]]:
    """Find one-to-one thresholded matches, preferring shorter distances."""
    if not costs or not costs[0]:
        return []
    # Augmenting paths avoid greedy assignment failures when neighborhoods overlap.
    label_to_candidate: dict[int, int] = {}

    def assign(candidate: int, seen: set[int]) -> bool:
        eligible = sorted(
            (distance, label)
            for label, distance in enumerate(costs[candidate])
            if distance <= tolerance
        )
        for _, label in eligible:
            if label in seen:
                continue
            seen.add(label)
            if label not in label_to_candidate or assign(label_to_candidate[label], seen):
                label_to_candidate[label] = candidate
                return True
        return False

    for candidate in range(len(costs)):
        assign(candidate, set())
    return [(candidate, label) for label, candidate in label_to_candidate.items()]
