# Pre-reset repository inventory

**Recorded:** 2026-10-02 (local working session)
**Scope:** RST-001, before repository reorganization
**Branch:** `mvp-reset/minimap-team-movement`
**Base HEAD:** `6fb42d6e9db2d7969723eb3cd1e154dae6cf0846`
**Preservation checkpoint:** `b6ea1d8da35af0854fe07148c702f45f2bdae9f6` (`checkpoint: preserve pre-mvp-reset work`)
**Configured remotes:** `origin` (`https://github.com/naheedroomy/valoscribe.git`, fetch/push); `upstream` (`https://github.com/SphinxNumberNine/valoscribe.git`, fetch/push). No push was performed.

## Git state before preservation

- Branch `main`, HEAD `6fb42d6e9db2d7969723eb3cd1e154dae6cf0846`, tracking `origin/main`.
- 67 tracked paths modified; staged diff was empty.
- Unstaged tracked diff: 67 files, 1,807 insertions and 896 deletions.
- 84 untracked status entries, including source, tests/fixtures, configs, scripts, and docs.
- Dirty changes and untracked files had no evident user-staged changes; all were retained in the checkpoint.
- No source modifications, moves, or deletions were made before the checkpoint.

## Preservation action

Created local branch `mvp-reset/minimap-team-movement` and committed the working source snapshot before cleanup. The checkpoint contains 243 paths (tracked modifications and untracked project source/docs/configs/tests/fixtures), 41,114 insertions and 896 deletions. It excludes ignored workspace outputs/caches and the source VOD. The candidate VTA-704 docs example bundle and its small synthetic outputs were retained as documentation/examples, not treated as real product results. The checkpoint is local; do not push without separate authorization.

## Root-level inventory

| Entry | Classification / treatment before RST-002 |
|---|---|
| `.env.example`, `.gitignore`, `AGENTS.md`, `LICENSE`, `README.md`, `pyproject.toml`, `uv.lock` | Conventional project entry points. |
| `.git/` | Git metadata; not project content. |
| `src/`, `tests/`, `scripts/`, `docs/`, `specs/` | Project source, tests, utilities, documentation, and prior work. Preserve and organize with bounded moves. |
| `champs2025_processed_vods/` | Before RST-002, 321 tracked metadata and generated artifacts totaled 329,823,660 bytes. The 142 exact generated `output/event_log.jsonl` and `output/frame_states.csv` files (329,542,540 bytes) were relocated to ignored `.local/runs/legacy-champs2025/` and removed from the index with a hash manifest. The 179 source-like match/map/series metadata JSON files (281,120 bytes) remain tracked as a documented local-data exception. |
| `tmp/` | Before RST-002, 262 ignored local VTA evidence/diagnostic artifacts totaling 197,153,065 bytes. Preserved intact under `.local/runs/legacy-tmp-evidence/`; each file's size/hash was verified after relocation. |
| `.venv/` | About 529 MB ignored Python environment; generated dependency/build environment. Keep local; do not track or remove. |
| `.mypy_cache/`, `.pytest_cache/`, `.ruff_cache/` | Ignored generated caches; keep local, do not track. |
| `dist/` | About 9 MB ignored built distribution artifact; generated. Do not track. |
| `.DS_Store` and nested `.DS_Store` files | Ignored OS metadata; not source. No value to preserve in Git. |
| `FIRST_AGENT_PROMPT.md` | Root-level historical prompt, not a conventional entry point. Moved to `docs/archive/FIRST_AGENT_PROMPT-legacy.md` with a superseded banner. |

The only candidate local video found was `../VOD/YTDown.com_YouTube_Media_4LEGEQ8KBS0_100T-vs-LOUD-VCT-Americas-Stage-2-Playoffs-Grand-Final-Map-3-Ascent_001_1080p.mp4` (approximately 1.8 GB). `../VOD` is a real neighboring directory, not a symlink. It remains outside this repository and is untouched. No footage was copied into the checkout.

## Source-like untracked work preserved

The checkpoint includes all source-like untracked paths: VTA analytics, commands, detectors, maps, reporting, tracking and typed contracts under `src/valoscribe/`; new and updated tests, expected outputs and documented fixtures under `tests/`; VTA research/evaluation scripts under `scripts/`; VTA-704 plans/readiness material under `specs/`; and implementation/evidence documentation and small synthetic example output under `docs/`. No source-like untracked entry from the pre-reset `git status --short` list was intentionally discarded. The complete exact path list is the contents of checkpoint commit `b6ea1d8` (`git show --format= --name-status b6ea1d8`).

## Secret and artifact review

- Filename scan found no `.env`, PEM/key, or credentials-named file in the checkout (the committed `.env.example` is intentionally redacted configuration documentation).
- A local text scan looked for common API-key, bearer-token, cloud-key, and private-key patterns without printing matched values. The matches were in LLM configuration/tests and resolve to code/config names and test-only placeholder inputs; no local credential file or user credential was found. This is a heuristic scan, not a formal secret-scanner certification.
- Generated/build/local data identified: `tmp/`, `.venv/`, caches, `dist/`, ignored `.DS_Store`; tracked historical processed event/state files under `champs2025_processed_vods/`; source video outside the checkout under `../VOD/`.
- No generated data or secrets were copied to the checkpoint from ignored paths; the small committed synthetic example outputs are intentional docs fixtures.

## Existing seams reviewed

- Active reset spec and handoff are external at `../valorant-mvp-reset-spec/`; the reset is a minimap-first team-shape objective, and RST-001/RST-002 precede MVP code.
- The prior `PROJECT_SPEC.md` and old `AGENTS.md` describe a broader numbered VTA program and are superseded for the next milestone.
- `src/valoscribe/commands/minimap.py` is an existing calibration/anonymous-diagnostics command surface, not the reset's complete team movement MVP; `src/valoscribe/commands/round_analysis.py` and `src/valoscribe/__main__.py` expose existing round-analysis CLI commands. Do not churn stable Valoscribe module placement to match the preferred future tree.
- Existing tracked tournament/HUD configuration is in `src/valoscribe/config/`; existing map configuration/assets are adjacent there. Canonical location distinction must be documented; avoid moves that would break imports or packaging.

## RST-002 completed actions

1. Copied the supplied reset spec byte-for-byte to `specs/active/`; archived the prior project spec, superseded VTA-704 plans/spec and historical prompt. Moved the readiness report to a dated status path and marked it historical.
2. Organized architecture, archival, status, ADR and example documents; added documentation index and code-layout map. Updated local links after moves.
3. Preserved the existing `src/valoscribe/` module homes and documented the mapping; no stable source code was moved.
4. Kept existing tournament/map configs/assets in their consumed package location; no calibration values were invented.
5. Added `.local/` ignore policy; moved the exact 142 generated dataset artifacts and all ignored root `tmp/` evidence into `.local/`, verified their hashes, and retained the 179 source-like metadata files.
6. Updated root `AGENTS.md` and `README.md` to the active reset; the README describes only an existing CLI help command, not an unverified MVP workflow. See `docs/status/repository-cleanup-report.md` for validation and remaining gates.
