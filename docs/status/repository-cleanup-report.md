# RST-001/RST-002 repository cleanup report

**Date:** 2026-10-02
**Branch:** `mvp-reset/minimap-team-movement`
**Pre-reset preservation:** checkpoint commit `b6ea1d8da35af0854fe07148c702f45f2bdae9f6` on this branch, before cleanup moves.
**Scope:** repository inventory and bounded organization only. No MVP detection/calibration code was added. No push was performed.

## Preservation and data migration

- The pre-reset inventory is [`pre-reset-repository-inventory.md`](pre-reset-repository-inventory.md). It records base branch/HEAD/remotes, the 67-file unstaged diff (1,807 insertions / 896 deletions), 84 untracked entries, root exceptions, source home, source VOD location, and the privacy-conscious pattern review.
- The checkpoint captured all 243 then-dirty/source-like paths in a local commit before any cleanup, including source, tests, configs, scripts, fixture annotations, docs and prior plans. The base commit remains recoverable on the branch ancestry. No ignored cache, virtualenv, raw video, or root `tmp/` output was committed.
- Exactly 142 tracked generated dataset artifacts (`event_log.jsonl` and `frame_states.csv`) were moved, byte-for-byte, to ignored `.local/runs/legacy-champs2025/`, then removed from the Git index. Their combined size is 329,542,540 bytes. SHA-256 was verified at each destination. The tracked path/hash/byte manifest is [`legacy-champs2025-generated-output-manifest.sha256`](legacy-champs2025-generated-output-manifest.sha256), SHA-256 `86680390e7af2f673690e4eb7fd0d076b90f207dd328198718b7414cc901b669`; the complete local migration manifest is ignored at `.local/runs/legacy-champs2025/migration-manifest.json`.
- The 179 small match/map/series metadata JSON files (281,120 bytes) were kept in the existing `champs2025_processed_vods/` tree as source-like input metadata; only exact generated output paths were untracked. That remaining data tree is a documented root exception, not an active MVP data location.
- The ignored root `tmp/` (262 files, 197,153,065 bytes) was renamed intact to `.local/runs/legacy-tmp-evidence/`; all destination file sizes and hashes were reverified. Its local ignored manifest hash is `9b51de49dceb3c22e281ef341019eb71eade29e6d58287389efe338674a94852`.
- The neighboring `../VOD/` directory and its approximately 1.8 GB local Ascent VOD were left untouched. No video was copied into the repository.
- `.local/` is ignored. It contains local preserved evidence and generated legacy outputs; no credential values were printed or copied into documentation.

## Organization completed

- Copied the supplied active spec byte-for-byte to `specs/active/MVP_RESET_AND_REPOSITORY_CLEANUP_SPEC.md`. `cmp` confirmed identity with the supplied source file.
- Moved the prior `PROJECT_SPEC.md` to `specs/archive/PROJECT_SPEC-legacy.md`, and the old VTA-704 plan/spec to `specs/archive/`. These and archived Markdown docs carry an explicit superseded/historical banner linking to the active spec. The dated readiness report is now `docs/status/2026-10-02-full-run-readiness-historical.md`, explicitly labeled as a pre-reset report, not current acceptance.
- Organized existing architecture references in `docs/architecture/`, prior project/status/experimental material in `docs/archive/`, the existing ADR in `docs/adr/`, and factual inventory/status material in `docs/status/`. Added `docs/README.md` index and `docs/architecture/code-layout.md` mapping.
- Preserved existing VTA source under its coherent `src/valoscribe/` module homes. HUD/map candidate profiles remain under `src/valoscribe/config/` because current CLI/package seams depend on them. No new guessed configs or calibration values were created.
- Moved the small, synthetic VTA-704 example package to `examples/tactical_mvp/vta704/`; updated the existing regression test to use that location. It remains explicitly synthetic and is not real-run evidence.
- Organized VTA one-off experiments under `scripts/dev/` and evaluators/validators under `scripts/maintenance/`; retained existing series-processing scripts and match lists in `scripts/`. Updated test invocations and code provenance paths to the new locations. Regression tests cover those entry points.
- Relocated seven review/manifest JSON artifacts used by automated tests from `docs/` to `tests/fixtures/` and updated their tests. This keeps test inputs in the fixture home while docs/archive retains historical narrative.
- Updated root `AGENTS.md` with the reset scope, safety rules, offline constraints and phase order. Replaced the broad root README with a concise provisional description and the verified existing CLI help command. It clearly says no tactical MVP run/output is accepted yet; it does not fabricate a verified MVP workflow or tactical output example.
- Updated `.gitignore` to exclude `.local/`, local artifact/run/cache directories and only the exact legacy dataset `output/` directories. Removed broad media-extension ignores so intentional small test media can be tracked. Kept the existing `.env` ignore and `.env.example` exception.

## Root layout and documented exceptions

Conventional root entry points/directories remain: `.env.example`, `.gitignore`, `AGENTS.md`, `LICENSE`, `README.md`, `pyproject.toml`, `uv.lock`, `src/`, `tests/`, `configs/` (reserved for the first reviewed portable MVP example; not created with placeholders), `docs/`, `specs/`, `examples/`, and `scripts/`.

Observed root-only exceptions are:

- `.git/`: Git metadata.
- `.local/`: ignored machine-local inputs and preserved/generated runs, now canonical.
- `.venv/`: ignored developer Python environment.
- `.mypy_cache/`, `.pytest_cache/`, `.ruff_cache/`: ignored test/type/lint caches.
- `dist/`: ignored local build output.
- `.DS_Store`: ignored OS metadata (a root/nested instance remains locally; it is not staged).
- `champs2025_processed_vods/`: the 179 pre-existing source-like match/map/series metadata records documented above. The generated event/state files are no longer tracked.

The local `../VOD/` folder is outside the repository root and is not a symlink or moved repo dependency. MIT license and upstream attribution were not modified.

## Validation and gates

- `uv run pytest`: **passed**, 1,198 passed / 1 skipped.
- `uv run ruff check src tests`: **passed**.
- `uv run mypy src/valoscribe`: **passed**, no issues in 125 source files.
- Active spec byte copy: passed (`cmp -s` returned success).
- `.local` ignore behavior: passed (`git check-ignore` matched both migration manifests).
- Generated dataset relocation: passed, all 142 hashes and byte sizes matched; `git ls-files` contains 0 `event_log.jsonl` / `frame_states.csv` output paths under the old data tree.
- `uv run python -m valoscribe --help`: **passed**. It prints the current existing CLI groups; it is explicitly not an MVP analysis command.
- Markdown local-link audit: **passed**, 113 links checked, 0 broken after moves.
- Active spec copy identity: **passed** with byte-for-byte `cmp`.
- Repository and product gates are separate: RST cleanup does not mean the required five-round team-movement product is implemented or accepted. This task stops before MVP code/calibration.

## Remaining bounded limitations

1. Source-like match metadata remains under the documented `champs2025_processed_vods/` root exception; it has not been bulk moved or deleted.
2. Some archived documents preserve historical machine-local paths and old stage-specific instructions as provenance. They are visibly archived and are not inputs to the active workflow.
3. There is not yet a verified end-to-end MVP command, tracked example config, calibration, or five-round result. MVP-001 and later remain gated.
