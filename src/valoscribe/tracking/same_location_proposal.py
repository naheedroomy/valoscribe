"""Replay authenticated minimap crops as anonymous same-location proposals."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Literal

import cv2
import numpy as np

from valoscribe.detectors.minimap_color_detector import (
    MinimapColorCandidateDetector,
    MinimapColorProfile,
)
from valoscribe.tracking.portrait_experiment import (
    _PRODUCTION_PROTOCOL,
    _canonical_json,
    _decode_crop,
    _validate_source_manifest,
    _verify_crop_pixels,
    _verify_readback,
    _within_root,
)
from valoscribe.types.portrait_experiment import PortraitExperimentManifest
from valoscribe.types.same_location_proposal import (
    SameLocationProposal,
    SameLocationProposalDiagnostics,
    SameLocationProposalManifest,
    SameLocationTemplateScore,
)

_READBACK_ROOT = Path("/private/tmp/vta304-round4-neutral-portrait-experiment-v3-readback")
_COLOR_PROFILE = Path(__file__).parents[1] / "config" / "minimap_color_vta201_train_profile.json"
_NEIGHBORHOOD = 20
_PINNED_COLOR_PROFILE_SHA256 = "cbee57bba5010354bc891fe3821b800cdb56bdfd0616ea9c0d853c3f283fe4a1"


def run_same_location_proposal_diagnostic(
    source_root: Path,
    output_dir: Path,
    *,
    readback_root: Path = _READBACK_ROOT,
    color_profile_path: Path = _COLOR_PROFILE,
) -> SameLocationProposalManifest:
    """Write raw, uncalibrated proposals for each fixed source-grid crop.

    Existing color contours are only spatial anchors. Accepted and rejected
    contour geometries are retained; the synthetic color-support mask is not
    a portrait foreground mask and never modifies the unmasked similarity.
    """
    if output_dir.exists() or output_dir.is_symlink():
        raise FileExistsError(f"refusing to overwrite proposal diagnostic directory: {output_dir}")

    source_root = source_root.resolve(strict=True)
    source_manifest_bytes = (source_root / "manifest.json").read_bytes()
    source_digest = _sha256(source_manifest_bytes)
    if source_digest != _PRODUCTION_PROTOCOL.source_manifest_sha256:
        raise ValueError("source manifest digest does not match the pinned proposal packet")
    source_doc = json.loads(source_manifest_bytes)
    rows = _validate_source_manifest(source_doc, _PRODUCTION_PROTOCOL)

    readback_root = readback_root.resolve(strict=True)
    readback_manifest_bytes = (readback_root / "manifest.json").read_bytes()
    readback = PortraitExperimentManifest.model_validate_json(readback_manifest_bytes)
    _verify_readback(readback_root, readback, rows)
    if (
        readback.source_manifest_sha256 != source_digest
        or readback.review_sha256 != _PRODUCTION_PROTOCOL.review_sha256
        or readback.template_count != 4
        or readback.frame_count != 160
    ):
        raise ValueError(
            "portrait readback manifest does not authenticate the pinned source/templates"
        )
    template_bytes = (readback_root / "template_bank.json").read_bytes()
    if _sha256(template_bytes) != readback.template_bank_sha256:
        raise ValueError("template bank hash does not match authenticated readback manifest")
    template_rows = json.loads(template_bytes)
    if len(template_rows) != 4:
        raise ValueError("authenticated template bank must contain exactly four templates")
    templates: list[tuple[str, str, np.ndarray]] = []
    by_frame = {int(row["frame_index"]): row for row in rows}
    for item in template_rows:
        source_row = by_frame.get(int(item["frame_index"]))
        if (
            source_row is None
            or int(item["source_pts"]) != source_row["source_pts"]
            or item["source_crop_png_sha256"] != source_row["candidate_crop_png"]["sha256"]
        ):
            raise ValueError("template frame/PTS/crop provenance does not join to source manifest")
        meta = source_row["candidate_crop_png"]
        crop_path = _within_root(source_root, meta["path"])
        payload = crop_path.read_bytes()
        if _sha256(payload) != meta["sha256"]:
            raise ValueError(f"source crop PNG hash mismatch: {crop_path.name}")
        image = _decode_crop(payload, crop_path.name)
        _verify_crop_pixels(image, meta, crop_path.name)
        x, y = int(item["x"]), int(item["y"])
        patch = image[y : y + 20, x : x + 20]
        if patch.shape != (20, 20, 3):
            raise ValueError(f"template source window is clipped: {item['template_id']}")
        templates.append((str(item["template_id"]), str(item["agent_id"]), patch.copy()))
    if len({item[0] for item in templates}) != 4:
        raise ValueError("template IDs must be unique")

    profile_bytes = color_profile_path.read_bytes()
    if _sha256(profile_bytes) != _PINNED_COLOR_PROFILE_SHA256:
        raise ValueError("color profile digest does not match the frozen VTA-201 training profile")
    profile = MinimapColorProfile.model_validate_json(profile_bytes)
    detector = MinimapColorCandidateDetector(profile)
    output_dir.mkdir(parents=True)
    debug_dir = output_dir / "debug"
    proposal_crops_dir = debug_dir / "proposal_crops"
    masks_dir = debug_dir / "support_masks"
    proposal_crops_dir.mkdir(parents=True)
    masks_dir.mkdir(parents=True)
    proposals: list[SameLocationProposal] = []
    overlay_index: list[dict[str, str]] = []

    for row in rows:
        frame = int(row["frame_index"])
        pts = int(row["source_pts"])
        meta = row["candidate_crop_png"]
        path = _within_root(source_root, meta["path"])
        payload = path.read_bytes()
        if _sha256(payload) != meta["sha256"]:
            raise ValueError(f"source crop PNG hash mismatch: {path.name}")
        image = _decode_crop(payload, path.name)
        _verify_crop_pixels(image, meta, path.name)
        detection = detector.detect(
            image,
            vod_timestamp_s=float(row["timestamp_seconds_decimal"]),
            source_frame=frame,
        )
        # Stable sort preserves every overlapping/adjacent contour geometry.
        candidates = _ordered_candidates(detection.candidates, image.shape[1], image.shape[0])
        overlay = image.copy()
        cv2.putText(
            overlay,
            f"frame={frame} pts={pts}",
            (2, 12),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.32,
            (255, 255, 255),
            1,
        )
        for ordinal, candidate in enumerate(candidates):
            x = round(candidate.bounding_box.x * image.shape[1])
            y = round(candidate.bounding_box.y * image.shape[0])
            width = round(candidate.bounding_box.width * image.shape[1])
            height = round(candidate.bounding_box.height * image.shape[0])
            nx, ny, _, _ = _same_location_box(x, y, width, height)
            proposal_id = f"f{frame:06d}-p{pts}-c{ordinal:03d}"
            neighborhood_box = (nx, ny, _NEIGHBORHOOD, _NEIGHBORHOOD)
            reasons = list(candidate.rejection_reasons)
            scores: list[SameLocationTemplateScore] = []
            support_path: str | None = None
            support_digest: str | None = None
            crop_path_out: str | None = None
            crop_digest: str | None = None
            support_pixels = 0
            status: Literal["scored", "clipped", "empty_support"]
            if (
                nx < 0
                or ny < 0
                or nx + _NEIGHBORHOOD > image.shape[1]
                or ny + _NEIGHBORHOOD > image.shape[0]
            ):
                status = "clipped"
                reasons.append("same_location_neighborhood_clipped_at_source_crop_edge")
            else:
                patch = image[ny : ny + _NEIGHBORHOOD, nx : nx + _NEIGHBORHOOD]
                support = _color_support_mask(image, profile, candidate.broadcast_color)[
                    ny : ny + _NEIGHBORHOOD, nx : nx + _NEIGHBORHOOD
                ]
                support_pixels = int(cv2.countNonZero(support))
                support_payload = _encode_png(support)
                crop_payload = _encode_png(patch)
                support_name = f"{proposal_id}.png"
                crop_name = f"{proposal_id}.png"
                (masks_dir / support_name).write_bytes(support_payload)
                (proposal_crops_dir / crop_name).write_bytes(crop_payload)
                support_path = f"debug/support_masks/{support_name}"
                crop_path_out = f"debug/proposal_crops/{crop_name}"
                support_digest = _sha256(support_payload)
                crop_digest = _sha256(crop_payload)
                if support_pixels == 0:
                    status = "empty_support"
                    reasons.append("same_location_color_support_mask_is_empty")
                else:
                    status = "scored"
                    scores = _score_same_location(patch, templates, proposal_id)
            color_box = (x, y, width, height)
            color = (0, 255, 0) if candidate.accepted else (0, 0, 255)
            cv2.rectangle(overlay, (x, y), (x + width - 1, y + height - 1), color, 1)
            if nx >= 0 and ny >= 0:
                cv2.rectangle(
                    overlay,
                    (nx, ny),
                    (nx + _NEIGHBORHOOD - 1, ny + _NEIGHBORHOOD - 1),
                    (255, 190, 0),
                    1,
                )
            cv2.putText(
                overlay,
                f"{ordinal}:{candidate.broadcast_color}:{status}",
                (max(0, x), min(image.shape[0] - 1, max(20, y - 2))),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.28,
                color,
                1,
            )
            proposals.append(
                SameLocationProposal(
                    proposal_id=proposal_id,
                    frame_index=frame,
                    source_pts=pts,
                    timestamp_seconds=row["timestamp_seconds"],
                    source_crop_sha256=meta["sha256"],
                    broadcast_color=candidate.broadcast_color,
                    color_candidate_accepted=candidate.accepted,
                    color_candidate_rejection_reasons=list(candidate.rejection_reasons),
                    color_candidate_box_xywh=color_box,
                    neighborhood_box_xywh=neighborhood_box,
                    status=status,
                    support_pixel_count=support_pixels,
                    support_mask_path=support_path,
                    support_mask_sha256=support_digest,
                    neighborhood_crop_path=crop_path_out,
                    neighborhood_crop_sha256=crop_digest,
                    scores=scores,
                    rejection_reasons=reasons,
                )
            )
        overlay_payload = _encode_png(overlay)
        overlay_name = f"frame-{frame:06d}-pts-{pts}-proposals.png"
        (debug_dir / overlay_name).write_bytes(overlay_payload)
        overlay_index.append({"path": f"debug/{overlay_name}", "sha256": _sha256(overlay_payload)})

    raw_payload = _canonical_json([item.model_dump(mode="json") for item in proposals])
    scored = sum(item.status == "scored" for item in proposals)
    clipped = sum(item.status == "clipped" for item in proposals)
    empty = sum(item.status == "empty_support" for item in proposals)
    diagnostics = SameLocationProposalDiagnostics(
        source_frame_count=len(rows),
        proposal_count=len(proposals),
        scored_proposal_count=scored,
        clipped_proposal_count=clipped,
        empty_support_proposal_count=empty,
        raw_similarity_count=sum(len(item.scores) for item in proposals),
    )
    diagnostics_payload = _canonical_json(diagnostics.model_dump(mode="json"))
    overlay_payload = _canonical_json(overlay_index)
    (output_dir / "raw_proposals.json").write_bytes(raw_payload)
    (output_dir / "derived_diagnostics.json").write_bytes(diagnostics_payload)
    (output_dir / "debug_index.json").write_bytes(overlay_payload)
    manifest = SameLocationProposalManifest(
        source_manifest_sha256=source_digest,
        source_review_sha256=readback.review_sha256,
        template_bank_sha256=readback.template_bank_sha256,
        color_profile_sha256=_sha256(profile_bytes),
        raw_proposals_sha256=_sha256(raw_payload),
        derived_diagnostics_sha256=_sha256(diagnostics_payload),
        debug_index_sha256=_sha256(overlay_payload),
        frame_count=len(rows),
        proposal_count=len(proposals),
        raw_similarity_count=diagnostics.raw_similarity_count,
    )
    manifest_payload = _canonical_json(manifest.model_dump(mode="json"))
    (output_dir / "manifest.json").write_bytes(manifest_payload)
    _verify_output(output_dir, manifest, rows, templates)
    return manifest


def _same_location_box(x: int, y: int, width: int, height: int) -> tuple[int, int, int, int]:
    """Center the fixed template window on raw contour geometry without clamping."""
    center_x, center_y = x + width // 2, y + height // 2
    return (
        center_x - _NEIGHBORHOOD // 2,
        center_y - _NEIGHBORHOOD // 2,
        _NEIGHBORHOOD,
        _NEIGHBORHOOD,
    )


def _ordered_candidates(candidates: tuple[Any, ...], width: int, height: int) -> list[Any]:
    """Sort contours deterministically without applying overlap suppression."""
    return sorted(
        candidates,
        key=lambda candidate: (
            candidate.broadcast_color,
            round(candidate.bounding_box.y * height),
            round(candidate.bounding_box.x * width),
            round(candidate.bounding_box.width * width),
            round(candidate.bounding_box.height * height),
            not candidate.accepted,
            tuple(candidate.rejection_reasons),
        ),
    )


def _score_same_location(
    patch: np.ndarray,
    templates: list[tuple[str, str, np.ndarray]],
    proposal_id: str,
) -> list[SameLocationTemplateScore]:
    """Compare four templates against the identical supplied 20x20 patch."""
    if patch.dtype != np.uint8 or patch.shape != (_NEIGHBORHOOD, _NEIGHBORHOOD, 3):
        raise ValueError("same-location evidence must be one exact 20x20 BGR patch")
    if len(templates) != 4 or len({template_id for template_id, _, _ in templates}) != 4:
        raise ValueError("same-location comparison requires four unique templates")
    scores: list[SameLocationTemplateScore] = []
    for template_id, agent_id, template in templates:
        if template.dtype != np.uint8 or template.shape != patch.shape:
            raise ValueError(f"template must be an exact 20x20 BGR window: {template_id}")
        value = float(cv2.matchTemplate(patch, template, cv2.TM_CCOEFF_NORMED)[0, 0])
        if not math.isfinite(value):
            raise ValueError(f"non-finite raw similarity for {proposal_id}/{template_id}")
        scores.append(
            SameLocationTemplateScore(
                template_id=template_id,
                agent_id=agent_id,
                similarity=value,
            )
        )
    return scores


def _color_support_mask(
    image: np.ndarray, profile: MinimapColorProfile, color_id: str
) -> np.ndarray:
    color = next((item for item in profile.colors if item.color_id == color_id), None)
    if color is None:
        raise ValueError(f"unknown color profile id: {color_id}")
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask: np.ndarray = np.zeros(image.shape[:2], dtype=np.uint8)
    for item in color.ranges:
        mask = cv2.bitwise_or(
            mask,
            cv2.inRange(
                hsv, np.asarray(item.lower, dtype=np.uint8), np.asarray(item.upper, dtype=np.uint8)
            ),
        )
    return mask


def _verify_output(
    output_dir: Path,
    manifest: SameLocationProposalManifest,
    source_rows: list[dict[str, Any]],
    templates: list[tuple[str, str, np.ndarray]],
) -> None:
    raw = (output_dir / "raw_proposals.json").read_bytes()
    diagnostics_bytes = (output_dir / "derived_diagnostics.json").read_bytes()
    index_bytes = (output_dir / "debug_index.json").read_bytes()
    if (
        _sha256(raw) != manifest.raw_proposals_sha256
        or _sha256(diagnostics_bytes) != manifest.derived_diagnostics_sha256
        or _sha256(index_bytes) != manifest.debug_index_sha256
    ):
        raise ValueError("proposal artifact read-back hash mismatch")
    proposals = [SameLocationProposal.model_validate(item) for item in json.loads(raw)]
    diagnostics = SameLocationProposalDiagnostics.model_validate_json(diagnostics_bytes)
    if (
        len(proposals) != manifest.proposal_count
        or diagnostics.proposal_count != manifest.proposal_count
    ):
        raise ValueError("proposal count does not match readback joins")
    if diagnostics.source_frame_count != len(source_rows) or manifest.frame_count != len(
        source_rows
    ):
        raise ValueError("source frame count does not match proposal readback")
    if (
        diagnostics.raw_similarity_count != manifest.raw_similarity_count
        or manifest.raw_similarity_count != sum(len(item.scores) for item in proposals)
    ):
        raise ValueError("similarity count does not match proposal readback")
    template_ids = {item[0] for item in templates}
    if len(template_ids) != 4:
        raise ValueError("proposal output requires four authenticated templates")
    frame_pts = {
        int(row["frame_index"]): (
            int(row["source_pts"]),
            row["timestamp_seconds"],
            row["candidate_crop_png"]["sha256"],
        )
        for row in source_rows
    }
    proposal_ids: set[str] = set()
    for item in proposals:
        joined = frame_pts.get(item.frame_index)
        if joined != (item.source_pts, item.timestamp_seconds, item.source_crop_sha256):
            raise ValueError(
                "proposal frame/PTS/timestamp/crop hash does not join to source packet"
            )
        if item.proposal_id in proposal_ids:
            raise ValueError("duplicate proposal ID in raw output")
        proposal_ids.add(item.proposal_id)
        if item.status == "scored" and {score.template_id for score in item.scores} != template_ids:
            raise ValueError("scored proposal must contain all four same-location template scores")
        if item.status != "scored" and item.scores:
            raise ValueError("unscored proposal must not contain partial similarities")
        for rel_path, expected_digest in (
            (item.neighborhood_crop_path, item.neighborhood_crop_sha256),
            (item.support_mask_path, item.support_mask_sha256),
        ):
            if rel_path is None:
                if expected_digest is not None:
                    raise ValueError("missing debug path cannot have a hash")
                continue
            path = _within_root(output_dir, rel_path)
            if _sha256(path.read_bytes()) != expected_digest:
                raise ValueError("proposal crop/mask read-back hash mismatch")
    for item in json.loads(index_bytes):
        path = _within_root(output_dir, item["path"])
        if _sha256(path.read_bytes()) != item["sha256"]:
            raise ValueError("source overlay read-back hash mismatch")
    if len(json.loads(index_bytes)) != len(source_rows):
        raise ValueError("one debug source overlay is required per source frame")
    if (output_dir / "manifest.json").read_bytes() != _canonical_json(
        manifest.model_dump(mode="json")
    ):
        raise ValueError("proposal run manifest read-back mismatch")


def _encode_png(image: np.ndarray) -> bytes:
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise ValueError("could not encode diagnostic PNG")
    return encoded.tobytes()


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()
