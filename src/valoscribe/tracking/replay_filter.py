"""Fail-closed classification of live broadcast intervals."""

from __future__ import annotations

from valoscribe.types.persistent import (
    BroadcastFrameObservation,
    BroadcastInterval,
    BroadcastPhase,
)


class BroadcastStateClassifier:
    """Classify ordered frame observations without accepting replay material."""

    def __init__(self, *, minimum_confidence: float = 0.5) -> None:
        if not 0.0 <= minimum_confidence <= 1.0:
            raise ValueError("minimum_confidence must be in [0, 1]")
        self.minimum_confidence = minimum_confidence
        self._last_timestamp: float | None = None
        self._round_id: str | None = None

    def classify(self, observation: BroadcastFrameObservation) -> BroadcastInterval:
        """Return a state plus evidence and rejection reason for each frame."""
        reason: str | None = None
        phase = observation.phase
        if self._last_timestamp is not None and observation.vod_timestamp_s <= self._last_timestamp:
            reason = "out_of_order_timestamp"
        else:
            self._last_timestamp = observation.vod_timestamp_s
        if observation.round_id != self._round_id:
            self._round_id = observation.round_id
        if reason is None:
            if (
                observation.replay_cue
                or observation.historical_duplicate
                or phase == BroadcastPhase.REPLAY
            ):
                phase, reason = BroadcastPhase.REPLAY, "replay_cue_or_duplicate"
            elif phase == BroadcastPhase.PAUSED:
                reason = "broadcast_paused"
            elif (
                not observation.minimap_visible
                or not observation.hud_visible
                or phase == BroadcastPhase.HIDDEN
            ):
                phase, reason = BroadcastPhase.HIDDEN, "hud_or_minimap_hidden"
            elif phase != BroadcastPhase.LIVE:
                phase, reason = BroadcastPhase.UNKNOWN, "phase_not_confirmed_live"
            elif not (observation.timer_continuous or observation.score_continuous):
                reason = "round_continuity_missing"
            elif observation.confidence < self.minimum_confidence:
                reason = "frame_confidence_below_threshold"
            elif not observation.evidence:
                reason = "broadcast_evidence_missing"
        if reason is not None and phase == BroadcastPhase.LIVE:
            phase = BroadcastPhase.UNKNOWN
        evidence = [*observation.evidence, f"broadcast_state:{phase.value}"]
        if reason is not None:
            evidence.append(f"broadcast_rejected:{reason}")
        else:
            evidence.append("broadcast_live_confirmed")
        return BroadcastInterval(
            vod_timestamp_s=observation.vod_timestamp_s,
            round_id=observation.round_id,
            phase=phase,
            confidence=observation.confidence if reason is None else 0.0,
            evidence=evidence,
            rejection_reason=reason,
        )
