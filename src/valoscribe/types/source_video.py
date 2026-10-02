"""Immutable metadata contracts for sequential source-time video decoding."""

from __future__ import annotations

from fractions import Fraction
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SourceVideoMetadata(BaseModel):
    """Source stream inventory, kept separate from container-level duration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_path: str = Field(min_length=1)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    time_base_numerator: int = Field(gt=0)
    time_base_denominator: int = Field(gt=0)
    fps_numerator: int = Field(gt=0)
    fps_denominator: int = Field(gt=0)
    stream_duration_seconds: Fraction | None = None
    container_duration_seconds: Fraction | None = None
    frame_count: int = Field(gt=0)
    timestamp_kind: Literal["pts", "best_effort_timestamp"]
    ffprobe_version: str = Field(min_length=1)
    ffmpeg_version: str = Field(min_length=1)
    file_size: int = Field(ge=0)
    file_mtime_ns: int = Field(ge=0)

    @field_validator("stream_duration_seconds", "container_duration_seconds", mode="before")
    @classmethod
    def parse_duration(cls, value: object) -> Fraction | None:
        if value is None:
            return None
        if isinstance(value, Fraction):
            return value
        return Fraction(str(value))


class SourceVideoFrame(BaseModel):
    """One BGR frame with decode-order identity and observed source clock."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid", frozen=True)

    frame_index: int = Field(ge=0)
    source_pts: int
    time_base_numerator: int = Field(gt=0)
    time_base_denominator: int = Field(gt=0)
    timestamp_seconds: Fraction
    timestamp_kind: Literal["pts", "best_effort_timestamp"]
    bgr: np.ndarray

    @model_validator(mode="after")
    def validate_frame_clock_and_pixels(self) -> SourceVideoFrame:
        expected = Fraction(self.source_pts * self.time_base_numerator, self.time_base_denominator)
        if self.timestamp_seconds != expected:
            raise ValueError("timestamp_seconds disagrees with source PTS/timebase")
        if self.bgr.dtype != np.uint8 or self.bgr.ndim != 3 or self.bgr.shape[2] != 3:
            raise ValueError("bgr must be a uint8 HxWx3 array")
        return self

    def validate_against(self, metadata: SourceVideoMetadata) -> SourceVideoFrame:
        """Revalidate both contracts and their cross-model frame bounds."""
        validated_metadata = SourceVideoMetadata.model_validate(metadata.model_dump())
        validated_frame = SourceVideoFrame.model_validate(self.model_dump())
        if not 0 <= validated_frame.frame_index < validated_metadata.frame_count:
            raise ValueError("frame_index is outside the source inventory")
        metadata = validated_metadata
        if (
            validated_frame.bgr.shape != (metadata.height, metadata.width, 3)
            or validated_frame.bgr.dtype != np.uint8
        ):
            raise ValueError("frame pixels do not match source metadata")
        if (validated_frame.time_base_numerator, validated_frame.time_base_denominator) != (
            metadata.time_base_numerator,
            metadata.time_base_denominator,
        ):
            raise ValueError("frame timebase does not match source metadata")
        if validated_frame.timestamp_kind != metadata.timestamp_kind:
            raise ValueError("frame timestamp provenance does not match source metadata")
        return self
