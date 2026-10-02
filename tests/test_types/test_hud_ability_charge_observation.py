"""Tests for evidence-only HUD ability indicator observation contracts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from valoscribe.analytics.smoke_source_observation import decoded_crop_sha256
from valoscribe.types.hud_charge_observation import (
    HudAbilityChargeObservation,
    HudAbilityCrop,
)
from valoscribe.types.smoke_source_observation import SmokeSourceCrop

MANIFEST_PATH = (
    Path(__file__).parents[2]
    / "tests"
    / "fixtures"
    / "hud_ability_charge_observation_vta503.json"
)


def test_vta503_manifest_validates_as_evidence_only_observation() -> None:
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    observation = HudAbilityChargeObservation.model_validate(data)

    assert observation.schema_version == "1.0"
    assert observation.remaining_charge_count is None
    assert observation.unique_caster_attribution == "pending"
    assert [sample.frame_index for sample in observation.samples] == [
        149280,
        149340,
        149400,
        150300,
        150360,
    ]
    assert observation.samples[0].indicator_state == "bright_pip"
    assert observation.samples[1].indicator_state == "dim_pip"


def test_hud_sample_rejects_invalid_decoded_roi_hash() -> None:
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    data["samples"][0]["decoded_crop_sha256"] = "not-a-sha256"

    with pytest.raises(ValidationError, match="lowercase SHA-256"):
        HudAbilityChargeObservation.model_validate(data)


def test_hud_transition_rejects_missing_dim_state() -> None:
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    for sample in data["samples"]:
        sample["indicator_state"] = "bright_pip"

    with pytest.raises(ValidationError, match="requires reviewed bright and dim"):
        HudAbilityChargeObservation.model_validate(data)


def test_hud_transition_rejects_out_of_order_samples() -> None:
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    data["samples"][1]["timestamp_s"] = data["samples"][0]["timestamp_s"]

    with pytest.raises(ValidationError, match="strictly timestamp ordered"):
        HudAbilityChargeObservation.model_validate(data)


def test_decoded_roi_hash_uses_original_crop_bytes_and_rejects_out_of_bounds() -> None:
    frame = np.arange(8 * 9 * 3, dtype=np.uint8).reshape((8, 9, 3))
    crop = SmokeSourceCrop(x=2, y=1, width=3, height=4)

    assert decoded_crop_sha256(frame, crop) == hashlib.sha256(
        np.ascontiguousarray(frame[1:5, 2:5]).tobytes()
    ).hexdigest()
    with pytest.raises(ValueError, match="exceeds decoded frame dimensions"):
        decoded_crop_sha256(frame, SmokeSourceCrop(x=8, y=7, width=2, height=2))


def test_hud_crop_contract_rejects_negative_coordinates() -> None:
    with pytest.raises(ValidationError):
        HudAbilityCrop(x=-1, y=0, width=10, height=10)
