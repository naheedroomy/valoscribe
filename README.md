# Valoscribe — VALORANT MVP Reset

Valoscribe is an offline VALORANT broadcast-video analyzer. The active milestone is a small, evidence-backed Ascent team-movement MVP: show where one selected team is observed across several real rounds, with transparent coverage and corrections. It is not a live-game assistant.

## Current status

Repository reset RST-001/RST-002 is in progress. The minimap calibration and round-analysis commands below are existing tools, not the requested team-movement product. No five-round real MVP run, selected-team playback, reviewed zone timeline, or accepted tactical summary is currently claimed. See the [active specification](specs/active/MVP_RESET_AND_REPOSITORY_CLEANUP_SPEC.md) and [documentation index](docs/README.md).

## Setup

Requires Python 3.10+ and `uv`:

```bash
uv sync --dev
```

Source videos and machine-specific run data stay outside Git under `.local/` (ignored). Put source footage in `.local/media/`, local absolute-path configuration in `.local/configs/`, and generated runs in `.local/runs/`. The existing source video, if available, is local workspace data and must not be copied into the repository.

## Verified existing command

The existing CLI help entry point is:

```bash
uv run python -m valoscribe --help
```

It lists existing Valoscribe commands, including `minimap` calibration/anonymous diagnostics and `round-analysis` report generation. This command only displays the CLI interface; it does not process a real round or produce MVP movement output. Do not use synthetic VTA-704 examples as real evidence.

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
