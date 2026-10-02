> **Archived:** Historical material retained for provenance; it is not current implementation guidance. Use the [active MVP Reset specification](../../specs/active/MVP_RESET_AND_REPOSITORY_CLEANUP_SPEC.md).

# Anonymous tracking provenance foundation

## Scope and current gap

`RunManifest` records broad run metadata, but the existing Parquet helpers and artifact readers do not bind an artifact to a canonical manifest digest, the actual source-video bytes, or the configuration file contents. The artifact layer accepts standalone rows/files and therefore cannot detect cross-run reuse or later payload/config changes. This new seam is additive; it does not change the legacy `RunManifest` contract or player-track output.

The missing binding is addressed by `TrackingRunManifest`, per-frame `TrackingObservationProvenance`, and manifest-bound artifact sidecars. Manifests use canonical finite JSON SHA-256, are immutable once written, and are checked against caller-expected run/source/config values. Observation and artifact boundaries revalidate Pydantic objects to catch `model_copy` and mutable nested-data bypasses. Artifact readers also re-read and digest-check the persisted manifest and verify payload checksums and artifact kind.

## Contract and API

- `valoscribe.types.tracking_provenance.TrackingRunManifest`: complete safe run ID; source path and actual source SHA-256; dimensions; rational FPS and source timebase; map ID, positive match map ordinal, round plus explicit frame, PTS, and timestamp bounds; HUD/color/map config IDs, filenames, individual content SHA-256 and canonical aggregate config SHA-256; map asset SHA/version; project/upstream commits and code fingerprint; detector/tracker versions; optional annotation version; UTC start and schema version.
- `valoscribe.types.tracking_provenance.TrackingObservationProvenance`: run ID, manifest/source/config digests, map ID and positive match map ordinal/round, source frame index/PTS, exact rational timebase, and timestamp. `validate_observation` rejects any mismatch and derives timestamp only from source PTS × timebase, never from nominal FPS.
- `valoscribe.types.tracking_provenance.TrackingArtifactBinding`: kind, safe relative path, payload digest, run ID, and manifest digest; persisted separately as a `.provenance.json` sidecar to avoid circular manifest hashing.
- `valoscribe.tracking.provenance.local_file_sha256(path)`: hash local regular-file bytes, rejecting symlinks.
- `local_content_tree_sha256(root, relative_paths)`: canonical fingerprint of actual selected local code/config bytes and relative paths, including dirty/uncommitted content.
- `canonical_sha256(value)` and `canonical_config_sha256(hud, color, map_config)`: canonical content digests; config aggregation binds actual file digests, not filenames alone.
- `write_tracking_manifest` / `read_tracking_manifest`: immutable manifest creation and expected run/source/config validation.
- `validate_observation` / `validate_observation_rows` / `write_observation_jsonl`: exact per-row checks before JSONL output is opened.
- `write_bound_artifact` / `read_bound_artifact`: generic binary, visualization, or Parquet payload registration/reading with expected artifact kind, payload digest, manifest digest, run/source/config, and path safety checks. The run manifest must already be persisted and byte-canonically match the supplied manifest.

All paths in artifact helpers are relative to `runs/<run_id>`; absolute paths, traversal, and symlinks are rejected. Supplied filesystem paths must use their trusted canonical spelling (for example, pass `tmp_path.resolve()` in tests); symlink components anywhere from the filesystem root, including ancestors of supplied roots, are rejected rather than resolved. Checks cover the complete path at API boundaries, but this offline single-process interface assumes a trusted canonical path spelling and trusted directory; it does not guarantee safety against concurrent malicious filesystem substitution and does not use descriptor-anchored no-follow operations. Invalid JSONL preflight leaves no output. Artifact registration preflights both complete output paths and existing destinations before creating the payload. Payload and sidecar are separate atomic file creations, not a two-file transaction; if sidecar creation fails after payload creation, cleanup attempts to remove the payload. Existing artifacts and manifests are never overwritten.

## Integration and evidence limits

This is a provenance foundation only. There is no anonymous round runner yet, no source decoding in this change, and no modification to legacy Parquet readers, CLI, assignment, or output formats. The source metadata noted for future work is 1920×1080, 60/1 FPS, timebase 1/15360; it is not validated against production footage in this slice. Do not claim that all real output rows are provenance-bound or that provenance validation establishes CV quality. The next anonymous runner should hash local source/config/map bytes, construct the complete manifest from measured source metadata and independently supplied round bounds, attach `TrackingObservationProvenance` to every raw frame observation, retain raw detections separately from derived tracks, and register every emitted artifact through the bound-artifact API. Real-round annotations and benchmark acceptance remain separate gates.
