# Milestone specification index

Canonical milestone index. Specifications define scope; linked validation reports distinguish implemented capabilities from accepted product evidence.

| Milestone | Status | Specification and evidence |
|---|---|---|
| VALORANT MVP Reset v1.0 | Active implementation specification; implemented bounded partial-evidence workflow, not full tactical/opponent analysis | [Reset spec](active/MVP_RESET_AND_REPOSITORY_CLEANUP_SPEC.md), especially §§19–20; [real-round validation](../docs/status/mvp-real-round-validation.md): five manually configured Ascent attack windows, partial openings, three tentative concentrations; shift/regroup/opposite-side unknown |
| VOD round range and agent evidence | Proposed, revision 0.1; no implementation approved | [Next milestone proposal](planned/VOD_ROUND_RANGE_AND_AGENT_EVIDENCE_SPEC.md): supported Ascent layout, confirmed inclusive round range, both-team movement and portable map-aware external-agent bundle |

## Status and iteration policy

- `active/`: only one active implementation specification. The reset remains active; a proposal does not supersede it.
- `planned/`: proposed milestones. Explicit approval and reconciliation with active requirements are required before activation; no automatic implementation, schedule or acceptance claim.
- `archive/`: preserved historical specifications, not current instructions. Do not move/archive the active reset merely to add a proposal.
- Each proposal records status, revision, date, approval state and a short change log. Increment revisions for scope/acceptance changes; record what changed and why, retain evidence links and unresolved decisions.
- Update this index when status or scope changes. Mark completion only with linked user-visible artifacts and real-source acceptance evidence, keeping pending/partial criteria explicit.
- Keep machine-local sources, profiles, runs and annotations under ignored `.local/`; specs hold requirements and provenance links, not local generated artifacts.

## Change log

- 2026-10-04: Added canonical index and next-milestone revision 0.1 proposal. Active reset and existing implementation instructions unchanged.

Verify from project root: `git diff --check` and resolve local Markdown links before handoff.
