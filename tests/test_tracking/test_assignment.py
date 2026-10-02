from __future__ import annotations

import hashlib
from pathlib import Path

import cv2
import numpy as np
import pytest

from valoscribe.detectors.minimap_portrait_matcher import RosterPlayer, TeamRoster
from valoscribe.detectors.neutral_portrait_evidence import (
    NeutralPortraitEvidenceMatcher,
    _image_digest,
    _template_set_digest,
)
from valoscribe.tracking.assignment import (
    AssignmentConfig,
    ConstrainedPlayerAssigner,
    admit_neutral_agent_evidence,
)
from valoscribe.types.persistent import (
    AgentPortraitTemplateMatch,
    AssignmentObservation,
    AssignmentTrack,
    NeutralAgentEvidenceDecision,
    NeutralPortraitCalibration,
    NeutralPortraitProvenance,
    NeutralPortraitTemplate,
    NormalizedPoint,
    PortraitRosterMember,
    Side,
)


def portrait(agent: str, score: float = 0.95) -> AgentPortraitTemplateMatch:
    return AgentPortraitTemplateMatch(
        agent_id=agent,
        side=Side.ATTACK,
        confidence=score,
        template_id=f"{agent}:attack",
        roster_members=[PortraitRosterMember(team_id="alpha", player_id=f"{agent}-player")],
        evidence=["synthetic_template_match"],
    )


def track(player: str, agent: str, x: float | None, team: str = "alpha") -> AssignmentTrack:
    return AssignmentTrack(
        player_id=player,
        agent_id=agent,
        team_id=team,
        side=Side.ATTACK,
        previous_position=None if x is None else NormalizedPoint(x=x, y=0.5),
    )


def observation(
    candidate: str,
    agent_scores: list[tuple[str, float]],
    x: float,
    *,
    team: str = "alpha",
    side: Side = Side.ATTACK,
    registration: float = 0.95,
) -> AssignmentObservation:
    return AssignmentObservation(
        candidate_id=candidate,
        team_id=team,
        side=side,
        canonical_point=NormalizedPoint(x=x, y=0.5),
        detector_confidence=0.95,
        registration_confidence=registration,
        portrait_matches=[portrait(agent, score) for agent, score in agent_scores],
        evidence=["synthetic_registered_icon"],
    )


def test_hungarian_assignment_handles_crossing_players_and_emits_overlay() -> None:
    tracks = [track("p1", "jett", 0.4), track("p2", "sage", 0.6)]
    # Candidate order is intentionally reversed relative to roster order.
    candidates = [
        observation("icon-sage", [("sage", 0.95)], 0.58),
        observation("icon-jett", [("jett", 0.94)], 0.42),
    ]

    result = ConstrainedPlayerAssigner().assign(tracks, candidates)

    assert [item.candidate_id for item in result.assignments] == ["icon-jett", "icon-sage"]
    assert all(item.confidence > 0.8 for item in result.assignments)
    assert np.count_nonzero(result.debug_overlay) > 0


def test_missing_prior_position_uses_portrait_but_duplicate_agents_stay_ambiguous() -> None:
    tracks = [track("p1", "jett", None), track("p2", "jett", None)]
    candidates = [
        observation("icon-1", [("jett", 0.9)], 0.4),
        observation("icon-2", [("jett", 0.9)], 0.6),
    ]

    result = ConstrainedPlayerAssigner().assign(tracks, candidates)

    assert all(item.candidate_id is None for item in result.assignments)
    assert all(
        item.rejection_reason == "candidate_competes_for_multiple_players"
        for item in result.assignments
    )


def test_mirror_roster_and_impossible_team_side_registration_are_gated() -> None:
    tracks = [track("alpha-jett", "jett", 0.4), track("beta-jett", "jett", 0.6, team="beta")]
    candidates = [
        observation("alpha-icon", [("jett", 0.95)], 0.4),
        observation("wrong-side", [("jett", 0.95)], 0.6, team="beta", side=Side.DEFENSE),
        observation("unregistered", [("jett", 0.95)], 0.6, team="beta", registration=0.1),
    ]

    result = ConstrainedPlayerAssigner().assign(tracks, candidates)

    assert result.assignments[0].candidate_id == "alpha-icon"
    assert result.assignments[1].candidate_id is None
    assert result.assignments[1].rejection_reason == "no_compatible_candidate"


def test_ties_and_cost_gate_leave_tracks_unassigned() -> None:
    tracks = [track("p1", "jett", 0.5)]
    tied = [observation("one", [("jett", 0.9)], 0.5), observation("two", [("jett", 0.9)], 0.5)]

    result = ConstrainedPlayerAssigner().assign(tracks, tied)

    assert result.assignments[0].candidate_id is None
    assert result.assignments[0].rejection_reason == "assignment_ambiguous"

    strict = ConstrainedPlayerAssigner(AssignmentConfig(maximum_cost=0.1))
    too_far = [observation("far", [("jett", 0.9)], 0.6)]
    rejected = strict.assign(tracks, too_far)
    assert rejected.assignments[0].candidate_id is None
    assert rejected.assignments[0].rejection_reason == "assignment_cost_above_maximum"


def test_assignment_confidence_is_capped_by_weakest_evidence() -> None:
    assigner = ConstrainedPlayerAssigner()
    one_track = [track("p1", "jett", None)]

    for detector, registration, portrait_score, expected in (
        (0.95, 0.51, 0.95, 0.51),
        (0.95, 0.95, 0.2, 0.2),
        (0.4, 0.95, 0.95, 0.4),
    ):
        candidate = observation(
            "icon",
            [("jett", portrait_score)],
            0.5,
            registration=registration,
        ).model_copy(update={"detector_confidence": detector})

        result = assigner.assign(one_track, [candidate])

        assert result.assignments[0].candidate_id == "icon"
        assert result.assignments[0].confidence == pytest.approx(expected)
        assert result.assignments[0].confidence <= min(detector, registration, portrait_score)


def test_exactly_tied_alternative_candidate_is_reported() -> None:
    assigner = ConstrainedPlayerAssigner()
    candidates = [
        observation("candidate-a", [("jett", 0.9)], 0.5),
        observation("candidate-b", [("jett", 0.9)], 0.5),
    ]

    result = assigner.assign([track("p1", "jett", 0.5)], candidates)

    assert result.assignments[0].rejection_reason == "assignment_ambiguous"
    assert result.assignments[0].alternate_player_ids == ["candidate-b"]


def test_neutral_side_compatibility_is_explicit_and_known_contradictions_stay_forbidden() -> None:
    neutral = portrait("jett").model_copy(update={"side": Side.UNKNOWN})
    candidate = observation("neutral", [("jett", 0.95)], 0.5).model_copy(
        update={"portrait_matches": [neutral]}
    )
    one_track = [track("p1", "jett", None)]

    default = ConstrainedPlayerAssigner().assign(one_track, [candidate])
    enabled = ConstrainedPlayerAssigner(
        AssignmentConfig(allow_neutral_portrait_compatibility=True)
    ).assign(one_track, [candidate])
    contradictory = candidate.model_copy(
        update={"portrait_matches": [portrait("jett").model_copy(update={"side": Side.DEFENSE})]}
    )
    contradiction_result = ConstrainedPlayerAssigner(
        AssignmentConfig(allow_neutral_portrait_compatibility=True)
    ).assign(one_track, [contradictory])

    assert default.assignments[0].candidate_id is None
    assert enabled.assignments[0].candidate_id == "neutral"
    assert contradiction_result.assignments[0].candidate_id is None


def _authenticated_evidence(tmp_path: Path, candidate: str = "raw-candidate"):
    agents = ["jett", "sage", "sova", "cypher", "omen", "phoenix", "chamber"]
    templates = []
    for index, agent in enumerate(agents):
        for side, value in ((Side.ATTACK, 10 if index == 0 else 255),):
            image = np.full((12, 12, 3), value, dtype=np.uint8)
            mask = np.full((12, 12), 255, dtype=np.uint8)
            image_path = tmp_path / f"{agent}-{side.value}-image.png"
            mask_path = tmp_path / f"{agent}-{side.value}-mask.png"
            assert cv2.imwrite(str(image_path), image)
            assert cv2.imwrite(str(mask_path), mask)
            templates.append(
                NeutralPortraitTemplate(
                    template_id=f"{agent}:{side.value}",
                    agent_id=agent,
                    source_id=f"vod-{agent}",
                    source_type="live",
                    frame_id=f"frame-{agent}",
                    frame_sha256=hashlib.sha256(agent.encode()).hexdigest(),
                    hud_profile_id="synthetic-hud",
                    frame_width=1920,
                    frame_height=1080,
                    crop_x=100 + index,
                    crop_y=200,
                    crop_width=12,
                    crop_height=12,
                    image_path=image_path.name,
                    image_sha256=hashlib.sha256(image_path.read_bytes()).hexdigest(),
                    mask_path=mask_path.name,
                    mask_sha256=hashlib.sha256(mask_path.read_bytes()).hexdigest(),
                    acquisition_role="calibration",
                    review_status="accepted",
                    reviewer_id="reviewer",
                    side=side,
                )
            )
    # Deliberately lower-scoring contradictory same-agent evidence must remain diagnostic only.
    image = np.full((12, 12, 3), 214, dtype=np.uint8)
    mask = np.full((12, 12), 255, dtype=np.uint8)
    image_path, mask_path = tmp_path / "jett-defense-image.png", tmp_path / "jett-defense-mask.png"
    assert cv2.imwrite(str(image_path), image)
    assert cv2.imwrite(str(mask_path), mask)
    templates.append(
        NeutralPortraitTemplate(
            template_id="jett:defense",
            agent_id="jett",
            source_id="vod-jett-defense",
            source_type="live",
            frame_id="frame-jett-defense",
            frame_sha256=hashlib.sha256(b"jett-defense").hexdigest(),
            hud_profile_id="synthetic-hud",
            frame_width=1920,
            frame_height=1080,
            crop_x=101,
            crop_y=200,
            crop_width=12,
            crop_height=12,
            image_path=image_path.name,
            image_sha256=hashlib.sha256(image_path.read_bytes()).hexdigest(),
            mask_path=mask_path.name,
            mask_sha256=hashlib.sha256(mask_path.read_bytes()).hexdigest(),
            acquisition_role="calibration",
            review_status="accepted",
            reviewer_id="reviewer",
            side=Side.DEFENSE,
        )
    )
    calibration = NeutralPortraitCalibration(
        status="accepted",
        template_set_sha256=_template_set_digest(templates),
        required_agent_ids=agents,
        training_frame_ids=[item.frame_id for item in templates],
        heldout_frame_ids=["heldout"],
        negative_control_ids=["negative"],
        minimum_confidence=0.7,
        distinct_agent_margin=0.05,
        calibration_measurements={"synthetic_only": 1.0},
        reviewer_id="reviewer",
    )
    roster = TeamRoster(
        team_id="alpha",
        players=[RosterPlayer(player_id=f"{agent}-player", agent_id=agent) for agent in agents],
    )
    crop = np.full((12, 12, 3), 10, dtype=np.uint8)
    decision = NeutralPortraitEvidenceMatcher(templates, tmp_path, calibration).match(
        crop, [roster], candidate_id=candidate
    )
    assert decision.accepted
    return templates, calibration, roster, crop, decision


def test_neutral_admission_authenticates_recomputation_and_only_admits_best_template(
    tmp_path: Path,
) -> None:
    templates, calibration, roster, crop, decision = _authenticated_evidence(tmp_path)
    raw_observation = observation("raw-candidate", [], 0.5, side=Side.UNKNOWN)
    provenance = NeutralPortraitProvenance(
        candidate_id="raw-candidate", source_crop_sha256=_image_digest(crop)
    )
    kwargs = dict(
        calibration=calibration,
        templates=templates,
        asset_root=tmp_path,
        candidate_crop=crop,
        provenance=provenance,
        rosters=[roster],
        independently_evidenced_team=True,
        accepted_registration=True,
    )

    admitted = admit_neutral_agent_evidence(raw_observation, decision, **kwargs)

    assert admitted.observation is not None
    assert [
        (match.agent_id, match.side, match.confidence)
        for match in admitted.observation.portrait_matches
    ] == [("jett", Side.ATTACK, 1.0)]
    defense_assigner = ConstrainedPlayerAssigner(
        AssignmentConfig(allow_neutral_portrait_compatibility=True)
    )
    result = defense_assigner.assign(
        [track("jett-player", "jett", None).model_copy(update={"side": Side.DEFENSE})],
        [admitted.observation],
    )
    assert result.assignments[0].candidate_id is None

    forged = decision.model_copy(
        update={
            "raw_scores": [
                item.model_copy(update={"side": Side.UNKNOWN})
                if item.template_id == "jett:attack"
                else item
                for item in decision.raw_scores
            ]
        }
    )
    assert admit_neutral_agent_evidence(raw_observation, forged, **kwargs).observation is None
    forged_score = decision.model_copy(
        update={
            "raw_scores": [
                item.model_copy(update={"confidence": 0.99})
                if item.template_id == "jett:attack"
                else item
                for item in decision.raw_scores
            ],
            "best_score_by_agent": {**decision.best_score_by_agent, "jett": 0.99},
        }
    )
    validated_forged_score = NeutralAgentEvidenceDecision.model_validate(
        forged_score.model_dump()
    )
    assert validated_forged_score.accepted is decision.accepted
    assert validated_forged_score.template_set_sha256 == decision.template_set_sha256
    assert validated_forged_score.calibration_policy_sha256 == decision.calibration_policy_sha256
    score_forgery_admission = admit_neutral_agent_evidence(
        raw_observation, validated_forged_score, **kwargs
    )
    assert score_forgery_admission.observation is None
    assert score_forgery_admission.rejection_reason == "agent_decision_authentication_failed"

    forged_template = decision.model_copy(
        update={
            "raw_scores": [
                item.model_copy(update={"template_id": "jett:forged-attack"})
                if item.template_id == "jett:attack"
                else item
                for item in decision.raw_scores
            ]
        }
    )
    validated_forged_template = NeutralAgentEvidenceDecision.model_validate(
        forged_template.model_dump()
    )
    forged_attack = next(
        item for item in validated_forged_template.raw_scores if item.agent_id == "jett"
    )
    original_attack = next(item for item in decision.raw_scores if item.agent_id == "jett")
    assert validated_forged_template.accepted is decision.accepted
    assert validated_forged_template.template_set_sha256 == decision.template_set_sha256
    assert validated_forged_template.calibration_policy_sha256 == decision.calibration_policy_sha256
    assert forged_attack.confidence == original_attack.confidence
    assert forged_attack.side is original_attack.side
    template_forgery_admission = admit_neutral_agent_evidence(
        raw_observation, validated_forged_template, **kwargs
    )
    assert template_forgery_admission.observation is None
    assert template_forgery_admission.rejection_reason == "agent_decision_authentication_failed"
    other_candidate = provenance.model_copy(update={"candidate_id": "another-candidate"})
    assert (
        admit_neutral_agent_evidence(
            raw_observation, decision, **{**kwargs, "provenance": other_candidate}
        ).observation
        is None
    )
    assert (
        admit_neutral_agent_evidence(
            raw_observation, decision, **{**kwargs, "candidate_crop": np.zeros_like(crop)}
        ).observation
        is None
    )
    assert (
        admit_neutral_agent_evidence(
            raw_observation, decision, **{**kwargs, "candidate_crop": "not-an-image"}
        ).observation
        is None
    )
    altered_manifest = [
        item.model_copy(update={"acquisition_role": "heldout"})
        if item.template_id == "jett:attack"
        else item
        for item in templates
    ]
    assert (
        admit_neutral_agent_evidence(
            raw_observation, decision, **{**kwargs, "templates": altered_manifest}
        ).observation
        is None
    )
    altered_policy = calibration.model_copy(update={"minimum_confidence": 0.75})
    assert (
        admit_neutral_agent_evidence(
            raw_observation, decision, **{**kwargs, "calibration": altered_policy}
        ).observation
        is None
    )


def test_neutral_admission_rejects_tied_best_templates_with_conflicting_sides(
    tmp_path: Path,
) -> None:
    templates, calibration, roster, crop, _ = _authenticated_evidence(tmp_path)
    attack = next(item for item in templates if item.template_id == "jett:attack")
    conflict = attack.model_copy(
        update={
            "template_id": "jett:second-side",
            "source_id": "vod-jett-second",
            "frame_id": "frame-jett-second",
            "frame_sha256": hashlib.sha256(b"jett-second").hexdigest(),
            "side": Side.DEFENSE,
        }
    )
    templates = [*templates, conflict]
    calibration = calibration.model_copy(
        update={
            "template_set_sha256": _template_set_digest(templates),
            "training_frame_ids": [*calibration.training_frame_ids, conflict.frame_id],
        }
    )
    decision = NeutralPortraitEvidenceMatcher(templates, tmp_path, calibration).match(
        crop, [roster], candidate_id="raw-candidate"
    )
    assert decision.accepted
    admission = admit_neutral_agent_evidence(
        observation("raw-candidate", [], 0.5),
        decision,
        calibration=calibration,
        templates=templates,
        asset_root=tmp_path,
        candidate_crop=crop,
        provenance=NeutralPortraitProvenance(
            candidate_id="raw-candidate", source_crop_sha256=_image_digest(crop)
        ),
        rosters=[roster],
        independently_evidenced_team=True,
        accepted_registration=True,
    )
    assert admission.observation is None
    assert admission.rejection_reason == "resolved_agent_side_evidence_conflict"


def test_neutral_admission_requires_independent_team_and_registration_gates(tmp_path: Path) -> None:
    templates, calibration, roster, crop, decision = _authenticated_evidence(tmp_path)
    raw_observation = observation("raw-candidate", [], 0.5)
    kwargs = dict(
        calibration=calibration,
        templates=templates,
        asset_root=tmp_path,
        candidate_crop=crop,
        provenance=NeutralPortraitProvenance(
            candidate_id="raw-candidate", source_crop_sha256=_image_digest(crop)
        ),
        rosters=[roster],
        accepted_registration=True,
    )
    assert (
        admit_neutral_agent_evidence(
            raw_observation, decision, **kwargs, independently_evidenced_team=False
        ).observation
        is None
    )
    assert (
        admit_neutral_agent_evidence(
            raw_observation,
            decision,
            **{**kwargs, "accepted_registration": False},
            independently_evidenced_team=True,
        ).observation
        is None
    )


def test_duplicate_inputs_and_invalid_config_are_rejected() -> None:
    assigner = ConstrainedPlayerAssigner()
    one = track("p1", "jett", None)
    candidate = observation("icon", [("jett", 0.9)], 0.5)
    with pytest.raises(ValueError, match="track player IDs"):
        assigner.assign([one, one], [candidate])
    with pytest.raises(ValueError, match="candidate IDs"):
        assigner.assign([one], [candidate, candidate])
    with pytest.raises(ValueError, match="weights must sum"):
        AssignmentConfig(position_weight=0.5, portrait_weight=0.5, detector_weight=0.5)
