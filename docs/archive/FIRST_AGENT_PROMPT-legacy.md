> **Archived:** Historical material retained for provenance; it is not current implementation guidance. Use the [active MVP Reset specification](../../specs/active/MVP_RESET_AND_REPOSITORY_CLEANUP_SPEC.md).

# First AI Agent Prompt

You are implementing the first sprint of the VALORANT Tactical Movement Analyzer in a fork of `SphinxNumberNine/valoscribe`.

Read these files first:

1. `PROJECT_SPEC.md`
2. `AGENTS.md`
3. The existing Valoscribe `README.md`, `pyproject.toml`, CLI entrypoint, HUD configuration types, video frame reader, and tests.

## Scope for this run

Implement **VTA-001 only: Establish fork baseline**.

Do not start minimap detection, tracking, utility detection, LLM integration, a web UI, or unrelated refactoring.

## Required work

1. Record the upstream repository URL and current baseline commit SHA in `docs/baseline.md`.
2. Install/synchronize the existing development dependencies.
3. Run the existing test suite, Ruff, and mypy using the project’s current configuration.
4. Record the commands, environment assumptions, pass/fail counts, and any existing failures in `docs/baseline.md`.
5. Add `docs/../adr/0001-minimap-extension.md` explaining why the project will extend Valoscribe rather than rewrite it, and why minimap functionality will be isolated behind new modules and CLI flags.
6. Confirm that the existing MIT license and attribution remain present.
7. Make no production behavior changes unless required only to make the documented baseline commands execute; any such change must be isolated and justified.

## Acceptance criteria

- `docs/baseline.md` exists and is factual.
- `docs/../adr/0001-minimap-extension.md` exists.
- Existing license remains unchanged.
- Test/lint/type-check results are recorded.
- The diff contains no minimap implementation yet.

## Final response format

```text
Issue completed: VTA-001
Files changed:
Behavior added:
Tests run and results:
Metrics, if applicable:
Known limitations:
Next issue: VTA-002
```
