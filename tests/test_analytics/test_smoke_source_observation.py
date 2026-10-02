from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError
from pydantic_core import PydanticSerializationError

from valoscribe.analytics.smoke_source_observation import decoded_crop_sha256
from valoscribe.types.smoke_source_observation import (
    SmokeSourceCrop,
    SmokeSourceObservation,
    SmokeSourceSample,
    SmokeSourceSampleKind,
)


def observation_data() -> dict[str, object]:
    return {
        "source_filename": "vod.mp4",
        "source_frame_width": 1920,
        "source_frame_height": 1080,
        "nominal_fps": 60,
        "crop": {"x": 70, "y": 50, "width": 360, "height": 400},
        "first_present_timestamp_s": 2489.75,
        "last_present_timestamp_s": 2505.133333,
        "first_absent_after_present_timestamp_s": 2505.366667,
        "boundary_uncertainty_s": 0.25,
        "onset_last_unsettled_timestamp_s": 2489.5,
        "onset_first_persistent_timestamp_s": 2489.75,
        "end_last_present_timestamp_s": 2505.133333,
        "end_first_clearly_absent_timestamp_s": 2505.366667,
        "maximum_timing_uncertainty_s": 0.25,
        "center_source_crop_px": (251, 155),
        "center_tolerance_px": 3,
        "samples": [
            {
                "timestamp_s": 2489.5,
                "frame_index": 149370,
                "kind": "unsettled",
                "review_note": "transition",
            },
            {
                "timestamp_s": 2489.75,
                "frame_index": 149385,
                "kind": "present",
                "review_note": "reviewed source frame",
                "decoded_crop_sha256": "a" * 64,
            },
            {
                "timestamp_s": 2505.133333,
                "frame_index": 150308,
                "kind": "present",
                "review_note": "reviewed source frame",
                "decoded_crop_sha256": "a" * 64,
            },
            {
                "timestamp_s": 2505.25,
                "frame_index": 150315,
                "kind": "unsettled",
                "review_note": "transition",
            },
            {
                "timestamp_s": 2505.366667,
                "frame_index": 150322,
                "kind": "absent",
                "review_note": "reviewed",
            },
        ],
    }


def test_vta502_source_observation_records_reviewed_values_without_precise_onset() -> None:
    artifact_path = Path(__file__).parents[2] / "docs/smoke_source_observation_vta502.json"
    artifact = SmokeSourceObservation.model_validate_json(artifact_path.read_text())

    assert artifact.center_source_crop_px == (251, 155)
    assert artifact.center_tolerance_px == 3
    present_notes = [
        sample.review_note for sample in artifact.samples if sample.kind.value == "present"
    ]
    assert all(
        "unannotated raw crop" in note and "±3 source-crop pixels" in note for note in present_notes
    )
    assert all("±2 precision is unsupported" in note for note in present_notes)
    assert artifact.agent_attribution == "UNKNOWN"
    assert artifact.independent_visual_review is not None
    assert artifact.independent_visual_review.smoke_identity == "UNRESOLVED"
    assert artifact.independent_visual_review.smoke_plausibility == "MODERATE"
    assert artifact.independent_visual_review.caster_attribution == "UNKNOWN"
    assert artifact.independent_visual_review.interpretation == (
        "EXPLORATORY_VISUAL_FOOTPRINT_CANDIDATE_ONLY"
    )
    review_evidence = artifact.independent_visual_review.evidence
    assert [item.timestamp_s for item in review_evidence] == [
        2487.75, 2488.0, 2488.25, 2488.5, 2488.75, 2489.0, 2489.25,
        2489.5, 2489.75, 2490.0, 2505.0,
    ]
    assert "Relation to earlier teal-rimmed circle is unresolved" in review_evidence[8].description
    assert "changes with ADS" in review_evidence[8].description
    assert artifact.canonical_map_point is None
    assert artifact.first_present_timestamp_s == 2489.75
    assert artifact.last_present_timestamp_s == 2505.133333
    assert artifact.first_absent_after_present_timestamp_s == 2505.366667
    assert artifact.boundary_uncertainty_s == 0.25
    assert [(sample.timestamp_s, sample.kind.value) for sample in artifact.samples] == [
        (2487, "absent"),
        (2488, "unsettled"),
        (2489, "unsettled"),
        (2489.5, "unsettled"),
        (2489.75, "present"),
        (2490, "present"),
        (2505, "present"),
        (2505.133333, "present"),
        (2505.25, "unsettled"),
        (2505.366667, "absent"),
        (2506, "absent"),
    ]
    assert all(sample.decoded_crop_sha256 for sample in artifact.samples)
    assert artifact.onset_last_unsettled_timestamp_s == 2489.5
    assert artifact.onset_first_persistent_timestamp_s == 2489.75
    assert artifact.end_last_present_timestamp_s == 2505.133333
    assert artifact.end_first_clearly_absent_timestamp_s == 2505.366667
    assert all(len(sample.decoded_crop_sha256 or "") == 64 for sample in artifact.samples)


def test_source_observation_rejects_inverted_or_out_of_order_bounds():
    data = observation_data()
    data["onset_first_persistent_timestamp_s"] = 2489.4
    with pytest.raises(ValidationError, match="onset interval is not ordered"):
        SmokeSourceObservation.model_validate(data)

    data = observation_data()
    data["end_first_clearly_absent_timestamp_s"] = 2505.0
    with pytest.raises(ValidationError, match="end interval is not ordered"):
        SmokeSourceObservation.model_validate(data)

    data = observation_data()
    data["samples"] = list(data["samples"]) + [
        {
            "timestamp_s": 2489,
            "frame_index": 149340,
            "kind": "absent",
            "review_note": "out of order",
        }
    ]
    with pytest.raises(ValidationError, match="strictly ordered"):
        SmokeSourceObservation.model_validate(data)


def test_source_observation_rejects_absence_inside_persistent_segment():
    data = observation_data()
    data["samples"] = [
        {"timestamp_s": 2489.5, "frame_index": 149370, "kind": "unsettled",
         "review_note": "transition"},
        {"timestamp_s": 2489.75, "frame_index": 149385, "kind": "present",
         "review_note": "present"},
        {"timestamp_s": 2500, "frame_index": 150000, "kind": "absent", "review_note": "gap"},
        {"timestamp_s": 2505.133333, "frame_index": 150308, "kind": "present",
         "review_note": "present"},
        {"timestamp_s": 2505.25, "frame_index": 150315, "kind": "unsettled",
         "review_note": "transition"},
        {"timestamp_s": 2505.366667, "frame_index": 150322, "kind": "absent",
         "review_note": "absent"},
    ]
    with pytest.raises(ValidationError, match="absent sample inside persistent"):
        SmokeSourceObservation.model_validate(data)


def test_decoded_crop_hash_is_stable_and_uses_only_requested_crop():
    frame = np.zeros((4, 5, 3), dtype=np.uint8)
    frame[1:3, 2:5] = 7
    crop = SmokeSourceCrop(x=2, y=1, width=3, height=2)
    expected = decoded_crop_sha256(frame, crop)
    frame[0, 0] = 255
    assert decoded_crop_sha256(frame, crop) == expected
    assert len(expected) == 64


def test_crop_hash_rejects_malformed_frame_and_out_of_bounds_crop():
    crop = SmokeSourceCrop(x=2, y=1, width=3, height=2)
    with pytest.raises(ValueError, match="8-bit, three-channel"):
        decoded_crop_sha256(np.zeros((4, 5), dtype=np.uint8), crop)
    with pytest.raises(ValueError, match="exceeds decoded frame"):
        decoded_crop_sha256(np.zeros((2, 2, 3), dtype=np.uint8), crop)


def test_independent_review_rejects_duplicate_frame_indices_after_mutation():
    artifact_path = Path(__file__).parents[2] / "docs/smoke_source_observation_vta502.json"
    observation = SmokeSourceObservation.model_validate_json(artifact_path.read_text())
    assert observation.independent_visual_review is not None
    review = observation.independent_visual_review
    duplicate = review.evidence[3].model_copy(update={"decoded_crop_sha256": "0" * 64})
    review.evidence.insert(0, duplicate)

    with pytest.raises(PydanticSerializationError, match="frame indices must be unique"):
        review.model_dump()


def test_source_observation_rejects_invalid_interval_and_frame_dimensions():
    data = observation_data()
    data["last_present_timestamp_s"] = 2489
    with pytest.raises(ValidationError, match="interval is not ordered"):
        SmokeSourceObservation.model_validate(data)

    data = observation_data()
    data["source_frame_width"] = 100
    with pytest.raises(ValidationError, match="exceeds frame width"):
        SmokeSourceObservation.model_validate(data)


def test_source_sample_rejects_invalid_digest_and_negative_frame_index():
    sample = {
        "timestamp_s": 1,
        "frame_index": 60,
        "kind": SmokeSourceSampleKind.PRESENT,
        "review_note": "reviewed",
        "decoded_crop_sha256": "not-a-hash",
    }
    with pytest.raises(ValidationError, match="lowercase SHA-256"):
        SmokeSourceSample.model_validate(sample)
    sample["decoded_crop_sha256"] = "a" * 64
    sample["frame_index"] = -1
    with pytest.raises(ValidationError):
        SmokeSourceSample.model_validate(sample)
