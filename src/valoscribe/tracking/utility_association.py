"""Associate observed ability charge decreases with spatial utility appearances."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from valoscribe.types.persistent import (
    AbilityChargeDelta,
    SmokeEvent,
    UtilityAssociation,
)


@dataclass(frozen=True)
class UtilityAssociationResult:
    associations: list[UtilityAssociation]
    diagnostics: list[dict[str, str | float]]


def associate_utility(
    charge_deltas: list[AbilityChargeDelta],
    smoke_events: list[SmokeEvent],
    *,
    window_s: float = 3.0,
) -> UtilityAssociationResult:
    """Match each cue to a unique nearby smoke appearance; ambiguous matches fail closed."""
    if not isfinite(window_s) or window_s < 0:
        raise ValueError("window_s must be finite and nonnegative")
    diagnostics: list[dict[str, str | float]] = []
    associations: list[UtilityAssociation] = []
    grouped: dict[tuple[str | None, str | None, str | None, str], list[SmokeEvent]] = {}
    for event in smoke_events:
        key: tuple[str | None, str | None, str | None, str] = (
            event.match_id, event.map_id, event.round_id, event.event_id
        )
        grouped.setdefault(key, []).append(event)

    available: dict[tuple[str | None, str | None, str | None, str], SmokeEvent] = {}
    for key, records in grouped.items():
        first = records[0]
        if any(event != first for event in records[1:]):
            diagnostics.append(
                {"reason": "conflicting_utility_event", "event_id": first.event_id}
            )
            continue
        available[key] = first
        if len(records) > 1:
            diagnostics.append(
                {"reason": "duplicate_utility_event", "event_id": first.event_id}
            )

    ordered = sorted(charge_deltas, key=lambda item: (item.vod_timestamp_s, item.observation_id))
    seen: set[tuple[str | None, str | None, str | None, str]] = set()

    for delta in ordered:
        observation_key = (
            delta.match_id, delta.map_id, delta.round_id, delta.observation_id
        )
        if observation_key in seen:
            diagnostics.append(
                {"reason": "replayed_charge_delta", "observation_id": delta.observation_id}
            )
            continue
        seen.add(observation_key)
        if (
            delta.match_id is None
            or delta.map_id is None
            or delta.round_id is None
            or delta.team_id is None
        ):
            diagnostics.append({"reason": "missing_scope", "observation_id": delta.observation_id})
            continue
        candidates = [
            event
            for event in available.values()
            if (event.match_id, event.map_id, event.round_id)
            == (delta.match_id, delta.map_id, delta.round_id)
            and abs(event.appeared_at_s - delta.vod_timestamp_s) <= window_s
            and (
                delta.agent_id is None
                or event.agent_type is None
                or event.agent_type == delta.agent_id
            )
        ]
        candidates.sort(
            key=lambda event: (
                abs(event.appeared_at_s - delta.vod_timestamp_s),
                event.appeared_at_s,
                event.event_id,
            )
        )
        if not candidates:
            diagnostics.append(
                {"reason": "no_nearby_utility", "observation_id": delta.observation_id}
            )
            continue
        nearest_distance = abs(candidates[0].appeared_at_s - delta.vod_timestamp_s)
        nearest = [
            event
            for event in candidates
            if abs(event.appeared_at_s - delta.vod_timestamp_s) == nearest_distance
        ]
        if len(nearest) != 1:
            diagnostics.append(
                {"reason": "ambiguous_utility", "observation_id": delta.observation_id}
            )
            continue
        event = nearest[0]
        refs = ([delta.previous_evidence] if delta.previous_evidence is not None else [])
        refs.extend(delta.evidence)
        refs.extend(event.evidence)
        associations.append(
            UtilityAssociation(
                schema_version="1.0",
                association_id=f"{delta.observation_id}:{event.event_id}",
                match_id=delta.match_id,
                map_id=delta.map_id,
                round_id=delta.round_id,
                observation_id=delta.observation_id,
                utility_event_id=event.event_id,
                ability_id=delta.ability_id,
                player_id=delta.player_id,
                team_id=delta.team_id,
                observed=False,
                confidence=min(
                    delta.confidence,
                    event.confidence,
                    *(ref.confidence for ref in refs),
                ),
                evidence=refs,
                diagnostic=(
                    "multiple_nearby_candidates" if len(candidates) > 1
                    else "temporal_proximity_only"
                ),
            )
        )
        del available[(event.match_id, event.map_id, event.round_id, event.event_id)]
    return UtilityAssociationResult(associations, diagnostics)
