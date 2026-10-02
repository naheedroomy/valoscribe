> **Archived:** Historical material retained for provenance; it is not current implementation guidance. Use the [active MVP Reset specification](../../specs/active/MVP_RESET_AND_REPOSITORY_CLEANUP_SPEC.md).

# Raw HUD ability charge observations

`tracking.ability_charges.extract_ability_charge_deltas` converts explicit
`AbilityChargeObservation` samples into raw `AbilityChargeDelta` records. It does
not change the upstream blob detector and does not associate HUD changes with
spatial utility; the latter remains a separate inference step.

The caller supplies match/map/round/player/ability/agent/team identity, explicit
player-HUD evidence, broadcast intervals, round phases, and `max_gap_s`. No HUD
color is used to infer team or side, and no production time threshold is assumed.
Only a strictly decreasing count between consecutive, same-identity observations
within that bound emits a delta. Both endpoints must be confirmed live, in the
same round, in a usable non-preround/non-ended phase, and have timestamp- and
scope-matching player-HUD evidence. Missing or rejected observations break the
comparison; decreases are not inferred across hidden, paused, replay, uncertain,
or mis-scoped samples.

The emitted record retains the current HUD observation's evidence and carries
caller-provided identity and confidence. It is raw observed evidence, not proof
that utility was activated or that a spatial utility event belongs to this
player. Real VOD in-round numeric charge labels are not yet available; timing calibration
and real-data evaluation remain pending.

## VTA-503 source HUD evidence (#38)

`hud_ability_charge_observation_vta503.json` records independently reviewed,
source-frame evidence for bang's Omen Dark Cover third-slot pip. The original
1920×1080, 60 fps video ROI is `(x=1815, y=703, width=25, height=37)`.
The pip is bright at 2488 s/frame 149280, dim at 2489 s/frame 149340, remains
dim at the reviewed 2505 s/frame 150300 sample, and is bright again at 2506
s/frame 150360. Every stored sample includes a SHA-256 digest of the decoded
BGR ROI bytes. The manifest validates as a separate metadata-only source HUD
observation; it does not create an `AbilityChargeDelta` or modify the smoke
source manifest.

This is a charge-indicator state transition consistent with the ability
becoming unavailable/recharging. It does not establish an exact charge count,
that a cast occurred, or unique caster attribution. The circles reported near
2490–2505 s are historical, unresolved visual observations, not a verified
smoke interval or timing bracket. Absolute counts, bar-charge semantics,
deployment, spatial correspondence, canonical registration, and unique-caster
attribution remain unknown; no `agent_type` is assigned to the smoke.

The legacy smoke-source references in the frozen HUD observation JSON at lines 51, 60, and 69 are unresolved historical assertions only, not canonical lifecycle evidence; see [VTA-503 HUD note: status of adjacent smoke assertions](vta503-ability-smoke-assertions-status.md). The JSON remains unchanged.

A separate review of the 1423.4–1425.2 s sequence found both ability bars gray
before targeting, the left bar yellow on targeting entry, and a yellow-to-gray
transition during the observed targeting/release bracket at 1424.8–1424.9 s.
The round timer transition from 40 to 39 precedes release and is not count
evidence. These visual observations do not establish absolute charges or bar
semantics. A separate bounded Q848 review and its open acceptance gaps are
recorded in [the VTA-503 Q848 evidence review](vta503_q848_evidence_review.md).
