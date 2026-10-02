"""Constrained, ambiguity-aware identity assignment for registered minimap icons."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from pydantic import ValidationError

from valoscribe.detectors.minimap_portrait_matcher import TeamRoster
from valoscribe.types.persistent import (
    AssignmentObservation,
    AssignmentTrack,
    CandidateAssignment,
    NeutralAgentEvidenceDecision,
    NeutralPortraitCalibration,
    NeutralPortraitProvenance,
    NeutralPortraitTemplate,
    Side,
)


@dataclass(frozen=True)
class AssignmentResult:
    """One assignment decision per known player plus a map-space overlay."""

    assignments: tuple[CandidateAssignment, ...]
    debug_overlay: np.ndarray


@dataclass(frozen=True)
class AssignmentConfig:
    """Conservative gates and cost weights for one map/HUD profile."""

    maximum_displacement: float = 0.25
    minimum_registration_confidence: float = 0.5
    maximum_cost: float = 0.8
    ambiguity_margin: float = 0.05
    position_weight: float = 0.45
    portrait_weight: float = 0.45
    detector_weight: float = 0.1
    overlay_size: int = 512
    allow_neutral_portrait_compatibility: bool = False

    def __post_init__(self) -> None:
        if not math.isfinite(self.maximum_displacement) or self.maximum_displacement <= 0:
            raise ValueError("maximum_displacement must be finite and positive")
        for name in ("minimum_registration_confidence", "maximum_cost", "ambiguity_margin"):
            value = getattr(self, name)
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        weights = (self.position_weight, self.portrait_weight, self.detector_weight)
        if any(not math.isfinite(weight) or weight < 0 for weight in weights):
            raise ValueError("assignment weights must be finite and non-negative")
        if not math.isclose(sum(weights), 1.0, abs_tol=1e-9):
            raise ValueError("assignment weights must sum to 1")
        if self.overlay_size < 16:
            raise ValueError("overlay_size must be at least 16")


class ConstrainedPlayerAssigner:
    """Assign each icon candidate at most once and leave uncertain tracks unknown."""

    _FORBIDDEN = 1e6

    def __init__(self, config: AssignmentConfig | None = None) -> None:
        self.config = config or AssignmentConfig()

    def assign(
        self,
        tracks: list[AssignmentTrack],
        observations: list[AssignmentObservation],
    ) -> AssignmentResult:
        if len({track.player_id for track in tracks}) != len(tracks):
            raise ValueError("track player IDs must be unique")
        if len({item.candidate_id for item in observations}) != len(observations):
            raise ValueError("candidate IDs must be unique")
        overlay = np.zeros((self.config.overlay_size, self.config.overlay_size, 3), dtype=np.uint8)
        if not tracks:
            return AssignmentResult((), overlay)
        costs = [
            [self._pair_cost(track, candidate) for candidate in observations] for track in tracks
        ]
        matrix = [row + [self.config.maximum_cost] * len(tracks) for row in costs]
        selected = _hungarian(matrix)
        decisions: list[CandidateAssignment] = []
        for track_index, track in enumerate(tracks):
            col = selected[track_index]
            if col >= len(observations) or costs[track_index][col] >= self._FORBIDDEN:
                compatible = [value for value in costs[track_index] if value < self._FORBIDDEN]
                eligible = [value for value in compatible if value <= self.config.maximum_cost]
                if eligible:
                    decisions.append(
                        self._unknown(
                            track,
                            "candidate_claimed_by_better_assignment",
                            min(eligible),
                            [],
                        )
                    )
                elif compatible:
                    decisions.append(
                        self._unknown(
                            track,
                            "assignment_cost_above_maximum",
                            min(compatible),
                            [],
                        )
                    )
                else:
                    decisions.append(self._unknown(track, "no_compatible_candidate", None, []))
                continue
            cost = costs[track_index][col]
            alternatives = sorted(
                (
                    (tracks[index].player_id, pair_cost)
                    for index, row in enumerate(costs)
                    if index != track_index
                    for pair_cost in [row[col]]
                    if pair_cost < self._FORBIDDEN
                ),
                key=lambda item: (item[1], item[0]),
            )
            other_player_costs = [
                row[col]
                for index, row in enumerate(costs)
                if index != track_index and row[col] < self._FORBIDDEN
            ]
            candidate_margin = min(
                (abs(other_cost - cost) for other_cost in other_player_costs),
                default=1.0,
            )
            alternative_costs = [
                value
                for index, value in enumerate(costs[track_index])
                if index != col and value < self._FORBIDDEN
            ]
            alternative_margin = min(
                (abs(other_cost - cost) for other_cost in alternative_costs),
                default=1.0,
            )
            if cost > self.config.maximum_cost:
                decisions.append(
                    self._unknown(
                        track, "assignment_cost_above_maximum", cost, [p for p, _ in alternatives]
                    )
                )
                continue
            if candidate_margin < self.config.ambiguity_margin:
                decisions.append(
                    self._unknown(
                        track,
                        "candidate_competes_for_multiple_players",
                        cost,
                        [
                            tracks[i].player_id
                            for i, value in enumerate(costs)
                            if i != track_index and value[col] < self._FORBIDDEN
                        ],
                    )
                )
                continue
            if alternative_margin < self.config.ambiguity_margin:
                decisions.append(
                    self._unknown(
                        track,
                        "assignment_ambiguous",
                        cost,
                        [
                            observations[i].candidate_id
                            for i, value in enumerate(costs[track_index])
                            if i != col and value < self._FORBIDDEN
                        ],
                    )
                )
                continue
            observation = observations[col]
            selected_portrait = max(
                (
                    match
                    for match in observation.portrait_matches
                    if match.agent_id == track.agent_id
                    and _portrait_side_compatible(track.side, match.side, self.config)
                ),
                key=lambda match: match.confidence,
            )
            confidence = min(
                max(0.0, min(1.0, 1.0 - cost)),
                observation.detector_confidence,
                observation.registration_confidence,
                selected_portrait.confidence,
            )
            evidence = [*observation.evidence, f"hungarian_assignment_cost:{cost:.6f}"]
            evidence.append(
                f"portrait_template:{selected_portrait.template_id}:{selected_portrait.confidence:.6f}"
            )
            decisions.append(
                CandidateAssignment(
                    player_id=track.player_id,
                    candidate_id=observation.candidate_id,
                    confidence=confidence,
                    cost=cost,
                    alternate_player_ids=[p for p, _ in alternatives],
                    evidence=evidence,
                )
            )
            self._draw(overlay, observation, track.player_id, True)
        return AssignmentResult(tuple(decisions), overlay)

    def _pair_cost(self, track: AssignmentTrack, candidate: AssignmentObservation) -> float:
        if track.team_id != candidate.team_id:
            return self._FORBIDDEN
        if (
            track.side is not Side.UNKNOWN
            and candidate.side is not Side.UNKNOWN
            and track.side is not candidate.side
        ):
            return self._FORBIDDEN
        if candidate.registration_confidence < self.config.minimum_registration_confidence:
            return self._FORBIDDEN
        matches = [
            match
            for match in candidate.portrait_matches
            if match.agent_id == track.agent_id
            and _portrait_side_compatible(track.side, match.side, self.config)
        ]
        if not matches:
            return self._FORBIDDEN
        portrait_score = max(match.confidence for match in matches)
        if track.previous_position is None:
            position_cost = 0.5
        else:
            distance = math.hypot(
                candidate.canonical_point.x - track.previous_position.x,
                candidate.canonical_point.y - track.previous_position.y,
            )
            if distance > self.config.maximum_displacement:
                return self._FORBIDDEN
            position_cost = distance / self.config.maximum_displacement
        weights = self.config
        return (
            weights.position_weight * position_cost
            + weights.portrait_weight * (1.0 - portrait_score)
            + weights.detector_weight * (1.0 - candidate.detector_confidence)
        )

    def _unknown(
        self, track: AssignmentTrack, reason: str, cost: float | None, alternatives: list[str]
    ) -> CandidateAssignment:
        return CandidateAssignment(
            player_id=track.player_id,
            candidate_id=None,
            confidence=0.0,
            cost=None,
            alternate_player_ids=alternatives,
            evidence=[f"assignment_rejected:{reason}"]
            + ([f"best_cost:{cost:.6f}"] if cost is not None else []),
            rejection_reason=reason,
        )

    def _draw(
        self, overlay: np.ndarray, observation: AssignmentObservation, label: str, accepted: bool
    ) -> None:
        size = self.config.overlay_size
        point = (
            round(observation.canonical_point.x * (size - 1)),
            round(observation.canonical_point.y * (size - 1)),
        )
        color = (0, 255, 0) if accepted else (0, 0, 255)
        cv2.circle(overlay, point, 5, color, 1)
        cv2.putText(
            overlay,
            label,
            (min(point[0] + 5, size - 1), max(point[1] - 4, 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.3,
            color,
            1,
            cv2.LINE_AA,
        )


@dataclass(frozen=True)
class AssignmentAdmission:
    """Admission result keeping rejected evidence outside identity inputs."""

    observation: AssignmentObservation | None
    rejection_reason: str | None


def admit_neutral_agent_evidence(
    observation: AssignmentObservation,
    decision: NeutralAgentEvidenceDecision,
    *,
    calibration: NeutralPortraitCalibration,
    templates: list[NeutralPortraitTemplate],
    asset_root: Path,
    candidate_crop: np.ndarray,
    provenance: NeutralPortraitProvenance,
    rosters: list[TeamRoster],
    independently_evidenced_team: bool,
    accepted_registration: bool,
) -> AssignmentAdmission:
    """Recompute evidence from separately supplied trusted inputs before assignment."""
    if not independently_evidenced_team:
        return AssignmentAdmission(None, "team_evidence_not_independent")
    if not accepted_registration:
        return AssignmentAdmission(None, "registration_not_accepted")
    try:
        calibration = NeutralPortraitCalibration.model_validate(calibration.__dict__)
        decision = NeutralAgentEvidenceDecision.model_validate(decision.__dict__)
        provenance = NeutralPortraitProvenance.model_validate(provenance.__dict__)
        templates = [NeutralPortraitTemplate.model_validate(item.__dict__) for item in templates]
        rosters = [TeamRoster.model_validate(roster.__dict__) for roster in rosters]
    except (AttributeError, TypeError, ValidationError):
        return AssignmentAdmission(None, "neutral_evidence_contract_invalid")
    if calibration.status != "accepted" or calibration.reviewer_id is None:
        return AssignmentAdmission(None, "calibration_not_accepted")
    from valoscribe.detectors.neutral_portrait_evidence import _calibration_policy_digest

    if (
        decision.calibration_status != "accepted"
        or decision.calibration_policy_sha256 != _calibration_policy_digest(calibration)
        or decision.template_set_sha256 != calibration.template_set_sha256
    ):
        return AssignmentAdmission(None, "calibration_policy_mismatch")
    if (
        not calibration.required_agent_ids
        or set(decision.required_agent_coverage) != set(calibration.required_agent_ids)
        or set(decision.observed_agent_coverage) != set(calibration.required_agent_ids)
        or {match.agent_id for match in decision.raw_scores} != set(calibration.required_agent_ids)
    ):
        return AssignmentAdmission(None, "template_coverage_incomplete")
    if not decision.accepted or decision.resolved_agent_id is None:
        return AssignmentAdmission(None, "agent_decision_not_accepted")
    from valoscribe.detectors.neutral_portrait_evidence import (
        NeutralPortraitEvidenceMatcher,
        _image_digest,
    )

    try:
        actual_crop_digest = _image_digest(candidate_crop)
    except (AttributeError, TypeError, ValueError):
        return AssignmentAdmission(None, "candidate_crop_invalid")
    if (
        provenance.candidate_id != observation.candidate_id
        or decision.candidate_id != observation.candidate_id
        or provenance.source_crop_sha256 != actual_crop_digest
    ):
        return AssignmentAdmission(None, "agent_decision_provenance_mismatch")
    if (
        decision.minimum_confidence != calibration.minimum_confidence
        or decision.distinct_agent_margin != calibration.distinct_agent_margin
    ):
        return AssignmentAdmission(None, "agent_decision_threshold_mismatch")
    ranked = sorted(decision.best_score_by_agent.items(), key=lambda item: (-item[1], item[0]))
    if not ranked or ranked[0][0] != decision.resolved_agent_id:
        return AssignmentAdmission(None, "agent_decision_not_accepted")
    runner_up = ranked[1][1] if len(ranked) > 1 else 0.0
    if (
        ranked[0][1] < calibration.minimum_confidence
        or ranked[0][1] - runner_up < calibration.distinct_agent_margin
    ):
        return AssignmentAdmission(None, "agent_decision_below_calibration")
    matcher = NeutralPortraitEvidenceMatcher(templates, asset_root, calibration)
    try:
        verified = matcher.match(candidate_crop, rosters, candidate_id=observation.candidate_id)
    except (TypeError, ValueError):
        return AssignmentAdmission(None, "candidate_crop_invalid")
    if not verified.accepted or verified != decision:
        return AssignmentAdmission(None, "agent_decision_authentication_failed")
    resolved_matches = [
        match for match in verified.raw_scores if match.agent_id == verified.resolved_agent_id
    ]
    if not resolved_matches:
        return AssignmentAdmission(None, "resolved_agent_has_no_raw_evidence")
    best_score = max(match.confidence for match in resolved_matches)
    best_matches = [match for match in resolved_matches if match.confidence == best_score]
    if len({match.side for match in best_matches}) > 1:
        return AssignmentAdmission(None, "resolved_agent_side_evidence_conflict")
    best_match = min(best_matches, key=lambda match: match.template_id)
    admitted = observation.model_copy(update={"portrait_matches": [best_match]})
    return AssignmentAdmission(admitted, None)


def _portrait_side_compatible(
    track_side: Side, portrait_side: Side, config: AssignmentConfig
) -> bool:
    if track_side is Side.UNKNOWN:
        return True
    if portrait_side is track_side:
        return True
    return config.allow_neutral_portrait_compatibility and portrait_side is Side.UNKNOWN


def _hungarian(costs: list[list[float]]) -> list[int]:
    """Deterministic O(rows²·columns) rectangular Hungarian minimization."""
    rows = len(costs)
    columns = len(costs[0]) if rows else 0
    if rows > columns or any(len(row) != columns for row in costs):
        raise ValueError("Hungarian matrix must be rectangular with rows <= columns")
    u = [0.0] * (rows + 1)
    v = [0.0] * (columns + 1)
    p = [0] * (columns + 1)
    way = [0] * (columns + 1)
    for i in range(1, rows + 1):
        p[0] = i
        j0 = 0
        minv = [math.inf] * (columns + 1)
        used = [False] * (columns + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = math.inf
            j1 = 0
            for j in range(1, columns + 1):
                if not used[j]:
                    cur = costs[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j] = cur
                        way[j] = j0
                    if minv[j] < delta:
                        delta = minv[j]
                        j1 = j
            for j in range(columns + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    result = [-1] * rows
    for j in range(1, columns + 1):
        if p[j] != 0:
            result[p[j] - 1] = j - 1
    return result
