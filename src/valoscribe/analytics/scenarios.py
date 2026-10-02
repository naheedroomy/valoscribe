"""Deterministic filtering of versioned round and segment summaries."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from valoscribe.types.persistent import PersistentModel, ScenarioQuery, Side


class ScenarioSearchRecord(PersistentModel):
    """Searchable derived round or segment summary; unknown values remain explicit."""

    schema_version: Literal["1.0"] = "1.0"
    round_id: str = Field(min_length=1)
    segment_id: str | None = None
    map_id: str | None = None
    team_id: str | None = None
    side: Side | None = None
    round_number: int | None = Field(default=None, ge=1)
    buy_class: str | None = None
    display_clock_s: float | None = Field(default=None, ge=0.0)
    alive_attack: int | None = Field(default=None, ge=0, le=5)
    alive_defense: int | None = Field(default=None, ge=0, le=5)
    control_zones: list[str] = Field(default_factory=list)
    spike_state: str | None = None
    opening_duel_outcome: str | None = None
    utility_ids: list[str] = Field(default_factory=list)
    phase: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_ids: list[str] = Field(min_length=1)


def match_scenarios(
    query: ScenarioQuery, records: list[ScenarioSearchRecord]
) -> list[ScenarioSearchRecord]:
    """Return matching records in source order; missing values never satisfy filters."""
    return [record for record in records if _matches(query, record)]


def _matches(query: ScenarioQuery, record: ScenarioSearchRecord) -> bool:
    if record.confidence < query.confidence_floor:
        return False
    if query.map_ids and record.map_id not in query.map_ids:
        return False
    if query.team_ids and record.team_id not in query.team_ids:
        return False
    if query.sides and record.side not in query.sides:
        return False
    if query.round_numbers and record.round_number not in query.round_numbers:
        return False
    if query.buy_classes and record.buy_class not in query.buy_classes:
        return False
    if query.min_display_clock_s is not None and (
        record.display_clock_s is None or record.display_clock_s < query.min_display_clock_s
    ):
        return False
    if query.max_display_clock_s is not None and (
        record.display_clock_s is None or record.display_clock_s > query.max_display_clock_s
    ):
        return False
    if query.alive_attack is not None and record.alive_attack != query.alive_attack:
        return False
    if query.alive_defense is not None and record.alive_defense != query.alive_defense:
        return False
    if not set(query.required_control_zones).issubset(record.control_zones):
        return False
    if set(query.excluded_control_zones).intersection(record.control_zones):
        return False
    if query.spike_states and record.spike_state not in query.spike_states:
        return False
    if query.opening_duel_outcomes and (
        record.opening_duel_outcome not in query.opening_duel_outcomes
    ):
        return False
    if not set(query.required_utility_ids).issubset(record.utility_ids):
        return False
    if query.phases and record.phase not in query.phases:
        return False
    return True
