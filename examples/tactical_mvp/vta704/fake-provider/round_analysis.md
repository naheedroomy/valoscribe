# Round evidence analysis

Match/map/round: synthetic\-match / ascent / synthetic\-match\-map1\-round4 (round 4)

Round samples: 1; event sources: 1.

## Observations

- **Observed source record**: The HUD event log recorded event type round\_start; upstream evidence not\_provided\.
  Evidence synthetic\-hud\-export:line:1, JSONL line 1; timestamp 120 (synthetic\_vod\_seconds).
  Upstream confidence: not_provided; evidence references (0): not_provided.
- **Observed source record**: The HUD event log recorded event type spike\_plant; upstream evidence not\_provided\.
  Evidence synthetic\-hud\-export:line:2, JSONL line 2; timestamp 154.25 (synthetic\_vod\_seconds).
  Upstream confidence: not_provided; evidence references (0): not_provided.
- **Observed source record**: The HUD event log recorded event type round\_end; upstream evidence not\_provided\.
  Evidence synthetic\-hud\-export:line:3, JSONL line 3; timestamp 179.5 (synthetic\_vod\_seconds).
  Upstream confidence: not_provided; evidence references (0): not_provided.

## Hypotheses — tentative, not observed facts

- In this synthetic example, the recorded plant follows the round\-start event\.
  Model-reported confidence: 0.55 (subjective, uncalibrated).
  Supporting source references (membership only): synthetic\-hud\-export:line:1 at 120 (synthetic\_vod\_seconds), synthetic\-hud\-export:line:2 at 154.25 (synthetic\_vod\_seconds).

## Suggested coaching practices — tentative, not prescriptions

- As a review exercise, compare this timing with additional reviewed rounds\.
  Model-reported confidence: 0.61 (subjective, uncalibrated).
  Supporting source references (membership only): synthetic\-hud\-export:line:1 at 120 (synthetic\_vod\_seconds), synthetic\-hud\-export:line:2 at 154.25 (synthetic\_vod\_seconds), synthetic\-hud\-export:line:3 at 179.5 (synthetic\_vod\_seconds).

## Evidence availability and limitations

- One round cannot establish recurring habits or anti-strat patterns.
- Legacy HUD event logs lack calibrated event confidence; detection accuracy is not independently verified.
- Claim citations confirm reference membership only, not semantic support or causality.
- Model-reported confidence is subjective and is not calibrated.
- Source synthetic\-hud\-export: 3 scoped events from event\_log\.jsonl; clock synthetic\_vod\_seconds; bounds reference synthetic fixture bounds, not reviewed production evidence.
