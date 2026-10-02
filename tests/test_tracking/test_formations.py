"""Synthetic formation policy and classification tests."""

from __future__ import annotations

from valoscribe.analytics.formations import DeterministicFormationEngine
from valoscribe.maps.config import (
    FormationPolicy,
    MapDefinition,
    MapPolygon,
    MapRegistrationThresholds,
    MapZone,
)
from valoscribe.types.persistent import FormationLabel, FormationObservation, NormalizedPoint


def make_map() -> MapDefinition:
    zones = []
    for index in range(5):
        x = index / 5
        polygon = MapPolygon(
            polygon_id=f"p{index}",
            vertices=[
                NormalizedPoint(x=x, y=0),
                NormalizedPoint(x=x + 0.2, y=0),
                NormalizedPoint(x=x + 0.2, y=1),
                NormalizedPoint(x=x, y=1),
            ],
        )
        zones.append(MapZone(zone_id=f"z{index}", polygon=polygon))
    return MapDefinition(
        map_id="synthetic",
        map_name="Synthetic",
        canonical_minimap={
            "image_url": "https://example.invalid/map",
            "sha256": "a" * 64,
            "asset_version": "synthetic",
            "provenance": "synthetic only",
        },
        geometry_status="validated",
        walkable_areas=[zones[0].polygon],
        site_polygons=[zones[0].polygon],
        spawn_polygons=[zones[-1].polygon],
        named_zones=zones,
        orientation_rules=["synthetic"],
        registration_thresholds=MapRegistrationThresholds(
            minimum_confidence=0.8, maximum_alignment_error=0.1
        ),
        formation_policy=FormationPolicy(
            group_distance=0.08,
            split_distance=0.2,
            spread_distance=0.4,
            site_stack_minimum=3,
            site_zone_ids=["z0"],
            lane_zone_ids=[f"z{i}" for i in range(5)],
        ),
    )


def observation(
    xs: list[float], spike: float | None = None, conflict: bool = False
) -> FormationObservation:
    return FormationObservation(
        match_id="m",
        map_id="synthetic",
        round_id="r",
        team_id="t",
        vod_timestamp_s=1,
        players=[
            {
                "player_id": str(i),
                "position": {"x": x, "y": 0.5},
                "confidence": 1,
                "evidence": [f"player:{i}"],
            }
            for i, x in enumerate(xs)
        ],
        spike_position=None if spike is None else NormalizedPoint(x=spike, y=0.5),
        spike_evidence=[] if spike is None else ["spike:observed"],
        conflicting_signals=["conflict"] if conflict else [],
    )


def test_all_formation_labels_and_permutation_invariance() -> None:
    from itertools import permutations

    engine = DeterministicFormationEngine(make_map())
    fixtures = [
        ([0.10, 0.11, 0.12, 0.13, 0.14], FormationLabel.FIVE_MAN_GROUP),
        ([0.10, 0.11, 0.12, 0.13, 0.80], FormationLabel.FOUR_ONE_LURK),
        ([0.10, 0.11, 0.12, 0.70, 0.71], FormationLabel.THREE_TWO_SPLIT),
        ([0.10, 0.11, 0.60, 0.61, 0.95], FormationLabel.TWO_ONE_TWO_DEFAULT),
        ([0.10, 0.11, 0.12, 0.60, 0.95], FormationLabel.THREE_ONE_ONE_DEFAULT),
        ([0.05, 0.30, 0.55, 0.80, 0.95], FormationLabel.SPREAD_DEFAULT),
    ]
    for xs, expected in fixtures:
        baseline = engine.observe(observation(xs))
        assert baseline.formation == expected
        for order in permutations(range(5)):
            candidate = engine.observe(observation([xs[i] for i in order]))
            assert candidate.formation == expected
    assert len(engine.observe(observation(fixtures[0][0])).pairwise_distances) == 10
    unresolved = engine.observe(observation([0.1, 0.2, 0.4, 0.7, 0.9], conflict=True))
    assert unresolved.formation == FormationLabel.UNKNOWN_FORMATION


def test_threshold_boundaries_and_missing_spike_evidence() -> None:
    engine = DeterministicFormationEngine(make_map())
    # Spread separation is evaluated against the configured cutoff.
    spread = engine.observe(observation([0.05, 0.30, 0.55, 0.80, 0.95]))
    assert spread.formation == FormationLabel.SPREAD_DEFAULT
    missing_evidence = observation([0.01, 0.04, 0.07, 0.4, 0.8], spike=0.02)
    missing_evidence = missing_evidence.model_copy(update={"spike_evidence": []})
    result = engine.observe(missing_evidence)
    assert result.formation == FormationLabel.UNKNOWN_FORMATION
    assert "spike_evidence_missing" in result.diagnostics


def test_stack_requires_spike_in_site_and_configured_occupancy() -> None:
    result = DeterministicFormationEngine(make_map()).observe(
        observation([0.01, 0.04, 0.07, 0.4, 0.8], spike=0.02)
    )
    assert result.formation == FormationLabel.SITE_STACK
    assert result.spike_zone_id == "z0"


def test_incomplete_or_conflicting_snapshots_fail_closed() -> None:
    engine = DeterministicFormationEngine(make_map())
    partial = observation([0.1, 0.2, 0.3, 0.4])
    conflict = engine.observe(observation([0.1, 0.2, 0.3, 0.4, 0.5], conflict=True))
    assert engine.observe(partial).formation == FormationLabel.UNKNOWN_FORMATION
    assert conflict.formation == FormationLabel.UNKNOWN_FORMATION
    assert conflict.confidence == 0


def test_missing_policy_fails_closed() -> None:
    map_config = make_map().model_copy(update={"formation_policy": None})
    result = DeterministicFormationEngine(map_config).observe(
        observation([0.1, 0.2, 0.3, 0.4, 0.5])
    )
    assert result.formation == FormationLabel.UNKNOWN_FORMATION
    assert "formation_policy_missing" in result.diagnostics
