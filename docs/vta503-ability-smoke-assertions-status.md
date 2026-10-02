# VTA-503 HUD note: status of adjacent smoke assertions

## Status

The frozen `docs/hud_ability_charge_observation_vta503.json` is preserved byte-for-byte. Its `review_note` values at lines 51, 60, and 69 refer respectively to smoke-source first-present evidence at 2490 s, smoke remaining present through the 2505 s sample, and smoke-source first-absent evidence beginning at the 2506 s sample. These are **unresolved historical assertions only**. They are not canonical smoke ground truth, a reviewed lifecycle label, or accepted onset/persistence/disappearance evidence.

The independently reviewed contents of that JSON concern the HUD pip state and decoded HUD-crop bytes. The adjacent smoke wording does not make those HUD observations independent verification of smoke identity, continuity, lifecycle, or causality. Temporal coincidence between the pip transition and the old smoke assertions does not establish a cast-to-smoke association or prove that this player's ability caused smoke disappearance.

This note clarifies the evidentiary status; it does not edit or invalidate the frozen JSON as a provenance record. Preserve its original text and hashes. Do not use these three smoke assertions as training labels, canonical `ReviewedSmokeLabel` intervals, a confirmed appearance bracket, or VTA-502 timing metrics. VTA-502 remains open pending independently reviewed, source-bound canonical-coordinate lifecycle labels and held-out detector evaluation. VTA-503 also remains open; charge counts, cast attribution, and spatial association are not established by these notes.

See [`smoke-detection.md`](smoke-detection.md) for the unresolved source-space circle observations and [`vta503_q848_evidence_review.md`](vta503_q848_evidence_review.md) for the missing same-HUD controls. The source media and temporary review packet are not repository fixtures; their availability and reproducibility are limited as described in [`EVIDENCE_INDEX.md`](EVIDENCE_INDEX.md).
