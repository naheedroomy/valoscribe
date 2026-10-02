from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest

from valoscribe.detectors.portrait_center_localizer import (
    RADIAL_POLICY_SHA256,
    localize_radial_rims,
    localize_rim_hypotheses,
)
from valoscribe.tracking.portrait_center_experiment import (
    Annotation,
    Fixture,
    _maximum_cardinality_min_distance_matching,
    _unmatched_eligible_duplicates,
    run_portrait_center_experiment,
)

FIXTURE = Path(__file__).parents[1] / "fixtures" / "portrait_center_vta304_dev_v1.json"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _disk(
    center: tuple[int, int] = (60, 64),
    radius: int = 8,
    rim: int = 220,
    background: int = 50,
    extent: int = 360,
    start: int = 0,
    end: int = 360,
) -> np.ndarray:
    image = np.full((128, 128, 3), background, np.uint8)
    cv2.ellipse(image, center, (radius, radius), 0, start, end, (rim, rim, rim), 2)
    return image


def _annotation(
    identifier: str, center: tuple[float, float], uncertainty: float = 3.0
) -> dict[str, Any]:
    return {
        "id": identifier,
        "center_xy": list(center),
        "visible_bbox_xywh": [round(center[0] - 8), round(center[1] - 8), 16, 16],
        "uncertainty_px": uncertainty,
        "state": "visible",
        "review_evidence": ["synthetic independent annotation"],
        "review_observations": [
            {
                "reviewer": "synthetic-reviewer",
                "center_xy": list(center),
                "visible_bbox_xywh": [round(center[0] - 8), round(center[1] - 8), 16, 16],
                "evidence": "synthetic circle center",
            }
        ],
    }


def _synthetic_packet(tmp_path: Path) -> tuple[Path, Path, np.ndarray, dict[str, Any]]:
    root = tmp_path / "packet"
    (root / "crops").mkdir(parents=True)
    (root / "frames").mkdir()
    image = _disk(extent=128)
    crop_png = cv2.imencode(".png", image)[1].tobytes()
    crop_path = "crops/frame-000123.png"
    full_path = "frames/frame-000123.png"
    (root / crop_path).write_bytes(crop_png)
    (root / full_path).write_bytes(crop_png)
    row = {
        "frame_index": 123,
        "source_pts": 999,
        "candidate_crop_png": {
            "path": crop_path,
            "sha256": _sha(crop_png),
            "crop_bgr_sha256": _sha(image.tobytes()),
            "dimensions_px": [128, 128],
            "size_bytes": len(crop_png),
        },
        "candidate_crop_rect_xywh": [0, 0, 128, 128],
        "full_frame_png": {
            "path": full_path,
            "sha256": _sha(crop_png),
            "dimensions_px": [128, 128],
            "size_bytes": len(crop_png),
        },
        "decoded_bgr_sha256": _sha(image.tobytes()),
    }
    manifest = {"packet_kind": "synthetic_unit_fixture", "images": [row]}
    manifest_bytes = json.dumps(manifest, sort_keys=True).encode()
    (root / "manifest.json").write_bytes(manifest_bytes)
    fixture = {
        "schema_version": "vta304-portrait-center-dev-v1",
        "interpretation": "synthetic runner test only",
        "coordinate_convention": "native crop pixels; top-left origin; xywh visible boundaries",
        "source_manifest_sha256": _sha(manifest_bytes),
        "frames": [
            {
                "frame_index": 123,
                "source_pts": 999,
                "path": crop_path,
                "png_sha256": _sha(crop_png),
                "decoded_crop_bgr_sha256": _sha(image.tobytes()),
                "labels": [_annotation("synthetic-disk", (60.0, 64.0))],
                "uncertain_objects": [],
                "negative_regions": [],
            }
        ],
    }
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(json.dumps(fixture))
    return root, fixture_path, image, fixture


def test_radial_votes_localize_full_partial_white_and_nonwhite_rims() -> None:
    full = localize_radial_rims(_disk())
    assert len(full.hypotheses) == 1
    proposal = full.hypotheses[0]
    assert (proposal.center_x, proposal.center_y) == pytest.approx((60, 64), abs=1)
    assert proposal.radius_px == pytest.approx(9)
    assert proposal.radial_support is not None and proposal.radial_support > 0
    assert proposal.annular_contrast is not None and proposal.annular_contrast > 16
    assert proposal.normalized_score is not None and proposal.normalized_score >= 0.55
    assert proposal.policy_sha256 == RADIAL_POLICY_SHA256
    assert proposal.identity == proposal.side == "unknown"

    partial = localize_radial_rims(_disk(start=0, end=270))
    assert partial.hypotheses
    assert min(math.hypot(p.center_x - 60, p.center_y - 64) for p in partial.hypotheses) <= 4

    gray_nonwhite = localize_radial_rims(_disk(rim=150))
    assert any(math.hypot(p.center_x - 60, p.center_y - 64) <= 1 for p in gray_nonwhite.hypotheses)


def test_radial_votes_reject_lines_and_orthogonal_map_geometry() -> None:
    line = np.full((128, 128, 3), 50, np.uint8)
    cv2.line(line, (8, 64), (120, 64), (245, 245, 245), 2)
    assert localize_radial_rims(line).hypotheses == ()

    orthogonal = np.full((128, 128, 3), 50, np.uint8)
    cv2.rectangle(orthogonal, (15, 15), (110, 110), (245, 245, 245), 2)
    cv2.line(orthogonal, (8, 64), (120, 64), (245, 245, 245), 2)
    cv2.line(orthogonal, (64, 8), (64, 120), (245, 245, 245), 2)
    assert localize_radial_rims(orthogonal).hypotheses == ()


def test_overlap_clipping_and_repeatability_keep_explicit_uncertainty() -> None:
    overlap = _disk(center=(56, 64))
    cv2.circle(overlap, (68, 64), 8, (220, 220, 220), 2)
    first = localize_radial_rims(overlap)
    second = localize_radial_rims(overlap)
    assert len(first.hypotheses) >= 2
    assert any(p.status == "competing" for p in first.hypotheses)
    assert [(p.center_x, p.center_y, p.status) for p in first.hypotheses] == [
        (p.center_x, p.center_y, p.status) for p in second.hypotheses
    ]
    assert all(p.identity == p.side == "unknown" for p in first.hypotheses)

    clipped = localize_radial_rims(_disk(center=(4, 64)))
    assert any(p.status == "clipped" for p in clipped.hypotheses)
    assert all(
        "rim_intersects_crop_boundary" in p.reasons
        for p in clipped.hypotheses
        if p.status == "clipped"
    )


def test_frozen_contour_comparator_still_returns_old_hypotheses() -> None:
    image = _disk(radius=10)
    first = localize_rim_hypotheses(image).hypotheses
    second = localize_rim_hypotheses(image).hypotheses
    assert first
    assert first == second


def test_maximum_cardinality_matching_and_duplicate_count_counterexamples() -> None:
    labels = [
        Annotation.model_validate(_annotation("d", (322, 168), 8)),
        Annotation.model_validate(_annotation("e", (333, 170), 8)),
    ]
    match = _maximum_cardinality_min_distance_matching([(327, 169), (315, 168)], labels)
    assert len(match) == 2
    assert set(match) == {(0, 1), (1, 0)}

    nearby = [(327, 169), (328, 169)]
    complete = _maximum_cardinality_min_distance_matching(nearby, labels)
    assert len(complete) == 2
    assert set(complete) == {(0, 0), (1, 1)}
    assert _unmatched_eligible_duplicates(nearby, labels, complete) == 0

    surplus = [(327, 169), (328, 169), (329, 169)]
    partial = _maximum_cardinality_min_distance_matching(surplus, labels)
    assert len(partial) == 2
    assert _unmatched_eligible_duplicates(surplus, labels, partial) == 1


def test_reviewer_uncertainty_contains_each_recorded_center_and_fixture_ids_unique() -> None:
    data = json.loads(FIXTURE.read_text())
    Fixture.model_validate(data)
    too_small = json.loads(json.dumps(data))
    too_small["frames"][0]["labels"][0]["uncertainty_px"] = 2.0
    with pytest.raises(ValueError, match="include every reviewer center"):
        Fixture.model_validate(too_small)
    duplicate = json.loads(json.dumps(data))
    duplicate["frames"].append(duplicate["frames"][0])
    with pytest.raises(ValueError, match="frame_index values must be unique"):
        Fixture.model_validate(duplicate)
    duplicate = json.loads(json.dumps(data))
    duplicate["frames"][1]["labels"][0]["id"] = duplicate["frames"][0]["labels"][0]["id"]
    with pytest.raises(ValueError, match="annotation IDs must be unique"):
        Fixture.model_validate(duplicate)


def test_successful_authenticated_synthetic_runner_and_annotation_independence(
    tmp_path: Path,
) -> None:
    source, fixture_path, _, fixture = _synthetic_packet(tmp_path)
    first_output = tmp_path / "run-a"
    report = run_portrait_center_experiment(source, fixture_path, first_output)
    assert report["summary"]["reviewed_visible_labels"] == 1
    assert (first_output / "manifest.json").is_file()
    assert (first_output / "frame-123-prediction.png").is_file()

    revised = json.loads(json.dumps(fixture))
    revised["frames"][0]["labels"][0]["center_xy"] = [61.0, 64.0]
    revised["frames"][0]["labels"][0]["review_observations"][0]["center_xy"] = [61.0, 64.0]
    revised_path = tmp_path / "fixture-revised.json"
    revised_path.write_text(json.dumps(revised))
    second_output = tmp_path / "run-b"
    run_portrait_center_experiment(source, revised_path, second_output)
    assert (first_output / "hypotheses.jsonl").read_bytes() == (
        second_output / "hypotheses.jsonl"
    ).read_bytes()


@pytest.mark.parametrize(
    "corruption",
    [
        "crop_png",
        "full_png",
        "decoded_bgr",
        "crop_bgr",
        "pts",
        "path",
        "fixture_hash",
        "duplicate_frame",
        "duplicate_label",
        "duplicate_source_frame",
    ],
)
def test_authenticated_runner_refuses_corrupt_or_duplicate_inputs_without_output(
    tmp_path: Path, corruption: str
) -> None:
    source, fixture_path, _, fixture = _synthetic_packet(tmp_path)
    manifest_path = source / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    row = fixture["frames"][0]
    source_row = manifest["images"][0]
    if corruption == "crop_png":
        (source / source_row["candidate_crop_png"]["path"]).write_bytes(b"tampered")
    elif corruption == "full_png":
        (source / source_row["full_frame_png"]["path"]).write_bytes(b"tampered")
    elif corruption == "decoded_bgr":
        source_row["decoded_bgr_sha256"] = "0" * 64
    elif corruption == "crop_bgr":
        source_row["candidate_crop_png"]["crop_bgr_sha256"] = "0" * 64
    elif corruption == "pts":
        row["source_pts"] += 1
    elif corruption == "path":
        row["path"] = "../escape.png"
    elif corruption == "fixture_hash":
        row["png_sha256"] = "0" * 64
    elif corruption == "duplicate_frame":
        fixture["frames"].append(json.loads(json.dumps(row)))
    elif corruption == "duplicate_label":
        fixture["frames"][0]["uncertain_objects"].append(
            json.loads(json.dumps(fixture["frames"][0]["labels"][0]))
        )
    elif corruption == "duplicate_source_frame":
        manifest["images"].append(json.loads(json.dumps(source_row)))
    if corruption in {"decoded_bgr", "crop_bgr", "duplicate_source_frame"}:
        manifest_bytes = json.dumps(manifest, sort_keys=True).encode()
        manifest_path.write_bytes(manifest_bytes)
        fixture["source_manifest_sha256"] = _sha(manifest_bytes)
    fixture_path.write_text(json.dumps(fixture))
    output = tmp_path / "must-not-exist"
    with pytest.raises((ValueError, OSError)):
        run_portrait_center_experiment(source, fixture_path, output)
    assert not output.exists()


def test_output_symlink_is_refused_before_source_access(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    output = tmp_path / "link"
    output.symlink_to(target, target_is_directory=True)
    with pytest.raises(FileExistsError):
        run_portrait_center_experiment(tmp_path / "missing", FIXTURE, output)
    assert list(target.iterdir()) == []


def test_failed_image_write_does_not_emit_success_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, fixture_path, _, _ = _synthetic_packet(tmp_path)
    monkeypatch.setattr(cv2, "imwrite", lambda *_args, **_kwargs: False)
    output = tmp_path / "failed-write"
    with pytest.raises(OSError, match="failed to write diagnostic image"):
        run_portrait_center_experiment(source, fixture_path, output)
    assert not (output / "report.json").exists()
