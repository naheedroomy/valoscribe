# Valoscribe — VALORANT MVP Reset

Valoscribe is an offline VALORANT broadcast-video analyzer. The active milestone is a small, evidence-backed Ascent team-movement MVP: show where one selected team is observed across several real rounds, with transparent coverage and corrections. It is not a live-game assistant.

## Current status

RST-001/RST-002 are accepted. The Ascent crop and approximate zone geometry have parent-agent visual review for manual team-shape development only; this is not user approval, official geometry, or quantitative registration accuracy. MVP-004 adds deterministic per-round and aggregate candidate reports, occupancy exports, and report regeneration in immutable correction revisions. Source candidates remain partially observed and need human review/correction; real-round product acceptance is pending. See the [active specification](specs/active/MVP_RESET_AND_REPOSITORY_CLEANUP_SPEC.md), [calibration evidence](docs/status/mvp001-calibration-candidate.md), [movement-report interpretation](docs/guides/interpreting-movement-reports.md), and [documentation index](docs/README.md).

## Setup

Requires Python 3.10+ and `uv`:

```bash
uv sync --dev
```

Source videos and machine-specific run data stay outside Git under `.local/` (ignored). Put source footage in `.local/media/`, local absolute-path configuration in `.local/configs/`, and generated runs in `.local/runs/`. The existing source video, if available, is local workspace data and must not be copied into the repository.

## Offline team-shape commands

Configure a local source path under `.local/configs/` and inspect before analysis:

```bash
uv run python -m valoscribe tactical inspect --config .local/configs/ascent-team-movement-mvp001.yaml
uv run python -m valoscribe tactical analyze --config .local/configs/ascent-team-movement-mvp001.yaml
uv run python -m valoscribe tactical rebuild --run-dir .local/runs/ascent-team-movement-mvp002-r3
```

`inspect` writes local calibration artifacts; `analyze` refuses to overwrite an existing run and processes only configured intervals. The `rebuild` example was run against the existing five-round local run: it generated a new immutable derived report revision without marker detection. Outputs remain under `.local/runs/<run_id>/`; each round includes occupancy CSV/Parquet and evidence-linked summary JSON/Markdown, and the run includes aggregate JSON/Markdown/CSV/representative-round outputs. Candidate color detections are not accepted ground truth, partial coverage is not absence evidence, and summaries do not establish complete-team presence or intent. See [run instructions](docs/guides/running-team-shape-mvp.md), [correction/rebuild instructions](docs/guides/correcting-detections.md), and [report interpretation](docs/guides/interpreting-movement-reports.md).

## Development checks

```bash
uv run pytest
uv run ruff check src tests
uv run mypy src/valoscribe
```

## Project map

- [Active reset specification](specs/active/MVP_RESET_AND_REPOSITORY_CLEANUP_SPEC.md)
- [Agent scope and safety instructions](AGENTS.md)
- [Documentation index](docs/README.md)
- [Code/config layout](docs/architecture/code-layout.md)
- [Pre-reset inventory](docs/status/pre-reset-repository-inventory.md)
- [Cleanup report and verified gates](docs/status/repository-cleanup-report.md)

The upstream Valoscribe MIT license and attribution are retained.
