> **Archived:** Historical material retained for provenance; it is not current implementation guidance. Use the [active MVP Reset specification](../../specs/active/MVP_RESET_AND_REPOSITORY_CLEANUP_SPEC.md).

# Anonymous diagnostic round runner

`run_anonymous_round` is an additive, offline diagnostic API. It does not modify the legacy CLI or player-track schema and does not make production-validated claims. Invoke it with explicit `mode="diagnostic_only"` (or synthetic test mode), a locally generated source video, externally reviewed inclusive frame/PTS bounds, actual HUD/color/map config files, and the map asset named and hashed by the map config.

The runner streams the complete source with `SequentialPtsVideoSource`, verifies every decoded frame, and refuses final output unless EOF/frame-count/process/source checks pass. Round times are derived from observed integer PTS and rational timebase, never nominal FPS. The caller supplies externally reviewed live/nonlive context per frame; omitted context is unknown and clears tracklets. The existing side-agnostic `MinimapColorCandidateDetector` preserves accepted and rejected candidates; detections and tracklet coordinates are normalized only within the configured crop. Broadcast-color compatibility is only an appearance cue. Tracklet IDs are ephemeral run/map/round-scoped labels, not player, agent, team, or side identities. There is no smoothing, interpolation, prediction, alive inference, map registration, or tactical-zone mapping.

Diagnostic association thresholds are explicit and configurable, with defaults in `AnonymousRunnerThresholds`; they are not validated for production. Metrics are typed as unavailable until independent reviewed ground truth is supplied. The wrapper manifest retains the frozen `TrackingRunManifest` digest and typed FFmpeg/ffprobe, BGR24, and timestamp provenance; raw and derived rows carry the wrapper-payload digest. Raw accepted/rejected candidates are JSONL, anonymous tracklets are Parquet, and each debug overlay/manifest/data artifact has an immutable provenance sidecar. `validate_anonymous_rows` applies the same semantic preflight and consumer-readback checks: wrapper/shared-manifest digests, round/timebase bounds, reviewed live context, raw candidate frame/time/profile/source binding, accepted raw candidate references, coordinates, confidence, chronologically adjacent live evidence, association time/distance gates and derived confidence, and exact debug-overlay path/digest bindings. `read_anonymous_rows` verifies sidecars, semantic bindings, and the explicit versioned Arrow columns/types, including empty tracklet tables. Continuation checks index samples by tracklet and chronological frame, preserving the existing semantic checks without rescanning the entire sample table per row. Debug PNGs are read, sidecar-checked, and hashed incrementally rather than retained together in a second in-memory dictionary. The CLI reuses one validated raw/sample snapshot for its report and replay; replay verifies each overlay digest again as it consumes it. The dirty-code fingerprint includes the cropper, detector, raw/shared contracts, provenance validator/writer, runner, and artifact writer. Runner artifact paths are immutable; the CLI's output-root race guarantee is limited to cooperating callers using its sibling lock.

Parquet is required for certification. Install the existing optional dependency with `uv sync --extra parquet`; if `pyarrow` is unavailable, the runner fails before decoding and creates no output. No CSV fallback exists. Source hashing/decoding, configuration and asset reads, crop validation, detector execution, debug encoding, and immutable artifact writes are fail-closed boundaries: their errors abort certification rather than being silently ignored or caught broadly. Configuration parsing wraps only expected I/O, JSON, key, type, and Pydantic validation failures.

## Opt-in CLI diagnostic report and replay

`valoscribe minimap track-anonymous-round` wraps the runner and adds typed `diagnostic_report.json`, cautious `report.md`, and `anonymous_minimap_replay.mp4`. The reviewed input JSON has this shape; context rows may be omitted, and omitted context remains unknown:

```json
{
  "bounds": {
    "map_number": 3,
    "round_number": 4,
    "map_id": "ascent",
    "start_frame_index": 0,
    "end_frame_index": 1,
    "start_source_pts": 0,
    "end_source_pts": 1,
    "reviewer_id": "reviewer-id",
    "evidence_reference": "reviewed-source-frame-reference",
    "review_status": "externally_reviewed"
  },
  "context_by_frame": []
}
```

The `0`/`1` values above are schema-shape examples only, not production bounds. Supply local video, the actual reviewed manifest, HUD/color/map config and configured map asset, a new output directory, and project/upstream commit provenance. The command rejects existing outputs and uses a sibling lock to coordinate cooperating instances of this CLI. It builds artifacts in a temporary sibling directory and moves the completed run into a newly created output directory before printing success. It does not claim an atomic no-replace guarantee against unrelated processes creating destinations concurrently. Staging creation and later failures release the sibling lock and remove staging; a destination collision is not overwritten. The MP4 is crop-space debug-overlay playback, not full-screen video. Replay is deliberately restricted to a verified constant source cadence: every bounded source frame must be present and every adjacent integer PTS delta must equal the exact period derived from source FPS/timebase. Variable-cadence intervals are rejected before the replay file is created. The final source frame is held for one CFR frame period, so encoded duration is `frame_count / fps`, or source start-to-last PTS span plus one frame period. Each frame carries source frame index, integer PTS, exact rational timestamp, context and in-video warnings. Spatial short tracklet IDs map to readable full IDs and detector/association confidence in an adjacent information panel. Every raw candidate and every tracklet sample is listed and wrapped, not truncated. Unknown context is labeled as unreviewed only when its evidence is omitted; reviewer-assessed unknown remains distinct. Frames without a tracklet sample are labeled as unobserved; no interpolation is performed. The completed MP4 is decoded through EOF and its frame coverage, dimensions, frame rate, and duration are checked before publication.

The report lists source/config digests, exact reviewed bounds and context classification, raw accepted/rejected candidate and tracklet counts, confidence ranges, gaps/abstentions, and artifact paths. Unknown context includes omitted, unreviewed frames; it is not all reviewed. Player identity, canonical map coordinates, tactical claims, and quality metrics remain explicitly unavailable. This wrapper does not validate the candidate HUD crop, detector quality, or map geometry.

There is no accepted real VOD or independent ground truth in this slice. Real-run acceptance remains pending measured/approved HUD crop, map/config validation, and the later split of three development rounds plus two unseen validation rounds. Synthetic integration coverage proves mechanics only and cannot validate detection/tracking quality.
