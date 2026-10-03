# Valoscribe — VALORANT MVP Reset

Valoscribe is an offline VALORANT broadcast-video analyzer. The active milestone is a small, evidence-backed Ascent team-movement MVP: show where one selected team is observed across several real rounds, with transparent coverage and corrections. It is not a live-game assistant.

## Current status

RST-001/RST-002 are accepted. The Ascent crop and approximate zone geometry have bounded visual review for manual team-shape development only; this is not user approval, official geometry, or quantitative registration accuracy. MVP-004 adds deterministic per-round and aggregate candidate reports, occupancy exports, and report regeneration in immutable correction revisions. Five selected real-round openings and three approximate apparent commitments have bounded source-backed review and are accepted as partial observed evidence only; movement shifts, regroup directions, opposite-side absence, and complete-team claims remain unknown or unestablished. See the [five-round validation record](docs/status/mvp-real-round-validation.md) for scope and limitations. See the [active specification](specs/active/MVP_RESET_AND_REPOSITORY_CLEANUP_SPEC.md), [calibration evidence](docs/status/mvp001-calibration-candidate.md), [movement-report interpretation](docs/guides/interpreting-movement-reports.md), and [documentation index](docs/README.md).

## Setup

Requires Python 3.10+ and `uv`:

```bash
uv sync --extra parquet --extra dev
```

Source videos and machine-specific run data stay outside Git under `.local/` (ignored). Put source footage in `.local/media/`, local absolute-path configuration in `.local/configs/`, and generated runs in `.local/runs/`. The existing source video, if available, is local workspace data and must not be copied into the repository.

## Offline team-shape workflow

Use an editable local copy of the example; do not rely on a checked-in or machine-specific run:

```bash
mkdir -p .local/configs
cp configs/examples/ascent-team-movement.example.yaml .local/configs/ascent-local.yaml
# Edit .local/configs/ascent-local.yaml: set a unique run_id, source.video_path,
# the matching source SHA-256, and source-specific broadcast crop/color/transform
# after inspecting the selected local VOD. The included Ascent values are candidates.
uv run --extra parquet python -m valoscribe tactical inspect --config .local/configs/ascent-local.yaml
uv run --extra parquet python -m valoscribe tactical analyze --config .local/configs/ascent-local.yaml
```

`inspect` writes local calibration artifacts; inspect crop/transform against the actual source before processing. `analyze` refuses to overwrite a run and processes only manually configured intervals. Choose a fresh run ID; never remove old evidence to reuse one. For reviewed corrections, use the append-only controls in [correction instructions](docs/guides/correcting-detections.md), then rebuild its derived reports without rerunning detection:

```bash
uv run --extra parquet valoscribe tactical rebuild --run-dir .local/runs/<your-run-id>
```

The current bounded evidence run is [documented here](docs/status/mvp-real-round-validation.md): `.local/runs/ascent-team-movement-mvp005-continuation-r1`. It is partial evidence, not a portable input or acceptance fixture. Verified executions are also recorded locally: inspect `.local/runs/ascent-readme-verification-20261003-r1-inspect/inspect.json`; analyze `.local/runs/ascent-team-movement-mvp002-r3/logs/run.log` (35.212123 s, 1,188 samples); and correction-only rebuild `.local/runs/ascent-team-movement-mvp005-continuation-r1/continuation-rebuild-audit.json` (102.76 s; detector not invoked). These ignored `.local/` records are machine-local evidence, not repository fixtures. Each round provides minimap/canonical MP4 playback, raw observations, correction history, occupancy, and evidence-linked summaries. Candidate color detections are not accepted ground truth; partial coverage is not absence; summaries do not establish full-team presence or intent. See [full run instructions](docs/guides/running-team-shape-mvp.md), [report interpretation](docs/guides/interpreting-movement-reports.md), and [documentation index](docs/README.md).

## Development checks

```bash
uv run --extra parquet --extra dev pytest
uv run --extra parquet --extra dev ruff check src tests
uv run --extra parquet --extra dev mypy src/valoscribe
```

## Project map

- [Active reset specification](specs/active/MVP_RESET_AND_REPOSITORY_CLEANUP_SPEC.md)
- [Agent scope and safety instructions](AGENTS.md)
- [Documentation index](docs/README.md)
- [Code/config layout](docs/architecture/code-layout.md)
- [Pre-reset inventory](docs/status/pre-reset-repository-inventory.md)
- [Cleanup report and verified gates](docs/status/repository-cleanup-report.md)

The upstream Valoscribe MIT license and attribution are retained.
