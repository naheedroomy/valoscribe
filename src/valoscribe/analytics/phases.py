"""Deterministic, evidence-backed temporal round phase classification."""

from __future__ import annotations

from collections.abc import Iterable

from valoscribe.types.persistent import (
    PhaseDiagnostic,
    PhaseObservation,
    PhaseSegment,
    RoundPhase,
)


class DeterministicPhaseEngine:
    """Classify explicit round signals; absent or ambiguous cues stay UNKNOWN."""

    def __init__(self) -> None:
        self._round_key: tuple[str, str, str] | None = None
        self._last_timestamp: float | None = None
        self._segments: list[PhaseSegment] = []

    def observe(self, observation: PhaseObservation) -> PhaseSegment:
        """Append one valid observation and return its phase segment."""
        round_key = (observation.match_id, observation.map_id, observation.round_id)
        diagnostic: PhaseDiagnostic | None = None
        if observation.replay:
            return self._segment(
                observation,
                RoundPhase.UNKNOWN,
                0.0,
                [*observation.evidence, "replay_excluded"],
                PhaseDiagnostic(code="replay_excluded", evidence=["replay_frame"]),
            )
        if round_key != self._round_key:
            self._round_key = round_key
            self._last_timestamp = None
            self._segments = []
        if self._last_timestamp is not None and observation.vod_timestamp_s <= self._last_timestamp:
            return self._segment(
                observation,
                RoundPhase.UNKNOWN,
                0.0,
                [*observation.evidence, "timestamp_not_increasing"],
                PhaseDiagnostic(
                    code="out_of_order_timestamp", evidence=["timestamp_not_increasing"]
                ),
            )
        self._last_timestamp = observation.vod_timestamp_s

        phase, confidence, evidence, diagnostic = self._classify(observation)
        result = self._segment(observation, phase, confidence, evidence, diagnostic)
        if diagnostic is not None:
            self._segments.append(result)
            return result
        if self._segments and self._segments[-1].phase == phase:
            previous = self._segments[-1]
            self._segments[-1] = previous.model_copy(
                update={
                    "end_timestamp_s": observation.vod_timestamp_s,
                    "confidence": min(previous.confidence, result.confidence),
                    "evidence": list(dict.fromkeys([*previous.evidence, *result.evidence])),
                }
            )
            return self._segments[-1]
        self._segments.append(result)
        return result

    @property
    def segments(self) -> tuple[PhaseSegment, ...]:
        """Return the ordered phase runs observed for the current round."""
        return tuple(self._segments)

    @staticmethod
    def _classify(
        observation: PhaseObservation,
    ) -> tuple[RoundPhase, float, list[str], PhaseDiagnostic | None]:
        # Explicit terminal and planted signals have precedence over generic states.
        explicit = observation.explicit_phase
        if explicit is not None:
            return (
                explicit,
                observation.confidence,
                [*observation.evidence, f"explicit_phase:{explicit.value}"],
                None,
            )
        if observation.conflicting_signals:
            return (
                RoundPhase.UNKNOWN,
                0.0,
                [*observation.evidence, "phase_conflict"],
                PhaseDiagnostic(
                    code="conflicting_phase_signals", evidence=observation.conflicting_signals
                ),
            )
        if observation.round_end:
            phase = RoundPhase.ROUND_END
        elif observation.clutch:
            phase = RoundPhase.CLUTCH
        elif observation.planted:
            phase = RoundPhase.POST_PLANT
        elif observation.retake:
            phase = RoundPhase.RETAKE
        elif observation.save:
            phase = RoundPhase.SAVE
        elif observation.execute:
            phase = RoundPhase.EXECUTE
        elif observation.rotate:
            phase = RoundPhase.ROTATE
        elif observation.regroup:
            phase = RoundPhase.REGROUP
        elif observation.contact:
            phase = RoundPhase.CONTACT
        elif observation.pressure:
            phase = RoundPhase.PRESSURE
        elif observation.default:
            phase = RoundPhase.DEFAULT
        elif observation.opening:
            phase = RoundPhase.OPENING
        elif observation.preround:
            phase = RoundPhase.PREROUND
        else:
            return RoundPhase.UNKNOWN, 0.0, [*observation.evidence, "no_phase_rule_matched"], None
        signal_evidence = [
            f"signal:{signal}"
            for signal, active in zip(observation.signal_names, observation.signals)
            if active
        ]
        evidence = [
            *observation.evidence,
            f"phase_rule:{phase.value.lower()}",
            *signal_evidence,
        ]
        return phase, observation.confidence, evidence, None

    @staticmethod
    def _segment(
        observation: PhaseObservation,
        phase: RoundPhase,
        confidence: float,
        evidence: Iterable[str],
        diagnostic: PhaseDiagnostic | None,
    ) -> PhaseSegment:
        return PhaseSegment(
            match_id=observation.match_id,
            map_id=observation.map_id,
            round_id=observation.round_id,
            phase=phase,
            start_timestamp_s=observation.vod_timestamp_s,
            end_timestamp_s=observation.vod_timestamp_s,
            confidence=confidence,
            evidence=list(dict.fromkeys(evidence)),
            diagnostics=[] if diagnostic is None else [diagnostic],
        )
