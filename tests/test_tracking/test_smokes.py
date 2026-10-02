import pytest

from valoscribe.maps.config import SmokeTrackingThresholds
from valoscribe.tracking.smokes import track_anonymous_smokes, track_smokes
from valoscribe.types.persistent import (
    EvidenceRef,
    EvidenceSource,
    NormalizedPoint,
    SmokeCandidate,
    SmokeFrameObservation,
    SmokeRegionObservation,
    SmokeRegionState,
)


def candidate(timestamp: float, x: float, *, visible: bool = True, agent: str | None = None):
    reference = EvidenceRef(
        match_id="m1", map_id="map1", round_id="r1", vod_timestamp_s=timestamp,
        source=EvidenceSource.MINIMAP, confidence=0.9,
    )
    return SmokeCandidate(
        match_id="m1", map_id="map1", round_id="r1", vod_timestamp_s=timestamp,
        center=NormalizedPoint(x=x, y=0.5), approximate_radius=0.1,
        agent_type=agent, source=EvidenceSource.MINIMAP, confidence=0.9,
        evidence=[reference], live_visible=visible,
    )


def region(timestamp: float, x: float, *, radius: float = 0.2,
           state: SmokeRegionState = SmokeRegionState.CLEAR,
           visible: bool = True, observable: bool = True, scope: str = "r1"):
    reference = EvidenceRef(
        match_id="m1", map_id="map1", round_id=scope, vod_timestamp_s=timestamp,
        source=EvidenceSource.MINIMAP, confidence=0.8,
    )
    return SmokeRegionObservation(
        match_id="m1", map_id="map1", round_id=scope, vod_timestamp_s=timestamp,
        center=NormalizedPoint(x=x, y=0.5), approximate_radius=radius,
        state=state, live_visible=visible, fully_observable=observable,
        confidence=0.8, evidence=[reference],
    )


def test_tracks_smoke_lifecycle_overlap_and_hidden_gap_without_false_disappearance():
    result = track_smokes(
        [
            candidate(1.0, 0.2, agent="omen"), candidate(2.0, 0.2, agent="omen"),
            candidate(2.5, 0.35, agent="omen"), candidate(3.0, 0.2, agent="omen"),
            candidate(4.0, 0.2, visible=False, agent="omen"),
        ],
        SmokeTrackingThresholds(association_distance=0.05, maximum_observation_gap_s=2.0),
        supported_agents=frozenset({"omen"}),
    )
    assert len(result.events) == 2
    assert result.events[0].appeared_at_s == 1.0
    assert result.events[0].last_seen_at_s == 3.0
    assert result.events[0].disappeared_at_s is None
    assert result.events[0].overlaps_event_ids == [result.events[1].event_id]
    assert result.events[1].overlaps_event_ids == [result.events[0].event_id]
    assert result.diagnostics == [{"reason": "not_live_visible", "timestamp_s": 4.0}]


def test_explicit_live_clear_closes_after_configured_consecutive_frames():
    thresholds = SmokeTrackingThresholds(
        association_distance=0.1, maximum_observation_gap_s=2.0,
        disappearance_confirmation_frames=2,
    )
    refs = [
        EvidenceRef(match_id="m1", map_id="map1", round_id="r1", vod_timestamp_s=t,
                    source=EvidenceSource.MINIMAP, confidence=0.9)
        for t in (1.0, 2.0, 3.0, 4.0)
    ]
    clears = [
        SmokeFrameObservation(
            match_id="m1", map_id="map1", round_id="r1", vod_timestamp_s=t,
            evidence=[reference], live_visible=True, active_region_clear=True,
        ) for t, reference in zip((2.0, 3.0), refs[1:3])
    ]
    result = track_smokes(
        [candidate(1.0, 0.2, agent="omen")], thresholds,
        supported_agents=frozenset({"omen"}), frame_observations=clears,
    )
    assert result.events[0].last_seen_at_s == 1.0
    assert result.events[0].disappeared_at_s == 3.0
    assert [reference.vod_timestamp_s for reference in result.events[0].evidence] == [
        1.0, 2.0, 3.0
    ]
    assert result.events[0].confidence == 0.9


def test_hidden_frame_cannot_confirm_smoke_disappearance():
    threshold = SmokeTrackingThresholds(
        association_distance=0.1, maximum_observation_gap_s=2.0,
        disappearance_confirmation_frames=2,
    )
    hidden = SmokeFrameObservation(
        match_id="m1", map_id="map1", round_id="r1", vod_timestamp_s=2.0,
        evidence=[EvidenceRef(match_id="m1", map_id="map1", round_id="r1", vod_timestamp_s=2.0,
                           source=EvidenceSource.MINIMAP, confidence=0.9)],
        live_visible=False, active_region_clear=True,
    )
    result = track_smokes([candidate(1.0, 0.2, agent="omen")], threshold,
                          supported_agents=frozenset({"omen"}), frame_observations=[hidden])
    assert result.events[0].disappeared_at_s is None
    assert result.diagnostics == [{"reason": "not_live_visible", "timestamp_s": 2.0}]


def test_different_known_agents_do_not_associate_at_same_center():
    thresholds = SmokeTrackingThresholds(association_distance=0.1, maximum_observation_gap_s=2.0)
    result = track_smokes(
        [candidate(1.0, 0.2, agent="omen"), candidate(2.0, 0.2, agent="brimstone")],
        thresholds,
        supported_agents=frozenset({"omen", "brimstone"}),
    )
    assert len(result.events) == 2
    assert {event.agent_type for event in result.events} == {"omen", "brimstone"}


def test_agent_support_is_empty_by_default_and_rounds_do_not_associate():
    unsupported = candidate(1.0, 0.2, agent="omen")
    anonymous = candidate(2.0, 0.2)
    thresholds = SmokeTrackingThresholds(association_distance=0.1, maximum_observation_gap_s=2.0)
    assert track_smokes([unsupported, anonymous], thresholds).events == []
    diagnostics = track_smokes([unsupported, anonymous], thresholds).diagnostics
    assert [item["reason"] for item in diagnostics] == ["unsupported_agent", "unsupported_agent"]
    assert len(
        track_smokes([unsupported], thresholds, supported_agents=frozenset({"omen"})).events
    ) == 1

    first = candidate(1.0, 0.2, agent="omen")
    other_reference = EvidenceRef(
        match_id="m1", map_id="map1", round_id="r2", vod_timestamp_s=2.0,
        source=EvidenceSource.MINIMAP, confidence=0.9,
    )
    second = SmokeCandidate(
        match_id="m1", map_id="map1", round_id="r2", vod_timestamp_s=2.0,
        center=NormalizedPoint(x=0.2, y=0.5), approximate_radius=0.1,
        agent_type="omen", source=EvidenceSource.MINIMAP, confidence=0.9,
        evidence=[other_reference], live_visible=True,
    )
    result = track_smokes(
        [first, second],
        SmokeTrackingThresholds(association_distance=0.1, maximum_observation_gap_s=2.0),
        supported_agents=frozenset({"omen"}),
    )
    assert len(result.events) == 2


def test_anonymous_smokes_track_without_attribution_and_keep_overlap_evidence():
    thresholds = SmokeTrackingThresholds(
        association_distance=0.1, maximum_observation_gap_s=2.0,
        disappearance_confirmation_frames=2,
    )
    result = track_anonymous_smokes(
        [candidate(1.0, 0.2), candidate(2.0, 0.2), candidate(1.5, 0.35)],
        thresholds,
        region_observations=[region(3.0, 0.2), region(4.0, 0.2)],
    )
    assert len(result.events) == 2
    assert result.events[0].agent_type is None
    assert result.events[0].appeared_at_s == 1.0
    assert result.events[0].last_seen_at_s == 2.0
    assert result.events[0].disappeared_at_s == 4.0
    assert result.events[0].confidence == 0.8
    assert len(result.events[0].evidence) == 4
    assert result.events[0].overlaps_event_ids == [result.events[1].event_id]


def test_anonymous_path_rejects_known_agent_instead_of_promoting_it():
    result = track_anonymous_smokes(
        [candidate(1.0, 0.2, agent="omen")],
        SmokeTrackingThresholds(association_distance=0.1, maximum_observation_gap_s=2.0),
    )
    assert result.events == []
    assert result.diagnostics == [{"reason": "known_agent_not_anonymous", "timestamp_s": 1.0}]


def test_region_contract_rejects_evidence_with_different_timestamp():
    reference = EvidenceRef(
        match_id="m1", map_id="map1", round_id="r1", vod_timestamp_s=1.0,
        source=EvidenceSource.MINIMAP, confidence=0.8,
    )
    with pytest.raises(ValueError, match="evidence timestamp must match"):
        SmokeRegionObservation(
            match_id="m1", map_id="map1", round_id="r1", vod_timestamp_s=2.0,
            center=NormalizedPoint(x=0.2, y=0.5), approximate_radius=0.2,
            state=SmokeRegionState.CLEAR, live_visible=True, fully_observable=True,
            confidence=0.8, evidence=[reference],
        )


def test_region_clear_requires_full_live_clear_and_never_crosses_scope_or_gaps():
    thresholds = SmokeTrackingThresholds(
        association_distance=0.1, maximum_observation_gap_s=2.0,
        disappearance_confirmation_frames=2,
    )
    cases = [
        [region(2.0, 0.2, visible=False), region(3.0, 0.2)],
        [region(2.0, 0.2, observable=False), region(3.0, 0.2)],
        [region(2.0, 0.2, radius=0.05), region(3.0, 0.2, radius=0.05)],
        [region(2.0, 0.2, state=SmokeRegionState.UNKNOWN), region(3.0, 0.2)],
        [region(2.0, 0.2, scope="r2"), region(3.0, 0.2, scope="r2")],
        [region(2.0, 0.2), region(5.0, 0.2)],
    ]
    for observations in cases:
        result = track_anonymous_smokes([candidate(1.0, 0.2)], thresholds,
                                        region_observations=observations)
        assert result.events[0].disappeared_at_s is None


def test_region_clear_cannot_override_same_timestamp_candidate_presence():
    thresholds = SmokeTrackingThresholds(
        association_distance=0.1, maximum_observation_gap_s=2.0,
        disappearance_confirmation_frames=2,
    )
    presence = SmokeFrameObservation(
        match_id="m1", map_id="map1", round_id="r1", vod_timestamp_s=2.0,
        evidence=[candidate(2.0, 0.2).evidence[0]], live_visible=True,
        active_region_clear=False, candidates=[candidate(2.0, 0.2)],
    )
    result = track_anonymous_smokes(
        [candidate(1.0, 0.2)], thresholds,
        frame_observations=[presence],
        region_observations=[region(2.0, 0.2), region(3.0, 0.2)],
    )
    assert result.events[0].disappeared_at_s is None


def test_region_clear_cannot_override_occupancy_and_clears_only_covered_smoke():
    thresholds = SmokeTrackingThresholds(
        association_distance=0.1, maximum_observation_gap_s=2.0,
        disappearance_confirmation_frames=2,
    )
    candidates = [candidate(1.0, 0.2), candidate(1.0, 0.65)]
    observations = [
        region(2.0, 0.2, state=SmokeRegionState.OCCUPIED),
        region(3.0, 0.2),
        region(4.0, 0.2),
    ]
    result = track_anonymous_smokes(candidates, thresholds, region_observations=observations)
    assert [event.disappeared_at_s for event in result.events] == [4.0, None]


def frame(
    timestamp: float,
    *,
    candidates: list[SmokeCandidate] | None = None,
    visible: bool = True,
    clear: bool = True,
    scope: str = "r1",
) -> SmokeFrameObservation:
    return SmokeFrameObservation(
        match_id="m1", map_id="map1", round_id=scope, vod_timestamp_s=timestamp,
        evidence=[EvidenceRef(
            match_id="m1", map_id="map1", round_id=scope, vod_timestamp_s=timestamp,
            source=EvidenceSource.MINIMAP, confidence=0.8,
        )],
        live_visible=visible, active_region_clear=clear, candidates=candidates or [],
    )


def anonymous_thresholds() -> SmokeTrackingThresholds:
    return SmokeTrackingThresholds(
        association_distance=0.1, maximum_observation_gap_s=2.0,
        disappearance_confirmation_frames=2,
    )


def test_anonymous_confirmation_is_anchored_to_last_presence_and_distinct_times():
    event = track_anonymous_smokes(
        [candidate(1.0, 0.2)], anonymous_thresholds(),
        frame_observations=[frame(10.0), frame(10.0), frame(11.0)],
    ).events[0]
    assert event.disappeared_at_s is None

    event = track_anonymous_smokes(
        [candidate(1.0, 0.2)], anonymous_thresholds(),
        region_observations=[region(2.0, 0.2), region(10.0, 0.2), region(11.0, 0.2)],
    ).events[0]
    assert event.disappeared_at_s is None


def test_anonymous_frame_clear_is_vetoed_by_same_time_occupied_region():
    for frame_clears in ([frame(2.0), frame(3.0)], [frame(3.0), frame(2.0)]):
        event = track_anonymous_smokes(
            [candidate(1.0, 0.2)], anonymous_thresholds(),
            frame_observations=frame_clears,
            region_observations=[region(2.0, 0.2, state=SmokeRegionState.OCCUPIED)],
        ).events[0]
        assert event.disappeared_at_s is None


def test_anonymous_region_streak_resets_for_hidden_unknown_and_presence_frames():
    for obstructing_frame in (
        frame(2.5, candidates=[candidate(2.5, 0.2)], visible=False, clear=False),
        frame(2.5, candidates=[candidate(2.5, 0.2)], clear=False),
    ):
        event = track_anonymous_smokes(
            [candidate(1.0, 0.2)], anonymous_thresholds(),
            frame_observations=[obstructing_frame],
            region_observations=[region(2.0, 0.2), region(3.0, 0.2)],
        ).events[0]
        assert event.disappeared_at_s is None


def test_anonymous_hidden_frame_vetoes_globally_even_with_unrelated_candidate():
    hidden_unrelated = frame(
        2.5, candidates=[candidate(2.5, 0.8)], visible=False, clear=False
    )
    event = track_anonymous_smokes(
        [candidate(1.0, 0.2)], anonymous_thresholds(),
        frame_observations=[frame(2.0), frame(3.0), hidden_unrelated],
    ).events[0]
    assert event.disappeared_at_s is None


def test_anonymous_hidden_frame_does_not_advance_continuity_anchor():
    event = track_anonymous_smokes(
        [candidate(1.0, 0.2)], anonymous_thresholds(),
        frame_observations=[
            frame(10.0, visible=False, clear=False), frame(11.0), frame(12.0),
        ],
    ).events[0]
    assert event.disappeared_at_s is None


def test_anonymous_unknown_region_does_not_advance_continuity_anchor():
    event = track_anonymous_smokes(
        [candidate(1.0, 0.2)], anonymous_thresholds(),
        region_observations=[
            region(10.0, 0.2, state=SmokeRegionState.UNKNOWN),
            region(11.0, 0.2), region(12.0, 0.2),
        ],
    ).events[0]
    assert event.disappeared_at_s is None


def test_anonymous_accepted_clears_advance_continuity_anchor():
    two_clear_thresholds = anonymous_thresholds()
    event = track_anonymous_smokes(
        [candidate(1.0, 0.2)], two_clear_thresholds,
        frame_observations=[frame(2.0), frame(3.5)],
    ).events[0]
    assert event.disappeared_at_s == 3.5

    three_clear_thresholds = SmokeTrackingThresholds(
        association_distance=0.1, maximum_observation_gap_s=2.0,
        disappearance_confirmation_frames=3,
    )
    event = track_anonymous_smokes(
        [candidate(1.0, 0.2)], three_clear_thresholds,
        frame_observations=[frame(2.0), frame(3.0), frame(4.0)],
    ).events[0]
    assert event.disappeared_at_s == 4.0


def test_anonymous_disconnected_far_gap_clear_does_not_seed_restart():
    event = track_anonymous_smokes(
        [candidate(1.0, 0.2)], anonymous_thresholds(),
        frame_observations=[frame(10.0), frame(11.0), frame(12.0)],
    ).events[0]
    assert event.disappeared_at_s is None


def test_anonymous_frame_presence_vetoes_region_clear_at_same_time():
    occupied = frame(2.0, candidates=[candidate(2.0, 0.2)], clear=False)
    event = track_anonymous_smokes(
        [candidate(1.0, 0.2)], anonymous_thresholds(),
        frame_observations=[occupied],
        region_observations=[region(2.0, 0.2), region(3.0, 0.2)],
    ).events[0]
    assert event.disappeared_at_s is None


def test_anonymous_duplicate_region_timestamp_counts_once_and_irrelevant_scope_is_ignored():
    event = track_anonymous_smokes(
        [candidate(1.0, 0.2)], anonymous_thresholds(),
        frame_observations=[frame(2.0, scope="other")],
        region_observations=[region(2.0, 0.2), region(2.0, 0.2), region(3.0, 0.2, scope="other")],
    ).events[0]
    assert event.disappeared_at_s is None


def test_anonymous_region_clear_covers_all_retained_candidate_discs():
    candidates = [candidate(1.0, 0.2), candidate(1.5, 0.28)]
    event = track_anonymous_smokes(
        candidates, anonymous_thresholds(),
        region_observations=[region(2.0, 0.2, radius=0.15), region(3.0, 0.2, radius=0.15)],
    ).events[0]
    assert event.disappeared_at_s is None

    event = track_anonymous_smokes(
        candidates, anonymous_thresholds(),
        region_observations=[region(2.0, 0.24, radius=0.2), region(3.0, 0.24, radius=0.2)],
    ).events[0]
    assert event.disappeared_at_s == 3.0


def test_anonymous_presence_checks_all_retained_candidate_discs():
    event = track_anonymous_smokes(
        [candidate(1.0, 0.2), candidate(1.5, 0.28)], anonymous_thresholds(),
        frame_observations=[
            frame(2.0, candidates=[candidate(2.0, 0.28)], clear=False),
            frame(3.0),
        ],
    ).events[0]
    assert event.disappeared_at_s is None


def test_anonymous_event_confidence_includes_region_observation_confidence():
    weak_region = region(2.0, 0.2).model_copy(update={"confidence": 0.1})
    event = track_anonymous_smokes(
        [candidate(1.0, 0.2)], anonymous_thresholds(),
        region_observations=[weak_region, region(3.0, 0.2)],
    ).events[0]
    assert event.disappeared_at_s == 3.0
    assert event.confidence <= 0.1
