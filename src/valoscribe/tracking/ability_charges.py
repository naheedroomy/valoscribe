"""Extract raw ability charge decreases from consecutive live HUD observations."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Iterable, TypeVar

from valoscribe.types.persistent import (
    AbilityChargeDelta,
    BroadcastInterval,
    BroadcastPhase,
    EvidenceRef,
    EvidenceSource,
    RoundPhase,
)

T = TypeVar("T")


def _unique_context(items: Iterable[tuple[float, T]]) -> tuple[dict[float, T], set[float]]:
    """Keep only unique timestamp context; mark conflicting repeats ambiguous."""
    values: dict[float, T] = {}
    ambiguous: set[float] = set()
    for timestamp, value in items:
        if timestamp in values:
            ambiguous.add(timestamp)
            values.pop(timestamp)
        elif timestamp not in ambiguous:
            values[timestamp] = value
    return values, ambiguous


@dataclass(frozen=True)
class AbilityChargeObservation:
    """One observed charge count with caller-established HUD identity and evidence."""

    match_id: str
    map_id: str
    round_id: str
    player_id: str
    ability_id: str
    agent_id: str
    team_id: str
    vod_timestamp_s: float
    charges: int
    confidence: float
    evidence: EvidenceRef


def extract_ability_charge_deltas(
    observations: list[AbilityChargeObservation],
    broadcast_intervals: list[BroadcastInterval],
    round_phases: list[tuple[float, RoundPhase]],
    *,
    max_gap_s: float,
) -> list[AbilityChargeDelta]:
    """Emit witnessed decreases only when adjacent HUD observations are safe to compare.

    The caller supplies the time bound and all HUD identities. Missing frames,
    rejected broadcast intervals, phase transitions, and uncertain or mis-scoped
    observations break continuity rather than allowing a delta to bridge them.
    """
    if not isfinite(max_gap_s) or max_gap_s < 0:
        raise ValueError("max_gap_s must be finite and nonnegative")
    intervals, ambiguous_intervals = _unique_context(
        ((interval.vod_timestamp_s, interval) for interval in broadcast_intervals)
    )
    phases, ambiguous_phases = _unique_context(round_phases)
    by_stream: dict[tuple[str, str, str, str, str, str, str], list[AbilityChargeObservation]] = {}
    for observation in observations:
        key = (
            observation.match_id,
            observation.map_id,
            observation.round_id,
            observation.player_id,
            observation.ability_id,
            observation.agent_id,
            observation.team_id,
        )
        by_stream.setdefault(key, []).append(observation)

    deltas: list[AbilityChargeDelta] = []
    for key, stream in by_stream.items():
        stream.sort(key=lambda item: item.vod_timestamp_s)
        timestamp_counts: dict[float, int] = {}
        for observation in stream:
            timestamp_counts[observation.vod_timestamp_s] = (
                timestamp_counts.get(observation.vod_timestamp_s, 0) + 1
            )
        duplicate_timestamps = {
            timestamp for timestamp, count in timestamp_counts.items() if count > 1
        }
        previous: AbilityChargeObservation | None = None
        for current in stream:
            if current.vod_timestamp_s in duplicate_timestamps:
                previous = None
                continue
            interval = intervals.get(current.vod_timestamp_s)
            phase = phases.get(current.vod_timestamp_s)
            valid = (
                current.vod_timestamp_s not in ambiguous_intervals
                and current.vod_timestamp_s not in ambiguous_phases
                and interval is not None
                and interval.phase == BroadcastPhase.LIVE
                and interval.rejection_reason is None
                and interval.round_id == current.round_id
                and phase is not None
                and phase not in (
                    RoundPhase.PREROUND,
                    RoundPhase.ROUND_END,
                    RoundPhase.UNKNOWN,
                )
                and current.evidence.source == EvidenceSource.PLAYER_HUD
                and (
                    current.evidence.match_id,
                    current.evidence.map_id,
                    current.evidence.round_id,
                )
                == (current.match_id, current.map_id, current.round_id)
                and current.evidence.vod_timestamp_s == current.vod_timestamp_s
                and current.evidence.confidence > 0
                and current.confidence > 0
            )
            if not valid:
                previous = None
                continue
            if previous is not None:
                intermediate_timestamps = {
                    timestamp
                    for timestamp in (
                        *intervals.keys(), *phases.keys(), *ambiguous_intervals, *ambiguous_phases
                    )
                    if previous.vod_timestamp_s < timestamp < current.vod_timestamp_s
                }
                intermediate_invalid = any(
                    timestamp in ambiguous_intervals
                    or timestamp in ambiguous_phases
                    or (
                        timestamp in intervals
                        and (
                            intervals[timestamp].phase != BroadcastPhase.LIVE
                            or intervals[timestamp].rejection_reason is not None
                            or intervals[timestamp].round_id != current.round_id
                        )
                    )
                    or (
                        timestamp in phases
                        and phases[timestamp]
                        in (RoundPhase.PREROUND, RoundPhase.ROUND_END, RoundPhase.UNKNOWN)
                    )
                    for timestamp in intermediate_timestamps
                )
                prior_interval = intervals.get(previous.vod_timestamp_s)
                prior_phase = phases.get(previous.vod_timestamp_s)
                if (
                    not intermediate_invalid
                    and current.vod_timestamp_s > previous.vod_timestamp_s
                    and current.vod_timestamp_s - previous.vod_timestamp_s <= max_gap_s
                    and previous.vod_timestamp_s not in ambiguous_intervals
                    and previous.vod_timestamp_s not in ambiguous_phases
                    and prior_interval is not None
                    and prior_interval.phase == BroadcastPhase.LIVE
                    and prior_interval.rejection_reason is None
                    and prior_interval.round_id == previous.round_id
                    and prior_phase is not None
                    and prior_phase not in (
                        RoundPhase.PREROUND,
                        RoundPhase.ROUND_END,
                        RoundPhase.UNKNOWN,
                    )
                    and current.charges < previous.charges
                ):
                    timestamp = current.vod_timestamp_s
                    identity = ":".join((*key, str(previous.vod_timestamp_s), str(timestamp)))
                    deltas.append(
                        AbilityChargeDelta(
                            observation_id=f"hud-charge:{identity}",
                            match_id=current.match_id,
                            map_id=current.map_id,
                            round_id=current.round_id,
                            vod_timestamp_s=timestamp,
                            ability_id=current.ability_id,
                            previous_charges=previous.charges,
                            current_charges=current.charges,
                            player_id=current.player_id,
                            agent_id=current.agent_id,
                            team_id=current.team_id,
                            confidence=min(
                                current.confidence,
                                current.evidence.confidence,
                                previous.confidence,
                                previous.evidence.confidence,
                            ),
                            evidence=[current.evidence],
                            previous_evidence=previous.evidence,
                        )
                    )
            previous = current
    return sorted(deltas, key=lambda item: (item.vod_timestamp_s, item.observation_id))
