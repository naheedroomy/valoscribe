> **Archived:** Historical material retained for provenance; it is not current implementation guidance. Use the [active MVP Reset specification](../../specs/active/MVP_RESET_AND_REPOSITORY_CLEANUP_SPEC.md).

# VTA-103 real-VOD landmark evaluation

> **Local/future-checkpoint note:** The evaluator, manifest, configs, and tests referenced here are not included in a docs-only published checkout until a dependency-complete code checkpoint is included. The command below is a local/future recipe, not runnable from docs alone; see [`../architecture/publish-boundary.md`](../architecture/publish-boundary.md).

This artifact records independently reviewed registration labels for the Ascent
minimap in a locally supplied VCT Americas Stage 2 final VOD. Points were
placed on the *unwarped* 360×400 source crop and 2048×2048 canonical asset,
without using a registration transform. Labels are approximate visual
annotations, not pixel-verified ground truth.

- Source frame: 1920×1080; crop: 360×400; canonical asset: 2048×2048.
- Reviewer 1 annotated five landmarks at 300s and 840s; those original labels
  are unchanged.
- Reviewer 2 annotated four landmarks at 2460s; L4 was not confirmed and
  remains omitted.
- An independent reviewer added five landmarks at both 2820s and 2940s.
  Frame 2820 is clear; frame 2940 has translucent scenery, but the landmark
  corners are discernible. Uncertainty is ±2 source/±8 canonical pixels for
  L1, L2, L3, L5 and ±3 source/±10 canonical pixels for L4.
- The samples at 300s/840s are `train`; 2460s is `validation`; 2820s/2940s
  are independently reviewed `test` samples. Decoded frame hashes bind each
  annotation to the exact full-resolution frame. Video pixels are not checked
  into the repository.

## Frozen evaluation gate and result

Before evaluating the new labels, the maximum per-landmark reprojection error
was frozen at **25 canonical pixels**. The limit is based on 3 source pixels
× approximately 5 canonical pixels per source pixel + 10 canonical pixels of
annotation uncertainty. A split passes this offline gate only if every
landmark error is ≤25 pixels. The evaluator itself does not tune transforms, labels, or thresholds. Its
`offline_manifest_gate` is a separately named result against this frozen
25-pixel manifest-level limit; it is not production calibration acceptance.
Every manifest sample remains in its split summary, including decode,
registration, binding, malformed-label, or missing-reprojection failures. Such
samples are reported with `sample_error` and fail the offline gate. Split
coverage reports expected/evaluated/error sample counts and per-sample maxima.
The Ascent map config now supplies candidate registration limits:
`minimum_confidence: 0.30`, `maximum_alignment_error: 0.25`, and
`maximum_landmark_error_px: 25`. The confidence/alignment limits are conservative
limits chosen from measurements on these five real samples; all five measured
confidence values were ≥0.3665 and alignment errors ≤0.2287. Because these two
limits were set after observing this sample set, they have potential post-hoc
bias and are not evidence of generalization to held-out VODs. The 25-pixel
landmark limit was frozen before held-out evaluation; the largest measured
per-landmark error was 9.7792 px. All five current diagnostics pass each
configured candidate limit and the landmark evaluation, while overall
`diagnostics.passed` remains false with `hud_minimap_profile_pending`. These
are candidate evaluator limits, not full production calibration. The
evaluator's own `thresholds_used: null`
continues to mean it does not independently tune or claim production
acceptance. HUD calibration and map geometry remain pending.

Evaluated with the real local VOD and current affine registration pipeline:

| Split | Samples | Points | Mean error | RMS error | Maximum error | 25 px gate |
|---|---:|---:|---:|---:|---:|---|
| Train (300s, 840s) | 2 | 10 | 6.083 px | 6.541 px | 9.779 px | Pass |
| Validation (2460s) | 1 | 4 | 4.879 px | 4.988 px | 6.348 px | Pass |
| Test (2820s, 2940s) | 2 | 10 | 4.634 px | 4.979 px | 7.471 px | Pass |

All individual split maxima are below the frozen 25-pixel limit. On the new
heldout frames, maximum error is 4.804 px at 2820s and 7.471 px at 2940s. This
is a descriptive, approximate-label result; it is not pixel-verified ground
truth or evidence that map/HUD calibration is production-ready. The report
from `scripts/maintenance/evaluate_minimap_landmarks.py` retains
`acceptance_status: not_assessed` and `thresholds_used: null`: the fixed
manifest-level evaluation gate is intentionally separate from production
registration acceptance. Candidate confidence/alignment/landmark limits are
configured in the map definition, but their empirical calibration on this five-
sample set may be post-hoc biased and does not establish held-out generalization.
HUD calibration and map geometry remain pending, so the global calibration pass
guard remains closed even when individual landmark evaluations pass.

## Reproduce locally

Use the external VOD at the matching filename below (or supply its local path):

```bash
uv run python scripts/maintenance/evaluate_minimap_landmarks.py \
  --video ../VOD/YTDown.com_YouTube_Media_4LEGEQ8KBS0_100T-vs-LOUD-VCT-Americas-Stage-2-Playoffs-Grand-Final-Map-3-Ascent_001_1080p.mp4 \
  --manifest tests/fixtures/registration_landmarks/ascent-vct-americas-stage2-grand-final-vta103.json \
  --hud-config src/valoscribe/config/ascent_vct_americas_2026_stage2_final_1080p_candidate.json \
  --map-config src/valoscribe/config/ascent_map.json \
  --output /tmp/vta103-evaluation
```

The source frame hashes for the newly reviewed samples were computed from
frames decoded by the same OpenCV `VideoCapture` path used by
`calibrate_video`, with `CAP_PROP_POS_MSEC` set to timestamp × 1000 and the
full decoded BGR frame hashed via `decoded_image_sha256`:

- 2820s: `56a89f2e7ae80eb51074fc28119f692e924e5895acd1c3c0ea18c960b4e848f9`
- 2940s: `6aa5a721538da797d3c325c04e2380b0d6c12374efb850e9184db0d2324807fe`

The script writes per-sample diagnostics and `evaluation.json` in the output
directory. Hash mismatches must be investigated; never edit hashes to bypass a
mismatch. The VOD remains external and must use the filename recorded in the
manifest. The opt-in local-VOD integration test uses `VTA103_VOD_PATH` when set,
or the documented `../VOD` location; it skips when the file is unavailable and
never downloads video. It verifies all five decoded frame hashes and the five-
sample report.
