from __future__ import annotations

import json
from pathlib import Path

import pytest

from valoscribe.tracking.motion_model import KnownPlayer, PlayerMotionTracker
from valoscribe.types.persistent import (
    MotionModelConfig,
    NormalizedPoint,
    PlayerDetection,
    PlayerTrackEstimate,
    Side,
)

PLAYER = KnownPlayer(player_id="p1", agent_id="jett", team_id="alpha")
CONFIG = MotionModelConfig(
    map_width_m=100.0,
    map_height_m=100.0,
    maximum_speed_mps=8.0,
    maximum_prediction_gap_s=1.0,
    minimum_detection_confidence=0.5,
    minimum_registration_confidence=0.8,
)


def detection(
    timestamp: float,
    x: float,
    *,
    candidates: list[str] | None = None,
    registration: float = 0.95,
    source_frame: int = 0,
) -> PlayerDetection:
    return PlayerDetection(
        vod_timestamp_s=timestamp,
        team_id="alpha",
        broadcast_slot="unknown",
        side=Side.UNKNOWN,
        candidate_player_ids=candidates if candidates is not None else ["p1"],
        candidate_agent_ids=["jett"],
        crop_point=NormalizedPoint(x=x, y=0.5),
        canonical_point=NormalizedPoint(x=x, y=0.5),
        detector_confidence=0.9,
        registration_confidence=registration,
        source_frame=source_frame,
    )


def test_creates_one_track_per_known_player_and_keeps_observation_evidence() -> None:
    tracker = PlayerMotionTracker([PLAYER, KnownPlayer("p2", "sage", "beta")], CONFIG)

    estimate = tracker.update("p1", detection(1.0, 0.25, source_frame=24))

    assert tracker.player_ids == ("p1", "p2")
    assert estimate.position == NormalizedPoint(x=0.25, y=0.5)
    assert estimate.observed and not estimate.predicted
    assert estimate.source_frame == 24
    assert estimate.confidence == 0.9
    assert "frame=24" in estimate.evidence[0]


def test_predicts_only_after_two_observations_and_within_short_gap() -> None:
    tracker = PlayerMotionTracker([PLAYER], CONFIG)
    tracker.update("p1", detection(1.0, 0.2, source_frame=1))
    assert tracker.predict("p1", 1.25).rejection_reason == "motion_history_insufficient"
    tracker.update("p1", detection(1.25, 0.21, source_frame=2))

    predicted = tracker.predict("p1", 1.5)

    assert predicted.position is not None
    assert predicted.position.x == pytest.approx(0.22)
    assert predicted.position.y == pytest.approx(0.5)
    assert not predicted.observed and predicted.predicted
    assert predicted.source_frame is None
    assert 0 < predicted.confidence < 0.9
    assert len(predicted.evidence) == 3
    assert tracker.predict("p1", 2.25).rejection_reason == "prediction_gap_exceeded"
    assert tracker.predict("p1", 2.251).rejection_reason == "prediction_gap_exceeded"


def test_prediction_diagnostic_matches_golden_artifact() -> None:
    tracker = PlayerMotionTracker([PLAYER], CONFIG)
    tracker.update("p1", detection(1.0, 0.2, source_frame=1))
    tracker.update("p1", detection(1.25, 0.21, source_frame=2))
    estimate = tracker.predict("p1", 1.5)
    artifact = Path(__file__).parents[1] / "expected/golden/motion_model_prediction.json"

    assert json.loads(artifact.read_text()) == estimate.model_dump(mode="json")


def test_missing_identity_or_registration_returns_unknown_not_a_fake_point() -> None:
    tracker = PlayerMotionTracker([PLAYER], CONFIG)

    ambiguous = tracker.update("p1", detection(1.0, 0.2, candidates=["p1", "p2"]))
    unregistered = tracker.update("p1", detection(1.0, 0.2, registration=0.3))

    for estimate in (ambiguous, unregistered):
        assert estimate.position is None
        assert not estimate.observed and not estimate.predicted
        assert estimate.confidence == 0.0
        assert estimate.evidence
    assert ambiguous.rejection_reason == "identity_evidence_missing_or_ambiguous"
    assert unregistered.rejection_reason == "map_registration_confidence_below_minimum"


def test_rejects_impossible_speed_and_resets_track_history() -> None:
    tracker = PlayerMotionTracker([PLAYER], CONFIG)
    tracker.update("p1", detection(1.0, 0.2))

    impossible = tracker.update("p1", detection(1.1, 0.4))

    assert impossible.position is None
    assert impossible.rejection_reason == "movement_speed_gate_exceeded"
    assert tracker.predict("p1", 1.2).rejection_reason == "motion_history_insufficient"


def test_prediction_that_leaves_map_returns_unknown() -> None:
    fast_config = CONFIG.model_copy(update={"maximum_speed_mps": 30.0})
    tracker = PlayerMotionTracker([PLAYER], fast_config)
    tracker.update("p1", detection(1.0, 0.95))
    tracker.update("p1", detection(1.1, 0.98))

    estimate = tracker.predict("p1", 2.1)  # exactly at the prediction horizon
    assert estimate.rejection_reason == "prediction_gap_exceeded"

    out_of_bounds = tracker.predict("p1", 1.5)
    assert out_of_bounds.rejection_reason == "predicted_position_out_of_bounds"
    assert out_of_bounds.position is None


def test_non_increasing_observation_does_not_replace_good_track_state() -> None:
    tracker = PlayerMotionTracker([PLAYER], CONFIG)
    tracker.update("p1", detection(1.0, 0.2))
    tracker.update("p1", detection(1.2, 0.21))

    stale = tracker.update("p1", detection(1.1, 0.205))

    assert stale.position is None
    assert stale.rejection_reason == "observation_timestamp_not_increasing"
    assert tracker.predict("p1", 1.3).position is not None


def test_estimate_contract_rejects_fake_observations_and_unexplained_unknowns() -> None:
    with pytest.raises(ValueError, match="observed or predicted"):
        PlayerTrackEstimate(
            player_id="p1",
            vod_timestamp_s=1,
            position=NormalizedPoint(x=0.2, y=0.5),
            observed=True,
            predicted=True,
            confidence=0.9,
            evidence=["test"],
        )
    with pytest.raises(ValueError, match="unknown track samples"):
        PlayerTrackEstimate(
            player_id="p1",
            vod_timestamp_s=1,
            position=None,
            observed=False,
            predicted=False,
            confidence=0.9,
            evidence=["test"],
            rejection_reason="unknown",
        )
