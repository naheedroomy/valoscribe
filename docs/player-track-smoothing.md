# Player-track smoothing

`TrackSmoother` consumes already-associated raw `PlayerTrackEstimate` samples and
explicit timeline context. It returns versioned derived samples that retain the
original estimate separately. It does not modify or overwrite raw detections.

Causal EMA is applied only to observed estimates in a verified live interval.
A missing estimate can be linearly interpolated only when the surrounding
observations and every intervening sample share a round, are explicitly alive
and live, carry context evidence, and contain no teleport marker. The interval
must also be within the configured `MotionModelConfig.maximum_prediction_gap_s`
and its map-space speed must satisfy the configured
`MotionModelConfig.maximum_speed_mps`.

Unknown, replay, paused, hidden, death, missing-round, missing-context, and
teleport evidence fails closed. No smoothing or interpolation bridges these
boundaries. These rules prevent inference across round transitions, death,
teleports, replays, pauses, hidden intervals, and long gaps. `ema_alpha` is an
explicit caller parameter; map dimensions, speed limit, and gap threshold must
come from reviewed map configuration. No production thresholds are assumed.

Synthetic tests cover EMA, safe interpolation, retained raw observations, and
unsafe boundaries. Real-world smoothing quality and thresholds require labeled
rounds and remain unmeasured.
