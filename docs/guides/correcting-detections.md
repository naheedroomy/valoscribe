# Correcting minimap candidates

MVP-003 keeps raw detector output immutable. Review changes are appended to each round's `corrections.jsonl`; explicit frame-review records (including frames reviewed with no changes) go to `reviewed_frames.jsonl`. Reviewer records mean only that the frame was inspected; they do not certify player identity, detector accuracy, or official map geometry.

## Review controls

```bash
uv run --extra parquet python -m valoscribe tactical review \
  --run-dir .local/runs/<run-id> \
  --round-id map3-round4 \
  --reviewer <reviewer-label>
```

The OpenCV reviewer shows the source minimap crop, sampled timestamp, round, current corrected markers, confidence, and stable observation-ID suffixes. Controls:

- Left/Right arrows or A/D: previous/next sampled frame.
- Left click an existing marker: select it; click an empty map location: add a marker.
- Delete, Backspace, or `.`: remove the selected raw marker. Moving is performed as remove then add.
- `S`: append staged deltas and an explicit frame-review record, even if no changes were staged. `V` must be pressed to approve the currently displayed frame; inspecting it alone does not approve it.
- `X`: discard staged changes and restore the current frame to its last committed raw-plus-corrections state. Navigation remains locked while changes are unsaved.
- `Q` or Esc: quit without saving staged changes.

The `* UNSAVED` indicator is shown while deltas are staged. Raw observations are never edited. Deltas include run/round/sample, operation, stable target observation ID and original position when applicable, corrected position, reviewer, note, and timestamp. Invalid target IDs, mismatched original positions, invalid round IDs, and out-of-map corrected coordinates are rejected. `V` approves only the latest record for that sample; a later inspection record with `approved: false` revokes approval. Approval is rejected for excluded/unknown coverage or observations with missing canonical coordinates. A frame with zero approved markers is not proof that no team members were present.

## Source-level marker adjudication

For partial evidence, opt the round into fail-closed source adjudication, then append a source-backed disposition per effective marker instead of approving the whole frame. Use the stable observation ID shown by review output; the source timestamp and optional source frame must match the sampled evidence.

```bash
uv run --extra parquet python -m valoscribe tactical enable-source-adjudication \
  --run-dir .local/runs/<run-id> --round-id map3-round4
```


```bash
uv run --extra parquet python -m valoscribe tactical adjudicate-marker \
  --run-dir .local/runs/<run-id> \
  --round-id map3-round4 --sample-index 12 \
  --observation-id 'map3-round4:12:4' \
  --disposition supported --reviewer <reviewer-label> \
  --source-locator 'vod://source/frame/1234' \
  --source-timestamp-seconds 321.5 --source-frame-index 1234 \
  --confidence 0.9 --note 'marker visible in source'
```

Use `deferred` when ownership/visibility is ambiguous. Records append to `marker_adjudications.jsonl`; later records for the same stable ID supersede earlier dispositions without deleting history. The append API also records opted-in rounds in run-level `source_adjudication_mode.json`; if a listed round's sidecar is missing, rebuild fails closed instead of reverting to candidate counting. Presence of a sidecar, even empty, also opts that round into source-adjudication mode. Only supported effective markers (or an existing explicit whole-frame approval) affect tactical counts. Unreviewed/deferred candidates remain visible in corrected playback and corrected-observation output but are excluded from tactical features. Playback captions identify team/side, round, source time, RAW/CORRECTED/REVIEWED state, coverage, eligible/candidate counts, and named zones; green markers count as eligible evidence and orange markers remain deferred/unreviewed candidates. Supported partial evidence remains partial; a frame with no supported positions is unknown. Partial marker adjudication is never whole-frame approval or proof of absence. Moving/removing a marker creates/removes effective IDs; an old disposition never transfers to the moved ID, while historical adjudication records remain preserved.

## Rebuild

```bash
uv run --extra parquet python -m valoscribe tactical rebuild \
  --run-dir .local/runs/<run-id> \
  --round-id map3-round4
```

Without `--round-id`, all configured rounds are rebuilt. Each invocation creates a new `rounds/<round-id>/derived/revision-NNN/`; existing revisions are not overwritten. The revision contains corrected observations, exact adjudication and source-mode snapshots, per-sample CSV and Parquet occupancy (zone/macro counts, centroid, spread and coverage), corrected minimap and canonical playback, and a revision manifest with hashes for raw, coverage, correction, review and adjudication snapshots and `detector_invoked: false`. The source is decoded only at already sampled timestamps for corrected playback; marker detection is not run. Install the existing optional Parquet dependency with `uv sync --extra parquet` if it is unavailable.

In legacy candidate mode, unreviewed candidate-positive samples remain `partial`; zero-candidate samples remain `unknown`. In source-adjudication mode, only a whole-frame approval can retain `good`; partial supported evidence remains `partial`, and zero-supported samples are `unknown`. Source-supported count means observed supported markers, not the total team; these dispositions do not establish absence. Each new derived revision now includes a cautious per-round movement summary; aggregate summaries are published as immutable `aggregate/derived-revision-NNN/` snapshots. See [interpreting movement reports](interpreting-movement-reports.md) for exact rule thresholds and limits.
