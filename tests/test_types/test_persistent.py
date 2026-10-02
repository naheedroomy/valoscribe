"""Tests for versioned persistent tactical-analysis contracts."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError
from pydantic_core import PydanticSerializationError

from valoscribe.types.persistent import (
    AssignmentObservation,
    EvidenceRef,
    EvidenceSource,
    NormalizedPoint,
    PatternSummary,
    PlayerDetection,
    PlayerTrackPoint,
    ScenarioQuery,
    Side,
    UtilityEvent,
)


def evidence() -> EvidenceRef:
    return EvidenceRef(
        match_id="match-1",
        map_id="ascent",
        round_id="match-1-r1",
        vod_timestamp_s=12.5,
        round_elapsed_s=4.0,
        source=EvidenceSource.MINIMAP,
        confidence=0.9,
    )


def detection() -> PlayerDetection:
    return PlayerDetection(
        vod_timestamp_s=12.5,
        team_id="team-a",
        broadcast_slot="left",
        broadcast_color="red",
        side=Side.UNKNOWN,
        candidate_player_ids=["player-a"],
        candidate_agent_ids=["sova"],
        crop_point=NormalizedPoint(x=0.25, y=0.75),
        canonical_point=NormalizedPoint(x=0.4, y=0.6),
        detector_confidence=0.8,
        registration_confidence=0.95,
        source_frame=300,
    )


def track() -> PlayerTrackPoint:
    return PlayerTrackPoint(
        match_id="match-1",
        map_id="ascent",
        round_id="match-1-r1",
        vod_timestamp_s=12.5,
        round_elapsed_s=4.0,
        player_id="player-a",
        agent_id="sova",
        team_id="team-a",
        side=Side.ATTACK,
        position=NormalizedPoint(x=0.4, y=0.6),
        zone_id=None,
        alive=True,
        observed=True,
        confidence=0.85,
        evidence=[evidence()],
    )


def test_assignment_observation_v1_legacy_keys_and_json_read_compatibility() -> None:
    legacy = {
        "schema_version": "1.0",
        "candidate_id": "candidate-1",
        "team_id": "team-a",
        "side": "unknown",
        "canonical_point": {"schema_version": "1.0", "x": 0.4, "y": 0.6},
        "detector_confidence": 0.8,
        "registration_confidence": 0.95,
        "portrait_matches": [],
        "evidence": [],
    }

    observation = AssignmentObservation.model_validate(legacy)

    assert observation.model_dump(mode="json") == legacy
    assert AssignmentObservation.model_validate_json(observation.model_dump_json()) == observation


def test_versioned_raw_and_derived_models_serialize_separately() -> None:
    raw = detection()
    derived = track()

    raw_data = raw.model_dump(mode="json")
    derived_data = derived.model_dump(mode="json")
    assert raw_data["schema_version"] == "1.0"
    assert "candidate_player_ids" in raw_data
    assert "evidence" not in raw_data
    assert derived_data["schema_version"] == "1.0"
    assert derived_data["evidence"][0]["source"] == "minimap"
    assert derived_data["position"]["schema_version"] == "1.0"
    assert derived_data["evidence"][0]["schema_version"] == "1.0"
    assert "candidate_player_ids" not in derived_data
    assert PlayerDetection.model_validate_json(raw.model_dump_json()) == raw
    assert PlayerTrackPoint.model_validate_json(derived.model_dump_json()) == derived


def test_normalized_points_reject_out_of_range_and_nonfinite_coordinates() -> None:
    for coords in ({"x": -0.01, "y": 0.5}, {"x": 0.5, "y": 1.01}, {"x": float("nan"), "y": 0.5}):
        with pytest.raises(ValidationError):
            NormalizedPoint.model_validate(coords)


def test_confidence_timestamp_and_identifier_constraints() -> None:
    with pytest.raises(ValidationError):
        EvidenceRef(**{**evidence().model_dump(), "confidence": 1.1})
    with pytest.raises(ValidationError):
        EvidenceRef(**{**evidence().model_dump(), "vod_timestamp_s": -1.0})
    with pytest.raises(ValidationError):
        EvidenceRef(**{**evidence().model_dump(), "match_id": "  "})


def test_detection_rejects_invalid_confidence_and_track_inconsistent_interpolation() -> None:
    with pytest.raises(ValidationError):
        PlayerDetection(**{**detection().model_dump(), "detector_confidence": -0.1})

    with pytest.raises(ValidationError, match="cannot be marked observed"):
        PlayerTrackPoint(**{**track().model_dump(), "interpolated": True})
    with pytest.raises(ValidationError):
        PlayerTrackPoint(**{**track().model_dump(), "evidence": []})


def test_scenario_query_uses_independent_defaults_and_validates_filter_ranges() -> None:
    first = ScenarioQuery()
    second = ScenarioQuery()
    assert first.schema_version == "1.0"
    assert first.map_ids == []
    assert first.map_ids is not second.map_ids

    with pytest.raises(ValidationError):
        ScenarioQuery(round_numbers=[0])
    with pytest.raises(ValidationError, match="exceeds maximum"):
        ScenarioQuery(min_display_clock_s=50.0, max_display_clock_s=40.0)


def test_utility_and_pattern_models_validate_and_round_trip() -> None:
    utility = UtilityEvent(
        match_id="match-1",
        map_id="ascent",
        round_id="match-1-r1",
        vod_timestamp_s=12.5,
        team_id="team-a",
        ability_id="sova_recon_bolt",
        event_type="deployed",
        center=NormalizedPoint(x=0.4, y=0.6),
        geometry={"kind": "point"},
        observed=False,
        confidence=0.65,
        evidence=[evidence()],
    )
    query = ScenarioQuery(map_ids=["ascent"], sides=[Side.ATTACK])
    summary = PatternSummary(
        pattern_id="ascent-default-a",
        scenario_query=query,
        sample_size=1,
        matching_round_ids=["match-1-r1"],
        representative_round_ids=["match-1-r1"],
        outlier_round_ids=[],
        zone_occupancy_over_time={"A-main": [0.5]},
        common_transition_sequences=[["A-main", "A-site"]],
        rotation_timing_distribution={},
        utility_timing_distribution={},
        formation_distribution={},
        outcome_distribution={"win": 1},
        confidence_summary={"mean": 0.8},
        evidence_refs=[evidence()],
        narrative="Synthetic only",
    )

    assert UtilityEvent.model_validate_json(utility.model_dump_json()) == utility
    assert PatternSummary.model_validate_json(summary.model_dump_json()) == summary
    with pytest.raises(ValidationError, match="sample_size"):
        PatternSummary(**{**summary.model_dump(), "sample_size": 2})


def test_mutated_nested_collections_are_revalidated_before_json_persistence() -> None:
    derived = track()
    derived.evidence.clear()

    with pytest.raises(PydanticSerializationError):
        derived.model_dump_json()
    assert track().model_dump(include={"player_id"}) == {"player_id": "player-a"}


def test_track_and_utility_reject_evidence_from_another_round() -> None:
    invalid_evidence = evidence().model_copy(update={"round_id": "match-1-r2"})

    with pytest.raises(ValidationError, match="evidence match, map, and round"):
        PlayerTrackPoint(**{**track().model_dump(), "evidence": [invalid_evidence]})

    with pytest.raises(ValidationError, match="evidence match, map, and round"):
        UtilityEvent(
            match_id="match-1",
            map_id="ascent",
            round_id="match-1-r1",
            vod_timestamp_s=13.0,
            team_id="team-a",
            ability_id="sova_recon_bolt",
            event_type="deployed",
            observed=True,
            confidence=0.8,
            evidence=[invalid_evidence],
        )


def test_persistent_json_fields_reject_non_json_values() -> None:
    with pytest.raises(ValidationError):
        UtilityEvent(
            match_id="match-1",
            map_id="ascent",
            round_id="match-1-r1",
            vod_timestamp_s=13.0,
            team_id="team-a",
            ability_id="sova_recon_bolt",
            event_type="deployed",
            geometry={"invalid": object()},
            observed=True,
            confidence=0.8,
            evidence=[evidence()],
        )
    with pytest.raises(ValidationError, match="numbers must be finite"):
        UtilityEvent(
            match_id="match-1",
            map_id="ascent",
            round_id="match-1-r1",
            vod_timestamp_s=13.0,
            team_id="team-a",
            ability_id="sova_recon_bolt",
            event_type="deployed",
            geometry={"invalid": [float("nan")]},
            observed=True,
            confidence=0.8,
            evidence=[evidence()],
        )

    valid = PatternSummary(
        pattern_id="p1",
        scenario_query=ScenarioQuery(),
        sample_size=1,
        matching_round_ids=["match-1-r1"],
        representative_round_ids=[],
        outlier_round_ids=[],
        zone_occupancy_over_time={"A-main": [0.5, None, True]},
        common_transition_sequences=[],
        rotation_timing_distribution={},
        utility_timing_distribution={},
        formation_distribution={},
        outcome_distribution={},
        confidence_summary={},
        evidence_refs=[evidence()],
    )
    assert json.loads(valid.model_dump_json())["zone_occupancy_over_time"] == {
        "A-main": [0.5, None, True]
    }
    mutated = valid.model_copy(update={"confidence_summary": {"invalid": object()}})
    with pytest.raises(PydanticSerializationError):
        mutated.model_dump_json()


def test_all_persistent_models_generate_json_schemas() -> None:
    models = [
        NormalizedPoint,
        EvidenceRef,
        PlayerDetection,
        PlayerTrackPoint,
        UtilityEvent,
        ScenarioQuery,
        PatternSummary,
    ]
    for model in models:
        schema = model.model_json_schema()
        assert schema["title"] == model.__name__
        json.dumps(schema)
