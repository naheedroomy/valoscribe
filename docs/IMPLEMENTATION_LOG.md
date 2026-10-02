# Implementation and decision history

This is a maintained decision/evidence history, not a chronological claim about unrecorded work. No dates are added beyond dates already present in source documents. “Present” describes local worktree contents only unless explicitly identified as upstream baseline.

## Foundation and upstream behavior

- Upstream baseline is `963dbcef83f750a1a0a2e40d91ad8daf9a66fb67`; the original baseline checks recorded 447 passing / 33 failing tests, 406 Ruff findings, and 210 mypy errors across 24 files. These were baseline results, not acceptance or results for later changes. See [`baseline.md`](baseline.md).
- Valoscribe already supplies video ingestion, VLR metadata, HUD/player state, round state, killfeed and spike-plant events, and JSONL/CSV output. The inspected tracked sample contains events/player-state fields but no position columns. The accepted ADR chooses additive minimap modules over a broad rewrite or unconditional integration to preserve existing behavior.
- The MIT license and upstream attribution are required. Project license does not automatically cover third-party map assets; Riot public-content provenance/usage caveat remains in [`ascent-map-data.md`](ascent-map-data.md).

## Experiments and adverse/invalidated findings to retain

- **Team-color candidates (VTA-201): adverse baseline.** The documented two-frame color-only measurement has approximately 0.23 precision. It is not evidence for production identity or tracking. Keep raw rejected candidates and overlays; do not declare this detector accepted.
- **Ascent map geometry (VTA-102): evidence deliberately not promoted.** The bundled image and six point correspondences support a correspondence diagnostic only. The one supplied A Main rectangle was rejected because its exact center `(934, 410)` has alpha 0. Site highlights are not plantable extents; walkable mask, true site/spawn polygons, named zones, and orientation remain unresolved.
- **VTA-103 registration: constrained positive but not acceptance.** Five reviewed approximate landmark samples meet the frozen 25-canonical-pixel manifest gate (max reported 9.7792 px). The labels are not pixel-verified ground truth; candidate confidence/alignment settings were informed by these samples; HUD profile and map geometry remain pending. Keep this as candidate evaluation, not “calibration complete.”
- **VTA-304 supervised crop diagnostic: adverse and protocol-limited.** Its historical isolated comparison had two associations and one abstention on three visible labels; neither associated center met the supplied approximate ±5px-per-axis assumption. The run lacked strict freeze-before-gold blinding, and later scoring cannot be reproduced until exact decoded-crop raster correspondence is established. It is development-only, not canonical tracks or identity acceptance. Sparse identity labels are not full-round metrics.
- **Portrait/temporal/other tracking exploration: freeze.** Opt-in diagnostic foundations and historical hypotheses do not establish portrait identity, calibrated prediction, or production tracking. Do not launch further experiments merely to make progress; keep failed/adverse outcomes and protocol limitations visible.
- **VTA-502 smoke evidence: unresolved.** Historical circle observations are not reconciled lifecycle labels. A separate bounded observer review is neither detector output nor held-out performance. No canonical reviewed label/prediction cohort, precision/recall, or timing metrics are available. Do not convert asserted historical bounds into onset, persistence, or disappearance ground truth.
- **VTA-503 ability association: missing controls.** The bounded Q848 evidence review reports missing required same-HUD external controls for known starting inventory, actual uses, settled states, depletion, and reset/purchase. Do not infer a charge/use relationship or claim acceptance without them; no endless rescanning of the sole current VOD.
- **Current checks are worktree-local.** Parent reported 1,166 passed / 1 skipped, Ruff clean, and mypy clean across 119 files. These counts apply to the then-current uncommitted snapshot only; they do not establish branch/remote production acceptance or real-world accuracy. No metrics are fabricated here.

## Direction recorded

The independent upstream-first reassessment recommends pausing broad tracking experiments, completing calibration prerequisites, then adapting existing upstream HUD events through a narrow VTA-203/402–404 path before a bounded detector-to-track integration. This order preserves existing behavior and avoids treating synthetic mechanics as real acceptance. The full proposal and issue-by-issue state are in [`PROPOSAL.md`](PROPOSAL.md) and [`PROJECT_STATUS.md`](PROJECT_STATUS.md).

## Reproducible verification

Commands below are local/future-checkpoint recipes, not runnable from a docs-only published checkout; the referenced project-specific source/tests and optional dependencies remain local uncommitted until a dependency-complete code checkpoint. See [`PUBLISH_BOUNDARY.md`](PUBLISH_BOUNDARY.md). This documentation task did not rerun them. Run against the exact intended snapshot, offline where applicable, and record the actual result and snapshot identity:

```bash
uv run pytest
uv run ruff check src tests
uv run mypy src/valoscribe
```

For source-bound measurements, exact commands and local-input requirements are indexed in [`EVIDENCE_INDEX.md`](EVIDENCE_INDEX.md). Do not present a command as executed merely because it is documented here.
