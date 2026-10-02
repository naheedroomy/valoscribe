# MVP-002 real-source candidate run (not accuracy acceptance)

This report records one offline run over five manually configured, partial Ascent attack-round intervals. It does not claim marker precision/recall, a validated team-shape result, full-round coverage, or completion of the MVP. Generated video/JSON artifacts are ignored under `.local/` and were not committed.

## Source and intervals

- Source identifier: `YTDown.com_YouTube_Media_4LEGEQ8KBS0_100T-vs-LOUD-VCT-Americas-Stage-2-Playoffs-Grand-Final-Map-3-Ascent_001_1080p.mp4`.
- SHA-256: `a2feb25b842b6c1c2baa17f8ef0c5ecfe1816bd058a1c256350fa95900454c44`; 1920×1080, 60 fps.
- Selected team/side: 100T attack in the reviewed first-half broadcast segment; source-specific only.
- Source interval IDs: R4 263–330, R5 379–420, R6 540–600, R7 790–870, R9 971–1020 seconds. R9 971–975 replay/transition frames are explicit `excluded`; first live frame is t=975 (timer 1:39). Each opening window uses the first 8 usable seconds. None of the intervals is claimed to be a complete round.
- Sampling: 4 Hz; candidate HSV ranges H0–15 and 165–179 with S,V≥100; components area 12–180 px, confidence≥0.5, circularity≥0.2. These parameters were adjusted after inspecting real-source frames, not validated against an annotated ground-truth set.

## Run and observed output

- CLI commands run:
  - `uv run python -m valoscribe tactical inspect --config .local/configs/ascent-team-movement-mvp001.yaml`
  - `uv run python -m valoscribe tactical analyze --config .local/configs/ascent-team-movement-mvp001.yaml`
- Exact final run directory: `.local/runs/ascent-team-movement-mvp002-r3/`.
- Project commit recorded in manifest: `2819edc` (`feat: add offline tactical inspect and analyze workflow`).
- Candidate samples: 1,188 total; 1,162 `partial` (positive but unreviewed candidates), 10 `unknown` (zero candidate detections), 16 `excluded` (R9 replay/transition).
- Raw candidate observations: 5,496 total; per interval R4 1,625 / R5 742 / R6 1,201 / R7 1,347 / R9 581. These are detector candidate counts, not true-player detection counts.
- Pipeline processing time reported: 35.21 seconds (source hashing/opening and pre-run inspection are outside this timing); peak process RSS: 745,635,840 bytes; run artifact size: 50,754,706 bytes.
- Each round directory contains compact raw observations, a per-sample coverage timeline, JSON summary, minimap playback, and canonical-map playback. Run calibration contains crop/transform contacts and the Ascent zone overlay. The manifest includes hashes, dimensions, commit, sample rate, versions, and artifact paths.

## Manual output inspection and detector limits

Inspected beginning/middle/end plus the known R4 overlap/banner and R5 bright-obstruction frames in `.local/runs/mvp001/calibration/mvp002-r3-playback-contact.jpg`; inspected canonical overlays in `.local/runs/mvp001/calibration/mvp002-r3-canonical-contact.jpg`. Source crop evidence is `.local/runs/mvp001/calibration/revised-five-interval-crop-contact.jpg`; R9 replay/start timing evidence is `.local/runs/mvp001/calibration/r7-r9-exact-live-gaps.jpg`.

Visual playback shows usable minimap candidate positions, but also obvious extra color components at non-team/minimap-detail locations and intermittent misses. R4 averages about 6.1 candidates per sample despite a five-player roster; R9 averages about 3.0 and has two zero-candidate samples. These discrepancies are warnings, not a measured false-positive/false-negative count: there is no reviewed per-frame annotation set, so precision/recall and exact FP/FN counts are unavailable. All positive samples remain `partial`; zero candidates remain `unknown`. No absence, death, identity, or intent inference is made. The canonical display still depends on approximate affine and zone geometry.

## Validation commands

- `uv run pytest`: 1,205 passed, 1 skipped.
- `uv run pytest -q tests/test_tactical_mvp.py`: 7 passed.
- `uv run ruff check src tests`: passed.
- `uv run mypy src/valoscribe`: passed.
- `git diff --check`: passed.

## Remaining bounded work

- MVP-003: human marker correction workflow, immutable correction deltas, and corrected downstream rebuild.
- MVP-004: zone occupancy timelines and cautious deterministic per-round/aggregate movement summaries.
- MVP-005: review/correct the actual five rounds, document representative evidence and unknowns, and complete user acceptance.

The detector is not accepted as useful team movement yet. Parent-agent review of candidate geometry is not human/user approval or official map geometry; user final review remains pending.
