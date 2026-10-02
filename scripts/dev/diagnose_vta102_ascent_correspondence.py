"""Register the external VTA-102 overview to the canonical Ascent silhouette."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import TypedDict, cast

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "src/valoscribe/config/ascent_vta102_correspondence.json"
DEFAULT_SOURCE = Path("/tmp/vta102-ascent-community-overview.png")
ARTIFACT_DIR = Path("/tmp")


class DiagnosticError(ValueError):
    """Raised when an input image cannot be verified for this diagnostic."""


class SilhouetteFit(TypedDict):
    normalized_scale: float
    normalized_translation_px_at_256: list[float]
    occupancy_iou: float
    symmetric_contour_chamfer_px_at_1024: float


def _evaluate_anchors(
    anchors: list[dict[str, object]], matrix: list[list[float]]
) -> dict[str, object]:
    """Score fixed independent labels with Euclidean residuals in canonical pixels."""
    transform = np.asarray(matrix, dtype=np.float64)
    if transform.shape != (2, 3):
        raise DiagnosticError("anchor evaluation requires a 2x3 affine matrix")
    rows: list[dict[str, object]] = []
    for anchor in anchors:
        source = np.asarray(anchor["source_px"], dtype=np.float64)
        target = np.asarray(anchor["canonical_px"], dtype=np.float64)
        if source.shape != (2,) or target.shape != (2,):
            raise DiagnosticError("anchor coordinates must be two-dimensional")
        prediction = transform @ np.append(source, 1.0)
        residual = float(np.linalg.norm(prediction - target))
        source_uncertainty = float(anchor["source_uncertainty_px"])
        target_uncertainty = float(anchor["target_uncertainty_px"])
        allowance = float(anchor["scale_for_uncertainty"]) * source_uncertainty + target_uncertainty
        rows.append(
            {
                "label": anchor["label"],
                "predicted_canonical_px": prediction.tolist(),
                "residual_euclidean_px": residual,
                "allowed_residual_px": allowance,
                "pass": residual <= allowance,
            }
        )
    if not rows:
        raise DiagnosticError("anchor evaluation requires fixed reviewer labels")
    return {
        "metric": "Euclidean source-to-canonical point residual in canonical pixels",
        "threshold": "source_uncertainty_px * transform_scale + target_uncertainty_px",
        "anchor_count": len(rows),
        "passed_count": sum(bool(row["pass"]) for row in rows),
        "maximum_residual_px": max(float(row["residual_euclidean_px"]) for row in rows),
        "anchors": rows,
    }


def _load_verified_image(path: Path, expected_sha256: str, expected_size: tuple[int, int]):
    if not path.is_file():
        raise DiagnosticError(f"required image is missing: {path}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != expected_sha256:
        raise DiagnosticError(f"image SHA-256 mismatch: {path}")
    image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if image is None or (image.shape[1], image.shape[0]) != expected_size:
        raise DiagnosticError(f"image dimensions or decoding mismatch: {path}")
    return image


def _score_transform(
    source: np.ndarray, target: np.ndarray, scale: float, tx: float, ty: float
) -> tuple[float, float, float]:
    height, width = target.shape
    matrix = np.array([[scale, 0.0, tx], [0.0, scale, ty]], dtype=np.float32)
    # OpenCV's stub excludes uint8 although warpAffine accepts it at runtime.
    warped = cv2.warpAffine(  # type: ignore[call-overload]
        source.astype(np.uint8), matrix, (width, height), flags=cv2.INTER_NEAREST, borderValue=0
    ).astype(bool)
    intersection = np.logical_and(warped, target).sum()
    union = np.logical_or(warped, target).sum()
    iou = float(intersection / union) if union else 0.0
    kernel = np.ones((3, 3), dtype=np.uint8)
    warped_edge = cv2.morphologyEx(warped.astype(np.uint8), cv2.MORPH_GRADIENT, kernel) > 0
    target_edge = cv2.morphologyEx(target.astype(np.uint8), cv2.MORPH_GRADIENT, kernel) > 0
    to_target = cv2.distanceTransform((~target_edge).astype(np.uint8), cv2.DIST_L2, 3)
    to_source = cv2.distanceTransform((~warped_edge).astype(np.uint8), cv2.DIST_L2, 3)
    if not warped_edge.any() or not target_edge.any():
        return -1.0, iou, float("inf")
    chamfer = float((to_target[warped_edge].mean() + to_source[target_edge].mean()) / 2)
    return iou - 0.002 * chamfer, iou, chamfer


def _register(source: np.ndarray, target: np.ndarray) -> SilhouetteFit:
    """Fit uniform scale and translation at progressively finer image scales."""
    best_scale, best_tx, best_ty = 1.0, 0.0, 0.0
    for size, scale_radius, scale_step, shift_radius, shift_step in (
        (256, 0.06, 0.005, 18.0, 2.0),
        (512, 0.012, 0.001, 5.0, 1.0),
        (1024, 0.003, 0.0005, 2.0, 0.5),
    ):
        src = cv2.resize(
            source.astype(np.uint8), (size, size), interpolation=cv2.INTER_NEAREST
        ).astype(bool)
        dst = cv2.resize(
            target.astype(np.uint8), (size, size), interpolation=cv2.INTER_NEAREST
        ).astype(bool)
        center_tx, center_ty = best_tx * size / 256, best_ty * size / 256
        scales = np.arange(
            best_scale - scale_radius,
            best_scale + scale_radius + scale_step / 2,
            scale_step,
        )
        shifts_x = np.arange(
            center_tx - shift_radius,
            center_tx + shift_radius + shift_step / 2,
            shift_step,
        )
        shifts_y = np.arange(
            center_ty - shift_radius,
            center_ty + shift_radius + shift_step / 2,
            shift_step,
        )
        candidates: list[tuple[float, float, float, float, float, float]] = []
        for scale in scales:
            for tx in shifts_x:
                for ty in shifts_y:
                    score, iou, chamfer = _score_transform(
                        src, dst, float(scale), float(tx), float(ty)
                    )
                    candidates.append(
                        (score, iou, chamfer, float(scale), float(tx), float(ty))
                    )
        _, _, _, best_scale, best_tx, best_ty = max(candidates)
        best_tx *= 256 / size
        best_ty *= 256 / size
    final_score, final_iou, final_chamfer = _score_transform(
        cv2.resize(
            source.astype(np.uint8), (1024, 1024), interpolation=cv2.INTER_NEAREST
        ).astype(bool),
        cv2.resize(
            target.astype(np.uint8), (1024, 1024), interpolation=cv2.INTER_NEAREST
        ).astype(bool),
        best_scale,
        best_tx * 4,
        best_ty * 4,
    )
    del final_score
    return {
        "normalized_scale": float(best_scale),
        "normalized_translation_px_at_256": [float(best_tx), float(best_ty)],
        "occupancy_iou": final_iou,
        "symmetric_contour_chamfer_px_at_1024": final_chamfer,
    }


def diagnose(source_path: Path, artifact_dir: Path = ARTIFACT_DIR) -> dict[str, object]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    source_data = manifest["source"]
    size = source_data["dimensions_px"]
    source_image = _load_verified_image(
        source_path, source_data["sha256"], (size["width"], size["height"])
    )
    canonical_data = manifest["canonical_asset"]
    canonical_path = ROOT / "src/valoscribe/config" / canonical_data["local_path"]
    canonical_size = canonical_data["dimensions_px"]
    canonical = _load_verified_image(
        canonical_path,
        canonical_data["sha256"],
        (canonical_size["width"], canonical_size["height"]),
    )
    source_mask = np.rot90(cv2.cvtColor(source_image, cv2.COLOR_BGR2GRAY) > 25, 1)
    canonical_mask = canonical[:, :, 3] > 0
    fit = _register(source_mask, canonical_mask)
    evaluation_data = manifest["independent_heldout_anchor_evaluation"]
    anchors = evaluation_data["anchors"]
    anchor_matrix = evaluation_data["evaluated_transform_source_to_canonical_affine_matrix"]
    anchor_evaluation = _evaluate_anchors(anchors, anchor_matrix)
    anchor_evaluation["provenance"] = evaluation_data["provenance"]
    anchor_evaluation["evaluated_transform_source_to_canonical_affine_matrix"] = anchor_matrix
    if anchor_evaluation["passed_count"] != anchor_evaluation["anchor_count"]:
        raise DiagnosticError("one or more fixed independent anchors exceed their frozen threshold")
    scale = fit["normalized_scale"] * canonical.shape[1] / source_mask.shape[1]
    tx, ty = fit["normalized_translation_px_at_256"]
    raw_tx, raw_ty = tx * canonical.shape[1] / 256, ty * canonical.shape[0] / 256
    matrix = [
        [0.0, scale, raw_tx],
        [-scale, 0.0, scale * (source_mask.shape[0] - 1) + raw_ty],
    ]
    artifact_dir.mkdir(parents=True, exist_ok=True)
    pixel_scale = fit["normalized_scale"] * canonical.shape[1] / source_mask.shape[1]
    warped = cv2.warpAffine(
        source_mask.astype(np.uint8),
        np.array([[pixel_scale, 0, raw_tx], [0, pixel_scale, raw_ty]], np.float32),
        (canonical.shape[1], canonical.shape[0]),
        flags=cv2.INTER_NEAREST,
    )
    target = canonical_mask.astype(np.uint8)
    overlay = np.zeros((*target.shape, 3), dtype=np.uint8)
    overlay[target > 0] = (100, 100, 100)
    edge_contours, _ = cv2.findContours(warped, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(overlay, edge_contours, -1, (0, 0, 255), 2)
    overlay_path = artifact_dir / "vta102-ascent-registered-overlay.png"
    cv2.imwrite(str(overlay_path), overlay)
    report = {
        "status": "silhouette_registration_diagnostic",
        "source_sha256": source_data["sha256"],
        "canonical_sha256": canonical_data["sha256"],
        "orientation": "90_degrees_counterclockwise",
        "method": (
            "coarse-to-fine similarity scale/translation fit on binary floor "
            "occupancy; objective combines IoU and symmetric contour distance"
        ),
        "fit": fit,
        "candidate_source_to_canonical_affine_matrix": matrix,
        "independent_heldout_anchor_evaluation": anchor_evaluation,
        "anchor_status": "six independently annotated fixed point pairs pass uncertainty bounds",
        "transform_metric": anchor_evaluation["metric"],
        "overlay_path": str(overlay_path),
        "registration_established": False,
        "geometry_status": "pending",
        "limitations": (
            "Textured fills and linework contribute to occupancy; labels and interior "
            "details are not wall geometry. The registration is only an overview-to-"
            "canonical silhouette correspondence, not validated playable geometry."
        ),
    }
    report = cast(
        dict[str, object],
        json.loads(json.dumps(report, default=lambda value: value.item())),
    )
    (artifact_dir / "vta102-ascent-registration-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-image", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--artifact-dir", type=Path, default=ARTIFACT_DIR)
    args = parser.parse_args()
    try:
        print(json.dumps(diagnose(args.source_image, args.artifact_dir), indent=2, sort_keys=True))
    except (DiagnosticError, OSError, KeyError, ValueError) as error:
        parser.exit(2, f"diagnostic failed closed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
