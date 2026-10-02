import pytest

from valoscribe.analytics.phases import DeterministicPhaseEngine
from valoscribe.types.persistent import PhaseObservation, RoundPhase


def observation(timestamp: float, **changes: object) -> PhaseObservation:
    values: dict[str, object] = {
        "match_id": "match",
        "map_id": "ascent",
        "round_id": "r1",
        "vod_timestamp_s": timestamp,
        "confidence": 0.9,
        "evidence": ["synthetic_signal"],
    }
    values.update(changes)
    return PhaseObservation(**values)


@pytest.mark.parametrize(
    ("signal", "expected"),
    [
        ("preround", RoundPhase.PREROUND),
        ("opening", RoundPhase.OPENING),
        ("default", RoundPhase.DEFAULT),
        ("pressure", RoundPhase.PRESSURE),
        ("contact", RoundPhase.CONTACT),
        ("regroup", RoundPhase.REGROUP),
        ("rotate", RoundPhase.ROTATE),
        ("execute", RoundPhase.EXECUTE),
        ("planted", RoundPhase.POST_PLANT),
        ("retake", RoundPhase.RETAKE),
        ("save", RoundPhase.SAVE),
        ("clutch", RoundPhase.CLUTCH),
        ("round_end", RoundPhase.ROUND_END),
    ],
)
def test_explicit_signal_maps_to_evidence_backed_phase(signal: str, expected: RoundPhase) -> None:
    result = DeterministicPhaseEngine().observe(observation(1, **{signal: True}))
    assert result.phase == expected
    assert result.confidence == 0.9
    assert "synthetic_signal" in result.evidence
    assert f"phase_rule:{expected.value.lower()}" in result.evidence


def test_no_signal_and_conflicts_fail_closed() -> None:
    engine = DeterministicPhaseEngine()
    assert engine.observe(observation(1)).phase == RoundPhase.UNKNOWN
    conflict = engine.observe(observation(2, execute=True, conflicting_signals=["execute_vs_save"]))
    assert conflict.phase == RoundPhase.UNKNOWN
    assert conflict.confidence == 0
    assert conflict.diagnostics[0].code == "conflicting_phase_signals"


def test_rule_precedence_and_explicit_ontology_override() -> None:
    engine = DeterministicPhaseEngine()
    assert (
        engine.observe(observation(1, opening=True, planted=True, pressure=True)).phase
        == RoundPhase.POST_PLANT
    )
    assert (
        engine.observe(observation(2, explicit_phase=RoundPhase.CONTACT, planted=True)).phase
        == RoundPhase.CONTACT
    )


def test_ordering_replay_and_round_reset() -> None:
    engine = DeterministicPhaseEngine()
    engine.observe(observation(2, opening=True))
    replay = engine.observe(observation(3, replay=True, execute=True))
    assert replay.phase == RoundPhase.UNKNOWN
    assert replay.diagnostics[0].code == "replay_excluded"
    assert (
        engine.observe(observation(1.5, default=True)).diagnostics[0].code
        == "out_of_order_timestamp"
    )
    next_round = engine.observe(observation(0.5, round_id="r2", preround=True))
    assert next_round.phase == RoundPhase.PREROUND
    assert len(engine.segments) == 1


def test_adjacent_same_phase_observations_extend_without_interpolation() -> None:
    engine = DeterministicPhaseEngine()
    engine.observe(observation(1, opening=True))
    merged = engine.observe(observation(2, opening=True, evidence=["second_explicit_cue"]))
    assert len(engine.segments) == 1
    assert merged.start_timestamp_s == 1
    assert merged.end_timestamp_s == 2
    assert "second_explicit_cue" in merged.evidence
    assert engine.observe(observation(3, rotate=True)).start_timestamp_s == 3
