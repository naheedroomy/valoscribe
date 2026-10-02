# Current State and Full-Run Readiness

## Executive assessment

**The code can produce an offline round-analysis report and can optionally call a configured OpenAI-compatible model, but it has not completed a genuine real-VOD HUD-to-report run.** The recent real Ascent round-4 work decoded and diagnosed a bounded minimap clip; it deliberately did not attempt HUD extraction. The resulting report correctly says that tactical behavior is unknown because there are zero accepted HUD events. A separate live-provider request succeeded only on a synthetic HUD fixture. Neither is evidence of a working end-to-end real tactical analysis.

The immediate blocker is not LLM capability. It is the lack of a calibrated HUD profile for this broadcast and source-backed match metadata. Then the generated real HUD events still need source/timing validation. The minimap and player-tracking results remain anonymous, unregistered, and unvalidated. Start with a narrowly scoped, evidence-backed real HUD round; do not hold that first useful milestone hostage to perfect tracking, exhaustive hand labels, or a full tactical analyzer.

This report is based on the checkout docs/code and the existing local artifacts. No code or product behavior was changed, no credentials were read, and no new API request or full test suite was run for this report.

## Product goal and scope boundary

`PROJECT_SPEC.md` describes the long-term product: offline analysis of professional spectator VODs, combining Valoscribe's round/HUD data with minimap movement, spike and supported utility evidence, round timelines, scenario analysis, and evidence-linked reports. An optional LLM explains bounded structured evidence; it is not the detector and must remain disabled by default.

VTA-704 is a deliberately smaller slice: inventory supported events from one explicitly scoped HUD round, keep anonymous minimap diagnostics as availability metadata only, and optionally obtain cited tentative hypotheses/coaching suggestions. It does **not** claim to reconstruct tactics from the diagnostic or establish team tendencies from one round. `docs/PROJECT_STATUS.md` likewise distinguishes code/tests, synthetic verification, and real-source acceptance; the numbered issues remain incomplete where real acceptance gates are open.

“Full run” needs to be kept precise:

1. **Minimum real round end-to-end:** real video → calibrated HUD extraction → reviewed event/timestamp scope and metadata → VTA-704 report → one explicit opt-in live LLM request on that real evidence.
2. **Full VOD processing:** process a complete map video and retain event output, rather than a short reviewed interval.
3. **Full tactical analyzer:** validated player/map identities, movement and relevant utility/spike reconstruction, fusion, useful scenario analysis, and evidence-backed reporting, followed by multi-round and multi-VOD review.

Only synthetic report/provider mechanics and an anonymous real-video minimap diagnostic are evidenced now. None of the three levels has been accepted as a real tactical analysis run.

## Capability and evidence status

| Area | Present and verified | Real-source status / blocker |
|---|---|---|
| Legacy Valoscribe | Existing `orchestrate process-vod` accepts a video, metadata JSON, optional HUD config, and outputs event/state data. | This recent attempt did not run it: the candidate HUD profile has no required regions, and usable source-backed metadata was absent. Existing legacy tournament coordinates must not be reused unless demonstrated compatible with this exact source. |
| Round-analysis contracts/CLI | `round-analysis run BUNDLE --output-dir DIR` validates bounded input and writes JSON + Markdown; output creation is non-overwriting. Default is deterministic/offline. | Real VOD bundle has `hud_source: null`, so output has 0 HUD facts and truthfully reports unknown behavior. The code can consume real upstream event JSONL once a reviewed bundle/source exists; it does not itself extract that log. |
| Provider | Fake/injected-provider path and schema/failure behavior have tests. Optional configured OpenAI-compatible path is opt-in. | One paid live call returned HTTP 200/`finish_reason=stop` on a **synthetic** example: 1 hypothesis and 1 recommendation. It did not process real VOD evidence. Cost and token receipt: prompt 610, completion 504 (reasoning 357), total 1,114 tokens; one request. This proves transport/schema execution for that test only—not useful real analysis, cost at scale, or product value. Do not repeat this request merely to confirm it. |
| Reasoning configuration | Existing provider settings cover enablement, provider, credentials, endpoint/model, timeout, retries, temperature, image-upload permission, and usage logging. | Current integrated settings/request do not expose the `reasoning=xhigh` option used by the separately reported live test. Treat that as a small integration/configuration gap only if the intended model requires it; the successful one-off request is not evidence that the CLI can set it. |
| Real minimap diagnostic | Real source bytes were decoded across reviewed frames with provenance and debug artifacts. | Diagnostic only: 4,921/4,921 decoded frames over 82.0167 seconds; 1,002.51 seconds runtime (~17 minutes); 1.9 GiB artifact storage and 5,364,776,960 bytes (~5.0 GiB) peak process RSS (reported run measurements). 329,997 candidates (126,138 accepted / 203,859 rejected), 557 anonymous samples/tracklets, 4,898 frames without a sample, association confidence 0 throughout. No player identity, canonical coordinates, or quality metric. This is not successful player tracking or tactical evidence. |
| Tests/static checks | Current recorded repository result: 1,198 tests passed, 1 skipped; Ruff clean; mypy clean for 125 files (reported checks). | Synthetic/unit success verifies code mechanics, not real VOD correctness. These counts are recorded from the task context, not rerun in this reporting task. |
| Release/publication | Worktree is on `main` at `6fb42d6e9db2d7969723eb3cd1e154dae6cf0846`, tracking `origin/main`. | Worktree is broadly dirty with substantial uncommitted changes. Do not infer that the local VTA work is committed, pushed, or published. Project publication rules require checking an actual commit and its allowed files. |

## What happened on the real round attempt

Source context identifies the local 100T–LOUD VCT Americas Stage 2 Grand Final map 3 Ascent VOD, round 4, with a SHA-256 digest and reviewed interval: frames 15,600–20,520, PTS 3,993,600–5,253,120, timebase `1/15360`, timestamps 260–342 seconds.

The candidate profile `src/valoscribe/config/ascent_vct_americas_2026_stage2_final_1080p_candidate.json` is explicitly `calibration_status: pending`; it has a minimap crop but `regions: {}`. The compatibility artifact names the missing legacy orchestrator regions: `round_number`, `team1_score`, `team2_score`, `round_timer`, `killfeed`, and `player_info`. Consequently HUD extraction was **not attempted**, correctly avoiding guessed production crop coordinates. No matching source-backed metadata/roster/team-side/agent map was found, and unrelated `champs2025.json` coordinates were not treated as compatible.

The generated `round-analysis-bundle.json` has `hud_source: null` and one diagnostic reference. The real-run report therefore has zero round samples, zero event sources, zero HUD observations, no hypotheses/recommendations, and explicitly says behavior is unknown. This is the correct result for unavailable evidence, not a failed report-generation command.

The minimap run is valuable as a reproducible diagnostic and provenance trail, but its values must not be described as detection/tracking quality or movement: 4,898 frames are unknown-context and unobserved for tracklets; anonymous IDs are ephemeral; crop-space coordinates are not registered map coordinates; player identity is unavailable; association confidence is 0. Independent ground truth is absent.

## Current path through the code

**Implemented VTA-704 path:** local typed bundle → optional bounded local HUD event JSONL validation → deterministic facts only for supported HUD event types → optional model selection of known fact IDs and bounded tentative claims → locally resolved citations → non-overwriting JSON/Markdown output. Diagnostics are metadata, never converted into player, side, formation, movement, or strategy facts. The model does not supply observation text.

**Desired real first path:** actual VOD + compatible, reviewed source-specific HUD profile + validated metadata → real legacy HUD/round event log → reviewed event scope, timestamps, and clock domain → bundle referencing that exact log and optional diagnostic → deterministic real round report → one opt-in live call against its bounded facts → analyst checks output claims against source.

**Still missing between them:** calibrated crops and evidence that their outputs are right; source-backed match/map/round/player/team/side metadata; and one real event log with matching bounds/clock evidence. The current round-analysis CLI consumes the log; it does not create it. The anonymous diagnostic runner is a separate path and does not fill those gaps.

## Ordered readiness plan

### 1. Calibrate the actual broadcast HUD first

Obtain a source-bound crop review for this VOD/profile, especially timer, round number/score, killfeed, and player HUD; document source frames, dimensions, crop measurements, and reviewer/provenance. Validate the existing candidate minimap crop separately. Populate only measured regions in the appropriate HUD configuration and mark calibration status accurately. Reuse an existing legacy profile only after direct evidence establishes the same layout/crop compatibility. Do not invent or copy coordinates from another tournament.

**Gate:** a second person can inspect the source frames/crops and agree that each needed field is reading the intended HUD element. Capture ambiguous/unsupported fields as unavailable rather than guessing.

### 2. Supply source-backed metadata and clock/scope mapping

Provide the local metadata required by `process-vod` (`teams` and `players` are checked by the command), plus verified match/map/round identifiers and source timing. Record any mapping between source-video time/PTS and event-log time as evidence; do not silently equate VOD seconds, game clock, frame index, and PTS. Resolve teams/sides from match/half/overtime evidence, never permanent broadcast color. A reviewed local metadata file is enough for this first test; a network metadata fetch is not required.

**Gate:** metadata and round scope reconcile with the selected source/map/round, and all event timestamps remain in their declared clock domain.

### 3. Run the smallest reproducible real HUD extraction

Use the existing `orchestrate process-vod` CLI with its actual video, metadata, HUD config, output, and time-bound options (see verified command interface below). Begin with the reviewed round interval. Preserve the raw JSONL/event output and extraction logs; note the exact code/config/source hashes and run settings. Check that useful expected HUD events appear and that failures/abstentions remain visible. Do not call this a complete accepted HUD detector solely because files were emitted.

**Gate:** manually reconcile a modest set of timestamped events—at minimum the round boundaries and available event types—against source frames, recording misses, false detections, identity uncertainty, and timing offset. This is a bounded source review, not exhaustive frame-by-frame labeling or a full benchmark. Keep remaining quality limitations explicit.

### 4. Make and run a real VTA-704 bundle offline

Build a bundle with the matching match/map/round, real `hud_source`, event-log path, declared clock and inclusive reviewed bounds/reference; attach the real diagnostic only as availability metadata. Run with a **new empty output directory** (the CLI never overwrites its JSON/Markdown pair). The output should have nonzero supported observations only if the log contains them, correct line/timestamp citations, clear coverage/unknowns, and no claims from anonymous tracklets. Inspect each report observation against its cited source event/frame before calling the real-round inventory useful.

**Verified report command pattern:**

```bash
uv run python -m valoscribe round-analysis run \
  /path/to/reviewed-real-round-bundle.json \
  --output-dir /path/to/new-round-report-dir
```

The local example command uses `docs/vta704-example/round-analysis-bundle.json`, but its events are synthetic; it must not be represented as a real run. The recent real output directory's report is also available at `/private/tmp/vta-real-round4-analysis-c48od6/round-analysis-output/round_analysis.md` and `.json`.

### 5. Only then perform one live opt-in call on real facts

Keep LLM disabled by default. When the offline real report has been source-checked, explicitly opt in with `--enabled` and the existing documented environment configuration (`LLM_ENABLED=true`, configured model/provider credentials/settings); never put a key in a command, report, log, bundle, or artifact. First confirm the intended model/API supports the provider's structured-output schema. If `reasoning=xhigh` is a requirement, expose/configure that intentionally in the integrated provider before expecting the CLI to reproduce the separately observed one-off request. Keep image upload disabled; the round analyzer sends structured bounded facts, not video/images. Compare model claims with cited evidence and discard unsupported or generic output; citation membership alone does not establish semantic support or causality.

**Gate:** one real-source request completes with accepted schema and locally resolved citations, produces no invented identities/timestamps/events, and offers demonstrably useful suggestions to an analyst. A 200 response alone is not this gate.

### 6. Extend to full VOD, then movement/tactical analysis

After a bounded round is reproducible, run full-map VOD extraction with validated config and metadata; track coverage, runtime, failures, and event denominators rather than extrapolating from the 82-second diagnostic. Separately close real map calibration, player identity/continuity, side state, round phase/timeline, spike and supported utility gaps. Review a modest sample of outputs against source. Keep raw detections separate from derived tracking, preserve per-claim confidence/provenance, and keep unknowns explicit. Only after reviewed evidence exists should scenario filtering, cross-round aggregation, and tendencies be evaluated.

The long-range acceptance target is not one live API call. It is repeatable useful reports over independently reviewed rounds/VODs with honest sample denominators, source-backed citations, analyst-confirmed claim correctness/usefulness, and no unsupported team/side or causal claims. Thresholds should be agreed with reviewers before claiming acceptance, not invented in this report.

## Exact CLI and artifact references

The real extraction command exists as `valoscribe orchestrate process-vod VIDEO METADATA` with `--output/-o`, `--config/-c`, `--fps/-f`, optional `--start`, `--end`, `--quiet`, and diagnostic flags. Its implementation requires metadata `teams` and `players`. An exact ready-to-copy invocation is intentionally not supplied because the compatible calibrated profile and source-backed metadata do not yet exist. The minimap runner's reviewed-input requirements and sample schema are documented in `docs/anonymous-round-runner.md`; its zero/one frame bounds are explicitly schema examples, not production values.

Important local evidence:

- `/private/tmp/vta-real-round4-analysis-c48od6/run-context.json` — source hash, reviewed bounds, candidate/legacy profile compatibility, metadata absence, and explicit reason no HUD extraction was attempted.
- `/private/tmp/vta-real-round4-analysis-c48od6/hud-compatibility-check.json` — candidate profile is incompatible; no HUD extraction attempted.
- `/private/tmp/vta-real-round4-analysis-c48od6/round-analysis-bundle.json` — actual diagnostic-only bundle with `hud_source: null`.
- `/private/tmp/vta-real-round4-analysis-c48od6/round-analysis-output/round_analysis.md` and `.json` — actual empty-evidence real-source report.
- `/private/tmp/vta-e2e-round-review/round4-diagnostic-run/vta404-ascent-map3-round4-diagnostic-r1/report.md`, `diagnostic_report.json`, `manifest.json`, provenance sidecars, raw observations, tracklets, and replay — bounded anonymous diagnostic and reproducibility artifacts.
- `/var/folders/p9/nptz9rfx1xb7qpbjr2_d83x00000gn/T/vta704-live-test-9tw__7tn/round_analysis.md` and `.json` — actual synthetic-input live-provider response; not real VOD results.
- `specs/vta704-round-analysis-spec.md`, `specs/vta704-round-analysis-plan.md`, `docs/vta704-round-analysis.md`, `docs/vta704-example/` — VTA-704 contract, design, command usage, and synthetic examples.
- `docs/PROJECT_STATUS.md`, `PROJECT_SPEC.md`, `AGENTS.md` — project acceptance boundary, product source of truth, and no-guessed-coordinates/evidence rules.

## Bottom line and first action

The report-generation seam and optional provider path exist. The real evidence-generation seam is blocked. The first high-value next action is **source-backed HUD crop calibration for this broadcast, together with verified round metadata**, then a bounded extraction and source reconciliation. That unlocks a real deterministic report before any paid model call. The current successful synthetic live call is a plumbing check; it is not the requested real-VOD run or evidence of tactical-analysis readiness.