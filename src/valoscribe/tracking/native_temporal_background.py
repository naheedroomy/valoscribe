"""Authenticated source-crop temporal persistence diagnostics for VTA304."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import cv2
import numpy as np

from valoscribe.detectors.portrait_center_localizer import (
    RADIAL_POLICY_SHA256,
    RimHypothesis,
    localize_radial_rims,
)

SOURCE_MANIFEST_SHA256 = "95adb564bf8a2a1858063b280fb5e8eacb186f395e52711f80b9329579228f10"
ROW_GROUPS = ((0, 1, 2, 3, 4), (78, 79, 80, 81, 82), (155, 156, 157, 158, 159))
CENTER_POSITIONS = (2, 2, 2)
TEMPORAL_POLICY: dict[str, Any] = {
    "algorithm": "native_crop_grayscale_phase_correlation_and_median_background",
    "group_manifest_positions": [list(group) for group in ROW_GROUPS],
    "center_position_in_group": 2,
    "neighbor_radius_frames": 2,
    "exclude_center_from_background": True,
    "phase_response_min": 0.55,
    "maximum_pts_interval": 7680,
    "maximum_source_frame_interval": 30,
    "phase_tile_grid": [2, 2],
    "minimum_tile_response": 0.20,
    "minimum_tile_consensus_count": 2,
    "maximum_tile_consensus_error_px": 1.0,
    "maximum_pair_shift_px": 4.0,
    "minimum_valid_overlap_fraction": 0.95,
    "maximum_cycle_error_px": 1.0,
    "minimum_texture_gradient_fraction": 0.005,
    "phase_gradient_magnitude_min": 90.0,
    "photometric_compensation": "median_center_minus_aligned_neighbor_on_valid_pixels",
    "background_pixel_residual_threshold_gray": 12.0,
    "minimum_nonpersistent_rim_fraction": 0.40,
    "maximum_persistent_rim_fraction": 0.15,
    "minimum_supported_quadrants": 3,
    "minimum_valid_rim_sample_fraction": 0.75,
    "samples_per_rim": 32,
    "derived_meaning": (
        "geometric structure changed versus sampled temporal background; not player detection"
    ),
}
TEMPORAL_POLICY_SHA256 = hashlib.sha256(
    json.dumps(TEMPORAL_POLICY, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()


@dataclass(frozen=True)
class AuthenticatedCrop:
    manifest_position: int
    frame_index: int
    source_pts: int
    time_base: str
    image: np.ndarray
    grayscale_conversion_seconds: float
    crop_png_sha256: str
    decoded_bgr_sha256: str


@dataclass(frozen=True)
class Registration:
    neighbor_position: int
    frame_index: int
    source_pts: int
    translation_to_center_xy: tuple[float, float]
    adjacent_response_min: float
    direct_response: float
    cycle_error_px: float
    valid_overlap_fraction: float
    photometric_offset_gray: float
    residual_median_gray: float
    residual_p90_gray: float
    duration_ms: float
    global_phase_translation_xy: tuple[float, float]
    global_phase_response: float
    phase_consensus_fraction: float
    accepted: bool
    rejection_reasons: tuple[str, ...]
    aligned_gray: np.ndarray
    valid_mask: np.ndarray


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _contained(root: Path, relative_path: str) -> Path:
    relative = PurePosixPath(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("packet path must be relative and contained")
    candidate = root.joinpath(*relative.parts)
    if candidate.is_symlink() or not candidate.resolve().is_relative_to(root.resolve()):
        raise ValueError("packet path is symlinked or escapes the source root")
    return candidate


def _decode_authenticated_crops(
    source_root: Path, expected_manifest_sha256: str | None = SOURCE_MANIFEST_SHA256
) -> tuple[str, list[AuthenticatedCrop]]:
    root = source_root.resolve(strict=True)
    manifest_bytes = _contained(root, "manifest.json").read_bytes()
    manifest_sha = _sha(manifest_bytes)
    if expected_manifest_sha256 is not None and manifest_sha != expected_manifest_sha256:
        raise ValueError("source manifest digest differs from the frozen packet")
    manifest = json.loads(manifest_bytes)
    rows = manifest["images"]
    if len(rows) <= max(max(group) for group in ROW_GROUPS):
        raise ValueError("source manifest is missing one or more predeclared group rows")
    frame_indices = [row["frame_index"] for row in rows]
    source_pts = [row["source_pts"] for row in rows]
    if any(type(value) is not int or value < 0 for value in frame_indices + source_pts):
        raise ValueError("source frame indices and PTS must be finite non-negative integers")
    if len(set(frame_indices)) != len(frame_indices):
        raise ValueError("source manifest frame indices must be unique")
    if len(set(source_pts)) != len(source_pts):
        raise ValueError("source manifest PTS values must be unique")
    selected_positions = [position for group in ROW_GROUPS for position in group]
    selected = [rows[position] for position in selected_positions]
    crop_rects = {tuple(row["candidate_crop_rect_xywh"]) for row in selected}
    if len(crop_rects) != 1:
        raise ValueError("selected crop rectangles are inconsistent")
    for group in ROW_GROUPS:
        group_rows = [rows[position] for position in group]
        group_pts = [row["source_pts"] for row in group_rows]
        group_frames = [row["frame_index"] for row in group_rows]
        if any(not 0 < right - left <= 7680 for left, right in zip(group_pts, group_pts[1:])):
            raise ValueError("source PTS interval is nonpositive or crosses the frozen maximum gap")
        if any(not 0 < right - left <= 30 for left, right in zip(group_frames, group_frames[1:])):
            raise ValueError(
                "source frame interval is nonpositive or crosses the frozen maximum gap"
            )
        if any(right != left + 1 for left, right in zip(group, group[1:])):
            raise ValueError("sampled group positions must be contiguous")

    decoded: list[AuthenticatedCrop] = []
    for group in ROW_GROUPS:
        for position in group:
            row = rows[position]
            crop_meta = row["candidate_crop_png"]
            crop_path = _contained(root, crop_meta["path"])
            crop_png = crop_path.read_bytes()
            if _sha(crop_png) != crop_meta["sha256"]:
                raise ValueError(f"candidate crop PNG hash mismatch at manifest row {position}")
            crop_bgr = cv2.imdecode(np.frombuffer(crop_png, np.uint8), cv2.IMREAD_COLOR)
            if crop_bgr is None or list(crop_bgr.shape[:2][::-1]) != crop_meta["dimensions_px"]:
                raise ValueError(f"candidate crop dimensions/decode mismatch at row {position}")
            crop_bgr_sha = _sha(crop_bgr.tobytes())
            if crop_bgr_sha != crop_meta["crop_bgr_sha256"]:
                raise ValueError(f"candidate crop decoded BGR hash mismatch at row {position}")
            full_meta = row["full_frame_png"]
            full_png = _contained(root, full_meta["path"]).read_bytes()
            if _sha(full_png) != full_meta["sha256"]:
                raise ValueError(f"full-frame PNG hash mismatch at manifest row {position}")
            full_bgr = cv2.imdecode(np.frombuffer(full_png, np.uint8), cv2.IMREAD_COLOR)
            if (
                full_bgr is None
                or list(full_bgr.shape[:2][::-1]) != full_meta["dimensions_px"]
                or _sha(full_bgr.tobytes()) != row["decoded_bgr_sha256"]
            ):
                raise ValueError(
                    f"full-frame decoded BGR hash/dimensions mismatch at row {position}"
                )
            x, y, width, height = row["candidate_crop_rect_xywh"]
            reconstructed = full_bgr[y : y + height, x : x + width]
            if (
                reconstructed.shape != crop_bgr.shape
                or _sha(reconstructed.tobytes()) != crop_bgr_sha
            ):
                raise ValueError(f"full-frame crop reconstruction mismatch at row {position}")
            if row["time_base"] != "1/15360":
                raise ValueError(f"unexpected time base at manifest row {position}")
            start = time.perf_counter()
            gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
            elapsed = time.perf_counter() - start
            decoded.append(
                AuthenticatedCrop(
                    manifest_position=position,
                    frame_index=row["frame_index"],
                    source_pts=row["source_pts"],
                    time_base=row["time_base"],
                    image=gray,
                    grayscale_conversion_seconds=elapsed,
                    crop_png_sha256=crop_meta["sha256"],
                    decoded_bgr_sha256=crop_bgr_sha,
                )
            )
    return manifest_sha, decoded


def _phase(
    reference: np.ndarray, moving: np.ndarray, window: np.ndarray
) -> tuple[float, float, float, float, float, float, float, float]:
    start = time.perf_counter()
    global_shift, global_response = cv2.phaseCorrelate(
        reference.astype(np.float32), moving.astype(np.float32), window
    )
    height, width = reference.shape
    tile_shifts: list[tuple[float, float, float]] = []
    for row in range(2):
        for column in range(2):
            y0, y1 = row * height // 2, (row + 1) * height // 2
            x0, x1 = column * width // 2, (column + 1) * width // 2
            ref_tile = reference[y0:y1, x0:x1].astype(np.float32)
            moving_tile = moving[y0:y1, x0:x1].astype(np.float32)
            tile_window = cv2.createHanningWindow((x1 - x0, y1 - y0), cv2.CV_32F)
            shift, response = cv2.phaseCorrelate(ref_tile, moving_tile, tile_window)
            if response >= 0.20 and math.hypot(*shift) <= 4.0:
                tile_shifts.append((float(shift[0]), float(shift[1]), float(response)))
    if tile_shifts:
        median_x = float(np.median([item[0] for item in tile_shifts]))
        median_y = float(np.median([item[1] for item in tile_shifts]))
        inliers = [
            item
            for item in tile_shifts
            if math.hypot(item[0] - median_x, item[1] - median_y) <= 1.0
        ]
    else:
        inliers = []
    consensus_fraction = len(inliers) / 4.0
    if len(inliers) < 2:
        dx, dy, response = 0.0, 0.0, -1.0
    else:
        dx = float(np.median([item[0] for item in inliers]))
        dy = float(np.median([item[1] for item in inliers]))
        response = float(np.median([item[2] for item in inliers]))
    return (
        dx,
        dy,
        response,
        (time.perf_counter() - start) * 1000.0,
        float(global_shift[0]),
        float(global_shift[1]),
        float(global_response),
        consensus_fraction,
    )


def _register_group(
    group: list[AuthenticatedCrop], center_position: int = 2
) -> tuple[list[Registration], np.ndarray | None, np.ndarray | None, dict[str, Any]]:
    if center_position < 0 or center_position >= len(group):
        return [], None, None, {"accepted": False, "rejection_reasons": ["missing_center_frame"]}
    center = group[center_position]
    required = [center_position - 2, center_position - 1, center_position + 1, center_position + 2]
    if len(group) != 5 or any(index < 0 or index >= len(group) for index in required):
        return [], None, None, {"accepted": False, "rejection_reasons": ["missing_neighbor_frame"]}
    pts = [frame.source_pts for frame in group]
    if len(set(pts)) != len(pts) or any(b <= a for a, b in zip(pts, pts[1:])):
        return (
            [],
            None,
            None,
            {"accepted": False, "rejection_reasons": ["nonmonotonic_or_duplicate_pts"]},
        )
    frame_ids = [frame.frame_index for frame in group]
    if len(set(frame_ids)) != len(frame_ids):
        return [], None, None, {"accepted": False, "rejection_reasons": ["duplicate_source_frame"]}
    height, width = (int(value) for value in center.image.shape)
    image_size: tuple[int, int] = (width, height)
    window = cv2.createHanningWindow(image_size, cv2.CV_32F)
    adjacent: list[tuple[float, float, float, float, float, float, float, float]] = []
    for first, second in zip(group, group[1:]):
        adjacent.append(_phase(first.image, second.image, window))
    center_gradient_x = cv2.Sobel(center.image, cv2.CV_32F, 1, 0, ksize=3)
    center_gradient_y = cv2.Sobel(center.image, cv2.CV_32F, 0, 1, ksize=3)
    texture_fraction = float(np.mean(cv2.magnitude(center_gradient_x, center_gradient_y) >= 90.0))
    registrations: list[Registration] = []
    aligned: list[np.ndarray] = []
    valid_masks: list[np.ndarray] = []
    for neighbor_index in required:
        start = time.perf_counter()
        if neighbor_index < center_position:
            edge_range = range(neighbor_index, center_position)
        else:
            edge_range = range(center_position, neighbor_index)
        cumulative_x = sum(adjacent[index][0] for index in edge_range)
        cumulative_y = sum(adjacent[index][1] for index in edge_range)
        direct_reference, direct_moving = (
            (group[neighbor_index].image, center.image)
            if neighbor_index < center_position
            else (center.image, group[neighbor_index].image)
        )
        (
            direct_x,
            direct_y,
            direct_response,
            direct_ms,
            global_x,
            global_y,
            global_response,
            consensus_fraction,
        ) = _phase(direct_reference, direct_moving, window)
        cycle_error = math.hypot(cumulative_x - direct_x, cumulative_y - direct_y)
        translate_x, translate_y = (
            (cumulative_x, cumulative_y)
            if neighbor_index < center_position
            else (-cumulative_x, -cumulative_y)
        )
        matrix = np.asarray([[1.0, 0.0, translate_x], [0.0, 1.0, translate_y]], dtype=np.float32)
        opencv_warp_affine: Any = cv2.warpAffine
        opencv_transform: Any = matrix
        opencv_source: Any = group[neighbor_index].image.astype(np.float32)
        warped = opencv_warp_affine(
            opencv_source,
            opencv_transform,
            image_size,
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0,
        )
        opencv_valid_source: Any = np.ones((height, width), dtype=np.float32)
        valid = (
            opencv_warp_affine(
                opencv_valid_source,
                opencv_transform,
                image_size,
                flags=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_CONSTANT,
                borderValue=0,
            )
            >= 0.999
        )
        overlap = float(np.mean(valid))
        reasons: list[str] = []
        adjacent_response_min = min(adjacent[index][2] for index in edge_range)
        if texture_fraction < 0.005:
            reasons.append("insufficient_registration_texture")
        if adjacent_response_min < 0.55 or direct_response < 0.55:
            reasons.append("poor_phase_response")
        if math.hypot(cumulative_x, cumulative_y) > 4.0:
            reasons.append("relative_translation_exceeds_limit")
        if overlap < 0.95:
            reasons.append("insufficient_valid_overlap")
        if cycle_error > 1.0:
            reasons.append("cycle_inconsistency")
        offset = (
            float(
                np.median(center.image[valid].astype(np.float32) - warped[valid].astype(np.float32))
            )
            if np.any(valid)
            else 0.0
        )
        adjusted = np.clip(warped.astype(np.float32) + offset, 0, 255).astype(np.uint8)
        residual = np.abs(center.image.astype(np.int16) - adjusted.astype(np.int16)).astype(
            np.uint8
        )
        residual_values = residual[valid]
        accepted = not reasons
        registration = Registration(
            neighbor_position=neighbor_index,
            frame_index=group[neighbor_index].frame_index,
            source_pts=group[neighbor_index].source_pts,
            translation_to_center_xy=(translate_x, translate_y),
            adjacent_response_min=adjacent_response_min,
            direct_response=direct_response,
            cycle_error_px=cycle_error,
            valid_overlap_fraction=overlap,
            photometric_offset_gray=offset,
            residual_median_gray=float(np.median(residual_values))
            if residual_values.size
            else 255.0,
            residual_p90_gray=float(np.percentile(residual_values, 90))
            if residual_values.size
            else 255.0,
            duration_ms=(time.perf_counter() - start) * 1000.0,
            global_phase_translation_xy=(global_x, global_y),
            global_phase_response=global_response,
            phase_consensus_fraction=consensus_fraction,
            accepted=accepted,
            rejection_reasons=tuple(reasons),
            aligned_gray=adjusted,
            valid_mask=valid,
        )
        registrations.append(registration)
        aligned.append(adjusted)
        valid_masks.append(valid)
    all_accepted = all(item.accepted for item in registrations)
    if not all_accepted:
        return (
            registrations,
            None,
            None,
            {
                "accepted": False,
                "rejection_reasons": sorted(
                    {reason for item in registrations for reason in item.rejection_reasons}
                ),
                "texture_gradient_fraction": texture_fraction,
            },
        )
    background = np.median(np.stack(aligned, axis=0), axis=0).astype(np.uint8)
    valid_background = np.logical_and.reduce(valid_masks)
    residual_map = np.abs(center.image.astype(np.int16) - background.astype(np.int16)).astype(
        np.uint8
    )
    persistent_mask = ((residual_map <= 12) & valid_background).astype(np.uint8) * 255
    return (
        registrations,
        background,
        residual_map,
        {
            "accepted": True,
            "rejection_reasons": [],
            "texture_gradient_fraction": texture_fraction,
            "background_valid_fraction": float(np.mean(valid_background)),
            "background_residual_median_gray": float(np.median(residual_map[valid_background])),
            "background_residual_p90_gray": float(
                np.percentile(residual_map[valid_background], 90)
            ),
            "persistent_pixel_fraction": float(np.mean(persistent_mask[valid_background] > 0)),
            "persistent_mask": persistent_mask,
        },
    )


def _rim_temporal_evidence(
    candidate: RimHypothesis, residual_map: np.ndarray, valid_mask: np.ndarray
) -> dict[str, Any]:
    sample_count = int(TEMPORAL_POLICY["samples_per_rim"])
    empty_evidence = {
        "valid_support_coverage": 0.0,
        "valid_sample_count": 0,
        "fraction_nonpersistent": None,
        "supported_quadrants": None,
        "mean_rim_residual_gray": None,
    }
    if candidate.radius_px is None:
        return {**empty_evidence, "reason": "missing_radius"}
    radius = candidate.radius_px
    angles = np.arange(sample_count, dtype=np.float32) * (2.0 * np.pi / sample_count)
    xs = np.rint(candidate.center_x + radius * np.cos(angles)).astype(np.int32)
    ys = np.rint(candidate.center_y + radius * np.sin(angles)).astype(np.int32)
    height, width = residual_map.shape
    inside = (xs >= 0) & (xs < width) & (ys >= 0) & (ys < height)
    if not np.all(inside):
        return {**empty_evidence, "reason": "rim_clipped"}
    valid = valid_mask[ys, xs]
    valid_count = int(np.count_nonzero(valid))
    coverage = valid_count / sample_count
    evidence_base = {
        "valid_support_coverage": coverage,
        "valid_sample_count": valid_count,
    }
    if coverage < TEMPORAL_POLICY["minimum_valid_rim_sample_fraction"]:
        return {
            **evidence_base,
            "fraction_nonpersistent": None,
            "supported_quadrants": None,
            "mean_rim_residual_gray": None,
            "reason": "insufficient_valid_rim_background_coverage",
        }
    residual = residual_map[ys, xs]
    nonpersistent = valid & (residual > TEMPORAL_POLICY["background_pixel_residual_threshold_gray"])
    fraction = float(np.count_nonzero(nonpersistent) / valid_count)
    sectors = np.array_split(np.arange(sample_count), 4)
    quadrants = sum(
        int(np.count_nonzero(valid[section]) >= 4 and np.count_nonzero(nonpersistent[section]) >= 2)
        for section in sectors
    )
    return {
        **evidence_base,
        "fraction_nonpersistent": fraction,
        "supported_quadrants": quadrants,
        "mean_rim_residual_gray": float(np.mean(residual[valid])),
        "reason": None,
    }


def analyze_temporal_center(
    group: list[AuthenticatedCrop], center_position: int = 2
) -> tuple[dict[str, Any], np.ndarray | None, np.ndarray | None, np.ndarray | None, np.ndarray]:
    """Keep raw radial proposals unchanged and derive conservative temporal evidence."""
    if not group or center_position < 0 or center_position >= len(group):
        raise ValueError("center frame is missing")
    center = group[center_position]
    raw_start = time.perf_counter()
    raw = localize_radial_rims(cv2.cvtColor(center.image, cv2.COLOR_GRAY2BGR))
    raw_detector_ms = (time.perf_counter() - raw_start) * 1000.0
    start = time.perf_counter()
    registrations, background, residual, alignment = _register_group(group, center_position)
    registration_ms = (time.perf_counter() - start) * 1000.0
    decisions: list[dict[str, Any]] = []
    valid_mask = (
        np.ones(center.image.shape, bool)
        if alignment["accepted"]
        else np.zeros(center.image.shape, bool)
    )
    if registrations:
        valid_mask = np.logical_and.reduce([item.valid_mask for item in registrations])
    for index, candidate in enumerate(raw.hypotheses):
        decision: dict[str, Any] = {
            "raw_candidate_index": index,
            "raw_center_xy": [candidate.center_x, candidate.center_y],
            "raw_radius_px": candidate.radius_px,
            "raw_status": candidate.status,
            "raw_score": candidate.normalized_score,
            "identity": "unknown",
            "side": "unknown",
        }
        if not alignment["accepted"]:
            decision.update(
                status="abstain_poor_registration", reasons=alignment["rejection_reasons"]
            )
        elif candidate.status == "clipped":
            decision.update(status="abstain_clipped", reasons=["raw_candidate_clipped"])
        elif candidate.status == "competing":
            decision.update(
                status="abstain_competing", reasons=["raw_candidate_intersects_another_hypothesis"]
            )
        elif residual is None:
            decision.update(
                status="abstain_missing_residual",
                reasons=["registered_background_residual_unavailable"],
            )
        else:
            evidence = _rim_temporal_evidence(candidate, residual, valid_mask)
            decision["temporal_evidence"] = evidence
            fraction = evidence["fraction_nonpersistent"]
            if evidence["reason"] == "insufficient_valid_rim_background_coverage":
                decision.update(
                    status="abstain_insufficient_background_coverage",
                    reasons=[evidence["reason"]],
                )
            elif evidence["reason"] == "rim_clipped":
                decision.update(status="abstain_clipped", reasons=[evidence["reason"]])
            elif evidence["reason"]:
                decision.update(status="abstain_missing_rim_evidence", reasons=[evidence["reason"]])
            elif fraction <= 0.15:
                decision.update(
                    status="vetoed_persistent_or_stationary",
                    reasons=["rim_structure_persists_in_temporal_background"],
                )
            elif fraction >= 0.40 and evidence["supported_quadrants"] >= 3:
                decision.update(
                    status="temporally_nonpersistent_structural_hypothesis",
                    reasons=["original_rim_has_nonpersistent_temporal_residual_support"],
                )
            else:
                decision.update(
                    status="abstain_weak_residual_evidence",
                    reasons=["insufficient_nonpersistent_rim_residual_support"],
                )
        decisions.append(decision)
    return (
        {
            "frame_index": center.frame_index,
            "source_pts": center.source_pts,
            "group_positions": [item.manifest_position for item in group],
            "context_frames": [
                {
                    "frame_index": item.frame_index,
                    "source_pts": item.source_pts,
                    "pts_delta_from_center": item.source_pts - center.source_pts,
                    "time_base": item.time_base,
                }
                for item in group
            ],
            "raw_hypothesis_count": len(raw.hypotheses),
            "raw_hypotheses": [item.model_dump(mode="json") for item in raw.hypotheses],
            "derived_decisions": decisions,
            "alignment": {
                **{key: value for key, value in alignment.items() if key != "persistent_mask"},
                "registrations": [
                    {
                        "neighbor_position": item.neighbor_position,
                        "frame_index": item.frame_index,
                        "source_pts": item.source_pts,
                        "translation_to_center_xy": item.translation_to_center_xy,
                        "adjacent_response_min": item.adjacent_response_min,
                        "direct_response": item.direct_response,
                        "cycle_error_px": item.cycle_error_px,
                        "valid_overlap_fraction": item.valid_overlap_fraction,
                        "photometric_offset_gray": item.photometric_offset_gray,
                        "residual_median_gray": item.residual_median_gray,
                        "residual_p90_gray": item.residual_p90_gray,
                        "duration_ms": item.duration_ms,
                        "global_phase_translation_xy": item.global_phase_translation_xy,
                        "global_phase_response": item.global_phase_response,
                        "phase_consensus_fraction": item.phase_consensus_fraction,
                        "accepted": item.accepted,
                        "rejection_reasons": item.rejection_reasons,
                    }
                    for item in registrations
                ],
            },
            "registration_cost_ms": registration_ms,
            "raw_detector_cost_ms": raw_detector_ms,
            "context_grayscale_conversion_ms": [
                frame.grayscale_conversion_seconds * 1000.0 for frame in group
            ],
        },
        background,
        residual,
        alignment.get("persistent_mask"),
        raw.overlay,
    )


def _write_png(path: Path, image: np.ndarray) -> None:
    if not cv2.imwrite(str(path), image):
        raise OSError(f"failed to write temporal diagnostic image: {path}")


def _compute_code_sha256() -> str:
    code_paths = [
        Path(__file__),
        Path(__file__).parents[1] / "detectors" / "portrait_center_localizer.py",
        Path(__file__).parents[3] / "scripts" / "run_vta304_native_temporal_background.py",
    ]
    return _sha(b"".join(path.read_bytes() for path in code_paths))


def _hash_output_files(output_dir: Path) -> dict[str, str]:
    return {
        path.name: _sha(path.read_bytes())
        for path in sorted(output_dir.iterdir())
        if path.is_file()
    }


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n")


def run_native_temporal_background(source_root: Path, output_dir: Path) -> dict[str, Any]:
    """Run only the pinned source packet's three predeclared center rows."""
    return _run_native_temporal_background(
        source_root, output_dir, expected_manifest_sha256=SOURCE_MANIFEST_SHA256
    )


def _run_native_temporal_background(
    source_root: Path, output_dir: Path, *, expected_manifest_sha256: str | None
) -> dict[str, Any]:
    """Testable packet runner; production entrypoint always pins the source digest."""
    if output_dir.exists() or output_dir.is_symlink():
        raise FileExistsError(f"refusing existing or symlink output directory: {output_dir}")
    manifest_sha, crops = _decode_authenticated_crops(source_root, expected_manifest_sha256)
    groups: list[list[AuthenticatedCrop]] = []
    offset = 0
    for manifest_group in ROW_GROUPS:
        groups.append(crops[offset : offset + len(manifest_group)])
        offset += len(manifest_group)
    if expected_manifest_sha256 == SOURCE_MANIFEST_SHA256:
        expected_centers = [15788, 18128, 20438]
        actual_centers = [group[2].frame_index for group in groups]
        if actual_centers != expected_centers:
            raise ValueError("authenticated center rows do not match frozen source indices")
    analyzed = [
        analyze_temporal_center(group, center_pos)
        for group, center_pos in zip(groups, CENTER_POSITIONS)
    ]
    final_output_dir = output_dir
    temporary_directory = tempfile.TemporaryDirectory(
        prefix=f".{final_output_dir.name}.staging-", dir=final_output_dir.parent
    )
    try:
        output_dir = Path(temporary_directory.name)
        records: list[dict[str, Any]] = []
        for group, (record, background, residual, persistent_mask, raw_overlay) in zip(
            groups, analyzed
        ):
            center = group[2]
            frame_name = f"frame-{center.frame_index}"
            _write_png(output_dir / f"{frame_name}-raw.png", raw_overlay)
            if background is not None:
                _write_png(output_dir / f"{frame_name}-background.png", background)
            if residual is not None:
                residual_color = cv2.applyColorMap(residual, cv2.COLORMAP_INFERNO)
                _write_png(output_dir / f"{frame_name}-residual.png", residual_color)
            if persistent_mask is not None:
                _write_png(output_dir / f"{frame_name}-persistent-mask.png", persistent_mask)
            derived_overlay = cv2.cvtColor(center.image, cv2.COLOR_GRAY2BGR)
            for decision in record["derived_decisions"]:
                x, y = map(lambda value: int(round(value)), decision["raw_center_xy"])
                radius = max(1, int(round(decision["raw_radius_px"] or 1)))
                color = {
                    "temporally_nonpersistent_structural_hypothesis": (0, 220, 0),
                    "vetoed_persistent_or_stationary": (255, 100, 0),
                    "abstain_competing": (255, 0, 255),
                    "abstain_clipped": (0, 0, 255),
                }.get(decision["status"], (0, 180, 255))
                cv2.circle(derived_overlay, (x, y), radius, color, 1)
                cv2.circle(derived_overlay, (x, y), 2, color, -1)
            _write_png(output_dir / f"{frame_name}-derived.png", derived_overlay)
            records.append(record)
        raw_lines = "\n".join(
            json.dumps({"frame_index": record["frame_index"], **candidate}, sort_keys=True)
            for record in records
            for candidate in record["raw_hypotheses"]
        )
        derived_lines = "\n".join(
            json.dumps({"frame_index": record["frame_index"], **decision}, sort_keys=True)
            for record in records
            for decision in record["derived_decisions"]
        )
        (output_dir / "raw-hypotheses.jsonl").write_text(raw_lines + ("\n" if raw_lines else ""))
        (output_dir / "derived-decisions.jsonl").write_text(
            derived_lines + ("\n" if derived_lines else "")
        )
        report = {
            "status": "relative_temporal_background_diagnostic_only",
            "source_manifest_sha256": manifest_sha,
            "policy": TEMPORAL_POLICY,
            "policy_sha256": TEMPORAL_POLICY_SHA256,
            "radial_policy_sha256": RADIAL_POLICY_SHA256,
            "records": records,
            "frame_costs_ms": {
                str(record["frame_index"]): {
                    "raw_detector": record["raw_detector_cost_ms"],
                    "registration": record["registration_cost_ms"],
                    "grayscale_conversion": record["context_grayscale_conversion_ms"],
                }
                for record in records
            },
            "summary": {
                "center_frames": [record["frame_index"] for record in records],
                "raw_candidates": sum(record["raw_hypothesis_count"] for record in records),
                "derived_nonpersistent_hypotheses": sum(
                    decision["status"] == "temporally_nonpersistent_structural_hypothesis"
                    for record in records
                    for decision in record["derived_decisions"]
                ),
                "persistent_or_stationary_vetoes": sum(
                    decision["status"] == "vetoed_persistent_or_stationary"
                    for record in records
                    for decision in record["derived_decisions"]
                ),
                "poor_registration_abstentions": sum(
                    decision["status"] == "abstain_poor_registration"
                    for record in records
                    for decision in record["derived_decisions"]
                ),
            },
            "limitations": [
                "relative crop translation only; not canonical registration or geographic position",
                "no labels used; counts are descriptive, not precision or recall",
                "stationary player-like geometry may be removed as temporal background",
                "nonpersistent structure is not a player detection; identity/side unknown",
                "three centers and fifteen sampled half-second frames are not full-round coverage",
            ],
        }
        report_path = output_dir / "report.json"
        _write_json(report_path, report)
        code_digest = _compute_code_sha256()
        outputs = _hash_output_files(output_dir)
        _write_json(
            output_dir / "manifest.json",
            {
                "source_manifest_sha256": manifest_sha,
                "code_sha256": code_digest,
                "temporal_policy_sha256": TEMPORAL_POLICY_SHA256,
                "radial_policy_sha256": RADIAL_POLICY_SHA256,
                "outputs_sha256": outputs,
                "center_group_source_rows": [
                    {
                        "manifest_position": frame.manifest_position,
                        "frame_index": frame.frame_index,
                        "source_pts": frame.source_pts,
                    }
                    for group in groups
                    for frame in group
                ],
            },
        )
        if final_output_dir.exists() or final_output_dir.is_symlink():
            raise FileExistsError(f"refusing to publish over existing output: {final_output_dir}")
        os.rename(output_dir, final_output_dir)
    finally:
        temporary_directory.cleanup()
    return report
