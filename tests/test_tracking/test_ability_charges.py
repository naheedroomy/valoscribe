from __future__ import annotations

import pytest

from valoscribe.tracking.ability_charges import (
    AbilityChargeObservation,
    extract_ability_charge_deltas,
)
from valoscribe.types.persistent import (
    BroadcastInterval,
    BroadcastPhase,
    EvidenceRef,
    EvidenceSource,
    RoundPhase,
)


def observation(timestamp: float, charges: int, **overrides: object) -> AbilityChargeObservation:
    values: dict[str, object] = {
        "match_id": "m", "map_id": "map", "round_id": "r", "player_id": "p",
        "ability_id": "a", "agent_id": "agent", "team_id": "team",
        "vod_timestamp_s": timestamp, "charges": charges, "confidence": 0.9,
        "evidence": EvidenceRef(
            match_id="m", map_id="map", round_id="r", vod_timestamp_s=timestamp,
            source=EvidenceSource.PLAYER_HUD, confidence=0.8,
        ),
    }
    values.update(overrides)
    return AbilityChargeObservation(**values)  # type: ignore[arg-type]


def context(*timestamps: float, round_id: str = "r"):
    intervals = [BroadcastInterval(
        vod_timestamp_s=t, round_id=round_id, phase=BroadcastPhase.LIVE,
        confidence=0.9, evidence=["live"]
    ) for t in timestamps]
    phases = [(t, RoundPhase.DEFAULT) for t in timestamps]
    return intervals, phases


def extract(observations, timestamps=(1, 2), **kwargs):
    intervals, phases = context(*timestamps)
    return extract_ability_charge_deltas(
        observations, intervals, phases, max_gap_s=kwargs.get("max_gap_s", 2)
    )


def test_emits_raw_delta_for_consecutive_live_observed_hud_counts():
    result = extract([observation(1, 2), observation(2, 1)])
    assert len(result) == 1
    delta = result[0]
    assert (delta.previous_charges, delta.current_charges) == (2, 1)
    assert (delta.player_id, delta.agent_id, delta.team_id) == ("p", "agent", "team")
    assert delta.evidence[0].source == EvidenceSource.PLAYER_HUD
    assert delta.evidence[0].vod_timestamp_s == delta.vod_timestamp_s == 2
    assert delta.previous_evidence is not None
    assert delta.previous_evidence.vod_timestamp_s == 1
    assert delta.confidence == 0.8


def test_gap_occlusion_replay_and_unobserved_timestamp_break_continuity():
    assert extract([observation(1, 2), observation(4, 1)], (1, 4), max_gap_s=2) == []
    valid_interval, phases = context(1, 2)
    hidden = BroadcastInterval(
        vod_timestamp_s=2, round_id="r", phase=BroadcastPhase.HIDDEN,
        confidence=0, evidence=["covered"], rejection_reason="hud_or_minimap_hidden",
    )
    assert extract_ability_charge_deltas(
        [observation(1, 2), observation(2, 1)], [valid_interval[0], hidden], phases,
        max_gap_s=2,
    ) == []
    replay = BroadcastInterval(
        vod_timestamp_s=2, round_id="r", phase=BroadcastPhase.REPLAY,
        confidence=0, evidence=["replay"], rejection_reason="replay",
    )
    assert extract_ability_charge_deltas(
        [observation(1, 2), observation(2, 1)], [valid_interval[0], replay], phases,
        max_gap_s=2,
    ) == []


def test_intermediate_replay_hidden_and_preround_break_observation_pair():
    first, current = observation(1, 2), observation(3, 1)
    live = [1, 2, 3]
    intervals, phases = context(*live)
    replay = BroadcastInterval(
        vod_timestamp_s=2, round_id="r", phase=BroadcastPhase.REPLAY,
        confidence=0, evidence=["replay"], rejection_reason="replay",
    )
    assert extract_ability_charge_deltas(
        [first, current], [intervals[0], replay, intervals[2]], phases, max_gap_s=3
    ) == []
    hidden = replay.model_copy(update={
        "phase": BroadcastPhase.HIDDEN, "rejection_reason": "hidden"
    })
    assert extract_ability_charge_deltas(
        [first, current], [intervals[0], hidden, intervals[2]], phases, max_gap_s=3
    ) == []
    phases[1] = (2, RoundPhase.PREROUND)
    assert extract_ability_charge_deltas(
        [first, current], intervals, phases, max_gap_s=3
    ) == []


def test_duplicate_observation_timestamps_are_all_breaks_and_clean_pairs_recover():
    observations = [
        observation(1, 3),
        observation(2, 2),
        observation(2, 1),
        observation(3, 2),
        observation(4, 1),
        observation(6, 1),
        observation(6, 0),
        observation(7, 2),
        observation(8, 1),
        observation(9, 1),
    ]
    intervals, phases = context(1, 2, 3, 4, 6, 7, 8, 9)
    result = extract_ability_charge_deltas(
        observations, intervals, phases, max_gap_s=2
    )
    assert [(item.vod_timestamp_s, item.previous_charges, item.current_charges)
            for item in result] == [(4, 2, 1), (8, 2, 1)]


def test_rejected_live_interval_at_previous_observation_blocks_delta():
    first, current = observation(1, 2), observation(2, 1)
    intervals, phases = context(1, 2)
    rejected_previous = intervals[0].model_copy(
        update={"rejection_reason": "uncertain_live_classification"}
    )
    assert extract_ability_charge_deltas(
        [first, current], [rejected_previous, intervals[1]], phases, max_gap_s=2
    ) == []


def test_ambiguous_context_timestamps_fail_closed():
    first, current = observation(1, 2), observation(3, 1)
    intervals, phases = context(1, 2, 3)
    conflict = intervals[1].model_copy(update={"phase": BroadcastPhase.REPLAY})
    assert extract_ability_charge_deltas(
        [first, current], [*intervals, conflict], phases, max_gap_s=3
    ) == []
    assert extract_ability_charge_deltas(
        [first, current], intervals, [*phases, (2, RoundPhase.PREROUND)], max_gap_s=3
    ) == []


def test_round_phase_or_identity_transitions_do_not_bridge_observations():
    first = observation(1, 2)
    switched = observation(2, 1, player_id="other")
    assert extract([first, switched]) == []
    intervals, phases = context(1, 2)
    phases[1] = (2, RoundPhase.PREROUND)
    assert extract_ability_charge_deltas(
        [observation(1, 2), observation(2, 1)], intervals, phases, max_gap_s=2
    ) == []


def test_rejects_mis_scoped_or_non_hud_evidence_and_requires_configured_gap():
    bad_scope = observation(2, 1, evidence=EvidenceRef(
        match_id="other", map_id="map", round_id="r", vod_timestamp_s=2,
        source=EvidenceSource.PLAYER_HUD, confidence=0.8,
    ))
    assert extract([observation(1, 2), bad_scope]) == []
    non_hud = observation(2, 1, evidence=EvidenceRef(
        match_id="m", map_id="map", round_id="r", vod_timestamp_s=2,
        source=EvidenceSource.METADATA, confidence=0.8,
    ))
    assert extract([observation(1, 2), non_hud]) == []
    for value in (float("nan"), float("inf"), -1):
        with pytest.raises(ValueError, match="finite and nonnegative"):
            extract_ability_charge_deltas([], [], [], max_gap_s=value)
