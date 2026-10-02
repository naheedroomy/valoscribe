from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np
import pytest

from valoscribe.detectors.portrait_structure_diagnostic import (
    PortraitStructureAnalysis,
    _compact_enclosures,
    _digest_array,
    _gradient_evidence_digest,
    _spatial_descriptor,
    analyze_portrait_structure,
    compare_portrait_structure,
    policy_digest,
    write_portrait_structure_debug,
)
from valoscribe.types.persistent import (
    PortraitStructureDiagnostic,
    PortraitStructurePolicy,
    PortraitStructureROI,
    PortraitStructureStatus,
)

POLICY = PortraitStructurePolicy(
    canny_low=25,
    canny_high=75,
    minimum_area_px=60,
    minimum_gradient_pixels=4,
    minimum_support_fraction=0.2,
)
ROI = PortraitStructureROI(x=12, y=10, width=64, height=56)


def _image(*, pattern: str = "diagonal", origin: tuple[int, int] = (30, 26)) -> np.ndarray:
    image = np.full((80, 80, 3), 20, dtype=np.uint8)
    x, y = origin
    image[y : y + 30, x : x + 28] = 110
    image[y, x : x + 28] = 235
    image[y + 29, x : x + 28] = 235
    image[y : y + 30, x] = 235
    image[y : y + 30, x + 27] = 235
    if pattern == "diagonal":
        for offset in range(4, 24, 5):
            for step in range(8):
                px, py = x + offset + step, y + 6 + step
                if px < x + 26 and py < y + 26:
                    image[py : py + 2, px : px + 2] = 190
    elif pattern == "horizontal":
        image[y + 7 : y + 9, x + 4 : x + 24] = 190
        image[y + 16 : y + 18, x + 4 : x + 24] = 190
    return image


def _analyze(
    image: np.ndarray, roi: PortraitStructureROI = ROI, mask: np.ndarray | None = None
) -> PortraitStructureAnalysis:
    return analyze_portrait_structure(
        image, candidate_id="synthetic-candidate", roi=roi, policy=POLICY, exclusion_mask=mask
    )


def test_compact_closed_enclosure_localizes_in_native_coordinates_and_is_repeatable() -> None:
    image = _image()
    original = image.copy()
    first = _analyze(image)
    second = _analyze(image)

    assert first.result.status is PortraitStructureStatus.LOCALIZED
    assert first.result.proposed_boundary is not None
    assert abs(first.result.proposed_boundary.x - 30) <= 1
    assert abs(first.result.proposed_boundary.y - 26) <= 1
    assert first.result.coordinate_origin == "image_top_left"
    assert first.result.proposed_center_x == pytest.approx(43.5)
    assert first.result.proposed_center_y == pytest.approx(40.5)
    assert first.result.model_dump(mode="json") == second.result.model_dump(mode="json")
    np.testing.assert_array_equal(image, original)
    np.testing.assert_array_equal(first.descriptor, second.descriptor)


def test_native_boundary_stays_fixed_across_plus_minus_three_roi_perturbations() -> None:
    image = _image()
    for dx in range(-3, 4):
        for dy in range(-3, 4):
            candidate_roi = PortraitStructureROI(
                x=ROI.x + dx, y=ROI.y + dy, width=ROI.width, height=ROI.height
            )
            result = _analyze(image, candidate_roi).result
            assert result.status is PortraitStructureStatus.LOCALIZED
            assert result.proposed_boundary is not None
            assert abs(result.proposed_boundary.x - 30) <= 1
            assert abs(result.proposed_boundary.y - 26) <= 1


def test_attached_pointer_is_not_accepted_as_a_compact_enclosure() -> None:
    image = _image()
    # A thin attached triangular pointer makes the apparent outer contour non-compact.
    x, y = 57, 39
    for row in range(14):
        image[y + row, x : x + 14 - row] = 235
    result = _analyze(image).result
    assert result.status is PortraitStructureStatus.REJECTED
    assert result.feature_sha256 is None


def test_separate_neighboring_marker_yields_competing_enclosures() -> None:
    image = _image()
    x, y = 63, 30
    image[y : y + 12, x : x + 12] = 80
    image[y, x : x + 12] = 235
    image[y + 11, x : x + 12] = 235
    image[y : y + 12, x] = 235
    image[y : y + 12, x + 11] = 235
    result = _analyze(image).result
    assert result.status is PortraitStructureStatus.UNKNOWN
    assert "competing_enclosures" in result.rejection_reasons
    assert result.feature_sha256 is None


@pytest.mark.parametrize("side", ["left", "right", "top", "bottom"])
def test_enclosure_clipped_at_each_search_border_fails_closed(side: str) -> None:
    image = np.full((60, 60, 3), 20, dtype=np.uint8)
    roi = PortraitStructureROI(x=12, y=12, width=36, height=36)
    x, y = 22, 22
    if side == "left":
        x = roi.x
    elif side == "right":
        x = roi.x + roi.width - 28
    elif side == "top":
        y = roi.y
    else:
        y = roi.y + roi.height - 30
    image[y : y + 30, x : x + 28] = 110
    image[y, x : x + 28] = 235
    image[y + 29, x : x + 28] = 235
    image[y : y + 30, x] = 235
    image[y : y + 30, x + 27] = 235
    result = _analyze(image, roi).result
    assert result.status is PortraitStructureStatus.CLIPPED
    assert result.feature_sha256 is None
    assert result.proposed_boundary is None


def test_blank_interior_and_background_only_shape_have_no_usable_descriptor() -> None:
    blank = np.full((80, 80, 3), 20, dtype=np.uint8)
    assert _analyze(blank).result.status is PortraitStructureStatus.UNKNOWN
    background_shape = np.full((80, 80, 3), 20, dtype=np.uint8)
    background_shape[26:56, 30:58] = 110
    background_shape[26, 30:58] = 235
    background_shape[55, 30:58] = 235
    background_shape[26:56, 30] = 235
    background_shape[26:56, 57] = 235
    result = _analyze(background_shape).result
    assert result.status is PortraitStructureStatus.UNKNOWN
    assert result.feature_sha256 is None


def test_explicit_merged_overlap_returns_no_features() -> None:
    image = _image()
    conflict = np.zeros(image.shape[:2], dtype=np.uint8)
    conflict[31:50, 34:52] = 1
    result = _analyze(image, mask=conflict).result
    assert result.status is PortraitStructureStatus.OVERLAP
    assert result.feature_sha256 is None
    assert "explicit_exclusion_conflict_inside_enclosure" in result.rejection_reasons


def test_spatial_structure_distinguishes_equal_mean_interiors() -> None:
    diagonal = _analyze(_image(pattern="diagonal"))
    horizontal = _analyze(_image(pattern="horizontal"))
    assert diagonal.result.status is horizontal.result.status is PortraitStructureStatus.LOCALIZED
    assert diagonal.descriptor is not None and horizontal.descriptor is not None
    assert not np.allclose(diagonal.descriptor, horizontal.descriptor)
    assert np.mean(_image(pattern="diagonal")[26:56, 30:58]) == pytest.approx(
        np.mean(_image(pattern="horizontal")[26:56, 30:58]), abs=2.0
    )
    comparison = compare_portrait_structure(diagonal, horizontal)
    assert comparison.status == "available"
    assert comparison.distance is not None and comparison.distance > 0


def test_fixed_support_substitutions_do_not_change_retained_structure_or_comparison() -> None:
    image = _image()
    changed_outside = image.copy()
    changed_outside[:8, :8] = 255 - changed_outside[:8, :8]
    a, b = _analyze(image), _analyze(changed_outside)
    assert a.result.status is b.result.status is PortraitStructureStatus.LOCALIZED
    np.testing.assert_array_equal(a.support_mask, b.support_mask)
    np.testing.assert_allclose(
        a.gradient_magnitude[a.support_mask > 0], b.gradient_magnitude[b.support_mask > 0], atol=0
    )
    np.testing.assert_allclose(a.descriptor, b.descriptor, atol=1e-7)
    compared = compare_portrait_structure(a, b)
    assert compared.distance == pytest.approx(0.0, abs=1e-7)


def test_insufficient_common_support_and_policy_binding_fail_closed() -> None:
    low_common_policy = POLICY.model_copy(
        update={
            "grid_rows": 8,
            "grid_columns": 8,
            "minimum_gradient_pixels": 1,
            "minimum_common_support_fraction": 0.99,
        }
    )
    left = analyze_portrait_structure(
        _image(), candidate_id="left", roi=ROI, policy=low_common_policy
    )
    right_same_policy = analyze_portrait_structure(
        _image(), candidate_id="right", roi=ROI, policy=low_common_policy
    )
    assert (
        left.result.status is right_same_policy.result.status is PortraitStructureStatus.LOCALIZED
    )
    assert compare_portrait_structure(left, right_same_policy).status == "unknown"
    other_policy = POLICY.model_copy(update={"grid_rows": 3})
    right = analyze_portrait_structure(_image(), candidate_id="other", roi=ROI, policy=other_policy)
    assert compare_portrait_structure(left, right).status == "policy_mismatch"


def _with_local_support(
    analysis: PortraitStructureAnalysis, local_support: np.ndarray
) -> PortraitStructureAnalysis:
    boundary = analysis.result.proposed_boundary
    assert boundary is not None
    support = np.zeros_like(analysis.support_mask)
    support[
        boundary.y : boundary.y + boundary.height,
        boundary.x : boundary.x + boundary.width,
    ] = local_support
    descriptor, descriptor_support = _spatial_descriptor(
        analysis.gradient_magnitude,
        analysis.gradient_orientation,
        support,
        (boundary.x, boundary.y, boundary.width, boundary.height),
        analysis.policy,
    )
    assert descriptor is not None and descriptor_support is not None
    gradient_sha256 = _gradient_evidence_digest(
        analysis.gradient_magnitude,
        analysis.gradient_orientation,
        support,
        boundary,
        analysis.result.roi,
        analysis.policy,
        analysis.result.context_image_sha256,
    )
    updated_result = analysis.result.model_copy(
        update={
            "feature_sha256": _digest_array(descriptor),
            "support_sha256": _digest_array(support),
            "gradient_sha256": gradient_sha256,
        }
    )
    return replace(
        analysis,
        result=updated_result,
        support_mask=support,
        descriptor=descriptor,
        descriptor_support=descriptor_support,
    )


def test_failure_contract_forbids_success_fields_on_create_and_serialize() -> None:
    failure = _analyze(np.full((80, 80, 3), 20, dtype=np.uint8)).result
    success = _analyze(_image()).result
    success_values = {
        "proposed_boundary": success.proposed_boundary,
        "proposed_center_x": success.proposed_center_x,
        "proposed_center_y": success.proposed_center_y,
        "feature_sha256": success.feature_sha256,
        "support_sha256": success.support_sha256,
        "gradient_sha256": success.gradient_sha256,
        "supported_gradient_pixels": 1,
        "geometric_support_fraction": 0.5,
    }
    base = failure.model_dump(mode="python")
    for field, value in success_values.items():
        with pytest.raises(ValueError):
            PortraitStructureDiagnostic.model_validate({**base, field: value})
        corrupted = failure.model_copy(update={field: value})
        with pytest.raises(ValueError):
            corrupted.model_dump_json()


def test_localized_contract_requires_each_success_field_and_finite_consistent_geometry() -> None:
    success = _analyze(_image()).result
    base = success.model_dump(mode="python")
    required = (
        "proposed_boundary",
        "proposed_center_x",
        "proposed_center_y",
        "feature_sha256",
        "support_sha256",
        "gradient_sha256",
    )
    for field in required:
        invalid = {**base, field: None}
        with pytest.raises(ValueError):
            PortraitStructureDiagnostic.model_validate(invalid)
        corrupted = success.model_copy(update={field: None})
        with pytest.raises(ValueError):
            corrupted.model_dump_json()
    with pytest.raises(ValueError, match="finite"):
        success.model_copy(update={"proposed_center_x": float("nan")}).model_dump_json()
    with pytest.raises(ValueError, match="match the proposed boundary"):
        PortraitStructureDiagnostic.model_validate({**base, "proposed_center_x": 1.0})


def test_regenerated_nonshared_structure_does_not_change_common_comparison() -> None:
    image = _image(pattern="diagonal")
    base = _analyze(image)
    boundary = base.result.proposed_boundary
    assert boundary is not None
    exclusion = np.zeros(image.shape[:2], dtype=np.uint8)
    x0, x1 = boundary.x + 4, boundary.x + boundary.width - 4
    y0, y1 = boundary.y + boundary.height - 8, boundary.y + boundary.height - 3
    exclusion[y0:y1, x0:x1] = 1
    original = _analyze(image, mask=exclusion)

    changed_image = image.copy()
    changed_region = np.indices((2, x1 - x0 - 2)).sum(axis=0) % 2
    changed_image[y0 + 1 : y0 + 3, x0 + 1 : x1 - 1] = np.where(
        changed_region[:, :, None] > 0, 240, 40
    )
    regenerated = _analyze(changed_image, mask=exclusion)
    assert original.result.status is regenerated.result.status is PortraitStructureStatus.LOCALIZED
    assert original.result.gradient_sha256 != regenerated.result.gradient_sha256
    np.testing.assert_array_equal(original.support_mask, regenerated.support_mask)

    baseline = compare_portrait_structure(base, original)
    after_regeneration = compare_portrait_structure(base, regenerated)
    assert baseline.status == after_regeneration.status == "available"
    assert after_regeneration.shared_support_fraction == pytest.approx(
        baseline.shared_support_fraction
    )
    assert after_regeneration.distance == pytest.approx(baseline.distance, abs=1e-12)


@pytest.mark.parametrize("array_name", ["gradient_magnitude", "gradient_orientation"])
def test_mutated_supported_gradients_abstain_and_debug_writer_rejects(
    array_name: str, tmp_path: Path
) -> None:
    original = _analyze(_image())
    other = _analyze(_image())
    source = getattr(original, array_name)
    changed_array = source.copy()
    supported = original.support_mask > 0
    if array_name == "gradient_magnitude":
        changed_array[supported] *= 2
    else:
        changed_array[supported] = (changed_array[supported] + np.pi / 2) % np.pi
    tampered = replace(original, **{array_name: changed_array})

    comparison = compare_portrait_structure(tampered, other)
    assert comparison.status == "unknown"
    assert comparison.distance is None
    with pytest.raises(ValueError, match="gradient/support evidence is not bound"):
        write_portrait_structure_debug(tampered, tmp_path)


def test_disjoint_and_partial_pixel_support_are_not_reported_as_shared_cells() -> None:
    base = _analyze(_image())
    boundary = base.result.proposed_boundary
    assert boundary is not None
    height, width = boundary.height, boundary.width
    upper = np.zeros((height, width), dtype=np.uint8)
    lower = np.zeros_like(upper)
    upper[: height // 2] = 1
    lower[height // 2 :] = 1
    disjoint = compare_portrait_structure(
        _with_local_support(base, upper), _with_local_support(base, lower)
    )
    assert disjoint.status == "unknown"
    assert disjoint.shared_support_fraction == 0.0

    partial_a = np.zeros_like(upper)
    partial_b = np.zeros_like(upper)
    partial_a[: (height * 3) // 4] = 1
    partial_b[height // 4 :] = 1
    partial = compare_portrait_structure(
        _with_local_support(base, partial_a), _with_local_support(base, partial_b)
    )
    expected_common_pixels = int(np.count_nonzero(partial_a & partial_b))
    assert partial.shared_support_fraction == pytest.approx(
        expected_common_pixels / (height * width)
    )
    assert partial.shared_support_fraction == pytest.approx(0.5)
    assert partial.shared_support_fraction < 1.0


def test_nested_proposals_deduplicate_only_same_boundary_representations() -> None:
    def rectangle(x: int, y: int, width: int, height: int) -> np.ndarray:
        return np.array(
            [
                [[x, y]],
                [[x + width - 1, y]],
                [[x + width - 1, y + height - 1]],
                [[x, y + height - 1]],
            ],
            dtype=np.int32,
        )

    near_duplicates, rejected = _compact_enclosures(
        [rectangle(8, 8, 40, 40), rectangle(9, 9, 39, 39)], ROI, POLICY
    )
    assert not rejected
    assert len(near_duplicates) == 1

    nested_distinct, rejected = _compact_enclosures(
        [rectangle(8, 8, 40, 40), rectangle(20, 20, 16, 16)], ROI, POLICY
    )
    assert not rejected
    assert len(nested_distinct) == 2


def test_per_cell_minimum_counts_nonzero_supported_gradients_not_mask_pixels() -> None:
    magnitude = np.zeros((8, 8), dtype=np.float32)
    orientation = np.zeros((8, 8), dtype=np.float32)
    support = np.ones((8, 8), dtype=np.uint8)
    magnitude[1, 1] = 1.0
    magnitude[5, 5] = 1.0
    sparse_policy = POLICY.model_copy(
        update={"grid_rows": 2, "grid_columns": 2, "minimum_gradient_pixels": 2}
    )
    descriptor, cells = _spatial_descriptor(
        magnitude, orientation, support, (0, 0, 8, 8), sparse_policy
    )
    assert descriptor is None and cells is None


def test_nonfinite_invalid_input_and_contract_serialization() -> None:
    image = _image()
    with pytest.raises(ValueError, match="uint8 BGR"):
        _analyze(image.astype(np.float32))
    mask = np.zeros(image.shape[:2], dtype=np.float32)
    mask[0, 0] = np.nan
    with pytest.raises(ValueError, match="finite"):
        _analyze(image, mask=mask)
    with pytest.raises(ValueError):
        PortraitStructurePolicy(canny_low=100, canny_high=50)
    output = _analyze(image).result
    assert type(output).model_validate_json(output.model_dump_json()) == output
    with pytest.raises(ValueError, match="failure diagnostics forbid success fields"):
        output.model_copy(update={"status": PortraitStructureStatus.UNKNOWN}).model_dump_json()


@pytest.mark.parametrize("invalid_state", ["nan_center", "failure_boundary"])
def test_preflight_rejects_invalid_results_before_comparison_or_debug_output(
    invalid_state: str, tmp_path: Path
) -> None:
    localized = _analyze(_image())
    if invalid_state == "nan_center":
        invalid_result = localized.result.model_copy(update={"proposed_center_x": float("nan")})
        invalid_analysis = replace(localized, result=invalid_result)
    else:
        failure = _analyze(np.full((80, 80, 3), 20, dtype=np.uint8))
        invalid_result = failure.result.model_copy(
            update={"proposed_boundary": localized.result.proposed_boundary}
        )
        invalid_analysis = replace(failure, result=invalid_result)

    comparison = compare_portrait_structure(invalid_analysis, localized)
    assert comparison.status == "unknown"
    assert comparison.distance is None
    debug_path = tmp_path / invalid_state
    with pytest.raises(ValueError, match="gradient/support evidence is not bound"):
        write_portrait_structure_debug(invalid_analysis, debug_path)
    assert not debug_path.exists()


def test_supported_derivative_stencil_cannot_intersect_exclusion_before_output(
    tmp_path: Path,
) -> None:
    analysis = _analyze(_image())
    y, x = next(
        (int(row), int(column))
        for row, column in np.argwhere(analysis.support_mask > 0)
        if column + 1 < analysis.support_mask.shape[1]
        and analysis.support_mask[row, column + 1] > 0
    )
    exclusion = analysis.exclusion_mask.copy()
    exclusion[y, x + 1] = 1
    assert analysis.support_mask[y, x] == 1
    assert exclusion[y, x] == 0
    inconsistent = replace(
        analysis,
        exclusion_mask=exclusion,
        exclusion_mask_provided=True,
    )

    comparison = compare_portrait_structure(inconsistent, analysis)
    assert comparison.status == "unknown"
    assert comparison.distance is None
    debug_path = tmp_path / "exclusion-stencil-conflict"
    with pytest.raises(ValueError, match="gradient/support evidence is not bound"):
        write_portrait_structure_debug(inconsistent, debug_path)
    assert not debug_path.exists()


def test_debug_artifacts_match_result_decision(tmp_path: Path) -> None:
    exclusion = np.zeros((80, 80), dtype=np.uint8)
    exclusion[2:4, 2:4] = 1
    analysis = _analyze(_image(), mask=exclusion)
    write_portrait_structure_debug(analysis, tmp_path)
    manifest = json.loads((tmp_path / "diagnostic.json").read_text(encoding="utf-8"))
    assert manifest["result"] == analysis.result.model_dump(mode="json")
    assert manifest["proposals"] == [item.model_dump(mode="json") for item in analysis.proposals]
    assert set(manifest["artifact_files"]) == {
        "proposal-overlay.png",
        "edge-map.png",
        "support-mask.png",
        "exclusion-mask.png",
        "gradient-magnitude.png",
        "gradient-orientation.png",
        "descriptor.npz",
    }
    assert manifest["canonical_policy_body"] == analysis.policy.model_dump(mode="json")
    assert manifest["policy_sha256"] == policy_digest(analysis.policy)
    assert manifest["exclusion_mask_provided"] is True
    assert all((tmp_path / name).is_file() for name in manifest["artifact_files"])
    assert set(manifest["artifact_sha256"]) == set(manifest["artifact_files"])
    for filename, digest in manifest["artifact_sha256"].items():
        import hashlib

        assert hashlib.sha256((tmp_path / filename).read_bytes()).hexdigest() == digest
    np.testing.assert_array_equal(
        cv2.imread(str(tmp_path / "support-mask.png"), cv2.IMREAD_UNCHANGED),
        analysis.support_mask * 255,
    )
    np.testing.assert_array_equal(
        cv2.imread(str(tmp_path / "exclusion-mask.png"), cv2.IMREAD_UNCHANGED),
        analysis.exclusion_mask * 255,
    )
    with np.load(tmp_path / "descriptor.npz", allow_pickle=False) as archive:
        np.testing.assert_array_equal(archive["descriptor"], analysis.descriptor)
        np.testing.assert_array_equal(archive["descriptor_support"], analysis.descriptor_support)
    assert _digest_array(analysis.support_mask) == analysis.result.support_sha256
    assert _digest_array(analysis.descriptor) == analysis.result.feature_sha256


def test_debug_writer_reports_failed_png_writes_clearly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    analysis = _analyze(_image())
    monkeypatch.setattr(cv2, "imwrite", lambda *_args, **_kwargs: False)
    with pytest.raises(OSError, match="unable to write diagnostic artifact"):
        write_portrait_structure_debug(analysis, tmp_path)
