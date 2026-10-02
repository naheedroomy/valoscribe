# VALORANT Tactical Movement Analyzer
## MVP Reset, Repository Cleanup, and Real-Round Delivery Specification

**Document version:** 1.0  
**Date:** 2 October 2026  
**Status:** Active implementation specification  
**Audience:** AI coding agent working in the existing Valoscribe fork  
**Supersedes for the next milestone:** The earlier implementation sequence that made full HUD extraction, persistent player identity, exhaustive validation, utility reconstruction, or LLM reporting prerequisites for a useful demo.

---

## 1. Executive directive

The project has accumulated substantial infrastructure, tests, diagnostics, reports, and experimental code without yet demonstrating its central product value on real footage.

The next milestone is a deliberate product reset.

The agent must deliver the smallest useful vertical slice that answers:

> For several real rounds on one map, where did the selected team open, how did its observed formation shift, which side did it regroup toward, where did it appear to commit, and was any observed presence maintained on the opposite side?

The system may be partially manual. It does not need perfect tracking, automatic round discovery, agent identities, complete HUD extraction, utility inference, or an LLM.

The agent must also clean and organize the repository before adding more implementation. The final tracked working tree must be understandable, documented, free of generated clutter, and clean according to Git.

This milestone is successful only when it produces inspectable outputs from at least five real rounds. Test count, architecture, abstention behavior, provider plumbing, and synthetic fixtures are supporting evidence, not the product result.

---

## 2. Current baseline to verify

The following statements come from the current project-status report and must be verified against the actual checkout before being repeated as current facts:

- The code can generate an offline round-analysis report and can optionally call an OpenAI-compatible model.
- A genuine real-VOD HUD-to-report tactical run has not been accepted.
- The recent real Ascent round attempt analyzed a bounded minimap interval but did not perform HUD extraction.
- The current real minimap output is diagnostic only: anonymous, unregistered or insufficiently validated for tactical claims, and not reliable movement evidence.
- A synthetic live-provider request proved transport and schema plumbing only.
- The recorded repository state reported 1,198 tests passed, 1 skipped, Ruff clean, and mypy clean, but those results were not rerun for the report.
- The working tree was reported as broadly dirty with substantial uncommitted changes.
- The existing candidate broadcast profile includes a minimap crop but does not include the full HUD regions required by legacy Valoscribe extraction.
- The identified real source includes an Ascent round interval around source seconds 260–342, but the agent must verify source path, hash, team, side, and exact usable boundaries locally.

The agent must not assume that any of these facts remain unchanged after opening the repository.

---

## 3. Product outcome

### 3.1 Primary user story

As a VALORANT analyst, I want to select several rounds from one professional Ascent VOD and receive:

1. A visual minimap playback with the selected team’s observed markers highlighted.
2. A canonical Ascent playback showing the corresponding map positions.
3. A timestamped timeline of observed players per map zone.
4. A cautious deterministic description of the opening, major shift, regroup direction, apparent commitment, and opposite-side presence.
5. A multi-round comparison showing recurring movement patterns.
6. A lightweight way to correct false or missing detections and regenerate the analysis without rerunning the complete video pipeline.

### 3.2 MVP proof statement

At the end of this milestone, the repository must be able to demonstrate:

> Here are at least five real rounds from one Ascent broadcast. For each round, the playback and timeline show the selected team’s observed formation over time. Across the rounds, the system identifies at least one recurring opening or regroup pattern, with representative round and timestamp references.

### 3.3 Product principles

1. **Useful before perfect.** A corrected semi-automatic result is preferable to an automatic pipeline that yields no trusted tactical output.
2. **Team shape before player identity.** Team-level occupancy and movement are the MVP. Persistent individual identities are not required.
3. **Manual configuration is acceptable.** Manually selected intervals, side labels, map crop, transformation points, and color thresholds are allowed.
4. **Visible evidence first.** Every textual statement must be inspectable in a playback or timeline.
5. **Unknown is valid.** Missing coverage must be exposed instead of converted into a confident tactical conclusion.
6. **No infrastructure for hypothetical future needs.** New abstractions must be used by this milestone.
7. **One real vertical slice is more important than another large synthetic test layer.**

---

## 4. Scope

### 4.1 Required scope

The active MVP must support:

- One existing local professional-broadcast VOD.
- One known 1920×1080 broadcast layout.
- One map: **Ascent**.
- One selected team.
- One selected side for the comparison set, preferably attack if the available footage provides at least five complete usable rounds.
- At least five manually selected complete or tactically useful round intervals.
- Manually configured minimap crop.
- Manually configured broadcast-to-canonical-map transformation.
- Manually configured selected-team broadcast color or color ranges.
- Low-rate interval processing, initially 3–5 samples per second.
- Selected-team marker localization.
- Canonical map coordinates.
- Named-zone assignment.
- Team-level occupancy and movement features.
- Visual playback and structured outputs.
- Correction deltas that can be applied without rerunning detection.
- Per-round deterministic summaries.
- One multi-round deterministic summary.
- A compact, reproducible run manifest.

### 4.2 Explicitly deferred

The following must not block this milestone:

- Complete HUD calibration.
- Timer, scoreboard, player-panel, or killfeed extraction.
- Automatic round boundary discovery.
- Full-map or full-VOD batch processing.
- Persistent anonymous player tracking.
- Agent portrait recognition.
- Player-name identity.
- Formal IDF1 or multi-object-tracking acceptance gates.
- Spike-carrier reconstruction.
- Utility detection or ability-charge fusion.
- Smoke detection.
- Economy inference.
- Multiple maps.
- Multiple broadcast layouts.
- Automatic map or layout recognition.
- OpenAI, Gemini, or other LLM calls.
- Natural-language query parsing.
- A polished browser application.
- Cloud infrastructure.
- Model training pipelines.
- Broad upstream Valoscribe refactors.

Existing implementation for deferred functionality must be preserved where practical, but it must be clearly marked as deferred or experimental and must not complicate the active MVP path.

### 4.3 Hard product boundary

The implementation is offline and retrospective. It must not become a live in-game overlay or real-time decision assistant.

---

## 5. Decision record for this reset

The following decisions are binding for this milestone:

| ID | Decision |
|---|---|
| D-01 | The active path is minimap-first and does not wait for complete HUD extraction. |
| D-02 | Manual round intervals and manual minimap calibration are acceptable. |
| D-03 | Team-level positions and zone occupancy are sufficient for the MVP. |
| D-04 | Agent and player identity are optional metadata, not prerequisites. |
| D-05 | Human correction is part of the product, not a failure state. |
| D-06 | Deterministic reports are required; LLM reporting is deferred. |
| D-07 | Tests verify behavior but do not define product completion. |
| D-08 | Generated videos, raw VODs, caches, and large diagnostics must not live in the tracked repository. |
| D-09 | Old specifications and experiments are preserved in an archive, but only one specification is active. |
| D-10 | The final working tree must be clean and the repository root must be intentionally organized. |

---

## 6. Repository cleanup and organization

Repository cleanup is the first implementation phase. It must be bounded and must not turn into a rewrite of stable upstream Valoscribe code.

### 6.1 Safety before cleanup

Before moving or deleting anything, the agent must:

1. Record:
   - current branch;
   - current commit;
   - configured remotes;
   - `git status --short`;
   - staged diff summary;
   - unstaged diff summary;
   - untracked file list;
   - largest files and directories in the repository working tree.
2. Check for secrets, local `.env` files, API keys, source videos, generated reports, and large artifacts. Secrets must never be committed or copied into documentation.
3. Preserve all meaningful source, configuration, test, and documentation changes before destructive cleanup.
4. Prefer a local checkpoint commit on a dedicated reset branch if repository policy permits commits.
5. If a checkpoint commit is not permitted, create a patch plus a manifest of untracked source-like files under an ignored local backup directory.
6. Never use `git clean -fdx`, broad recursive deletion, or equivalent destructive commands.
7. Use `git mv` for tracked files whenever practical so history remains understandable.

Recommended branch name:

```text
mvp-reset/minimap-team-movement
```

Recommended checkpoint commit, after excluding secrets and generated data:

```text
checkpoint: preserve pre-mvp-reset work
```

No push is required unless separately requested.

### 6.2 Cleanup inventory document

Create:

```text
docs/status/pre-reset-repository-inventory.md
```

It must contain:

- the recorded Git state;
- a root-level tree summary;
- classification of unusual or duplicate files;
- identified generated data;
- identified source-like untracked files;
- proposed move/archive/delete actions;
- items intentionally left in place and why.

### 6.3 Allowed root-level contents

After cleanup, the repository root should contain only conventional project entry points and top-level directories. The target allowlist is:

```text
.env.example
.gitignore
AGENTS.md
LICENSE
README.md
pyproject.toml
uv.lock                  # if already used by the project
src/
tests/
configs/
docs/
specs/
examples/
scripts/
```

Additional existing project-standard files such as `Dockerfile`, CI configuration, security policy, contribution guide, or lock files may remain when they are actually used. Every other root-level file must be moved, archived, deleted as generated data, or explicitly justified in the cleanup report.

### 6.4 Target top-level structure

```text
.
├── README.md
├── AGENTS.md
├── LICENSE
├── pyproject.toml
├── uv.lock
├── .env.example
├── .gitignore
├── src/
│   └── valoscribe/
│       ├── ... existing upstream modules ...
│       └── tactical/                 # preferred canonical home for new VTA work
│           ├── __init__.py
│           ├── cli.py
│           ├── config.py
│           ├── contracts.py
│           ├── pipeline.py
│           ├── minimap/
│           │   ├── crop.py
│           │   ├── transform.py
│           │   ├── markers.py
│           │   └── overlays.py
│           ├── movement/
│           │   ├── zones.py
│           │   ├── occupancy.py
│           │   └── patterns.py
│           ├── review/
│           │   ├── corrections.py
│           │   └── local_reviewer.py
│           ├── reporting/
│           │   ├── round_report.py
│           │   └── aggregate_report.py
│           └── experimental/         # only when needed for preserved non-MVP work
├── configs/
│   ├── maps/
│   ├── broadcasts/
│   └── examples/
├── specs/
│   ├── active/
│   └── archive/
├── docs/
│   ├── README.md
│   ├── architecture/
│   ├── guides/
│   ├── status/
│   ├── adr/
│   └── archive/
├── examples/
│   └── tactical_mvp/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── golden/
│   └── fixtures/
└── scripts/
    ├── maintenance/
    └── dev/
```

This source layout is a preferred direction, not permission to churn stable upstream code. Apply these rules:

- Do not reorganize stable Valoscribe modules solely for visual symmetry.
- Consolidate duplicated or scattered VTA extension code into one canonical location when the move is reasonably bounded.
- Do not create a second implementation of an existing concern merely to satisfy this tree.
- If the current source layout already has a coherent canonical home, preserve it and document the mapping in `docs/architecture/code-layout.md`.
- New MVP code must not be placed in random root scripts or temporary directories.

### 6.5 Documentation structure

Use the following policy:

```text
specs/active/
  MVP_RESET_AND_REPOSITORY_CLEANUP_SPEC.md   # the only active implementation spec

specs/archive/
  previous project specs, task plans, and superseded milestone specs

docs/architecture/
  current system design and data flow

docs/guides/
  setup, running the MVP, correcting detections, interpreting outputs

docs/status/
  dated factual status, cleanup report, real-run validation report

docs/adr/
  architecture decisions that remain applicable

docs/archive/
  stale or historical narrative documentation not used as active guidance
```

Required documentation actions:

1. Copy this specification into `specs/active/` and make it the only active milestone specification.
2. Archive the previous broad project specification rather than deleting it.
3. Archive VTA-704 and other superseded plans/specs unless they remain active for another clearly named path.
4. Move the current readiness report to a dated file under `docs/status/`.
5. Add `docs/README.md` as a documentation index showing active, historical, and status material.
6. Update `AGENTS.md` so it points to this specification first.
7. Remove contradictory “source of truth” claims from superseded files, or add a clear archived banner.
8. Keep one root `README.md` with a concise product description, setup, one verified MVP command, output example, and links to detailed docs.

### 6.6 Generated data and local workspace policy

All machine-local inputs and outputs must live under an ignored workspace:

```text
.local/
├── media/          # source VODs
├── configs/        # machine-specific run configs containing absolute paths
├── runs/           # generated run outputs
├── cache/          # decoded or transformed cache
├── annotations/    # local correction/annotation work
└── backups/        # temporary safety patches/manifests
```

The entire `.local/` directory must be ignored by Git.

Do not track:

- source VODs;
- generated playback videos;
- frame dumps;
- per-candidate crops;
- caches;
- temporary `/private/tmp` output copies;
- large Parquet or JSONL runs generated from local footage;
- secrets or real API credentials.

Small, intentional fixtures may remain under `tests/fixtures/` only when they are legally and technically appropriate, stable, documented, and needed by automated tests.

Add or update `.gitignore` for at least:

```text
.local/
artifacts/
runs/
.cache/
.pytest_cache/
.mypy_cache/
.ruff_cache/
__pycache__/
*.py[cod]
.env
.env.*
!.env.example
```

Do not use a broad media extension ignore if the repository intentionally tracks tiny test media; prefer directory-based policy.

### 6.7 File migration rules

| Current item type | Destination/action |
|---|---|
| Active reset specification | `specs/active/` |
| Superseded project/task specs | `specs/archive/` with archived banner |
| Current factual status reports | `docs/status/` with date in filename |
| Architecture descriptions | `docs/architecture/` |
| How-to/run instructions | `docs/guides/` |
| ADRs | `docs/adr/` |
| Synthetic examples | `examples/tactical_mvp/` or `tests/fixtures/` depending on purpose |
| One-off useful maintenance scripts | `scripts/maintenance/` |
| One-off development helpers | `scripts/dev/` |
| Generated local reports/videos | `.local/runs/` |
| Raw local VODs | `.local/media/` |
| Duplicated or obsolete generated files | Remove after preservation check |
| Unknown source-like untracked files | Preserve, classify, then place in canonical source/test/docs location |

### 6.8 Cleanup completion criteria

Repository cleanup is complete when:

- the root follows the allowlist or every exception is documented;
- there is exactly one active implementation specification;
- active docs do not point to temporary absolute output paths as required inputs;
- generated outputs are outside the tracked tree;
- old specs remain accessible in an archive but cannot be mistaken for active instructions;
- no source-like work is left in temporary or random directories;
- imports, commands, and documentation links work after moves;
- tests and static checks pass at the same or better baseline, excluding documented pre-existing failures;
- `git status --short` is empty after the agent’s final commits;
- `docs/status/repository-cleanup-report.md` records what moved, what was archived, what was removed, and why.

---

## 7. MVP system design

### 7.1 End-to-end flow

```text
Manual run configuration
        ↓
Decode only selected round intervals at 3–5 FPS
        ↓
Crop configured minimap region
        ↓
Apply configured map transformation
        ↓
Detect selected-team minimap markers
        ↓
Write immutable raw observations
        ↓
Apply optional human correction deltas
        ↓
Assign canonical positions to Ascent zones
        ↓
Build team occupancy and movement timeline
        ↓
Generate per-round playback and deterministic summary
        ↓
Aggregate five or more rounds into recurring patterns
```

### 7.2 Architectural boundaries

The implementation must preserve these layers:

1. **Raw observation layer**  
   Direct detector output. Never overwritten by corrections or analytics.

2. **Corrected observation layer**  
   Raw observations plus explicit human deltas.

3. **Derived movement layer**  
   Zone occupancy, team centroid, spread, macro-side counts, movement shifts, and apparent commitments.

4. **Reporting layer**  
   Cautious deterministic text and representative evidence links.

Do not let reporting code mutate observations. Do not let manual corrections rewrite raw detector files.

### 7.3 Reuse of Valoscribe

Reuse existing code where it genuinely reduces work:

- video opening and timestamp seeking;
- frame decoding;
- CLI framework;
- Pydantic conventions;
- logging;
- output helpers;
- existing minimap crop configuration if verified for the selected source.

Do not make legacy full-HUD extraction a gate for the MVP. Existing HUD and round-analysis functionality may remain available as a separate path.

---

## 8. Configuration

### 8.1 Tracked example versus local configuration

Commit a redacted example:

```text
configs/examples/ascent-team-movement.example.yaml
```

Create the machine-specific real run under:

```text
.local/configs/<descriptive-run-id>.yaml
```

The local configuration may contain an absolute VOD path. The manifest must store a normalized source identifier and hash, but active documentation must not depend on one developer’s absolute filesystem path.

### 8.2 Required configuration shape

The exact Pydantic naming may adapt to existing conventions, but the semantics below are required.

```yaml
schema_version: 1

run:
  run_id: ascent-team-movement-mvp-r1
  description: "Five selected attack rounds from one Ascent broadcast"
  sample_fps: 4.0
  output_root: .local/runs
  debug_level: summary       # none | summary | verbose

source:
  video_path: /absolute/local/path/to/map-vod.mp4
  expected_width: 1920
  expected_height: 1080
  sha256: null               # computed if omitted

map:
  id: ascent
  canonical_width: 1000
  canonical_height: 1000
  zone_config: configs/maps/ascent.yaml

broadcast:
  profile_id: vct-americas-2026-1080p-manual
  minimap_crop:
    x: 0
    y: 0
    width: 0
    height: 0
  transform:
    method: homography
    source_points:
      - [0, 0]
      - [0, 0]
      - [0, 0]
      - [0, 0]
    canonical_points:
      - [0, 0]
      - [1000, 0]
      - [1000, 1000]
      - [0, 1000]

team:
  name: "Selected Team"
  side: attack
  broadcast_slot: left
  broadcast_color_label: red
  color_ranges_hsv:
    - lower: [0, 120, 100]
      upper: [10, 255, 255]
    - lower: [170, 120, 100]
      upper: [179, 255, 255]

marker_detection:
  min_area_px: 5
  max_area_px: 500
  min_confidence: 0.35
  morphology_kernel_px: 3
  merge_distance_px: 8

rounds:
  - round_id: map3-round4
    source_start_seconds: 260.0
    source_end_seconds: 342.0
    side: attack
    live_start_offset_seconds: 0.0
    analysis_end_offset_seconds: null
    excluded_intervals: []
```

The example values above are placeholders except for the previously reported candidate interval. The agent must measure and document the real crop, transformation points, team color ranges, side, and final round intervals.

### 8.3 Round selection

The real validation set must contain at least five rounds that:

- are from the same map and broadcast layout;
- use the same selected team and comparison side;
- expose a sufficiently visible minimap for a meaningful portion of the round;
- include more than one opening or commitment outcome if available;
- avoid using only trivially similar rounds;
- include at least one case with temporary obstruction, overlap, or another realistic detection difficulty.

The agent must document why each round was selected.

### 8.4 Excluded intervals

The run config must support per-round intervals that should not be analyzed, including:

- broadcast replay;
- scoreboard overlay;
- tactical timeout graphic;
- desk/advertisement transition;
- missing or obstructed minimap;
- observer replay transition.

Excluded intervals must appear as explicit gaps in coverage rather than being silently interpolated.

---

## 9. Required data contracts

Use typed models. Names may adapt to current code, but the fields and separation are required.

### 9.1 Run manifest

```text
RunManifest
- schema_version
- run_id
- created_at
- project_commit
- upstream_commit, when known
- source_video_sha256
- source_dimensions
- configuration_sha256
- map_config_sha256
- code_version
- sample_fps
- round_ids
- output_paths
- warnings
```

A compact manifest is required. Do not expand this milestone into a generalized provenance framework.

### 9.2 Raw marker observation

```text
RawMarkerObservation
- run_id
- round_id
- sample_index
- source_frame_index, if available
- source_timestamp_seconds
- crop_x
- crop_y
- canonical_x, optional when transform failed
- canonical_y, optional when transform failed
- confidence
- detector_version
- quality_flags
```

No player or agent identity is required.

### 9.3 Correction delta

```text
CorrectionDelta
- run_id
- round_id
- sample_index
- operation: add | remove | move
- target_observation_id, optional
- original_canonical_x, optional
- original_canonical_y, optional
- corrected_canonical_x, optional
- corrected_canonical_y, optional
- reviewer
- note, optional
- created_at
```

Corrections must be append-only and independently inspectable.

### 9.4 Corrected team frame

```text
TeamFrameState
- run_id
- round_id
- source_timestamp_seconds
- game_time_label, optional/manual
- observations
- observed_marker_count
- zone_counts
- macro_counts: A | MID | B | OTHER
- centroid_x, optional
- centroid_y, optional
- spread, optional
- coverage_status: good | partial | unknown | excluded
- warnings
```

### 9.5 Round movement summary

```text
RoundMovementSummary
- round_id
- usable_time_seconds
- opening_distribution
- opening_confidence
- first_major_shift_time
- first_major_shift_direction
- apparent_commitment_site
- apparent_commitment_time
- opposite_side_presence: present | not_observed | unknown
- representative_timestamps
- unknown_intervals
- warnings
```

Use `not_observed` only when coverage is sufficiently strong. Otherwise use `unknown`.

### 9.6 Aggregate summary

```text
AggregateMovementSummary
- run_id
- included_rounds
- excluded_rounds
- opening_pattern_counts
- apparent_commitment_counts
- regroup_direction_counts
- opposite_side_presence_counts
- approximate_commitment_time_distribution
- recurring_patterns
- representative_rounds
- limitations
```

---

## 10. Computer-vision implementation requirements

### 10.1 Interval decoding

- Decode only configured round intervals.
- Sample at the configured low rate; default to 4 FPS.
- Seek efficiently using existing video helpers where practical.
- Stream frames rather than loading a complete interval into memory.
- Do not persist every decoded frame by default.
- Do not generate one artifact per candidate marker.
- Record decode failures and timestamp discontinuities.

### 10.2 Minimap crop

- Use the manually measured crop from the selected source.
- Verify it on frames from the beginning, middle, and end of each selected round.
- Produce one calibration contact sheet or short calibration video.
- Reject or flag frames where the expected crop is out of bounds or substantially obstructed.

### 10.3 Canonical map transformation

- Support a manually measured affine transform or homography.
- Use a canonical Ascent coordinate system, recommended 1000×1000.
- Save the transformation matrix in the run’s configuration snapshot.
- Generate a calibration overlay showing source minimap reference points and canonical alignment.
- Do not claim canonical accuracy without visual review.
- If transformation fails for a frame, retain crop-space evidence and mark canonical coordinates unavailable.

### 10.4 Selected-team marker detection

The first detector should be intentionally simple and tunable. It may combine:

- HSV or Lab color segmentation for the selected team’s marker ring/outline;
- morphology;
- connected components or contour filtering;
- area, circularity, local contrast, or ring-shape checks;
- merging of nearby components;
- temporal persistence as a confidence aid.

Requirements:

- Return zero or more marker centers with confidence and quality flags.
- Do not force exactly five detections.
- Do not infer missing markers solely to make the count five.
- Do not classify agent portraits.
- Do not assign player names.
- Preserve raw candidates only in compact structured form when needed; do not emit hundreds of thousands of candidate images.
- Provide a summary debug mode that shows accepted detections and a bounded sample of rejections.

### 10.5 Noise smoothing

The MVP may use simple temporal smoothing, but it must not pretend to be identity tracking.

Allowed approaches include:

- short-window median of zone counts;
- persistence requirement for a new occupied zone;
- removal of one-sample isolated detections;
- bounded nearest-neighbor stabilization without durable track IDs.

Do not introduce a full tracking framework merely to smooth occupancy.

### 10.6 Coverage and uncertainty

For each sampled timestamp, compute a coverage status.

Suggested behavior:

- `good`: minimap visible and at least four plausible selected-team markers observed before known heavy combat, or reviewer-approved frame;
- `partial`: minimap visible but marker count/evidence is incomplete;
- `unknown`: crop unavailable, transform failed, or evidence too weak;
- `excluded`: configured replay/overlay interval.

These thresholds are configurable and must be described, not presented as universal truth.

Absence of an observed marker is not evidence of death, rotation, or lack of opposite-side presence unless coverage is strong enough for the claim.

---

## 11. Ascent map understanding

### 11.1 Zone configuration

Create:

```text
configs/maps/ascent.yaml
```

It must contain reviewed polygons or regions for at least:

- Attacker Spawn / deep attacker area
- A Lobby
- A Main
- A Site
- A defensive/back-site region
- Mid Bottom / attacker-side mid
- Mid Top / central mid
- Catwalk / A Link side
- Market / B Link side
- B Lobby
- B Main
- B Site
- B defensive/back-site region
- Defender Spawn / rotation area
- Unknown / outside configured polygons

Exact names may follow existing map terminology, but every zone must also map to a macro group:

```text
A
MID
B
SPAWN
OTHER
```

### 11.2 Review requirement

Generate a canonical map image with every polygon and label drawn. A human must be able to inspect overlaps, gaps, and incorrect boundaries.

### 11.3 Derived team features

At each sample, derive only features supported by current observations:

- observed marker count;
- players observed per detailed zone;
- players observed per macro group;
- centroid of observed markers;
- spatial spread;
- number of occupied macro lanes;
- majority-side position;
- whether at least one marker is visibly present on the opposite side.

Do not label map control, cleared space, or defender knowledge from positions alone.

---

## 12. Deterministic tactical rules

The reporting logic must remain simple, explainable, and cautious.

### 12.1 Opening distribution

Define a configurable opening window, initially the first 6–10 usable seconds after the configured live-round start.

Compute the stable median or modal macro distribution across that window, for example:

```text
A=2, MID=1, B=2
```

Possible human-readable label:

```text
Observed 2-1-2 opening distribution.
```

Do not call it a “default” unless the aggregate evidence across rounds supports that wording.

### 12.2 First major shift

A major shift may be emitted when one of the following persists for a configured duration:

- at least two observed markers move from one macro group to another;
- the team centroid crosses a configured macro boundary by a meaningful amount;
- the macro occupancy vector changes materially and remains changed.

The summary must include the evidence timestamp and resulting occupancy.

### 12.3 Regroup direction

Report an apparent regroup toward A or B when:

- the corresponding macro count increases by at least two relative to a stable previous window;
- the increase persists for a configured minimum duration;
- coverage during both windows is not `unknown`.

Use wording such as:

```text
Observed formation shifted toward A.
```

Do not infer communication, intent, or a specific called strategy.

### 12.4 Apparent site commitment

An apparent commitment may be emitted when:

- a majority of currently observed markers occupy a site plus its immediate approach;
- the condition persists for a configured duration;
- there is no immediate reversal;
- coverage is adequate.

Suggested initial threshold:

```text
at least 3 observed markers and at least 60% of observed markers
for at least 2 seconds
```

This is a tunable MVP rule, not a tactical truth definition.

### 12.5 Opposite-side presence

Report:

- `present` when at least one marker is positively observed in the opposite-side macro group during the commitment window;
- `not_observed` only when coverage is strong enough that absence is meaningful;
- `unknown` for incomplete coverage.

Avoid the word “lurk” in the deterministic output unless persistent identity or a reviewed human label supports it. Prefer “opposite-side presence.”

### 12.6 Recurring patterns

Across five or more rounds, group rounds using transparent keys such as:

- opening macro distribution;
- regroup direction;
- apparent commitment site;
- opposite-side presence state;
- approximate commitment-time bucket.

The MVP does not need unsupervised clustering or embeddings.

Example aggregate output:

```text
In 3 of 5 reviewed rounds, the observed team opened with players on all three
macro lanes and later shifted a majority toward A. In 2 of those 3 rounds,
B-side presence remained visible during the apparent A commitment.
Representative rounds: 4, 8, and 11.
```

Every count must show its denominator and excluded/unknown rounds.

---

## 13. Human correction workflow

### 13.1 Requirement

The user must be able to correct false positives and missed marker positions without editing pipeline code and without rerunning frame detection.

### 13.2 Minimum local reviewer

Implement a small local reviewer using existing dependencies where possible. An OpenCV window is acceptable.

Required interactions:

- open a selected round and sampled timestamp;
- display the minimap crop with current detections;
- next/previous sample;
- click an existing detection to remove it;
- click an empty location to add a marker;
- optionally drag or remove-and-add to move a marker;
- save append-only correction deltas;
- show whether the frame has unsaved edits;
- quit safely without corrupting the correction file.

Suggested keys:

```text
Left/Right or A/D: previous/next sample
Left click: add marker or select nearest marker
Delete/Backspace: remove selected marker
S: save
Q/Esc: quit
```

Exact controls may adapt, but they must be documented in `docs/guides/correcting-detections.md`.

### 13.3 Rebuild after correction

Provide a command that applies corrections and regenerates:

- corrected observations;
- occupancy data;
- per-round summary;
- aggregate summary;
- corrected playback overlay.

It must not rerun marker detection unless explicitly requested.

---

## 14. CLI requirements

Integrate with the existing Typer CLI if practical. Exact names may follow current conventions, but the following capabilities are required.

### 14.1 Inspect configuration and calibration

```bash
uv run python -m valoscribe tactical inspect \
  --config .local/configs/ascent-mvp.yaml
```

Must:

- validate configuration;
- verify the source exists and dimensions match;
- compute or verify source hash;
- render crop and transformation calibration artifacts;
- list configured rounds and excluded intervals;
- make no tactical claims.

### 14.2 Analyze configured rounds

```bash
uv run python -m valoscribe tactical analyze \
  --config .local/configs/ascent-mvp.yaml
```

Must:

- process only configured intervals;
- write raw observations;
- apply existing corrections if present;
- write playback and structured outputs;
- generate round and aggregate reports;
- use a new run directory or an explicit safe resume mode;
- never overwrite a previous completed run silently.

### 14.3 Review detections

```bash
uv run python -m valoscribe tactical review \
  --run-dir .local/runs/<run-id> \
  --round-id <round-id>
```

### 14.4 Rebuild derived outputs

```bash
uv run python -m valoscribe tactical rebuild \
  --run-dir .local/runs/<run-id>
```

### 14.5 Optional single-round development mode

A single configured round may be processed during development, but milestone acceptance requires at least five rounds in one comparison set.

---

## 15. Output contract

Use a compact run directory:

```text
.local/runs/<run-id>/
├── manifest.json
├── config.snapshot.yaml
├── calibration/
│   ├── minimap-crop-contact-sheet.png
│   ├── transform-overlay.png
│   └── ascent-zones.png
├── rounds/
│   ├── <round-id>/
│   │   ├── raw_observations.jsonl
│   │   ├── corrections.jsonl
│   │   ├── corrected_observations.jsonl
│   │   ├── occupancy.parquet
│   │   ├── occupancy.csv
│   │   ├── minimap_playback.mp4
│   │   ├── canonical_playback.mp4
│   │   ├── summary.json
│   │   └── summary.md
│   └── ...
├── aggregate/
│   ├── summary.json
│   ├── summary.md
│   ├── pattern_table.csv
│   └── representative_rounds.json
└── logs/
    └── run.log
```

Do not create per-frame folders by default.

### 15.1 Playback requirements

The minimap playback must display:

- source timestamp;
- round ID;
- selected team and side;
- accepted marker centers;
- marker confidence where practical;
- raw versus corrected state;
- coverage status;
- excluded/unknown state when applicable.

The canonical playback must display:

- canonical Ascent map;
- selected-team observed markers;
- detailed zone labels or current zone names;
- macro occupancy counts;
- apparent phase annotations only when a deterministic rule has fired.

### 15.2 Report requirements

Each round report must contain:

- source interval;
- usable and unknown coverage durations;
- opening distribution;
- first major observed shift;
- apparent regroup direction;
- apparent commitment site and time, if supported;
- opposite-side presence state;
- representative timestamps;
- warnings and limitations;
- paths to the playback files.

The aggregate report must contain:

- exact included and excluded round counts;
- pattern frequency with denominators;
- representative rounds;
- unknown/low-coverage rounds;
- correction counts;
- limitations.

No report may claim agent identity, player intent, utility causality, or complete team strategy.

---

## 16. Testing and validation strategy

### 16.1 Testing principle

Add the smallest set of tests that protects the active MVP. Do not create a broad generalized test program as a substitute for real outputs.

### 16.2 Required automated tests

At minimum:

- configuration validation;
- crop bounds validation;
- coordinate transformation using known points;
- zone polygon assignment;
- correction add/remove/move application;
- raw observations remain immutable;
- occupancy calculation;
- deterministic opening/shift/commitment rules;
- output non-overwrite behavior;
- one small end-to-end integration fixture that produces all required file types.

### 16.3 Existing suite

Run the repository’s existing tests, Ruff, and mypy after cleanup and at final completion. Do not advertise the combined test count as evidence of tactical accuracy.

Report categories separately where available:

```text
Existing/upstream tests
New MVP unit tests
New MVP integration tests
Real rounds processed
Real rounds manually reviewed
Real rounds corrected
```

### 16.4 Real validation

Real validation is mandatory.

For every selected round, a reviewer must inspect:

- minimap crop validity;
- transformation plausibility;
- obvious false positives;
- obvious missed markers;
- apparent occupancy timeline;
- opening summary;
- regroup/commitment summary;
- unknown interval handling.

The agent must create:

```text
docs/status/mvp-real-round-validation.md
```

It must include:

- source identifier and hash;
- selected team and side;
- exact round intervals;
- why the rounds were chosen;
- detected/corrected marker counts;
- known failure cases;
- correction effort;
- representative screenshots or local artifact paths;
- per-round pass/partial/fail assessment;
- aggregate pattern found;
- limitations.

A round may be marked partial and still be useful, but at least five rounds must have enough evidence for an opening distribution and at least three must support a shift or apparent commitment statement.

---

## 17. Performance and artifact guardrails

The previous diagnostic path produced disproportionately large outputs and expensive processing for a short interval. The MVP must avoid that pattern.

Requirements:

- default sample rate no higher than 5 FPS;
- decode only selected intervals;
- no full-VOD run;
- no per-candidate image output by default;
- no storing all frames in memory;
- no storing hundreds of thousands of rejected candidate records unless a bounded debug flag explicitly requests them;
- playback must be video-encoded rather than emitted as frame sequences;
- debug output must be capped and documented;
- runtime, peak memory if measurable, and output size must be reported;
- a run producing gigabytes of artifacts for five short rounds must be treated as a defect unless the source videos themselves are included, which they must not be.

A useful design target is a compact run directory that a developer can inspect and retain locally without special storage handling. Exact limits may depend on codec and machine, but the implementation must show deliberate control of output volume.

---

## 18. Implementation sequence

The agent must complete these phases in order. It may work continuously without waiting for approval, but it must not skip acceptance evidence.

### RST-001 — Snapshot and classify the existing repository

Deliver:

- reset branch or equivalent safety checkpoint;
- pre-reset inventory document;
- secret/generated-data review;
- proposed migration mapping.

Gate:

- no destructive move has occurred before preservation;
- all source-like untracked work is accounted for.

### RST-002 — Clean and organize the repository

Deliver:

- root cleanup;
- `specs/active` and `specs/archive`;
- organized docs and docs index;
- ignored `.local` workspace policy;
- cleanup report;
- updated `README.md` and `AGENTS.md`;
- working imports and commands.

Gate:

- existing tests/static checks pass or pre-existing failures are documented;
- no generated data is tracked;
- active documentation is unambiguous.

### MVP-001 — Real run configuration and calibration

Deliver:

- tracked example config;
- local real config;
- verified source hash/dimensions;
- at least five round intervals;
- verified minimap crop;
- transformation calibration artifacts;
- Ascent zone map.

Gate:

- human-inspectable crop, transform, and zone overlays are correct enough to continue.

### MVP-002 — Selected-team marker detection and playback

Deliver:

- low-rate interval decoder;
- marker detector;
- raw observations;
- minimap and canonical playback;
- bounded debug output.

Gate:

- all selected rounds produce inspectable playback;
- the detector finds useful team-shape evidence in at least five rounds;
- no claim of identity tracking is made.

### MVP-003 — Corrections, zones, and occupancy

Deliver:

- local correction reviewer;
- append-only correction deltas;
- corrected observations;
- zone assignment;
- occupancy timelines;
- rebuild command.

Gate:

- a user can add/remove a marker, save, rebuild, and observe the corrected downstream result without rerunning detection.

### MVP-004 — Deterministic round and aggregate analysis

Deliver:

- opening-distribution rule;
- major-shift/regroup rule;
- apparent-commitment rule;
- opposite-side-presence rule;
- per-round reports;
- aggregate report.

Gate:

- every statement points to timestamped structured evidence;
- low-coverage conditions yield unknown rather than invented conclusions.

### MVP-005 — Real five-round completion and final cleanup

Deliver:

- final run over at least five rounds;
- reviewed outputs;
- applied corrections where needed;
- real validation report;
- updated root README quick start;
- clean final Git worktree;
- logical commits.

Gate:

- milestone acceptance criteria in Section 19 are met.

---

## 19. Milestone acceptance criteria

The milestone passes only when all repository and product criteria below are satisfied.

### 19.1 Repository criteria

- [ ] Meaningful pre-reset work was preserved before cleanup.
- [ ] Repository root is intentionally organized.
- [ ] Only one active implementation specification exists.
- [ ] Previous specifications and status reports are archived or organized, not scattered.
- [ ] Generated outputs and source VODs are outside the tracked tree.
- [ ] `.local/` is documented and ignored.
- [ ] Root README contains one verified MVP workflow.
- [ ] `AGENTS.md` directs future agents to the active spec and scope lock.
- [ ] `docs/README.md` indexes current documentation.
- [ ] No secrets are present in tracked files, logs, examples, or reports.
- [ ] Existing functionality remains importable and testable.
- [ ] Final `git status --short` is empty.

### 19.2 Functional criteria

- [ ] One real Ascent VOD and one broadcast layout are used.
- [ ] One selected team and one comparison side are documented.
- [ ] At least five real rounds are configured and processed.
- [ ] Each round has minimap and canonical playback.
- [ ] Each round has raw observations and corrected-observation support.
- [ ] Each round has a zone-occupancy timeline.
- [ ] Each usable round has an opening-distribution statement.
- [ ] At least three rounds support a major-shift, regroup, or apparent-commitment statement.
- [ ] The aggregate report identifies at least one recurring pattern or truthfully reports that no pattern is established.
- [ ] Representative round IDs and timestamps support every aggregate pattern.
- [ ] Unknown intervals and low coverage are visible.
- [ ] Manual corrections can be applied and downstream outputs rebuilt without rerunning detection.

### 19.3 Usability criterion

A human reviewer, using the generated playback and reports, can answer for each usable round:

1. Where was the selected team observed during the opening?
2. Did the observed formation materially shift?
3. Which side did it shift toward?
4. Was there an apparent site commitment?
5. Was opposite-side presence positively observed, not observed with strong coverage, or unknown?

### 19.4 Non-criteria

The milestone must not be rejected solely because it lacks:

- agent identity;
- player identity;
- exact five-marker recall on every frame;
- perfect individual tracks;
- utility events;
- full HUD events;
- automatic round detection;
- an LLM summary;
- full-VOD processing;
- formal tracking benchmarks.

---

## 20. Minimalism and anti-drift rules

These rules exist specifically to prevent another infrastructure-first drift.

1. Do not add a new abstraction unless at least two active MVP components use it now.
2. Do not create generalized provider, plugin, orchestration, model-training, or cloud layers.
3. Do not add an LLM call.
4. Do not solve a five-round requirement by building a full-VOD scheduler.
5. Do not solve zone occupancy by implementing perfect identity tracking.
6. Do not expand to another map or layout.
7. Do not create hundreds of tests for hypothetical edge cases before running the five real rounds.
8. Do not describe abstention as the primary product result.
9. Do not keep large debug artifacts merely because they are available.
10. Do not continue into the next future milestone after Section 19 passes.
11. When two implementations are possible, prefer the one that produces inspectable real output sooner.
12. When a requirement is uncertain, choose the smallest evidence-preserving behavior and document the limitation.

---

## 21. Required commits

Use logical commits where repository policy permits. A recommended sequence is:

```text
checkpoint: preserve pre-mvp-reset work
chore: organize specs docs configs and local artifact policy
feat: add manual Ascent minimap movement pipeline
feat: add correction and occupancy workflow
feat: add deterministic round and aggregate movement reports
docs: record five-round MVP validation
```

Do not combine generated local outputs into commits.

Do not push unless separately requested.

---

## 22. Required final agent response

The implementation agent’s final response must use this structure:

```text
Milestone completed: VTA MVP Reset v1.0

Repository cleanup
- Branch and final commit:
- Pre-reset preservation method:
- Root files/directories after cleanup:
- Files moved:
- Files archived:
- Generated files removed or relocated:
- Final git status:

Implementation
- Source files added/changed:
- Commands added:
- Existing Valoscribe behavior affected:

Real run
- Source video identifier and SHA-256:
- Map, selected team, and side:
- Exact rounds and source intervals:
- Sample FPS:
- Runtime, peak memory if available, and output size:
- Run directory:

Results
- Per-round opening summaries:
- Per-round shift/commitment summaries:
- Aggregate recurring patterns:
- Representative timestamps:
- Corrections applied:
- Unknown/low-coverage intervals:

Verification
- Existing test results:
- New MVP test results:
- Ruff result:
- mypy result:
- Manual review completed:

Acceptance criteria
- Repository criteria: PASS/FAIL with exceptions
- Functional criteria: PASS/FAIL with exceptions
- Usability criterion: PASS/FAIL with explanation

Known limitations
- Maximum five concise items.

Recommended next milestone
- Exactly one recommendation, no implementation beyond this milestone.
```

The response must not claim completion if the real round outputs were not generated and reviewed.

---

## 23. Future work after acceptance

Only after this milestone is accepted should the project consider one next step. Reasonable candidates include:

- add stable anonymous track continuity;
- fuse manually or automatically detected round/kill/spike events;
- add one supported utility class;
- support a second map;
- support a second broadcast layout;
- add an evidence-bounded OpenAI/Gemini narrative layer.

The next step must be selected based on what limited the usefulness of the five-round result, not based on the original long-term architecture checklist.

---

## 24. Definition of done

This specification is complete when the codebase is organized, the working tree is clean, and the user can open one run directory containing five or more real Ascent rounds and see:

- the selected team’s observed minimap markers;
- canonical map positions;
- zone occupancy over time;
- corrected evidence where needed;
- per-round movement summaries;
- one aggregate recurring-pattern summary;
- honest unknowns and limitations.

That is the MVP. Everything else is later work.
