> **Archived:** Historical material retained for provenance; it is not current implementation guidance. Use the [active MVP Reset specification](../../specs/active/MVP_RESET_AND_REPOSITORY_CLEANUP_SPEC.md).

# Portrait structure diagnostic: synthetic foundation and frozen construction protocol

## Scope and evidence status

This module is an opt-in diagnostic foundation for VTA-304, not issue completion, a production matcher, a calibrated predictor, or approval of portrait identity. It uses one closed compact edge-enclosure hypothesis and a supported spatial grayscale-gradient descriptor. No roster, player/agent identity, identity template, or label is available to localization. The enclosed region is a geometric hypothesis only: a ring is not proof of portrait purity, and gradients may encode marker or map/background edges. Synthetic tests do not establish semantic overlap handling or face purity.

Policy values are explicitly synthetic-only and unvalidated against broadcast sources. No production crop coordinates, crop thresholds, or identity thresholds are declared here. The diagnostic has no CLI, tracker, or default pipeline integration. It writes no artifacts unless the explicit debug writer is called.

Result contracts require all finite, ROI-contained, center-consistent geometry and feature, pixel-support, and canonical-gradient digests for `localized`. The gradient digest binds supported per-pixel magnitude/orientation values to the exact support bitmap, native shape, ROI/boundary mapping, source-image digest, and policy digest. Comparisons and debug writing recompute that digest and abstain/reject if mutable gradient arrays no longer match. Every failure state forbids each success-only field individually and reports zero usable support/gradient count. Nested contour representations are deduplicated only when dimensions, center, and intersection-over-union are comparable; distinct nested enclosures remain competing proposals and abstain.

## Frozen construction protocol specification (future authorization required)

Before opening an allowlisted construction image, freeze the implementation revision and a construction manifest containing:

- Each source file's encoded and decoded image hashes, source/frame provenance, dimensions, and live/replay evidence.
- Native coordinate convention, source context envelopes, boundary annotations with reviewer-declared uncertainty, visible structural evidence, clipping and neighboring-marker overlap evidence. Unsupported boundaries remain unknown.
- Predictor-input manifest separated from reviewer annotations. Review centers, labels, and corrections are scoring annotations only and never localization inputs or offset-selection targets.
- Frozen grid, comparison and support rules, synthetic policy, implementation digest, full preprocessing/pipeline/configuration digest, and expected output cardinalities.
- Every registered observation and every preregistered perturbation, including abstentions, no-enclosure cases, ambiguity, clipping, overlap, and unavailable descriptors.
- For clear supported observations, the full registered integer ±3 grid; never select a best offset. Report localization agreement against reviewer-declared uncertainty before prediction inspection.
- Independently reviewed portrait-boundary and diagnostic-feature evidence. Roster elimination cannot establish identity or boundary truth.
- Localization success/abstention/clipping/overlap/descriptor-availability counts. Zero useful coverage cannot pass. At least two usable, independently reviewed observations on different frames per each of seven agents are required before any bank-readiness decision; conditional examples do not automatically qualify.
- Self-excluded cross-frame structural comparisons versus the fixed BGR baseline, retaining ties, adverse offsets, and unavailable comparisons. This is not calibrated accuracy or an acceptance threshold.

The construction loop is bounded to one frozen construction run and independent review, then at most one documented mechanism-level revision with a new preregistration. Otherwise request the exact missing permissible construction artifact or stop. No repeated center, mask, or parameter sweeps. Do not access sealed calibration, heldout, evaluation, gold, or the broader historical ledger in this work.

The previously authorized source allowlist for a later, separately approved preparation step is:

- `/tmp/vta304-calibration-r2/construction/full/frame-025200.png`
- `/tmp/vta304-calibration-r2/construction/full/frame-032400.png`
- `/tmp/vta304-calibration-r2/construction/full/frame-033600.png`
- `/tmp/vta304-calibration-r2/construction/full/frame-034800.png`
- Corresponding PNGs under `/tmp/vta304-calibration-r2/construction/minimap/`

No source images were accessed in this implementation. Further image use still requires the frozen protocol and independent reviewer packet authorization. No network, acquisition, or external API is part of this diagnostic.

## Full VTA-304 remains pending

This slice does not produce `player_tracks.parquet`, reviewed labeled-round identity/visibility records, timestamp/candidate-matched predictions, identity accuracy, visible-player coverage, identity-switch counts, or stable-identity playback. Those tracks and metrics remain pending, with documented denominators, until a separately authorized and reviewed real construction/evaluation sequence can support them. Do not report unavailable metrics as zero or infer identity from temporary track IDs. Existing Round 4 Omen evidence remains partial, not full-round acceptance.

## Support and comparison semantics

The analysis retains a native-resolution binary support mask: a pixel is supported only when the pixel and its complete 3×3 derivative stencil are valid and not excluded. `support_sha256` digests this full pixel mask, not a grid-cell occupancy vector. `gradient_sha256` binds canonical finite float32 magnitude/orientation arrays only at supported native pixels, together with the entire support mapping and pipeline/source binding. The policy grid pools only nonzero supported gradients; `minimum_gradient_pixels` counts those gradients per cell.

Comparison requires matching policy digests and equal native proposal width/height. It maps the arrays by integer pixel offsets from each proposal boundary; there is no resize, fractional interpolation, or inferred partial-cell equivalence. Unequal dimensions conservatively return unavailable. The reported `shared_support_fraction` is the exact number of mutually supported native pixels divided by proposal area. Each comparison histogram is recomputed from only those common pixels, shared cells are selected after gradient-count gates, and each vector is normalized only after restricting to shared cells. Thus unsupported pixels/cells cannot contribute to comparison normalization. This is a raw diagnostic distance, not an identity probability or calibrated score.

## Debug bundle

`write_portrait_structure_debug` explicitly writes `diagnostic.json`, proposal overlay, edge map, support and exclusion masks, gradient magnitude/orientation previews, and descriptor/support arrays. The manifest retains the canonical policy body and digest, whether an exclusion mask was provided, and SHA-256 values for each artifact. PNG writes are checked for success and lossless decode equality; NPZ arrays are reopened and compared. Digest disagreement or failed writes raises an error. These artifacts are diagnostic only. Neither the in-memory nor serialized descriptor represents identity probability.
