"""Resolve current team sides from explicit match evidence and round context."""

from __future__ import annotations

from valoscribe.types.persistent import Side
from valoscribe.types.side_state import HalfState, TeamSideEvidence, TeamSideState


def resolve_team_sides(
    round_number: int,
    teams: list[TeamSideEvidence],
    *,
    minimum_confidence: float = 0.5,
) -> tuple[TeamSideState, ...]:
    """Resolve side swaps without treating any broadcast color as a side.

    Regulation sides derive from the first-half anchor. Overtime requires an
    explicit overtime starting-side anchor because it can differ from the
    first-half setup; subsequent overtime rounds alternate sides. Colors are
    carried only from current match-context evidence and never derive side.
    """
    if round_number < 1:
        raise ValueError("round_number must be at least 1")
    if not 0.0 <= minimum_confidence <= 1.0:
        raise ValueError("minimum_confidence must be between 0 and 1")

    half = _half_for_round(round_number)
    duplicate_team_ids = _duplicates([team.team_id for team in teams])
    anchors = [_anchor_for_round(team, round_number) for team in teams]
    confident_sides = [
        side
        for side, confidence, _ in anchors
        if side in (Side.ATTACK, Side.DEFENSE)
        and confidence is not None
        and confidence >= minimum_confidence
    ]
    duplicate_sides = _duplicates([side.value for side in confident_sides])
    colors = [team.broadcast_color for team in teams if team.broadcast_color is not None]
    duplicate_colors = _duplicates(colors)
    result: list[TeamSideState] = []
    for team, (anchor, anchor_confidence, anchor_evidence) in zip(teams, anchors):
        reason: str | None = None
        side = Side.UNKNOWN
        color = team.broadcast_color
        evidence: list[str] = []
        confidence = 0.0
        if team.team_id in duplicate_team_ids:
            reason = "duplicate_team_evidence"
        elif anchor_confidence is None:
            reason = (
                "overtime_starting_side_evidence_missing"
                if half is HalfState.OVERTIME
                else "first_half_side_evidence_missing"
            )
        elif anchor_confidence < minimum_confidence:
            reason = "side_evidence_below_minimum_confidence"
        elif anchor.value in duplicate_sides:
            reason = (
                "conflicting_overtime_starting_side_evidence"
                if half is HalfState.OVERTIME
                else "conflicting_first_half_side_evidence"
            )
        elif anchor is Side.UNKNOWN:
            reason = (
                "overtime_starting_side_evidence_missing"
                if half is HalfState.OVERTIME
                else "first_half_side_evidence_missing"
            )
        else:
            side = _side_for_round(anchor, round_number)
            confidence = anchor_confidence
            evidence.extend(anchor_evidence)
            evidence.append(f"round_context:{half.value}")
            if team.broadcast_color is not None:
                if team.broadcast_color in duplicate_colors:
                    color = None
                    reason = "conflicting_broadcast_color_evidence"
                elif team.color_confidence is None or team.color_confidence < minimum_confidence:
                    color = None
                else:
                    evidence.extend(team.color_evidence)
        result.append(
            TeamSideState(
                round_number=round_number,
                half=half,
                team_id=team.team_id,
                broadcast_color=color,
                side=side,
                confidence=confidence,
                evidence=evidence,
                rejection_reason=reason,
            )
        )
    return tuple(result)


def _half_for_round(round_number: int) -> HalfState:
    if round_number <= 12:
        return HalfState.FIRST
    if round_number <= 24:
        return HalfState.SECOND
    return HalfState.OVERTIME


def _anchor_for_round(
    team: TeamSideEvidence, round_number: int
) -> tuple[Side, float | None, list[str]]:
    if round_number <= 24:
        return team.first_half_side, team.side_confidence, team.side_evidence
    if team.overtime_starting_side is None:
        return Side.UNKNOWN, None, []
    return (
        team.overtime_starting_side,
        team.overtime_side_confidence,
        team.overtime_side_evidence,
    )


def _side_for_round(starting_side: Side, round_number: int) -> Side:
    if starting_side not in (Side.ATTACK, Side.DEFENSE):
        return Side.UNKNOWN
    if round_number <= 12:
        invert = False
    elif round_number <= 24:
        invert = True
    else:
        # VCT overtime starts from the explicit overtime anchor and alternates
        # sides each round; this does not assume first-half sides at round 25.
        invert = (round_number - 25) % 2 == 1
    if invert:
        return Side.DEFENSE if starting_side is Side.ATTACK else Side.ATTACK
    return starting_side


def _duplicates(values: list[str]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates
