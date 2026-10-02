# Match-contextual side state

`resolve_team_sides` derives a team's current attack/defense side from its
explicit first-half starting-side evidence and round number. It does not infer
side from broadcast colors. The evidence must be match-contextual (for example,
reviewed match metadata); absent, unknown, duplicated-team, or low-confidence
side evidence yields `Side.UNKNOWN` with a reason.

The first half is rounds 1–12; the second half (13–24) reverses the anchored
side. Professional VCT overtime begins at round 25 from an explicit
`overtime_starting_side` anchor with its own confidence and evidence. This anchor
may differ from the first-half starting side. Sides then alternate each round
(25, 26, 27, 28, ...). Without a sufficiently confident overtime anchor, side is
`unknown`; the resolver does not derive it from first-half state. This models
the professional overtime rules in scope and does not claim support for modes
with different side-selection rules.

A known broadcast color is carried only when its current-context evidence has
sufficient confidence and is unique among supplied teams. Color confidence is
independent of side confidence: weak/conflicting color evidence invalidates the
color field but does not lower or reject otherwise-supported side evidence.
Color labels such as red and blue have no semantic side mapping.

The confidence values are evidence confidence thresholds, not a measured
probability of correctness. Consumers must keep rejection reasons and evidence
with resolved records. No production match-frame evaluation is included; the
resolver's synthetic tests validate state transitions and conservative failure
behavior.
