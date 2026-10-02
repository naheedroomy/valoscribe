"""Deterministic smoke lifecycle association; detection remains upstream."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

from valoscribe.maps.config import SmokeTrackingThresholds
from valoscribe.types.persistent import (
    EvidenceRef,
    SmokeCandidate,
    SmokeEvent,
    SmokeFrameObservation,
    SmokeRegionObservation,
    SmokeRegionState,
)


@dataclass(frozen=True)
class SmokeTrackingResult:
    """Smoke events and structured reasons for observations not lifecycle-tracked."""

    events: list[SmokeEvent]
    diagnostics: list[dict[str, str | float]]


def track_smokes(
    candidates: list[SmokeCandidate],
    thresholds: SmokeTrackingThresholds,
    supported_agents: frozenset[str] = frozenset(),
    frame_observations: list[SmokeFrameObservation] | None = None,
) -> SmokeTrackingResult:
    """Track only explicitly supported agents; anonymous candidates stay restricted."""
    return _track_smokes(
        candidates, thresholds, frame_observations, None,
        lambda candidate: candidate.agent_type is not None
        and candidate.agent_type in supported_agents,
        "unsupported_agent",
        anonymous_lifecycle=False,
    )


def track_anonymous_smokes(
    candidates: list[SmokeCandidate],
    thresholds: SmokeTrackingThresholds,
    frame_observations: list[SmokeFrameObservation] | None = None,
    region_observations: list[SmokeRegionObservation] | None = None,
) -> SmokeTrackingResult:
    """Track generic smoke geometry without claiming an agent attribution."""
    return _track_smokes(
        candidates, thresholds, frame_observations, region_observations,
        lambda candidate: candidate.agent_type is None, "known_agent_not_anonymous",
        anonymous_lifecycle=True,
    )


def _track_smokes(
    candidates: list[SmokeCandidate],
    thresholds: SmokeTrackingThresholds,
    frame_observations: list[SmokeFrameObservation] | None,
    region_observations: list[SmokeRegionObservation] | None,
    candidate_is_accepted: Callable[[SmokeCandidate], bool],
    rejected_reason: str,
    anonymous_lifecycle: bool,
) -> SmokeTrackingResult:
    """Shared association and lifecycle logic for supported and anonymous paths."""
    accepted: list[SmokeCandidate] = []
    diagnostics: list[dict[str, str | float]] = []
    for candidate in sorted(candidates, key=lambda item: item.vod_timestamp_s):
        if not candidate.live_visible:
            diagnostics.append(
                {"reason": "not_live_visible", "timestamp_s": candidate.vod_timestamp_s}
            )
            continue
        if not candidate_is_accepted(candidate):
            diagnostics.append(
                {"reason": rejected_reason, "timestamp_s": candidate.vod_timestamp_s}
            )
            continue
        accepted.append(candidate)

    groups: list[list[SmokeCandidate]] = []
    for candidate in accepted:
        possible = [
            group for group in groups
            if group[-1].match_id == candidate.match_id
            and group[-1].map_id == candidate.map_id
            and group[-1].round_id == candidate.round_id
            and group[-1].agent_type == candidate.agent_type
            and candidate.vod_timestamp_s - group[-1].vod_timestamp_s
            <= thresholds.maximum_observation_gap_s
            and math.dist(
                (group[-1].center.x, group[-1].center.y),
                (candidate.center.x, candidate.center.y),
            ) <= thresholds.association_distance
        ]
        if possible:
            min(possible, key=lambda group: group[0].vod_timestamp_s).append(candidate)
        else:
            groups.append([candidate])

    observations = sorted(frame_observations or [], key=lambda item: item.vod_timestamp_s)
    events: list[SmokeEvent] = []
    for index, group in enumerate(groups, start=1):
        first, last = group[0], group[-1]
        if anonymous_lifecycle:
            (
                disappearance_confirmed,
                disappeared_at,
                disappearance_evidence,
                observation_confidences,
            ) = _anonymous_disappearance(
                group, thresholds, frame_observations or [], region_observations or [],
                diagnostics,
            )
        else:
            disappearance_confirmed = False
            disappeared_at = None
            disappearance_evidence = []
            observation_confidences = []
            clear_observations: list[SmokeFrameObservation] = []
            for observation in observations:
                if (observation.match_id, observation.map_id, observation.round_id) != (
                    first.match_id, first.map_id, first.round_id
                ):
                    continue
                if observation.vod_timestamp_s <= last.vod_timestamp_s:
                    continue
                if any(
                    math.dist(
                        (first.center.x, first.center.y),
                        (candidate.center.x, candidate.center.y),
                    ) <= first.approximate_radius + candidate.approximate_radius
                    for candidate in observation.candidates
                ):
                    clear_observations = []
                    continue
                if not observation.live_visible:
                    diagnostics.append(
                        {"reason": "not_live_visible", "timestamp_s": observation.vod_timestamp_s}
                    )
                    continue
                if not observation.active_region_clear:
                    clear_observations = []
                    continue
                if (
                    clear_observations
                    and observation.vod_timestamp_s - clear_observations[-1].vod_timestamp_s
                    > thresholds.maximum_observation_gap_s
                ):
                    clear_observations = []
                clear_observations.append(observation)
                if len(clear_observations) >= thresholds.disappearance_confirmation_frames:
                    break
            disappearance_confirmed = (
                len(clear_observations) >= thresholds.disappearance_confirmation_frames
            )
            disappeared_at = (
                clear_observations[-1].vod_timestamp_s if disappearance_confirmed else None
            )
            disappearance_evidence = [
                reference
                for observation in clear_observations if observation.live_visible
                for reference in observation.evidence
            ] if disappearance_confirmed else []
            if not disappearance_confirmed:
                region_clears: list[SmokeRegionObservation] = []
                for region_observation in sorted(
                    region_observations or [], key=lambda item: item.vod_timestamp_s
                ):
                    if (
                        region_observation.match_id,
                        region_observation.map_id,
                        region_observation.round_id,
                    ) != (first.match_id, first.map_id, first.round_id) or (
                        region_observation.vod_timestamp_s <= last.vod_timestamp_s
                    ):
                        continue
                    distance = math.dist(
                        (first.center.x, first.center.y),
                        (region_observation.center.x, region_observation.center.y),
                    )
                    if distance > first.approximate_radius + region_observation.approximate_radius:
                        continue
                    covers_tracked_region = region_observation.approximate_radius >= (
                        distance + max(item.approximate_radius for item in group)
                    )
                    contradictory_presence = any(
                        frame.match_id == region_observation.match_id
                        and frame.map_id == region_observation.map_id
                        and frame.round_id == region_observation.round_id
                        and frame.vod_timestamp_s == region_observation.vod_timestamp_s
                        and any(
                            math.dist(
                                (first.center.x, first.center.y),
                                (candidate.center.x, candidate.center.y),
                            ) <= max(item.approximate_radius for item in group)
                            + candidate.approximate_radius
                            for candidate in frame.candidates
                        )
                        for frame in frame_observations or []
                    )
                    if (
                        not region_observation.live_visible
                        or not region_observation.fully_observable
                        or not covers_tracked_region
                        or region_observation.state != SmokeRegionState.CLEAR
                        or contradictory_presence
                    ):
                        region_clears = []
                        continue
                    previous_timestamp = (
                        region_clears[-1].vod_timestamp_s if region_clears
                        else last.vod_timestamp_s
                    )
                    if (
                        region_observation.vod_timestamp_s - previous_timestamp
                        > thresholds.maximum_observation_gap_s
                    ):
                        region_clears = []
                    region_clears.append(region_observation)
                    if len(region_clears) >= thresholds.disappearance_confirmation_frames:
                        disappearance_confirmed = True
                        disappeared_at = region_observation.vod_timestamp_s
                        disappearance_evidence = [
                            reference for clear in region_clears for reference in clear.evidence
                        ]
                        break
        events.append(SmokeEvent(
            event_id=f"{first.round_id}-smoke-{index}",
            match_id=first.match_id,
            map_id=first.map_id,
            round_id=first.round_id,
            center=first.center,
            approximate_radius=max(item.approximate_radius for item in group),
            agent_type=(
                first.agent_type
                if all(item.agent_type == first.agent_type for item in group)
                else None
            ),
            appeared_at_s=first.vod_timestamp_s,
            last_seen_at_s=last.vod_timestamp_s,
            disappeared_at_s=disappeared_at,
            active_windows=[[first.vod_timestamp_s, last.vod_timestamp_s]],
            confidence=min(
                [item.confidence for item in group]
                + observation_confidences
                + [reference.confidence for reference in disappearance_evidence]
            ),
            evidence=[reference for item in group for reference in item.evidence]
            + disappearance_evidence,
        ))
    for event in events:
        event.overlaps_event_ids.extend(
            other.event_id for other in events
            if other is not event and _circles_overlap(event, other)
            and event.appeared_at_s <= other.last_seen_at_s
            and other.appeared_at_s <= event.last_seen_at_s
        )
    return SmokeTrackingResult(events=events, diagnostics=diagnostics)


def _anonymous_disappearance(
    group: list[SmokeCandidate],
    thresholds: SmokeTrackingThresholds,
    frames: list[SmokeFrameObservation],
    regions: list[SmokeRegionObservation],
    diagnostics: list[dict[str, str | float]],
) -> tuple[bool, float | None, list[EvidenceRef], list[float]]:
    """Confirm anonymous disappearance from one timestamp-batched evidence stream."""
    first, last = group[0], group[-1]
    geometry = [(item.center.x, item.center.y, item.approximate_radius) for item in group]
    records: dict[float, list[SmokeFrameObservation | SmokeRegionObservation]] = {}
    for observation in frames:
        if (observation.match_id, observation.map_id, observation.round_id) != (
            first.match_id, first.map_id, first.round_id
        ) or observation.vod_timestamp_s <= last.vod_timestamp_s:
            continue
        records.setdefault(observation.vod_timestamp_s, []).append(observation)
    for region_item in regions:
        if (region_item.match_id, region_item.map_id, region_item.round_id) != (
            first.match_id, first.map_id, first.round_id
        ) or region_item.vod_timestamp_s <= last.vod_timestamp_s:
            continue
        if not any(
            math.dist((region_item.center.x, region_item.center.y), (x, y))
            <= radius + region_item.approximate_radius
            for x, y, radius in geometry
        ):
            continue
        records.setdefault(region_item.vod_timestamp_s, []).append(region_item)

    clear_streak: list[
        tuple[float, list[SmokeRegionObservation | SmokeFrameObservation]]
    ] = []
    # This is the latest accepted presence or continuous clear, never an unknown/hidden time.
    continuity_anchor = last.vod_timestamp_s
    for timestamp in sorted(records):
        batch = records[timestamp]
        scoped_frames = [
            item for item in batch if isinstance(item, SmokeFrameObservation)
        ]
        # Visibility is a scoped, global veto; unrelated candidate geometry cannot hide it.
        hidden_frame = any(not item.live_visible for item in scoped_frames)
        relevant_frames = [
            item for item in batch
            if isinstance(item, SmokeFrameObservation)
            and (
                not item.candidates
                or any(
                    math.dist((x, y), (candidate.center.x, candidate.center.y))
                    <= radius + candidate.approximate_radius
                    for candidate in item.candidates for x, y, radius in geometry
                )
            )
        ]
        relevant_regions = [item for item in batch if isinstance(item, SmokeRegionObservation)]
        if hidden_frame or any(not item.live_visible for item in relevant_regions):
            diagnostics.extend(
                {"reason": "not_live_visible", "timestamp_s": timestamp}
                for item in scoped_frames + relevant_regions if not item.live_visible
            )
        frame_presence = any(
            any(
                math.dist((x, y), (candidate.center.x, candidate.center.y))
                <= radius + candidate.approximate_radius
                for x, y, radius in geometry
            )
            for frame in relevant_frames for candidate in frame.candidates
        )
        region_presence = any(
            item.state == SmokeRegionState.OCCUPIED for item in relevant_regions
        )
        unusable_frame = any(
            not item.live_visible or not item.active_region_clear
            for item in relevant_frames
        )
        unusable_region = any(
            not item.live_visible or not item.fully_observable
            or item.state != SmokeRegionState.CLEAR
            or not all(
                math.dist((item.center.x, item.center.y), (x, y)) + radius
                <= item.approximate_radius
                for x, y, radius in geometry
            )
            for item in relevant_regions
        )
        usable_clears = [
            item for item in relevant_frames
            if item.live_visible and item.active_region_clear and not item.candidates
        ] + [
            item for item in relevant_regions
            if item.live_visible and item.fully_observable
            and item.state == SmokeRegionState.CLEAR
            and all(
                math.dist((item.center.x, item.center.y), (x, y)) + radius
                <= item.approximate_radius
                for x, y, radius in geometry
            )
        ]
        if hidden_frame or any(not item.live_visible for item in relevant_regions):
            clear_streak = []
            continue
        if frame_presence or region_presence:
            clear_streak = []
            continuity_anchor = timestamp
            continue
        if unusable_frame or unusable_region:
            clear_streak = []
            continue
        if not usable_clears:
            continue
        if timestamp - continuity_anchor > thresholds.maximum_observation_gap_s:
            # A disconnected clear cannot establish a fresh continuity chain.
            clear_streak = []
            continue
        # A timestamp batch contributes one confirmation, regardless of record count.
        clear_streak.append((timestamp, usable_clears))
        # Only an accepted clear advances continuity; vetoes preserve the last anchor.
        continuity_anchor = timestamp
        if len(clear_streak) >= thresholds.disappearance_confirmation_frames:
            confirmation_records = [
                item for _, timestamp_records in clear_streak for item in timestamp_records
            ]
            evidence = [ref for item in confirmation_records for ref in item.evidence]
            confidences = [
                item.confidence for item in confirmation_records
                if isinstance(item, SmokeRegionObservation)
            ]
            return True, timestamp, evidence, confidences
    return False, None, [], []


def _circles_overlap(first: SmokeEvent, second: SmokeEvent) -> bool:
    return math.dist(
        (first.center.x, first.center.y), (second.center.x, second.center.y)
    ) <= first.approximate_radius + second.approximate_radius
