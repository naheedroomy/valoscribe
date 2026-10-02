"""Reviewed VOD evidence for ability-cast identity, separate from smoke labels."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import Field, field_validator, model_validator

from valoscribe.types.persistent import PersistentModel


def _text_is_not_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("cast observation text must not be blank")
    return value


class CastObservationFrame(PersistentModel):
    """One source frame cited by an independently reviewed cast observation."""

    timestamp_s: float = Field(ge=0.0)
    frame_index: int = Field(ge=0)
    full_frame_bgr_sha256: str
    minimap_crop_bgr_sha256: str
    description: str = Field(min_length=1)

    @field_validator("description")
    @classmethod
    def description_is_not_blank(cls, value: str) -> str:
        return _text_is_not_blank(value)

    @field_validator("timestamp_s")
    @classmethod
    def timestamp_is_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("cast evidence timestamp must be finite")
        return value

    @field_validator("full_frame_bgr_sha256", "minimap_crop_bgr_sha256")
    @classmethod
    def digest_is_sha256(cls, value: str) -> str:
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError("cast evidence digest must be a lowercase SHA-256 hex digest")
        return value


class CastObservationEvent(PersistentModel):
    """A reviewed cast-related event and its source-time bracket."""

    event_id: str = Field(min_length=1)
    start_timestamp_s: float = Field(ge=0.0)
    end_timestamp_s: float = Field(ge=0.0)
    description: str = Field(min_length=1)
    evidence_frame_indices: list[int] = Field(min_length=1)

    @field_validator("event_id", "description")
    @classmethod
    def event_text_is_not_blank(cls, value: str) -> str:
        return _text_is_not_blank(value)

    @field_validator("start_timestamp_s", "end_timestamp_s")
    @classmethod
    def event_times_are_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("cast event timestamps must be finite")
        return value

    @model_validator(mode="after")
    def bracket_is_ordered(self) -> CastObservationEvent:
        if self.end_timestamp_s < self.start_timestamp_s:
            raise ValueError("cast event bracket must be ordered")
        return self


class UnresolvedSmokeFootprint(PersistentModel):
    """Separate negative-knowledge record; cast evidence is not deployment evidence."""

    status: Literal["unresolved"]
    center: None = None
    world_smoke_deployment: Literal["unknown"]
    smoke_lifecycle: Literal["unknown"]
    caster_to_footprint_correspondence: Literal["unknown"]
    minimap_correspondence: Literal["unknown"]


class ReviewedCastObservation(PersistentModel):
    """Hash-backed identity evidence; deliberately cannot represent smoke ground truth."""

    schema_version: Literal["1.0"] = "1.0"
    observation_id: str = Field(min_length=1)
    source_video_path: str = Field(min_length=1)
    source_video_filename: str = Field(min_length=1)
    source_video_sha256: str
    source_frame_dimensions_wh: tuple[int, int]
    nominal_fps: float = Field(gt=0.0)
    source_acquisition_manifest_path: str = Field(min_length=1)
    source_crop_rect_xywh: tuple[int, int, int, int]
    observation_kind: Literal["reviewed_cast_observation"]
    observed_player: str = Field(min_length=1)
    observed_agent: str = Field(min_length=1)
    observed_ability: str = Field(min_length=1)
    confidence: float = Field(gt=0.0, le=1.0)
    confidence_basis: str = Field(min_length=1)
    events: list[CastObservationEvent] = Field(min_length=1)
    evidence_frames: list[CastObservationFrame] = Field(min_length=1)
    smoke_footprint_observation: UnresolvedSmokeFootprint
    not_a_smoke_label: Literal[True]

    @field_validator(
        "observation_id",
        "source_video_path",
        "source_video_filename",
        "source_acquisition_manifest_path",
        "observed_player",
        "observed_agent",
        "observed_ability",
        "confidence_basis",
    )
    @classmethod
    def required_text_is_not_blank(cls, value: str) -> str:
        return _text_is_not_blank(value)

    @field_validator("source_video_sha256")
    @classmethod
    def source_digest_is_sha256(cls, value: str) -> str:
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError("source video digest must be a lowercase SHA-256 hex digest")
        return value

    @field_validator("nominal_fps", "confidence")
    @classmethod
    def numeric_values_are_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("cast observation numeric values must be finite")
        return value

    @model_validator(mode="after")
    def evidence_is_source_bound_and_complete(self) -> ReviewedCastObservation:
        width, height = self.source_frame_dimensions_wh
        if width <= 0 or height <= 0:
            raise ValueError("cast source frame dimensions must be positive")
        x, y, crop_width, crop_height = self.source_crop_rect_xywh
        if min(x, y) < 0 or min(crop_width, crop_height) <= 0:
            raise ValueError("cast source crop rectangle must be positive and in bounds")
        if x + crop_width > width or y + crop_height > height:
            raise ValueError("cast source crop exceeds frame dimensions")
        if self.source_video_filename != self.source_video_path.rsplit("/", 1)[-1]:
            raise ValueError("cast source filename must match source path")

        by_frame: dict[int, CastObservationFrame] = {}
        tolerance = 0.5 / self.nominal_fps + 1e-6
        for frame in self.evidence_frames:
            if frame.frame_index in by_frame:
                raise ValueError("cast evidence frame indices must be unique")
            if abs(frame.timestamp_s - frame.frame_index / self.nominal_fps) > tolerance:
                raise ValueError("cast evidence frame and timestamp disagree with nominal fps")
            by_frame[frame.frame_index] = frame

        event_ids = [event.event_id for event in self.events]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("cast event identifiers must be unique")
        for event in self.events:
            cited_frames = [by_frame.get(index) for index in event.evidence_frame_indices]
            if any(frame is None for frame in cited_frames):
                raise ValueError("cast event cites a missing evidence frame")
            if any(
                frame.timestamp_s < event.start_timestamp_s - tolerance
                or frame.timestamp_s > event.end_timestamp_s + tolerance
                for frame in cited_frames
                if frame is not None
            ):
                raise ValueError("cast event evidence falls outside its time bracket")
        return self
