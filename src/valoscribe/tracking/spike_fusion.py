"""Evidence-gated fusion for round spike state."""

from __future__ import annotations

import math
from enum import Enum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from valoscribe.types.persistent import NormalizedPoint, PersistentModel


class SpikeState(str, Enum):
    UNKNOWN = "UNKNOWN"
    IN_SPAWN = "IN_SPAWN"
    CARRIED = "CARRIED"
    DROPPED = "DROPPED"
    PLANTING = "PLANTING"
    PLANTED = "PLANTED"
    DEFUSING = "DEFUSING"
    DEFUSED = "DEFUSED"
    DETONATED = "DETONATED"
    ROUND_ENDED = "ROUND_ENDED"


class SpikeObservation(PersistentModel):
    """Raw spike cue from one frame; cues remain independently identifiable."""

    schema_version: Literal["1.0"] = "1.0"
    match_id: str = Field(min_length=1)
    map_id: str = Field(min_length=1)
    round_id: str = Field(min_length=1)
    vod_timestamp_s: float = Field(ge=0)
    hud_state: SpikeState | None = None
    carrier_player_id: str | None = None
    carrier_marker_visible: bool = False
    drop_marker_visible: bool = False
    plant_event: bool = False
    planted_location: NormalizedPoint | None = None
    replay: bool = False
    confidence: float = Field(ge=0, le=1)
    evidence: list[str] = Field(min_length=1)

    @field_validator("match_id", "map_id", "round_id")
    @classmethod
    def identifier_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("identifiers must not be blank")
        return value

    @field_validator("vod_timestamp_s", "confidence")
    @classmethod
    def finite_numbers(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("spike observation values must be finite")
        return value

    @field_validator("carrier_player_id")
    @classmethod
    def carrier_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("carrier_player_id must not be blank")
        return value

    @field_validator("evidence")
    @classmethod
    def evidence_not_blank(cls, values: list[str]) -> list[str]:
        if any(not item.strip() for item in values):
            raise ValueError("evidence entries must not be blank")
        return values

    @model_validator(mode="after")
    def marker_fields_consistent(self) -> SpikeObservation:
        if self.carrier_player_id is not None and not self.carrier_marker_visible:
            raise ValueError("carrier identity requires a visible carrier marker")
        return self


class SpikeDiagnostic(PersistentModel):
    schema_version: Literal["1.0"] = "1.0"
    code: str = Field(min_length=1)
    evidence: list[str] = Field(min_length=1)


class FusedSpikeState(PersistentModel):
    schema_version: Literal["1.0"] = "1.0"
    match_id: str
    map_id: str
    round_id: str
    vod_timestamp_s: float = Field(ge=0)
    state: SpikeState
    carrier_player_id: str | None = None
    planted_location: NormalizedPoint | None = None
    confidence: float = Field(ge=0, le=1)
    evidence: list[str] = Field(min_length=1)
    diagnostics: list[SpikeDiagnostic] = Field(default_factory=list)


class SpikeStateFusion:
    """Fuse ordered spike cues; rejected frames never alter round state."""

    def __init__(self) -> None:
        self._round_key: tuple[str, str, str] | None = None
        self._last_timestamp: float | None = None
        self._state = SpikeState.UNKNOWN
        self._carrier: str | None = None
        self._location: NormalizedPoint | None = None
        self._confidence = 0.0
        self._evidence = ["no_confirmed_spike_cue"]

    def fuse(self, observation: SpikeObservation) -> FusedSpikeState:
        diagnostic: list[SpikeDiagnostic] = []
        evidence = list(observation.evidence)
        if observation.replay:
            diagnostic.append(SpikeDiagnostic(code="replay_excluded", evidence=["replay_frame"]))
            return self._result(observation, SpikeState.UNKNOWN, 0.0, evidence, diagnostic)

        round_key = (observation.match_id, observation.map_id, observation.round_id)
        new_round = round_key != self._round_key
        if new_round:
            self._round_key = round_key
            self._last_timestamp = None
            self._state = SpikeState.UNKNOWN
            self._carrier = None
            self._location = None
            self._confidence = 0.0
            self._evidence = ["no_confirmed_spike_cue"]
        elif (
            self._last_timestamp is not None
            and observation.vod_timestamp_s <= self._last_timestamp
        ):
            diagnostic.append(
                SpikeDiagnostic(
                    code="out_of_order_timestamp", evidence=["timestamp_not_increasing"]
                )
            )
            return self._result(observation, SpikeState.UNKNOWN, 0.0, evidence, diagnostic)
        self._last_timestamp = observation.vod_timestamp_s

        cues: list[tuple[SpikeState, str]] = []
        if observation.hud_state is not None and observation.hud_state != SpikeState.UNKNOWN:
            cues.append((observation.hud_state, "hud_state"))
        if observation.plant_event:
            cues.append((SpikeState.PLANTED, "plant_event"))
        if observation.drop_marker_visible:
            cues.append((SpikeState.DROPPED, "minimap_drop_marker"))
        if observation.carrier_marker_visible:
            cues.append((SpikeState.CARRIED, "minimap_carrier_marker"))

        # Explicit plant event outranks HUD/minimap cues; contradictory explicit
        # cues fail closed instead of allowing a weaker cue to overwrite them.
        event_cues = [state for state, source in cues if source == "plant_event"]
        if event_cues:
            state = SpikeState.PLANTED
            conflicting = [
                source
                for cue, source in cues
                if cue
                not in (
                    SpikeState.PLANTED,
                    SpikeState.DEFUSING,
                    SpikeState.DEFUSED,
                    SpikeState.DETONATED,
                    SpikeState.ROUND_ENDED,
                )
            ]
        else:
            strong = [(cue, source) for cue, source in cues if source == "hud_state"]
            weak = [(cue, source) for cue, source in cues if source != "hud_state"]
            if strong:
                state = strong[-1][0]
                conflicting = [source for cue, source in cues if cue != state]
            elif weak:
                unique = {cue for cue, _ in weak}
                state = next(iter(unique)) if len(unique) == 1 else SpikeState.UNKNOWN
                conflicting = [source for cue, source in weak if cue != state]
            else:
                state, conflicting = self._state, []
        if not cues:
            confidence = self._confidence
            evidence = list(self._evidence)
            if observation.planted_location is not None:
                diagnostic.append(
                    SpikeDiagnostic(
                        code="location_without_plant_confirmation",
                        evidence=["planted_location_observed"],
                    )
                )
            evidence.append(f"spike_state:{state.value.lower()}")
            return self._result(observation, state, confidence, evidence, diagnostic)
        if conflicting:
            diagnostic.append(SpikeDiagnostic(code="conflicting_spike_cues", evidence=conflicting))
            state = SpikeState.UNKNOWN
        if observation.planted_location is not None:
            if state == SpikeState.PLANTED and not conflicting:
                self._location = observation.planted_location
                evidence.append("planted_location_observed")
            else:
                diagnostic.append(
                    SpikeDiagnostic(
                        code="location_without_plant_confirmation",
                        evidence=["planted_location_observed"],
                    )
                )
        if state == SpikeState.CARRIED:
            if observation.carrier_marker_visible and observation.carrier_player_id is not None:
                self._carrier = observation.carrier_player_id
        elif state in (
            SpikeState.DROPPED,
            SpikeState.IN_SPAWN,
            SpikeState.PLANTED,
            SpikeState.DEFUSED,
            SpikeState.DETONATED,
            SpikeState.ROUND_ENDED,
        ) and not conflicting:
            self._carrier = None
        if state == SpikeState.UNKNOWN and diagnostic:
            confidence = 0.0
        elif state == SpikeState.UNKNOWN:
            confidence = self._confidence
            evidence = list(self._evidence)
        else:
            confidence = observation.confidence
            self._state = state
            self._confidence = confidence
            self._evidence = list(observation.evidence) + [f"spike_state:{state.value.lower()}"]
        evidence.append(f"spike_state:{state.value.lower()}")
        return self._result(observation, state, confidence, evidence, diagnostic)

    def _result(
        self,
        observation: SpikeObservation,
        state: SpikeState,
        confidence: float,
        evidence: list[str],
        diagnostics: list[SpikeDiagnostic],
    ) -> FusedSpikeState:
        return FusedSpikeState(
            match_id=observation.match_id,
            map_id=observation.map_id,
            round_id=observation.round_id,
            vod_timestamp_s=observation.vod_timestamp_s,
            state=state,
            carrier_player_id=self._carrier if state in (self._state, SpikeState.UNKNOWN) else None,
            planted_location=self._location
            if state
            in (SpikeState.PLANTED, SpikeState.DEFUSING, SpikeState.DEFUSED, SpikeState.DETONATED)
            else None,
            confidence=confidence,
            evidence=list(dict.fromkeys(evidence)),
            diagnostics=diagnostics,
        )
