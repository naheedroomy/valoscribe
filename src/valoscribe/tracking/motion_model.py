"""Per-known-player motion gates and bounded, evidence-backed prediction."""

from __future__ import annotations

import math
from dataclasses import dataclass

from valoscribe.types.persistent import (
    MotionModelConfig,
    NormalizedPoint,
    PlayerDetection,
    PlayerTrackEstimate,
)


@dataclass(frozen=True)
class KnownPlayer:
    """Match-metadata identity used to create exactly one independent track."""

    player_id: str
    agent_id: str
    team_id: str


@dataclass(frozen=True)
class _Observation:
    timestamp_s: float
    position: NormalizedPoint
    confidence: float
    source_frame: int | None
    evidence: str


class PlayerMotionTracker:
    """Track already-resolved player detections; never perform identity assignment."""

    def __init__(self, players: list[KnownPlayer], config: MotionModelConfig) -> None:
        if not players:
            raise ValueError("at least one known player is required")
        ids = [player.player_id for player in players]
        if len(ids) != len(set(ids)):
            raise ValueError("known player IDs must be unique")
        if any(
            not p.player_id.strip() or not p.agent_id.strip() or not p.team_id.strip()
            for p in players
        ):
            raise ValueError("known player identifiers must not be blank")
        self._players = {player.player_id: player for player in players}
        self._config = config
        self._observations: dict[str, tuple[_Observation, ...]] = {
            player_id: () for player_id in ids
        }

    @property
    def player_ids(self) -> tuple[str, ...]:
        """Return the stable set of configured player tracks."""
        return tuple(self._players)

    def update(self, player_id: str, detection: PlayerDetection) -> PlayerTrackEstimate:
        """Accept a plausible, uniquely identified, registered raw detection."""
        player = self._players.get(player_id)
        if player is None:
            raise KeyError(f"unknown player track: {player_id}")
        if detection.team_id != player.team_id:
            return self._unknown(player_id, detection, "team_identity_mismatch")
        if detection.candidate_player_ids != [
            player.player_id
        ] or detection.candidate_agent_ids != [player.agent_id]:
            return self._unknown(player_id, detection, "identity_evidence_missing_or_ambiguous")
        if detection.registration_confidence < self._config.minimum_registration_confidence:
            return self._unknown(player_id, detection, "map_registration_confidence_below_minimum")
        if detection.detector_confidence < self._config.minimum_detection_confidence:
            return self._unknown(player_id, detection, "detection_confidence_below_minimum")

        previous = self._observations[player_id]
        current = _Observation(
            timestamp_s=detection.vod_timestamp_s,
            position=detection.canonical_point,
            confidence=min(detection.detector_confidence, detection.registration_confidence),
            source_frame=detection.source_frame,
            evidence=self._observation_evidence(detection),
        )
        if previous:
            prior = previous[-1]
            delta_s = current.timestamp_s - prior.timestamp_s
            if delta_s <= 0.0:
                return self._unknown(player_id, detection, "observation_timestamp_not_increasing")
            if delta_s > self._config.maximum_prediction_gap_s:
                self._observations[player_id] = (current,)
                return self._observed(player_id, current)
            if (
                self._distance_m(prior.position, current.position) / delta_s
                > self._config.maximum_speed_mps
            ):
                self._observations[player_id] = ()
                return self._unknown(player_id, detection, "movement_speed_gate_exceeded")
        self._observations[player_id] = (*previous[-1:], current)
        return self._observed(player_id, current)

    def predict(self, player_id: str, timestamp_s: float) -> PlayerTrackEstimate:
        """Predict only within the configured short gap and after motion is observed."""
        if player_id not in self._players:
            raise KeyError(f"unknown player track: {player_id}")
        if not math.isfinite(timestamp_s) or timestamp_s < 0.0:
            raise ValueError("prediction timestamp must be finite and non-negative")
        observations = self._observations[player_id]
        if len(observations) < 2:
            return self._unknown_at(
                player_id, timestamp_s, "motion_history_insufficient", observations
            )
        previous, latest = observations
        elapsed = timestamp_s - latest.timestamp_s
        if elapsed <= 0.0:
            return self._unknown_at(
                player_id, timestamp_s, "prediction_timestamp_not_after_observation", observations
            )
        if elapsed >= self._config.maximum_prediction_gap_s:
            return self._unknown_at(player_id, timestamp_s, "prediction_gap_exceeded", observations)

        interval = latest.timestamp_s - previous.timestamp_s
        velocity_x = (latest.position.x - previous.position.x) / interval
        velocity_y = (latest.position.y - previous.position.y) / interval
        predicted_x = latest.position.x + velocity_x * elapsed
        predicted_y = latest.position.y + velocity_y * elapsed
        if not 0.0 <= predicted_x <= 1.0 or not 0.0 <= predicted_y <= 1.0:
            return self._unknown_at(
                player_id, timestamp_s, "predicted_position_out_of_bounds", observations
            )
        point = NormalizedPoint(x=predicted_x, y=predicted_y)
        decay = 1.0 - elapsed / self._config.maximum_prediction_gap_s
        return PlayerTrackEstimate(
            player_id=player_id,
            vod_timestamp_s=timestamp_s,
            source_frame=None,
            position=point,
            observed=False,
            predicted=True,
            confidence=latest.confidence * decay,
            evidence=[
                previous.evidence,
                latest.evidence,
                f"constant_velocity_prediction:{elapsed:.6f}s",
            ],
        )

    def _distance_m(self, first: NormalizedPoint, second: NormalizedPoint) -> float:
        dx = (second.x - first.x) * self._config.map_width_m
        dy = (second.y - first.y) * self._config.map_height_m
        return math.hypot(dx, dy)

    @staticmethod
    def _observation_evidence(detection: PlayerDetection) -> str:
        return (
            f"raw_minimap_detection:timestamp={detection.vod_timestamp_s:.6f}:"
            f"frame={detection.source_frame}:detector_confidence={detection.detector_confidence:.6f}:"
            f"registration_confidence={detection.registration_confidence:.6f}"
        )

    @staticmethod
    def _observed(player_id: str, observation: _Observation) -> PlayerTrackEstimate:
        return PlayerTrackEstimate(
            player_id=player_id,
            vod_timestamp_s=observation.timestamp_s,
            source_frame=observation.source_frame,
            position=observation.position,
            observed=True,
            predicted=False,
            confidence=observation.confidence,
            evidence=[observation.evidence],
        )

    def _unknown(
        self, player_id: str, detection: PlayerDetection, reason: str
    ) -> PlayerTrackEstimate:
        return PlayerTrackEstimate(
            player_id=player_id,
            vod_timestamp_s=detection.vod_timestamp_s,
            source_frame=detection.source_frame,
            position=None,
            observed=False,
            predicted=False,
            confidence=0.0,
            evidence=[f"raw_minimap_detection:frame={detection.source_frame}"],
            rejection_reason=reason,
        )

    @staticmethod
    def _unknown_at(
        player_id: str,
        timestamp_s: float,
        reason: str,
        observations: tuple[_Observation, ...],
    ) -> PlayerTrackEstimate:
        evidence = [observation.evidence for observation in observations[-2:]]
        evidence.append(f"motion_prediction_rejected:{reason}")
        return PlayerTrackEstimate(
            player_id=player_id,
            vod_timestamp_s=timestamp_s,
            position=None,
            observed=False,
            predicted=False,
            confidence=0.0,
            evidence=evidence,
            rejection_reason=reason,
        )
