# Minimap calibration CLI

Run one offline calibration sample with:

```bash
valoscribe minimap calibrate \
  --video ./input/ascent.mp4 \
  --timestamp 00:00:08.500 \
  --hud-config ./configs/hud/profile.json \
  --map-config ./src/valoscribe/config/ascent_map.json \
  --output ./.local/runs/calibration
```

The output directory contains `frame.png`, `minimap_crop.png`,
`registered_minimap.png`, `alignment_overlay.png`, and `diagnostics.json` when a
frame and crop are available. Expected input, crop, and registration failures
are recorded in `diagnostics.json`; the command exits non-zero when calibration
is not accepted. The diagnostics record the timestamp, profile/map identifiers,
map asset and patch versions, crop source/dimensions, crop orientation,
source-crop-to-canonical transform, confidence, alignment error, registration
method, pass/fail, and failure reason.

A legacy `regions.minimap` rectangle is accepted for backward compatibility, but
is labelled `legacy_regions_minimap_unvalidated` and cannot produce a passing
calibration. A configured minimap profile must also set
`calibration_status: "validated"` before the CLI can report pass. Calibration
without reviewed landmark labels is always diagnostic/provisional and cannot
report pass, even when HUD, map geometry, and registration thresholds are
validated. Labels must bind to the exact decoded frame and canonical image,
and `registration_thresholds.maximum_landmark_error_px` must be configured and
satisfied. Before decoding or registering the canonical image, the CLI verifies
the local asset's file-byte SHA-256 against `canonical_minimap.sha256`; a
mismatch is rejected with expected and actual hashes in the diagnostic.
The bundled
Ascent map is catalog release 13.06; it has no verified game-patch label, and
its tactical geometry remains pending. Its configuration contains candidate
registration thresholds: `minimum_confidence: 0.30`,
`maximum_alignment_error: 0.25`, and `maximum_landmark_error_px: 25`
canonical-image pixels. These candidate values are not general
production-validated limits; do not treat ECC confidence or a visually
plausible overlay as proof of correct map orientation or geometry.

## Local VCT Americas sample: measured candidate, not validated profile

The external VOD at the time of measurement was:

`../VOD/YTDown.com_YouTube_Media_4LEGEQ8KBS0_100T-vs-LOUD-VCT-Americas-Stage-2-Playoffs-Grand-Final-Map-3-Ascent_001_1080p.mp4`

It is user-supplied local input and is not bundled. A candidate HUD profile is
`src/valoscribe/config/ascent_vct_americas_2026_stage2_final_1080p_candidate.json`.
It records a conservative rectangle `(x=70, y=50, width=360, height=400)` in a
1920x1080 frame. Manual pixel inspection of six sampled gameplay frames found
the minimap outline consistently within approximately `x=75..425, y=58..443`;
the configured bounds add a small margin and exclude the prior 450x450 crop's
large gameplay-background area. The measured rectangle is a fixture-specific
candidate, not a production-calibrated HUD profile. The manifest below records
frame timestamps, visible round numbers, and observed overlay conditions; no
frame pixels or VOD data are stored in the repository.

The Riot Public Content Catalog Ascent map shows A near the top and B near the
bottom. At the sampled broadcast frames A is on the right and B on the left,
consistent with rotating the broadcast crop 90 degrees counter-clockwise to
compare it to the catalog image. The candidate profile records this orientation.
The CLI rotates/pads for image registration and composes the rotation/padding
with the registrar matrix, so `transform_matrix` continues to map coordinates
from the original unrotated crop to canonical-image coordinates.

| Time (seconds) | Nominal frame ID at 60 fps | Visible round | Sample condition |
|---:|---:|---:|---|
| 300 | 18000 | 4 | live gameplay; spike-carrier-killed banner and killfeed |
| 600 | 36000 | 6 | live gameplay; spike-planted banner |
| 840 | 50400 | 7 | live gameplay; player HUD, weapon/action effects |
| 2460 | 147600 | 19 | live gameplay; killfeed / signature-ability banner |
| 2820 | 169200 | 22 | live gameplay; broadcast killfeed and ability HUD |
| 2940 | 176400 | 23 | live gameplay; killfeed and player HUD |

Earlier calibration runs were written outside the repository, and their
original files are not guaranteed to be present in this checkout. Any future
local calibration output belongs under `.local/runs/`; the VOD itself remains
external. The cited runs used a pending map config and pending HUD profile and
were diagnostic only.

The screen evidence confirms the *relative orientation* (A right/B left versus
A top/B bottom) and supports the candidate crop bounds. It does not prove
coordinate registration: minimap display includes player/utility icons,
translucent background, and possible version/style differences. Across the six
runs, affine ECC confidence ranged from 0.366 to 0.835, and normalized mean
absolute pixel error ranged from 0.144 to 0.229. These are diagnostic metrics,
not acceptance thresholds or a pass claim. The map remains
`geometry_status: pending`, HUD profile remains `calibration_status: pending`,
and the calibration command rejects the runs.

To promote either profile, obtain permitted, independently reviewed labels
spanning both halves and broadcast overlay states; independently review exact
map footprint and orientation; mask/normalize dynamic icons and any background
beneath the transparent minimap; and establish production thresholds with
reviewer provenance. The VTA-103 heldout evaluation and its frozen 25-pixel
manifest-level gate are documented in `docs/minimap-vta103-evaluation.md`;
that offline gate does not configure production thresholds or promote either
pending profile. No threshold was relaxed to improve these results.

Calibration uses local files only. It does not download input videos, maps, or
other assets.

## Optional labeled-landmark evaluation

To measure registration against independently reviewed points, pass an optional
JSON file with `--landmarks ./labels.json`:

```json
{
  "provenance": "Reviewer, source frame/asset, and labeling method",
  "source_frame_sha256": "<64 lowercase hex characters>",
  "canonical_asset_sha256": "<64 lowercase hex characters>",
  "landmarks": [
    {
      "landmark_id": "reviewed-point-1",
      "source_crop_point": {"x": 120.0, "y": 80.0},
      "canonical_point": {"x": 310.0, "y": 205.0}
    }
  ]
}
```

Coordinates are finite, non-negative pixel coordinates measured from the
upper-left of the original, unrotated `minimap_crop.png` and canonical map
image, respectively. At least one uniquely identified point and non-empty
provenance are required; malformed, empty, or out-of-bounds labels produce a
failure diagnostic. The two SHA-256 values bind labels to the exact decoded
source frame and canonical image used by this run. Label-binding hashes use
compact ASCII JSON for the decoded array shape, followed by a NUL byte and
contiguous row-major decoded pixel bytes; they do not hash PNG/JPEG file bytes.
Separately, `canonical_minimap.sha256` is verified against the canonical asset's
exact file bytes before it is loaded. The frame
hash covers the full decoded video frame, not the minimap crop. Mismatches fail
with an explicit diagnostic.

`diagnostics.json` includes per-point Euclidean reprojection error in pixels
plus mean, RMS, maximum error, and the configured acceptance limit. Labels
without `registration_thresholds.maximum_landmark_error_px` fail closed; the
maximum measured error must not exceed that independently configured pixel
limit. No threshold is inferred from labels, and labels do not promote a
pending HUD profile or map geometry. Independently configured production
thresholds and profile validation remain pending; VTA-103 has real reviewed
train, validation, and heldout labels, but remains approximate visual evidence.
Synthetic examples are not real acceptance evidence.
