# Per-player motion state (VTA-301)

`PlayerMotionTracker` owns one state slot for each metadata-known player. It
consumes an already-resolved `PlayerDetection`; it does not match colors,
portraits, or competing detections. A detection updates the matching slot only
when player, agent, and team evidence are unique and its detector and map
registration confidence meet the configured minima.

`MotionModelConfig` requires explicit map dimensions in meters, a maximum speed,
a maximum prediction interval, and confidence thresholds. Supply these from
reviewed map/HUD configuration; this implementation does not invent Ascent
geometry or production movement thresholds. Movement gates use Euclidean map
space distance divided by elapsed time. A long observation gap starts a fresh
anchor rather than bridging the gap.

Prediction requires two accepted observations to estimate velocity and is
available only within `maximum_prediction_gap_s`. It is constant-velocity,
confidence decays linearly over the configured interval, and coordinates that
would leave the normalized map return unknown. Predicted estimates have no
source frame and are explicitly `predicted`, never `observed`. Every output
carries evidence and a confidence; rejected or unsupported positions have no
coordinate, zero confidence, and a reason.

The synthetic debug artifact
`tests/expected/golden/motion_model_prediction.json` records a predicted
`PlayerTrackEstimate` with source-frame evidence for both observations and the
prediction duration for the missing-frame estimate. The test compares this
artifact with the model's JSON serialization. No labeled real minimap sequence or validated map
scale is currently available, so real-map movement thresholds and prediction
quality remain pending.
