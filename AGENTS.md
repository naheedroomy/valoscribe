# Agent instructions

## Active source of truth

The only active implementation specification is [`specs/active/MVP_RESET_AND_REPOSITORY_CLEANUP_SPEC.md`](specs/active/MVP_RESET_AND_REPOSITORY_CLEANUP_SPEC.md). It supersedes the earlier broad `PROJECT_SPEC.md` and numbered-VTA sequence for this milestone. Read it before implementation. The documentation map is [`docs/README.md`](docs/README.md); code/config placement is [`docs/architecture/code-layout.md`](docs/architecture/code-layout.md).

## Scope lock: VALORANT MVP Reset v1.0

Deliver an offline, retrospective, minimap-first team-shape analysis on one local Ascent broadcast and at least five selected rounds. Team-level occupancy/movement is sufficient. Manual intervals, source-specific crop/color config, human correction, and cautious deterministic summaries are allowed. Identity/tracking, full HUD, utility/spike reconstruction, automatic round discovery, multiple maps/layouts, cloud work, and LLM calls are deferred. Do not treat tests, abstention, architecture, or provider plumbing as the real product result.

Preserve all meaningful existing work and Valoscribe behavior. Never invent source crops, team/side labels, map polygons, round intervals, acceptance metrics, or calibration. Keep source configs' crop/color values in broadcast configuration and map polygons/thresholds in map configuration. Keep raw observations immutable and corrections append-only. No paid API/LLM calls, network test dependencies, or credentials in reports/tests. No push absent separate authorization.

## Required phase order

1. RST-001: inventory and preserve before cleanup.
2. RST-002: bounded repository organization and checks.
3. MVP-001 onward only after the RST gates; follow the active specification in order.

For cleanup, never use `git clean`, `git reset --hard`, broad recursive deletion, or an unreviewed data move. Use exact, reversible moves. Do not move or modify the neighboring `../VOD` workspace as part of repository cleanup. Machine-local VODs, configs, runs, annotations, caches, and backups belong under ignored `.local/`.

## Development checks

Before editing a code seam, inspect the existing code and relevant tests. Keep changes narrow, preserve upstream attribution and the MIT license, and do not move stable source merely for visual symmetry. After implementation, run:

```bash
uv run pytest
uv run ruff check src tests
uv run mypy src/valoscribe
```

Report command results separately from real-source acceptance. If real fixtures or calibration evidence are missing, say so and do not claim product completion.
