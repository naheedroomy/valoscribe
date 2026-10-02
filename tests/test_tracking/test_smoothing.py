from __future__ import annotations

import pytest

from valoscribe.tracking.smoothing import TrackSmoother
from valoscribe.types.persistent import (
    MotionModelConfig,
    NormalizedPoint,
    PlayerTrackEstimate,
    TrackSmoothingInput,
)

CONFIG = MotionModelConfig(
    map_width_m=100.0,
    map_height_m=100.0,
    maximum_speed_mps=8.0,
    maximum_prediction_gap_s=1.0,
    minimum_detection_confidence=0.5,
    minimum_registration_confidence=0.8,
)
SMOOTHER = TrackSmoother(CONFIG, ema_alpha=0.5)


def estimate(
    timestamp: float,
    x: float | None,
    *,
    observed: bool = True,
    confidence: float = 0.9,
) -> PlayerTrackEstimate:
    return PlayerTrackEstimate(
        player_id="p1",
        vod_timestamp_s=timestamp,
        source_frame=int(timestamp * 10),
        position=NormalizedPoint(x=x, y=0.5) if x is not None else None,
        observed=observed if x is not None else False,
        predicted=False,
        confidence=confidence if x is not None else 0.0,
        evidence=[f"raw:{timestamp}"],
        rejection_reason=None if x is not None else "detection_missing",
    )


def sample(
    timestamp: float,
    x: float | None,
    *,
    round_id: str | None = "r1",
    alive: bool | None = True,
    state: str = "live",
    teleport_before: bool = False,
) -> TrackSmoothingInput:
    return TrackSmoothingInput(
        estimate=estimate(timestamp, x),
        round_id=round_id,
        alive=alive,
        interval_state=state,
        teleport_before=teleport_before,
        context_evidence=["reviewed_context"],
    )


def test_causal_ema_and_linear_gap_interpolation_preserve_raw_samples() -> None:
    raw = [sample(1.0, 0.2), sample(1.5, None), sample(2.0, 0.24)]

    result = SMOOTHER.smooth(raw)

    assert result[0].position == NormalizedPoint(x=0.2, y=0.5)
    assert result[0].observed and not result[0].interpolated
    assert result[1].position == NormalizedPoint(x=0.22, y=0.5)
    assert result[1].interpolated and not result[1].observed
    assert result[1].raw_estimate == raw[1].estimate
    assert result[1].confidence > 0.0
    assert result[2].position == NormalizedPoint(x=0.22, y=0.5)
    assert result[2].raw_estimate == raw[2].estimate
    assert raw[2].estimate.position == NormalizedPoint(x=0.24, y=0.5)


@pytest.mark.parametrize(
    ("middle", "right_timestamp", "expected_reason"),
    [
        ({"state": "replay"}, 2.0, "context_not_verified"),
        ({"state": "paused"}, 2.0, "context_not_verified"),
        ({"state": "hidden"}, 2.0, "context_not_verified"),
        ({"alive": False}, 2.0, "context_not_verified"),
        ({"round_id": "r2"}, 2.0, "context_not_verified"),
        ({"teleport_before": True}, 2.0, "context_not_verified"),
        ({"round_id": "r1"}, 3.0, "context_not_verified"),
    ],
)
def test_interpolation_fails_closed_across_unsafe_segments(
    middle: dict[str, object], right_timestamp: float, expected_reason: str
) -> None:
    left_sample = sample(1.0, 0.2)
    middle_sample = sample(1.5, None, **middle)
    right_sample = sample(right_timestamp, 0.24)
    result = SMOOTHER.smooth([left_sample, middle_sample, right_sample])

    assert result[1].position is None
    assert result[1].rejection_reason == expected_reason
    assert result[1].raw_estimate == middle_sample.estimate


def test_interpolation_rejects_speed_above_configured_map_gate() -> None:
    result = SMOOTHER.smooth([sample(1.0, 0.2), sample(1.5, None), sample(2.0, 0.4)])

    assert result[1].position is None
    assert result[1].rejection_reason == "context_not_verified"


def test_smoothing_refuses_unverified_or_unknown_context() -> None:
    missing_round = sample(1.0, 0.2, round_id=None)
    no_evidence = sample(1.1, 0.2).model_copy(update={"context_evidence": []})
    unknown_state = sample(1.2, 0.2, state="unknown")

    for result in SMOOTHER.smooth([missing_round, no_evidence, unknown_state]):
        assert result.position is None
        assert result.confidence == 0.0
        assert result.rejection_reason == "context_not_verified"


def test_teleport_on_observed_endpoint_resets_ema() -> None:
    result = SMOOTHER.smooth([sample(1.0, 0.2), sample(1.2, 0.21, teleport_before=True)])

    assert result[1].position == NormalizedPoint(x=0.21, y=0.5)
    assert result[1].evidence[-1] == "segment_start_observation"


def test_teleport_in_missing_sample_resets_ema_across_gap() -> None:
    result = SMOOTHER.smooth(
        [sample(1.0, 0.2), sample(1.1, None, teleport_before=True), sample(1.2, 0.21)]
    )

    assert result[1].position is None
    assert result[2].position == NormalizedPoint(x=0.21, y=0.5)
    assert result[2].evidence[-1] == "segment_start_observation"


def test_implausible_speed_resets_ema() -> None:
    result = SMOOTHER.smooth([sample(1.0, 0.2), sample(1.1, 0.4)])

    assert result[1].position == NormalizedPoint(x=0.4, y=0.5)
    assert result[1].evidence[-1] == "segment_start_observation"


def test_invalid_alpha_and_nonincreasing_timestamps_are_rejected() -> None:
    with pytest.raises(ValueError, match="ema_alpha"):
        TrackSmoother(CONFIG, ema_alpha=0)
    with pytest.raises(ValueError, match="strictly increasing"):
        SMOOTHER.smooth([sample(1.0, 0.2), sample(1.0, 0.3)])
