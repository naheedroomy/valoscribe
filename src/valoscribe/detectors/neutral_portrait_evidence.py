"""Explicitly opt-in, side-neutral portrait evidence with fail-closed gates."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

from valoscribe.detectors.minimap_portrait_matcher import TeamRoster
from valoscribe.types.persistent import (
    AgentPortraitTemplateMatch,
    NeutralAgentEvidenceDecision,
    NeutralPortraitCalibration,
    NeutralPortraitTemplate,
    PortraitRosterMember,
)


class NeutralPortraitEvidenceMatcher:
    """Match reviewed masked assets; default legacy matching is unaffected."""

    def __init__(
        self,
        templates: list[NeutralPortraitTemplate],
        asset_root: Path,
        calibration: NeutralPortraitCalibration,
    ) -> None:
        self.templates = templates
        self.calibration = calibration
        self.template_set_sha256 = _template_set_digest(templates)
        self.errors: list[str] = []
        self.assets: list[tuple[NeutralPortraitTemplate, np.ndarray, np.ndarray]] = []
        if len({item.template_id for item in templates}) != len(templates):
            self.errors.append("duplicate_template_id")
        provenance = [
            (item.source_id, item.frame_id, item.agent_id, item.image_sha256) for item in templates
        ]
        if len(set(provenance)) != len(provenance):
            self.errors.append("duplicate_source_provenance")
        for item in templates:
            if item.acquisition_role == "heldout":
                self.errors.append(f"heldout_template_not_prediction_asset:{item.template_id}")
                continue
            if item.review_status != "accepted" or item.reviewer_id is None:
                self.errors.append(f"template_unreviewed:{item.template_id}")
                continue
            if item.source_type != "live":
                self.errors.append(f"template_source_not_live:{item.template_id}")
                continue
            image = _load_verified(asset_root, item.image_path, item.image_sha256)
            mask = _load_verified(asset_root, item.mask_path, item.mask_sha256)
            if image is None or mask is None:
                self.errors.append(f"template_asset_invalid:{item.template_id}")
                continue
            if (
                not _valid_image(image)
                or mask.ndim != 2
                or mask.size == 0
                or mask.shape != image.shape[:2]
                or image.shape[1] != item.crop_width
                or image.shape[0] != item.crop_height
            ):
                self.errors.append(f"template_mask_invalid:{item.template_id}")
                continue
            mask = np.where(mask > 0, 255, 0).astype(np.uint8)
            if not np.any(mask):
                self.errors.append(f"template_mask_empty:{item.template_id}")
                continue
            self.assets.append((item, image, mask))

    def match(
        self, icon_crop: np.ndarray, rosters: list[TeamRoster], *, candidate_id: str
    ) -> NeutralAgentEvidenceDecision:
        """Return raw scores always; only accepted calibration can resolve."""
        if not _valid_image(icon_crop):
            raise ValueError("icon_crop must be a non-empty uint8 BGR image")
        if not candidate_id.strip():
            raise ValueError("candidate_id must not be blank")
        roster_agents = {player.agent_id for roster in rosters for player in roster.players}
        required = self.calibration.required_agent_ids
        reasons = list(self.errors)
        if self.calibration.status != "accepted" or self.calibration.reviewer_id is None:
            reasons.append("calibration_not_accepted")
        if self.calibration.template_set_sha256 != self.template_set_sha256:
            reasons.append("calibration_template_set_mismatch")
        for item in self.templates:
            declared_frames = (
                self.calibration.training_frame_ids
                if item.acquisition_role == "calibration"
                else self.calibration.heldout_frame_ids
            )
            if item.frame_id not in declared_frames:
                reasons.append(f"template_outside_declared_split:{item.template_id}")
        library_agents = {item.agent_id for item in self.templates}
        if not set(required).issubset(library_agents):
            reasons.append("template_library_incomplete_agent_coverage")
        if not set(required).issubset(roster_agents):
            reasons.append("roster_incomplete_agent_coverage")
        if roster_agents != set(required) or library_agents != roster_agents:
            reasons.append("roster_template_coverage_mismatch")
        if not rosters:
            reasons.append("roster_metadata_missing")

        roster_members: dict[str, list[PortraitRosterMember]] = {}
        for roster in rosters:
            for player in roster.players:
                roster_members.setdefault(player.agent_id, []).append(
                    PortraitRosterMember(team_id=roster.team_id, player_id=player.player_id)
                )
        raw_scores: list[AgentPortraitTemplateMatch] = []
        for item, template, mask in self.assets:
            if item.agent_id not in roster_members:
                continue
            score = _masked_similarity(icon_crop, template, mask)
            if score is None:
                reasons.append(f"candidate_mask_invalid:{item.template_id}")
                continue
            raw_scores.append(
                AgentPortraitTemplateMatch(
                    agent_id=item.agent_id,
                    side=item.side,
                    confidence=score,
                    template_id=item.template_id,
                    roster_members=sorted(
                        set(roster_members[item.agent_id]),
                        key=lambda member: (member.team_id, member.player_id),
                    ),
                    evidence=[
                        "neutral_masked_template_similarity",
                        f"template_sha256:{item.image_sha256}",
                    ],
                )
            )
        raw_scores.sort(key=lambda match: (-match.confidence, match.agent_id, match.template_id))
        best: dict[str, float] = {}
        for raw_score in raw_scores:
            best[raw_score.agent_id] = max(raw_score.confidence, best.get(raw_score.agent_id, 0.0))
        resolved: str | None = None
        if not raw_scores:
            reasons.append("no_usable_template_scores")
        else:
            ranked = sorted(best.items(), key=lambda item: (-item[1], item[0]))
            top_agent, top_score = ranked[0]
            next_distinct = ranked[1][1] if len(ranked) > 1 else 0.0
            if top_score < self.calibration.minimum_confidence:
                reasons.append("best_match_below_calibrated_minimum")
            if top_score - next_distinct < self.calibration.distinct_agent_margin:
                reasons.append("distinct_agent_scores_ambiguous")
            if not reasons:
                resolved = top_agent
        reasons = list(dict.fromkeys(reasons))
        accepted = resolved is not None and not reasons
        return NeutralAgentEvidenceDecision(
            template_set_sha256=self.template_set_sha256,
            calibration_policy_sha256=_calibration_policy_digest(self.calibration),
            candidate_id=candidate_id,
            source_crop_sha256=_image_digest(icon_crop),
            minimum_confidence=self.calibration.minimum_confidence,
            distinct_agent_margin=self.calibration.distinct_agent_margin,
            calibration_status=self.calibration.status,
            required_agent_coverage=required,
            observed_agent_coverage=sorted(library_agents),
            raw_scores=raw_scores,
            best_score_by_agent=best,
            resolved_agent_id=resolved,
            accepted=accepted,
            rejection_reasons=[] if accepted else (reasons or ["evidence_rejected"]),
        )


def _image_digest(image: np.ndarray) -> str:
    return hashlib.sha256(
        str(image.shape).encode() + b":" + image.dtype.str.encode() + b":" + image.tobytes()
    ).hexdigest()


def _calibration_policy_digest(calibration: NeutralPortraitCalibration) -> str:
    encoded = json.dumps(
        calibration.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _template_set_digest(templates: list[NeutralPortraitTemplate]) -> str:
    data = [
        item.model_dump(mode="json")
        for item in sorted(templates, key=lambda item: item.template_id)
    ]
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _load_verified(root: Path, relative_path: str, expected_sha256: str) -> np.ndarray | None:
    path = (root / relative_path).resolve()
    try:
        path.relative_to(root.resolve())
        payload = path.read_bytes()
    except (OSError, ValueError):
        return None
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        return None
    return cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_UNCHANGED)


def _valid_image(image: object) -> bool:
    return (
        isinstance(image, np.ndarray)
        and image.dtype == np.uint8
        and image.ndim == 3
        and image.shape[0] > 0
        and image.shape[1] > 0
        and image.shape[2] == 3
    )


def _masked_similarity(icon: np.ndarray, template: np.ndarray, mask: np.ndarray) -> float | None:
    height, width = icon.shape[:2]
    weights = (mask > 0).astype(np.float32)
    resized_weights = cv2.resize(weights, (width, height), interpolation=cv2.INTER_AREA)
    weighted_pixels = template.astype(np.float32) * weights[:, :, None]
    resized_weighted_pixels = cv2.resize(
        weighted_pixels, (width, height), interpolation=cv2.INTER_AREA
    )
    retained = resized_weights > 1e-6
    retained_pixels = int(np.count_nonzero(retained))
    if retained_pixels == 0:
        return None
    resized = np.zeros((height, width, 3), dtype=np.float32)
    resized[retained] = resized_weighted_pixels[retained] / resized_weights[retained, None]
    differences = np.abs(icon.astype(np.float32) - resized)[retained]
    return float(np.clip(1.0 - np.mean(differences, dtype=np.float64) / 255.0, 0.0, 1.0))
