"""Opt-in verification of provisional VTA-102 annotation input files."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import cv2

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/map_annotations/ascent-vta102-source-interior-v1.json"


class AnnotationValidationError(ValueError):
    """Raised when provisional annotation evidence does not match its bindings."""


def _sha256(path: Path) -> str:
    if not path.is_file():
        raise AnnotationValidationError(f"required image is missing: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(source_path: Path) -> dict[str, Any]:
    """Verify the source, frozen mapping, canonical hash, and accepted pixel centers."""
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    source = fixture["source"]
    canonical = fixture["canonical_mapping"]
    if _sha256(source_path) != source["sha256"]:
        raise AnnotationValidationError("source image SHA-256 mismatch")
    source_image = cv2.imread(str(source_path), cv2.IMREAD_UNCHANGED)
    if source_image is None or (source_image.shape[1], source_image.shape[0]) != (
        source["dimensions_px"]["width"],
        source["dimensions_px"]["height"],
    ):
        raise AnnotationValidationError("source image dimensions or decoding mismatch")

    canonical_path = ROOT / canonical["asset_path"]
    if _sha256(canonical_path) != canonical["sha256"]:
        raise AnnotationValidationError("canonical image SHA-256 mismatch")
    canonical_image = cv2.imread(str(canonical_path), cv2.IMREAD_UNCHANGED)
    if canonical_image is None or canonical_image.ndim != 3 or canonical_image.shape[2] != 4:
        raise AnnotationValidationError("canonical image must decode as RGBA")
    if (canonical_image.shape[1], canonical_image.shape[0]) != (
        canonical["dimensions_px"]["width"],
        canonical["dimensions_px"]["height"],
    ):
        raise AnnotationValidationError("canonical image dimensions mismatch")

    manifest_path = ROOT / canonical["mapping_manifest_path"]
    if _sha256(manifest_path) != canonical["mapping_manifest_sha256"]:
        raise AnnotationValidationError("frozen mapping manifest SHA-256 mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest["source"]["sha256"] != source["sha256"]
        or manifest["canonical_asset"]["sha256"] != canonical["sha256"]
    ):
        raise AnnotationValidationError("mapping manifest image bindings mismatch")

    alpha = canonical_image[:, :, 3]
    for annotation in fixture["source_annotations"]:
        x, y = annotation["center_px"]
        if alpha[y, x] == 0:
            raise AnnotationValidationError(
                f"annotation center is outside canonical alpha interior: {annotation['label']}"
            )
    for annotation in fixture["rejected_annotations"]:
        x, y = annotation["center_px"]
        if alpha[y, x] != 0:
            label = annotation["label"]
            raise AnnotationValidationError(
                f"rejected annotation center unexpectedly enters alpha interior: {label}"
            )
    return {
        "source_sha256": source["sha256"],
        "canonical_sha256": canonical["sha256"],
        "accepted_annotation_count": len(fixture["source_annotations"]),
        "rejected_annotation_count": len(fixture["rejected_annotations"]),
        "geometry_status": fixture["geometry_status"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-image",
        type=Path,
        default=Path("/tmp/vta102-ascent-community-overview.png"),
        help="local, independently acquired community overview (not bundled)",
    )
    args = parser.parse_args()
    try:
        print(json.dumps(validate(args.source_image), indent=2, sort_keys=True))
    except (AnnotationValidationError, OSError, KeyError, ValueError) as error:
        parser.exit(2, f"annotation validation failed closed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
