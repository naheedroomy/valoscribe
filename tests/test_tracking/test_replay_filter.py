from __future__ import annotations

import pytest

from valoscribe.tracking.replay_filter import BroadcastStateClassifier
from valoscribe.types.persistent import (
    BroadcastFrameObservation,
    BroadcastPhase,
)


def observation(timestamp: float, **overrides: object) -> BroadcastFrameObservation:
    values: dict[str, object] = {
        "vod_timestamp_s": timestamp,
        "round_id": "round-1",
        "phase": BroadcastPhase.LIVE,
        "minimap_visible": True,
        "hud_visible": True,
        "timer_continuous": True,
        "confidence": 0.9,
        "evidence": ["synthetic_frame_observation"],
    }
    values.update(overrides)
    return BroadcastFrameObservation.model_validate(values)


def test_live_requires_visibility_continuity_confidence_and_evidence() -> None:
    interval = BroadcastStateClassifier().classify(observation(1.0))
    assert interval.phase == BroadcastPhase.LIVE
    assert interval.rejection_reason is None

    for data, reason in [
        ({"minimap_visible": False}, "hud_or_minimap_hidden"),
        ({"timer_continuous": False}, "round_continuity_missing"),
        ({"confidence": 0.1}, "frame_confidence_below_threshold"),
        ({"evidence": []}, "broadcast_evidence_missing"),
        ({"phase": BroadcastPhase.PAUSED}, "broadcast_paused"),
        ({"replay_cue": True}, "replay_cue_or_duplicate"),
        ({"historical_duplicate": True}, "replay_cue_or_duplicate"),
    ]:
        rejected = BroadcastStateClassifier().classify(observation(1.0, **data))
        assert rejected.phase != BroadcastPhase.LIVE
        assert rejected.rejection_reason == reason
        assert any(item == f"broadcast_rejected:{reason}" for item in rejected.evidence)


def test_out_of_order_rejected_and_round_change_resets_context() -> None:
    classifier = BroadcastStateClassifier()
    assert classifier.classify(observation(2.0)).phase == BroadcastPhase.LIVE
    assert classifier.classify(observation(1.0)).rejection_reason == "out_of_order_timestamp"
    next_round = classifier.classify(observation(3.0, round_id="round-2"))
    assert next_round.phase == BroadcastPhase.LIVE


def test_replay_cue_overrides_live_without_advancing_replay_to_live() -> None:
    classifier = BroadcastStateClassifier()
    replay = classifier.classify(observation(1.0, replay_cue=True))
    live = classifier.classify(observation(2.0))
    assert replay.phase == BroadcastPhase.REPLAY
    assert live.phase == BroadcastPhase.LIVE
    with pytest.raises(ValueError):
        BroadcastStateClassifier(minimum_confidence=1.1)
