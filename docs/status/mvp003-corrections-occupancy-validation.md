# MVP-003 corrections and occupancy validation

**Status:** implementation and bounded agent visual-review proof complete; no human/user acceptance claimed. This is not MVP-004 movement-summary acceptance or full MVP completion.

## Input and review scope

- Reused local five-round run: `.local/runs/ascent-team-movement-mvp002-r3/` (source SHA-256 `a2feb25b842b6c1c2baa17f8ef0c5ecfe1816bd058a1c256350fa95900454c44`; Ascent, 100T attack candidate profile; 4 samples/s).
- Existing selection remains partial intervals: R4 263–330, R5 379–420, R6 540–600, R7 790–870, R9 971–1020 seconds. R9 971–975 remains explicitly excluded. These are not complete rounds.
- Direct source crop at R4 t=263.00 was inspected at `.local/runs/mvp001/calibration/mvp002-r3-playback-contact.jpg` and decoded source crop `/tmp/review-r4-s0.jpg`. Three append-only deltas were recorded for R4 sample 0: one move, one removal of a crop-edge component, and one manually added candidate. The move/add positions reflect agent visual review only; whether the candidate markers are actually the selected players is unresolved. Reviewer value is `agent-visual-review-not-human-approval`.
- The frame was explicitly recorded in `reviewed_frames.jsonl`; only that one sample becomes `good`. All other positive candidates remain `partial`, zero-candidate samples `unknown`, and configured replay samples `excluded`.

## Rebuild evidence

- Ran `uv run python -m valoscribe tactical rebuild --run-dir .local/runs/ascent-team-movement-mvp002-r3` over all five intervals. No marker detector call occurs in this code path; each revision manifest records `detector_invoked: false`.
- Latest derived revision paths are `rounds/map3-round4/derived/revision-004/`, R5/R6/R7/R9 `derived/revision-002/` under the local run. Each contains corrected JSONL, occupancy CSV and Parquet, corrected minimap and canonical playback, and `revision.json`. Previous revisions are preserved.
- R4 revision has 268 frame rows, 1,625 corrected candidates, three correction deltas and one reviewed frame: 1 `good`, 267 `partial`. Other rounds retain their candidate counts and have no correction/review deltas: R5 164 frames/742 candidates, R6 240/1,201, R7 320/1,347, R9 196/581. R6 has 5 unknown frames; R7 3 unknown; R9 16 excluded and 2 unknown.
- R4 raw SHA-256 is `b7f8b04d3bcd51dc0135fd7a90650cd02880b673be18540c77e76c0eddff68aa` before/after; revision manifest records the same hash. Rebuild output sizes total 43,331,625 bytes (~41.3 MiB). All-round rebuild wall time was 98.834 seconds; peak RSS was not measured for this command.
- Five-round beginning/middle/end corrected minimap contacts were generated and directly inspected at `.local/runs/ascent-team-movement-mvp002-r3/calibration/mvp003-corrected-review-contact.jpg`. R9 opening visibly retains the explicit excluded label. This contact sheet is a candidate-output review aid, not human approval.

## Limits and next gate

- Candidate counts are not player counts or precision/recall. No identity, death, control, intent, or tactical claim is made.
- The correction proof is one R4 sample with agent-authored example deltas. The remaining four rounds are rebuilt but unreviewed; their positive samples remain partial.
- The map polygons and broadcast transform are approximate candidate geometry, not official/human-calibrated truth.
- MVP-004 remains: evidence-linked cautious opening/shift/commitment summaries. MVP-005 still requires human review and acceptance across five rounds, with at least five useful openings and three supported shifts/commitments before product completion can be claimed.
