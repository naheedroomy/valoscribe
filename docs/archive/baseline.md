> **Archived:** Historical material retained for provenance; it is not current implementation guidance. Use the [active MVP Reset specification](../../specs/active/MVP_RESET_AND_REPOSITORY_CLEANUP_SPEC.md).

# VTA-001 Baseline

## Repository

- Upstream: `https://github.com/SphinxNumberNine/valoscribe`
- Fork: `https://github.com/naheedroomy/valoscribe`
- Baseline commit: `963dbcef83f750a1a0a2e40d91ad8daf9a66fb67`
- Remotes: `origin` points to the fork; `upstream` points to the original repository.
- Baseline code was not modified. The MIT `LICENSE` is unchanged (SHA-256: `597c6e0eef57b762e87fe3dbda21b9b39fec22c98e8b8da82eed0e8f27b9b091`).

## Environment

- macOS 26.6.2, Apple Silicon (`aarch64`)
- `uv 0.12.3`
- System `python3`: 3.9.6; `uv` selected CPython 3.13.15 to create `.venv` (the project requires Python >=3.10).
- Development dependencies are declared in the `dev` optional dependency group in `pyproject.toml`.

## Dependency synchronization and checks

Initial `uv sync --extra dev` attempt resolved 42 packages and built the local project, but failed while downloading `ruff==0.14.8` from `files.pythonhosted.org` (`host unreachable`). An initial `uv --offline sync --extra dev` also failed because `playwright==1.57.0` was not cached. The first check attempts therefore could not start because pytest, Ruff, and mypy were unavailable.

A later bounded retry succeeded: `uv sync --extra dev` exited 0, resolved 42 packages, downloaded the dependencies, and installed 38 packages. It used `UV_HTTP_TIMEOUT=10` and `UV_HTTP_RETRIES=1`; installation completed in approximately 11 seconds of preparation and 98 ms of install time after download. Checks were then run offline (`UV_OFFLINE=1`, `uv run --offline`) to prevent dependency/network access during tests.

| Command | Result |
| --- | --- |
| `uv run --offline pytest` | Exit 1; 447 passed, 33 failed in 1.45 s. This is the upstream baseline, with no production fixes applied. |
| `uv run --offline ruff check src tests` | Exit 1; 406 lint errors reported (131 fixable, 11 additional unsafe fixes available). |
| `uv run --offline mypy src/valoscribe` | Exit 1; 210 errors in 24 files (49 source files checked). |

The test failures are pre-existing baseline findings, not caused by VTA-001 changes. They span active-agent CLI invocation, model validation expectations, template-credit/score detector expectations, detector-registry contents, killfeed event shape, orchestration/round-state behavior, and timer/state validation. No failure was repaired in this baseline issue. The tests use mocked YouTube calls and no network access was enabled for test execution.

The earlier unavailable-tool attempts are setup history only; the table above records the completed checks.

## Scope confirmation

This baseline records the unmodified upstream state. No minimap implementation or production behavior changes are included in VTA-001.
