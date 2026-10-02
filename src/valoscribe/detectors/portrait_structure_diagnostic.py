"""Synthetic-first, diagnostic-only portrait enclosure and structure analysis."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from valoscribe.types.persistent import (
    PortraitStructureComparison,
    PortraitStructureDiagnostic,
    PortraitStructurePolicy,
    PortraitStructureROI,
    PortraitStructureStatus,
)


@dataclass(frozen=True)
class PortraitStructureAnalysis:
    """Persistent decision plus in-memory visualization and descriptor arrays."""

    policy: PortraitStructurePolicy
    result: PortraitStructureDiagnostic
    proposals: tuple[PortraitStructureROI, ...]
    support_mask: np.ndarray
    exclusion_mask: np.ndarray
    exclusion_mask_provided: bool
    edge_map: np.ndarray
    gradient_magnitude: np.ndarray
    gradient_orientation: np.ndarray
    descriptor: np.ndarray | None
    descriptor_support: np.ndarray | None
    overlay: np.ndarray


def analyze_portrait_structure(
    context_bgr: np.ndarray,
    *,
    candidate_id: str,
    roi: PortraitStructureROI,
    policy: PortraitStructurePolicy,
    exclusion_mask: np.ndarray | None = None,
) -> PortraitStructureAnalysis:
    """Localize one closed compact enclosure and describe supported gradients.

    The ROI and returned geometry use native image pixels with top-left origin.
    Every policy value is synthetic-only and uncalibrated for broadcast imagery.
    """
    _validate_inputs(context_bgr, candidate_id, roi, policy, exclusion_mask)
    height, width = context_bgr.shape[:2]
    image_digest = _digest_array(context_bgr)
    if roi.x + roi.width > width or roi.y + roi.height > height:
        raise ValueError("roi must be within context_bgr")

    region = context_bgr[roi.y : roi.y + roi.height, roi.x : roi.x + roi.width]
    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, policy.canny_low, policy.canny_high)
    kernel = np.ones((policy.closing_kernel, policy.closing_kernel), np.uint8)
    closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(closed, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    boxes, has_rejected_geometry = _compact_enclosures(contours, roi, policy)
    proposals = tuple(_as_roi(box) for box in boxes)
    overlay = context_bgr.copy()
    cv2.rectangle(
        overlay, (roi.x, roi.y), (roi.x + roi.width - 1, roi.y + roi.height - 1), (255, 180, 0), 1
    )
    for box in boxes:
        cv2.rectangle(
            overlay, (box[0], box[1]), (box[0] + box[2] - 1, box[1] + box[3] - 1), (0, 180, 255), 1
        )

    status: PortraitStructureStatus
    reasons: list[str] = []
    chosen: tuple[int, int, int, int] | None = None
    if has_rejected_geometry:
        status = PortraitStructureStatus.REJECTED
        reasons.append("noncompact_parent_enclosure")
    elif not boxes and _touches_search_border(gray, context_bgr, roi):
        status = PortraitStructureStatus.CLIPPED
        reasons.append("edge_structure_truncated_at_search_envelope")
    elif not boxes:
        status = PortraitStructureStatus.UNKNOWN
        reasons.append("no_supported_compact_enclosure")
    elif len(boxes) != 1:
        status = PortraitStructureStatus.UNKNOWN
        reasons.append("competing_enclosures")
    else:
        chosen = boxes[0]
        x, y, box_width, box_height = chosen
        local_x, local_y = x - roi.x, y - roi.y
        if (
            local_x <= 0
            or local_y <= 0
            or local_x + box_width >= roi.width - 1
            or local_y + box_height >= roi.height - 1
        ):
            status = PortraitStructureStatus.CLIPPED
            reasons.append("enclosure_touches_search_envelope")
        else:
            status = PortraitStructureStatus.LOCALIZED

    support = np.zeros((height, width), dtype=np.uint8)
    exclusion = (
        np.asarray(exclusion_mask != 0, dtype=np.uint8)
        if exclusion_mask is not None
        else np.zeros((height, width), dtype=np.uint8)
    )
    magnitude_full = np.zeros((height, width), dtype=np.float32)
    orientation_full = np.zeros((height, width), dtype=np.float32)
    descriptor: np.ndarray | None = None
    descriptor_support: np.ndarray | None = None
    gradient_count = 0
    support_fraction = 0.0
    if status is PortraitStructureStatus.LOCALIZED and chosen is not None:
        x, y, box_width, box_height = chosen
        # Restrict gradients to the interior; the enclosure edge itself is not a portrait feature.
        inset = max(1, int(round(min(box_width, box_height) * 0.08)))
        interior = np.zeros((height, width), dtype=np.uint8)
        interior[y + inset : y + box_height - inset, x + inset : x + box_width - inset] = 1
        interior_area = int(np.count_nonzero(interior))
        if exclusion_mask is not None:
            excluded = exclusion.astype(bool)
            excluded_inside = int(np.count_nonzero(excluded & interior.astype(bool)))
            if interior_area and excluded_inside / interior_area >= 0.25:
                status = PortraitStructureStatus.OVERLAP
                reasons.append("explicit_exclusion_conflict_inside_enclosure")
            interior[excluded] = 0
        gray_full = cv2.cvtColor(context_bgr, cv2.COLOR_BGR2GRAY)
        # Require the full 3x3 derivative stencil to stay inside the valid support.
        stencil = cv2.erode(interior, np.ones((3, 3), np.uint8), borderType=cv2.BORDER_CONSTANT)
        gx = cv2.Sobel(gray_full, cv2.CV_32F, 1, 0, ksize=3, borderType=cv2.BORDER_CONSTANT)
        gy = cv2.Sobel(gray_full, cv2.CV_32F, 0, 1, ksize=3, borderType=cv2.BORDER_CONSTANT)
        magnitude = cv2.magnitude(gx, gy)
        orientation = cv2.phase(gx, gy, angleInDegrees=False) % np.pi
        gradient_count = int(np.count_nonzero((stencil > 0) & (magnitude > 0)))
        support_fraction = float(np.count_nonzero(stencil) / max(1, interior_area))
        if (
            status is PortraitStructureStatus.LOCALIZED
            and support_fraction >= policy.minimum_support_fraction
            and gradient_count >= policy.minimum_gradient_pixels
        ):
            descriptor, descriptor_support = _spatial_descriptor(
                magnitude, orientation, stencil, chosen, policy
            )
            if descriptor is None:
                status = PortraitStructureStatus.UNKNOWN
                reasons.append("insufficient_spatial_gradient_support")
        elif status is PortraitStructureStatus.LOCALIZED:
            status = PortraitStructureStatus.UNKNOWN
            reasons.append("insufficient_supported_texture")
        magnitude_full[:] = magnitude
        orientation_full[:] = orientation
        support[:] = stencil

    if status is not PortraitStructureStatus.LOCALIZED:
        descriptor = None
        descriptor_support = None
        support.fill(0)
        magnitude_full.fill(0)
        orientation_full.fill(0)
        if not reasons:
            reasons.append("diagnostic_unavailable")

    geometry = (
        _as_roi(chosen)
        if chosen is not None and status is PortraitStructureStatus.LOCALIZED
        else None
    )
    center_x = chosen[0] + (chosen[2] - 1) / 2 if geometry and chosen else None
    center_y = chosen[1] + (chosen[3] - 1) / 2 if geometry and chosen else None
    gradient_digest = (
        _gradient_evidence_digest(
            magnitude_full,
            orientation_full,
            support,
            geometry,
            roi,
            policy,
            image_digest,
        )
        if geometry is not None
        else None
    )
    result = PortraitStructureDiagnostic(
        candidate_id=candidate_id,
        context_image_sha256=image_digest,
        roi=roi,
        status=status,
        policy_sha256=policy_digest(policy),
        proposed_boundary=geometry,
        proposed_center_x=center_x,
        proposed_center_y=center_y,
        geometric_support_fraction=support_fraction if geometry else 0.0,
        ambiguity_count=max(0, len(boxes) - 1),
        rejection_reasons=reasons,
        feature_sha256=_digest_array(descriptor) if descriptor is not None else None,
        support_sha256=_digest_array(support) if geometry else None,
        gradient_sha256=gradient_digest,
        supported_gradient_pixels=gradient_count if geometry else 0,
    )
    return PortraitStructureAnalysis(
        policy=policy,
        result=result,
        proposals=proposals,
        support_mask=support,
        exclusion_mask=exclusion,
        exclusion_mask_provided=exclusion_mask is not None,
        edge_map=cv2.copyMakeBorder(
            edges,
            roi.y,
            height - roi.y - roi.height,
            roi.x,
            width - roi.x - roi.width,
            cv2.BORDER_CONSTANT,
        ),
        gradient_magnitude=magnitude_full,
        gradient_orientation=orientation_full,
        descriptor=descriptor,
        descriptor_support=descriptor_support,
        overlay=overlay,
    )


def compare_portrait_structure(
    left: PortraitStructureAnalysis, right: PortraitStructureAnalysis
) -> PortraitStructureComparison:
    """Compare available structure only when both complete analyses preflight."""
    left_bound = _analysis_evidence_is_bound(left)
    right_bound = _analysis_evidence_is_bound(right)
    digest = _safe_policy_digest(left.policy)
    if not left_bound or not right_bound:
        return PortraitStructureComparison(
            status="unknown", policy_sha256=digest, shared_support_fraction=0.0
        )
    if (
        digest != right.result.policy_sha256
        or digest != left.result.policy_sha256
        or policy_digest(right.policy) != digest
    ):
        return PortraitStructureComparison(
            status="policy_mismatch", policy_sha256=digest, shared_support_fraction=0.0
        )
    if (
        left.result.status is not PortraitStructureStatus.LOCALIZED
        or right.result.status is not PortraitStructureStatus.LOCALIZED
    ):
        return PortraitStructureComparison(
            status="unknown", policy_sha256=digest, shared_support_fraction=0.0
        )
    left_box = left.result.proposed_boundary
    right_box = right.result.proposed_boundary
    if left_box is None or right_box is None:
        return PortraitStructureComparison(
            status="unknown", policy_sha256=digest, shared_support_fraction=0.0
        )
    if (left_box.width, left_box.height) != (right_box.width, right_box.height):
        return PortraitStructureComparison(
            status="unknown", policy_sha256=digest, shared_support_fraction=0.0
        )
    width, height = left_box.width, left_box.height
    left_slice = np.s_[left_box.y : left_box.y + height, left_box.x : left_box.x + width]
    right_slice = np.s_[right_box.y : right_box.y + height, right_box.x : right_box.x + width]
    common_pixels = (left.support_mask[left_slice] > 0) & (right.support_mask[right_slice] > 0)
    shared_fraction = float(np.count_nonzero(common_pixels) / (width * height))
    if not np.any(common_pixels) or shared_fraction < left.policy.minimum_common_support_fraction:
        return PortraitStructureComparison(
            status="unknown", policy_sha256=digest, shared_support_fraction=shared_fraction
        )
    left_descriptor, left_cells = _spatial_descriptor(
        left.gradient_magnitude[left_slice],
        left.gradient_orientation[left_slice],
        common_pixels.astype(np.uint8),
        (0, 0, width, height),
        left.policy,
        normalize=False,
    )
    right_descriptor, right_cells = _spatial_descriptor(
        right.gradient_magnitude[right_slice],
        right.gradient_orientation[right_slice],
        common_pixels.astype(np.uint8),
        (0, 0, width, height),
        right.policy,
        normalize=False,
    )
    if (
        left_descriptor is None
        or right_descriptor is None
        or left_cells is None
        or right_cells is None
    ):
        return PortraitStructureComparison(
            status="unknown", policy_sha256=digest, shared_support_fraction=shared_fraction
        )
    shared_cells = (left_cells > 0) & (right_cells > 0)
    if not np.any(shared_cells):
        return PortraitStructureComparison(
            status="unknown", policy_sha256=digest, shared_support_fraction=shared_fraction
        )
    a = left_descriptor[shared_cells].astype(np.float64)
    b = right_descriptor[shared_cells].astype(np.float64)
    norm_a, norm_b = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if norm_a <= 0 or norm_b <= 0:
        return PortraitStructureComparison(
            status="unknown", policy_sha256=digest, shared_support_fraction=shared_fraction
        )
    a /= norm_a
    b /= norm_b
    distance = float(np.linalg.norm(a - b) / np.sqrt(max(1, a.size)))
    return PortraitStructureComparison(
        status="available",
        policy_sha256=digest,
        shared_support_fraction=shared_fraction,
        distance=distance,
    )


def write_portrait_structure_debug(analysis: PortraitStructureAnalysis, directory: Path) -> None:
    """Write and verify an explicit diagnostic bundle; never called implicitly."""
    if not _analysis_evidence_is_bound(analysis):
        raise ValueError("analysis gradient/support evidence is not bound to its result")
    directory.mkdir(parents=True, exist_ok=True)
    supported = analysis.support_mask > 0
    magnitude = np.where(supported, analysis.gradient_magnitude, 0.0)
    orientation = np.where(supported, analysis.gradient_orientation, 0.0)
    maximum = float(np.max(magnitude)) if magnitude.size else 0.0
    magnitude_preview = np.zeros(magnitude.shape, dtype=np.uint8)
    if maximum > 0:
        magnitude_preview = np.clip(magnitude * (255.0 / maximum), 0, 255).astype(np.uint8)
    orientation_preview = np.clip(orientation * (255.0 / np.pi), 0, 255).astype(np.uint8)
    png_arrays = {
        "proposal-overlay.png": analysis.overlay,
        "edge-map.png": analysis.edge_map,
        "support-mask.png": analysis.support_mask * 255,
        "exclusion-mask.png": analysis.exclusion_mask * 255,
        "gradient-magnitude.png": magnitude_preview,
        "gradient-orientation.png": orientation_preview,
    }
    artifact_hashes: dict[str, str] = {}
    for filename, array in png_arrays.items():
        path = directory / filename
        if not cv2.imwrite(str(path), array):
            raise OSError(f"unable to write diagnostic artifact: {path}")
        decoded = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if decoded is None or not np.array_equal(decoded, array):
            raise OSError(f"diagnostic PNG round-trip mismatch: {path}")
        artifact_hashes[filename] = hashlib.sha256(path.read_bytes()).hexdigest()

    descriptor = (
        analysis.descriptor if analysis.descriptor is not None else np.empty((0,), np.float32)
    )
    descriptor_support = (
        analysis.descriptor_support
        if analysis.descriptor_support is not None
        else np.empty((0,), np.uint8)
    )
    archive_path = directory / "descriptor.npz"
    np.savez_compressed(
        archive_path,
        descriptor=descriptor,
        descriptor_support=descriptor_support,
    )
    with np.load(archive_path, allow_pickle=False) as archive:
        if not np.array_equal(archive["descriptor"], descriptor):
            raise OSError(f"diagnostic NPZ descriptor round-trip mismatch: {archive_path}")
        if not np.array_equal(archive["descriptor_support"], descriptor_support):
            raise OSError(f"diagnostic NPZ support round-trip mismatch: {archive_path}")
    if analysis.descriptor is not None:
        if _digest_array(descriptor) != analysis.result.feature_sha256:
            raise OSError("diagnostic descriptor digest does not match diagnostic result")
    if analysis.result.status is PortraitStructureStatus.LOCALIZED:
        if _digest_array(analysis.support_mask) != analysis.result.support_sha256:
            raise OSError("diagnostic pixel-support digest does not match diagnostic result")
    artifact_hashes[archive_path.name] = hashlib.sha256(archive_path.read_bytes()).hexdigest()

    canonical_policy = analysis.policy.model_dump(mode="json")
    canonical_policy_sha256 = policy_digest(analysis.policy)
    if canonical_policy_sha256 != analysis.result.policy_sha256:
        raise OSError("diagnostic policy digest does not match diagnostic result")
    manifest = {
        "result": analysis.result.model_dump(mode="json"),
        "proposals": [proposal.model_dump(mode="json") for proposal in analysis.proposals],
        "canonical_policy_body": canonical_policy,
        "policy_sha256": canonical_policy_sha256,
        "exclusion_mask_provided": analysis.exclusion_mask_provided,
        "artifact_sha256": artifact_hashes,
        "artifact_files": [*png_arrays, archive_path.name],
    }
    (directory / "diagnostic.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def policy_digest(policy: PortraitStructurePolicy) -> str:
    encoded = json.dumps(
        policy.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _safe_policy_digest(policy: PortraitStructurePolicy) -> str:
    try:
        return policy_digest(policy)
    except (TypeError, ValueError):
        return hashlib.sha256(b"invalid-portrait-structure-policy").hexdigest()


def _gradient_evidence_digest(
    magnitude: np.ndarray,
    orientation: np.ndarray,
    support: np.ndarray,
    boundary: PortraitStructureROI,
    roi: PortraitStructureROI,
    policy: PortraitStructurePolicy,
    context_image_sha256: str,
) -> str:
    """Bind supported native-pixel gradients to support, geometry, source, and policy."""
    if (
        magnitude.shape != orientation.shape
        or magnitude.shape != support.shape
        or magnitude.ndim != 2
        or magnitude.dtype != np.float32
        or orientation.dtype != np.float32
        or support.dtype != np.uint8
        or not np.isin(support, (0, 1)).all()
        or not np.isfinite(magnitude).all()
        or not np.isfinite(orientation).all()
    ):
        raise ValueError("gradient evidence arrays have invalid shape or values")
    if np.any(magnitude < 0) or np.any(orientation < 0) or np.any(orientation >= np.pi):
        raise ValueError("gradient evidence is outside its canonical value range")
    selected = support > 0
    supported_magnitude = np.where(selected, magnitude, 0).astype("<f4", copy=False)
    supported_orientation = np.where(selected, orientation, 0).astype("<f4", copy=False)
    header = {
        "schema": "supported-native-gradient-v1",
        "coordinate_origin": "image_top_left",
        "context_image_sha256": context_image_sha256,
        "native_shape": list(support.shape),
        "roi": roi.model_dump(mode="json"),
        "boundary": boundary.model_dump(mode="json"),
        "policy_sha256": policy_digest(policy),
    }
    hasher = hashlib.sha256(json.dumps(header, sort_keys=True, separators=(",", ":")).encode())
    hasher.update(np.ascontiguousarray(support).tobytes())
    hasher.update(np.ascontiguousarray(supported_magnitude).tobytes())
    hasher.update(np.ascontiguousarray(supported_orientation).tobytes())
    return hasher.hexdigest()


def _analysis_evidence_is_bound(analysis: PortraitStructureAnalysis) -> bool:
    """Validate the complete result and arrays before use or serialization."""
    if not isinstance(analysis, PortraitStructureAnalysis):
        return False
    if not isinstance(analysis.result, PortraitStructureDiagnostic):
        return False
    try:
        result = PortraitStructureDiagnostic.model_validate(analysis.result.__dict__)
        if policy_digest(analysis.policy) != result.policy_sha256:
            return False
        support = analysis.support_mask
        exclusion = analysis.exclusion_mask
        magnitude = analysis.gradient_magnitude
        orientation = analysis.gradient_orientation
        if (
            not isinstance(support, np.ndarray)
            or support.ndim != 2
            or support.dtype != np.uint8
            or not np.isin(support, (0, 1)).all()
            or not isinstance(exclusion, np.ndarray)
            or exclusion.shape != support.shape
            or exclusion.dtype != np.uint8
            or not np.isin(exclusion, (0, 1)).all()
            or (not analysis.exclusion_mask_provided and np.any(exclusion))
            or not isinstance(magnitude, np.ndarray)
            or magnitude.shape != support.shape
            or not isinstance(orientation, np.ndarray)
            or orientation.shape != support.shape
            or not np.isfinite(magnitude).all()
            or not np.isfinite(orientation).all()
        ):
            return False
        if result.status is not PortraitStructureStatus.LOCALIZED:
            return (
                analysis.descriptor is None
                and analysis.descriptor_support is None
                and result.gradient_sha256 is None
                and result.feature_sha256 is None
                and result.support_sha256 is None
                and not np.any(support)
                and not np.any(magnitude)
                and not np.any(orientation)
            )
        boundary = result.proposed_boundary
        exclusion_dilation = cv2.dilate(exclusion, np.ones((3, 3), np.uint8))
        if np.any((support > 0) & (exclusion_dilation > 0)):
            return False
        if (
            boundary is None
            or analysis.descriptor is None
            or analysis.descriptor_support is None
            or _digest_array(analysis.descriptor) != result.feature_sha256
            or _digest_array(support) != result.support_sha256
            or _gradient_evidence_digest(
                magnitude,
                orientation,
                support,
                boundary,
                result.roi,
                analysis.policy,
                result.context_image_sha256,
            )
            != result.gradient_sha256
        ):
            return False
        expected_descriptor, expected_cell_support = _spatial_descriptor(
            magnitude,
            orientation,
            support,
            (boundary.x, boundary.y, boundary.width, boundary.height),
            analysis.policy,
        )
        return (
            expected_descriptor is not None
            and expected_cell_support is not None
            and np.array_equal(analysis.descriptor, expected_descriptor)
            and np.array_equal(analysis.descriptor_support, expected_cell_support)
            and np.isfinite(analysis.descriptor).all()
        )
    except (TypeError, ValueError, OverflowError):
        return False


def _validate_inputs(
    image: np.ndarray,
    candidate_id: str,
    roi: PortraitStructureROI,
    policy: PortraitStructurePolicy,
    exclusion_mask: np.ndarray | None,
) -> None:
    if (
        not isinstance(image, np.ndarray)
        or image.dtype != np.uint8
        or image.ndim != 3
        or image.shape[2] != 3
        or not image.size
    ):
        raise ValueError("context_bgr must be a non-empty uint8 BGR image")
    if not candidate_id.strip():
        raise ValueError("candidate_id must not be blank")
    if not isinstance(roi, PortraitStructureROI) or not isinstance(policy, PortraitStructurePolicy):
        raise ValueError("roi and policy must use their typed contracts")
    if exclusion_mask is not None:
        if not isinstance(exclusion_mask, np.ndarray) or exclusion_mask.shape != image.shape[:2]:
            raise ValueError("exclusion_mask must match the context image dimensions")
        if not np.isfinite(exclusion_mask).all():
            raise ValueError("exclusion_mask must contain only finite values")


def _touches_search_border(
    gray: np.ndarray, context: np.ndarray, roi: PortraitStructureROI
) -> bool:
    """Recognize contrast continuing beyond an envelope without closing it."""
    height, width = gray.shape
    sides = (
        (gray[0, :], context[max(0, roi.y - 1), roi.x : roi.x + roi.width]),
        (
            gray[-1, :],
            context[min(context.shape[0] - 1, roi.y + height), roi.x : roi.x + roi.width],
        ),
        (gray[:, 0], context[roi.y : roi.y + roi.height, max(0, roi.x - 1)]),
        (
            gray[:, -1],
            context[roi.y : roi.y + roi.height, min(context.shape[1] - 1, roi.x + width)],
        ),
    )
    for edge_pixels, outside_pixels in sides:
        if outside_pixels.ndim == 2:
            outside_gray = cv2.cvtColor(
                outside_pixels[np.newaxis, :, :], cv2.COLOR_BGR2GRAY
            ).reshape(-1)
        else:
            outside_gray = cv2.cvtColor(
                outside_pixels[:, np.newaxis, :], cv2.COLOR_BGR2GRAY
            ).reshape(-1)
        differences = np.abs(edge_pixels.astype(np.int16) - outside_gray.astype(np.int16))
        if np.count_nonzero(differences >= 30) >= 4:
            return True
    return False


def _compact_enclosures(
    contours: Sequence[Any],
    roi: PortraitStructureROI,
    policy: PortraitStructurePolicy,
) -> tuple[list[tuple[int, int, int, int]], bool]:
    candidates: list[tuple[int, int, int, int, float]] = []
    broad_noncompact: list[tuple[int, int, int, int, float]] = []
    roi_area = roi.width * roi.height
    for contour in contours:
        x, y, width, height = cv2.boundingRect(contour)
        area = float(cv2.contourArea(contour))
        if area < policy.minimum_area_px or area > roi_area * policy.maximum_area_fraction:
            continue
        if width < 4 or height < 4:
            continue
        aspect = width / height
        if not policy.minimum_aspect_ratio <= aspect <= policy.maximum_aspect_ratio:
            continue
        extent = area / (width * height)
        perimeter = float(cv2.arcLength(contour, True))
        compactness = (4.0 * np.pi * area / (perimeter * perimeter)) if perimeter else 0.0
        if extent < 0.30:
            continue
        candidate = (roi.x + x, roi.y + y, width, height, area)
        if compactness < policy.minimum_compactness:
            broad_noncompact.append(candidate)
            continue
        candidates.append(candidate)
    candidates.sort(key=lambda item: (-item[4], item[0], item[1], item[2], item[3]))
    deduplicated: list[tuple[int, int, int, int, float]] = []
    for candidate in candidates:
        if any(_same_enclosure(candidate, accepted) for accepted in deduplicated):
            continue
        deduplicated.append(candidate)
    ambiguous_parent = any(
        parent[4] > child[4] * 1.3 and _contains(parent, child)
        for parent in broad_noncompact
        for child in deduplicated
    )
    return [(x, y, width, height) for x, y, width, height, _ in deduplicated], ambiguous_parent


def _contains(a: tuple[int, int, int, int, float], b: tuple[int, int, int, int, float]) -> bool:
    ax, ay, aw, ah, _ = a
    bx, by, bw, bh, _ = b
    return ax <= bx and ay <= by and ax + aw >= bx + bw and ay + ah >= by + bh


def _same_enclosure(
    a: tuple[int, int, int, int, float], b: tuple[int, int, int, int, float]
) -> bool:
    ax, ay, aw, ah, _ = a
    bx, by, bw, bh, _ = b
    if min(aw, bw) / max(aw, bw) < 0.85 or min(ah, bh) / max(ah, bh) < 0.85:
        return False
    center_distance_x = abs((ax + (aw - 1) / 2) - (bx + (bw - 1) / 2))
    center_distance_y = abs((ay + (ah - 1) / 2) - (by + (bh - 1) / 2))
    if center_distance_x > max(2.0, 0.1 * min(aw, bw)):
        return False
    if center_distance_y > max(2.0, 0.1 * min(ah, bh)):
        return False
    ix, iy = max(ax, bx), max(ay, by)
    iw, ih = max(0, min(ax + aw, bx + bw) - ix), max(0, min(ay + ah, by + bh) - iy)
    intersection = iw * ih
    union = aw * ah + bw * bh - intersection
    return union > 0 and intersection / union >= 0.80


def _as_roi(box: tuple[int, int, int, int] | None) -> PortraitStructureROI:
    assert box is not None
    return PortraitStructureROI(x=box[0], y=box[1], width=box[2], height=box[3])


def _spatial_descriptor(
    magnitude: np.ndarray,
    orientation: np.ndarray,
    support: np.ndarray,
    box: tuple[int, int, int, int],
    policy: PortraitStructurePolicy,
    *,
    normalize: bool = True,
) -> tuple[np.ndarray | None, np.ndarray | None]:
    x, y, width, height = box
    desc = np.zeros((policy.grid_rows, policy.grid_columns, 8), dtype=np.float32)
    valid_cells = np.zeros((policy.grid_rows, policy.grid_columns), dtype=np.uint8)
    for row in range(policy.grid_rows):
        y0, y1 = y + row * height // policy.grid_rows, y + (row + 1) * height // policy.grid_rows
        for column in range(policy.grid_columns):
            x0, x1 = (
                x + column * width // policy.grid_columns,
                x + (column + 1) * width // policy.grid_columns,
            )
            cell_support = support[y0:y1, x0:x1] > 0
            cell_magnitude = magnitude[y0:y1, x0:x1]
            valid_gradients = cell_support & (cell_magnitude > 0)
            if np.count_nonzero(valid_gradients) < policy.minimum_gradient_pixels:
                continue
            angles = orientation[y0:y1, x0:x1][valid_gradients]
            weights = cell_magnitude[valid_gradients]
            bins = np.floor(angles * (8.0 / np.pi)).astype(np.int32) % 8
            desc[row, column] = np.bincount(bins, weights=weights, minlength=8).astype(np.float32)
            valid_cells[row, column] = 1
    if not np.any(valid_cells):
        return None, None
    norm = float(np.linalg.norm(desc))
    if norm <= 0:
        return None, None
    if normalize:
        desc /= norm
    return desc, valid_cells


def _digest_array(array: np.ndarray) -> str:
    payload = f"{array.dtype.str}:{array.shape}:".encode() + array.tobytes()
    return hashlib.sha256(payload).hexdigest()
