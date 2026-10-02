# One-round E2E diagnostic slice — VTA-404

## Scope

Wrap the existing `run_anonymous_round` runner with an opt-in offline CLI. It accepts reviewed inclusive frame/PTS bounds and only genuinely reviewed context samples. It emits raw candidate/tracklet artifacts, a typed JSON/Markdown summary, and crop-space playback. Anonymous tracklets are not confirmed players; crop coordinates are not canonical map coordinates. No team, side, or tactical claims are supported.

Keep detector and association policy unchanged. Do not add identity, map registration, tactical interpretation, tuning, UI/dashboard, or unrelated changes. Preserve existing dirty worktree changes.

## Milestones

1. Inspect runner/contracts and relevant tests; record affected baseline.
2. Add CLI/report/replay integration. Reject incompatible source cadence, invalid evidence, collisions, unavailable Parquet, or incomplete output. The sibling lock coordinates cooperating CLI instances; do not claim atomic exclusion against unrelated concurrent writers.
3. Add synthetic focused tests for integration, rendering, validation, and failure paths.
4. Review exact inclusive round bounds against the source PTS inventory. Context rows are optional; omitted frames remain unknown. Do not infer timestamps from nominal FPS or invent review context.
5. Run focused and repository pytest, Ruff, and mypy checks. Record the real-input blocker and next artifact.

## Acceptance

- Existing detector and association policy remain unchanged. Debug markers use crop-bounded short IDs; the replay panel maps them to full IDs and confidence.
- Typed report includes provenance, exact source bounds, context classification, candidate and tracklet counts, confidence/gaps, artifacts, and unavailable identity/map/quality claims.
- Replay is restricted to complete contiguous CFR windows. Every adjacent source PTS delta must match the exact FPS/timebase period. It lists every raw candidate and tracklet sample without truncation, warns about unknown context/gaps, and makes no identity or map claims.
- Final MP4 must decode through EOF with matching frame count, dimensions, frame rate, and `frame_count / fps` duration. The final source frame is displayed for one CFR period.
- Contact sheets show global frame index and exact inventory PTS/time and stay outside Git. Do not claim a real-round run or VTA-404 acceptance without reviewed bounds.

## Evidence and remaining work

The source is `../VOD/YTDown.com_YouTube_Media_4LEGEQ8KBS0_100T-vs-LOUD-VCT-Americas-Stage-2-Playoffs-Grand-Final-Map-3-Ascent_001_1080p.mp4`. Full ffprobe inventory: 201,799 frames, 1920×1080, 60/1 fps, timebase 1/15360. Review sheets at `/private/tmp/vta-e2e-round-review/contact-sheet-1.jpg`, `contact-sheet-2.jpg`, and `contact-sheet-3.jpg` sample 240–380s every five seconds. They show both live play and camera/interstitial cuts but do not establish exact full-round limits. Sparse Round 4 observations are not round bounds or full-round ground truth. The real runner has not been invoked.

Independent bounds review is required next. Provide the exact start/end frame indices and PTS, plus only the context frames that were actually reviewed. Sparse context is acceptable but produces tracklets only across adjacent live-reviewed frames; all omitted context remains unknown. The guarded command template is `/private/tmp/vta-e2e-round-review/run-reviewed-round4.sh`; it refuses to run until `/private/tmp/vta-e2e-round-review/round4-reviewed-input.json` exists.

A synthetic-only final 120-frame pilot (64×64 source/crop) ran the runner, artifact readback, and replay in 0.720s. It wrote 120 debug PNGs (336,017 bytes) and an 831,560-byte information-panel replay; process peak RSS was 140.22 MiB. Results are not real-source performance evidence. Pilot artifacts are in `/private/tmp/vta-e2e-correction-final-pilot-ybvtnh16/resource-pilot.json`.

## Real-source bounded diagnostic run (2026-10-02)

The guarded command `/private/tmp/vta-e2e-round-review/run-reviewed-round4.sh` completed once without code/config tuning against the directly reviewed manifest and the actual source. Input scope remains frames 15600–20520 inclusive (PTS 3993600–5253120; 82.0167 s): it brackets Round 4 with a short buy-phase lead-in and round-end tail, but is not the exact whole buy phase or final gameplay boundary. Only 23 individually reviewed frames were live; all other frames remain unknown. The original source and configuration remain as candidate diagnostic inputs, not validated production settings.

- Runtime: 1002.51 s elapsed (user 2561.95 s, system 390.87 s); peak RSS 5,364,776,960 bytes; zero swaps.
- Output root: `/private/tmp/vta-e2e-round-review/round4-diagnostic-run/vta404-ascent-map3-round4-diagnostic-r1/` (kept outside Git). It contains 4921 debug PNGs plus 4921 provenance sidecars, `raw_observations.jsonl` (4921 frame rows; 329,997 candidates: 126,138 accepted and 203,859 rejected), `anonymous_tracklets.parquet` (557 rows), `anonymous_run.json`, typed JSON/Markdown reports, and `anonymous_minimap_replay.mp4`.
- Run report: 4921/4921 source frames decoded; context 23 live / 0 nonlive / 4898 unknown; 4898 frames have no tracklet sample. There are 557 observed tracklet samples/labels, each effectively an isolated diagnostic sample: association confidence is 0.000 throughout, so do not treat these as player continuity. Detector confidence range is 0.046–0.886.
- Replay EOF validation: ffprobe counted 4921 frames at 60/1 fps, 1040×7154, duration 82.016667 s; full ffmpeg decode to null exited successfully (3.79 s). Three unmodified replay PNGs for parent inspection: `/private/tmp/vta-e2e-round-review/round4-diagnostic-run/replay-inspection-frames/replay-frame-01.png` (first), `replay-frame-02.png` (middle), and `replay-frame-03.png` (last).
- This is a successful real-source diagnostic integration run only. Identity, reliable cross-frame continuity, canonical map coordinates, detection/tracking quality, tactical claims, exact whole-round bounds, and overall VTA-404 acceptance remain pending. No player-absence inference can be drawn from unknown frames or missing samples.

The candidate crop is 360×400, or 432,000 raw pixel bytes/frame. Budget roughly 433 KB/frame for retained PNG bytes before Python/container overhead: about 25.98 MB/s at 60 fps, or 1.56 GB/minute. Measure a bounded representative real crop before a full-round run. HUD crop/profile and map applicability are unvalidated. VTA-404 and the full objective remain pending real-input review and acceptance.
