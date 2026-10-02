import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from pydantic_core import PydanticSerializationError

from valoscribe.types.cast_observation import ReviewedCastObservation
from valoscribe.types.smoke_evaluation import ReviewedSmokeLabel

ARTIFACT = Path(__file__).parents[2] / "tests/fixtures/vta502_cast_observation_1425.json"


def test_vta502_cast_artifact_records_cast_identity_not_smoke_ground_truth() -> None:
    observation = ReviewedCastObservation.model_validate_json(ARTIFACT.read_text())

    assert observation.observed_player == "bang"
    assert observation.observed_agent == "Omen"
    assert observation.observed_ability == "Dark Cover"
    assert observation.confidence == 0.95
    assert [
        (event.event_id, event.start_timestamp_s, event.end_timestamp_s)
        for event in observation.events
    ] == [
        ("targeting-entry", 1423.4, 1423.5),
        ("dark-cover-preview", 1423.7, 1424.8),
        ("release-transition", 1424.8, 1424.9),
        ("post-release-glove", 1425.0, 1425.0),
        ("world-view-return", 1425.1, 1425.1),
        ("observer-cut", 1425.3, 1425.4),
    ]
    assert observation.source_video_sha256 == (
        "a2feb25b842b6c1c2baa17f8ef0c5ecfe1816bd058a1c256350fa95900454c44"
    )
    assert observation.evidence_frames[0].full_frame_bgr_sha256 == (
        "964ad5bb792876971ceef53d2f6763b5a23515c06edbd534783ba40a53f9ef78"
    )
    footprint = observation.smoke_footprint_observation
    assert footprint.center is None
    assert footprint.world_smoke_deployment == "unknown"
    assert footprint.smoke_lifecycle == "unknown"
    assert footprint.caster_to_footprint_correspondence == "unknown"
    assert footprint.minimap_correspondence == "unknown"
    assert observation.not_a_smoke_label is True

    with pytest.raises(ValidationError):
        ReviewedSmokeLabel.model_validate(observation.model_dump())


REQUIRED_TEXT_PATHS = [
    ("observation_id",),
    ("source_video_path",),
    ("source_video_filename",),
    ("source_acquisition_manifest_path",),
    ("observed_player",),
    ("observed_agent",),
    ("observed_ability",),
    ("confidence_basis",),
    ("events", 0, "event_id"),
    ("events", 0, "description"),
    ("evidence_frames", 0, "description"),
]


def _at_path(value: Any, path: tuple[str | int, ...]) -> Any:
    for part in path:
        value = value[part] if isinstance(part, int) else value[part]
    return value


@pytest.mark.parametrize("path", REQUIRED_TEXT_PATHS)
def test_cast_observation_rejects_blank_required_text_on_construction(
    path: tuple[str | int, ...],
) -> None:
    payload = json.loads(ARTIFACT.read_text())
    _at_path(payload, path[:-1])[path[-1]] = " \t\n "

    with pytest.raises(ValidationError, match="text must not be blank"):
        ReviewedCastObservation.model_validate(payload)


@pytest.mark.parametrize("path", REQUIRED_TEXT_PATHS)
@pytest.mark.parametrize("serializer", ["model_dump", "model_dump_json"])
def test_cast_observation_rejects_blank_required_text_after_mutation(
    path: tuple[str | int, ...], serializer: str
) -> None:
    observation = ReviewedCastObservation.model_validate_json(ARTIFACT.read_text())
    target = observation
    for part in path[:-1]:
        target = target[part] if isinstance(part, int) else getattr(target, part)
    target.__dict__[path[-1]] = " \t\n "

    with pytest.raises(PydanticSerializationError, match="text must not be blank"):
        getattr(observation, serializer)()


def test_cast_artifact_rejects_hash_and_bracket_mutation() -> None:
    payload = json.loads(ARTIFACT.read_text())
    payload["evidence_frames"][0]["full_frame_bgr_sha256"] = "not-a-hash"
    with pytest.raises(ValidationError, match="lowercase SHA-256"):
        ReviewedCastObservation.model_validate(payload)

    payload = json.loads(ARTIFACT.read_text())
    payload["events"][0]["evidence_frame_indices"] = [85422]
    with pytest.raises(ValidationError, match="outside its time bracket"):
        ReviewedCastObservation.model_validate(payload)


def test_cast_observation_revalidates_mutated_persistent_evidence() -> None:
    observation = ReviewedCastObservation.model_validate_json(ARTIFACT.read_text())
    observation.evidence_frames[0].__dict__["full_frame_bgr_sha256"] = "bad"
    with pytest.raises(PydanticSerializationError, match="lowercase SHA-256"):
        observation.model_dump()


def test_cast_observation_rejects_missing_event_evidence_and_smoke_promotion() -> None:
    payload = json.loads(ARTIFACT.read_text())
    payload["events"][0]["evidence_frame_indices"] = [999999]
    with pytest.raises(ValidationError, match="missing evidence frame"):
        ReviewedCastObservation.model_validate(payload)

    payload = json.loads(ARTIFACT.read_text())
    payload["not_a_smoke_label"] = False
    with pytest.raises(ValidationError):
        ReviewedCastObservation.model_validate(payload)

    payload = json.loads(ARTIFACT.read_text())
    payload["smoke_footprint_observation"]["world_smoke_deployment"] = "deployed"
    payload["smoke_footprint_observation"]["center"] = [0.5, 0.5]
    with pytest.raises(ValidationError):
        ReviewedCastObservation.model_validate(payload)
