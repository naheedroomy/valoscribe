> **Archived:** Historical material retained for provenance; it is not current implementation guidance. Use the [active MVP Reset specification](../../specs/active/MVP_RESET_AND_REPOSITORY_CLEANUP_SPEC.md).

# Upstream-first implementation proposal

## Direction

Continue the fork as a small, opt-in extension of Valoscribe. Preserve upstream ingestion, HUD detection, round orchestration, metadata, and event outputs. Do not rewrite those components or imply that existing HUD events validate new spatial outputs. The purpose is offline, evidence-backed tactical movement analysis; all claims must remain linked to deterministic observations, confidence, and provenance. The optional LLM remains disabled by default and outside the core CV pipeline.

This proposal is a sequencing recommendation, not approval to expand scope or a declaration of issue completion. The complete issue matrix is in [`project-status-legacy.md`](project-status-legacy.md).

## Recommended sequence

1. **Checkpoint truthful status and maintain integrity.** Preserve the baseline SHA, MIT license, upstream attribution, source provenance, failure records, and the separation between implemented mechanics, synthetic tests, reviewed observations, and acceptance. Stage explicit paths only; never publish temporary evidence/media or local secrets.
2. **Close calibration VTA-101–104 before production tracking.** Confirm one selected real VOD and matching HUD crop/profile; finish independently reviewed Ascent walkable, site, spawn, and named-zone geometry; verify orientation; evaluate registration on distinct held-out source frames. Keep global acceptance blocked while map geometry or HUD configuration is pending. The five-sample VTA-103 landmark result is approximate diagnostic evidence, not production calibration.
3. **Reuse upstream HUD for a thin integration path.** Sequence VTA-203 then VTA-402–404: adapt existing team/side/half, round/timer/score, player alive/dead, kill, and plant events. Preserve upstream JSONL/CSV and use explicit timestamp, replay, obstruction, and unknown-state boundaries. Do not rebuild upstream extraction. Unknown player position is an honest result and does not count as movement acceptance.
4. **Build one bounded real detector-to-track path.** After prerequisites, evaluate a frozen candidate detector against independently reviewed development and held-out labels, then use existing assignment, motion, and smoothing seams. Require full-round visibility, timestamp-matched predictions, real identity accuracy/coverage/switch metrics, and stable-ID playback before accepting VTA-304. Never promote crop-space diagnostics or anonymous tracklets to canonical player tracks.
5. **Add supported spatial evidence only when independently grounded.** Complete zone mapping only after validated geometry. Evaluate spike and smoke/utility fusion with compatible labels, source evidence, confidence, and held-out metrics. Keep unknown caster, identity, charge, and lifecycle unknown. Do not use roster context to infer an actor.
6. **Connect deterministic analytics/reporting to accepted data.** VTA-601–605 can be mechanically exercised synthetically, but real report acceptance requires genuine matching rounds, source timestamps, sample sizes, and evidence references. Keep LLM work optional and defer any extra effort until this path is deterministic and accepted.

## Freeze and stop rules

- Freeze new tracking hypotheses, parameter sweeps, and diagnostic branches; retain prior results, including adverse and invalidated outcomes.
- Do not re-open a failed historical comparison as acceptance evidence unless its exact source/raster binding, protocol, and inputs can be reproduced.
- Do not repeatedly rescan a known VOD when a required source/control artifact is unavailable. Record the precise missing artifact and request it only if the relevant acceptance work is resumed.
- Keep raw detections separate from tracked/derived state; preserve uncertainty, source timestamps, and confidence.
- Treat partial decode/write, pixel/PTS/hash disagreement, unknown identity promoted as observed, replay leakage, or incomplete output reported as success as integrity blockers.
- Synthetic tests are necessary interface/mechanics evidence, never a substitute for required real-source results.

## Checkpoint policy

The current worktree has broad mixed changes; this document does not certify their correctness or instruct a whole-tree publish. Use explicit allowlists. A documentation checkpoint may publish only reviewed project instructions/specification/ADR, evidence/status docs, `.env.example`, and minimal `.gitignore` hygiene when separately reviewed. Code checkpoints must be dependency-complete, independently reviewed, and validated against that exact snapshot. Exclude `tmp/`, source media, secrets, caches, build outputs, and local `progress.md`. The branch's upstream association requires an explicit push target to `origin`; publishing mechanics are owned by the parent and are not performed by this task.

## Basis and prior decisions

The independent upstream-first reassessment recommends a documentation checkpoint, blocks indiscriminate whole-tree publishing, and identifies calibration-first sequencing as the minimal route toward a real end-to-end path. The accepted minimap extension ADR rejects both rewriting the application and unconditional integration because those would risk existing behavior without demonstrated benefit. See [`../adr/0001-minimap-extension.md`](../adr/0001-minimap-extension.md) and the detailed history in [`IMPLEMENTATION_LOG.md`](IMPLEMENTATION_LOG.md).
