"""One-pass local VTA-304 portrait-rim feasibility run; not production output."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path, PurePosixPath
from typing import Any

import cv2
import numpy as np
from pydantic import Field, model_validator

from valoscribe.detectors.minimap_color_detector import (
    MinimapColorCandidateDetector,
    MinimapColorProfile,
)
from valoscribe.detectors.portrait_center_localizer import (
    RADIAL_POLICY,
    RADIAL_POLICY_SHA256,
    localize_radial_rims,
    localize_rim_hypotheses,
)
from valoscribe.types.persistent import PersistentModel


class ReviewerGeometry(PersistentModel):
    reviewer: str
    center_xy: tuple[float, float]
    visible_bbox_xywh: tuple[int, int, int, int]
    evidence: str


class Annotation(PersistentModel):
    id: str
    center_xy: tuple[float, float]
    visible_bbox_xywh: tuple[int, int, int, int]
    uncertainty_px: float = Field(gt=0)
    state: str
    overlap: bool = False
    review_evidence: list[str]
    review_observations: list[ReviewerGeometry] = Field(default_factory=list)

    @model_validator(mode="after")
    def reviewer_centers_fit_uncertainty(self) -> Annotation:
        for observation in self.review_observations:
            distance = math.hypot(
                observation.center_xy[0] - self.center_xy[0],
                observation.center_xy[1] - self.center_xy[1],
            )
            if distance > self.uncertainty_px + 1e-9:
                raise ValueError("uncertainty_px must include every reviewer center")
        return self


class NegativeRegion(PersistentModel):
    id: str
    bbox_xywh: tuple[int, int, int, int]
    state: str
    review_evidence: list[str]


class FrameFixture(PersistentModel):
    frame_index: int
    source_pts: int
    path: str
    png_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decoded_crop_bgr_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    labels: list[Annotation]
    uncertain_objects: list[Annotation]
    negative_regions: list[NegativeRegion]


class Fixture(PersistentModel):
    schema_version: str
    interpretation: str
    coordinate_convention: str
    source_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    frames: list[FrameFixture]

    @model_validator(mode="after")
    def frame_and_annotation_ids_are_unique(self) -> Fixture:
        frame_indices = [frame.frame_index for frame in self.frames]
        if len(frame_indices) != len(set(frame_indices)):
            raise ValueError("fixture frame_index values must be unique")
        ids = [
            identifier
            for frame in self.frames
            for identifier in [
                *(item.id for item in frame.labels),
                *(item.id for item in frame.uncertain_objects),
                *(item.id for item in frame.negative_regions),
            ]
        ]
        if len(ids) != len(set(ids)):
            raise ValueError("annotation IDs must be unique across fixture frames")
        return self


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _contained(root: Path, relative: str) -> Path:
    rel = PurePosixPath(relative)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError("source manifest path must be relative and contained")
    candidate = root.joinpath(*rel.parts)
    if candidate.is_symlink() or not candidate.resolve().is_relative_to(root.resolve()):
        raise ValueError("source path must be a contained regular path")
    return candidate


def run_portrait_center_experiment(
    source_root: Path, fixture_path: Path, output_dir: Path, *, method: str = "radial"
) -> dict[str, Any]:
    """Authenticate packet and scoring fixture, run frozen detector once, emit diagnostics."""
    if method not in {"radial", "contour"}:
        raise ValueError("method must be 'radial' or 'contour'")
    if output_dir.exists() or output_dir.is_symlink():
        raise FileExistsError(f"refusing existing or symlink output directory: {output_dir}")
    root = source_root.resolve(strict=True)
    manifest_path = _contained(root, "manifest.json")
    manifest_bytes = manifest_path.read_bytes()
    manifest_hash = _sha(manifest_bytes)
    fixture_bytes = fixture_path.read_bytes()
    fixture = Fixture.model_validate_json(fixture_bytes)
    if fixture.schema_version != "vta304-portrait-center-dev-v1":
        raise ValueError("unsupported portrait center fixture version")
    if fixture.source_manifest_sha256 != manifest_hash:
        raise ValueError("fixture does not bind this source manifest")
    manifest = json.loads(manifest_bytes)
    manifest_rows = manifest["images"]
    source_indices = [row["frame_index"] for row in manifest_rows]
    if len(source_indices) != len(set(source_indices)):
        raise ValueError("source manifest frame_index values must be unique")
    source_paths = [row["candidate_crop_png"]["path"] for row in manifest_rows]
    if len(source_paths) != len(set(source_paths)):
        raise ValueError("source manifest crop paths must be unique")
    source_rows = {row["frame_index"]: row for row in manifest_rows}
    verified: list[tuple[FrameFixture, Any, str]] = []
    for row in fixture.frames:
        source = source_rows.get(row.frame_index)
        if source is None or source["source_pts"] != row.source_pts:
            raise ValueError("fixture frame/PTS is absent from source manifest")
        if row.path != source["candidate_crop_png"]["path"]:
            raise ValueError("fixture crop path differs from source manifest")
        path = _contained(root, row.path)
        png = path.read_bytes()
        if _sha(png) != row.png_sha256 or row.png_sha256 != source["candidate_crop_png"]["sha256"]:
            raise ValueError("source crop PNG hash mismatch")
        full_path = _contained(root, source["full_frame_png"]["path"])
        full_png = full_path.read_bytes()
        if _sha(full_png) != source["full_frame_png"]["sha256"]:
            raise ValueError("source full-frame PNG hash mismatch")
        full = cv2.imdecode(np.frombuffer(full_png, dtype=np.uint8), cv2.IMREAD_COLOR)
        if full is None or _sha(full.tobytes()) != source["decoded_bgr_sha256"]:
            raise ValueError("decoded source full-frame BGR hash mismatch")
        x, y, width, height = source["candidate_crop_rect_xywh"]
        crop = full[y : y + height, x : x + width]
        decoded_crop_png = cv2.imdecode(np.frombuffer(png, dtype=np.uint8), cv2.IMREAD_COLOR)
        expected_crop_hash = source["candidate_crop_png"]["crop_bgr_sha256"]
        if (
            decoded_crop_png is None
            or _sha(decoded_crop_png.tobytes()) != expected_crop_hash
            or _sha(crop.tobytes()) != row.decoded_crop_bgr_sha256
            or row.decoded_crop_bgr_sha256 != expected_crop_hash
        ):
            raise ValueError("decoded source crop BGR hash mismatch")
        verified.append((row, crop, _sha(png)))

    # Run prediction before annotations are used for scoring or overlays.
    localizer = localize_radial_rims if method == "radial" else localize_rim_hypotheses
    results = [(row, image, digest, localizer(image)) for row, image, digest in verified]
    contour_comparisons = (
        {row.frame_index: localize_rim_hypotheses(image) for row, image, _ in verified}
        if method == "radial"
        else {}
    )
    profile_path = Path(__file__).parents[1] / "config" / "minimap_color_vta201_train_profile.json"
    profile = MinimapColorProfile.model_validate_json(profile_path.read_text())
    color_detector = MinimapColorCandidateDetector(profile)
    output_dir.mkdir(parents=False, exist_ok=False)
    hypothesis_lines: list[str] = []
    frame_reports: list[dict[str, Any]] = []
    for row, image, crop_digest, result in results:
        for item in result.hypotheses:
            hypothesis_lines.append(
                json.dumps(
                    {"frame_index": row.frame_index, **item.model_dump(mode="json")}, sort_keys=True
                )
            )
        # Annotation overlay is separate from prediction/edge artifacts.
        annotation_overlay = image.copy()
        for label in row.labels:
            x, y, w, h = label.visible_bbox_xywh
            cv2.rectangle(annotation_overlay, (x, y), (x + w - 1, y + h - 1), (0, 255, 0), 1)
            cv2.circle(
                annotation_overlay,
                (round(label.center_xy[0]), round(label.center_xy[1])),
                2,
                (0, 255, 0),
                -1,
            )
        name = f"frame-{row.frame_index}"
        for suffix, image_artifact in (
            ("prediction", result.overlay),
            ("edges", result.edge_map),
            ("annotations", annotation_overlay),
        ):
            artifact_path = output_dir / f"{name}-{suffix}.png"
            if not cv2.imwrite(str(artifact_path), image_artifact):
                raise OSError(f"failed to write diagnostic image: {artifact_path}")
        color = color_detector.detect(image, source_frame=row.frame_index)
        predictions = list(result.hypotheses)
        available = [label for label in row.labels if label.state == "visible"]
        contour_match_count = None
        contour_hypothesis_count = None
        if method == "radial":
            contour_hypotheses = contour_comparisons[row.frame_index].hypotheses
            contour_pairs = _maximum_cardinality_min_distance_matching(
                [(item.center_x, item.center_y) for item in contour_hypotheses], available
            )
            contour_match_count = len(contour_pairs)
            contour_hypothesis_count = len(contour_hypotheses)
        raw_centers = [
            (candidate.crop_point.x * image.shape[1], candidate.crop_point.y * image.shape[0])
            for candidate in color.candidates
        ]
        errors: list[dict[str, float | str | bool]] = []
        prediction_centers = [(item.center_x, item.center_y) for item in predictions]
        eligible_pairs = _maximum_cardinality_min_distance_matching(prediction_centers, available)
        for label_index, label in enumerate(available):
            distances = [
                math.hypot(p.center_x - label.center_xy[0], p.center_y - label.center_xy[1])
                for p in predictions
            ]
            if not distances:
                errors.append(
                    {
                        "label_id": label.id,
                        "nearest_center_error_px": "no_hypothesis",
                        "uncertainty_px": label.uncertainty_px,
                        "within_uncertainty": False,
                        "bbox_iou": 0.0,
                    }
                )
                continue
            nearest_index = min(range(len(distances)), key=distances.__getitem__)
            distance = distances[nearest_index]
            errors.append(
                {
                    "label_id": label.id,
                    "nearest_center_error_px": round(distance, 3),
                    "uncertainty_px": label.uncertainty_px,
                    "within_uncertainty": distance <= label.uncertainty_px,
                    "bbox_iou": round(
                        _bbox_iou(
                            label.visible_bbox_xywh, predictions[nearest_index].boundary_xywh
                        ),
                        4,
                    ),
                }
            )

        assigned_labels = {label_index for label_index, _ in eligible_pairs}
        assigned_predictions = {prediction_index for _, prediction_index in eligible_pairs}
        duplicate_hypotheses = _unmatched_eligible_duplicates(
            prediction_centers, available, eligible_pairs
        )
        false_localizations = sum(
            any(
                x <= p.center_x < x + w and y <= p.center_y < y + h
                for negative in row.negative_regions
                if negative.state == "portrait_free"
                for x, y, w, h in [negative.bbox_xywh]
            )
            for p in predictions
        )
        frame_reports.append(
            {
                "frame_index": row.frame_index,
                "reviewed_visible_count": len(available),
                "hypothesis_count": len(predictions),
                "frozen_contour_comparator_hypothesis_count": contour_hypothesis_count,
                "frozen_contour_comparator_matches": contour_match_count,
                "matched_label_count": len(assigned_labels),
                "missed_labels": len(available) - len(assigned_labels),
                "unmatched_structural_hypotheses": len(predictions) - len(assigned_predictions),
                "duplicate_hypothesis_count": duplicate_hypotheses,
                "ambiguous_overlap_annotation_count": sum(label.overlap for label in available),
                "abstained_reviewed_labels": len(available) - len(assigned_labels),
                "center_errors_outside_uncertainty": sum(
                    not bool(error["within_uncertainty"]) for error in errors
                ),
                "center_errors": errors,
                "false_localizations_in_negative_regions": false_localizations,
                "uncertain_annotations_excluded_from_scoring": len(row.uncertain_objects)
                + sum(label.state != "visible" for label in row.labels),
                "legacy_raw_color_candidate_count": len(color.candidates),
                "raw_color_bbox_center_baseline": _score_centers(raw_centers, available),
                "structural_hypothesis_count": len(predictions),
                "overlap_or_clipped_hypothesis_count": sum(
                    p.status in {"clipped", "competing"} for p in predictions
                ),
                "annotation_counts_are_partial": True,
            }
        )
    lines = "\n".join(hypothesis_lines) + ("\n" if hypothesis_lines else "")
    (output_dir / "hypotheses.jsonl").write_text(lines)
    policy = {
        "method": method,
        "parameters": RADIAL_POLICY
        if method == "radial"
        else {
            "canny": [35, 105],
            "close_kernel": 3,
            "contour_size_px": [14, 28],
            "aspect_ratio": [0.62, 1.6],
            "minimum_circularity": 0.45,
        },
        "policy_sha256": RADIAL_POLICY_SHA256 if method == "radial" else None,
        "settings_frozen_before_scoring": True,
        "interpretation": "uncalibrated structural hypotheses only; no semantic portrait claim",
    }
    report = {
        "status": "development_feasibility_only",
        "source_manifest_sha256": manifest_hash,
        "fixture_sha256": _sha(fixture_bytes),
        "code_sha256": _sha(
            Path(__file__).read_bytes()
            + Path(__file__)
            .parents[1]
            .joinpath("detectors", "portrait_center_localizer.py")
            .read_bytes()
            + profile_path.read_bytes()
        ),
        "policy": policy,
        "frames": frame_reports,
        "summary": {
            "reviewed_visible_labels": sum(r["reviewed_visible_count"] for r in frame_reports),
            "matched_visible_labels": sum(r["matched_label_count"] for r in frame_reports),
            "abstained_visible_labels": sum(r["abstained_reviewed_labels"] for r in frame_reports),
            "duplicates": sum(r["duplicate_hypothesis_count"] for r in frame_reports),
            "unmatched_structural_hypotheses": sum(
                r["unmatched_structural_hypotheses"] for r in frame_reports
            ),
            "hypotheses": sum(r["hypothesis_count"] for r in frame_reports),
            "false_localizations_in_explicit_negative_regions": sum(
                r["false_localizations_in_negative_regions"] for r in frame_reports
            ),
            "uncertain_labels_not_scored": sum(
                r["uncertain_annotations_excluded_from_scoring"] for r in frame_reports
            ),
        },
        "limitations": [
            "review annotations are approximate, partial, and not calibrated ground truth",
            "center-error nearest matching is descriptive and not a one-to-one assignment metric",
            "structural geometry does not establish portrait semantics",
            "no identities, sides, or tracks emitted",
        ],
    }
    (output_dir / "report.json").write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    (output_dir / "manifest.json").write_text(
        json.dumps(
            {
                "source_manifest_sha256": manifest_hash,
                "fixture_sha256": _sha(fixture_bytes),
                "code_sha256": report["code_sha256"],
                "policy": policy,
                "outputs": sorted(p.name for p in output_dir.iterdir()),
            },
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )
    return report


def _maximum_cardinality_min_distance_matching(
    centers: list[tuple[float, float]], labels: list[Annotation]
) -> list[tuple[int, int]]:
    """Find maximum-cardinality eligible pairs, minimizing total center error."""
    label_count, center_count = len(labels), len(centers)
    source = 0
    label_offset = 1
    center_offset = label_offset + label_count
    sink = center_offset + center_count
    graph: list[list[list[float | int]]] = [[] for _ in range(sink + 1)]

    def add_edge(start: int, end: int, capacity: int, cost: float) -> list[float | int]:
        forward: list[float | int] = [end, len(graph[end]), capacity, cost]
        reverse: list[float | int] = [start, len(graph[start]), 0, -cost]
        graph[start].append(forward)
        graph[end].append(reverse)
        return forward

    for label_index in range(label_count):
        add_edge(source, label_offset + label_index, 1, 0.0)
    pair_edges: list[tuple[int, int, list[float | int]]] = []
    for label_index, label in enumerate(labels):
        for center_index, (x, y) in enumerate(centers):
            distance = math.hypot(x - label.center_xy[0], y - label.center_xy[1])
            if distance <= label.uncertainty_px:
                edge = add_edge(
                    label_offset + label_index,
                    center_offset + center_index,
                    1,
                    distance,
                )
                pair_edges.append((label_index, center_index, edge))
    for center_index in range(center_count):
        add_edge(center_offset + center_index, sink, 1, 0.0)

    node_count = len(graph)
    while True:
        distances = [math.inf] * node_count
        previous: list[tuple[int, int] | None] = [None] * node_count
        distances[source] = 0.0
        for _ in range(node_count - 1):
            changed = False
            for start, edges in enumerate(graph):
                if not math.isfinite(distances[start]):
                    continue
                for edge_index, edge in enumerate(edges):
                    end, _, capacity, cost = edge
                    if int(capacity) <= 0:
                        continue
                    candidate_distance = distances[start] + float(cost)
                    if candidate_distance < distances[int(end)] - 1e-12:
                        distances[int(end)] = candidate_distance
                        previous[int(end)] = (start, edge_index)
                        changed = True
            if not changed:
                break
        if previous[sink] is None:
            break
        node = sink
        while node != source:
            prior = previous[node]
            if prior is None:
                raise RuntimeError("incomplete residual matching path")
            start, edge_index = prior
            edge = graph[start][edge_index]
            edge[2] = int(edge[2]) - 1
            reverse = graph[node][int(edge[1])]
            reverse[2] = int(reverse[2]) + 1
            node = start
    return sorted(
        (label_index, center_index)
        for label_index, center_index, edge in pair_edges
        if int(edge[2]) == 0
    )


def _unmatched_eligible_duplicates(
    centers: list[tuple[float, float]],
    labels: list[Annotation],
    assignments: list[tuple[int, int]],
) -> int:
    """Count each unmatched proposal once when it duplicates a matched label."""
    matched_labels = {label_index for label_index, _ in assignments}
    matched_centers = {center_index for _, center_index in assignments}
    return sum(
        center_index not in matched_centers
        and any(
            math.hypot(
                centers[center_index][0] - labels[label_index].center_xy[0],
                centers[center_index][1] - labels[label_index].center_xy[1],
            )
            <= labels[label_index].uncertainty_px
            for label_index in matched_labels
        )
        for center_index in range(len(centers))
    )


def _score_centers(centers: list[tuple[float, float]], labels: list[Annotation]) -> dict[str, Any]:
    """Descriptive nearest raw-center baseline; labels do not seed detection."""
    distances = [
        min(
            (math.hypot(x - label.center_xy[0], y - label.center_xy[1]) for x, y in centers),
            default=None,
        )
        for label in labels
    ]
    return {
        "candidate_count": len(centers),
        "nearest_center_error_px": [
            None if value is None else round(value, 3) for value in distances
        ],
        "within_label_uncertainty_count": sum(
            value is not None and value <= label.uncertainty_px
            for value, label in zip(distances, labels)
        ),
        "interpretation": "legacy raw color contour bbox-center baseline; uncalibrated",
    }


def _bbox_iou(left: tuple[int, int, int, int], right: tuple[int, int, int, int]) -> float:
    lx, ly, lw, lh = left
    rx, ry, rw, rh = right
    intersection = max(0, min(lx + lw, rx + rw) - max(lx, rx)) * max(
        0, min(ly + lh, ry + rh) - max(ly, ry)
    )
    union = lw * lh + rw * rh - intersection
    return intersection / union if union else 0.0
