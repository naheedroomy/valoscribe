"""Deterministic minimap registration with fixed-scale and optional affine refinement."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal, cast

import cv2
import numpy as np
from numpy.typing import NDArray

from valoscribe.maps.config import FeatureRegistrationConfig, MapRegistrationThresholds

Image = NDArray[np.uint8]
Transform = tuple[tuple[float, float, float], tuple[float, float, float]]
RegistrationMethod = Literal["fixed", "affine", "feature_affine", "rejected"]


@dataclass(frozen=True)
class RegistrationResult:
    """Aligned crop and measured diagnostics; ``None`` image means rejected input."""

    aligned_minimap: Image | None
    transform_matrix: Transform | None
    confidence: float | None
    alignment_error: float | None
    method: RegistrationMethod
    failure_reason: str | None
    feature_confidence: float | None = None
    feature_alignment_error: float | None = None
    feature_failure_reason: str | None = None
    raw_confidence: float | None = None
    raw_alignment_error: float | None = None
    raw_failure_reason: str | None = None


class MinimapRegistrar:
    """Resize a crop to canonical dimensions and optionally ECC-refine an affine warp.

    Alignment thresholds are supplied by map configuration. If no measured threshold
    is available, the fixed transform is returned as provisional rather than asserting
    that its alignment is accepted.
    """

    def __init__(
        self,
        thresholds: MapRegistrationThresholds | None = None,
        feature_config: FeatureRegistrationConfig | None = None,
    ) -> None:
        self.thresholds = thresholds
        self.feature_config = feature_config

    def register(
        self,
        minimap_crop: np.ndarray,
        canonical_minimap: np.ndarray,
        *,
        obstruction_mask: np.ndarray | None = None,
        refine_affine: bool = True,
    ) -> RegistrationResult:
        """Register one crop; failures are diagnostics, never propagated exceptions."""
        invalid = _validate_images(minimap_crop, canonical_minimap, obstruction_mask)
        if invalid is not None:
            return _rejected(invalid)
        if self.feature_config is not None:
            if obstruction_mask is not None:
                return _rejected("feature_registration_does_not_accept_obstruction_mask")
            if not refine_affine:
                return _rejected("feature_registration_requires_affine_refinement")
            feature_result = self._register_features(minimap_crop, canonical_minimap)
            if feature_result.aligned_minimap is not None:
                return replace(
                    feature_result,
                    feature_confidence=feature_result.confidence,
                    feature_alignment_error=feature_result.alignment_error,
                )
            if not _feature_failure_allows_raw_fallback(feature_result.failure_reason):
                return replace(
                    feature_result,
                    feature_confidence=feature_result.confidence,
                    feature_alignment_error=feature_result.alignment_error,
                    feature_failure_reason=feature_result.failure_reason,
                )
            if self.thresholds is None:
                return replace(
                    feature_result,
                    feature_confidence=feature_result.confidence,
                    feature_alignment_error=feature_result.alignment_error,
                    feature_failure_reason=feature_result.failure_reason,
                    raw_failure_reason="raw_registration_thresholds_unconfigured",
                )

            raw_result = MinimapRegistrar(thresholds=self.thresholds).register(
                minimap_crop, canonical_minimap, refine_affine=True
            )
            feature_reason = feature_result.failure_reason or "feature_registration_rejected"
            raw_reason = raw_result.failure_reason
            if raw_result.aligned_minimap is not None:
                return replace(
                    raw_result,
                    feature_confidence=feature_result.confidence,
                    feature_alignment_error=feature_result.alignment_error,
                    feature_failure_reason=feature_reason,
                    raw_confidence=raw_result.confidence,
                    raw_alignment_error=raw_result.alignment_error,
                    raw_failure_reason=raw_reason,
                )
            return replace(
                raw_result,
                failure_reason=f"feature_registration_rejected:{feature_reason};"
                f"raw_registration_rejected:{raw_reason or 'unknown'}",
                feature_confidence=feature_result.confidence,
                feature_alignment_error=feature_result.alignment_error,
                feature_failure_reason=feature_reason,
                raw_confidence=raw_result.confidence,
                raw_alignment_error=raw_result.alignment_error,
                raw_failure_reason=raw_reason,
            )

        source_gray = _gray(minimap_crop)
        template_gray = _gray(canonical_minimap)
        height, width = template_gray.shape
        resized = cv2.resize(source_gray, (width, height), interpolation=cv2.INTER_LINEAR)
        color = cv2.resize(minimap_crop, (width, height), interpolation=cv2.INTER_LINEAR)
        mask = _resize_mask(obstruction_mask, (width, height))
        if _texture(resized, mask) < 1e-6 or _texture(template_gray, mask) < 1e-6:
            return _rejected("low_texture")

        fixed_score = _correlation(template_gray, resized, mask)
        fixed_error = _alignment_error(template_gray, resized, mask)
        scale_x = width / minimap_crop.shape[1]
        scale_y = height / minimap_crop.shape[0]
        fixed_matrix = np.array(
            [[scale_x, 0.0, 0.0], [0.0, scale_y, 0.0]], dtype=np.float32
        )
        if not _transform_is_plausible(fixed_matrix, minimap_crop.shape[:2], (height, width)):
            return _rejected("fixed_transform_failed_plausibility")
        fallback = self._result(
            color,
            fixed_matrix,
            fixed_score,
            fixed_error,
            "fixed",
            "affine_refinement_failed" if refine_affine else None,
        )

        if not refine_affine:
            return self._apply_thresholds(fallback)

        warp = np.eye(2, 3, dtype=np.float32)
        try:
            ecc_result = cv2.findTransformECC(
                template_gray,
                resized,
                warp,
                cv2.MOTION_AFFINE,
                (
                    cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT,
                    100,
                    1e-6,
                ),
                mask if mask is not None else np.empty((0, 0), dtype=np.uint8),
                5,
            )
            correlation = float(ecc_result[0])
            warp = np.asarray(ecc_result[1], dtype=np.float32)
            if not np.isfinite(correlation) or not np.isfinite(warp).all():
                return self._affine_failure(fallback, "affine_transform_non_finite")
            if warp.shape != (2, 3):
                return self._affine_failure(fallback, "affine_transform_invalid_shape")
            inverse_warp = cv2.invertAffineTransform(warp)
            fixed_homogeneous = np.vstack((fixed_matrix, [0.0, 0.0, 1.0]))
            warp_homogeneous = np.vstack((inverse_warp, [0.0, 0.0, 1.0]))
            matrix = (warp_homogeneous @ fixed_homogeneous)[:2]
            if not _transform_is_plausible(matrix, minimap_crop.shape[:2], (height, width)):
                return self._affine_failure(fallback, "affine_transform_failed_plausibility")
            aligned = cv2.warpAffine(
                color,
                warp,
                (width, height),
                flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                borderMode=cv2.BORDER_CONSTANT,
            )
            aligned_gray = _gray(aligned)
            error = _alignment_error(template_gray, aligned_gray, mask)
            result = self._result(aligned, matrix, correlation, error, "affine", None)
            if (
                result.alignment_error is not None
                and fallback.alignment_error is not None
                and result.alignment_error > fallback.alignment_error
            ) or (
                result.confidence is not None
                and fallback.confidence is not None
                and result.confidence < fallback.confidence
            ):
                return self._affine_failure(
                    fallback, "affine_refinement_worse_than_fixed_fallback"
                )
            return self._apply_thresholds(result)
        except Exception as exc:
            return self._affine_failure(
                fallback, f"affine_refinement_failed:{exc.__class__.__name__}"
            )

    def _register_features(
        self, crop: np.ndarray, canonical: np.ndarray
    ) -> RegistrationResult:
        """Align map-specific stable grayscale features, rejecting weak matches."""
        config = self.feature_config
        if config is None:
            return _rejected("feature_registration_not_configured")
        source_gray = _gray(crop)
        canonical_gray = _gray(canonical)
        source_feature = _feature_image(crop, source_gray, config, source=True)
        canonical_feature = _feature_image(
            canonical, canonical_gray, config, source=False
        )
        height, width = canonical_gray.shape
        resized_feature = cv2.resize(
            source_feature, (width, height), interpolation=cv2.INTER_NEAREST
        )
        if not _feature_coverage_is_valid(
            resized_feature, config.minimum_feature_coverage, config.maximum_feature_coverage
        ) or not _feature_coverage_is_valid(
            canonical_feature, config.minimum_feature_coverage, config.maximum_feature_coverage
        ):
            return _rejected("feature_domain_coverage_outside_configured_range")

        scale = np.array(
            [[width / crop.shape[1], 0.0, 0.0], [0.0, height / crop.shape[0], 0.0]],
            dtype=np.float32,
        )
        warp = np.eye(2, 3, dtype=np.float32)
        try:
            correlation, feature_warp = cv2.findTransformECC(
                canonical_feature,
                resized_feature,
                warp,
                cv2.MOTION_AFFINE,
                (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 100, 1e-6),
                np.empty((0, 0), dtype=np.uint8),
                5,
            )
            warp = np.asarray(feature_warp, dtype=np.float32)
            if not np.isfinite(correlation) or not np.isfinite(warp).all():
                return _rejected("feature_transform_non_finite")
            inverse_warp = cv2.invertAffineTransform(warp)
            matrix = (
                np.vstack((inverse_warp, [0.0, 0.0, 1.0]))
                @ np.vstack((scale, [0.0, 0.0, 1.0]))
            )[:2]
            if not _transform_is_plausible(matrix, crop.shape[:2], (height, width)):
                return _rejected("feature_transform_failed_plausibility")
            aligned_features = cv2.warpAffine(
                resized_feature,
                warp,
                (width, height),
                flags=cv2.INTER_NEAREST | cv2.WARP_INVERSE_MAP,
                borderMode=cv2.BORDER_CONSTANT,
            )
            error = _alignment_error(canonical_feature, aligned_features, None)
            confidence = float(correlation)
            aligned = cv2.warpAffine(
                cv2.resize(crop, (width, height), interpolation=cv2.INTER_LINEAR),
                warp,
                (width, height),
                flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                borderMode=cv2.BORDER_CONSTANT,
            )
            candidate = self._result(
                aligned, matrix, confidence, error, "feature_affine", None
            )
            if confidence < config.minimum_confidence:
                return _rejected("feature_confidence_below_configured_threshold", candidate)
            if error > config.maximum_alignment_error:
                return _rejected("feature_error_above_configured_threshold", candidate)
            return candidate
        except Exception as exc:
            return _rejected(f"feature_registration_failed:{exc.__class__.__name__}")

    def _result(
        self,
        image: np.ndarray,
        matrix: np.ndarray,
        correlation: float,
        error: float,
        method: RegistrationMethod,
        failure_reason: str | None,
    ) -> RegistrationResult:
        return RegistrationResult(
            aligned_minimap=image.copy(),
            transform_matrix=(
                (float(matrix[0, 0]), float(matrix[0, 1]), float(matrix[0, 2])),
                (float(matrix[1, 0]), float(matrix[1, 1]), float(matrix[1, 2])),
            ),
            confidence=float(np.clip(correlation, 0.0, 1.0)),
            alignment_error=error,
            method=method,
            failure_reason=failure_reason,
        )

    def _affine_failure(
        self, fallback: RegistrationResult, reason: str
    ) -> RegistrationResult:
        accepted_fallback = self._apply_thresholds(fallback)
        if accepted_fallback.aligned_minimap is None:
            threshold_reason = accepted_fallback.failure_reason
            combined_reason = (
                f"{reason};{threshold_reason}" if threshold_reason is not None else reason
            )
            return _rejected(combined_reason, accepted_fallback)
        return replace(accepted_fallback, failure_reason=reason)

    def _apply_thresholds(self, result: RegistrationResult) -> RegistrationResult:
        if result.aligned_minimap is None or self.thresholds is None:
            return result
        if (
            result.confidence is not None
            and result.confidence < self.thresholds.minimum_confidence
        ):
            return _rejected("confidence_below_configured_threshold", result)
        if (
            result.alignment_error is not None
            and result.alignment_error > self.thresholds.maximum_alignment_error
        ):
            return _rejected("alignment_error_above_configured_threshold", result)
        return result


def _feature_failure_allows_raw_fallback(reason: str | None) -> bool:
    """Allow only feature fit failures to try separately thresholded grayscale."""
    if reason is None:
        return False
    return reason in {
        "feature_confidence_below_configured_threshold",
        "feature_error_above_configured_threshold",
        "feature_transform_non_finite",
        "feature_transform_failed_plausibility",
    } or reason.startswith("feature_registration_failed:")


def _transform_is_plausible(
    matrix: np.ndarray,
    source_shape: tuple[int, ...],
    target_shape: tuple[int, int],
) -> bool:
    """Require a finite, invertible transform covering at least half the image."""
    if matrix.shape != (2, 3) or not np.isfinite(matrix).all():
        return False
    linear = matrix[:, :2].astype(np.float64)
    determinant = float(np.linalg.det(linear))
    scale = float(np.linalg.norm(linear, ord=2))
    if not np.isfinite(determinant) or scale == 0.0 or determinant < 0.0:
        return False
    if determinant <= np.finfo(np.float64).eps * scale * scale * 16:
        return False

    source_height, source_width = source_shape[:2]
    target_height, target_width = target_shape
    corners = np.array(
        [
            [0, 0],
            [source_width - 1, 0],
            [source_width - 1, source_height - 1],
            [0, source_height - 1],
        ],
        dtype=np.float64,
    )
    mapped = corners @ linear.T + matrix[:, 2]
    target = np.array(
        [
            [0, 0],
            [target_width - 1, 0],
            [target_width - 1, target_height - 1],
            [0, target_height - 1],
        ],
        dtype=np.float32,
    )
    mapped_polygon = mapped.astype(np.float32)
    target_area = float(target_width * target_height)
    mapped_area = float(cv2.contourArea(mapped_polygon))
    if not np.isfinite(mapped_area) or mapped_area > 4.0 * target_area:
        return False
    try:
        intersection_area, _ = cv2.intersectConvexConvex(
            mapped_polygon, target
        )
    except cv2.error:
        return False
    return bool(np.isfinite(intersection_area) and intersection_area / target_area >= 0.5)


def _validate_images(
    crop: np.ndarray,
    canonical: np.ndarray,
    mask: np.ndarray | None,
) -> str | None:
    for name, image in (("minimap_crop", crop), ("canonical_minimap", canonical)):
        if not isinstance(image, np.ndarray) or image.ndim not in (2, 3):
            return f"{name}_must_be_a_2d_or_3d_image"
        if image.shape[0] < 3 or image.shape[1] < 3:
            return f"{name}_dimensions_too_small"
        if image.ndim == 3 and image.shape[2] not in (1, 3, 4):
            return f"{name}_has_unsupported_channel_count"
        if image.dtype != np.uint8:
            return f"{name}_must_have_uint8_pixels"
    if mask is not None:
        if not isinstance(mask, np.ndarray) or mask.ndim != 2:
            return "obstruction_mask_must_be_a_2d_image"
        if mask.shape != canonical.shape[:2]:
            return "obstruction_mask_dimensions_must_match_canonical_image"
        if mask.dtype != np.uint8:
            return "obstruction_mask_must_have_uint8_pixels"
        if np.all(mask > 0):
            return "obstruction_mask_excludes_entire_image"
    return None


def _gray(image: np.ndarray) -> Image:
    if image.ndim == 2:
        return cast(Image, image)
    if image.shape[2] == 1:
        return cast(Image, image[:, :, 0])
    if image.shape[2] == 4:
        return cast(Image, cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY))
    return cast(Image, cv2.cvtColor(image, cv2.COLOR_BGR2GRAY))


def _feature_image(
    image: np.ndarray,
    gray: np.ndarray,
    config: FeatureRegistrationConfig,
    *,
    source: bool,
) -> Image:
    lower, upper = config.source_gray_range if source else config.canonical_gray_range
    selected = (gray >= lower) & (gray <= upper)
    if source and image.ndim == 3 and image.shape[2] >= 3:
        channels = image[:, :, :3].astype(np.int16)
        spread = channels.max(axis=2) - channels.min(axis=2)
        selected &= spread <= config.maximum_source_channel_spread
    return cast(Image, selected.astype(np.uint8) * 255)


def _feature_coverage_is_valid(
    feature: np.ndarray, minimum: float, maximum: float
) -> bool:
    coverage = float(np.count_nonzero(feature) / feature.size)
    return minimum <= coverage <= maximum


def _resize_mask(mask: np.ndarray | None, size: tuple[int, int]) -> np.ndarray | None:
    if mask is None:
        return None
    resized = cv2.resize(mask, size, interpolation=cv2.INTER_NEAREST)
    return cast(np.ndarray, np.where(resized > 0, 0, 255).astype(np.uint8))


def _texture(image: np.ndarray, mask: np.ndarray | None) -> float:
    samples = image if mask is None else image[mask > 0]
    return float(np.std(samples)) if samples.size else 0.0


def _correlation(first: np.ndarray, second: np.ndarray, mask: np.ndarray | None) -> float:
    first_samples = first.astype(np.float32)
    second_samples = second.astype(np.float32)
    if mask is not None:
        selected = mask > 0
        first_samples = first_samples[selected]
        second_samples = second_samples[selected]
    if first_samples.size == 0:
        return 0.0
    first_centered = (first_samples - np.mean(first_samples)).ravel()
    second_centered = (second_samples - np.mean(second_samples)).ravel()
    denominator = float(np.linalg.norm(first_centered) * np.linalg.norm(second_centered))
    if denominator == 0.0:
        return 0.0
    return float(np.dot(first_centered, second_centered) / denominator)


def _alignment_error(first: np.ndarray, second: np.ndarray, mask: np.ndarray | None) -> float:
    difference = cv2.absdiff(first, second).astype(np.float32) / 255.0
    samples = difference if mask is None else difference[mask > 0]
    return float(np.mean(samples)) if samples.size else 1.0


def _rejected(reason: str, previous: RegistrationResult | None = None) -> RegistrationResult:
    return RegistrationResult(
        aligned_minimap=None,
        transform_matrix=previous.transform_matrix if previous else None,
        confidence=previous.confidence if previous else None,
        alignment_error=previous.alignment_error if previous else None,
        method="rejected",
        failure_reason=reason,
    )
