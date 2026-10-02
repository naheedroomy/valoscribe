"""Evidence-backed map-zone assignments from observed live track samples."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from valoscribe.maps.config import MapDefinition, MapPolygon
from valoscribe.types.persistent import (
    NormalizedPoint,
    TrackSmoothingInput,
    ZoneTransitionEvent,
)


@dataclass(frozen=True)
class ZoneUpdate:
    """Current derived zone and zero or more boundary events."""

    zone_id: str | None
    events: tuple[ZoneTransitionEvent, ...]
    rejection_reason: str | None = None


@dataclass(frozen=True)
class _PreviousZone:
    round_id: str
    zone_id: str


class ZoneTransitionTracker:
    """Apply validated map polygons and hysteresis to raw observed positions only."""

    def __init__(self, map_definition: MapDefinition | None) -> None:
        self.map_definition = map_definition
        self._previous: dict[str, _PreviousZone] = {}

    def update(self, sample: TrackSmoothingInput) -> ZoneUpdate:
        """Return zone events for one timestamp; never use predicted/interpolated points."""
        map_definition = self.map_definition
        if map_definition is None:
            self._previous.pop(sample.estimate.player_id, None)
            return ZoneUpdate(None, (), "map_configuration_missing")
        if map_definition.geometry_status != "validated":
            self._previous.pop(sample.estimate.player_id, None)
            return ZoneUpdate(None, (), "map_geometry_pending")
        estimate = sample.estimate
        player_id = estimate.player_id
        if sample.round_id is None:
            self._previous.pop(player_id, None)
            return ZoneUpdate(None, (), "round_context_missing")
        if sample.alive is not True:
            self._previous.pop(player_id, None)
            return ZoneUpdate(None, (), "player_not_confirmed_alive")
        if sample.interval_state != "live":
            self._previous.pop(player_id, None)
            return ZoneUpdate(None, (), f"interval_not_live:{sample.interval_state}")
        if not sample.context_evidence:
            self._previous.pop(player_id, None)
            return ZoneUpdate(None, (), "live_context_evidence_missing")
        if not estimate.observed or estimate.predicted or estimate.position is None:
            self._previous.pop(player_id, None)
            return ZoneUpdate(None, (), "raw_observed_position_missing")
        if estimate.confidence <= 0.0:
            self._previous.pop(player_id, None)
            return ZoneUpdate(None, (), "position_confidence_missing")

        previous = self._previous.get(player_id)
        if previous is not None and previous.round_id != sample.round_id:
            previous = None
        direct_zone = map_definition.zone_at(estimate.position)
        current_zone = direct_zone
        if previous is not None and direct_zone != previous.zone_id:
            previous_polygon = next(
                (
                    zone.polygon
                    for zone in map_definition.named_zones
                    if zone.zone_id == previous.zone_id
                ),
                None,
            )
            if (
                previous_polygon is not None
                and _distance_to_boundary(estimate.position, previous_polygon)
                <= map_definition.zone_hysteresis_distance
            ):
                current_zone = previous.zone_id

        if current_zone is None:
            self._previous.pop(player_id, None)
        else:
            self._previous[player_id] = _PreviousZone(sample.round_id, current_zone)

        transitions: list[tuple[Literal["enter", "leave"], str]] = []
        if previous is None and current_zone is not None:
            transitions.append(("enter", current_zone))
        elif previous is not None and current_zone != previous.zone_id:
            transitions.append(("leave", previous.zone_id))
            if current_zone is not None:
                transitions.append(("enter", current_zone))

        event_evidence = [
            *sample.context_evidence,
            *estimate.evidence,
            f"map_geometry:{map_definition.map_id}:{map_definition.schema_version}",
            "zone_lookup:normalized_point_in_polygon",
        ]
        events = tuple(
            ZoneTransitionEvent(
                map_id=map_definition.map_id,
                map_config_version=map_definition.schema_version,
                player_id=player_id,
                round_id=sample.round_id,
                vod_timestamp_s=estimate.vod_timestamp_s,
                event_type=event_type,
                zone_id=zone_id,
                position=estimate.position,
                confidence=estimate.confidence,
                evidence=event_evidence,
            )
            for event_type, zone_id in transitions
        )
        return ZoneUpdate(current_zone, events)


def _distance_to_boundary(point: NormalizedPoint, polygon: MapPolygon) -> float:
    """Return Euclidean normalized-coordinate distance to polygon boundary."""
    x = point.x
    y = point.y
    distances: list[float] = []
    vertices = polygon.vertices
    for index, first in enumerate(vertices):
        second = vertices[(index + 1) % len(vertices)]
        dx = second.x - first.x
        dy = second.y - first.y
        length_squared = dx * dx + dy * dy
        fraction = (
            0.0
            if length_squared == 0.0
            else max(0.0, min(1.0, ((x - first.x) * dx + (y - first.y) * dy) / length_squared))
        )
        closest_x = first.x + fraction * dx
        closest_y = first.y + fraction * dy
        distances.append(math.hypot(x - closest_x, y - closest_y))
    return min(distances)
