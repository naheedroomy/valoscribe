> **Archived:** Historical material retained for provenance; it is not current implementation guidance. Use the [active MVP Reset specification](../../specs/active/MVP_RESET_AND_REPOSITORY_CLEANUP_SPEC.md).

# Player-track artifact and evaluation

> **Local/future-checkpoint note:** Tracking implementation, optional Parquet extra, fixtures, and tests cited here are not included in a docs-only published checkout until a dependency-complete code checkpoint is included. Commands are not runnable from docs alone; see [`../architecture/publish-boundary.md`](../architecture/publish-boundary.md).

`tracking.artifacts.build_track_rows` converts one raw motion estimate and its
smoothed/interpolated result into a validated artifact row. The row stores raw
estimate JSON and raw evidence separately from derived coordinates, state,
confidence, rejection reason, and derived evidence. The artifact writer emits
Apache Parquet with the `player_tracks/1.0` schema marker; the reader validates
the marker and every row. CSV/JSON files are not written with a `.parquet`
extension.

Parquet support is optional to keep the CV installation light. Install it with
`uv sync --extra parquet` (or install the package with `[parquet]`). If PyArrow
is absent, read/write fails explicitly with `ParquetUnavailableError` before
creating output. PyArrow 25.0.1 was installed with
`uv sync --extra dev --extra parquet`; the optional integration test now writes
and reads a real `player_tracks.parquet`, checks both `PAR1` file markers, the
complete row-field schema and `player_tracks/1.0` metadata, compares decoded
rows, and writes independently timestamped playback PNGs. Run the reproducible
smoke with:

```bash
uv run --extra dev --extra parquet pytest \
  tests/test_tracking/test_artifacts.py::test_parquet_round_trip_when_optional_dependency_is_available -q
```

This synthetic end-to-end smoke verifies the artifact path, not real-player
identity accuracy or map calibration. Four inspected minimap frames at
300.00, 301.00, 302.00, and 303.00 seconds support only temporary visual tracks
T1–T4, R1, and R3; they do not provide unambiguous real roster/player IDs. The
red mark at (75, 202) in the 300-second frame remains an unresolved static
overlap and is a separate VTA-201 revisit. Four-frame visual continuity alone
is insufficient to claim real identity accuracy or an identity-switch metric.

## VTA-304 #50: partially reviewed Round 4 identity fixture

`tests/fixtures/player_identity_observation_vta304_round4.json` is a versioned raw-source
label fixture for Round 4 of the registered 100T–LOUD Ascent VOD. Its six
samples bind exact decoded BGR full-frame and 360×400 minimap crop SHA-256
hashes to source frames 18000, 18001, 18002, 18060, 18120, and 18180 (60 fps,
300–303 seconds). The 18000–18002 frames were decoded consecutively from the
local registered MP4. They are recorded as identity/visibility evidence only,
not as 60-fps movement. The separate one-second samples support reviewed Omen
icon centers (crop pixels) (283, 250), (276, 252), and (270, 260) at 300, 301,
and 302 seconds. The 18001, 18002, and 18180 samples are marked uncertain with
notes because no icon center was independently localized in those frames.

The reviewed full HUD identifies both 100T bang and LOUD Erde as Omen, but bang
is alive while Erde's player panel is greyed/dead. Thus Omen appearance alone is
ambiguous across teams. Reviewer visual inspection found the blue-hooded icon
moving across the localized samples; combined with same-frame HUD alive/dead
contrast, this supports attributing the live icon to 100T bang, with bounded
confidence. Broadcast color is not used as a permanent team identifier. The
fixture stores only human source labels and hashes. It contains no tracker
predictions, evaluation results, score, accuracy claim, or full-round coverage
claim. Visible samples require a center; uncertain samples require an
explanatory note.

The manifest can be independently re-extracted and checked against the local
source file, fail-closed on file metadata or hash mismatch, with this explicit
opt-in command (no network or manifest mutation):

```bash
uv run python scripts/maintenance/validate_player_identity_observation.py \
  --video ../VOD/YTDown.com_YouTube_Media_4LEGEQ8KBS0_100T-vs-LOUD-VCT-Americas-Stage-2-Playoffs-Grand-Final-Map-3-Ascent_001_1080p.mp4
```

The fixture is a partially reviewed prerequisite, not VTA-304 acceptance. Full
round coverage, visibility labeling throughout the round, timestamp-matched
tracker predictions, real-player identity accuracy, visible-player coverage,
identity switches, and stable-identity playback remain pending.

`evaluate_identity_labels` reports identity accuracy, visible-player coverage,
and identity switches only when reviewed labels are supplied. With no labels,
it returns `available=false` and no fabricated metric values. The exact fixture
needed to unblock full acceptance is a permitted labeled reference set
containing the match ID and round ID; VOD timestamps for each reviewed frame;
stable real player IDs with evidence linking each ID to its minimap icon;
per-frame visibility labels; expected player IDs for visible icons; and
corresponding timestamped tracker predictions for those same candidate IDs.
Unlabeled VOD crops or temporary labels such as T1/R1 do not qualify.

`render_track_overlay` makes a canonical-map debug image with stable player IDs;
observed points are green and derived/interpolated points are orange.
`write_track_debug_playback` writes an ordered PNG sequence (one timestamp per
frame) without a video codec dependency. Each frame contains only rows at its
timestamp, and one export rejects mixed matches or rounds. These synthetic
interface tests do not establish real identity accuracy or map calibration;
reviewed label metrics remain pending.

## VTA-304 supervised crop-space diagnostic (development only)

`scripts/dev/diagnose_vta304_supervised_crop.py` is an explicitly supervised
crop-local diagnostic. It reuses the frozen VTA-201 color detector profile and
the repository's deterministic `_hungarian` implementation with a documented
motion-cost adapter. It does not register the map, convert crop pixels to
canonical coordinates, export accepted `player_tracks`, or change the pending
production crop-calibration/identity gates. The seed is a separate development
annotation JSON; the gold observation fixture is not a script input. Predictions
are written to a new output directory by staging and atomic publication.
Raw accepted and rejected color candidates remain in `raw_detections.jsonl`;
association ambiguities, missed detections, and motion-gate abstentions remain
explicit in `predictions.jsonl`. Version 2 records separate hashes for decoded
BGR frame bytes, decoded BGR crop bytes, and encoded PNG bytes, with explicit
raster conventions. It hashes the exact persisted policy bytes and inventories
the dependency source files and runtime/media-tool versions. Debug PNGs are
crop-space detector overlays, not canonical-map evidence.

The runner requires a typed `source_binding` in the seed: source-video digest,
exact frame and timestamp, exact configured crop rectangle, coordinate frame,
decoded BGR full-frame and crop hashes, and supplied per-axis uncertainty.
The legacy development seed has no such binding and is rejected by default;
re-measure the actual seed frame before running the version-2 workflow. Do not
copy or infer hashes from another acquisition. A seeded identity and later
association remain uncalibrated; no identity probability is asserted.

The available development seed at 280.0s identifies 100T bang / Omen at
(275, 255) in the original 360×400 minimap crop, with a supplied approximate
±5px-per-axis scoring assumption. This tolerance is not stored in the gold
fixture. The fixed diagnostic policy uses a 14px seed radius, 70px/s maximum
motion, 1.0s maximum gap, 4px ambiguity margin, and 70px assignment cost
ceiling. The historical run decoded and verified the full source stream and
retains all 45 half-second samples from frame 16800 / 280.0s through frame
18120 / 302.0s. Predictions were frozen at
`/tmp/vta304-supervised-crop-diagnostic` before the isolated scoring command.
This output contains 1 seeded, 41 associated, and 3 abstained samples; it has
2,909 raw candidates and 23 real crop-space debug overlays. Source labels are
not used to tune this run.

A process-order deviation must remain visible in machine-readable run
provenance: `evaluation_blinding.strict_freeze_before_gold=false`,
`evaluation_blinding.developer_gold_exposure=true`,
`evaluation_blinding.programmatic_input_separation=true`, and
`acceptance={"status":"diagnostic_only","assessment":"not_assessed"}`.
An earlier parallel inspection accidentally opened
`tests/fixtures/player_identity_observation_vta304_round4.json` before predictions were
frozen. The runner does not accept/read the gold fixture; this is only
programmatic input separation and does not establish developer blinding or an
untouched holdout. No labels were injected into predictions, and no thresholds
or predictions were changed after scoring. Strict freeze-before-opening-gold
procedure cannot be claimed. The failed localization results are evidence,
not completion or acceptance. Isolated comparison against its three visible
labels
at 300s, 301s, and 302s found one abstention and two associations. The 301s
center (278, 242) is about 10.2px from the labeled (276, 252); the 302s center
(271.5, 250.5) is about 9.6px from (270, 260). Both exceed the supplied approximate ±5px-per-axis scoring assumption. Thus this supervised crop diagnostic
has 2/3 visible-label association coverage and 0/2 associated centers within
the approximate per-axis tolerance assumption; its identity continuity is not
accepted. This historical comparison is not reproducible as a scoring result
until exact decoded-crop raster correspondence is proven. The evaluator command
is `uv run python scripts/maintenance/evaluate_vta304_crop_diagnostic.py --run <run-dir>
--fixture tests/fixtures/player_identity_observation_vta304_round4.json --output <result>`;
it hashes all inputs and returns `pending_raster_binding` rather than scoring a
frame whose decoded crop hash differs or is absent. The uncertain gold samples
at 300.0167s and 300.0333s have no scored half-second prediction. These sparse labels cannot establish player identity accuracy,
full-round visibility coverage, identity-switch rate, map calibration, or
VTA-304 acceptance. Do not use these predictions as canonical player tracks.

## VTA-304 canonical run export

`tracking.run_export.export_player_track_run` accepts already-assigned
`TrackSmoothingInput` and `SmoothedTrackSample` values plus an explicit known
roster, match/map/round IDs, complete existing `RunManifest`, source SHA-256,
and canonical map image. It writes `runs/<run_id>/player_tracks.parquet`,
stable-ID timestamped debug PNGs, the existing `runs/<run_id>/manifest.json`,
and typed `player_tracks.binding.json`. Readback now requires both
`expected_manifest_sha256` and `expected_binding_sha256`, independently supplied
SHA-256 pins over the exact manifest and binding file bytes. Since the pinned
binding commits the Parquet digest and run context, coherent replacement of the
Parquet plus a rewritten sidecar does not pass the original pins.

The adapter rejects empty inputs, anonymous/unknown track IDs, missing roster
metadata, mixed round/context, incomplete provenance, source-hash mismatch,
unsafe or symlinked paths, duplicate player/timestamp keys, inconsistent raw
and derived row payloads, and repeated destinations. Reader metadata and
Parquet bytes are read through no-follow file descriptors; Parquet is hashed
and decoded from the same in-memory payload. Optional PyArrow is checked after
pure request validation and before outputs are created. Failed exports clean
only paths after successfully acquiring a new run directory, so a competing
creator's directory and contents are left intact.
The integration test uses explicit synthetic identity-bearing inputs to prove
the persisted interface; the anonymous-round runner is not converted into
real-player data. Real map registration, reviewed source labels, matched real
tracker predictions, and real-player accuracy/coverage/switch metrics remain
required for VTA-304 acceptance.
