"""Synthetic checks for roster-constrained minimap portrait matching."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from valoscribe.detectors.minimap_portrait_matcher import (
    MinimapPortraitMatcher,
    RosterPlayer,
    TeamRoster,
)
from valoscribe.types.persistent import Side


def image(value: int, marker: int) -> np.ndarray:
    crop = np.full((24, 24, 3), value, dtype=np.uint8)
    cv2.circle(crop, (12, 12), 5, (marker, 255 - marker, 80), -1)
    return crop


def test_known_roster_ranks_template_candidates_without_assigning_team_or_side(tmp_path) -> None:
    jett_attack = image(20, 40)
    jett_defense = image(20, 220)
    sova_attack = image(130, 70)
    matcher = MinimapPortraitMatcher(
        {
            ("jett", Side.ATTACK): jett_attack,
            ("jett", Side.DEFENSE): jett_defense,
            ("sova", Side.ATTACK): sova_attack,
            ("not_in_roster", Side.ATTACK): image(230, 120),
        }
    )
    roster = TeamRoster(
        team_id="team-a",
        players=[
            RosterPlayer(player_id="p1", agent_id="jett"),
            RosterPlayer(player_id="p2", agent_id="sova"),
        ],
    )

    result = matcher.match(jett_attack.copy(), [roster])

    assert result.candidates[0].agent_id == "jett"
    assert result.candidates[0].side == Side.ATTACK
    assert result.candidates[0].confidence == pytest.approx(1.0)
    assert all(candidate.agent_id != "not_in_roster" for candidate in result.candidates)
    assert result.resolved_agent_id == "jett"
    assert not result.ambiguous
    assert [
        (member.team_id, member.player_id) for member in result.candidates[0].roster_members
    ] == [("team-a", "p1")]
    assert "team_id" not in type(result.candidates[0]).model_fields
    assert "player_id" not in type(result.candidates[0]).model_fields
    output = tmp_path / "portrait-candidates.png"
    assert cv2.imwrite(str(output), result.debug_overlay)
    assert cv2.imread(str(output)) is not None


def test_mirrored_roster_compositions_do_not_create_team_or_side_assignment() -> None:
    jett_attack = image(20, 40)
    jett_defense = image(20, 220)
    matcher = MinimapPortraitMatcher(
        {("jett", Side.ATTACK): jett_attack, ("jett", Side.DEFENSE): jett_defense}
    )
    roster_one = TeamRoster(
        team_id="left-team", players=[RosterPlayer(player_id="left-j", agent_id="jett")]
    )
    roster_two = TeamRoster(
        team_id="right-team", players=[RosterPlayer(player_id="right-j", agent_id="jett")]
    )

    first = matcher.match(jett_attack, [roster_one, roster_two])
    mirrored = matcher.match(jett_attack, [roster_two, roster_one])

    assert first.resolved_agent_id == mirrored.resolved_agent_id == "jett"
    assert [(item.agent_id, item.side) for item in first.candidates] == [
        (item.agent_id, item.side) for item in mirrored.candidates
    ]
    assert [
        (member.team_id, member.player_id) for member in first.candidates[0].roster_members
    ] == [("left-team", "left-j"), ("right-team", "right-j")]
    assert "team_id" not in type(first.candidates[0]).model_fields


def test_equal_side_templates_remain_ambiguous_and_do_not_force_a_side() -> None:
    icon = image(70, 160)
    matcher = MinimapPortraitMatcher(
        {("sage", Side.ATTACK): icon.copy(), ("sage", Side.DEFENSE): icon.copy()}
    )
    roster = TeamRoster(
        team_id="team", players=[RosterPlayer(player_id="sage-player", agent_id="sage")]
    )

    result = matcher.match(icon, [roster])

    assert result.ambiguous
    assert result.resolved_agent_id is None
    assert result.rejection_reason == "top_matches_ambiguous"
    assert {candidate.side for candidate in result.candidates} == {Side.ATTACK, Side.DEFENSE}


def test_missing_templates_and_roster_fail_with_diagnostics() -> None:
    icon = image(20, 40)
    roster = TeamRoster(team_id="team", players=[RosterPlayer(player_id="p1", agent_id="jett")])

    no_templates = MinimapPortraitMatcher({}).match(icon, [roster])
    no_roster = MinimapPortraitMatcher({("jett", Side.ATTACK): icon}).match(icon, [])

    assert no_templates.rejection_reason == "portrait_templates_missing"
    assert no_templates.candidates == ()
    assert no_roster.rejection_reason == "roster_metadata_missing"
    assert no_roster.candidates == ()


def test_empty_icon_crop_is_rejected_clearly() -> None:
    matcher = MinimapPortraitMatcher({})
    with pytest.raises(ValueError, match="non-empty uint8 BGR"):
        matcher.match(np.zeros((0, 0, 3), dtype=np.uint8), [])
