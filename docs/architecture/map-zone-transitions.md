# Map-zone transitions

`ZoneTransitionTracker` assigns zones only from raw, observed positions in verified live-round context. It does not consume predicted or interpolated positions, and it emits derived `ZoneTransitionEvent` records separately from the input detections. Every emitted event carries source evidence, confidence, round/player identifiers, and the map-config schema version.

Named polygons, normalized-coordinate hysteresis distance, and overlap precedence belong in the versioned map configuration. If multiple polygons contain a point, the first declared named zone wins; this deterministic tie-breaker is not a claim that overlapping polygons are correct. A point near the previous zone's boundary remains assigned to that zone until it exceeds the configured hysteresis distance. A zone-to-zone change emits a leave event followed by an enter event at the observed timestamp.

Missing map configuration, pending geometry, absent position, unconfirmed alive state, missing live context, replay/pause/hidden intervals, and predicted positions fail closed without emitting events. Unsafe samples clear prior zone state so later samples cannot bridge an unobserved interval.

The bundled Ascent config has `geometry_status: pending` and no named zones. No Ascent zones or production hysteresis values are inferred here. Synthetic polygons test lookup and transitions only; production zone behavior requires reviewed Ascent polygons and calibrated hysteresis in map configuration.
