import json
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pytest
from pydantic import ValidationError

from valoscribe.analytics.player_identity_observation import (
    decoded_frame_sha256,
    decoded_identity_crop_sha256,
    verify_identity_observation,
)
from valoscribe.types.player_identity_observation import (
    PlayerIdentityCrop,
    PlayerIdentityObservation,
)


def observation_data() -> dict[str, object]:
    return {
        "source_filename": "vod.mp4",
        "source_frame_width": 8,
        "source_frame_height": 6,
        "nominal_fps": 60,
        "crop": {"x": 1, "y": 1, "width": 4, "height": 3},
        "round_id": "round-4",
        "label": {
            "team_id": "100T",
            "player_id": "bang",
            "agent": "Omen",
            "alive": True,
            "roster_evidence": (
                "HUD identifies alive 100T bang as Omen and greyed/dead LOUD Erde as Omen"
            ),
            "icon_link_evidence": (
                "HUD alive contrast and reviewer-observed movement support bang; "
                "Omen alone is ambiguous"
            ),
        },
        "samples": [
            {
                "timestamp_s": 300,
                "frame_index": 18000,
                "icon_center_crop_px": [2, 2],
                "visibility": "visible",
                "decoded_frame_sha256": "a" * 64,
                "decoded_crop_sha256": "b" * 64,
            }
        ],
    }


def test_vta304_fixture_records_bang_and_uncertain_unlocalized_frames():
    fixture_path = (
        Path(__file__).parents[2] / "tests/fixtures/player_identity_observation_vta304_round4.json"
    )
    observation = PlayerIdentityObservation.model_validate_json(fixture_path.read_text())

    assert (observation.label.team_id, observation.label.player_id) == ("100T", "bang")
    assert observation.label.agent == "Omen"
    assert observation.label.alive is True
    uncertain = {
        sample.frame_index: sample
        for sample in observation.samples
        if sample.visibility == "uncertain"
    }
    assert set(uncertain) == {18001, 18002, 18180}
    assert all(sample.icon_center_crop_px is None for sample in uncertain.values())
    assert all(sample.uncertainty_note for sample in uncertain.values())


def test_vta304_pts_v2_fixture_is_bound_to_six_reviewed_source_rasters():
    root = Path(__file__).parents[2]
    fixture = PlayerIdentityObservation.model_validate_json(
        (root / "tests/fixtures/player_identity_observation_vta304_round4_pts_v2.json").read_text()
    )
    review_path = (
        root / "tests/fixtures/player_identity_observation_vta304_round4_pts_v2_review.json"
    )
    review = json.loads(review_path.read_text())
    frames = {frame["frame_index"]: frame for frame in review["source_capture"]["frames"]}
    assert [sample.frame_index for sample in fixture.samples] == [
        18000, 18001, 18002, 18060, 18120, 18121
    ]
    assert review["review"]["status"] == (
        "exposed development review; not blinded gold or full-round acceptance"
    )
    assert "not calibrated probabilities" in review["review"]["confidence_convention"]
    assert "exclude protruding direction indicator" in review["review"]["coordinate_convention"]
    assert all(sample.visibility == "visible" for sample in fixture.samples)
    for sample in fixture.samples:
        source = frames[sample.frame_index]
        assert sample.decoded_frame_sha256 == source["full_bgr_sha256"]
        assert sample.decoded_crop_sha256 == source["crop_bgr_sha256"]
        assert sample.timestamp_s == source["timestamp_seconds"]
        assert source["source_video_sha256"] == review["source_capture"]["source_video_sha256"]


def test_full_frame_and_crop_hashes_bind_to_exact_decoded_pixels():
    frame = np.zeros((6, 8, 3), dtype=np.uint8)
    crop = PlayerIdentityCrop(x=1, y=1, width=4, height=3)
    frame_hash = decoded_frame_sha256(frame)
    crop_hash = decoded_identity_crop_sha256(frame, crop)
    frame[0, 0, 0] = 1
    assert decoded_frame_sha256(frame) != frame_hash
    assert decoded_identity_crop_sha256(frame, crop) == crop_hash
    frame[1, 1, 0] = 1
    assert decoded_identity_crop_sha256(frame, crop) != crop_hash


def test_observation_schema_requires_proven_icon_link_and_valid_hashes():
    observation = PlayerIdentityObservation.model_validate(observation_data())
    assert observation.label.team_id == "100T"
    assert observation.label.player_id == "bang"
    assert observation.label.alive is True
    assert observation.samples[0].decoded_crop_sha256 == "b" * 64

    invalid = observation_data()
    invalid["samples"] = [dict(observation_data()["samples"][0], decoded_frame_sha256="bad")]
    with pytest.raises(ValidationError, match="lowercase SHA-256"):
        PlayerIdentityObservation.model_validate(invalid)

    invalid = observation_data()
    invalid["label"] = dict(observation_data()["label"], icon_link_evidence=" ")
    with pytest.raises(ValidationError):
        PlayerIdentityObservation.model_validate(invalid)


def test_local_verification_fails_closed_on_a_frame_hash_mismatch(monkeypatch):
    import cv2

    frame = np.zeros((6, 8, 3), dtype=np.uint8)
    data = observation_data()
    sample = dict(data["samples"][0])
    sample["decoded_frame_sha256"] = decoded_frame_sha256(frame)
    sample["decoded_crop_sha256"] = decoded_identity_crop_sha256(
        frame, PlayerIdentityCrop(x=1, y=1, width=4, height=3)
    )
    data["samples"] = [sample]
    observation = PlayerIdentityObservation.model_validate(data)

    capture = Mock()
    capture.isOpened.return_value = True
    capture.get.side_effect = lambda property_id: {
        cv2.CAP_PROP_FRAME_WIDTH: 8,
        cv2.CAP_PROP_FRAME_HEIGHT: 6,
        cv2.CAP_PROP_FPS: 60,
    }[property_id]
    capture.read.return_value = (True, frame.copy())
    monkeypatch.setattr(cv2, "VideoCapture", lambda _: capture)
    verify_identity_observation(Path("vod.mp4"), observation)
    bad_sample = sample | {"decoded_frame_sha256": "c" * 64}
    data["samples"] = [bad_sample]
    with pytest.raises(ValueError, match="decoded frame hash mismatch"):
        verify_identity_observation(
            Path("vod.mp4"),
            PlayerIdentityObservation.model_validate(data),
        )


def test_visibility_requires_consistent_icon_location_and_uncertainty_note():
    sample = observation_data()["samples"][0]
    assert isinstance(sample, dict)

    invalid = observation_data()
    invalid["samples"] = [dict(sample, icon_center_crop_px=None)]
    with pytest.raises(ValidationError, match="visible icons require an icon center"):
        PlayerIdentityObservation.model_validate(invalid)

    invalid = observation_data()
    invalid["samples"] = [dict(sample, visibility="not_visible")]
    with pytest.raises(ValidationError, match="not-visible icons cannot have an icon center"):
        PlayerIdentityObservation.model_validate(invalid)

    invalid = observation_data()
    invalid["samples"] = [
        dict(sample, visibility="uncertain", icon_center_crop_px=None)
    ]
    with pytest.raises(ValidationError, match="uncertain visibility requires"):
        PlayerIdentityObservation.model_validate(invalid)

    uncertain = dict(
        sample,
        visibility="uncertain",
        icon_center_crop_px=None,
        uncertainty_note="No center could be localized in this frame.",
    )
    invalid["samples"] = [uncertain]
    assert PlayerIdentityObservation.model_validate(invalid).samples[0].visibility == "uncertain"


def test_observation_rejects_duplicate_frames_and_invalid_icon_location():
    data = observation_data()
    second = dict(data["samples"][0], timestamp_s=300.01, frame_index=18000)
    data["samples"] = [data["samples"][0], second]
    with pytest.raises(ValidationError, match="ordered by distinct frame"):
        PlayerIdentityObservation.model_validate(data)

    data = observation_data()
    data["samples"] = [dict(data["samples"][0], icon_center_crop_px=[400, 2])]
    with pytest.raises(ValidationError, match="inside the source crop"):
        PlayerIdentityObservation.model_validate(data)
