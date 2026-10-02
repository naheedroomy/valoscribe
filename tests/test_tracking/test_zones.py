from __future__ import annotations

from typing import Literal

from valoscribe.maps.config import MapDefinition, MapPolygon, MapRegistrationThresholds, MapZone
from valoscribe.tracking.zones import ZoneTransitionTracker
from valoscribe.types.persistent import (
    NormalizedPoint,
    PlayerTrackEstimate,
    TrackSmoothingInput,
)


def _polygon(polygon_id: str, vertices: list[tuple[float, float]]) -> MapPolygon:
    return MapPolygon(
        polygon_id=polygon_id,
        vertices=[NormalizedPoint(x=x, y=y) for x, y in vertices],
    )


def _map(zones: list[MapZone], *, hysteresis: float = 0.0) -> MapDefinition:
    return MapDefinition(
        map_id="synthetic-map-v1",
        map_name="Synthetic",
        canonical_minimap={
            "image_url": "https://example.invalid/synthetic.png",
            "sha256": "a" * 64,
            "asset_version": "synthetic-test",
            "patch_version": "not-applicable",
            "provenance": "Synthetic geometry only.",
        },
        geometry_status="validated",
        walkable_areas=[_polygon("walk", [(0, 0), (1, 0), (1, 1), (0, 1)])],
        site_polygons=[_polygon("site", [(0.1, 0.1), (0.3, 0.1), (0.3, 0.3), (0.1, 0.3)])],
        spawn_polygons=[_polygon("spawn", [(0.7, 0.7), (0.9, 0.7), (0.9, 0.9), (0.7, 0.9)])],
        named_zones=zones,
        zone_hysteresis_distance=hysteresis,
        orientation_rules=["Synthetic top-left origin."],
        registration_thresholds=MapRegistrationThresholds(
            minimum_confidence=0.8, maximum_alignment_error=0.02
        ),
    )


def _zone(zone_id: str, vertices: list[tuple[float, float]]) -> MapZone:
    return MapZone(zone_id=zone_id, polygon=_polygon(f"polygon-{zone_id}", vertices))


def _sample(
    timestamp: float,
    x: float | None,
    y: float | None,
    *,
    round_id: str | None = "round-1",
    alive: bool | None = True,
    interval_state: Literal["live", "replay", "paused", "hidden", "unknown"] = "live",
    observed: bool = True,
    predicted: bool = False,
) -> TrackSmoothingInput:
    position = None if x is None or y is None else NormalizedPoint(x=x, y=y)
    estimate = PlayerTrackEstimate(
        player_id="player-1",
        vod_timestamp_s=timestamp,
        source_frame=int(timestamp * 30),
        position=position,
        observed=observed if position is not None else False,
        predicted=predicted if position is not None else False,
        confidence=0.9 if position is not None else 0.0,
        evidence=["synthetic_raw_detection"] if position is not None else ["raw_position_missing"],
        rejection_reason=None if position is not None else "position_missing",
    )
    return TrackSmoothingInput(
        estimate=estimate,
        round_id=round_id,
        alive=alive,
        interval_state=interval_state,
        context_evidence=["synthetic_live_round"],
    )


def test_observed_boundary_crossing_emits_separate_enter_and_leave_events() -> None:
    tracker = ZoneTransitionTracker(
        _map([_zone("site-a", [(0.1, 0.1), (0.4, 0.1), (0.4, 0.4), (0.1, 0.4)])])
    )

    outside = tracker.update(_sample(1.0, 0.05, 0.2))
    entered = tracker.update(_sample(2.0, 0.2, 0.2))
    remained = tracker.update(_sample(3.0, 0.3, 0.3))
    left = tracker.update(_sample(4.0, 0.8, 0.8))

    assert outside.zone_id is None and outside.events == ()
    assert [(event.event_type, event.zone_id) for event in entered.events] == [("enter", "site-a")]
    assert entered.events[0].confidence == 0.9
    assert "synthetic_raw_detection" in entered.events[0].evidence
    assert remained.events == ()
    assert [(event.event_type, event.zone_id) for event in left.events] == [("leave", "site-a")]


def test_near_border_hysteresis_holds_prior_zone_until_clearly_outside() -> None:
    tracker = ZoneTransitionTracker(
        _map(
            [_zone("site-a", [(0.1, 0.1), (0.4, 0.1), (0.4, 0.4), (0.1, 0.4)])],
            hysteresis=0.05,
        )
    )

    entered = tracker.update(_sample(1.0, 0.2, 0.2))
    near_border = tracker.update(_sample(2.0, 0.42, 0.2))
    outside = tracker.update(_sample(3.0, 0.5, 0.2))

    assert [event.event_type for event in entered.events] == ["enter"]
    assert near_border.zone_id == "site-a" and near_border.events == ()
    assert outside.zone_id is None
    assert [(event.event_type, event.zone_id) for event in outside.events] == [("leave", "site-a")]


def test_overlapping_zones_resolve_by_declared_config_order() -> None:
    tracker = ZoneTransitionTracker(
        _map(
            [
                _zone("first", [(0.1, 0.1), (0.6, 0.1), (0.6, 0.6), (0.1, 0.6)]),
                _zone("second", [(0.4, 0.4), (0.9, 0.4), (0.9, 0.9), (0.4, 0.9)]),
            ]
        )
    )

    result = tracker.update(_sample(1.0, 0.5, 0.5))

    assert result.zone_id == "first"
    assert [(event.event_type, event.zone_id) for event in result.events] == [("enter", "first")]


def test_missing_map_or_pending_geometry_produces_no_events() -> None:
    from pathlib import Path

    pending = MapDefinition.model_validate_json(
        (Path(__file__).parents[2] / "src/valoscribe/config/ascent_map.json").read_text(
            encoding="utf-8"
        )
    )

    missing = ZoneTransitionTracker(None).update(_sample(1.0, 0.2, 0.2))
    unresolved = ZoneTransitionTracker(pending).update(_sample(1.0, 0.2, 0.2))

    assert missing.rejection_reason == "map_configuration_missing"
    assert unresolved.rejection_reason == "map_geometry_pending"
    assert missing.events == unresolved.events == ()


def test_missing_position_death_and_replay_reset_state_without_bridging() -> None:
    tracker = ZoneTransitionTracker(
        _map([_zone("site-a", [(0.1, 0.1), (0.4, 0.1), (0.4, 0.4), (0.1, 0.4)])])
    )

    assert tracker.update(_sample(1.0, 0.2, 0.2)).events[0].event_type == "enter"
    no_position = tracker.update(_sample(2.0, None, None))
    assert no_position.rejection_reason == "raw_observed_position_missing"
    assert no_position.events == ()
    assert tracker.update(_sample(3.0, 0.2, 0.2)).events[0].event_type == "enter"

    dead = tracker.update(_sample(4.0, 0.2, 0.2, alive=False))
    assert dead.rejection_reason == "player_not_confirmed_alive"
    replay = tracker.update(_sample(5.0, 0.2, 0.2, interval_state="replay"))
    assert replay.rejection_reason == "interval_not_live:replay"
    after_replay = tracker.update(_sample(6.0, 0.2, 0.2))
    assert [(event.event_type, event.zone_id) for event in after_replay.events] == [
        ("enter", "site-a")
    ]


def test_unobserved_position_does_not_generate_zone_events() -> None:
    tracker = ZoneTransitionTracker(
        _map([_zone("site-a", [(0.1, 0.1), (0.4, 0.1), (0.4, 0.4), (0.1, 0.4)])])
    )

    result = tracker.update(_sample(1.0, 0.2, 0.2, observed=False, predicted=True))

    assert result.rejection_reason == "raw_observed_position_missing"
    assert result.events == ()
