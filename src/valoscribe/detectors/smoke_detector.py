"""Conservative HSV circular-smoke candidate extraction from registered minimaps."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from numpy.typing import NDArray

from valoscribe.maps.config import SmokeDetectionConfig
from valoscribe.types.persistent import (
    EvidenceRef,
    EvidenceSource,
    NormalizedPoint,
    SmokeCandidate,
    SmokeFrameObservation,
)

Image = NDArray[np.uint8]


@dataclass(frozen=True)
class SmokeDetectionResult:
    """Raw frame observation, candidates, and diagnostic overlay."""

    observation: SmokeFrameObservation
    candidates: list[SmokeCandidate]
    overlay: Image


def detect_smoke_candidates(
    registered_minimap: Image,
    valid_mask: Image,
    config: SmokeDetectionConfig | None,
    *,
    match_id: str,
    map_id: str,
    round_id: str,
    vod_timestamp_s: float,
    evidence: list[EvidenceRef],
    live_visible: bool,
) -> SmokeDetectionResult:
    """Detect color-configured circles; absence is never treated as verified clear.

    Both image registration and mask validity are caller responsibilities. Incomplete,
    hidden, malformed, or disabled inputs yield no candidates and cannot confirm clear.
    """
    valid = (
        config is not None
        and registered_minimap.ndim == 3
        and registered_minimap.shape[2] == 3
        and registered_minimap.dtype == np.uint8
        and valid_mask.shape == registered_minimap.shape[:2]
        and valid_mask.dtype == np.uint8
        and live_visible
        and bool(evidence)
    )
    overlay = (
        registered_minimap.copy()
        if registered_minimap.ndim >= 2
        else np.zeros((1, 1, 3), np.uint8)
    )
    candidates: list[SmokeCandidate] = []
    if valid:
        assert config is not None
        hsv = cv2.cvtColor(registered_minimap, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array(config.hsv_lower), np.array(config.hsv_upper))
        mask = cv2.bitwise_and(mask, valid_mask)
        count, labels, stats, centroids = cv2.connectedComponentsWithStats(
            mask, connectivity=8
        )
        height, width = mask.shape
        for label in range(1, count):
            area = int(stats[label, cv2.CC_STAT_AREA])
            radius_px = float(np.sqrt(area / np.pi))
            if not config.minimum_area_px <= area <= config.maximum_area_px:
                continue
            if not config.minimum_radius_px <= radius_px <= config.maximum_radius_px:
                continue
            component = (labels == label).astype(np.uint8)
            contours, _ = cv2.findContours(
                component, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            perimeter = cv2.arcLength(contours[0], True)
            circularity = float(4.0 * np.pi * area / (perimeter * perimeter)) if perimeter else 0.0
            if circularity < config.minimum_circularity:
                continue
            x, y = (float(value) for value in centroids[label])
            confidence = min(1.0, max(0.0, circularity))
            candidates.append(SmokeCandidate(
                match_id=match_id, map_id=map_id, round_id=round_id,
                vod_timestamp_s=vod_timestamp_s,
                center=NormalizedPoint(x=x / width, y=y / height),
                approximate_radius=radius_px / max(width, height),
                agent_type=None, source=EvidenceSource.MINIMAP,
                confidence=confidence, evidence=evidence, live_visible=True,
            ))
            cv2.circle(overlay, (round(x), round(y)), round(radius_px), (0, 255, 0), 1)
    observation = SmokeFrameObservation(
        match_id=match_id, map_id=map_id, round_id=round_id,
        vod_timestamp_s=vod_timestamp_s, evidence=evidence,
        live_visible=live_visible, active_region_clear=False, candidates=candidates,
    )
    return SmokeDetectionResult(observation=observation, candidates=candidates, overlay=overlay)
