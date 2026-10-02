"""VTA-102 external overview correspondence evidence stays fail-closed."""

import hashlib
import json
from pathlib import Path
from runpy import run_path

import pytest

ROOT = Path(__file__).parents[2]
MANIFEST = ROOT / "src/valoscribe/config/ascent_vta102_correspondence.json"
DIAGNOSTIC = run_path(str(ROOT / "scripts/dev/diagnose_vta102_ascent_correspondence.py"))
DIAGNOSE = DIAGNOSTIC["diagnose"]
DIAGNOSTIC_ERROR = DIAGNOSTIC["DiagnosticError"]


def test_vta102_manifest_records_bounded_fit_without_promoting_geometry() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert manifest["schema_version"] == "1.2"
    assert manifest["assessment_status"] == "independent_anchor_evaluation_passed_geometry_pending"
    assert manifest["source"]["url"].startswith("https://valoranthub.com/")
    assert manifest["source"]["sha256"] == (
        "c62eea459c56980bf751bdecb0583f6a02da72095251c09fe74e5b4caccb1a76"
    )
    assert manifest["orientation_observation"]["overview_to_canonical"] == (
        "90_degrees_counterclockwise"
    )
    assert manifest["orientation_observation"]["not_a_registered_transform"] is True
    fit = manifest["diagnostic"]["optimized_silhouette_fit"]
    assert fit["occupancy_iou_at_1024"] == pytest.approx(0.97035)
    assert fit["symmetric_contour_chamfer_px_at_1024"] == pytest.approx(1.209)
    assert len(fit["candidate_source_to_canonical_affine_matrix"]) == 2
    assert manifest["candidate_transform"] is None
    evaluation = manifest["independent_heldout_anchor_evaluation"]
    assert evaluation["provenance"]["labels_are_fixed"] is True
    assert evaluation["provenance"]["must_not_be_changed_to_improve_metrics"] is True
    assert evaluation["anchor_count"] == evaluation["passed_count"] == 6
    assert [
        (anchor["label"], anchor["source_px"], anchor["canonical_px"])
        for anchor in evaluation["anchors"]
    ] == [
        ("defender_spawn_far_top_right", [1008, 27], [82, 773]),
        ("B_boat_house_left_top", [116, 325], [452, 1873]),
        ("B_site_upper_left", [216, 303], [422, 1746]),
        ("A_site_rafters_far_right", [1503, 338], [467, 159]),
        ("A_wine_projection_right", [1556, 729], [951, 95]),
        ("attacker_spawn_bottom_chamfer", [680, 1564], [1980, 1182]),
    ]
    assert evaluation["maximum_residual_px"] == pytest.approx(7.7904138208395235)
    assert manifest["maximum_residual_px"] == evaluation["maximum_residual_px"]
    assert evaluation["threshold_frozen_before_scoring"] is True
    assert manifest["geometry_status"] == "pending"
    assert manifest["failure_reasons"]


def test_vta102_diagnostic_verifies_hashes_and_reports_unregistered_overlap() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    source_path = Path(manifest["source"]["local_path"])
    result = DIAGNOSE(source_path)

    assert result["source_sha256"] == hashlib.sha256(source_path.read_bytes()).hexdigest()
    assert result["canonical_sha256"] == manifest["canonical_asset"]["sha256"]
    assert result["status"] == "silhouette_registration_diagnostic"
    assert result["fit"]["occupancy_iou"] > 0.95
    assert result["fit"]["symmetric_contour_chamfer_px_at_1024"] < 2
    assert result["registration_established"] is False
    assert result["candidate_source_to_canonical_affine_matrix"][0][1] > 1
    evaluation = result["independent_heldout_anchor_evaluation"]
    assert evaluation["anchor_count"] == evaluation["passed_count"] == 6
    assert evaluation["maximum_residual_px"] == pytest.approx(7.7904138208395235)
    assert evaluation["metric"] == (
        "Euclidean source-to-canonical point residual in canonical pixels"
    )
    assert result["geometry_status"] == "pending"
    assert Path(result["overlay_path"]).is_file()


def test_vta102_fixed_anchor_evaluation_scores_known_and_perturbed_transform() -> None:
    evaluate = DIAGNOSTIC["_evaluate_anchors"]
    anchors = [
        {
            "label": "synthetic-known-point",
            "source_px": [2, 3],
            "canonical_px": [8, 1],
            "source_uncertainty_px": 2,
            "target_uncertainty_px": 1,
            "scale_for_uncertainty": 2.0,
        }
    ]

    known = evaluate(anchors, [[2, 0, 4], [0, 2, -5]])
    assert known["anchors"][0]["predicted_canonical_px"] == [8.0, 1.0]
    assert known["anchors"][0]["residual_euclidean_px"] == 0
    assert known["anchors"][0]["allowed_residual_px"] == 5
    assert known["anchors"][0]["pass"] is True

    perturbed = evaluate(anchors, [[2, 0, 10], [0, 2, -5]])
    assert perturbed["anchors"][0]["residual_euclidean_px"] == 6
    assert perturbed["anchors"][0]["pass"] is False


def test_vta102_diagnostic_fails_closed_when_external_source_is_missing(tmp_path: Path) -> None:
    with pytest.raises(DIAGNOSTIC_ERROR, match="required image is missing"):
        DIAGNOSE(tmp_path / "not-downloaded.png")


def test_vta102_diagnostic_fails_closed_when_external_source_hash_changes(tmp_path: Path) -> None:
    altered_source = tmp_path / "altered.png"
    altered_source.write_bytes(b"not the labeled source image")

    with pytest.raises(DIAGNOSTIC_ERROR, match="image SHA-256 mismatch"):
        DIAGNOSE(altered_source)
