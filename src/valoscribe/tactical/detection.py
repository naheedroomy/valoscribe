"""Source-configured, team-color candidate detector without identity tracking."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import cast

import cv2
import numpy as np

from valoscribe.tactical.config import DetectorConfig, HSVRange


@dataclass(frozen=True)
class MarkerCandidate:
    crop_x: float
    crop_y: float
    confidence: float
    flags: tuple[str, ...]


@dataclass(frozen=True)
class DetectionResult:
    markers: tuple[MarkerCandidate, ...]
    rejected_by_reason: dict[str, int]


def detect_markers(
    crop: np.ndarray,
    ranges: list[HSVRange],
    settings: DetectorConfig,
    map_mask: np.ndarray,
) -> DetectionResult:
    """Detect plausible compact color centers, returning zero or more candidates."""
    if crop.dtype != np.uint8 or crop.ndim != 3 or crop.shape[2] != 3:
        raise ValueError("crop must be an 8-bit BGR image")
    if map_mask.shape != crop.shape[:2]:
        raise ValueError("map mask must match crop dimensions")
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    color_mask = np.zeros(crop.shape[:2], dtype=np.uint8)
    for bounds in ranges:
        bound_mask = cv2.inRange(
            hsv,
            np.asarray(bounds.lower, dtype=np.uint8),
            np.asarray(bounds.upper, dtype=np.uint8),
        )
        color_mask = cast(np.ndarray, cv2.bitwise_or(color_mask, bound_mask))
    color_mask = cast(np.ndarray, cv2.bitwise_and(color_mask, map_mask))
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE,
        (settings.morphology_kernel_px, settings.morphology_kernel_px),
    )
    cleaned = cv2.morphologyEx(color_mask, cv2.MORPH_OPEN, kernel)
    contours, _ = cv2.findContours(cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    accepted: list[MarkerCandidate] = []
    rejected: Counter[str] = Counter()
    for contour in contours:
        area = float(cv2.contourArea(contour))
        x, y, width, height = cv2.boundingRect(contour)
        perimeter = float(cv2.arcLength(contour, True))
        circularity = 4.0 * math.pi * area / perimeter**2 if perimeter else 0.0
        aspect = min(width, height) / max(width, height)
        reason: str | None = None
        if area < settings.min_area_px:
            reason = "area_below_minimum"
        elif area > settings.max_area_px:
            reason = "area_above_maximum"
        elif aspect < settings.min_aspect_ratio:
            reason = "aspect_ratio_out_of_range"
        elif circularity < settings.min_circularity:
            reason = "circularity_below_minimum"
        confidence = float(np.clip(0.55 * min(circularity, 1.0) + 0.45 * aspect, 0, 1))
        if reason is None and confidence < settings.min_confidence:
            reason = "confidence_below_minimum"
        if reason:
            rejected[reason] += 1
            continue
        accepted.append(
            MarkerCandidate(
                crop_x=x + width / 2,
                crop_y=y + height / 2,
                confidence=confidence,
                flags=("source_color_candidate", "no_identity_assigned"),
            )
        )
    accepted.sort(key=lambda marker: (-marker.confidence, marker.crop_y, marker.crop_x))
    merged: list[MarkerCandidate] = []
    for marker in accepted:
        close_index = next(
            (
                index
                for index, kept in enumerate(merged)
                if math.hypot(marker.crop_x - kept.crop_x, marker.crop_y - kept.crop_y)
                <= settings.merge_distance_px
            ),
            None,
        )
        if close_index is None:
            merged.append(marker)
        elif marker.confidence > merged[close_index].confidence:
            merged[close_index] = marker
    return DetectionResult(tuple(merged), dict(rejected))


def crop_map_mask(
    canonical_mask: np.ndarray,
    affine_crop_to_map: list[list[float]],
    crop_width: int,
    crop_height: int,
) -> np.ndarray:
    """Project the canonical floorplan silhouette into raw minimap crop space."""
    if canonical_mask.ndim != 2 or crop_width <= 0 or crop_height <= 0:
        raise ValueError("invalid mask dimensions")
    matrix = np.asarray(affine_crop_to_map, dtype=np.float64)
    if matrix.shape != (2, 3) or abs(float(np.linalg.det(matrix[:, :2]))) < 1e-9:
        raise ValueError("crop-to-map affine must be invertible and 2x3")
    inverse = cv2.invertAffineTransform(matrix)
    result = cv2.warpAffine(
        canonical_mask,
        inverse,
        (crop_width, crop_height),
        flags=cv2.INTER_NEAREST,
        borderMode=cv2.BORDER_CONSTANT,
    )
    return cast(
        np.ndarray,
        cv2.morphologyEx(result, cv2.MORPH_DILATE, np.ones((3, 3), np.uint8)),
    )
