# Minimap portrait candidate matching

`MinimapPortraitMatcher` compares a cropped minimap icon center with available
attack- and defense-side portrait templates. The caller supplies tournament
rosters from match metadata; templates are restricted to agent IDs present in
those rosters. Outputs are ranked `AgentPortraitTemplateMatch` evidence, not a
player/team/side assignment. Multiple mirrored compositions therefore retain
all compatible roster IDs instead of treating screen position or broadcast
color as team identity.

Templates can be passed as `{(agent_id, Side): BGR image}` or loaded from
`<template-root>/attack/<agent>_atk.png` and
`<template-root>/defense/<agent>_def.png` (JPG is also supported). Missing
rosters, templates, or roster-compatible templates return an empty candidate
list with a diagnostic reason. Invalid image input raises `ValueError`.

Similarity is `1 - mean absolute pixel difference / 255` after resizing the
template to the crop size. It is an uncalibrated ranking score, not a
probability. `minimum_confidence` and `ambiguity_margin` are caller-supplied
thresholds. Near-ties (including indistinguishable attack/defense templates)
remain ambiguous and do not produce a resolved agent ID. Even when the agent
candidate is unambiguous, the result does not assert a team, player, or side.
`debug_overlay` labels the top-ranked candidates.

Tests use generated images and write an overlay artifact in the test's temporary
directory. No licensed minimap portrait templates or labeled real minimap
icon crops are currently available, so template similarity, thresholds, and
real-frame accuracy remain unvalidated. Acceptance evidence requires permitted
attack/defense portrait templates plus manually labeled icon-center crops and
team rosters, including examples with mirrored compositions and ambiguous
portraits.
