"""Optional, non-persistent labeled registration evaluation inputs."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PixelPoint(BaseModel):
    """Image-pixel coordinate with a top-left origin."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    x: float = Field(ge=0.0)
    y: float = Field(ge=0.0)

    @field_validator("x", "y")
    @classmethod
    def finite_coordinate(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("landmark coordinates must be finite")
        return value


class RegistrationLandmark(BaseModel):
    """One reviewed point pair from original crop to canonical image."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    landmark_id: str = Field(min_length=1)
    source_crop_point: PixelPoint
    canonical_point: PixelPoint

    @field_validator("landmark_id")
    @classmethod
    def identifier_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("landmark_id must not be blank")
        return value


class RegistrationLandmarkLabels(BaseModel):
    """Opt-in reviewed labels and provenance; this contract is not persisted."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    provenance: str = Field(min_length=1)
    source_frame_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    canonical_asset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    landmarks: list[RegistrationLandmark] = Field(min_length=1)

    @field_validator("provenance")
    @classmethod
    def provenance_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("landmark provenance must not be blank")
        return value

    @model_validator(mode="after")
    def identifiers_are_unique(self) -> RegistrationLandmarkLabels:
        ids = [landmark.landmark_id for landmark in self.landmarks]
        if len(ids) != len(set(ids)):
            raise ValueError("landmark IDs must be unique")
        return self


def decoded_image_sha256(image: np.ndarray) -> str:
    """Hash an image's decoded pixel data with its shape as an ASCII JSON prefix."""
    shape_prefix = json.dumps(list(image.shape), separators=(",", ":")).encode("ascii")
    digest = hashlib.sha256()
    digest.update(shape_prefix + b"\0")
    digest.update(np.ascontiguousarray(image).tobytes())
    return digest.hexdigest()


def evaluate_registration_landmarks(
    labels: RegistrationLandmarkLabels,
    transform_matrix: tuple[tuple[float, float, float], tuple[float, float, float]],
    source_shape: tuple[int, ...],
    canonical_shape: tuple[int, ...],
    maximum_error_px: float | None = None,
) -> dict[str, Any]:
    """Measure reprojection errors and compare them to an independent configured limit."""
    if maximum_error_px is not None and (
        not math.isfinite(maximum_error_px) or maximum_error_px <= 0.0
    ):
        raise ValueError("landmark acceptance threshold must be finite and positive")
    source_height, source_width = source_shape[:2]
    canonical_height, canonical_width = canonical_shape[:2]
    matrix = np.asarray(transform_matrix, dtype=np.float64)
    if matrix.shape != (2, 3) or not np.isfinite(matrix).all():
        raise ValueError("landmark evaluation requires a finite 2x3 transform")

    errors: list[dict[str, Any]] = []
    distances: list[float] = []
    for landmark in labels.landmarks:
        source = landmark.source_crop_point
        expected = landmark.canonical_point
        if source.x >= source_width or source.y >= source_height:
            raise ValueError(f"landmark_source_out_of_bounds:{landmark.landmark_id}")
        if expected.x >= canonical_width or expected.y >= canonical_height:
            raise ValueError(f"landmark_canonical_out_of_bounds:{landmark.landmark_id}")
        predicted = matrix @ np.array([source.x, source.y, 1.0])
        error = float(np.linalg.norm(predicted - [expected.x, expected.y]))
        if not math.isfinite(error):
            raise ValueError(f"landmark_error_non_finite:{landmark.landmark_id}")
        distances.append(error)
        errors.append({"landmark_id": landmark.landmark_id, "error_px": error})
    return {
        "provenance": labels.provenance,
        "point_count": len(distances),
        "per_point_errors": errors,
        "mean_error_px": float(np.mean(distances)),
        "rms_error_px": float(np.sqrt(np.mean(np.square(distances)))),
        "maximum_error_px": max(distances),
        "maximum_error_threshold_px": maximum_error_px,
        "acceptance_threshold_configured": maximum_error_px is not None,
        "passed": maximum_error_px is not None and max(distances) <= maximum_error_px,
    }
