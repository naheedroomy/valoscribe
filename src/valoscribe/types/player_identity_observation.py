"""Versioned human labels linking a roster identity to a minimap icon."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import Field, field_validator, model_validator

from valoscribe.types.persistent import PersistentModel


class PlayerIdentityCrop(PersistentModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class PlayerIdentitySample(PersistentModel):
    timestamp_s: float = Field(ge=0.0)
    frame_index: int = Field(ge=0)
    icon_center_crop_px: tuple[int, int] | None = None
    visibility: Literal["visible", "not_visible", "uncertain"]
    uncertainty_note: str | None = None
    decoded_frame_sha256: str
    decoded_crop_sha256: str

    @field_validator("timestamp_s")
    @classmethod
    def timestamp_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("identity sample timestamp must be finite")
        return value

    @field_validator("decoded_frame_sha256", "decoded_crop_sha256")
    @classmethod
    def digest_is_sha256(cls, value: str) -> str:
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError("decoded frame and crop digests must be lowercase SHA-256 hex")
        return value

    @model_validator(mode="after")
    def validate_visibility_evidence(self) -> PlayerIdentitySample:
        if self.visibility == "visible" and self.icon_center_crop_px is None:
            raise ValueError("visible icons require an icon center")
        if self.visibility == "not_visible" and self.icon_center_crop_px is not None:
            raise ValueError("not-visible icons cannot have an icon center")
        if self.visibility == "uncertain" and not self.uncertainty_note:
            raise ValueError("uncertain visibility requires an uncertainty note")
        return self


class PlayerIdentityLabel(PersistentModel):
    team_id: str = Field(min_length=1)
    player_id: str = Field(min_length=1)
    agent: str = Field(min_length=1)
    alive: bool
    roster_evidence: str = Field(min_length=1)
    icon_link_evidence: str = Field(min_length=1)

    @field_validator("team_id", "player_id", "agent", "roster_evidence", "icon_link_evidence")
    @classmethod
    def text_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("identity label text cannot be blank")
        return value


class PlayerIdentityObservation(PersistentModel):
    """Raw reviewed source evidence, separate from tracker predictions."""

    schema_version: Literal["1.0"] = "1.0"
    source_filename: str = Field(min_length=1)
    source_frame_width: int = Field(gt=0)
    source_frame_height: int = Field(gt=0)
    nominal_fps: float = Field(gt=0.0)
    crop: PlayerIdentityCrop
    round_id: str = Field(min_length=1)
    label: PlayerIdentityLabel
    samples: list[PlayerIdentitySample] = Field(min_length=1)

    @field_validator("nominal_fps")
    @classmethod
    def fps_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("nominal frame rate must be finite")
        return value

    @model_validator(mode="after")
    def validate_bounds_and_sample_labels(self) -> PlayerIdentityObservation:
        if self.crop.x + self.crop.width > self.source_frame_width:
            raise ValueError("identity crop exceeds frame width")
        if self.crop.y + self.crop.height > self.source_frame_height:
            raise ValueError("identity crop exceeds frame height")
        previous_frame = -1
        for sample in self.samples:
            if sample.frame_index <= previous_frame:
                raise ValueError("identity samples must be ordered by distinct frame index")
            previous_frame = sample.frame_index
            if sample.icon_center_crop_px is not None:
                x, y = sample.icon_center_crop_px
                if not (0 <= x < self.crop.width and 0 <= y < self.crop.height):
                    raise ValueError("icon center must be inside the source crop")
        return self
