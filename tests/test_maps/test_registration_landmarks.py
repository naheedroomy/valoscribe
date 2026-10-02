"""Synthetic opt-in landmark reprojection evaluation coverage."""

import json
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from valoscribe.maps.config import MapDefinition
from valoscribe.maps.landmarks import (
    RegistrationLandmarkLabels,
    decoded_image_sha256,
    evaluate_registration_landmarks,
)


def labels_for(points):
    return RegistrationLandmarkLabels.model_validate(
        {
            "provenance": "synthetic reviewed fixture",
            "source_frame_sha256": "a" * 64,
            "canonical_asset_sha256": "b" * 64,
            "landmarks": points,
        }
    )


def test_exact_transform_has_zero_per_point_and_aggregate_error() -> None:
    labels = labels_for(
        [
            {
                "landmark_id": "a",
                "source_crop_point": {"x": 1, "y": 2},
                "canonical_point": {"x": 12, "y": 24},
            },
            {
                "landmark_id": "b",
                "source_crop_point": {"x": 3, "y": 4},
                "canonical_point": {"x": 16, "y": 28},
            },
        ]
    )

    evaluation = evaluate_registration_landmarks(
        labels, ((2.0, 0.0, 10.0), (0.0, 2.0, 20.0)), (10, 10), (40, 40)
    )

    assert evaluation["point_count"] == 2
    assert evaluation["mean_error_px"] == 0
    assert evaluation["rms_error_px"] == 0
    assert evaluation["maximum_error_px"] == 0
    assert evaluation["acceptance_threshold_configured"] is False


def test_wrong_transform_reports_pixel_errors_without_acceptance_claim() -> None:
    labels = labels_for(
        [
            {
                "landmark_id": "a",
                "source_crop_point": {"x": 2, "y": 3},
                "canonical_point": {"x": 14, "y": 23},
            }
        ]
    )

    evaluation = evaluate_registration_landmarks(
        labels, ((2.0, 0.0, 10.0), (0.0, 2.0, 20.0)), (10, 10), (40, 40)
    )

    assert evaluation["per_point_errors"] == [
        {"landmark_id": "a", "error_px": pytest.approx(3.0)}
    ]
    assert evaluation["mean_error_px"] == pytest.approx(3.0)
    assert evaluation["provenance"] == "synthetic reviewed fixture"
    assert evaluation["acceptance_threshold_configured"] is False


def test_configured_landmark_limit_controls_acceptance() -> None:
    labels = labels_for(
        [
            {
                "landmark_id": "a",
                "source_crop_point": {"x": 2, "y": 3},
                "canonical_point": {"x": 14, "y": 23},
            }
        ]
    )

    accepted = evaluate_registration_landmarks(
        labels, ((2.0, 0.0, 10.0), (0.0, 2.0, 20.0)), (10, 10), (40, 40), 3.0
    )
    rejected = evaluate_registration_landmarks(
        labels, ((2.0, 0.0, 10.0), (0.0, 2.0, 20.0)), (10, 10), (40, 40), 2.9
    )

    assert accepted["passed"] is True
    assert rejected["passed"] is False
    assert rejected["maximum_error_threshold_px"] == 2.9


def test_ascent_candidate_landmark_limit_accepts_reference_and_rejects_perturbed_source() -> None:
    map_path = Path(__file__).parents[2] / "src/valoscribe/config/ascent_map.json"
    map_definition = MapDefinition.model_validate(json.loads(map_path.read_text()))
    threshold = map_definition.registration_thresholds
    assert threshold is not None
    assert threshold.maximum_landmark_error_px == 25

    def one_landmark(source_x: int) -> RegistrationLandmarkLabels:
        return labels_for(
            [
                {
                    "landmark_id": "reference",
                    "source_crop_point": {"x": source_x, "y": 10},
                    "canonical_point": {"x": 10, "y": 10},
                }
            ]
        )

    accepted = evaluate_registration_landmarks(
        one_landmark(10), ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)), (64, 64), (64, 64),
        threshold.maximum_landmark_error_px,
    )
    rejected = evaluate_registration_landmarks(
        one_landmark(40), ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)), (64, 64), (64, 64),
        threshold.maximum_landmark_error_px,
    )

    assert accepted["passed"] is True
    assert accepted["maximum_error_px"] == 0
    assert rejected["maximum_error_px"] == 30
    assert rejected["passed"] is False


def test_decoded_image_hash_includes_shape_and_pixel_bytes() -> None:
    image = np.zeros((2, 3, 3), dtype=np.uint8)

    assert decoded_image_sha256(image) == decoded_image_sha256(image.copy())
    assert decoded_image_sha256(image) != decoded_image_sha256(image.reshape(3, 2, 3))


def test_empty_malformed_and_out_of_bounds_labels_fail() -> None:
    with pytest.raises(ValidationError):
        labels_for([])
    with pytest.raises(ValidationError):
        labels_for(
            [
                {
                    "landmark_id": "bad",
                    "source_crop_point": {"x": -1, "y": 0},
                    "canonical_point": {"x": 0, "y": 0},
                }
            ]
        )
    labels = labels_for(
        [
            {
                "landmark_id": "outside",
                "source_crop_point": {"x": 10, "y": 0},
                "canonical_point": {"x": 0, "y": 0},
            }
        ]
    )
    with pytest.raises(ValueError, match="landmark_source_out_of_bounds:outside"):
        evaluate_registration_landmarks(
            labels, ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)), (10, 10), (10, 10)
        )
