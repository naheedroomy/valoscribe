# Correcting minimap candidates

MVP-003 keeps raw detector output immutable. Review changes are appended to each round's `corrections.jsonl`; explicit frame-review records (including frames reviewed with no changes) go to `reviewed_frames.jsonl`. Reviewer records mean only that the frame was inspected; they do not certify player identity, detector accuracy, or official map geometry.

## Review controls

```bash
uv run python -m valoscribe tactical review \
  --run-dir .local/runs/<run-id> \
  --round-id map3-round4 \
  --reviewer <reviewer-label>
```

The OpenCV reviewer shows the source minimap crop, sampled timestamp, round, current corrected markers, confidence, and stable observation-ID suffixes. Controls:

- Left/Right arrows or A/D: previous/next sampled frame.
- Left click an existing marker: select it; click an empty map location: add a marker.
- Delete, Backspace, or `.`: remove the selected raw marker. Moving is performed as remove then add.
- `S`: append staged deltas and an explicit frame-review record, even if no changes were staged.
- `Q` or Esc: quit without saving staged changes.

The `* UNSAVED` indicator is shown while deltas are staged. Raw observations are never edited. Deltas include run/round/sample, operation, stable target observation ID and original position when applicable, corrected position, reviewer, note, and timestamp. Invalid target IDs, mismatched original positions, invalid round IDs, and out-of-map corrected coordinates are rejected.

## Rebuild

```bash
uv run python -m valoscribe tactical rebuild \
  --run-dir .local/runs/<run-id> \
  --round-id map3-round4
```

Without `--round-id`, all configured rounds are rebuilt. Each invocation creates a new `rounds/<round-id>/derived/revision-NNN/`; existing revisions are not overwritten. The revision contains corrected observations, per-sample CSV and Parquet occupancy (zone/macro counts, centroid, spread and coverage), corrected minimap and canonical playback, and a revision manifest with the raw-file SHA-256 and `detector_invoked: false`. The source is decoded only at already sampled timestamps for corrected playback; marker detection is not run. Install the existing optional Parquet dependency with `uv sync --extra parquet` if it is unavailable.

Unreviewed candidate-positive samples remain `partial`; zero-candidate samples remain `unknown`. A sample becomes `good` only after it has an explicit reviewer record, including a reviewed zero-marker frame. This is reviewer-confirmed evidence for that frame, not a claim that all team members are visible. MVP-003 emits occupancy features only; tactical opening/shift summaries remain MVP-004.
