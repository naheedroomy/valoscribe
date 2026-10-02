"""Evidence-gated fusion of timestamped round player snapshots."""

from __future__ import annotations

import math
from typing import Literal, cast

from pydantic import Field, field_validator

from valoscribe.types.persistent import (
    AliveState,
    BroadcastInterval,
    BroadcastPhase,
    FusedAliveState,
    NormalizedPoint,
    PersistentModel,
    PlayerTrackEstimate,
)


class RoundSnapshotInput(PersistentModel):
    """Inputs fused at one timestamp; each source remains independently recorded."""

    schema_version: Literal["1.0"] = "1.0"
    match_id: str = Field(min_length=1)
    map_id: str = Field(min_length=1)
    round_id: str = Field(min_length=1)
    vod_timestamp_s: float = Field(ge=0.0)
    round_elapsed_s: float | None = Field(default=None, ge=0.0)
    display_clock_s: float | None = Field(default=None, ge=0.0)
    broadcast: BroadcastInterval
    tracks: list[PlayerTrackEstimate] = Field(default_factory=list)
    alive_states: list[FusedAliveState] = Field(default_factory=list)

    @field_validator("vod_timestamp_s", "round_elapsed_s", "display_clock_s")
    @classmethod
    def times_finite(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("snapshot times must be finite")
        return value


class SnapshotDiagnostic(PersistentModel):
    """Structured conflict retained when snapshot evidence disagrees."""

    schema_version: Literal["1.0"] = "1.0"
    player_id: str = Field(min_length=1)
    code: str = Field(min_length=1)
    evidence: list[str] = Field(min_length=1)
    confidence_attenuation: float = Field(ge=0.0, le=1.0)


class SnapshotPlayer(PersistentModel):
    """Player state included in a fused snapshot."""

    schema_version: Literal["1.0"] = "1.0"
    player_id: str = Field(min_length=1)
    position: NormalizedPoint | None = None
    alive: AliveState
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(min_length=1)
    diagnostics: list[SnapshotDiagnostic] = Field(default_factory=list)


class FusedRoundSnapshot(PersistentModel):
    """Versioned derived state at a single verified live round timestamp."""

    schema_version: Literal["1.0"] = "1.0"
    match_id: str = Field(min_length=1)
    map_id: str = Field(min_length=1)
    round_id: str = Field(min_length=1)
    vod_timestamp_s: float = Field(ge=0.0)
    round_elapsed_s: float | None = Field(default=None, ge=0.0)
    display_clock_s: float | None = Field(default=None, ge=0.0)
    phase: str = "UNKNOWN"
    attacking_team: str = "UNKNOWN"
    defending_team: str = "UNKNOWN"
    spike_state: str = "UNKNOWN"
    players: list[SnapshotPlayer] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(min_length=1)


class RoundSnapshotFusion:
    """Build deterministic snapshots only from confirmed live intervals."""

    def __init__(self, interval_s: float = 0.25) -> None:
        if not math.isfinite(interval_s) or interval_s not in (0.25, 0.5):
            raise ValueError("interval_s must be 0.25 or 0.5")
        self.interval_s = interval_s
        self._last_timestamp: dict[str, float] = {}

        self.rejections: list[str] = []

    def fuse(self, source: RoundSnapshotInput) -> FusedRoundSnapshot | None:
        """Return a snapshot, or record a structured rejection diagnostic."""
        rejection = self._rejection(source)
        if rejection is not None:
            self.rejections.append(f"{source.round_id}@{source.vod_timestamp_s:.6f}:{rejection}")
            return None
        last = self._last_timestamp.get(source.round_id)
        if last is not None and source.vod_timestamp_s <= last:
            self.rejections.append(
                f"{source.round_id}@{source.vod_timestamp_s:.6f}:duplicate_or_out_of_order"
            )
            return None
        interval = source.broadcast
        assert interval.round_id is not None
        round_id = source.round_id
        if last is not None and source.vod_timestamp_s - last + 1e-9 < self.interval_s:
            self.rejections.append(
                f"{round_id}@{source.vod_timestamp_s:.6f}:before_sampling_interval"
            )
            return None
        alive_by_player = {state.player_id: state for state in source.alive_states}
        tracks_by_player = {track.player_id: track for track in source.tracks}
        players: list[SnapshotPlayer] = []
        for player_id in sorted(set(alive_by_player) | set(tracks_by_player)):
            player_state: AliveState
            alive = alive_by_player.get(player_id)
            track = tracks_by_player.get(player_id)
            diagnostics: list[SnapshotDiagnostic] = []
            if (
                alive is not None
                and track is not None
                and alive.state == AliveState.DEAD
                and track.observed
            ):
                player_state = AliveState.UNKNOWN
                confidence = min(alive.confidence, track.confidence) * 0.5
                diagnostics.append(
                    SnapshotDiagnostic(
                        player_id=player_id,
                        code="dead_state_conflicts_with_observed_position",
                        evidence=list(dict.fromkeys([*alive.evidence, *track.evidence])),
                        confidence_attenuation=0.5,
                    )
                )
            elif alive is not None and track is not None and alive.state != AliveState.UNKNOWN:
                player_state = alive.state
                confidence = min(alive.confidence, track.confidence)
            elif alive is not None:
                player_state = cast(AliveState, alive.state)
                confidence = alive.confidence
            else:
                player_state = AliveState.UNKNOWN
                confidence = 0.0
            evidence = [*interval.evidence]
            if track is not None:
                evidence.extend(track.evidence)
            if alive is not None:
                evidence.extend(alive.evidence)
            position = (
                track.position
                if track is not None
                and track.observed
                and not (
                    alive is not None
                    and alive.state == AliveState.DEAD
                    and track.observed
                )
                else None
            )
            players.append(
                SnapshotPlayer(
                    player_id=player_id,
                    position=position,
                    alive=player_state,
                    confidence=confidence,
                    evidence=list(dict.fromkeys(evidence)),
                    diagnostics=diagnostics,
                )
            )
        confidence = min([interval.confidence, *(player.confidence for player in players)])
        self._last_timestamp[round_id] = source.vod_timestamp_s
        return FusedRoundSnapshot(
            match_id=source.match_id,
            map_id=source.map_id,
            round_id=source.round_id,
            vod_timestamp_s=source.vod_timestamp_s,
            round_elapsed_s=source.round_elapsed_s,
            display_clock_s=source.display_clock_s,
            players=players,
            confidence=confidence,
            evidence=list(dict.fromkeys([*interval.evidence, "round_snapshot_fusion"])),
        )

    @staticmethod
    def _rejection(source: RoundSnapshotInput) -> str | None:
        interval = source.broadcast
        if interval.phase != BroadcastPhase.LIVE or interval.rejection_reason is not None:
            return f"broadcast_not_live:{interval.rejection_reason or interval.phase.value}"
        if interval.round_id != source.round_id:
            return "broadcast_round_mismatch"
        if interval.vod_timestamp_s != source.vod_timestamp_s:
            return "broadcast_timestamp_mismatch"
        for track in source.tracks:
            if track.vod_timestamp_s != source.vod_timestamp_s:
                return "track_timestamp_mismatch"
        for alive in source.alive_states:
            if alive.round_id != source.round_id or alive.vod_timestamp_s != source.vod_timestamp_s:
                return "alive_state_round_or_timestamp_mismatch"
        return None
