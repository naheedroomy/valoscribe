"""Synthetic registration geometry and failure-path coverage."""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from valoscribe.maps.config import FeatureRegistrationConfig, MapRegistrationThresholds
from valoscribe.maps.registration import MinimapRegistrar


def textured_map() -> np.ndarray:
    image = np.zeros((96, 128), dtype=np.uint8)
    for y in range(image.shape[0]):
        image[y, :] = 35 + y
    cv2.rectangle(image, (15, 12), (58, 49), 230, 2)
    cv2.rectangle(image, (21, 18), (49, 42), 90, -1)
    cv2.circle(image, (91, 66), 13, 15, -1)
    cv2.line(image, (72, 8), (113, 84), 255, 3)
    cv2.putText(image, "MAP", (6, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.5, 5, 1)
    return image


def test_fixed_transform_reports_scale_and_diagnostic_artifacts(tmp_path: Path) -> None:
    canonical = textured_map()
    crop = cv2.resize(canonical, (64, 48), interpolation=cv2.INTER_AREA)
    result = MinimapRegistrar().register(crop, canonical, refine_affine=False)

    assert result.method == "fixed"
    assert result.failure_reason is None
    assert result.transform_matrix == ((2.0, 0.0, 0.0), (0.0, 2.0, 0.0))
    assert result.confidence is not None and result.confidence > 0.5
    assert result.alignment_error is not None and result.alignment_error < 0.25
    assert result.aligned_minimap is not None

    assert cv2.imwrite(str(tmp_path / "aligned_minimap.png"), result.aligned_minimap)
    diagnostics = {
        "method": result.method,
        "transform_matrix": result.transform_matrix,
        "confidence": result.confidence,
        "alignment_error": result.alignment_error,
        "failure_reason": result.failure_reason,
    }
    (tmp_path / "registration_diagnostics.json").write_text(
        json.dumps(diagnostics, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    assert (tmp_path / "registration_diagnostics.json").is_file()


def test_affine_refinement_corrects_synthetic_translation() -> None:
    canonical = textured_map()
    source_to_target = np.array([[1.0, 0.0, 4.0], [0.0, 1.0, -3.0]], dtype=np.float32)
    moved = cv2.warpAffine(
        canonical,
        source_to_target,
        (canonical.shape[1], canonical.shape[0]),
        borderMode=cv2.BORDER_REFLECT,
    )

    result = MinimapRegistrar().register(moved, canonical)

    assert result.method == "affine"
    assert result.failure_reason is None
    assert result.aligned_minimap is not None
    assert result.alignment_error is not None and result.alignment_error < 0.08
    assert result.transform_matrix is not None
    assert result.transform_matrix[0][2] == pytest.approx(-4.0, abs=0.75)
    assert result.transform_matrix[1][2] == pytest.approx(3.0, abs=0.75)


def test_obstruction_mask_excludes_masked_overlay_pixels() -> None:
    canonical = textured_map()
    obstructed = canonical.copy()
    obstructed[20:46, 40:78] = 255 - obstructed[20:46, 40:78]
    mask = np.zeros(canonical.shape, dtype=np.uint8)
    mask[18:48, 38:80] = 255

    result = MinimapRegistrar().register(obstructed, canonical, obstruction_mask=mask)

    assert result.method in {"fixed", "affine"}
    if result.method == "fixed":
        assert result.failure_reason is not None
        assert result.failure_reason in {
            "affine_refinement_worse_than_fixed_fallback",
            "affine_refinement_failed",
        } or result.failure_reason.startswith("affine_refinement_failed:")
    else:
        assert result.failure_reason is None
    assert result.alignment_error is not None and result.alignment_error < 0.01


def _feature_registration_config() -> FeatureRegistrationConfig:
    return FeatureRegistrationConfig(
        source_gray_range=(65, 165),
        canonical_gray_range=(65, 160),
        maximum_source_channel_spread=10,
        minimum_feature_coverage=0.05,
        maximum_feature_coverage=0.60,
        minimum_confidence=0.70,
        maximum_alignment_error=0.15,
    )


def test_feature_registration_rejects_disabled_affine_refinement() -> None:
    result = MinimapRegistrar(feature_config=_feature_registration_config()).register(
        textured_map(), textured_map(), refine_affine=False
    )

    assert result.method == "rejected"
    assert result.aligned_minimap is None
    assert result.failure_reason == "feature_registration_requires_affine_refinement"


def test_feature_registration_rejects_obstruction_mask() -> None:
    image = textured_map()
    mask = np.zeros(image.shape, dtype=np.uint8)
    result = MinimapRegistrar(feature_config=_feature_registration_config()).register(
        image, image, obstruction_mask=mask
    )

    assert result.method == "rejected"
    assert result.aligned_minimap is None
    assert result.failure_reason == "feature_registration_does_not_accept_obstruction_mask"


def test_feature_registration_ignores_different_scene_backgrounds() -> None:
    config = FeatureRegistrationConfig(
        source_gray_range=(65, 165),
        canonical_gray_range=(65, 160),
        maximum_source_channel_spread=10,
        minimum_feature_coverage=0.05,
        maximum_feature_coverage=0.60,
        minimum_confidence=0.70,
        maximum_alignment_error=0.15,
    )
    canonical = np.full((128, 128, 3), 24, dtype=np.uint8)
    cv2.rectangle(canonical, (20, 20), (105, 100), (100, 100, 100), 5)
    cv2.circle(canonical, (65, 62), 18, (145, 145, 145), -1)
    cv2.line(canonical, (32, 90), (92, 30), (75, 75, 75), 4)
    crop = np.indices((128, 128)).sum(axis=0) % 2
    crop = np.where(crop[..., None] == 0, (210, 30, 30), (28, 28, 28)).astype(np.uint8)
    cv2.rectangle(crop, (20, 20), (105, 100), (100, 100, 100), 5)
    cv2.circle(crop, (65, 62), 18, (145, 145, 145), -1)
    cv2.line(crop, (32, 90), (92, 30), (75, 75, 75), 4)

    raw = MinimapRegistrar(
        MapRegistrationThresholds(minimum_confidence=0.99, maximum_alignment_error=0.01)
    ).register(crop, canonical)
    feature = MinimapRegistrar(feature_config=config).register(crop, canonical)

    assert raw.method == "rejected"
    assert feature.method == "feature_affine"
    assert feature.failure_reason is None
    assert feature.confidence is not None and feature.confidence >= config.minimum_confidence
    assert feature.alignment_error is not None
    assert feature.alignment_error <= config.maximum_alignment_error
    assert feature.aligned_minimap is not None


def test_feature_rejection_falls_back_only_to_independently_accepted_raw_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from valoscribe.maps.registration import RegistrationResult

    feature_config = _feature_registration_config()
    thresholds = MapRegistrationThresholds(
        minimum_confidence=0.30, maximum_alignment_error=0.25
    )
    canonical = textured_map()

    def reject_features(_self, _crop, _canonical):
        return RegistrationResult(
            aligned_minimap=None,
            transform_matrix=None,
            confidence=0.622,
            alignment_error=0.168,
            method="rejected",
            failure_reason="feature_confidence_below_configured_threshold",
        )

    monkeypatch.setattr(MinimapRegistrar, "_register_features", reject_features)
    registrar = MinimapRegistrar(thresholds, feature_config)

    unconfigured = MinimapRegistrar(feature_config=feature_config).register(
        canonical, canonical
    )
    assert unconfigured.method == "rejected"
    assert unconfigured.aligned_minimap is None
    assert unconfigured.raw_failure_reason == "raw_registration_thresholds_unconfigured"
    assert unconfigured.raw_confidence is None

    accepted = registrar.register(canonical.copy(), canonical)
    assert accepted.method == "affine"
    assert accepted.aligned_minimap is not None
    assert accepted.feature_confidence == 0.622
    assert accepted.feature_alignment_error == 0.168
    assert accepted.feature_failure_reason == "feature_confidence_below_configured_threshold"
    assert accepted.raw_confidence is not None and accepted.raw_confidence >= 0.30
    assert accepted.raw_alignment_error is not None and accepted.raw_alignment_error <= 0.25
    assert accepted.raw_failure_reason is None

    mismatch = np.random.default_rng(55).integers(
        0, 256, size=canonical.shape, dtype=np.uint8
    )
    rejected = registrar.register(mismatch, canonical)
    assert rejected.method == "rejected"
    assert rejected.aligned_minimap is None
    assert rejected.feature_failure_reason == "feature_confidence_below_configured_threshold"
    assert rejected.raw_failure_reason is not None
    assert any(
        reason in rejected.raw_failure_reason
        for reason in (
            "confidence_below_configured_threshold",
            "alignment_error_above_configured_threshold",
        )
    )
    assert rejected.raw_confidence is not None and rejected.raw_confidence < 0.30
    assert "feature_registration_rejected:" in (rejected.failure_reason or "")
    assert "raw_registration_rejected:" in (rejected.failure_reason or "")

    blank = np.zeros_like(canonical)
    weak = registrar.register(blank, blank)
    assert weak.method == "rejected"
    assert weak.raw_failure_reason == "low_texture"
    assert "feature_registration_rejected:" in (weak.failure_reason or "")
    assert "raw_registration_rejected:low_texture" in (weak.failure_reason or "")


def test_feature_registration_rejects_mismatched_layout_and_weak_features() -> None:
    config = FeatureRegistrationConfig(
        source_gray_range=(65, 165),
        canonical_gray_range=(65, 160),
        maximum_source_channel_spread=10,
        minimum_feature_coverage=0.05,
        maximum_feature_coverage=0.60,
        minimum_confidence=0.70,
        maximum_alignment_error=0.15,
    )
    source = np.full((128, 128, 3), 20, dtype=np.uint8)
    canonical = np.full_like(source, 20)
    cv2.rectangle(source, (12, 12), (112, 112), (100, 100, 100), -1)
    cv2.circle(source, (30, 30), 10, (150, 150, 150), -1)
    cv2.circle(canonical, (40, 90), 9, (100, 100, 100), -1)
    cv2.line(canonical, (80, 20), (110, 110), (150, 150, 150), 5)

    mismatched = MinimapRegistrar(feature_config=config).register(source, canonical)
    weak_config = FeatureRegistrationConfig(
        source_gray_range=(200, 220),
        canonical_gray_range=(200, 220),
        maximum_source_channel_spread=10,
        minimum_feature_coverage=0.05,
        maximum_feature_coverage=0.60,
        minimum_confidence=0.70,
        maximum_alignment_error=0.15,
    )
    weak = MinimapRegistrar(feature_config=weak_config).register(source, canonical)

    assert mismatched.method == "rejected"
    assert mismatched.failure_reason is not None
    assert mismatched.aligned_minimap is None
    assert weak.method == "rejected"
    assert weak.failure_reason == "feature_domain_coverage_outside_configured_range"


def test_low_texture_and_incompatible_mask_are_rejected_without_exception() -> None:
    blank = np.zeros((32, 32), dtype=np.uint8)
    low_texture = MinimapRegistrar().register(blank, blank)
    invalid_mask = MinimapRegistrar().register(
        textured_map(), textured_map(), obstruction_mask=np.ones((3, 3), dtype=np.uint8)
    )

    assert low_texture.method == "rejected"
    assert low_texture.failure_reason == "low_texture"
    assert invalid_mask.method == "rejected"
    assert invalid_mask.failure_reason == "obstruction_mask_dimensions_must_match_canonical_image"


def test_configured_threshold_rejects_mismatched_background() -> None:
    rng = np.random.default_rng(16)
    crop = rng.integers(0, 256, size=(96, 128), dtype=np.uint8)
    canonical = rng.integers(0, 256, size=(96, 128), dtype=np.uint8)
    registrar = MinimapRegistrar(
        MapRegistrationThresholds(minimum_confidence=0.8, maximum_alignment_error=0.1)
    )

    result = registrar.register(crop, canonical)

    assert result.method == "rejected"
    assert result.failure_reason in {
        "confidence_below_configured_threshold",
        "alignment_error_above_configured_threshold",
    }
    assert result.transform_matrix is not None


def test_pathological_ecc_warp_uses_only_plausible_fixed_fallback(monkeypatch) -> None:
    canonical = textured_map()
    identity_warp = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32)
    monkeypatch.setattr(
        cv2,
        "findTransformECC",
        lambda *_args, **_kwargs: (0.95, identity_warp * 1e-4),
    )

    result = MinimapRegistrar().register(canonical, canonical)

    assert result.method == "fixed"
    assert result.failure_reason == "affine_transform_failed_plausibility"
    assert result.aligned_minimap is not None


def test_reflected_affine_transform_is_rejected() -> None:
    from valoscribe.maps.registration import _transform_is_plausible

    reflection = np.array([[-1.0, 0.0, 127.0], [0.0, 1.0, 0.0]])

    assert not _transform_is_plausible(reflection, (96, 128), (96, 128))


def test_worse_plausible_ecc_result_uses_fixed_fallback_with_diagnostic(monkeypatch) -> None:
    canonical = textured_map()
    monkeypatch.setattr(
        cv2,
        "findTransformECC",
        lambda *_args, **_kwargs: (0.5, np.eye(2, 3, dtype=np.float32)),
    )

    result = MinimapRegistrar().register(canonical, canonical)

    assert result.method == "fixed"
    assert result.failure_reason == "affine_refinement_worse_than_fixed_fallback"
    assert result.aligned_minimap is not None
    assert result.alignment_error == 0


def test_non_finite_or_malformed_ecc_output_is_diagnostic(monkeypatch) -> None:
    canonical = textured_map()
    monkeypatch.setattr(
        cv2,
        "findTransformECC",
        lambda *_args, **_kwargs: (float("nan"), np.eye(2, 3, dtype=np.float32)),
    )

    result = MinimapRegistrar().register(canonical, canonical)

    assert result.method == "fixed"
    assert result.failure_reason == "affine_transform_non_finite"
    assert result.aligned_minimap is not None


def test_ecc_shape_exception_becomes_explicit_fallback_diagnostic(monkeypatch) -> None:
    canonical = textured_map()

    def raise_shape_error(*_args, **_kwargs):
        raise cv2.error("synthetic shape error")

    monkeypatch.setattr(cv2, "findTransformECC", raise_shape_error)
    result = MinimapRegistrar().register(canonical, canonical)

    assert result.method == "fixed"
    assert result.failure_reason == "affine_refinement_failed:error"
    assert result.aligned_minimap is not None


def test_mask_with_unsupported_pixel_type_returns_structured_failure() -> None:
    image = textured_map()
    result = MinimapRegistrar().register(
        image, image, obstruction_mask=np.zeros(image.shape, dtype=np.float32)
    )

    assert result.method == "rejected"
    assert result.failure_reason == "obstruction_mask_must_have_uint8_pixels"


def test_invalid_frame_dimensions_return_structured_failure() -> None:
    result = MinimapRegistrar().register(
        np.zeros((2, 2), dtype=np.uint8), np.zeros((10, 10), dtype=np.uint8)
    )

    assert result.method == "rejected"
    assert result.aligned_minimap is None
    assert result.transform_matrix is None
    assert result.confidence is None
    assert result.alignment_error is None
    assert result.failure_reason == "minimap_crop_dimensions_too_small"
