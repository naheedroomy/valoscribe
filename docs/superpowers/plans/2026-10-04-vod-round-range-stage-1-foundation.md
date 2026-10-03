# VOD Round Range & Agent Evidence: Stage 1 Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Stage 1 foundation for VOD round-range tactical analysis, including two-team persistence contracts, source-bound round-to-time manifest contracts, fail-closed preflight validation, and the `analyze-vod` CLI subcommand with `--preflight` inspection.

**Architecture:** Extend existing single-team contracts with backward-compatible `team_id: str = "single-team"` defaults. Introduce dedicated Pydantic contracts for round manifests and two-team broadcast profiles in `valoscribe.tactical.manifest`. Implement preflight validation and execution planning in `valoscribe.tactical.preflight`. Expose these via the Typer CLI `analyze-vod` in `valoscribe.tactical.cli`.

**Tech Stack:** Python 3.10+, Pydantic v2, Typer, OpenCV, Pytest, Ruff, Mypy.

**Spec:** [`valoscribe/docs/superpowers/specs/2026-10-04-vod-round-range-stage-1-foundation-design.md`](file:///Users/naheedroomy/Documents/valorant-analyzer/valoscribe/docs/superpowers/specs/2026-10-04-vod-round-range-stage-1-foundation-design.md) (referencing [`valoscribe/specs/planned/VOD_ROUND_RANGE_AND_AGENT_EVIDENCE_SPEC.md`](file:///Users/naheedroomy/Documents/valorant-analyzer/valoscribe/specs/planned/VOD_ROUND_RANGE_AND_AGENT_EVIDENCE_SPEC.md)).

## Global Constraints

- Keep changes reviewable and preserve Valoscribe behavior for existing single-team runs and tests.
- Offline only: no network calls, API keys, or CV LLMs in tests or the core pipeline.
- Fail closed: unconfirmed, missing, or out-of-range rounds abort immediately with actionable error details; never silently skip rounds.
- Never overwrite existing run directories (`FileExistsError`).
- Use strict Pydantic models (`extra="forbid"`).
- All checks must pass before handoff:
  - `uv run --extra parquet --extra dev pytest`
  - `uv run --extra parquet --extra dev ruff check src tests`
  - `uv run --extra parquet --extra dev mypy src/valoscribe`

---

### Task 1: Two-Team Extensions to Existing Tactical Contracts

**Files:**
- Modify: `src/valoscribe/tactical/contracts.py:15-105`
- Create: `tests/test_tactical_contracts.py`

**Interfaces:**
- Consumes: Existing `Contract`, `RawMarkerObservation`, `TeamFrameState`, `CorrectionDelta`, `MarkerAdjudication`.
- Produces: Updated contracts accepting `team_id: str = "single-team"` without breaking existing serializations.

- [ ] **Step 1: Write the failing test for contract extensions and backward compatibility**

```python
# tests/test_tactical_contracts.py
from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from valoscribe.tactical.contracts import (
    CorrectionDelta,
    MarkerAdjudication,
    RawMarkerObservation,
    TeamFrameState,
)


def test_raw_marker_observation_defaults_team_id_to_single_team() -> None:
    obs = RawMarkerObservation(
        run_id="run-1",
        round_id="round-1",
        sample_index=0,
        source_timestamp_seconds=10.0,
        crop_x=50.0,
        crop_y=60.0,
        confidence=0.9,
        detector_version="v1",
    )
    assert obs.team_id == "single-team"

    # Explicit team_id
    obs_team = RawMarkerObservation(
        run_id="run-1",
        round_id="round-1",
        sample_index=0,
        source_timestamp_seconds=10.0,
        crop_x=50.0,
        crop_y=60.0,
        confidence=0.9,
        detector_version="v1",
        team_id="100T",
    )
    assert obs_team.team_id == "100T"


def test_team_frame_state_defaults_team_id() -> None:
    state = TeamFrameState(
        run_id="run-1",
        round_id="round-1",
        sample_index=0,
        source_timestamp_seconds=10.0,
        observed_marker_count=2,
        coverage_status="good",
    )
    assert state.team_id == "single-team"


def test_correction_delta_and_adjudication_defaults_team_id() -> None:
    delta = CorrectionDelta(
        correction_id="c1",
        run_id="run-1",
        round_id="round-1",
        sample_index=0,
        operation="add",
        reviewer="rev",
    )
    assert delta.team_id == "single-team"

    adjudication = MarkerAdjudication(
        adjudication_id="adj-1",
        run_id="run-1",
        round_id="round-1",
        sample_index=0,
        target_observation_id="obs-1",
        disposition="supported",
        reviewer="rev",
        source_locator="src:10",
        source_timestamp_seconds=10.0,
        confidence=1.0,
    )
    assert adjudication.team_id == "single-team"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra parquet --extra dev pytest tests/test_tactical_contracts.py -v`
Expected: FAIL with AttributeError or validation error (`team_id` unexpected or missing attribute).

- [ ] **Step 3: Modify `contracts.py` to add `team_id: str = "single-team"`**

In `src/valoscribe/tactical/contracts.py`:
- In `RawMarkerObservation`: add `team_id: str = "single-team"`
- In `TeamFrameState`: add `team_id: str = "single-team"`
- In `CorrectionDelta`: add `team_id: str = "single-team"`
- In `MarkerAdjudication`: add `team_id: str = "single-team"`

- [ ] **Step 4: Run test and existing test suite to verify passing**

Run: `uv run --extra parquet --extra dev pytest tests/test_tactical_contracts.py tests/test_tactical_mvp.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit changes**

```bash
git add src/valoscribe/tactical/contracts.py tests/test_tactical_contracts.py
git commit -m "feat(tactical): add team_id field with backward-compatible default to contracts"
```

---

### Task 2: VOD Round Manifest & Broadcast Profile Contracts

**Files:**
- Create: `src/valoscribe/tactical/manifest.py`
- Create: `tests/test_tactical_manifest.py`

**Interfaces:**
- Consumes: `CropConfig`, `TransformConfig`, `HSVRange` from `valoscribe.tactical.config`.
- Produces: `ExcludedSpan`, `TeamManifestDefinition`, `RoundManifestEntry`, `VODRoundManifest`, `TeamColorCalibration`, `VODBroadcastProfile`.

- [ ] **Step 1: Write the failing tests for manifest and profile models**

```python
# tests/test_tactical_manifest.py
import pytest
from pydantic import ValidationError

from valoscribe.tactical.config import CropConfig, HSVRange, TransformConfig
from valoscribe.tactical.manifest import (
    ExcludedSpan,
    RoundManifestEntry,
    TeamColorCalibration,
    TeamManifestDefinition,
    VODBroadcastProfile,
    VODRoundManifest,
)


def test_round_manifest_entry_validates_intervals() -> None:
    # Valid entry
    entry = RoundManifestEntry(
        map_round=1,
        round_id="map3-round1",
        source_start_seconds=100.0,
        source_end_seconds=180.0,
        live_start_seconds=115.0,
        status="confirmed",
        team_sides={"100T": "attack", "LOUD": "defense"},
        boundary_evidence="live timer 1:40 at 115s",
        excluded_spans=[
            ExcludedSpan(start_seconds=120.0, end_seconds=125.0, reason="replay")
        ],
    )
    assert entry.map_round == 1
    assert entry.status == "confirmed"

    # End before start fails
    with pytest.raises(ValidationError, match="end_seconds must be greater than start_seconds"):
        RoundManifestEntry(
            map_round=1,
            round_id="map3-round1",
            source_start_seconds=200.0,
            source_end_seconds=180.0,
            live_start_seconds=190.0,
            status="confirmed",
            team_sides={"100T": "attack", "LOUD": "defense"},
            boundary_evidence="evidence",
        )

    # Excluded span outside round interval fails
    with pytest.raises(ValidationError, match="excluded span must fall within"):
        RoundManifestEntry(
            map_round=1,
            round_id="map3-round1",
            source_start_seconds=100.0,
            source_end_seconds=180.0,
            live_start_seconds=115.0,
            status="confirmed",
            team_sides={"100T": "attack", "LOUD": "defense"},
            boundary_evidence="evidence",
            excluded_spans=[
                ExcludedSpan(start_seconds=50.0, end_seconds=60.0, reason="outside")
            ],
        )


def test_vod_round_manifest_validates_unique_rounds_and_teams() -> None:
    teams = {
        "100T": TeamManifestDefinition(
            team_id="100T",
            name="100 Thieves",
            starting_side="attack",
            broadcast_slot="left",
            broadcast_color_label="red",
        ),
        "LOUD": TeamManifestDefinition(
            team_id="LOUD",
            name="LOUD",
            starting_side="defense",
            broadcast_slot="right",
            broadcast_color_label="green",
        ),
    }

    round_1 = RoundManifestEntry(
        map_round=1,
        round_id="map3-round1",
        source_start_seconds=100.0,
        source_end_seconds=180.0,
        live_start_seconds=115.0,
        status="confirmed",
        team_sides={"100T": "attack", "LOUD": "defense"},
        boundary_evidence="evidence",
    )

    manifest = VODRoundManifest(
        schema_version=1,
        source_video_sha256="a" * 64,
        match_id="match-1",
        map_id="map3",
        map_name="ascent",
        teams=teams,
        halftime_after_round=12,
        rounds=[round_1],
        reviewer="reviewer1",
    )
    assert len(manifest.rounds) == 1

    # Duplicate map_round fails
    with pytest.raises(ValidationError, match="round numbers must be unique"):
        VODRoundManifest(
            schema_version=1,
            source_video_sha256="a" * 64,
            match_id="match-1",
            map_id="map3",
            map_name="ascent",
            teams=teams,
            rounds=[round_1, round_1],
            reviewer="reviewer1",
        )


def test_vod_broadcast_profile_validates_both_teams() -> None:
    crop = CropConfig(x=70, y=50, width=360, height=400)
    transform = TransformConfig(
        method="affine",
        input_coordinates="crop_px",
        output_coordinates="canonical_px",
        matrix=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
        training_points=4,
        training_residual_mean_rms_max_px=[0.5, 0.5, 0.5],
        calibration_status="calibrated",
    )
    calibrations = {
        "100T": TeamColorCalibration(
            team_id="100T",
            color_ranges_hsv=[HSVRange(lower=(0, 100, 100), upper=(10, 255, 255))],
        ),
        "LOUD": TeamColorCalibration(
            team_id="LOUD",
            color_ranges_hsv=[HSVRange(lower=(40, 100, 100), upper=(80, 255, 255))],
        ),
    }
    profile = VODBroadcastProfile(
        profile_id="ascent-vct-2024",
        calibration_status="calibrated",
        minimap_crop=crop,
        transform=transform,
        team_calibrations=calibrations,
    )
    assert "100T" in profile.team_calibrations
    assert "LOUD" in profile.team_calibrations
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra parquet --extra dev pytest tests/test_tactical_manifest.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'valoscribe.tactical.manifest'`.

- [ ] **Step 3: Implement `valoscribe.tactical.manifest`**

Create `src/valoscribe/tactical/manifest.py`:
- Implement `ExcludedSpan(StrictModel)` with `start_seconds`, `end_seconds`, `reason`, and validator `end_seconds > start_seconds`.
- Implement `TeamManifestDefinition(StrictModel)` with `team_id`, `name`, `starting_side: Literal["attack", "defense"]`, `broadcast_slot`, `broadcast_color_label`.
- Implement `RoundManifestEntry(StrictModel)` with `map_round`, `round_id`, `source_start_seconds`, `source_end_seconds`, `live_start_seconds`, `status: Literal["confirmed", "unresolved", "missing", "excluded"]`, `team_sides`, `boundary_evidence`, `excluded_spans`, with ordering and boundary validators.
- Implement `VODRoundManifest(StrictModel)` with `schema_version`, `source_video_sha256`, `match_id`, `map_id`, `map_name`, `teams`, `halftime_after_round`, `rounds`, `reviewer`, `review_method`, `notes`, with uniqueness validators for `map_round` and `round_id` and check that team sides match manifest teams.
- Implement `TeamColorCalibration(StrictModel)` with `team_id`, `color_ranges_hsv: list[HSVRange]`.
- Implement `VODBroadcastProfile(StrictModel)` with `profile_id`, `calibration_status`, `minimap_crop`, `transform`, `team_calibrations: dict[str, TeamColorCalibration]`.
- Add helper functions: `load_manifest(path: Path) -> VODRoundManifest` and `load_profile(path: Path) -> VODBroadcastProfile`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --extra parquet --extra dev pytest tests/test_tactical_manifest.py -v`
Expected: PASS.

- [ ] **Step 5: Commit changes**

```bash
git add src/valoscribe/tactical/manifest.py tests/test_tactical_manifest.py
git commit -m "feat(tactical): add typed contracts for VOD round manifest and broadcast profile"
```

---

### Task 3: Preflight Validation Engine & Execution Plan

**Files:**
- Create: `src/valoscribe/tactical/preflight.py`
- Create: `tests/test_tactical_preflight.py`

**Interfaces:**
- Consumes: `VODRoundManifest`, `VODBroadcastProfile` from `valoscribe.tactical.manifest`.
- Produces: `validate_vod_preflight()`, `VODExecutionPlan`, `ResolvedRoundPlan`, `PreflightValidationError`, `RoundRangeResolutionError`.

- [ ] **Step 1: Write the failing tests for preflight validation**

```python
# tests/test_tactical_preflight.py
from pathlib import Path
import pytest

from valoscribe.tactical.config import CropConfig, HSVRange, TransformConfig
from valoscribe.tactical.manifest import (
    ExcludedSpan,
    RoundManifestEntry,
    TeamColorCalibration,
    TeamManifestDefinition,
    VODBroadcastProfile,
    VODRoundManifest,
)
from valoscribe.tactical.preflight import (
    PreflightValidationError,
    RoundRangeResolutionError,
    validate_vod_preflight,
)


@pytest.fixture
def sample_profile() -> VODBroadcastProfile:
    return VODBroadcastProfile(
        profile_id="ascent-vct-2024",
        calibration_status="calibrated",
        minimap_crop=CropConfig(x=70, y=50, width=360, height=400),
        transform=TransformConfig(
            method="affine",
            input_coordinates="crop_px",
            output_coordinates="canonical_px",
            matrix=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
            training_points=4,
            training_residual_mean_rms_max_px=[0.5, 0.5, 0.5],
            calibration_status="calibrated",
        ),
        team_calibrations={
            "100T": TeamColorCalibration(
                team_id="100T",
                color_ranges_hsv=[HSVRange(lower=(0, 100, 100), upper=(10, 255, 255))],
            ),
            "LOUD": TeamColorCalibration(
                team_id="LOUD",
                color_ranges_hsv=[HSVRange(lower=(40, 100, 100), upper=(80, 255, 255))],
            ),
        },
    )


@pytest.fixture
def sample_manifest() -> VODRoundManifest:
    teams = {
        "100T": TeamManifestDefinition(
            team_id="100T",
            name="100 Thieves",
            starting_side="attack",
            broadcast_slot="left",
            broadcast_color_label="red",
        ),
        "LOUD": TeamManifestDefinition(
            team_id="LOUD",
            name="LOUD",
            starting_side="defense",
            broadcast_slot="right",
            broadcast_color_label="green",
        ),
    }
    rounds = [
        RoundManifestEntry(
            map_round=i,
            round_id=f"map3-round{i}",
            source_start_seconds=100.0 * i,
            source_end_seconds=100.0 * i + 80.0,
            live_start_seconds=100.0 * i + 15.0,
            status="confirmed" if i != 8 else "unresolved",
            team_sides={"100T": "attack", "LOUD": "defense"} if i <= 12 else {"100T": "defense", "LOUD": "attack"},
            boundary_evidence=f"evidence {i}",
        )
        for i in range(1, 15)
    ]
    return VODRoundManifest(
        schema_version=1,
        source_video_sha256="0123456789abcdef" * 4,
        match_id="match-1",
        map_id="map3",
        map_name="ascent",
        teams=teams,
        halftime_after_round=12,
        rounds=rounds,
        reviewer="rev",
    )


def test_preflight_success_with_halftime_range(
    tmp_path: Path, sample_manifest: VODRoundManifest, sample_profile: VODBroadcastProfile
) -> None:
    fake_vod = tmp_path / "video.mp4"
    fake_vod.write_bytes(b"dummy video content")
    output_dir = tmp_path / "output_run"

    plan = validate_vod_preflight(
        vod_path=fake_vod,
        map_name="ascent",
        match_id="match-1",
        map_id="map3",
        from_round=11,
        to_round=14,
        selected_team_id="100T",
        manifest=sample_manifest,
        profile=sample_profile,
        output_dir=output_dir,
        verify_sha256=False,
    )
    assert plan.selected_team_id == "100T"
    assert plan.opponent_team_id == "LOUD"
    assert len(plan.selected_rounds) == 4
    # Round 11: 100T is attack; Round 13 (after halftime): 100T is defense
    assert plan.selected_rounds[0].selected_team_side == "attack"
    assert plan.selected_rounds[2].selected_team_side == "defense"


def test_preflight_fails_on_unconfirmed_or_missing_round(
    tmp_path: Path, sample_manifest: VODRoundManifest, sample_profile: VODBroadcastProfile
) -> None:
    fake_vod = tmp_path / "video.mp4"
    fake_vod.write_bytes(b"dummy")
    output_dir = tmp_path / "output_run"

    # Range [7, 9] includes round 8 which has status="unresolved"
    with pytest.raises(RoundRangeResolutionError) as exc_info:
        validate_vod_preflight(
            vod_path=fake_vod,
            map_name="ascent",
            match_id="match-1",
            map_id="map3",
            from_round=7,
            to_round=9,
            selected_team_id="100T",
            manifest=sample_manifest,
            profile=sample_profile,
            output_dir=output_dir,
            verify_sha256=False,
        )
    assert "Round 8 is 'unresolved'" in str(exc_info.value)


def test_preflight_fails_when_output_dir_exists(
    tmp_path: Path, sample_manifest: VODRoundManifest, sample_profile: VODBroadcastProfile
) -> None:
    fake_vod = tmp_path / "video.mp4"
    fake_vod.write_bytes(b"dummy")
    output_dir = tmp_path / "output_run"
    output_dir.mkdir()
    (output_dir / "existing.txt").write_text("hello")

    with pytest.raises(FileExistsError, match="Refusing to overwrite existing output"):
        validate_vod_preflight(
            vod_path=fake_vod,
            map_name="ascent",
            match_id="match-1",
            map_id="map3",
            from_round=1,
            to_round=3,
            selected_team_id="100T",
            manifest=sample_manifest,
            profile=sample_profile,
            output_dir=output_dir,
            verify_sha256=False,
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra parquet --extra dev pytest tests/test_tactical_preflight.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'valoscribe.tactical.preflight'`.

- [ ] **Step 3: Implement `valoscribe.tactical.preflight`**

Create `src/valoscribe/tactical/preflight.py`:
- Define `PreflightValidationError(ValueError)` and `RoundRangeResolutionError(PreflightValidationError)`.
- Define `ResolvedRoundPlan(StrictModel)`:
  - `map_round: int`
  - `round_id: str`
  - `source_interval_seconds: tuple[float, float]`
  - `live_start_offset_seconds: float`
  - `selected_team_side: Literal["attack", "defense"]`
  - `opponent_team_side: Literal["attack", "defense"]`
  - `boundary_evidence: str`
  - `excluded_intervals: list[dict[str, Any]]`
- Define `VODExecutionPlan(StrictModel)`:
  - `match_id: str`
  - `map_id: str`
  - `map_name: str`
  - `source_video_path: Path`
  - `source_video_sha256: str`
  - `selected_team_id: str`
  - `opponent_team_id: str`
  - `minimap_crop: CropConfig`
  - `transform: TransformConfig`
  - `selected_team_calibrations: list[HSVRange]`
  - `opponent_team_calibrations: list[HSVRange]`
  - `selected_rounds: list[ResolvedRoundPlan]`
  - `output_dir: Path`
- Implement `validate_vod_preflight(...)`:
  - Check VOD file exists.
  - If `verify_sha256=True`, compute file SHA-256 in 64KB chunks and compare to `manifest.source_video_sha256`. Raise `PreflightValidationError` on mismatch.
  - Check `map_name == "ascent"` and `manifest.map_name == "ascent"`.
  - Check `selected_team_id in manifest.teams`.
  - Determine `opponent_team_id` (remaining team in `manifest.teams`).
  - Check both teams are in `profile.team_calibrations`.
  - Check `from_round <= to_round`.
  - Verify every round in `range(from_round, to_round + 1)` exists in `manifest.rounds` and has `status == "confirmed"`. If any fail, raise `RoundRangeResolutionError` with itemized list.
  - Check `output_dir`: if exists and not empty, raise `FileExistsError`.
  - Return compiled `VODExecutionPlan`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --extra parquet --extra dev pytest tests/test_tactical_preflight.py -v`
Expected: PASS.

- [ ] **Step 5: Commit changes**

```bash
git add src/valoscribe/tactical/preflight.py tests/test_tactical_preflight.py
git commit -m "feat(tactical): implement preflight validation engine and execution planning"
```

---

### Task 4: Example Fixtures for Ascent Map 3

**Files:**
- Create: `configs/examples/ascent-map3-rounds.example.json`
- Create: `configs/examples/ascent-vct-profile.example.json`
- Modify: `tests/test_tactical_manifest.py`

**Interfaces:**
- Consumes: `load_manifest`, `load_profile`.
- Produces: Tested, reusable manifest and profile matching the local Grand Final Ascent VOD (`YTDown.com_YouTube_Media_4LEGEQ8KBS0_100T-vs-LOUD-VCT-Americas-Stage-2-Playoffs-Grand-Final-Map-3-Ascent_001_1080p.mp4`).

- [ ] **Step 1: Write the test verifying example fixtures**

Add to `tests/test_tactical_manifest.py`:
```python
def test_example_manifest_and_profile_fixtures_load() -> None:
    from pathlib import Path
    from valoscribe.tactical.manifest import load_manifest, load_profile

    root = Path(__file__).parents[1]
    manifest_path = root / "configs/examples/ascent-map3-rounds.example.json"
    profile_path = root / "configs/examples/ascent-vct-profile.example.json"

    assert manifest_path.is_file()
    assert profile_path.is_file()

    manifest = load_manifest(manifest_path)
    assert manifest.map_name == "ascent"
    assert "100T" in manifest.teams
    assert "LOUD" in manifest.teams
    assert len(manifest.rounds) >= 5

    profile = load_profile(profile_path)
    assert "100T" in profile.team_calibrations
    assert "LOUD" in profile.team_calibrations
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra parquet --extra dev pytest tests/test_tactical_manifest.py::test_example_manifest_and_profile_fixtures_load -v`
Expected: FAIL with `AssertionError: assert manifest_path.is_file()`.

- [ ] **Step 3: Create the example fixture files**

1. Create `configs/examples/ascent-map3-rounds.example.json`:
   - Bind to VOD SHA `a2feb25b842b6c1c2baa17f8ef0c5ecfe1816bd058a1c256350fa95900454c44`.
   - Teams: `100T` (attack start), `LOUD` (defense start).
   - Rounds: Map 3 rounds 4, 5, 6, 7, 9 (confirmed intervals from `mvp-real-round-validation.md` with exact live start offsets, exclusion spans for round 9 replay).
   - Reviewer and boundary evidence notes.

2. Create `configs/examples/ascent-vct-profile.example.json`:
   - Crop: `x: 70, y: 50, width: 360, height: 400`.
   - Transform: matrix from existing `configs/examples/ascent-team-movement.example.yaml`.
   - Team calibrations:
     - `100T`: HSV ranges for red/orange markers.
     - `LOUD`: HSV ranges for green markers.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --extra parquet --extra dev pytest tests/test_tactical_manifest.py::test_example_manifest_and_profile_fixtures_load -v`
Expected: PASS.

- [ ] **Step 5: Commit changes**

```bash
git add configs/examples/ascent-map3-rounds.example.json configs/examples/ascent-vct-profile.example.json tests/test_tactical_manifest.py
git commit -m "feat(tactical): add validated example manifest and profile fixtures for Ascent Map 3"
```

---

### Task 5: `analyze-vod` CLI Subcommand with `--preflight` Inspection

**Files:**
- Modify: `src/valoscribe/tactical/cli.py`
- Create: `tests/test_tactical_analyze_vod.py`

**Interfaces:**
- Consumes: `validate_vod_preflight` from `valoscribe.tactical.preflight`, `load_manifest`, `load_profile` from `valoscribe.tactical.manifest`.
- Produces: CLI subcommand `analyze-vod`.

- [ ] **Step 1: Write the failing tests for `analyze-vod` CLI**

```python
# tests/test_tactical_analyze_vod.py
import json
from pathlib import Path
from typer.testing import CliRunner

from valoscribe.tactical.cli import app

runner = CliRunner()


def test_analyze_vod_preflight_success(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    manifest_path = root / "configs/examples/ascent-map3-rounds.example.json"
    profile_path = root / "configs/examples/ascent-vct-profile.example.json"
    fake_vod = tmp_path / "vod.mp4"
    fake_vod.write_bytes(b"dummy video")
    output_dir = tmp_path / "run_out"

    result = runner.invoke(
        app,
        [
            "analyze-vod",
            "--vod", str(fake_vod),
            "--map", "ascent",
            "--match", "vct-americas-grand-final",
            "--map-id", "map3",
            "--from-round", "4",
            "--to-round", "7",
            "--team", "100T",
            "--profile", str(profile_path),
            "--round-manifest", str(manifest_path),
            "--output", str(output_dir),
            "--preflight",
            "--no-verify-sha",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Preflight validation PASSED" in result.output
    assert "Selected Team: 100T" in result.output
    assert "Opponent: LOUD" in result.output


def test_analyze_vod_missing_round_failure(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    manifest_path = root / "configs/examples/ascent-map3-rounds.example.json"
    profile_path = root / "configs/examples/ascent-vct-profile.example.json"
    fake_vod = tmp_path / "vod.mp4"
    fake_vod.write_bytes(b"dummy video")
    output_dir = tmp_path / "run_out"

    # Requesting round 8, which is not in the confirmed 5-round example
    result = runner.invoke(
        app,
        [
            "analyze-vod",
            "--vod", str(fake_vod),
            "--map", "ascent",
            "--match", "vct-americas-grand-final",
            "--map-id", "map3",
            "--from-round", "4",
            "--to-round", "8",
            "--team", "100T",
            "--profile", str(profile_path),
            "--round-manifest", str(manifest_path),
            "--output", str(output_dir),
            "--preflight",
            "--no-verify-sha",
        ],
    )
    assert result.exit_code != 0
    assert "unconfirmed or missing" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra parquet --extra dev pytest tests/test_tactical_analyze_vod.py -v`
Expected: FAIL with `Error: No such command 'analyze-vod'`.

- [ ] **Step 3: Implement `analyze-vod` in `src/valoscribe/tactical/cli.py`**

In `src/valoscribe/tactical/cli.py`:
- Add `@app.command("analyze-vod")` with parameters:
  - `vod: Path = typer.Option(..., "--vod", exists=True, dir_okay=False)`
  - `map_name: str = typer.Option(..., "--map")`
  - `match_id: str = typer.Option(..., "--match")`
  - `map_id: str = typer.Option(..., "--map-id")`
  - `from_round: int = typer.Option(..., "--from-round", min=1)`
  - `to_round: int = typer.Option(..., "--to-round", min=1)`
  - `team: str = typer.Option(..., "--team")`
  - `profile_path: Path = typer.Option(..., "--profile", exists=True, dir_okay=False)`
  - `round_manifest_path: Path = typer.Option(..., "--round-manifest", exists=True, dir_okay=False)`
  - `output: Path = typer.Option(..., "--output", file_okay=False)`
  - `preflight: bool = typer.Option(True, "--preflight/--no-preflight")`
  - `verify_sha: bool = typer.Option(True, "--verify-sha/--no-verify-sha")`
- Load manifest and profile via `load_manifest` and `load_profile`.
- Call `validate_vod_preflight(...)`.
- Catch `(PreflightValidationError, RoundRangeResolutionError, FileExistsError)` and report actionable user-facing error via `typer.BadParameter` or `typer.echo` + `raise typer.Exit(1)`.
- If `preflight` is True:
  - Print formatted JSON of `plan`.
  - Print human-readable ASCII summary table with columns: `Round`, `Map Round`, `Start (s)`, `End (s)`, `Live Start (s)`, `Selected Side`, `Opponent Side`, `Exclusions`.
  - Exit 0.
- If `preflight` is False:
  - Create output directory and save `execution-plan.json`.
  - Echo informative message that Stage 1 foundation is complete and outputs are ready for Stage 2 baseline extraction.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --extra parquet --extra dev pytest tests/test_tactical_analyze_vod.py -v`
Expected: PASS.

- [ ] **Step 5: Commit changes**

```bash
git add src/valoscribe/tactical/cli.py tests/test_tactical_analyze_vod.py
git commit -m "feat(tactical): add analyze-vod CLI subcommand with preflight inspection mode"
```

---

### Task 6: Real VOD Smoke Check & Comprehensive Verification Gates

**Files:**
- Test against real local VOD: `../VOD/YTDown.com_YouTube_Media_4LEGEQ8KBS0_100T-vs-LOUD-VCT-Americas-Stage-2-Playoffs-Grand-Final-Map-3-Ascent_001_1080p.mp4`

- [ ] **Step 1: Run `analyze-vod --preflight` on real local VOD fixture**

Run command:
```bash
uv run --extra parquet python -m valoscribe tactical analyze-vod \
  --vod ../VOD/YTDown.com_YouTube_Media_4LEGEQ8KBS0_100T-vs-LOUD-VCT-Americas-Stage-2-Playoffs-Grand-Final-Map-3-Ascent_001_1080p.mp4 \
  --map ascent \
  --match vct-americas-2024-stage-2-gf \
  --map-id map3 \
  --from-round 4 \
  --to-round 7 \
  --team 100T \
  --profile configs/examples/ascent-vct-profile.example.json \
  --round-manifest configs/examples/ascent-map3-rounds.example.json \
  --output .local/runs/test-preflight-smoke \
  --preflight \
  --verify-sha
```
Expected: Preflight validation PASSED, SHA verified against real VOD, ASCII plan rendered, exits 0.

- [ ] **Step 2: Run full repository test suite**

Run: `uv run --extra parquet --extra dev pytest`
Expected: All tests PASS.

- [ ] **Step 3: Run linter check**

Run: `uv run --extra parquet --extra dev ruff check src tests`
Expected: All checks PASS with zero errors.

- [ ] **Step 4: Run type check**

Run: `uv run --extra parquet --extra dev mypy src/valoscribe`
Expected: Success: no issues found.

- [ ] **Step 5: Commit any final test cleanups and push branch**

```bash
git push origin mvp-reset/minimap-team-movement
```
