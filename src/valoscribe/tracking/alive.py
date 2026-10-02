"""Deterministic per-round fusion of HUD alive state and killfeed evidence."""

from __future__ import annotations

import math

from valoscribe.types.persistent import (
    AliveState,
    FusedAliveState,
    HUDAliveObservation,
    KillfeedKillObservation,
)


class AliveStateTracker:
    """Fuse raw alive observations without guessing identity or revival."""

    def __init__(self, round_id: str, *, confidence_threshold: float = 0.8) -> None:
        if not round_id.strip():
            raise ValueError("round_id must not be blank")
        if not math.isfinite(confidence_threshold) or not 0.0 <= confidence_threshold <= 1.0:
            raise ValueError("confidence_threshold must be finite and in [0, 1]")
        self.confidence_threshold = confidence_threshold
        self.reset_round(round_id)

    def reset_round(self, round_id: str) -> None:
        """Start a new isolated round and discard all prior alive evidence."""
        if not round_id.strip():
            raise ValueError("round_id must not be blank")
        self.round_id = round_id
        self._states: dict[str, FusedAliveState] = {}
        self._confirmed_dead: set[str] = set()
        self._seen_event_ids: set[str] = set()
        self._latest_timestamp = -math.inf

    def update_hud(self, observation: HUDAliveObservation) -> FusedAliveState:
        """Fuse one HUD observation; an occluded HUD preserves prior evidence."""
        self._validate_round(observation.round_id)
        self._validate_timestamp(observation.vod_timestamp_s)
        previous = self._states.get(observation.player_id)
        evidence = [f"hud:{item}" for item in observation.evidence]
        if observation.state is AliveState.ALIVE and observation.player_id in self._confirmed_dead:
            assert previous is not None
            state = AliveState.DEAD
            confidence = previous.confidence
            reason = None
            evidence = [*previous.evidence, *evidence, "confirmed_death_latch"]
        elif not observation.visible:
            if previous is None:
                state, confidence = AliveState.UNKNOWN, 0.0
                reason = "hud_occluded_no_prior_evidence"
                evidence.append("hud_occluded")
            else:
                state, confidence = previous.state, previous.confidence
                reason = previous.rejection_reason
                evidence = [*previous.evidence, *evidence, "hud_occluded_prior_evidence_preserved"]
        elif observation.state is AliveState.UNKNOWN:
            if observation.player_id in self._confirmed_dead:
                assert previous is not None
                state, confidence = AliveState.DEAD, previous.confidence
                reason = None
                evidence = [*previous.evidence, *evidence, "uncertain_hud_after_confirmed_death"]
            else:
                state, confidence = AliveState.UNKNOWN, 0.0
                reason = "hud_state_unknown"
        elif observation.confidence < self.confidence_threshold:
            if observation.player_id in self._confirmed_dead:
                assert previous is not None
                state, confidence = AliveState.DEAD, previous.confidence
                reason = None
                evidence = [*previous.evidence, *evidence, "uncertain_hud_after_confirmed_death"]
            else:
                state, confidence = AliveState.UNKNOWN, 0.0
                reason = "hud_confidence_below_threshold"
        elif (
            previous is not None
            and previous.state is AliveState.DEAD
            and observation.state is AliveState.ALIVE
        ):
            state, confidence = AliveState.UNKNOWN, 0.0
            reason = "revival_requires_explicit_evidence"
            evidence = [*previous.evidence, *evidence]
        else:
            state, confidence = observation.state, observation.confidence
            reason = None
            if (
                previous is not None
                and previous.state is AliveState.DEAD
                and state is AliveState.DEAD
            ):
                evidence = [*previous.evidence, *evidence]
        result = self._store(
            observation.player_id,
            observation.vod_timestamp_s,
            state,
            confidence,
            evidence,
            reason,
        )
        return result

    def update_killfeed(self, observation: KillfeedKillObservation) -> tuple[FusedAliveState, ...]:
        """Apply a unique, sufficiently confident victim; return ambiguous candidates as unknown."""
        self._validate_round(observation.round_id)
        if observation.event_id in self._seen_event_ids:
            return ()
        self._validate_timestamp(observation.vod_timestamp_s)
        self._seen_event_ids.add(observation.event_id)
        candidates = list(dict.fromkeys(observation.victim.candidate_player_ids))
        evidence = [f"killfeed:{item}" for item in observation.evidence]
        evidence.extend(f"victim_agent:{observation.victim.agent_id}" for _ in [0])
        if len(candidates) != 1:
            reason = "victim_identity_unresolved" if not candidates else "victim_identity_ambiguous"
            return tuple(
                self._store_rejected(
                    player_id,
                    observation.vod_timestamp_s,
                    [*evidence, reason],
                    reason,
                )
                for player_id in candidates
            )
        victim_id = candidates[0]
        if observation.victim.confidence < self.confidence_threshold:
            reason = "victim_confidence_below_threshold"
            return (
                self._store_rejected(
                    victim_id,
                    observation.vod_timestamp_s,
                    [*evidence, reason],
                    reason,
                ),
            )
        return (
            self._store(
                victim_id,
                observation.vod_timestamp_s,
                AliveState.DEAD,
                observation.victim.confidence,
                [*evidence, f"victim_player:{victim_id}", "killfeed_victim_death"],
                None,
            ),
        )

    def state_for(self, player_id: str) -> FusedAliveState | None:
        """Return the latest fused state for a player in this round."""
        return self._states.get(player_id)

    def tracking_alive(self, player_id: str) -> bool | None:
        """Return the value suitable for TrackSmoothingInput.alive."""
        state = self.state_for(player_id)
        if state is None or state.state is AliveState.UNKNOWN:
            return None
        return state.state is AliveState.ALIVE

    def _validate_round(self, round_id: str) -> None:
        if round_id != self.round_id:
            raise ValueError(f"observation round {round_id!r} does not match {self.round_id!r}")

    def _validate_timestamp(self, timestamp: float) -> None:
        if timestamp < self._latest_timestamp:
            raise ValueError("alive observations must be timestamp ordered within a round")
        self._latest_timestamp = timestamp

    def _store_rejected(
        self,
        player_id: str,
        timestamp: float,
        evidence: list[str],
        reason: str,
    ) -> FusedAliveState:
        if player_id in self._confirmed_dead:
            previous = self._states[player_id]
            return self._store(
                player_id,
                timestamp,
                AliveState.DEAD,
                previous.confidence,
                [*previous.evidence, *evidence, "confirmed_death_latch"],
                None,
            )
        return self._store(player_id, timestamp, AliveState.UNKNOWN, 0.0, evidence, reason)

    def _store(
        self,
        player_id: str,
        timestamp: float,
        state: AliveState,
        confidence: float,
        evidence: list[str],
        reason: str | None,
    ) -> FusedAliveState:
        if state is AliveState.DEAD:
            self._confirmed_dead.add(player_id)
        result = FusedAliveState(
            player_id=player_id,
            round_id=self.round_id,
            vod_timestamp_s=timestamp,
            state=state,
            confidence=confidence,
            evidence=evidence,
            rejection_reason=reason,
        )
        self._states[player_id] = result
        return result
