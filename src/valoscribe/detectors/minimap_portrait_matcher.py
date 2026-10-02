"""Roster-constrained, side-template portrait candidates for minimap icons."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import cv2
import numpy as np
from pydantic import Field, field_validator

from valoscribe.types.persistent import (
    AgentPortraitTemplateMatch,
    PersistentModel,
    PortraitRosterMember,
    Side,
)


class RosterPlayer(PersistentModel):
    """Known player/agent metadata; roster membership is not a detection."""

    schema_version: Literal["1.0"] = "1.0"
    player_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)

    @field_validator("player_id", "agent_id")
    @classmethod
    def identifiers_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("roster identifiers must not be blank")
        return value


class TeamRoster(PersistentModel):
    """Known composition from match metadata, never inferred from color/side."""

    schema_version: Literal["1.0"] = "1.0"
    team_id: str = Field(min_length=1)
    players: list[RosterPlayer] = Field(min_length=1)

    @field_validator("team_id")
    @classmethod
    def team_id_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("team_id must not be blank")
        return value


@dataclass(frozen=True)
class PortraitMatchResult:
    """Ranked visual matches and an optional conservative resolution."""

    candidates: tuple[AgentPortraitTemplateMatch, ...]
    resolved_agent_id: str | None
    ambiguous: bool
    rejection_reason: str | None
    debug_overlay: np.ndarray


class MinimapPortraitMatcher:
    """Match icon crops against side-specific templates within known rosters.

    The matcher reports candidate evidence only. It never assigns a team, player,
    or side to a broadcast color or minimap position.
    """

    def __init__(
        self,
        templates: dict[tuple[str, Side], np.ndarray],
        *,
        minimum_confidence: float = 0.65,
        ambiguity_margin: float = 0.04,
    ) -> None:
        if not 0.0 <= minimum_confidence <= 1.0:
            raise ValueError("minimum_confidence must be between 0 and 1")
        if not 0.0 <= ambiguity_margin <= 1.0:
            raise ValueError("ambiguity_margin must be between 0 and 1")
        self.minimum_confidence = minimum_confidence
        self.ambiguity_margin = ambiguity_margin
        self.templates: dict[tuple[str, Side], np.ndarray] = {}
        for (agent_id, side), image in templates.items():
            if not agent_id.strip() or side not in {Side.ATTACK, Side.DEFENSE}:
                continue
            if _valid_image(image):
                self.templates[(agent_id, side)] = image.copy()

    @classmethod
    def from_directory(
        cls,
        template_dir: Path,
        *,
        minimum_confidence: float = 0.65,
        ambiguity_margin: float = 0.04,
    ) -> MinimapPortraitMatcher:
        """Load `<side>/<agent>_<atk|def>.png|jpg`; missing assets are allowed."""
        templates: dict[tuple[str, Side], np.ndarray] = {}
        for side, suffix in ((Side.ATTACK, "atk"), (Side.DEFENSE, "def")):
            directory = Path(template_dir) / side.value
            if not directory.is_dir():
                continue
            for path in sorted(
                (*directory.glob(f"*_{suffix}.png"), *directory.glob(f"*_{suffix}.jpg"))
            ):
                image = cv2.imread(str(path), cv2.IMREAD_COLOR)
                if image is not None:
                    templates[(path.stem[: -(len(suffix) + 1)], side)] = image
        return cls(
            templates,
            minimum_confidence=minimum_confidence,
            ambiguity_margin=ambiguity_margin,
        )

    def match(
        self,
        icon_crop: np.ndarray,
        rosters: list[TeamRoster],
    ) -> PortraitMatchResult:
        """Return ranked roster-constrained candidates and a diagnostic overlay."""
        if not _valid_image(icon_crop):
            raise ValueError("icon_crop must be a non-empty uint8 BGR image")
        overlay = icon_crop.copy()
        if not rosters:
            return self._rejected(overlay, "roster_metadata_missing")
        if not self.templates:
            return self._rejected(overlay, "portrait_templates_missing")

        roster_members: dict[str, list[tuple[str, str]]] = {}
        for roster in rosters:
            for player in roster.players:
                roster_members.setdefault(player.agent_id, []).append(
                    (roster.team_id, player.player_id)
                )
        if not roster_members:
            return self._rejected(overlay, "roster_metadata_empty")

        candidates: list[AgentPortraitTemplateMatch] = []
        for (agent_id, side), template in self.templates.items():
            members = roster_members.get(agent_id)
            if not members:
                continue
            confidence = _similarity(icon_crop, template)
            candidates.append(
                AgentPortraitTemplateMatch(
                    agent_id=agent_id,
                    side=side,
                    confidence=confidence,
                    template_id=f"{agent_id}:{side.value}",
                    roster_members=[
                        PortraitRosterMember(team_id=team, player_id=player)
                        for team, player in sorted(set(members))
                    ],
                    evidence=[
                        "icon_crop_template_similarity",
                        "agent_present_in_roster_metadata",
                    ],
                )
            )
        candidates.sort(
            key=lambda candidate: (-candidate.confidence, candidate.agent_id, candidate.side.value)
        )
        if not candidates:
            return self._rejected(overlay, "no_roster_agents_have_templates")

        top = candidates[0]
        margin = top.confidence - candidates[1].confidence if len(candidates) > 1 else 1.0
        ambiguous = top.confidence < self.minimum_confidence or margin < self.ambiguity_margin
        reason = None
        resolved_agent = None
        if top.confidence < self.minimum_confidence:
            reason = "best_match_below_minimum_confidence"
        elif margin < self.ambiguity_margin:
            reason = "top_matches_ambiguous"
        else:
            resolved_agent = top.agent_id
        _draw_candidates(overlay, candidates)
        return PortraitMatchResult(
            candidates=tuple(candidates),
            resolved_agent_id=resolved_agent,
            ambiguous=ambiguous,
            rejection_reason=reason,
            debug_overlay=overlay,
        )

    def _rejected(self, overlay: np.ndarray, reason: str) -> PortraitMatchResult:
        cv2.putText(
            overlay,
            reason,
            (2, max(12, min(20, overlay.shape[0] - 2))),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.35,
            (0, 0, 255),
            1,
            cv2.LINE_AA,
        )
        return PortraitMatchResult((), None, True, reason, overlay)


def _valid_image(image: object) -> bool:
    return (
        isinstance(image, np.ndarray)
        and image.dtype == np.uint8
        and image.ndim == 3
        and image.shape[0] > 0
        and image.shape[1] > 0
        and image.shape[2] == 3
    )


def _similarity(icon: np.ndarray, template: np.ndarray) -> float:
    resized = cv2.resize(template, (icon.shape[1], icon.shape[0]), interpolation=cv2.INTER_AREA)
    difference = cv2.absdiff(icon, resized)
    return float(np.clip(1.0 - np.mean(difference, dtype=np.float64) / 255.0, 0.0, 1.0))


def _draw_candidates(overlay: np.ndarray, candidates: list[AgentPortraitTemplateMatch]) -> None:
    for index, candidate in enumerate(candidates[:5]):
        cv2.putText(
            overlay,
            f"{candidate.agent_id}/{candidate.side.value}:{candidate.confidence:.3f}",
            (2, min(14 + index * 12, overlay.shape[0] - 2)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.32,
            (0, 255, 0) if index == 0 else (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
