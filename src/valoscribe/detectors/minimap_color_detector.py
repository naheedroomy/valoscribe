"""Configurable, side-agnostic broadcast-color candidates from minimap crops."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import cv2
import numpy as np
from numpy.typing import NDArray
from pydantic import Field, field_validator, model_validator

from valoscribe.types.persistent import (
    NormalizedBox,
    NormalizedPoint,
    PersistentModel,
    RawMinimapColorCandidate,
)

Image = NDArray[np.uint8]


class HSVRange(PersistentModel):
    """Inclusive OpenCV HSV bounds (H: 0–179, S/V: 0–255)."""

    schema_version: Literal["1.0"] = "1.0"
    lower: tuple[int, int, int]
    upper: tuple[int, int, int]

    @field_validator("lower", "upper")
    @classmethod
    def channels_are_in_range(cls, value: tuple[int, int, int]) -> tuple[int, int, int]:
        if len(value) != 3 or not (0 <= value[0] <= 179 and all(0 <= x <= 255 for x in value[1:])):
            raise ValueError("HSV bounds must use H 0..179 and S/V 0..255")
        return value

    @model_validator(mode="after")
    def bounds_are_ordered(self) -> HSVRange:
        if any(low > high for low, high in zip(self.lower, self.upper)):
            raise ValueError("HSV lower bounds must not exceed upper bounds")
        return self


class BroadcastColorMask(PersistentModel):
    """A configurable broadcast color label, not a team or side assignment."""

    schema_version: Literal["1.0"] = "1.0"
    color_id: str = Field(min_length=1)
    ranges: list[HSVRange] = Field(min_length=1)

    @field_validator("color_id")
    @classmethod
    def color_id_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("color_id must not be blank")
        return value


class MinimapColorProfile(PersistentModel):
    """Contour thresholds for one measured HUD/map crop profile."""

    schema_version: Literal["1.0"] = "1.0"
    profile_id: str = Field(min_length=1)
    colors: list[BroadcastColorMask] = Field(min_length=1)
    minimum_area_px: float = Field(gt=0.0)
    maximum_area_fraction: float = Field(gt=0.0, le=1.0)
    minimum_circularity: float = Field(ge=0.0, le=1.0)
    minimum_aspect_ratio: float = Field(gt=0.0, le=1.0)
    maximum_aspect_ratio: float = Field(gt=0.0, le=1.0, default=1.0)
    morphology_kernel_size: int = Field(default=3, ge=1)
    # Evaluation metadata is accepted for provenance; the detector does not use it.
    fit_split: str | None = None
    match_tolerance_px: float | None = Field(default=None, ge=0.0)

    @field_validator("profile_id")
    @classmethod
    def profile_id_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("profile_id must not be blank")
        return value

    @field_validator(
        "maximum_area_fraction",
        "minimum_area_px",
        "minimum_circularity",
        "minimum_aspect_ratio",
        "maximum_aspect_ratio",
    )
    @classmethod
    def thresholds_are_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("detector thresholds must be finite")
        return value

    @field_validator("fit_split")
    @classmethod
    def fit_split_is_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("fit_split must not be blank")
        return value

    @field_validator("match_tolerance_px")
    @classmethod
    def match_tolerance_is_finite(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("match_tolerance_px must be finite and non-negative")
        return value

    @model_validator(mode="after")
    def profile_is_coherent(self) -> MinimapColorProfile:
        if self.morphology_kernel_size % 2 == 0:
            raise ValueError("morphology_kernel_size must be odd")
        if self.maximum_aspect_ratio < self.minimum_aspect_ratio:
            raise ValueError("maximum aspect ratio must not be below minimum")
        ids = [color.color_id for color in self.colors]
        if len(ids) != len(set(ids)):
            raise ValueError("color IDs must be unique")
        return self


@dataclass(frozen=True)
class MinimapColorDetection:
    """Ranked raw candidates plus an RGB/BGR-compatible debug overlay."""

    candidates: tuple[RawMinimapColorCandidate, ...]
    debug_overlay: Image


class MinimapColorCandidateDetector:
    """Detect configurable HSV blobs without inferring team, side, or identity."""

    def __init__(self, profile: MinimapColorProfile) -> None:
        self.profile = profile

    def detect(
        self,
        minimap_crop: np.ndarray,
        *,
        vod_timestamp_s: float = 0.0,
        source_frame: int | None = None,
        excluded_background: np.ndarray | None = None,
    ) -> MinimapColorDetection:
        """Return candidates ranked by heuristic confidence and a rejection overlay.

        ``excluded_background`` is a binary mask where nonzero pixels are static
        background/obstruction and must not contribute to color contours.
        """
        _validate_input(minimap_crop, excluded_background)
        height, width = minimap_crop.shape[:2]
        hsv = cv2.cvtColor(minimap_crop, cv2.COLOR_BGR2HSV)
        kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (self.profile.morphology_kernel_size, self.profile.morphology_kernel_size),
        )
        overlay: np.ndarray = minimap_crop.copy()
        found: list[tuple[float, RawMinimapColorCandidate, tuple[int, int, int, int]]] = []
        max_area = height * width * self.profile.maximum_area_fraction

        for color in self.profile.colors:
            mask: np.ndarray = np.zeros((height, width), dtype=np.uint8)
            for hsv_range in color.ranges:
                mask = cv2.bitwise_or(
                    mask,
                    cv2.inRange(
                        hsv,
                        np.asarray(hsv_range.lower, dtype=np.uint8),
                        np.asarray(hsv_range.upper, dtype=np.uint8),
                    ),
                )
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
            if excluded_background is not None:
                mask[excluded_background > 0] = 0
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                area = float(cv2.contourArea(contour))
                if area <= 0.0:
                    continue
                x, y, box_width, box_height = cv2.boundingRect(contour)
                perimeter = float(cv2.arcLength(contour, True))
                circularity = 4.0 * math.pi * area / (perimeter * perimeter) if perimeter else 0.0
                aspect_ratio = min(box_width, box_height) / max(box_width, box_height)
                reasons: list[str] = []
                if area < self.profile.minimum_area_px:
                    reasons.append("area_below_minimum")
                if area > max_area:
                    reasons.append("area_above_maximum")
                if circularity < self.profile.minimum_circularity:
                    reasons.append("circularity_below_minimum")
                if aspect_ratio < self.profile.minimum_aspect_ratio:
                    reasons.append("aspect_ratio_out_of_range")
                if aspect_ratio > self.profile.maximum_aspect_ratio:
                    reasons.append("aspect_ratio_out_of_range")
                local_mask = mask[y : y + box_height, x : x + box_width]
                pixel_count = int(cv2.countNonZero(local_mask))
                fill_ratio = min(1.0, area / max(1, box_width * box_height))
                confidence = float(np.clip(0.65 * circularity + 0.35 * fill_ratio, 0.0, 1.0))
                box = (x, y, box_width, box_height)
                candidate = RawMinimapColorCandidate(
                    vod_timestamp_s=vod_timestamp_s,
                    source_frame=source_frame,
                    color_profile_id=self.profile.profile_id,
                    broadcast_color=color.color_id,
                    crop_point=NormalizedPoint(
                        x=(x + box_width / 2) / width,
                        y=(y + box_height / 2) / height,
                    ),
                    bounding_box=NormalizedBox(
                        x=x / width,
                        y=y / height,
                        width=box_width / width,
                        height=box_height / height,
                    ),
                    contour_area_px=area,
                    mask_pixel_count=pixel_count,
                    detector_confidence=confidence,
                    accepted=not reasons,
                    rejection_reasons=reasons,
                )
                found.append((confidence, candidate, box))

        found.sort(key=lambda item: item[0], reverse=True)
        for _, candidate, (x, y, box_width, box_height) in found:
            accepted = candidate.accepted
            draw_color = (0, 255, 0) if accepted else (0, 0, 255)
            cv2.rectangle(overlay, (x, y), (x + box_width - 1, y + box_height - 1), draw_color, 1)
            label = f"{candidate.broadcast_color}:{candidate.detector_confidence:.2f}"
            if not accepted:
                label += ":" + ",".join(candidate.rejection_reasons)
            cv2.putText(
                overlay,
                label,
                (x, max(10, y - 3)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.3,
                draw_color,
                1,
                cv2.LINE_AA,
            )
        return MinimapColorDetection(
            candidates=tuple(item[1] for item in found),
            debug_overlay=overlay,
        )


def _validate_input(crop: np.ndarray, excluded_background: np.ndarray | None) -> None:
    if not isinstance(crop, np.ndarray) or crop.dtype != np.uint8 or crop.ndim != 3:
        raise ValueError("minimap crop must be a uint8 BGR image")
    if crop.shape[0] < 3 or crop.shape[1] < 3 or crop.shape[2] != 3:
        raise ValueError("minimap crop must be a non-empty three-channel image")
    if excluded_background is not None:
        if (
            not isinstance(excluded_background, np.ndarray)
            or excluded_background.ndim != 2
            or excluded_background.shape != crop.shape[:2]
        ):
            raise ValueError("excluded background mask must match crop dimensions")
