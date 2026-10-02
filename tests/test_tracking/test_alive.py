import pytest

from valoscribe.tracking.alive import AliveStateTracker
from valoscribe.tracking.smoothing import TrackSmoother
from valoscribe.types.persistent import (
    AliveState,
    HUDAliveObservation,
    KillfeedIdentityEvidence,
    KillfeedKillObservation,
    MotionModelConfig,
    NormalizedPoint,
    PlayerTrackEstimate,
    TrackSmoothingInput,
)


def hud(
    player: str,
    timestamp: float,
    state: AliveState = AliveState.ALIVE,
    *,
    visible: bool = True,
    confidence: float = 0.99,
    round_id: str = "round-1",
) -> HUDAliveObservation:
    return HUDAliveObservation(
        player_id=player,
        round_id=round_id,
        vod_timestamp_s=timestamp,
        state=state,
        confidence=confidence,
        visible=visible,
        evidence=["synthetic_hud"],
    )


def killfeed(
    event_id: str,
    timestamp: float,
    candidates: list[str],
    *,
    confidence: float = 0.99,
    round_id: str = "round-1",
) -> KillfeedKillObservation:
    return KillfeedKillObservation(
        event_id=event_id,
        round_id=round_id,
        vod_timestamp_s=timestamp,
        killer=KillfeedIdentityEvidence(
            agent_id="Jett", candidate_player_ids=["killer"], confidence=0.99
        ),
        victim=KillfeedIdentityEvidence(
            agent_id="Sova", candidate_player_ids=candidates, confidence=confidence
        ),
        evidence=["synthetic_killfeed"],
    )


def test_fused_dead_state_suppresses_observed_track_position() -> None:
    """Callers must pass the fused alive flag; no VOD orchestrator does so yet."""
    tracker = AliveStateTracker("round-1")
    tracker.update_killfeed(killfeed("death", 1.0, ["victim"]))
    alive = tracker.tracking_alive("victim")
    assert alive is False

    estimate = PlayerTrackEstimate(
        player_id="victim",
        vod_timestamp_s=1.0,
        source_frame=10,
        position=NormalizedPoint(x=0.4, y=0.6),
        observed=True,
        predicted=False,
        confidence=0.9,
        evidence=["raw:marker_observation"],
    )
    smoother = TrackSmoother(
        MotionModelConfig(
            map_width_m=100.0,
            map_height_m=100.0,
            maximum_speed_mps=8.0,
            maximum_prediction_gap_s=1.0,
            minimum_detection_confidence=0.5,
            minimum_registration_confidence=0.8,
        ),
        ema_alpha=0.5,
    )
    result = smoother.smooth(
        [
            TrackSmoothingInput(
                estimate=estimate,
                round_id="round-1",
                alive=alive,
                interval_state="live",
                context_evidence=["synthetic_context"],
            )
        ]
    )

    assert result[0].position is None
    assert result[0].raw_estimate == estimate
    assert result[0].raw_estimate.position == NormalizedPoint(x=0.4, y=0.6)
    assert result[0].rejection_reason == "context_not_verified"


def test_hud_visible_occluded_and_unknown_states() -> None:
    tracker = AliveStateTracker("round-1")

    visible = tracker.update_hud(hud("player", 1.0))
    assert visible.state is AliveState.ALIVE
    assert tracker.tracking_alive("player") is True

    occluded = tracker.update_hud(hud("player", 2.0, visible=False))
    assert occluded.state is AliveState.ALIVE
    assert "hud_occluded_prior_evidence_preserved" in occluded.evidence

    unknown = tracker.update_hud(hud("other", 3.0, visible=False))
    assert unknown.state is AliveState.UNKNOWN
    assert tracker.tracking_alive("other") is None

    explicit_unknown = tracker.update_hud(hud("player", 4.0, AliveState.UNKNOWN))
    assert explicit_unknown.state is AliveState.UNKNOWN
    assert explicit_unknown.rejection_reason == "hud_state_unknown"


def test_unique_confident_killfeed_marks_victim_dead() -> None:
    tracker = AliveStateTracker("round-1")
    result = tracker.update_killfeed(killfeed("event-1", 1.0, ["victim"]))

    assert len(result) == 1
    assert result[0].player_id == "victim"
    assert result[0].state is AliveState.DEAD
    assert tracker.tracking_alive("victim") is False


def test_ambiguous_duplicate_and_low_confidence_killfeed_are_not_deaths() -> None:
    tracker = AliveStateTracker("round-1")

    ambiguous = tracker.update_killfeed(killfeed("ambiguous", 1.0, ["a", "b"]))
    assert {item.player_id for item in ambiguous} == {"a", "b"}
    assert all(item.state is AliveState.UNKNOWN for item in ambiguous)
    assert all(item.rejection_reason == "victim_identity_ambiguous" for item in ambiguous)

    low = tracker.update_killfeed(killfeed("low", 2.0, ["c"], confidence=0.4))
    assert low[0].state is AliveState.UNKNOWN
    assert low[0].rejection_reason == "victim_confidence_below_threshold"

    confident = killfeed("duplicate", 3.0, ["d"])
    assert tracker.update_killfeed(confident)[0].state is AliveState.DEAD
    assert tracker.update_killfeed(confident) == ()


def test_hud_cannot_revive_dead_player_without_explicit_evidence() -> None:
    tracker = AliveStateTracker("round-1")
    tracker.update_killfeed(killfeed("death", 1.0, ["victim"]))

    result = tracker.update_hud(hud("victim", 2.0, AliveState.ALIVE))

    assert result.state is AliveState.DEAD
    assert result.rejection_reason is None
    assert tracker.tracking_alive("victim") is False


def test_confirmed_death_survives_alive_hud_and_ambiguous_killfeed() -> None:
    tracker = AliveStateTracker("round-1")
    tracker.update_killfeed(killfeed("death", 1.0, ["victim"]))

    alive_hud = tracker.update_hud(hud("victim", 2.0, AliveState.ALIVE))
    assert alive_hud.state is AliveState.DEAD
    assert tracker.tracking_alive("victim") is False

    ambiguous = tracker.update_killfeed(
        killfeed("ambiguous", 3.0, ["victim", "other"])
    )
    assert len(ambiguous) == 2
    assert tracker.state_for("victim").state is AliveState.DEAD
    assert tracker.tracking_alive("victim") is False


def test_round_reset_discards_prior_states_and_events() -> None:
    tracker = AliveStateTracker("round-1")
    tracker.update_killfeed(killfeed("event", 1.0, ["victim"]))
    tracker.reset_round("round-2")

    assert tracker.state_for("victim") is None
    assert tracker.tracking_alive("victim") is None
    result = tracker.update_killfeed(killfeed("event", 0.5, ["victim"], round_id="round-2"))
    assert result[0].state is AliveState.DEAD


def test_rejects_observations_for_other_round_and_out_of_order_timestamps() -> None:
    tracker = AliveStateTracker("round-1")

    with pytest.raises(ValueError, match="does not match"):
        tracker.update_hud(hud("player", 1.0, round_id="round-2"))

    tracker.update_hud(hud("player", 2.0))
    with pytest.raises(ValueError, match="timestamp ordered"):
        tracker.update_hud(hud("player", 1.0))
