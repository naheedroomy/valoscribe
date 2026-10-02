import pytest

from valoscribe.tracking.utility_association import associate_utility
from valoscribe.types.persistent import (
    AbilityChargeDelta,
    EvidenceRef,
    EvidenceSource,
    NormalizedPoint,
    SmokeEvent,
)


def reference(
    timestamp: float,
    source: EvidenceSource = EvidenceSource.PLAYER_HUD,
    *,
    match_id: str = "m",
    map_id: str = "map",
    round_id: str = "r",
    confidence: float = 0.9,
):
    return EvidenceRef(
        match_id=match_id,
        map_id=map_id,
        round_id=round_id,
        vod_timestamp_s=timestamp,
        source=source,
        confidence=confidence,
    )


def delta(timestamp: float, observation_id: str = "charge", **kwargs):
    values = {
        "observation_id": observation_id,
        "match_id": "m",
        "map_id": "map",
        "round_id": "r",
        "vod_timestamp_s": timestamp,
        "ability_id": "caller-supplied-ability",
        "previous_charges": 2,
        "current_charges": 1,
        "player_id": "caller-supplied-player",
        "team_id": "team",
        "confidence": 0.9,
        "evidence": [
            reference(timestamp)
            if kwargs.get("match_id", "m") is None
            else reference(
                timestamp,
                match_id=kwargs.get("match_id", "m"),
                map_id=kwargs.get("map_id", "map"),
                round_id=kwargs.get("round_id", "r"),
            )
        ],
    }
    values.update(kwargs)
    return AbilityChargeDelta(**values)


def smoke(event_id: str, timestamp: float, agent: str | None = None, **kwargs):
    values = {
        "event_id": event_id,
        "match_id": "m",
        "map_id": "map",
        "round_id": "r",
        "center": NormalizedPoint(x=0.5, y=0.5),
        "approximate_radius": 0.1,
        "agent_type": agent,
        "appeared_at_s": timestamp,
        "last_seen_at_s": timestamp,
        "active_windows": [[timestamp, timestamp]],
        "confidence": 0.8,
        "evidence": [
            reference(
                timestamp,
                EvidenceSource.MINIMAP,
                match_id=kwargs.get("match_id", "m"),
                map_id=kwargs.get("map_id", "map"),
                round_id=kwargs.get("round_id", "r"),
            )
        ],
    }
    values.update(kwargs)
    return SmokeEvent(**values)


def test_matches_nearest_in_scope_and_includes_both_evidence_sources():
    result = associate_utility([delta(10)], [smoke("far", 11), smoke("near", 10.5)], window_s=2)
    assert len(result.associations) == 1
    association = result.associations[0]
    assert association.utility_event_id == "near"
    assert association.observed is False
    assert association.diagnostic == "multiple_nearby_candidates"
    assert {ref.source for ref in association.evidence} == {
        EvidenceSource.PLAYER_HUD,
        EvidenceSource.MINIMAP,
    }


def test_ambiguous_tie_fails_closed_and_events_cannot_be_reused():
    tied = associate_utility([delta(10)], [smoke("a", 9), smoke("b", 11)])
    assert tied.associations == []
    assert tied.diagnostics[0]["reason"] == "ambiguous_utility"
    matched = associate_utility([delta(10, "one"), delta(10, "two")], [smoke("only", 10)])
    assert len(matched.associations) == 1
    assert matched.diagnostics[0]["reason"] == "no_nearby_utility"


def test_round_mismatch_replay_and_missing_scope_fail_closed():
    replay = associate_utility([delta(10), delta(10)], [smoke("s", 10)])
    assert len(replay.associations) == 1
    assert replay.diagnostics[0]["reason"] == "replayed_charge_delta"
    no_scope = delta(
        10, "unscoped", match_id=None, map_id=None, round_id=None, evidence=[reference(10)]
    )
    result = associate_utility([no_scope], [smoke("s", 10)])
    assert result.associations == []
    assert result.diagnostics[0]["reason"] == "missing_scope"


def test_charge_delta_contract_requires_decrease_and_matching_evidence():
    with pytest.raises(ValueError, match="must represent a decrease"):
        delta(10, current_charges=2)
    with pytest.raises(ValueError, match="timestamp must match"):
        delta(10, evidence=[reference(9)])


def test_window_must_be_finite_and_nonnegative():
    for window in (float("nan"), float("inf"), float("-inf"), -0.1):
        with pytest.raises(ValueError, match="finite and nonnegative"):
            associate_utility([], [], window_s=window)


def test_scoped_ids_allow_same_local_ids_in_distinct_matches():
    first_delta = delta(10, match_id="match-1")
    second_delta = delta(10, match_id="match-2")
    first_smoke = smoke("same-event", 10, match_id="match-1")
    second_smoke = smoke("same-event", 10, match_id="match-2")

    result = associate_utility([first_delta, second_delta], [first_smoke, second_smoke])

    assert len(result.associations) == 2
    assert {item.match_id for item in result.associations} == {"match-1", "match-2"}


def test_duplicate_scoped_utility_event_is_diagnosed_and_not_reused():
    result = associate_utility(
        [delta(10)], [smoke("same-event", 10), smoke("same-event", 10)]
    )

    assert len(result.associations) == 1
    assert result.associations[0].diagnostic == "temporal_proximity_only"
    assert result.diagnostics == [
        {"reason": "duplicate_utility_event", "event_id": "same-event"}
    ]


@pytest.mark.parametrize(
    "low_confidence_source",
    ["delta", "smoke", "current_hud", "spatial", "prior_hud"],
)
def test_unique_exact_time_match_confidence_uses_each_input(
    low_confidence_source: str,
):
    expected_confidence = 0.2
    confidences = {
        "delta": 0.9,
        "smoke": 0.9,
        "current_hud": 0.9,
        "spatial": 0.9,
        "prior_hud": 0.9,
    }
    confidences[low_confidence_source] = expected_confidence
    prior = reference(9.0, confidence=confidences["prior_hud"])
    current = reference(10.0, confidence=confidences["current_hud"])
    spatial = reference(10.0, EvidenceSource.MINIMAP, confidence=confidences["spatial"])
    charge = delta(
        10,
        confidence=confidences["delta"],
        evidence=[current],
        previous_evidence=prior,
    )
    utility = smoke("smoke", 10, confidence=confidences["smoke"], evidence=[spatial])

    result = associate_utility([charge], [utility])

    association = result.associations[0]
    assert association.observed is False
    assert association.diagnostic == "temporal_proximity_only"
    assert association.confidence == expected_confidence
    assert association.evidence == [prior, current, spatial]
    assert association.model_dump(mode="json")["evidence"][0]["vod_timestamp_s"] == 9.0


@pytest.mark.parametrize("include_previous_evidence", [False, True])
def test_prior_evidence_is_optional_and_inputs_are_not_mutated(
    include_previous_evidence: bool,
):
    charge = delta(
        10,
        previous_evidence=reference(9.0) if include_previous_evidence else None,
    )
    utility = smoke("smoke", 10)
    charge_before = charge.model_dump(mode="json")
    utility_before = utility.model_dump(mode="json")

    result = associate_utility([charge], [utility])

    expected_evidence_count = 3 if include_previous_evidence else 2
    assert len(result.associations[0].evidence) == expected_evidence_count
    assert charge.model_dump(mode="json") == charge_before
    assert utility.model_dump(mode="json") == utility_before


def test_conflicting_event_payloads_quarantine_key_in_any_order_and_on_repetition():
    first = smoke("conflict", 10)
    changed = smoke("conflict", 11)
    for events in ([first, changed], [changed, first], [first, changed, first]):
        result = associate_utility([delta(10, "one"), delta(10, "two")], list(events))
        assert result.associations == []
        assert result.diagnostics == [
            {"reason": "conflicting_utility_event", "event_id": "conflict"},
            {"reason": "no_nearby_utility", "observation_id": "one"},
            {"reason": "no_nearby_utility", "observation_id": "two"},
        ]


def test_conflicts_are_scoped_and_identical_duplicates_retain_existing_behavior():
    conflicted = smoke("shared", 10)
    conflict_copy = smoke("shared", 12)
    other_scope = smoke("shared", 10, match_id="other-match")
    identical = smoke("identical", 10)

    result = associate_utility(
        [delta(10, "a"), delta(10, "b", match_id="other-match")],
        [conflicted, conflict_copy, other_scope, identical, smoke("identical", 10)],
    )

    assert {item.match_id for item in result.associations} == {"other-match", "m"}
    assert {item.utility_event_id for item in result.associations} == {"shared", "identical"}
    assert result.diagnostics == [
        {"reason": "conflicting_utility_event", "event_id": "shared"},
        {"reason": "duplicate_utility_event", "event_id": "identical"},
    ]
