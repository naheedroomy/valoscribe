import pytest
from pydantic import ValidationError

from valoscribe.tracking.round_snapshots import RoundSnapshotFusion, RoundSnapshotInput
from valoscribe.types.persistent import (
    AliveState,
    BroadcastInterval,
    BroadcastPhase,
    FusedAliveState,
    NormalizedPoint,
    PlayerTrackEstimate,
)


def _source(
    timestamp: float = 10.0,
    phase: BroadcastPhase = BroadcastPhase.LIVE,
) -> RoundSnapshotInput:
    interval = BroadcastInterval(
        vod_timestamp_s=timestamp,
        round_id="r1",
        phase=phase,
        confidence=0.9,
        evidence=["timer_continuity"],
        rejection_reason=None if phase == BroadcastPhase.LIVE else "replay_cue_or_duplicate",
    )
    track = PlayerTrackEstimate(
        player_id="p1",
        vod_timestamp_s=timestamp,
        position=NormalizedPoint(x=0.4, y=0.6),
        observed=True,
        predicted=False,
        confidence=0.8,
        evidence=["minimap_detection"],
    )
    alive = FusedAliveState(
        player_id="p1",
        round_id="r1",
        vod_timestamp_s=timestamp,
        state=AliveState.ALIVE,
        confidence=0.95,
        evidence=["hud_alive"],
    )
    return RoundSnapshotInput(
        match_id="m1",
        map_id="ascent",
        round_id="r1",
        vod_timestamp_s=timestamp,
        round_elapsed_s=4.0,
        display_clock_s=96.0,
        broadcast=interval,
        tracks=[track],
        alive_states=[alive],
    )


def test_fuses_coherent_timestamped_player_snapshot() -> None:
    fusion = RoundSnapshotFusion()
    snapshot = fusion.fuse(_source(10.0))
    assert snapshot is not None
    assert (snapshot.vod_timestamp_s, snapshot.round_elapsed_s, snapshot.display_clock_s) == (
        10.0,
        4.0,
        96.0,
    )
    assert snapshot.players[0].position == NormalizedPoint(x=0.4, y=0.6)
    assert snapshot.players[0].alive == AliveState.ALIVE
    assert snapshot.players[0].confidence == 0.8
    assert snapshot.phase == snapshot.attacking_team == snapshot.spike_state == "UNKNOWN"


def test_replay_and_duplicate_cannot_emit_snapshots() -> None:
    fusion = RoundSnapshotFusion()
    assert fusion.fuse(_source(9.0, BroadcastPhase.REPLAY)) is None
    assert fusion.fuse(_source(10.0)) is not None
    assert fusion.fuse(_source(10.0)) is None
    assert len(fusion.rejections) == 2
    assert "broadcast_not_live" in fusion.rejections[0]
    assert "duplicate_or_out_of_order" in fusion.rejections[1]


@pytest.mark.parametrize(("interval_s", "expected"), [(0.25, [0.1, 0.4]), (0.5, [0.1])])
def test_sampling_cadence_uses_last_emitted_timestamp(
    interval_s: float, expected: list[float]
) -> None:
    fusion = RoundSnapshotFusion(interval_s)
    timestamps = (0.1, 0.26, 0.4, 0.5)
    emitted = [timestamp for timestamp in timestamps if fusion.fuse(_source(timestamp))]
    assert emitted == expected


def test_sampling_cadence_tolerates_float_epsilon_and_rejects_out_of_order() -> None:
    fusion = RoundSnapshotFusion(0.5)
    assert fusion.fuse(_source(10.0)) is not None
    assert fusion.fuse(_source(10.5 - 1e-10)) is not None
    assert fusion.fuse(_source(10.25)) is None
    assert "duplicate_or_out_of_order" in fusion.rejections[-1]


def test_replay_does_not_advance_cadence() -> None:
    fusion = RoundSnapshotFusion()
    assert fusion.fuse(_source(9.0, BroadcastPhase.REPLAY)) is None
    assert fusion.fuse(_source(10.0)) is not None
    assert fusion.fuse(_source(10.25, BroadcastPhase.REPLAY)) is None
    assert fusion.fuse(_source(10.25)) is not None


def test_round_cadence_resets_for_new_round() -> None:
    fusion = RoundSnapshotFusion()
    assert fusion.fuse(_source(10.0)) is not None
    second = _source(20.0)
    second = second.model_copy(update={"round_id": "r2"})
    second = second.model_copy(update={
        "broadcast": second.broadcast.model_copy(update={"round_id": "r2"}),
        "alive_states": [s.model_copy(update={"round_id": "r2"}) for s in second.alive_states],
    })
    assert fusion.fuse(second) is not None
    assert fusion.fuse(second.model_copy(update={
        "vod_timestamp_s": 20.25,
        "broadcast": second.broadcast.model_copy(update={"vod_timestamp_s": 20.25}),
        "tracks": [t.model_copy(update={"vod_timestamp_s": 20.25}) for t in second.tracks],
        "alive_states": [
            state.model_copy(update={"vod_timestamp_s": 20.25})
            for state in second.alive_states
        ],
    })) is not None


def test_persistent_contract_rejects_unsupported_schema_version() -> None:
    with pytest.raises(ValidationError):
        RoundSnapshotInput.model_validate(
            {**_source().model_dump(), "schema_version": "2.0"}
        )


def test_dead_and_observed_track_conflict_retains_evidence_without_position() -> None:
    source = _source(10.0)
    source = source.model_copy(update={
        "alive_states": [source.alive_states[0].model_copy(update={"state": AliveState.DEAD})]
    })
    fusion = RoundSnapshotFusion()
    fusion.fuse(source)
    sampled = _source(10.25)
    sampled = sampled.model_copy(update={
        "alive_states": [sampled.alive_states[0].model_copy(update={"state": AliveState.DEAD})]
    })
    snapshot = fusion.fuse(sampled)
    assert snapshot is not None
    player = snapshot.players[0]
    assert player.alive == AliveState.UNKNOWN
    assert player.position is None
    assert player.confidence == 0.4
    assert player.diagnostics[0].code == "dead_state_conflicts_with_observed_position"
    assert set(player.diagnostics[0].evidence) >= {"hud_alive", "minimap_detection"}
