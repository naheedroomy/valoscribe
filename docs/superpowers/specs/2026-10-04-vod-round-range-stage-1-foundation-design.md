# VOD Round Range & Agent Evidence: Stage 1 Foundation Design

- **Status**: Proposed / Approved by User
- **Date**: 2026-10-04
- **Related Spec**: `valoscribe/specs/planned/VOD_ROUND_RANGE_AND_AGENT_EVIDENCE_SPEC.md`
- **Scope**: Stage 1 (Range/Profile Foundation, Two-Team Contracts, Preflight Validation, and `analyze-vod` CLI Entrypoint)

## 1. Background & Objectives

The `VOD_ROUND_RANGE_AND_AGENT_EVIDENCE_SPEC.md` defines an end-to-end workflow to take a local VOD, an inclusive round range, and team identifiers, reconstruct movement sequences for both teams on the supported Ascent spectator layout, and produce a portable evidence bundle for natural language consumption by external LLM agents.

Stage 1 establishes the typed foundations and preflight validation:
1. Reusable, SHA-256 bound round-to-time manifest format.
2. Two-team persistence data contracts with backward compatibility for legacy single-team runs.
3. Preflight validation enforcing fail-closed checks for missing/unconfirmed rounds, SHA mismatches, and independent two-team color calibration.
4. An `analyze-vod` CLI command supporting `--preflight` dry-run inspection and execution planning.

## 2. Architecture & Components

```
valoscribe/
  src/valoscribe/tactical/
    contracts.py       # Extended with team_id defaults for backward compatibility
    manifest.py        # New: VODRoundManifest, TeamManifestDefinition, RoundManifestEntry, Profile
    preflight.py       # New: Preflight validation, round range resolution, VODExecutionPlan
    cli.py             # Extended: analyze-vod command with --preflight flag
  configs/examples/
    ascent-map3-rounds.example.json   # Validated sample manifest for Map 3 Ascent VOD
    ascent-profile.example.json       # Validated sample two-team calibration profile
  tests/tactical/
    test_contracts.py                 # Backward compatibility checks
    test_manifest_contracts.py        # Manifest schema & validation tests
    test_preflight.py                 # Range resolution, fail-closed missing round tests
    test_cli_analyze_vod.py           # CLI invocation & error handling tests
```

## 3. Data Contracts

### 3.1 Extensions to `valoscribe.tactical.contracts`
To support two teams while preserving all existing saved runs and test fixtures, add `team_id: str = "single-team"`:
- `RawMarkerObservation`: add `team_id: str = "single-team"`
- `TeamFrameState`: add `team_id: str = "single-team"`
- `CorrectionDelta`: add `team_id: str = "single-team"`
- `MarkerAdjudication`: add `team_id: str = "single-team"`

Legacy single-team data remains tagged as `"single-team"` and cannot be conflated with opponent data.

### 3.2 New Contracts in `valoscribe.tactical.manifest`

#### `ExcludedSpan`
- `start_seconds: float` (ge=0)
- `end_seconds: float` (gt=start_seconds)
- `reason: str` (min_length=1)

#### `TeamManifestDefinition`
- `team_id: str` (e.g. `"100T"`)
- `name: str` (e.g. `"100 Thieves"`)
- `starting_side: Literal["attack", "defense"]`
- `broadcast_slot: str` (e.g. `"left"`)
- `broadcast_color_label: str` (e.g. `"red"`)

#### `RoundManifestEntry`
- `map_round: int = Field(ge=1)`
- `round_id: str = Field(min_length=1)`
- `source_start_seconds: float = Field(ge=0)`
- `source_end_seconds: float = Field(gt=0)`
- `live_start_seconds: float = Field(ge=0)`
- `status: Literal["confirmed", "unresolved", "missing", "excluded"] = "confirmed"`
- `team_sides: dict[str, Literal["attack", "defense"]]`
- `boundary_evidence: str` (e.g. `"live timer 1:39 at 263s after freeze countdown"`)
- `excluded_spans: list[ExcludedSpan] = Field(default_factory=list)`

Validators:
- `source_end_seconds > source_start_seconds`
- `source_start_seconds <= live_start_seconds < source_end_seconds`
- Any `excluded_spans` must lie within `[source_start_seconds, source_end_seconds]`

#### `VODRoundManifest`
- `schema_version: Literal[1] = 1`
- `source_video_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")`
- `match_id: str`
- `map_id: str`
- `map_name: str` (initially constrained to `"ascent"`)
- `teams: dict[str, TeamManifestDefinition]` (must contain at least 2 teams)
- `halftime_after_round: int = 12`
- `rounds: list[RoundManifestEntry]`
- `reviewer: str`
- `review_method: Literal["manual_confirmation", "candidate_index"] = "manual_confirmation"`
- `notes: str | None = None`

Validators:
- `rounds` must have unique `map_round` numbers and unique `round_id` strings.
- `teams` must include entries matching all keys referenced in `RoundManifestEntry.team_sides`.

#### `VODBroadcastProfile`
- `profile_id: str`
- `calibration_status: str`
- `minimap_crop: CropConfig`
- `transform: TransformConfig`
- `team_calibrations: dict[str, list[HSVRange]]` (must contain separate HSV ranges for each team)

## 4. Preflight Validation & Execution Planning (`valoscribe.tactical.preflight`)

### 4.1 Validation Rules
1. **VOD Integrity**:
   - Verify `video_path` exists on disk.
   - If `compute_sha256=True`, compute file SHA-256 and assert equality with `manifest.source_video_sha256`. Raise actionable error on mismatch.
2. **Map & Layout**:
   - Assert `map_name == "ascent"` and matches `manifest.map_name`.
   - Assert `minimap_crop` coordinates fit inside expected broadcast resolution (e.g. 1920x1080).
3. **Teams & Calibrations**:
   - Assert requested `--team` is in `manifest.teams`.
   - Identify opponent team (`set(manifest.teams.keys()) - {selected_team}`).
   - Assert both `selected_team` and `opponent_team` have entries in `profile.team_calibrations`.
4. **Inclusive Round Range Resolution**:
   - Assert `from_round <= to_round`.
   - For every integer `r` in `range(from_round, to_round + 1)`:
     - Find matching entry in `manifest.rounds`. If not found, fail closed.
     - Check `entry.status == "confirmed"`. If `status != "confirmed"`, fail closed.
   - Collect any missing or unconfirmed rounds; if any exist, raise `RoundRangeResolutionError` detailing every unconfirmed round number, its status, and boundary anchor.
5. **Output Collision Guard**:
   - If `output_dir.exists()` and contains files/subdirectories, raise `FileExistsError` refusing to overwrite existing run.

### 4.2 Execution Plan Output (`VODExecutionPlan`)
On preflight success, compile:
- `match_id`, `map_id`, `map_name`
- `selected_team_id`, `opponent_team_id`
- `minimap_crop`, `transform`
- `selected_rounds`: list of resolved round execution specs (timestamps, sides, exclusions)
- `calibrations`: `{team_id: list[HSVRange]}`

## 5. CLI Command Specification

### `analyze-vod`
```text
uv run --extra parquet python -m valoscribe tactical analyze-vod \
  --vod <path> \
  --map <map-name> \
  --match <match-id> \
  --map-id <map-instance> \
  --from-round <first-inclusive> \
  --to-round <last-inclusive> \
  --team <stable-team-id> \
  --profile <calibrated-profile.json> \
  --round-manifest <confirmed-rounds.json> \
  --output <new-output-directory> \
  [--preflight / --no-preflight]
```

Behavior:
- Parses arguments and loads manifest and profile.
- Calls `validate_vod_preflight(...)`.
- If `--preflight` is passed:
  - Formats and echoes the `VODExecutionPlan` in JSON.
  - Displays a clean ASCII summary table of resolved rounds and sides.
  - Exits with status `0`.
- If `--no-preflight` is passed:
  - In Stage 1, creates output directory, persists `execution-plan.json`, and informs user that Stage 1 foundation is verified and ready for Stage 2 baseline extraction.

## 6. Testing & Quality Gates

1. **Contracts Test Suite (`tests/tactical/test_manifest_contracts.py`)**:
   - Validate valid manifest loading.
   - Validate rejection of invalid intervals, negative timestamps, bad SHA strings, and unconfirmed states.
   - Verify existing tests in `test_contracts.py` pass without regression.
2. **Preflight Test Suite (`tests/tactical/test_preflight.py`)**:
   - Test successful plan compilation for contiguous rounds.
   - Test halftime side flip verification.
   - Test failure cases: missing VOD, SHA mismatch, missing rounds, unconfirmed rounds, uncalibrated opponent team, existing output directory.
3. **CLI Test Suite (`tests/tactical/test_cli_analyze_vod.py`)**:
   - Test Typer runner invocation with `--preflight`.
   - Test handling of CLI error parameters.
4. **Fixture Smoke Test**:
   - Smoke test against `VOD/YTDown.com_YouTube_Media_4LEGEQ8KBS0_100T-vs-LOUD-VCT-Americas-Stage-2-Playoffs-Grand-Final-Map-3-Ascent_001_1080p.mp4` using `configs/examples/ascent-map3-rounds.example.json`.
5. **Quality Checks**:
   - `uv run --extra parquet --extra dev pytest`
   - `uv run --extra parquet --extra dev ruff check src tests`
   - `uv run --extra parquet --extra dev mypy src/valoscribe`

## 7. Non-Goals for Stage 1

- Automatic CV round detection / OCR scoreboard reading (manifest is source-grounded and manually confirmed).
- Complete two-team video decoding and trajectory linking (handled in Stage 2).
- Portable zip bundle packaging and LLM agent entrypoint (handled in Stage 3).
- Arbitrary broadcast layouts beyond Ascent spectator layout.
