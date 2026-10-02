from __future__ import annotations

import pytest

from valoscribe.tracking.spike_fusion import SpikeObservation, SpikeState, SpikeStateFusion
from valoscribe.types.persistent import NormalizedPoint


def observation(**changes: object) -> SpikeObservation:
    values: dict[str, object] = {
        "match_id": "match",
        "map_id": "map",
        "round_id": "round-1",
        "vod_timestamp_s": 1.0,
        "confidence": 0.9,
        "evidence": ["synthetic_frame"],
    }
    values.update(changes)
    return SpikeObservation(**values)


def test_fuses_carrier_change_drop_plant_and_location() -> None:
    fusion = SpikeStateFusion()
    first = fusion.fuse(observation(carrier_marker_visible=True, carrier_player_id="p1"))
    assert first.state == SpikeState.CARRIED
    assert first.carrier_player_id == "p1"
    changed = fusion.fuse(
        observation(vod_timestamp_s=2, carrier_marker_visible=True, carrier_player_id="p2")
    )
    assert changed.carrier_player_id == "p2"
    dropped = fusion.fuse(observation(vod_timestamp_s=3, drop_marker_visible=True))
    assert dropped.state == SpikeState.DROPPED
    plant = fusion.fuse(observation(vod_timestamp_s=4, plant_event=True))
    assert plant.state == SpikeState.PLANTED
    assert plant.planted_location is None
    loc = NormalizedPoint(x=0.4, y=0.5)
    with_location = fusion.fuse(
        observation(vod_timestamp_s=5, hud_state=SpikeState.PLANTED, planted_location=loc)
    )
    assert with_location.planted_location == loc


def test_hud_outranks_minimap_and_conflicts_fail_closed() -> None:
    fusion = SpikeStateFusion()
    result = fusion.fuse(observation(hud_state=SpikeState.IN_SPAWN, carrier_marker_visible=True))
    assert result.state == SpikeState.UNKNOWN
    assert result.diagnostics[0].code == "conflicting_spike_cues"


def test_round_reset_replay_and_out_of_order_are_isolated() -> None:
    fusion = SpikeStateFusion()
    assert fusion.fuse(observation(plant_event=True)).state == SpikeState.PLANTED
    replay = fusion.fuse(observation(vod_timestamp_s=1.5, replay=True))
    assert replay.state == SpikeState.UNKNOWN
    assert replay.diagnostics[0].code == "replay_excluded"
    older = fusion.fuse(observation(vod_timestamp_s=1.25))
    assert older.state == SpikeState.PLANTED
    assert older.diagnostics == []
    next_round = fusion.fuse(observation(round_id="round-2", vod_timestamp_s=0.5))
    assert next_round.state == SpikeState.UNKNOWN
    assert next_round.planted_location is None


def test_replay_before_round_change_does_not_reset_or_advance_state() -> None:
    fusion = SpikeStateFusion()
    planted = fusion.fuse(observation(plant_event=True))
    replay = fusion.fuse(
        observation(round_id="round-2", vod_timestamp_s=99, replay=True)
    )
    assert replay.state == SpikeState.UNKNOWN
    assert replay.planted_location is None
    live_old = fusion.fuse(observation(vod_timestamp_s=0.5))
    assert live_old.state == SpikeState.UNKNOWN
    assert live_old.diagnostics[0].code == "out_of_order_timestamp"
    assert planted.state == SpikeState.PLANTED


def test_replay_at_future_timestamp_does_not_reject_live_frame() -> None:
    fusion = SpikeStateFusion()
    fusion.fuse(observation(vod_timestamp_s=2, hud_state=SpikeState.IN_SPAWN))
    replay = fusion.fuse(observation(vod_timestamp_s=100, replay=True))
    assert replay.state == SpikeState.UNKNOWN
    live = fusion.fuse(observation(vod_timestamp_s=3, plant_event=True))
    assert live.state == SpikeState.PLANTED


def test_round_key_includes_match_and_map() -> None:
    fusion = SpikeStateFusion()
    fusion.fuse(observation(match_id="match-a", map_id="map-a", plant_event=True))
    new_match = fusion.fuse(
        observation(match_id="match-b", map_id="map-a", vod_timestamp_s=1)
    )
    assert new_match.state == SpikeState.UNKNOWN
    assert new_match.confidence == 0.0
    new_map = fusion.fuse(
        observation(match_id="match-b", map_id="map-b", vod_timestamp_s=1)
    )
    assert new_map.state == SpikeState.UNKNOWN
    assert new_map.planted_location is None


def test_absent_cues_retain_historical_confidence_and_evidence() -> None:
    fusion = SpikeStateFusion()
    confirmed = fusion.fuse(
        observation(hud_state=SpikeState.IN_SPAWN, evidence=["spawn_hud"], confidence=0.7)
    )
    absent = fusion.fuse(observation(vod_timestamp_s=2, evidence=["empty_frame"], confidence=1.0))
    assert absent.state == confirmed.state
    assert absent.confidence == confirmed.confidence
    assert "spawn_hud" in absent.evidence
    assert "empty_frame" not in absent.evidence


def test_carried_marker_without_identity_preserves_confirmed_carrier() -> None:
    fusion = SpikeStateFusion()
    fusion.fuse(observation(carrier_marker_visible=True, carrier_player_id="p1"))
    carried = fusion.fuse(observation(vod_timestamp_s=2, carrier_marker_visible=True))
    assert carried.state == SpikeState.CARRIED
    assert carried.carrier_player_id == "p1"


def test_conflicting_cues_do_not_commit_planted_location_or_clear_carrier() -> None:
    fusion = SpikeStateFusion()
    fusion.fuse(observation(carrier_marker_visible=True, carrier_player_id="p1"))
    location = NormalizedPoint(x=0.4, y=0.5)
    conflict = fusion.fuse(
        observation(
            vod_timestamp_s=2,
            plant_event=True,
            drop_marker_visible=True,
            planted_location=location,
        )
    )
    assert conflict.state == SpikeState.UNKNOWN
    assert conflict.planted_location is None
    assert conflict.carrier_player_id == "p1"


def test_observation_requires_evidence_and_marker_identity_consistency() -> None:
    with pytest.raises(ValueError):
        observation(evidence=[])
    with pytest.raises(ValueError):
        observation(carrier_player_id="p1")
