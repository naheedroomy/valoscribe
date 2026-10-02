"""Frozen whole-crop structural rim hypotheses for offline VTA-304 diagnosis."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass

import cv2
import numpy as np
from pydantic import Field

from valoscribe.types.persistent import PersistentModel


class RimHypothesis(PersistentModel):
    """Uncalibrated geometric enclosure; never a semantic portrait detection."""

    center_x: float
    center_y: float
    boundary_xywh: tuple[int, int, int, int]
    circularity: float = Field(ge=0.0, le=1.1)
    status: str
    reasons: list[str]
    radius_px: float | None = None
    radial_support: float | None = None
    annular_contrast: float | None = None
    normalized_score: float | None = None
    policy_sha256: str | None = None
    identity: str = "unknown"
    side: str = "unknown"


@dataclass(frozen=True)
class LocalizationResult:
    hypotheses: tuple[RimHypothesis, ...]
    edge_map: np.ndarray
    overlay: np.ndarray


# Fixed before fixture scoring: grayscale Canny + 3px close; 14–28px contours,
# aspect 0.62–1.6, circularity >= 0.45. Values are development-only, not calibrated.
def localize_rim_hypotheses(image_bgr: np.ndarray) -> LocalizationResult:
    """Return every compact contour-based rim hypothesis without color seeding/NMS."""
    if not isinstance(image_bgr, np.ndarray) or image_bgr.dtype != np.uint8:
        raise ValueError("image_bgr must be a uint8 image")
    if image_bgr.ndim != 3 or image_bgr.shape[2] != 3:
        raise ValueError("image_bgr must have three BGR channels")
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 35, 105)
    closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(closed, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    height, width = gray.shape
    hypotheses: list[RimHypothesis] = []
    overlay = image_bgr.copy()
    for contour in contours:
        x, y, box_w, box_h = cv2.boundingRect(contour)
        if not (14 <= box_w <= 28 and 14 <= box_h <= 28):
            continue
        aspect = box_w / box_h
        perimeter = cv2.arcLength(contour, True)
        area = cv2.contourArea(contour)
        circularity = float(4 * np.pi * area / (perimeter * perimeter)) if perimeter else 0.0
        if not (0.62 <= aspect <= 1.6 and circularity >= 0.45):
            continue
        moments = cv2.moments(contour)
        if moments["m00"]:
            cx = moments["m10"] / moments["m00"]
            cy = moments["m01"] / moments["m00"]
        else:
            cx, cy = x + (box_w - 1) / 2, y + (box_h - 1) / 2
        clipped = x <= 0 or y <= 0 or x + box_w >= width or y + box_h >= height
        hypotheses.append(
            RimHypothesis(
                center_x=float(cx),
                center_y=float(cy),
                boundary_xywh=(x, y, box_w, box_h),
                circularity=min(circularity, 1.1),
                status="clipped" if clipped else "structural_hypothesis",
                reasons=[
                    "compact_closed_edge_enclosure",
                    *(["touches_image_boundary"] if clipped else []),
                ],
            )
        )
        cv2.rectangle(overlay, (x, y), (x + box_w - 1, y + box_h - 1), (0, 180, 255), 1)
        cv2.circle(overlay, (int(round(cx)), int(round(cy))), 2, (255, 0, 255), -1)
    hypotheses.sort(
        key=lambda h: (
            h.boundary_xywh[1],
            h.boundary_xywh[0],
            h.boundary_xywh[2],
            h.boundary_xywh[3],
        )
    )
    competing: set[int] = set()
    for i, left in enumerate(hypotheses):
        lx, ly, lw, lh = left.boundary_xywh
        for j in range(i + 1, len(hypotheses)):
            rx, ry, rw, rh = hypotheses[j].boundary_xywh
            intersection = max(0, min(lx + lw, rx + rw) - max(lx, rx)) * max(
                0, min(ly + lh, ry + rh) - max(ly, ry)
            )
            if intersection:
                competing.update((i, j))
    for index in competing:
        item = hypotheses[index]
        hypotheses[index] = item.model_copy(
            update={
                "status": "competing",
                "reasons": [*item.reasons, "overlapping_structural_hypothesis"],
            }
        )
    return LocalizationResult(tuple(hypotheses), closed, overlay)


RADII_PX = tuple(range(5, 11))
GRADIENT_MAGNITUDE_MIN = 90.0
GRADIENT_VOTE_WEIGHT_MAX = 1020.0
MINIMUM_RADIAL_SUPPORT_FRACTION = 0.55
MINIMUM_ANNULAR_CONTRAST_GRAY = 16.0
MINIMUM_NORMALIZED_SCORE = 0.20
NEAR_IDENTICAL_PEAK_COLLAPSE_PX = 4.0
ANNULAR_SAMPLE_COUNT = 32
MINIMUM_RADIAL_ALIGNMENT_ABS_COSINE = 0.65

RADIAL_POLICY = {
    "method": "grayscale_sobel_paired_radial_gradient_votes",
    "radii_px": list(RADII_PX),
    "gradient_magnitude_min": GRADIENT_MAGNITUDE_MIN,
    "gradient_vote_weight_max": GRADIENT_VOTE_WEIGHT_MAX,
    "peak_neighborhood_px": 3,
    "minimum_radial_support_fraction": MINIMUM_RADIAL_SUPPORT_FRACTION,
    "minimum_annular_contrast_gray": MINIMUM_ANNULAR_CONTRAST_GRAY,
    "minimum_normalized_score": MINIMUM_NORMALIZED_SCORE,
    "near_identical_peak_collapse_px": NEAR_IDENTICAL_PEAK_COLLAPSE_PX,
    "annular_sample_count": ANNULAR_SAMPLE_COUNT,
    "minimum_radial_alignment_abs_cosine": MINIMUM_RADIAL_ALIGNMENT_ABS_COSINE,
}
RADIAL_POLICY_SHA256 = hashlib.sha256(
    json.dumps(RADIAL_POLICY, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()


def localize_radial_rims(image_bgr: np.ndarray) -> LocalizationResult:
    """Vote for whole-crop circle centers from paired grayscale Sobel gradients.

    Scores describe geometric rim support only; they are not semantic confidence.
    """
    if not isinstance(image_bgr, np.ndarray) or image_bgr.dtype != np.uint8:
        raise ValueError("image_bgr must be a uint8 image")
    if image_bgr.ndim != 3 or image_bgr.shape[2] != 3:
        raise ValueError("image_bgr must have three BGR channels")
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    gray_float = gray.astype(np.float32)
    gx = cv2.Sobel(gray_float, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray_float, cv2.CV_32F, 0, 1, ksize=3)
    magnitude = cv2.magnitude(gx, gy)
    strong = magnitude >= GRADIENT_MAGNITUDE_MIN
    ys, xs = np.nonzero(strong)
    if not len(xs):
        return LocalizationResult((), np.zeros_like(gray), image_bgr.copy())
    unit_x = gx[ys, xs] / magnitude[ys, xs]
    unit_y = gy[ys, xs] / magnitude[ys, xs]
    weights = np.minimum(magnitude[ys, xs] / GRADIENT_VOTE_WEIGHT_MAX, 1.0)
    height, width = gray.shape
    candidates: list[tuple[float, float, int, float, float, float]] = []
    response = np.zeros((height, width), dtype=np.float32)
    angles = np.arange(ANNULAR_SAMPLE_COUNT) * (2.0 * np.pi / ANNULAR_SAMPLE_COUNT)
    cosines, sines = np.cos(angles), np.sin(angles)
    for radius in RADII_PX:
        accumulator = np.zeros((height, width), dtype=np.float32)
        for sign in (-1.0, 1.0):
            vote_x = np.rint(xs - sign * radius * unit_x).astype(np.int32)
            vote_y = np.rint(ys - sign * radius * unit_y).astype(np.int32)
            valid = (vote_x >= 0) & (vote_x < width) & (vote_y >= 0) & (vote_y < height)
            np.add.at(accumulator, (vote_y[valid], vote_x[valid]), weights[valid])
        response = np.maximum(response, accumulator)
        local_max = cv2.dilate(accumulator, np.ones((3, 3), np.uint8))
        peak_y, peak_x = np.nonzero((accumulator >= local_max - 1e-6) & (accumulator > 0))
        order = sorted(
            zip(peak_y.tolist(), peak_x.tolist()), key=lambda point: (-accumulator[point], point)
        )
        for cy, cx in order:
            ring_x = np.rint(cx + radius * cosines).astype(np.int32)
            ring_y = np.rint(cy + radius * sines).astype(np.int32)
            inner_x = np.rint(cx + radius * 0.45 * cosines).astype(np.int32)
            inner_y = np.rint(cy + radius * 0.45 * sines).astype(np.int32)
            valid = (ring_x >= 1) & (ring_x < width - 1) & (ring_y >= 1) & (ring_y < height - 1)
            if int(np.count_nonzero(valid)) < ANNULAR_SAMPLE_COUNT * 0.4:
                continue
            sampled_gx = gx[ring_y[valid], ring_x[valid]]
            sampled_gy = gy[ring_y[valid], ring_x[valid]]
            sampled_mag = magnitude[ring_y[valid], ring_x[valid]]
            radial_x = (ring_x[valid] - cx) / radius
            radial_y = (ring_y[valid] - cy) / radius
            alignment = np.abs(sampled_gx * radial_x + sampled_gy * radial_y) / np.maximum(
                sampled_mag, 1e-6
            )
            support_fraction = float(
                np.mean(
                    (sampled_mag >= GRADIENT_MAGNITUDE_MIN)
                    & (alignment >= MINIMUM_RADIAL_ALIGNMENT_ABS_COSINE)
                )
            )
            annular_mean = float(np.mean(gray[ring_y[valid], ring_x[valid]]))
            inner_valid = (inner_x >= 0) & (inner_x < width) & (inner_y >= 0) & (inner_y < height)
            inner_mean = float(np.mean(gray[inner_y[inner_valid], inner_x[inner_valid]]))
            contrast = abs(annular_mean - inner_mean)
            score = support_fraction * min(contrast / 64.0, 1.0)
            if (
                support_fraction < MINIMUM_RADIAL_SUPPORT_FRACTION
                or contrast < MINIMUM_ANNULAR_CONTRAST_GRAY
                or score < MINIMUM_NORMALIZED_SCORE
            ):
                continue
            candidates.append(
                (float(cx), float(cy), radius, float(accumulator[cy, cx]), contrast, score)
            )
    candidates.sort(key=lambda item: (-item[5], -item[3], item[1], item[0], item[2]))
    collapsed: list[tuple[float, float, int, float, float, float]] = []
    for candidate in candidates:
        if not any(
            math.hypot(candidate[0] - prior[0], candidate[1] - prior[1])
            <= NEAR_IDENTICAL_PEAK_COLLAPSE_PX
            for prior in collapsed
        ):
            collapsed.append(candidate)
    hypotheses: list[RimHypothesis] = []
    for cx, cy, radius, support, contrast, score in collapsed:
        clipped = (
            cx - radius < 0 or cy - radius < 0 or cx + radius >= width or cy + radius >= height
        )
        hypotheses.append(
            RimHypothesis(
                center_x=cx,
                center_y=cy,
                boundary_xywh=(round(cx - radius), round(cy - radius), 2 * radius, 2 * radius),
                circularity=1.0,
                status="clipped" if clipped else "structural_hypothesis",
                reasons=[
                    "paired_radial_gradient_rim_support",
                    *(["rim_intersects_crop_boundary"] if clipped else []),
                ],
                radius_px=float(radius),
                radial_support=support,
                annular_contrast=contrast,
                normalized_score=score,
                policy_sha256=RADIAL_POLICY_SHA256,
            )
        )
    for i, left in enumerate(hypotheses):
        left_radius = left.radius_px
        if left_radius is None:
            raise RuntimeError("radial hypothesis must retain its radius")
        for j in range(i + 1, len(hypotheses)):
            right = hypotheses[j]
            right_radius = right.radius_px
            if right_radius is None:
                raise RuntimeError("radial hypothesis must retain its radius")
            distance = math.hypot(left.center_x - right.center_x, left.center_y - right.center_y)
            if distance > NEAR_IDENTICAL_PEAK_COLLAPSE_PX and distance < left_radius + right_radius:
                for index in (i, j):
                    item = hypotheses[index]
                    if item.status != "clipped":
                        hypotheses[index] = item.model_copy(
                            update={
                                "status": "competing",
                                "reasons": [*item.reasons, "intersecting_rim_hypothesis"],
                            }
                        )
    overlay = image_bgr.copy()
    for item in hypotheses:
        if item.radius_px is None:
            raise RuntimeError("radial hypothesis must retain its radius")
        cv2.circle(
            overlay,
            (round(item.center_x), round(item.center_y)),
            round(item.radius_px),
            (0, 180, 255),
            1,
        )
        cv2.circle(overlay, (round(item.center_x), round(item.center_y)), 2, (255, 0, 255), -1)
    normalized_response = np.empty_like(response)
    cv2.normalize(response, normalized_response, 0, 255, cv2.NORM_MINMAX)
    return LocalizationResult(tuple(hypotheses), normalized_response.astype(np.uint8), overlay)
