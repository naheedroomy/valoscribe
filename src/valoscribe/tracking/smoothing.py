"""Evidence-gated smoothing and interpolation for already-associated tracks."""

from __future__ import annotations

import math

from valoscribe.types.persistent import (
    MotionModelConfig,
    NormalizedPoint,
    SmoothedTrackSample,
    TrackSmoothingInput,
)


class TrackSmoother:
    """Apply causal EMA and interpolate only inside verified live round segments."""

    def __init__(self, config: MotionModelConfig, *, ema_alpha: float) -> None:
        if not math.isfinite(ema_alpha) or not 0.0 < ema_alpha <= 1.0:
            raise ValueError("ema_alpha must be finite and in (0, 1]")
        self.config = config
        self.ema_alpha = ema_alpha

    def smooth(self, samples: list[TrackSmoothingInput]) -> tuple[SmoothedTrackSample, ...]:
        """Return derived samples without altering source estimates."""
        self._validate_sequence(samples)
        output = [self._unknown(sample, "context_not_verified") for sample in samples]
        previous_observation: int | None = None
        previous_smooth: NormalizedPoint | None = None

        for index, sample in enumerate(samples):
            if not self._safe_context(sample):
                previous_observation = None
                previous_smooth = None
                continue
            estimate = sample.estimate
            if not estimate.observed or estimate.position is None:
                continue
            current_point = estimate.position
            can_continue = (
                previous_observation is not None
                and previous_smooth is not None
                and self._compatible(samples[previous_observation], sample)
            )
            if can_continue:
                assert previous_observation is not None and previous_smooth is not None
                previous_sample = samples[previous_observation]
                dt = estimate.vod_timestamp_s - previous_sample.estimate.vod_timestamp_s
                crossed_teleport = any(
                    item.teleport_before for item in samples[previous_observation + 1 : index + 1]
                )
                assert previous_sample.estimate.position is not None
                speed = self._distance_m(previous_sample.estimate.position, current_point) / dt
                if (
                    dt > self.config.maximum_prediction_gap_s
                    or crossed_teleport
                    or speed > self.config.maximum_speed_mps
                ):
                    can_continue = False
            if can_continue:
                assert previous_smooth is not None
                alpha = self.ema_alpha
                position = NormalizedPoint(
                    x=alpha * current_point.x + (1.0 - alpha) * previous_smooth.x,
                    y=alpha * current_point.y + (1.0 - alpha) * previous_smooth.y,
                )
                evidence = [
                    *sample.context_evidence,
                    *estimate.evidence,
                    f"causal_ema_alpha:{alpha:.6f}",
                    "previous_smoothed_sample",
                ]
                confidence = estimate.confidence
            else:
                position = current_point
                evidence = [
                    *sample.context_evidence,
                    *estimate.evidence,
                    "segment_start_observation",
                ]
                confidence = estimate.confidence
            output[index] = SmoothedTrackSample(
                raw_estimate=estimate,
                position=position,
                observed=True,
                confidence=confidence,
                evidence=evidence,
            )
            previous_observation = index
            previous_smooth = position

        self._interpolate_verified_gaps(samples, output)
        return tuple(output)

    def _interpolate_verified_gaps(
        self,
        samples: list[TrackSmoothingInput],
        output: list[SmoothedTrackSample],
    ) -> None:
        observed_indices = [
            index
            for index, item in enumerate(samples)
            if item.estimate.observed and item.estimate.position is not None
        ]
        for left_index, right_index in zip(observed_indices, observed_indices[1:]):
            if right_index == left_index + 1:
                continue
            left = samples[left_index]
            right = samples[right_index]
            segment = samples[left_index : right_index + 1]
            if not all(self._safe_context(item) for item in segment):
                continue
            if not self._compatible(left, right):
                continue
            if any(item.round_id != left.round_id for item in segment):
                continue
            if any(item.teleport_before for item in segment[1:]):
                continue
            left_time = left.estimate.vod_timestamp_s
            right_time = right.estimate.vod_timestamp_s
            duration = right_time - left_time
            if duration <= 0.0 or duration > self.config.maximum_prediction_gap_s:
                continue
            assert left.estimate.position is not None and right.estimate.position is not None
            left_point = left.estimate.position
            right_point = right.estimate.position
            distance = self._distance_m(left_point, right_point)
            if distance / duration > self.config.maximum_speed_mps:
                continue
            for index in range(left_index + 1, right_index):
                raw = samples[index].estimate
                if raw.position is not None or raw.observed or raw.predicted:
                    continue
                fraction = (raw.vod_timestamp_s - left_time) / duration
                if not 0.0 < fraction < 1.0:
                    continue
                point = NormalizedPoint(
                    x=left_point.x + fraction * (right_point.x - left_point.x),
                    y=left_point.y + fraction * (right_point.y - left_point.y),
                )
                confidence = (
                    min(left.estimate.confidence, right.estimate.confidence)
                    * min(fraction, 1.0 - fraction)
                    * 2.0
                )
                output[index] = SmoothedTrackSample(
                    raw_estimate=raw,
                    position=point,
                    observed=False,
                    interpolated=True,
                    confidence=confidence,
                    evidence=[
                        *samples[index].context_evidence,
                        *left.estimate.evidence,
                        *right.estimate.evidence,
                        "linear_interpolation_between_verified_observations",
                    ],
                )

    def _compatible(self, left: TrackSmoothingInput, right: TrackSmoothingInput) -> bool:
        return (
            left.estimate.player_id == right.estimate.player_id
            and left.round_id is not None
            and left.round_id == right.round_id
            and left.alive is True
            and right.alive is True
            and left.interval_state == "live"
            and right.interval_state == "live"
            and not right.teleport_before
            and left.estimate.vod_timestamp_s < right.estimate.vod_timestamp_s
        )

    @staticmethod
    def _safe_context(sample: TrackSmoothingInput) -> bool:
        return (
            sample.round_id is not None
            and sample.alive is True
            and sample.interval_state == "live"
            and bool(sample.context_evidence)
        )

    def _distance_m(self, first: NormalizedPoint, second: NormalizedPoint) -> float:
        return math.hypot(
            (second.x - first.x) * self.config.map_width_m,
            (second.y - first.y) * self.config.map_height_m,
        )

    @staticmethod
    def _unknown(sample: TrackSmoothingInput, reason: str) -> SmoothedTrackSample:
        return SmoothedTrackSample(
            raw_estimate=sample.estimate,
            position=None,
            observed=False,
            confidence=0.0,
            evidence=[*sample.context_evidence, f"smoothing_rejected:{reason}"],
            rejection_reason=reason,
        )

    @staticmethod
    def _validate_sequence(samples: list[TrackSmoothingInput]) -> None:
        if not samples:
            return
        player_ids = {sample.estimate.player_id for sample in samples}
        if len(player_ids) != 1:
            raise ValueError("smoothing sequence must contain exactly one player")
        timestamps = [sample.estimate.vod_timestamp_s for sample in samples]
        if any(right <= left for left, right in zip(timestamps, timestamps[1:])):
            raise ValueError("smoothing timestamps must be strictly increasing")
