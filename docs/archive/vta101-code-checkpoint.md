> **Archived:** Historical material retained for provenance; it is not current implementation guidance. Use the [active MVP Reset specification](../../specs/active/MVP_RESET_AND_REPOSITORY_CLEANUP_SPEC.md).

# VTA-101 limited code checkpoint

## Scope and boundary

This page describes the reviewed, limited six-file code checkpoint for synthetic minimap HUD-profile cropping and safe crop saving. It records the exact candidate file allowlist; it is not production acceptance and does not complete VTA-101. Inclusion in any checkout must be verified against the referenced paths and checkpoint version; the earlier docs-only commit `56e45e7` does not contain this checkpoint. Do not claim a push or other publication until verified against an actual commit SHA. Any publication claim must be tied to a commit that contains exactly the reviewed checkpoint (including the scoped two-line change to `utils.py`) and its required dependencies.

Candidate allowlist:

1. `src/valoscribe/detectors/cropper.py`
2. `tests/test_detectors/test_cropper.py`
3. `tests/test_detectors/test_minimap_profile.py`
4. `tests/fixtures/generate_synthetic_frame.py`
5. `src/valoscribe/commands/utils.py` — only the two-line empty-crop guard in the save-crops loop; the original worktree file also has unrelated dirty hunks that are **not** in this checkpoint.
6. `tests/test_utils/test_save_crops.py`

The code adds an opt-in minimap profile interface; it does not supply or claim production HUD coordinates. Existing profiles without the new top-level profile retain legacy behavior. The synthetic fixture and geometry below are test-only, not observed HUD/map measurements.

## Behavior and failure paths

`Cropper.crop_minimap(frame)` reads a top-level `frame_width`, `frame_height`, and `minimap` rectangle (`x`, `y`, `width`, `height`). It rejects malformed frames, absent/invalid positive integer frame dimensions, frame/profile dimension mismatches, negative origins, non-positive rectangle size, and rectangles outside the configured frame with `ValueError`. On success it returns a copied BGR/BGRA crop. When the profile has no new `minimap` entry, the helper returns an empty `(0, 0, 3)` array; `crop_all_regions` keeps the `minimap` output key, uses legacy `regions.minimap` where available, or returns the empty sentinel otherwise.

`tests/fixtures/generate_synthetic_frame.py` creates a deterministic 320×180 PNG and JSON metadata with synthetic 11×11 red, green, and blue square anchors centered at `(48,42)`, `(160,90)`, and `(272,138)`. In particular, a test profile rectangle `{ "x": 40, "y": 34, "width": 18, "height": 18 }` puts the red anchor center at crop-local `(8,8)`; its expected BGR pixel is `[0,0,255]`. The fixture is generated in a test temporary directory and makes no production-coordinate claim.

The `utils crop --save-crops` path now skips writing simple-region crops with `crop.size == 0`. This fixes the reviewed P1 failure when an absent minimap is represented by the empty sentinel. Non-empty simple HUD regions still use the existing `cv2.imwrite` path and filename/format. The regression invokes the Typer CLI, makes the writer reject empty arrays, verifies the four nonempty simple regions are saved, and verifies `minimap.jpg` is omitted. It mocks reader, cropper, and GUI calls; this is not real video or image-encoding validation.

## Review and verification evidence

The independent review at `/Users/naheedroomy/.pi/agent/sessions/--Users-naheedroomy-Documents-valorant-analyzer--/subagent-artifacts/outputs/30010db1-92e2-4fc4-956f-5cad56153f40/vta101-save-path-fix-review.md` found no blockers and returned “OK with notes.” It confirmed that the save guard skips only zero-size arrays, retains nonempty crop output behavior, and fixes the empty-minimap P1. Review limits: no production footage, calibration, real encoding, or source-media acceptance was established.

Focused recipe (run from repository root after the exact six-file checkpoint and project dependencies are available):

```bash
uv run pytest tests/test_detectors/test_cropper.py tests/test_detectors/test_minimap_profile.py tests/test_utils/test_save_crops.py
```

The parent's focused full recipe (the three test files listed above) reported **36 passed**; the narrower minimap-profile and save-path mini-recipe reported 9 passed, and should not be mistaken for the full recipe. A broader, read-only snapshot comparison reported candidate **456 passed, 33 failed**, versus upstream baseline **447 passed, 33 failed**; all 33 failing test names were identical. Ruff findings were 396 candidate versus 406 baseline, and mypy findings were 202 candidate versus 210 baseline. These are comparisons of those specific checkpoint snapshots, not clean full-suite gates or acceptance metrics. They must not be conflated with the parent-reported later run on the separate original worktree: `uv run pytest` 1,167 passed, 1 skipped; Ruff clean; mypy clean across 119 files. That later worktree was not the published candidate snapshot and did not change the production-acceptance boundary.

## Remaining acceptance

VTA-101 remains open. Production HUD provenance/profile coordinates and fixture-backed golden crops remain pending. No issue completion, production crop accuracy, or real-source metric is claimed here. See [`project-status-legacy.md`](project-status-legacy.md) and [`EVIDENCE_INDEX.md`](EVIDENCE_INDEX.md) for current acceptance status and reproduction boundaries.
