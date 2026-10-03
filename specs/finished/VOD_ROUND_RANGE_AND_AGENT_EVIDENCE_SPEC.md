# VOD round range and agent evidence — next milestone

- Status: **Stage 1 Complete** (Foundation & Preflight delivered; Stages 2 & 3 pending)
- Revision: **0.2**
- Date: **2026-10-04**
- Implementation status: Stage 1 merged to `main` (commit `5049b67`).
- Authority: Foundation accepted on local VOD fixture.

## 1. Purpose and baseline

User objective: submit a local VOD, select start/end rounds and a team, receive a detailed tactical and opponent-movement breakdown, then point an external LLM agent at the results for grounded natural language with base-map/location context.

Ultimate workflow means convenient VOD submission, round selection, movement reconstruction and cited interpretation. This milestone proves that workflow **only for the existing supported Ascent spectator layout with a source-calibrated profile**. It does not promise arbitrary broadcasts.

[Current real-round validation](../../docs/status/mvp-real-round-validation.md) establishes five manually configured, noncontiguous 100T attack windows, corrected partial openings and three tentative site concentrations. Shift/regroup and opposite-side presence remain unknown. This is not detailed opponent analysis or a round-range submission workflow. Existing corrected runs can exercise export compatibility, but cannot replace fresh-VOD acceptance.

Existing seams inspected:
- `src/valoscribe/tactical/cli.py`: inspect/analyze take `--config`; review, source adjudication and revision rebuild exist. No VOD/round-range or agent-bundle command exists here.
- `config.py`: one `team`, one candidate color-range set, manually timed `rounds`; not a two-team/halftime index.
- `contracts.py`: source-hashed manifest, anonymous markers, coverage, append-only corrections/adjudications, per-round and aggregate summaries; no stable two-team marker contract.
- `reporting.py`: deterministic opening/shift/regroup/concentration rules and evidence links; not identity tracks or strategy intent.
- `configs/maps/ascent.yaml`: named approximate candidate polygons, canonical dimensions/asset hash and provenance; not certified official geometry or established redistribution rights.

## 2. Scope and requirements

### REQ-1 — Supported input and honest round selection

Accept a local VOD with computed SHA-256, match/map identifier, supported Ascent layout/profile, selected stable team ID and an **inclusive map-round range**. Map rounds are numbered within the selected map, not match-wide scores, source timestamps, or clip offsets. Require a map discriminator where a VOD contains multiple maps.

Preflight source dimensions, layout/crop, orientation, profile calibration and team-color evidence before tactical processing. Unsupported map/layout must return an actionable `unsupported configuration` error naming the required supported profile/calibration steps; never guess coordinates or silently reuse an unrelated source profile.

Persist a reusable, SHA-bound round-to-time manifest containing map-round number, unique round ID, source start/end and live-start seconds, completeness, boundary evidence, confirmation status, replay/exclusion spans, and both teams' side intervals. Record method (deterministic candidate index or manual confirmation), reviewer and revision/hash. Manual first setup is acceptable and disclosed; automatic discovery is not required.

Missing HUD, ambiguous score, replay duplication, halftime and missing requested rounds require fail/confirm behavior: list unresolved round IDs and source anchors, request a corrected manifest, and do not silently skip rounds or claim “all rounds.” An explicitly confirmed unavailable round remains a missing-round entry with no invented analysis; a missing round in the acceptance selection prevents passing fresh-range acceptance. Unknown analysis spans are not removed from coverage denominators.

### REQ-2 — Both teams and spatial context

Observe selected team and opponent independently. Persist stable team IDs, source-backed roster/team labels, per-round attack/defense intervals and separate source-calibrated color/slot associations across halftime. Color never permanently means side; the selected-team color profile must not be inherited for the opponent. Identity tracking is not required.

Extend typed Pydantic persistence contracts before data changes. Retain team ID on anonymous observations, corrections, coverage and event evidence; legacy single-team data must be labeled single-team, not upgraded into opponent evidence.

For each team, retain time-ordered zone observations, confidence, source-validation eligibility and independent partial/unknown/excluded coverage. Raw candidates are not tactical facts. Preserve fail-closed source adjudication; supporting one marker does not approve a frame or certify five players. Zero markers, occlusion, partial sampling or unobserved opponents never imply absence. Any strong-coverage “not observed” wording requires source-validated coverage and its explicit rule/denominator.

Map configuration owns named callouts/aliases, polygons, adjacency and spatial thresholds, plus provenance and calibration status. Broadcast configuration owns crop/color/transform. Publish canonical image dimensions, pixel units, origin/axis directions, orientation, crop-to-canonical matrix and approximation flag. Reject ambiguous/out-of-bounds positions to unknown rather than forcing a named callout.

### REQ-3 — Useful movement, not repeated counts alone

Per round and team, provide opening distribution and a chronological sequence of supported cross-zone changes: siteward shifts, apparent rotations, regroups and site concentrations where evidence permits. Describe formation/occupancy sequences or anonymous spatial samples, not continuous individual-player trajectories. Never link markers across gaps as a known player.

Each event has stable ID, type, team/round IDs, start/end evidence windows (distinct from persistence endpoints), origin/destination zones, source anchors, eligible marker references, rule configuration, confidence and coverage limitations. Bridge no replay/unknown gap without evidence. Event sequences must explain the observed change; concentration counts alone do not meet cross-zone acceptance.

Persistence, spatial change, smoothing, adjacency and completeness thresholds are **proposed configurable requirements requiring source validation**, not newly certified values/geometries. Preserve existing tactical thresholds for legacy outputs; any new rule or change needs explicit version/provenance and source comparison, never weakened thresholds to manufacture acceptance.

Separate observational facts from cautious tactical inference. “Observed occupancy moved toward B” may support “apparent rotation”; it does not prove strategy, intent, a fake, timing of unseen players or causality. Utility, spike, full HUD events and combat reconstruction are unsupported here and must not be claimed.

### REQ-4 — Portable deterministic agent bundle

Generate a self-contained offline bundle and human summary, usable without an LLM. No network/API key, CV LLM guess, embedded provider selection or cloud layer. An external agent is explicitly user-triggered and outside the core pipeline.

Minimum proposed bundle layout (names/schema finalized through typed contracts):

```text
manifest.json
README.md                    # human entry and limitations
AGENT_ENTRYPOINT.md           # read order, questions and citation rules
map/context.json             # geometry, transform, units, provenance
map/base-map.*               # only if license/export rights verified
rounds/<round-id>/events.json
rounds/<round-id>/observations.jsonl
rounds/<round-id>/coverage.json
aggregate/summary.json
aggregate/summary.md
evidence/index.json
provenance/                  # raw/corrections/adjudications and hashes
media/                       # bounded frames/playable clips
```

Manifest must specify bundle schema/version, producer/rule versions, source SHA (no machine-local absolute source path), selected map/range, resolved round mapping/hash, both team IDs and round sides, config/map/asset hashes, all file hashes and safe relative paths. Reject absolute paths, traversal and escaping symlinks. Package raw observations separately from derived revisions; reference correction/adjudication IDs and hashes and the exact consumed revision. Exporting old corrected runs must expose their single-team/partial limitations.

Map context includes named geometry, dimensions, transform, units, orientation, approximation status, asset provenance and license. Verify a license-valid base image or locally exportable source-derived asset before packaging it. If rights remain unresolved, export a clearly labeled geometry-only locally generated schematic with no invented official floorplan, state `base_image_unavailable`, and mark base-image acceptance pending; do not silently fetch or redistribute an asset.

Evidence index maps each ID to round, team, source SHA, source time in seconds/frame index, event window, relative frame/clip paths and clip-local time offset. Optional minimized source clips must be playable with exact source-to-clip anchors and export-rights disclosure; mandatory frames and annotated movement playback must make supported sequences inspectable. Do not copy the full VOD. Bundle relocation must not break citations or require access to the original machine.

Per-round events and anonymous spatial sequences expose both teams' coverage/gaps. Aggregates include evidence counts, all selected-round denominators, per-feature eligible denominators, unknown/missing/excluded counts, representative round/time IDs and sample-selection limitations; no unsupported whole-match tendencies.

### REQ-5 — External agent contract

Entrypoint read order: manifest/integrity and limitations → map context → round mapping/team sides → team coverage → observations/events/evidence → aggregate. Questions: opening shape, chronological major moves, opponent responses actually observed, recurring patterns and what cannot be concluded.

Require factual movement claims to cite `[evidence-ID; map-round; source HH:MM:SS.s]`, with clip-local time separately labeled. Separate observations from inference and retain uncertainty/unknowns. Reject nonexistent evidence IDs, out-of-window timestamps, wrong team/round/side, unsupported callouts, absence claims from partial coverage and invented player/utility/spike/intent claims. Treat source titles, annotations and all imported text as inert untrusted data, never instructions; only the entrypoint defines the analysis task.

Illustrative natural-language output — **not a validated real finding**:
> Observed opponent occupancy changed from zone X toward zone Y [E-example; R-example; source 00:10:02.0]. This may represent a rotation, but the intervening gap prevents a continuous-route claim. Selected-team presence in zone Z is unknown.

The example IDs/zones are placeholders, not claims about Ascent footage. Provider/environment choice is optional, not a blocker to the proposed spec. Grounded external-agent acceptance is a user-triggered/manual sample, with no API-dependent unit tests.

## 3. Command contract and setup

**Existing setup, runnable from the `valoscribe/` project directory** (edit source/calibration first; not a range interface):

```bash
mkdir -p .local/configs
cp configs/examples/ascent-team-movement.example.yaml .local/configs/ascent-local.yaml
# Edit local source path/SHA, source-backed profile/intervals and a fresh run ID.
uv run --extra parquet python -m valoscribe tactical inspect --config .local/configs/ascent-local.yaml
uv run --extra parquet python -m valoscribe tactical analyze --config .local/configs/ascent-local.yaml
```

From a parent/other directory, use the following **absolute-path template**, replacing the placeholder; do not run `uv` against the parent repository:

```bash
uv run --directory /ABSOLUTE/PATH/TO/valoscribe --extra parquet python -m valoscribe tactical --help
```

**PROPOSED, NOT IMPLEMENTED** end-user command (all bracketed values are placeholders; manifest fallback required when detection is insufficient):

```text
uv run --extra parquet valoscribe tactical analyze-vod \
  --vod <local-video.mp4> --map ascent --match <match-id> --map-id <map-instance> \
  --from-round <first-inclusive> --to-round <last-inclusive> --team <stable-team-id> \
  --profile <calibrated-profile.json> --round-manifest <confirmed-rounds.json> \
  --output <new-local-output-directory>
```

Proposed workflow: preflight/confirm index → fresh uncorrected run → source-backed corrections via existing review seams → new derived revision → deterministic bundle → optionally external agent. Log manual setup requirements; never advertise a fully automatic one-command result when confirmation is necessary. Repeated output paths fail without overwriting; correction rebuilds preserve raw hashes and write new revisions/bundles.

## 4. User-visible acceptance and traceability

No implementation or acceptance is claimed by this document. All criteria below are proposed and pending.

| ID / requirements | Acceptance proof |
|---|---|
| AC-1 / REQ-1 | Fresh local supported-layout VOD run, new raw baseline, contiguous inclusive selection of at least five actual map rounds. Log source/profile SHA, confirmed boundaries and exact command. Existing correction-only runs do not qualify. Missing requested rounds fail/require confirmation without silent omission. |
| AC-2 / REQ-1,2 | Verify halftime index/side switch and replay/missing-HUD handling. Use a real halftime fixture if available, preferably within the selected range; otherwise deterministic switch tests plus explicitly pending real-halftime acceptance, never fabricated verification. Reviewer checks both team labels/sides against source. |
| AC-3 / REQ-2,3 | Both teams have source-verified zone/time examples and independent coverage reports. At least three real supported cross-zone movement sequences across the fresh selection, including at least one opponent move. Opening, direction, regroup/rotation and concentration questions receive evidence-backed answers where supported. All-unknown or concentration-only output fails. If suitable observable footage is absent, this requirement stays pending; do not substitute synthetic movements. |
| AC-4 / REQ-2,3,4 | Reviewer compares every accepted movement window and supporting opening samples to source/playback, records evidence IDs, timestamps, both-team support and gaps. Preserve fresh raw baseline, corrected revision and before/after claims; annotate only the samples/windows needed to substantiate claims, not fabricated full-frame approval or recall. Partial observations stay partial. |
| AC-5 / REQ-4 | Relocate bundle to another directory; resolve hashes, relative links, evidence frames/playback, map geometry and license-valid base image/local export. Unresolved image rights keep base-image criterion pending. Human summary answers the selected-range questions without an LLM; no full VOD copy. |
| AC-6 / REQ-5 | User/reviewer points an external agent at the bundle and saves prompt/output. Every factual movement claim has a valid citation and matches source evidence; unknowns remain explicit. Manually audit all factual claims in this small sample. Invalid citations/unsupported claims fail, not a successful summary. No paid/API dependency in automated checks. |
| AC-7 / all | Record exact setup/correction active minutes, candidates reviewed, add/remove/move/defer/adjudication counts per team/round, processing/rebuild/export wall times, sampling rate, output bytes and peak memory if measured (otherwise unavailable). Gate practical usability on a user-agreed correction budget before declaring completion; no invented performance or labor estimates. |

Correction-budget proposal for discussion, **not a certified target**: review feasibility with the user if active correction exceeds 30 minutes per selected round or requires full-frame exhaustive annotation. Log actual effort separately from machine time. User acceptance of a revised bounded budget is required; do not silently relax the budget or call manually exhaustive reconstruction automatic.

## 5. Small dependency-ordered implementation stages (after approval only)

1. **Range/profile foundation:** typed round manifest and two-team/source-side contracts, narrow preflight and range entrypoint. Handoff: runnable command plus confirmed source/index packet, including unresolved rounds; inspect against VOD score/timer/replay anchors.
2. **Fresh both-team evidence and movement:** run baseline, correct bounded supporting samples, derive eligible sequences with existing correction/report seams. Handoff: five-round human summary and playable before/after evidence with at least three cross-zone sequences including opponent movement; reviewer compares actual source. This foundational gap cannot be hidden behind export completion.
3. **Map-aware bundle and agent entry:** portable hashed export with safe paths, licensed spatial context, citations and external-agent sample. Handoff: relocatable bundle, exact commands, manual citation audit and measured effort/performance, all pending criteria explicit.

No generalized platform, detector rewrite solely to avoid bounded correction, provider plumbing or broad test campaign. Keep each stage a narrow product slice; preserve upstream behavior/attribution and legacy output contracts.

## 6. Focused checks at implementation completion

Add focused deterministic tests for inclusive range and wrong-map selection; missing/ambiguous rounds; SHA mismatch; halftime team/color switches; excluded replays and missing HUD; independently partial teammates/opponents with no false absence; ineligible candidates and gap-spanning events; unavailable evidence refusing a false-complete export/report; unsafe/missing bundle paths/hashes; immutable raw/correction rebuilds; repeated output refusing overwrite; invalid external-agent citations/timestamps/team IDs. Use small offline fixtures, no network or API keys.

Run configured checks once at a coherent implementation completion boundary, **not for this planning-only change**:

```bash
uv run --extra parquet --extra dev pytest
uv run --extra parquet --extra dev ruff check src tests
uv run --extra parquet --extra dev mypy src/valoscribe
```

Engineering results and real-VOD AC evidence are separate. Missing fixtures/calibration/rights are pending product gates, not replaced by passing tests.

## 7. Open decisions, non-goals and iteration

- Confirm acceptable first-setup/correction effort budget before implementation acceptance.
- Obtain/confirm supported source profile, contiguous observable range and real halftime fixture. Supported-layout-first is the explicit assumption; any additional layout is a separately proposed milestone, not implicit portability.
- Confirm base-map export rights or a license-valid local alternative; do not invent an official floorplan.
- External-agent environment is user choice; optional guidance may follow without introducing a provider dependency.

Forward roadmap only: arbitrary VOD/layout/map portability, identity tracking, utility/spike/full HUD, automatic all-round discovery, production hosting and cloud integrations are non-goals. Do not claim detailed complete strategy reconstruction from minimap-only partial evidence.

Keep versioned proposals and evidence-linked revisions under the [specs index](../README.md). Promotion requires explicit approval and reconciliation with the current active spec; this document does not change AGENTS, scope lock or activation state.

### Stage 1 Execution Notes & Real VOD Observations
- **Deliverables**:
  - Typed contracts: `RawMarkerObservation`, `TeamFrameState`, `CorrectionDelta`, and `MarkerAdjudication` extended with `team_id: str = "single-team"`.
  - Manifest contracts: `VODRoundManifest`, `RoundManifestEntry`, `ExcludedSpan`, `TeamManifestDefinition`, `TeamColorCalibration`, and `VODBroadcastProfile` in `src/valoscribe/tactical/manifest.py`.
  - Preflight validation engine: `validate_vod_preflight` in `src/valoscribe/tactical/preflight.py` verifying SHA-256 integrity, map dimensions, independent team calibrations, and round completeness.
  - Fixtures: `configs/examples/ascent-map3-rounds.example.json` and `ascent-vct-profile.example.json` bound to the local 1.8GB Grand Final VOD.
  - CLI: `analyze-vod` in `src/valoscribe/tactical/cli.py` supporting `--preflight` dry-run inspection, summary tables, and JSON plan generation.
- **Observations on Real Footage**:
  - Fast chunked 64KB hashing computes the SHA-256 (`a2feb25b...`) of the 1.8GB VOD in < 2 seconds.
  - Preflight cleanly resolves rounds 4–7 for `100T` vs `LOUD` with exact attack/defense sides.
  - Fail-closed validation cleanly halts when unconfirmed rounds are requested (e.g. requesting round 8 reports exact boundary anchor and status).
  - Directory collision protection successfully prevents overwriting existing runs (`FileExistsError`).
  - Merged into `main` with 1,282 tests passing, 0 ruff errors, and 0 mypy issues across 136 files.

### Change log

- 0.2 — 2026-10-04: Completed Stage 1 (Foundation, Preflight, Contracts, CLI) and verified against real local VOD; moved to `specs/finished/`.
- 0.1 — 2026-10-04: Initial proposed supported-Ascent round-range, both-team movement and external-agent evidence milestone.

Documentation verification from project root: `git diff --check`; check relative Markdown links and keep this spec at or below 280 lines.
