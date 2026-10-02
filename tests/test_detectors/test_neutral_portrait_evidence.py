from __future__ import annotations

import hashlib
from pathlib import Path

import cv2
import numpy as np

from valoscribe.detectors.minimap_portrait_matcher import RosterPlayer, TeamRoster
from valoscribe.detectors.neutral_portrait_evidence import (
    NeutralPortraitEvidenceMatcher,
    _template_set_digest,
)
from valoscribe.types.persistent import NeutralPortraitCalibration, NeutralPortraitTemplate, Side


def _write_asset(root: Path, name: str, image: np.ndarray) -> tuple[str, str]:
    path = root / f"{name}.png"
    assert cv2.imwrite(str(path), image)
    return path.name, hashlib.sha256(path.read_bytes()).hexdigest()


def _templates(root: Path, agents: list[str]) -> list[NeutralPortraitTemplate]:
    result = []
    for index, agent in enumerate(agents):
        image = np.full((12, 12, 3), 20 + index * 20, dtype=np.uint8)
        mask = np.full((12, 12), 255, dtype=np.uint8)
        image_path, image_hash = _write_asset(root, f"{agent}-portrait", image)
        mask_path, mask_hash = _write_asset(root, f"{agent}-mask", mask)
        result.append(
            NeutralPortraitTemplate(
                template_id=f"{agent}:live-unique-crop",
                agent_id=agent,
                source_id="vod-live",
                source_type="live",
                frame_id=f"frame-{index}",
                frame_sha256=hashlib.sha256(f"frame-{index}".encode()).hexdigest(),
                hud_profile_id="synthetic-hud-v1",
                frame_width=1920,
                frame_height=1080,
                crop_x=100 + index,
                crop_y=200,
                crop_width=12,
                crop_height=12,
                image_path=image_path,
                image_sha256=image_hash,
                mask_path=mask_path,
                mask_sha256=mask_hash,
                acquisition_role="calibration",
                review_status="accepted",
                reviewer_id="reviewer-1",
                side=Side.UNKNOWN,
            )
        )
    return result


def _calibration(
    templates: list[NeutralPortraitTemplate], required: list[str]
) -> NeutralPortraitCalibration:
    return NeutralPortraitCalibration(
        status="accepted",
        template_set_sha256=_template_set_digest(templates),
        required_agent_ids=required,
        training_frame_ids=sorted({item.frame_id for item in templates}),
        heldout_frame_ids=["heldout-frame"],
        negative_control_ids=["negative-control"],
        minimum_confidence=0.7,
        distinct_agent_margin=0.05,
        calibration_measurements={"synthetic_heldout_accuracy": 1.0},
        reviewer_id="calibration-reviewer",
    )


def _roster(agents: list[str]) -> list[TeamRoster]:
    return [
        TeamRoster(
            team_id="team-a",
            players=[RosterPlayer(player_id=f"p-{agent}", agent_id=agent) for agent in agents],
        )
    ]


def test_neutral_mask_scores_only_retained_pixels_and_requires_full_coverage(
    tmp_path: Path,
) -> None:
    agents = ["neon", "jett", "sova", "cypher", "omen", "phoenix", "chamber"]
    templates = _templates(tmp_path, agents)
    matcher = NeutralPortraitEvidenceMatcher(templates, tmp_path, _calibration(templates, agents))
    # Candidate background is unrelated; its retained center pixels exactly match Neon.
    candidate = np.full((12, 12, 3), 250, dtype=np.uint8)
    candidate[2:10, 2:10] = 20
    mask = np.zeros((12, 12), dtype=np.uint8)
    mask[2:10, 2:10] = 255
    mask_path, mask_hash = _write_asset(tmp_path, "neon-center-mask", mask)
    image_path, image_hash = _write_asset(
        tmp_path, "neon-centered-template", np.full_like(candidate, 20)
    )
    # Replace only the Neon mask/image while retaining a calibration generated for the manifest.
    templates[0] = templates[0].model_copy(
        update={
            "image_path": image_path,
            "image_sha256": image_hash,
            "mask_path": mask_path,
            "mask_sha256": mask_hash,
        }
    )
    matcher = NeutralPortraitEvidenceMatcher(templates, tmp_path, _calibration(templates, agents))

    result = matcher.match(candidate, _roster(agents), candidate_id="candidate-1")

    assert result.accepted
    assert result.resolved_agent_id == "neon"
    assert result.best_score_by_agent["neon"] == 1.0
    assert result.raw_scores[0].side is Side.UNKNOWN
    assert result.raw_scores[0].template_id == "neon:live-unique-crop"


def test_neon_only_library_cannot_resolve_incomplete_roster(tmp_path: Path) -> None:
    templates = _templates(tmp_path, ["neon"])
    matcher = NeutralPortraitEvidenceMatcher(
        templates, tmp_path, _calibration(templates, ["neon", "jett"])
    )

    result = matcher.match(
        np.full((12, 12, 3), 20, dtype=np.uint8),
        _roster(["neon", "jett"]),
        candidate_id="candidate-1",
    )

    assert not result.accepted
    assert result.resolved_agent_id is None
    assert "template_library_incomplete_agent_coverage" in result.rejection_reasons
    assert result.raw_scores  # Rejected scores remain diagnostic evidence.


def test_duplicate_same_agent_templates_do_not_create_agent_tie(tmp_path: Path) -> None:
    templates = _templates(
        tmp_path, ["neon", "jett", "sova", "cypher", "omen", "phoenix", "chamber"]
    )
    duplicate = templates[0].model_copy(
        update={"template_id": "neon:second-unique-crop", "frame_id": "neon-frame-2"}
    )
    # Reuse exact assets, but retain a distinct template and source-frame provenance ID.
    templates.append(duplicate)
    required = [item.agent_id for item in templates[:7]]
    result = NeutralPortraitEvidenceMatcher(
        templates, tmp_path, _calibration(templates, required)
    ).match(np.full((12, 12, 3), 20, dtype=np.uint8), _roster(required), candidate_id="candidate-1")
    assert result.accepted
    assert result.resolved_agent_id == "neon"
    assert len([match for match in result.raw_scores if match.agent_id == "neon"]) == 2


def test_near_tie_and_pending_calibration_fail_closed_with_scores(tmp_path: Path) -> None:
    agents = ["neon", "jett", "sova", "cypher", "omen", "phoenix", "chamber"]
    templates = _templates(tmp_path, agents)
    templates[1] = templates[1].model_copy(
        update={"image_path": templates[0].image_path, "image_sha256": templates[0].image_sha256}
    )
    calibration = _calibration(templates, agents).model_copy(
        update={"status": "pending", "reviewer_id": None}
    )
    result = NeutralPortraitEvidenceMatcher(templates, tmp_path, calibration).match(
        np.full((12, 12, 3), 20, dtype=np.uint8), _roster(agents), candidate_id="candidate-1"
    )
    assert not result.accepted
    assert result.resolved_agent_id is None
    assert "calibration_not_accepted" in result.rejection_reasons
    assert "distinct_agent_scores_ambiguous" in result.rejection_reasons
    assert result.raw_scores


def test_actual_roster_coverage_cannot_be_underdeclared(tmp_path: Path) -> None:
    templates = _templates(tmp_path, ["neon"])
    matcher = NeutralPortraitEvidenceMatcher(templates, tmp_path, _calibration(templates, ["neon"]))

    result = matcher.match(
        np.full((12, 12, 3), 20, dtype=np.uint8),
        _roster(["neon", "jett", "sova", "cypher", "omen", "phoenix", "chamber"]),
        candidate_id="candidate-1",
    )

    assert not result.accepted
    assert result.resolved_agent_id is None
    assert "roster_template_coverage_mismatch" in result.rejection_reasons


def test_heldout_template_never_scores_even_when_declared_heldout(tmp_path: Path) -> None:
    templates = _templates(
        tmp_path, ["neon", "jett", "sova", "cypher", "omen", "phoenix", "chamber"]
    )
    templates[0] = templates[0].model_copy(update={"acquisition_role": "heldout"})
    calibration = _calibration(templates, [item.agent_id for item in templates]).model_copy(
        update={
            "training_frame_ids": [item.frame_id for item in templates[1:]],
            "heldout_frame_ids": [templates[0].frame_id],
        }
    )

    result = NeutralPortraitEvidenceMatcher(templates, tmp_path, calibration).match(
        np.full((12, 12, 3), 20, dtype=np.uint8),
        _roster([item.agent_id for item in templates]),
        candidate_id="candidate-1",
    )

    assert not result.accepted
    assert all(match.agent_id != "neon" for match in result.raw_scores)
    assert "heldout_template_not_prediction_asset:neon:live-unique-crop" in result.rejection_reasons


def test_known_template_side_is_preserved_in_raw_evidence(tmp_path: Path) -> None:
    templates = _templates(
        tmp_path, ["neon", "jett", "sova", "cypher", "omen", "phoenix", "chamber"]
    )
    templates[0] = templates[0].model_copy(update={"side": Side.ATTACK})
    agents = [item.agent_id for item in templates]

    result = NeutralPortraitEvidenceMatcher(
        templates, tmp_path, _calibration(templates, agents)
    ).match(np.full((12, 12, 3), 20, dtype=np.uint8), _roster(agents), candidate_id="candidate-1")

    assert result.raw_scores[0].side is Side.ATTACK


def test_masked_resize_does_not_mix_excluded_colors() -> None:
    from valoscribe.detectors.neutral_portrait_evidence import _masked_similarity

    template = np.zeros((4, 4, 3), dtype=np.uint8)
    template[:, 2:] = 255
    mask = np.zeros((4, 4), dtype=np.uint8)
    mask[:, :2] = 255
    candidate = np.zeros((1, 1, 3), dtype=np.uint8)

    score = _masked_similarity(candidate, template, mask)

    assert score == 1.0


def test_negative_control_crop_is_rejected_below_policy_threshold(tmp_path: Path) -> None:
    agents = ["neon", "jett", "sova", "cypher", "omen", "phoenix", "chamber"]
    templates = _templates(tmp_path, agents)
    matcher = NeutralPortraitEvidenceMatcher(templates, tmp_path, _calibration(templates, agents))

    result = matcher.match(
        np.full((12, 12, 3), 255, dtype=np.uint8),
        _roster(agents),
        candidate_id="negative-control-candidate",
    )

    assert not result.accepted
    assert result.resolved_agent_id is None
    assert "best_match_below_calibrated_minimum" in result.rejection_reasons
    assert result.raw_scores


def test_evaluation_labels_change_scoring_not_neutral_prediction(tmp_path: Path) -> None:
    agents = ["neon", "jett", "sova", "cypher", "omen", "phoenix", "chamber"]
    templates = _templates(tmp_path, agents)
    matcher = NeutralPortraitEvidenceMatcher(templates, tmp_path, _calibration(templates, agents))
    image = np.full((12, 12, 3), 20, dtype=np.uint8)
    roster = _roster(agents)
    labels = {"expected_agent": "neon"}

    prediction_before = matcher.match(image, roster, candidate_id="candidate-1")
    score_before = prediction_before.resolved_agent_id == labels["expected_agent"]
    labels["expected_agent"] = "jett"
    prediction_after = matcher.match(image, roster, candidate_id="candidate-1")
    score_after = prediction_after.resolved_agent_id == labels["expected_agent"]

    assert prediction_before == prediction_after
    assert score_before is True
    assert score_after is False


def test_corrupt_asset_replay_and_empty_mask_reject_without_resolving(tmp_path: Path) -> None:
    agents = ["neon", "jett", "sova", "cypher", "omen", "phoenix", "chamber"]
    templates = _templates(tmp_path, agents)
    templates[0] = templates[0].model_copy(update={"source_type": "replay"})
    templates[1] = templates[1].model_copy(update={"image_sha256": "0" * 64})
    empty_mask_path, empty_hash = _write_asset(
        tmp_path, "empty-mask", np.zeros((12, 12), dtype=np.uint8)
    )
    templates[2] = templates[2].model_copy(
        update={"mask_path": empty_mask_path, "mask_sha256": empty_hash}
    )
    templates[3] = templates[3].model_copy(update={"review_status": "pending", "reviewer_id": None})
    templates[4] = templates[4].model_copy(update={"acquisition_role": "heldout"})
    result = NeutralPortraitEvidenceMatcher(
        templates, tmp_path, _calibration(templates, agents)
    ).match(np.full((12, 12, 3), 20, dtype=np.uint8), _roster(agents), candidate_id="candidate-1")
    assert not result.accepted
    assert result.resolved_agent_id is None
    assert any(reason.startswith("template_source_not_live") for reason in result.rejection_reasons)
    assert any(reason.startswith("template_asset_invalid") for reason in result.rejection_reasons)
    assert any(reason.startswith("template_mask_empty") for reason in result.rejection_reasons)
    assert any(reason.startswith("template_unreviewed") for reason in result.rejection_reasons)
    assert any(
        reason.startswith("template_outside_declared_split") for reason in result.rejection_reasons
    )
    assert result.raw_scores
