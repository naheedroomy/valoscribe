"""VTA-102 source annotations are provisional and metadata-only."""

import json
from pathlib import Path
from runpy import run_path

import cv2
import pytest

ROOT = Path(__file__).parents[2]
FIXTURE_PATH = ROOT / "tests/fixtures/map_annotations/ascent-vta102-source-interior-v1.json"
VALIDATOR = run_path(str(ROOT / "scripts/maintenance/validate_vta102_source_annotations.py"))
VALIDATE = VALIDATOR["validate"]
VALIDATION_ERROR = VALIDATOR["AnnotationValidationError"]


def test_vta102_annotations_bind_to_frozen_source_and_canonical_mapping() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    manifest_path = ROOT / fixture["canonical_mapping"]["mapping_manifest_path"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert fixture["schema_version"] == "1.0"
    assert fixture["issue"] == "VTA-102"
    assert fixture["annotation_status"] == "provisional_source_interior_samples"
    assert fixture["geometry_status"] == "pending"
    assert fixture["source"]["sha256"] == manifest["source"]["sha256"]
    assert fixture["canonical_mapping"]["sha256"] == manifest["canonical_asset"]["sha256"]
    assert (
        fixture["canonical_mapping"]["mapping_manifest_source_sha256"]
        == manifest["source"]["sha256"]
    )
    assert (
        fixture["canonical_mapping"]["mapping_manifest_canonical_sha256"]
        == manifest["canonical_asset"]["sha256"]
    )
    assert fixture["derived_geometry"] == {
        "walkable_areas": [],
        "site_polygons": [],
        "spawn_polygons": [],
        "named_zones": [],
        "zone_at_promotion": False,
    }
    assert fixture["acceptance"]["full_vta102_acceptance"] == "pending"


def test_vta102_six_accepted_centers_are_inside_alpha_and_a_main_is_rejected() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    canonical_path = ROOT / fixture["canonical_mapping"]["asset_path"]
    image = cv2.imread(str(canonical_path), cv2.IMREAD_UNCHANGED)
    assert image is not None
    alpha = image[:, :, 3]

    expected = {
        "A Site": ([642, 269, 678, 301], [660, 285]),
        "B Site": ([602, 1652, 638, 1688], [620, 1670]),
        "Defender Spawn": ([307, 812, 343, 848], [325, 830]),
        "Attacker Spawn": ([1570, 1080, 1610, 1120], [1590, 1100]),
        "Mid Courtyard": ([1092, 1054, 1124, 1086], [1108, 1070]),
        "B Main": ([805, 1330, 839, 1364], [822, 1347]),
    }
    assert {
        item["label"]: (item["rectangle_px"], item["center_px"])
        for item in fixture["source_annotations"]
    } == expected
    for item in fixture["source_annotations"]:
        x, y = item["center_px"]
        assert alpha[y, x] > 0

    rejected = fixture["rejected_annotations"]
    assert [(item["label"], item["rectangle_px"], item["center_px"]) for item in rejected] == [
        ("A Main", [916, 394, 952, 426], [934, 410])
    ]
    assert alpha[410, 934] == 0


def test_vta102_opt_in_validation_fails_closed_if_local_community_source_is_missing(
    tmp_path: Path,
) -> None:
    with pytest.raises(VALIDATION_ERROR, match="required image is missing"):
        VALIDATE(tmp_path / "source-not-downloaded.png")
