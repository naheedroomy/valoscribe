# AGENTS.md

## Mission

Extend the Valoscribe fork into an offline, evidence-backed VALORANT tactical movement analyzer. The system reconstructs player movement, spike state, supported utility, round phases, and scenario patterns from professional spectator VODs.

`PROJECT_SPEC.md` is the source of truth.

## Non-negotiable rules

1. Work on one numbered VTA issue at a time.
2. Read the existing code before modifying architecture.
3. Preserve Valoscribe behavior unless the active issue explicitly migrates it.
4. Keep the LLM disabled by default and out of the core CV pipeline.
5. No API key or external network dependency in tests.
6. Never assume a broadcast color permanently means attack or defense.
7. Store raw detections separately from tracked/derived output.
8. All inferences require confidence and evidence.
9. Keep tournament coordinates in HUD configuration.
10. Keep map thresholds and polygons in map configuration.
11. Add tests and debug artifacts for CV changes.
12. Preserve the MIT license and upstream attribution.

## Required workflow

Before coding:

1. Identify the active VTA issue.
2. Inspect relevant existing modules and tests.
3. State the minimal implementation plan.
4. Confirm current baseline tests for the affected area.

During coding:

1. Keep changes reviewable.
2. Add or update typed Pydantic contracts first when persistent data changes.
3. Add failure-path behavior, not only the happy path.
4. Avoid unrelated refactors.
5. Do not silently change CLI or output formats.

Before completion:

```bash
uv run pytest
uv run ruff check src tests
uv run mypy src/valoscribe
```

Use the repository’s actual configured paths if they differ.

## Definition of Done response

Report exactly:

```text
Issue completed:
Files changed:
Behavior added:
Tests run and results:
Metrics, if applicable:
Known limitations:
Next issue:
```

## Stop conditions

Do not invent production crop coordinates, map assets, labels, or evaluation results. When a required real fixture is unavailable:

- Implement the interface and synthetic/unit tests.
- Clearly mark fixture-dependent acceptance criteria as pending.
- Provide the exact artifact or measurement needed next.

Do not solve missing deterministic evidence by asking an LLM to guess.
