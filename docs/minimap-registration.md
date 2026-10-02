# Minimap registration

> **Local/future-checkpoint note:** The VTA registration implementation and related configs/tests are not included in a docs-only published checkout until a dependency-complete code checkpoint is included. Code examples and commands are not runnable from docs alone; see [`PUBLISH_BOUNDARY.md`](PUBLISH_BOUNDARY.md).

`valoscribe.maps.MinimapRegistrar` resizes a validated minimap crop to the
canonical image dimensions and can refine the result with OpenCV ECC affine
registration. It does not estimate a homography or fetch images at runtime.

```python
from valoscribe.maps import MinimapRegistrar

result = MinimapRegistrar(map_definition.registration_thresholds).register(
    crop,
    canonical_image,
    obstruction_mask=known_overlay_mask,  # nonzero pixels identify obstructions
)
```

This obstruction-mask example applies to the default grayscale/ECC mode. Map-specific
feature registration does not accept `obstruction_mask` and requires
`refine_affine=True`; those incompatible options return structured rejections.

The result reports an aligned image, a 2×3 transform from original crop pixels
to canonical-image pixels, ECC/correlation confidence, normalized mean absolute
alignment error, the selected method, and a failure reason. Input validation,
low texture, OpenCV convergence failures, and configured-threshold rejection
produce structured results instead of escaping exceptions. If ECC refinement
fails, the fixed resize is returned with `affine_refinement_failed`; invalid or
low-texture inputs are rejected.

`MapRegistrationThresholds` must come from map configuration and be set only
from calibration evidence. Ascent currently has candidate configured values of
`minimum_confidence: 0.30`, `maximum_alignment_error: 0.25`, and
`maximum_landmark_error_px: 25` canonical-image pixels. These are candidate
thresholds, not general production-validated limits; the map geometry and HUD
profile remain pending real-VOD calibration acceptance. Synthetic and optional
local-VOD tests save generated artifacts in pytest's per-test temporary
directory.

## Map-specific feature registration

A map may opt in to `feature_registration`. If absent, the original whole-image
grayscale fixed/ECC path is unchanged. When configured, registration uses
thresholded stable grayscale features, with source channel-spread filtering to
remove the translucent scene background. Its confidence and binary-mask
alignment error use the feature domain and are checked only against the separate
`FeatureRegistrationConfig` limits. Feature coverage, ECC output, and geometric
plausibility are also checked. Invalid feature inputs and unsupported options are rejected. If a valid feature
fit fails, registration may try the original grayscale path only when its own
map-specific thresholds are configured; it returns a raw transform only if that
path independently passes those thresholds. The result records each method's
score and failure reason separately. No feature score is compared with a raw
threshold, and failure of both paths remains a rejection. The aligned output
uses the original color crop warped by the accepted transform.

Ascent's feature settings (`source_gray_range: [65, 165]`,
`canonical_gray_range: [65, 160]`, source channel spread ≤10) were evaluated on
train frames 300s and 840s. Before assessing later samples, separate candidate
limits were frozen at feature confidence ≥0.70 and binary alignment error
≤0.15 (train minima/maxima: 0.7271 and 0.1169). These are evidence-bounded
candidate values for this VOD/profile, not generally validated thresholds.
The legacy raw grayscale limits remain unchanged at confidence ≥0.30 and error
≤0.25 and are not loosened or reused as feature metrics.

| Time | Split | Feature confidence | Feature error | Maximum landmark error | Feature limits | 25 px landmark gate |
|---:|---|---:|---:|---:|---|---|
| 300s | train | 0.8041 | 0.0867 | 12.434 px | pass | pass |
| 840s | train | 0.7271 | 0.1169 | 12.222 px | pass | pass |
| 2460s | validation | 0.7577 | 0.1051 | 6.381 px | pass | pass |
| 2820s | test | 0.7384 | 0.1144 | 5.182 px | pass | pass |
| 2940s | test | 0.7658 | 0.1026 | 13.123 px | pass | pass |
| 2490s | smoke-window test | 0.8053 | 0.0852 | 10.134 px | pass | pass |
| 2505s | smoke-window test | 0.8386 | 0.0718 | 10.167 px | pass | pass |

The two smoke-window frame hashes are
`228589eb602d57d757f31843efd0c936f3f3617bf387945deb1ed771c9efbbcb` (2490s)
and `f472f552dd047647e2c51d4ce54ec47a92fcdc9bda669bb3aeff7a7294b1fd32`
(2505s). Their four landmarks each are approximate visual annotations from a
reviewer who had seen prior fixture labels; they are not blind or pixel-verified
ground truth. The separate fixture records that limitation. Across all seven
samples, measured feature confidence/error and each measured landmark gate
pass; the 25-pixel gate is an offline evaluator limit, not production
calibration. Per-sample original annotations also remain approximate visual
evidence, not pixel-verified ground truth.

Calibration remains fail-closed: overall `diagnostics.passed` is false because
the HUD profile and map geometry remain pending. Passing feature and landmark
checks does not validate the HUD, map geometry, or production registration.
