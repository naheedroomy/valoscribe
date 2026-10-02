"""Versioned source-HUD evidence for reviewed ability-indicator transitions."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import Field, field_validator, model_validator

from valoscribe.types.persistent import PersistentModel


class HudAbilityCrop(PersistentModel):
    """Original-frame HUD region in decoded-video pixel coordinates."""

    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class HudAbilitySample(PersistentModel):
    """One visually reviewed indicator state; not a numeric charge count."""

    timestamp_s: float = Field(ge=0.0)
    frame_index: int = Field(ge=0)
    indicator_state: Literal["bright_pip", "dim_pip", "uncertain"]
    decoded_crop_sha256: str
    confidence: float = Field(gt=0.0, le=1.0)
    review_status: Literal["independently_reviewed"]
    review_note: str = Field(min_length=1)

    @field_validator("timestamp_s", "confidence")
    @classmethod
    def numeric_values_are_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("HUD sample numeric values must be finite")
        return value

    @field_validator("decoded_crop_sha256")
    @classmethod
    def digest_is_sha256(cls, value: str) -> str:
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError("decoded crop digest must be a lowercase SHA-256 hex digest")
        return value


class HudAbilityChargeObservation(PersistentModel):
    """Evidence-only HUD state transition; attribution and charge count stay unknown."""

    schema_version: Literal["1.0"] = "1.0"
    source_filename: str = Field(min_length=1)
    source_frame_width: int = Field(gt=0)
    source_frame_height: int = Field(gt=0)
    nominal_fps: float = Field(gt=0.0)
    crop: HudAbilityCrop
    player_label: str = Field(min_length=1)
    observed_agent_label: str = Field(min_length=1)
    observed_ability_label: str = Field(min_length=1)
    transition_bracket_start_s: float = Field(ge=0.0)
    transition_bracket_end_s: float = Field(ge=0.0)
    interpretation: Literal["available_to_unavailable_or_recharging"]
    remaining_charge_count: None = None
    unique_caster_attribution: Literal["pending"] = "pending"
    canonical_registration_status: Literal["pending"] = "pending"
    confidence: float = Field(gt=0.0, le=1.0)
    confidence_basis: str = Field(min_length=1)
    smoke_source_observation: str = Field(min_length=1)
    samples: list[HudAbilitySample] = Field(min_length=2)

    @field_validator(
        "nominal_fps", "transition_bracket_start_s", "transition_bracket_end_s", "confidence"
    )
    @classmethod
    def numeric_values_are_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("HUD observation numeric values must be finite")
        return value

    @model_validator(mode="after")
    def validate_bounds_transition_and_order(self) -> HudAbilityChargeObservation:
        if self.crop.x + self.crop.width > self.source_frame_width:
            raise ValueError("HUD crop exceeds frame width")
        if self.crop.y + self.crop.height > self.source_frame_height:
            raise ValueError("HUD crop exceeds frame height")
        if self.transition_bracket_end_s <= self.transition_bracket_start_s:
            raise ValueError("HUD transition bracket must be ordered")
        if any(a.timestamp_s >= b.timestamp_s for a, b in zip(self.samples, self.samples[1:])):
            raise ValueError("HUD samples must be strictly timestamp ordered")
        has_bright = any(sample.indicator_state == "bright_pip" for sample in self.samples)
        has_dim = any(sample.indicator_state == "dim_pip" for sample in self.samples)
        if not (has_bright and has_dim):
            raise ValueError("HUD transition requires reviewed bright and dim pip samples")
        if not (
            self.transition_bracket_start_s
            <= self.samples[0].timestamp_s
            < self.transition_bracket_end_s
        ):
            raise ValueError("HUD transition bracket does not contain transition samples")
        return self
