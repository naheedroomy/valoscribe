from valoscribe.tactical.contracts import (
    CorrectionDelta,
    MarkerAdjudication,
    RawMarkerObservation,
    TeamFrameState,
)


def test_raw_marker_observation_defaults_team_id_to_single_team() -> None:
    obs = RawMarkerObservation(
        run_id="run-1",
        round_id="round-1",
        sample_index=0,
        source_timestamp_seconds=10.0,
        crop_x=50.0,
        crop_y=60.0,
        confidence=0.9,
        detector_version="v1",
    )
    assert obs.team_id == "single-team"

    # Explicit team_id
    obs_team = RawMarkerObservation(
        run_id="run-1",
        round_id="round-1",
        sample_index=0,
        source_timestamp_seconds=10.0,
        crop_x=50.0,
        crop_y=60.0,
        confidence=0.9,
        detector_version="v1",
        team_id="100T",
    )
    assert obs_team.team_id == "100T"


def test_team_frame_state_defaults_team_id() -> None:
    state = TeamFrameState(
        run_id="run-1",
        round_id="round-1",
        sample_index=0,
        source_timestamp_seconds=10.0,
        observed_marker_count=2,
        coverage_status="good",
    )
    assert state.team_id == "single-team"


def test_correction_delta_and_adjudication_defaults_team_id() -> None:
    delta = CorrectionDelta(
        correction_id="c1",
        run_id="run-1",
        round_id="round-1",
        sample_index=0,
        operation="add",
        reviewer="rev",
    )
    assert delta.team_id == "single-team"

    adjudication = MarkerAdjudication(
        adjudication_id="adj-1",
        run_id="run-1",
        round_id="round-1",
        sample_index=0,
        target_observation_id="obs-1",
        disposition="supported",
        reviewer="rev",
        source_locator="src:10",
        source_timestamp_seconds=10.0,
        confidence=1.0,
    )
    assert adjudication.team_id == "single-team"
