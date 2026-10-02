# Project status and VTA issue matrix

> **Publication boundary:** Referenced VTA artifacts may be local or included in a checkout through an explicitly enumerated, reviewed, dependency-complete code checkpoint. Verify each checkpoint's allowlist and version in the checkout under review; see [`PUBLISH_BOUNDARY.md`](PUBLISH_BOUNDARY.md). The six-file VTA-101 limited checkpoint is version-specific, and earlier docs-only commit `56e45e7` does not contain it. Do not assert a push or other publication without verification against an actual commit SHA; see [`vta101-code-checkpoint.md`](vta101-code-checkpoint.md).

## Acceptance boundary

This is a project status document, not a production acceptance report. Issue implementation presence, synthetic/unit-test coverage, and real-source acceptance are separate states. **No VTA issue is marked complete unless every acceptance criterion in `PROJECT_SPEC.md` is met.** A passing synthetic test proves mechanics only. Any code-checkpoint availability claim must be limited to its reviewed allowlist and identified committed artifact; this document does not certify publication.

Baseline provenance: upstream commit `963dbcef83f750a1a0a2e40d91ad8daf9a66fb67`; details and historical upstream checks are in [`baseline.md`](baseline.md). A parent-reported later original-worktree run had 1,167 passed / 1 skipped, Ruff clean, and mypy clean across 119 files. Those checks apply only to that uncommitted worktree snapshot, not the VTA-101 candidate, remote production behavior, or real-world acceptance; see [`vta101-code-checkpoint.md`](vta101-code-checkpoint.md) for the candidate's separate snapshot comparison.

## Numbered issue matrix

“Code/tests present” means relevant implementation and/or tests exist in this worktree; it does not mean the issue is complete. Real acceptance remains pending wherever the table says so.

| Issue | Implementation/test evidence in worktree | Real acceptance and remaining gate |
|---|---|---|
| VTA-001 | `docs/baseline.md`; project instructions, spec, ADR, and baseline recorded. | Baseline is recorded; this checkpoint does not attest that it has been published. Preserve upstream attribution and MIT license. |
| VTA-002 | `src/valoscribe/types/run_manifest.py`, tracking run/export modules, and `tests/test_types/test_run_manifest.py`, `tests/test_tracking/test_run_export.py`. | Synthetic manifest/export coverage exists; full application run-manifest emission is not established as accepted. |
| VTA-003 | Persistent contracts under `src/valoscribe/types/`; `tests/test_types/`; `docs/schema-compatibility.md`. | Schema mechanics tested; real detector/evidence semantics and compatibility acceptance remain open. |
| VTA-004 | `tests/fixtures/`, `tests/expected/`, `tests/test_fixture_conventions.py`, and fixture provenance documents. | Offline/synthetic conventions exist; source-backed fixtures remain external and some are only metadata. |
| VTA-101 | Reviewed six-file limited candidate for minimap-profile crop mechanics and empty-crop save guard; exact allowlist, API behavior, synthetic geometry, review, and test recipe in [`vta101-code-checkpoint.md`](vta101-code-checkpoint.md). Verify referenced paths and checkpoint version in the checkout under review; earlier docs-only commit `56e45e7` lacks the checkpoint. | Synthetic mechanics only. Real HUD provenance/profile calibration and fixture-backed golden crops remain pending; VTA-101 is not complete. |
| VTA-102 | Ascent config, correspondence/annotation manifests, validators, and `tests/test_maps/`. | **Pending:** map geometry, orientation, walkable area, true site/spawn boundaries, and named zones are not validated. Six-point correspondence evidence is not geometry acceptance; see [`ascent-map-data.md`](ascent-map-data.md). |
| VTA-103 | Registration/evaluator code and `tests/test_maps/test_registration*.py`; five-sample reviewed landmark report. | Candidate landmark evaluation passes its frozen 25-pixel manifest gate, but annotation uncertainty, candidate thresholds, pending HUD profile, and pending map geometry keep production calibration acceptance closed; see [`minimap-vta103-evaluation.md`](minimap-vta103-evaluation.md). |
| VTA-104 | `src/valoscribe/commands/minimap.py`, calibration tests, and calibration docs. | CLI mechanics exist; selected production HUD/map profile and end-to-end calibrated overlays remain pending. |
| VTA-201 | Color candidate detector, evaluator, profile, and tests. | **Pending:** documented color-only baseline is about 0.23 precision on two frames; no accepted labeled-frame precision/recall result. See [`minimap-color-candidates.md`](minimap-color-candidates.md). |
| VTA-202 | Portrait matcher and tests; side-state and portrait diagnostics. | **Pending:** mirror-composition and real icon identity acceptance; diagnostics are not calibrated identity evidence. |
| VTA-203 | `src/valoscribe/detectors/side_state_resolver.py`, tests, and `docs/side-state-resolution.md`. | Synthetic transitions covered; no accepted complete selected-source half/overtime validation. Do not assign permanent team meaning to broadcast color. |
| VTA-301 | `src/valoscribe/tracking/motion_model.py`; `tests/test_tracking/test_motion_model.py`. | Synthetic state/motion behavior exists; measured plausible movement and full-round real tracks pending. |
| VTA-302 | `src/valoscribe/tracking/assignment.py`; `tests/test_tracking/test_assignment.py`. | Assignment mechanics tested; real-player identity assignment accuracy pending. |
| VTA-303 | `src/valoscribe/tracking/smoothing.py`; `tests/test_tracking/test_smoothing.py`. | Synthetic interpolation guards tested; validated real timeline boundaries and track acceptance pending. |
| VTA-304 | Artifact/export, anonymous and crop diagnostic modules; tests and `docs/player-track-artifacts.md`. | **Pending:** full-round reviewed labels, matched predictions, identity accuracy, visibility coverage, switch metrics, canonical calibration, and stable-ID playback. Some historical diagnostics were adverse or procedurally invalid; see [`IMPLEMENTATION_LOG.md`](IMPLEMENTATION_LOG.md). |
| VTA-401 | Zone and transition implementation/tests; [`map-zone-transitions.md`](map-zone-transitions.md). | **Pending:** Ascent has no validated named-zone geometry; synthetic polygons do not satisfy map-zone acceptance. |
| VTA-402 | Alive-state and spike/fusion modules plus tests. | Synthetic fusion covered; upstream kill/alive evidence adapter and selected-source timestamped real-round validation remain pending. |
| VTA-403 | Replay filter and tests. | Mechanics covered synthetically; real replay/pause/hidden interval classification on selected source pending. |
| VTA-404 | Round snapshot module/tests and anonymous runner. | **Pending:** coherent real active-round sequence and replay-safe fusion are not accepted. Anonymous synthetic runner is not integrated real-player evidence. |
| VTA-501 | Spike fusion module/tests. | **Pending:** real carrier/drop/plant/location evidence fusion; HUD-only plant events do not prove spatial carrier/location reconstruction. |
| VTA-502 | Smoke detector, source observation/evaluation code, tests, and documented bounded reviews. | **Pending:** canonical lifecycle labels linked to predictions, held-out precision/recall/timing metrics. Historical disputed observations are unresolved and must not be treated as labels. See [`smoke-detection.md`](smoke-detection.md) and [`smoke-deployment-review-vta502.md`](smoke-deployment-review-vta502.md). |
| VTA-503 | Ability-charge observations and utility association modules/tests. | **Pending:** compatible inventory and spatial association evidence. Q848 controls are absent; see [`vta503_q848_evidence_review.md`](vta503_q848_evidence_review.md). |
| VTA-601 | Scenario query modules/CLI and tests. | Query mechanics tested; full selected-map genuine round matching not established. |
| VTA-602 | Phase analytics and tests. | Synthetic labels exist; validated real-round phase labels and evidence remain pending. |
| VTA-603 | Formation analytics and tests. | Synthetic formation mechanics exist; validated real player positions and formation acceptance pending. |
| VTA-604 | Aggregates and representative selection with tests. | Synthetic aggregation exists; genuine selected-map samples and reported denominators pending. |
| VTA-605 | Deterministic reporting and tests. | Renderer exists; no accepted full Ascent report with every tactical claim grounded in real samples/evidence. |
| VTA-701 | Provider abstraction/fake provider and tests. | Contract mechanics covered; core deterministic processing must remain independent and LLM stays disabled by default. |
| VTA-702 | OpenAI-compatible provider implementation and tests. | Provider contract tests exist; external operation is optional and not core acceptance. No API/network dependency in tests. |
| VTA-703 | Query-language parsing and tests. | Synthetic parsing/failure handling exists; real acceptance is optional and must fail closed to deterministic filters. |
| VTA-704 | Evidence-grounded narrative/reporting tests. | Synthetic evidence checks exist; no real report acceptance until deterministic evidence path is accepted. LLM cannot create or repair evidence. |

## Priority and next checkpoint

Follow the upstream-first sequence in [`PROPOSAL.md`](PROPOSAL.md): close VTA-101–104 calibration gates, reuse upstream HUD/round evidence through narrow VTA-203/402–404 adapters, then validate one bounded end-to-end path before expanding real tracking. Freeze further exploratory tracking experiments. Keep `LLM_ENABLED=false` by default. Required external artifacts and reproducible commands are indexed in [`EVIDENCE_INDEX.md`](EVIDENCE_INDEX.md).
