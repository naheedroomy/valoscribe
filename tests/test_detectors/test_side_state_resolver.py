from __future__ import annotations

import pytest
from pydantic import ValidationError

from valoscribe.detectors.side_state_resolver import resolve_team_sides
from valoscribe.types.persistent import Side
from valoscribe.types.side_state import HalfState, TeamSideEvidence


def evidence(team_id: str, side: Side, color: str) -> TeamSideEvidence:
    return TeamSideEvidence(
        team_id=team_id,
        first_half_side=side,
        side_confidence=0.95,
        side_evidence=["reviewed_match_metadata:first_half_starting_side"],
        broadcast_color=color,
        color_confidence=0.9,
        color_evidence=["current_frame:team_hud_color"],
    )


def test_regulation_halves_swap_sides_without_mapping_color_to_side() -> None:
    teams = [evidence("alpha", Side.ATTACK, "red"), evidence("beta", Side.DEFENSE, "blue")]

    first = resolve_team_sides(1, teams)
    second = resolve_team_sides(13, teams)

    assert [state.side for state in first] == [Side.ATTACK, Side.DEFENSE]
    assert [state.side for state in second] == [Side.DEFENSE, Side.ATTACK]
    assert [state.broadcast_color for state in first] == ["red", "blue"]
    assert [state.broadcast_color for state in second] == ["red", "blue"]
    assert first[0].half is HalfState.FIRST
    assert second[0].half is HalfState.SECOND


def test_overtime_requires_explicit_anchor_and_alternates_each_round() -> None:
    team = evidence("alpha", Side.ATTACK, "red")
    missing_anchor = resolve_team_sides(25, [team])[0]

    assert missing_anchor.side is Side.UNKNOWN
    assert missing_anchor.rejection_reason == "overtime_starting_side_evidence_missing"

    overtime_team = team.model_copy(
        update={
            "overtime_starting_side": Side.DEFENSE,
            "overtime_side_confidence": 0.88,
            "overtime_side_evidence": ["reviewed_vct_overtime_starting_side"],
        }
    )
    states = [
        resolve_team_sides(round_number, [overtime_team])[0]
        for round_number in (24, 25, 26, 27, 28)
    ]

    assert [state.side for state in states] == [
        Side.DEFENSE,
        Side.DEFENSE,
        Side.ATTACK,
        Side.DEFENSE,
        Side.ATTACK,
    ]
    assert [state.confidence for state in states[1:]] == [0.88] * 4
    assert all(state.half is HalfState.OVERTIME for state in states[1:])


def test_overtime_complementary_anchors_are_accepted() -> None:
    teams = [
        evidence("alpha", Side.DEFENSE, "red").model_copy(
            update={
                "overtime_starting_side": Side.ATTACK,
                "overtime_side_confidence": 0.9,
                "overtime_side_evidence": ["reviewed_vct_ot_side"],
            }
        ),
        evidence("beta", Side.ATTACK, "blue").model_copy(
            update={
                "overtime_starting_side": Side.DEFENSE,
                "overtime_side_confidence": 0.9,
                "overtime_side_evidence": ["reviewed_vct_ot_side"],
            }
        ),
    ]

    first_ot_round = resolve_team_sides(25, teams)
    second_ot_round = resolve_team_sides(26, teams)

    assert [state.side for state in first_ot_round] == [Side.ATTACK, Side.DEFENSE]
    assert [state.side for state in second_ot_round] == [Side.DEFENSE, Side.ATTACK]


def test_overtime_anchor_conflicts_are_rejected_and_color_confidence_is_independent() -> None:
    teams = [
        evidence("alpha", Side.ATTACK, "red").model_copy(
            update={
                "overtime_starting_side": Side.ATTACK,
                "overtime_side_confidence": 0.95,
                "overtime_side_evidence": ["reviewed_vct_ot_side"],
                "color_confidence": 0.2,
            }
        ),
        evidence("beta", Side.DEFENSE, "blue").model_copy(
            update={
                "overtime_starting_side": Side.ATTACK,
                "overtime_side_confidence": 0.9,
                "overtime_side_evidence": ["reviewed_vct_ot_side"],
            }
        ),
    ]

    states = resolve_team_sides(25, teams)

    assert [state.side for state in states] == [Side.UNKNOWN, Side.UNKNOWN]
    assert [state.rejection_reason for state in states] == [
        "conflicting_overtime_starting_side_evidence",
        "conflicting_overtime_starting_side_evidence",
    ]

    state = resolve_team_sides(25, [teams[0]])[0]
    assert state.side is Side.ATTACK
    assert state.confidence == 0.95
    assert state.broadcast_color is None


def test_missing_or_low_confidence_side_evidence_stays_unknown() -> None:
    team = TeamSideEvidence(
        team_id="alpha",
        first_half_side=Side.UNKNOWN,
        side_confidence=0.9,
        side_evidence=["no_starting_side_observed"],
        broadcast_color="red",
        color_confidence=0.99,
        color_evidence=["current_frame_color"],
    )
    low_confidence = evidence("beta", Side.DEFENSE, "blue").model_copy(
        update={"side_confidence": 0.2}
    )

    states = resolve_team_sides(13, [team, low_confidence])

    assert [state.side for state in states] == [Side.UNKNOWN, Side.UNKNOWN]
    assert [state.confidence for state in states] == [0.0, 0.0]
    assert [state.rejection_reason for state in states] == [
        "first_half_side_evidence_missing",
        "side_evidence_below_minimum_confidence",
    ]


def test_conflicting_starting_side_evidence_stays_unknown() -> None:
    teams = [evidence("alpha", Side.ATTACK, "red"), evidence("beta", Side.ATTACK, "blue")]

    states = resolve_team_sides(1, teams)

    assert [state.side for state in states] == [Side.UNKNOWN, Side.UNKNOWN]
    assert [state.rejection_reason for state in states] == [
        "conflicting_first_half_side_evidence",
        "conflicting_first_half_side_evidence",
    ]


def test_conflicting_colors_in_context_reject_color_states() -> None:
    teams = [evidence("alpha", Side.ATTACK, "red"), evidence("beta", Side.DEFENSE, "red")]

    states = resolve_team_sides(1, teams)

    assert [state.side for state in states] == [Side.ATTACK, Side.DEFENSE]
    assert [state.broadcast_color for state in states] == [None, None]
    assert [state.rejection_reason for state in states] == [
        "conflicting_broadcast_color_evidence",
        "conflicting_broadcast_color_evidence",
    ]


def test_missing_color_confidence_keeps_side_but_not_color() -> None:
    team = evidence("alpha", Side.ATTACK, "red").model_copy(
        update={"color_confidence": None, "color_evidence": []}
    )

    state = resolve_team_sides(1, [team])[0]

    assert state.side is Side.ATTACK
    assert state.broadcast_color is None
    assert state.confidence == 0.95


def test_invalid_round_and_confidence_threshold_are_rejected() -> None:
    team = [evidence("alpha", Side.ATTACK, "red")]
    with pytest.raises(ValueError, match="round_number"):
        resolve_team_sides(0, team)
    with pytest.raises(ValueError, match="minimum_confidence"):
        resolve_team_sides(1, team, minimum_confidence=1.1)


def test_non_finite_evidence_confidence_is_rejected() -> None:
    with pytest.raises(ValidationError, match="less than or equal to 1"):
        TeamSideEvidence(
            team_id="alpha",
            first_half_side=Side.ATTACK,
            side_confidence=float("nan"),
            side_evidence=["reviewed_metadata"],
        )


def test_partial_overtime_anchor_evidence_is_rejected() -> None:
    with pytest.raises(ValidationError, match="must be supplied together"):
        TeamSideEvidence(
            team_id="alpha",
            first_half_side=Side.ATTACK,
            side_confidence=0.9,
            side_evidence=["reviewed_metadata"],
            overtime_starting_side=Side.ATTACK,
            overtime_side_confidence=0.9,
        )
