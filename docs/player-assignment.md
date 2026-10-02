# Constrained minimap player assignment

`ConstrainedPlayerAssigner` associates registered `AssignmentObservation` inputs
with known `AssignmentTrack` roster identities. It uses a deterministic
rectangular Hungarian implementation, so the module adds no optional dependency.
Each candidate can be used at most once; one dummy/unassigned column per track
allows the solver to leave roster slots unresolved.

Hard gates reject team mismatches, known-side conflicts, low registration
confidence, and missing matching agent-portrait evidence. Remaining pair costs
combine normalized positional displacement, portrait-template mismatch, and
color-detector confidence. Broadcast color is not a team or side mapping. A
track without a prior position can still match by portrait and contextual team
and side evidence, with a neutral position cost.

Assignments above the configured cost limit are rejected. Near ties between a
track's candidate alternatives or between players competing for the same icon
are also rejected rather than resolved by arbitrary Hungarian tie-breaks.
Every known player receives an assigned or explicit unknown `CandidateAssignment`
with confidence, cost (when available), alternate players, evidence, and a
rejection reason. The returned synthetic map-space overlay draws accepted
assignments for inspection; production overlays should use the same API with a
configured canonical-map background in a later rendering integration.

Default weights and gates are conservative API defaults, not calibrated
production thresholds. Calibrate them with labeled, registered frames before
reporting identity accuracy. Synthetic tests cover reversed/crossing candidate
order, duplicate-agent compositions, missing prior positions, team/side and
registration gates, ties, threshold rejection, and overlay output. No real-frame
identity accuracy is claimed.
