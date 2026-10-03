"""Tests for tactical preflight validation and execution planning."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from valoscribe.tactical.config import CropConfig, HSVRange, TransformConfig
from valoscribe.tactical.manifest import (
    ExcludedSpan,
    RoundManifestEntry,
    TeamColorCalibration,
    TeamManifestDefinition,
    VODBroadcastProfile,
    VODRoundManifest,
)
from valoscribe.tactical.preflight import (
    PreflightValidationError,
    ResolvedRoundPlan,
    RoundRangeResolutionError,
    VODExecutionPlan,
    validate_vod_preflight,
)


@pytest.fixture
def sample_profile() -> VODBroadcastProfile:
    return VODBroadcastProfile(
        profile_id="ascent-vct-2024",
        calibration_status="calibrated",
        minimap_crop=CropConfig(x=70, y=50, width=360, height=400),
        transform=TransformConfig(
            method="affine",
            input_coordinates="crop_px",
            output_coordinates="canonical_px",
            matrix=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
            training_points=4,
            training_residual_mean_rms_max_px=[0.5, 0.5, 0.5],
            calibration_status="calibrated",
        ),
        team_calibrations={
            "100T": TeamColorCalibration(
                team_id="100T",
                color_ranges_hsv=[HSVRange(lower=(0, 100, 100), upper=(10, 255, 255))],
            ),
            "LOUD": TeamColorCalibration(
                team_id="LOUD",
                color_ranges_hsv=[HSVRange(lower=(40, 100, 100), upper=(80, 255, 255))],
            ),
        },
    )


@pytest.fixture
def sample_manifest() -> VODRoundManifest:
    teams = {
        "100T": TeamManifestDefinition(
            team_id="100T",
            name="100 Thieves",
            starting_side="attack",
            broadcast_slot="left",
            broadcast_color_label="red",
        ),
        "LOUD": TeamManifestDefinition(
            team_id="LOUD",
            name="LOUD",
            starting_side="defense",
            broadcast_slot="right",
            broadcast_color_label="green",
        ),
    }
    rounds = [
        RoundManifestEntry(
            map_round=i,
            round_id=f"map3-round{i}",
            source_start_seconds=100.0 * i,
            source_end_seconds=100.0 * i + 80.0,
            live_start_seconds=100.0 * i + 15.0,
            status="confirmed" if i != 8 else "unresolved",
            team_sides={"100T": "attack", "LOUD": "defense"}
            if i <= 12
            else {"100T": "defense", "LOUD": "attack"},
            boundary_evidence=f"evidence {i}",
            excluded_spans=[
                ExcludedSpan(
                    start_seconds=100.0 * i + 20.0,
                    end_seconds=100.0 * i + 25.0,
                    reason="tech replay",
                )
            ]
            if i == 5
            else [],
        )
        for i in range(1, 15)
    ]
    return VODRoundManifest(
        schema_version=1,
        source_video_sha256="0123456789abcdef" * 4,
        match_id="match-1",
        map_id="map3",
        map_name="ascent",
        teams=teams,
        halftime_after_round=12,
        rounds=rounds,
        reviewer="rev",
    )


def test_preflight_success_with_halftime_range(
    tmp_path: Path, sample_manifest: VODRoundManifest, sample_profile: VODBroadcastProfile
) -> None:
    fake_vod = tmp_path / "video.mp4"
    fake_vod.write_bytes(b"dummy video content")
    output_dir = tmp_path / "output_run"

    plan = validate_vod_preflight(
        vod_path=fake_vod,
        map_name="ascent",
        match_id="match-1",
        map_id="map3",
        from_round=11,
        to_round=14,
        selected_team_id="100T",
        manifest=sample_manifest,
        profile=sample_profile,
        output_dir=output_dir,
        verify_sha256=False,
    )
    assert isinstance(plan, VODExecutionPlan)
    assert plan.selected_team_id == "100T"
    assert plan.opponent_team_id == "LOUD"
    assert len(plan.selected_rounds) == 4
    assert isinstance(plan.selected_rounds[0], ResolvedRoundPlan)
    # Round 11: 100T is attack; Round 13 (after halftime): 100T is defense
    assert plan.selected_rounds[0].selected_team_side == "attack"
    assert plan.selected_rounds[0].opponent_team_side == "defense"
    assert plan.selected_rounds[0].live_start_offset_seconds == 15.0
    assert plan.selected_rounds[0].source_interval_seconds == (1100.0, 1180.0)
    assert plan.selected_rounds[2].selected_team_side == "defense"
    assert plan.selected_rounds[2].opponent_team_side == "attack"
    assert len(plan.selected_team_calibrations) == 1
    assert len(plan.opponent_team_calibrations) == 1


def test_preflight_success_preserves_excluded_spans(
    tmp_path: Path, sample_manifest: VODRoundManifest, sample_profile: VODBroadcastProfile
) -> None:
    fake_vod = tmp_path / "video.mp4"
    fake_vod.write_bytes(b"dummy video content")
    output_dir = tmp_path / "output_run"

    plan = validate_vod_preflight(
        vod_path=fake_vod,
        map_name="ascent",
        match_id="match-1",
        map_id="map3",
        from_round=4,
        to_round=6,
        selected_team_id="100T",
        manifest=sample_manifest,
        profile=sample_profile,
        output_dir=output_dir,
        verify_sha256=False,
    )
    assert len(plan.selected_rounds) == 3
    r5 = plan.selected_rounds[1]
    assert r5.map_round == 5
    assert len(r5.excluded_intervals) == 1
    assert r5.excluded_intervals[0]["reason"] == "tech replay"


def test_preflight_fails_on_unconfirmed_or_missing_round(
    tmp_path: Path, sample_manifest: VODRoundManifest, sample_profile: VODBroadcastProfile
) -> None:
    fake_vod = tmp_path / "video.mp4"
    fake_vod.write_bytes(b"dummy")
    output_dir = tmp_path / "output_run"

    # Range [7, 9] includes round 8 which has status="unresolved"
    with pytest.raises(RoundRangeResolutionError) as exc_info:
        validate_vod_preflight(
            vod_path=fake_vod,
            map_name="ascent",
            match_id="match-1",
            map_id="map3",
            from_round=7,
            to_round=9,
            selected_team_id="100T",
            manifest=sample_manifest,
            profile=sample_profile,
            output_dir=output_dir,
            verify_sha256=False,
        )
    assert "Round 8 is 'unresolved'" in str(exc_info.value)
    assert "unconfirmed or missing" in str(exc_info.value)


def test_preflight_fails_when_output_dir_exists_with_files(
    tmp_path: Path, sample_manifest: VODRoundManifest, sample_profile: VODBroadcastProfile
) -> None:
    fake_vod = tmp_path / "video.mp4"
    fake_vod.write_bytes(b"dummy")
    output_dir = tmp_path / "output_run"
    output_dir.mkdir()
    (output_dir / "existing.txt").write_text("hello")

    with pytest.raises(FileExistsError, match="Refusing to overwrite existing output"):
        validate_vod_preflight(
            vod_path=fake_vod,
            map_name="ascent",
            match_id="match-1",
            map_id="map3",
            from_round=1,
            to_round=3,
            selected_team_id="100T",
            manifest=sample_manifest,
            profile=sample_profile,
            output_dir=output_dir,
            verify_sha256=False,
        )


def test_preflight_succeeds_when_output_dir_is_empty(
    tmp_path: Path, sample_manifest: VODRoundManifest, sample_profile: VODBroadcastProfile
) -> None:
    fake_vod = tmp_path / "video.mp4"
    fake_vod.write_bytes(b"dummy")
    output_dir = tmp_path / "output_run_empty"
    output_dir.mkdir()

    plan = validate_vod_preflight(
        vod_path=fake_vod,
        map_name="ascent",
        match_id="match-1",
        map_id="map3",
        from_round=1,
        to_round=3,
        selected_team_id="100T",
        manifest=sample_manifest,
        profile=sample_profile,
        output_dir=output_dir,
        verify_sha256=False,
    )
    assert len(plan.selected_rounds) == 3


def test_preflight_fails_when_vod_file_missing(
    tmp_path: Path, sample_manifest: VODRoundManifest, sample_profile: VODBroadcastProfile
) -> None:
    non_existent_vod = tmp_path / "non_existent.mp4"
    output_dir = tmp_path / "output_run"

    with pytest.raises(PreflightValidationError, match="VOD source file does not exist"):
        validate_vod_preflight(
            vod_path=non_existent_vod,
            map_name="ascent",
            match_id="match-1",
            map_id="map3",
            from_round=1,
            to_round=3,
            selected_team_id="100T",
            manifest=sample_manifest,
            profile=sample_profile,
            output_dir=output_dir,
            verify_sha256=False,
        )


def test_preflight_sha256_verification(
    tmp_path: Path, sample_manifest: VODRoundManifest, sample_profile: VODBroadcastProfile
) -> None:
    fake_vod = tmp_path / "video.mp4"
    data = b"video data chunk 12345"
    fake_vod.write_bytes(data)
    actual_sha = hashlib.sha256(data).hexdigest()
    output_dir = tmp_path / "output_run"

    # Mismatch fails
    with pytest.raises(PreflightValidationError, match="VOD SHA-256 mismatch"):
        validate_vod_preflight(
            vod_path=fake_vod,
            map_name="ascent",
            match_id="match-1",
            map_id="map3",
            from_round=1,
            to_round=3,
            selected_team_id="100T",
            manifest=sample_manifest,
            profile=sample_profile,
            output_dir=output_dir,
            verify_sha256=True,
        )

    # Correct SHA passes
    sample_manifest.source_video_sha256 = actual_sha
    plan = validate_vod_preflight(
        vod_path=fake_vod,
        map_name="ascent",
        match_id="match-1",
        map_id="map3",
        from_round=1,
        to_round=3,
        selected_team_id="100T",
        manifest=sample_manifest,
        profile=sample_profile,
        output_dir=output_dir,
        verify_sha256=True,
    )
    assert plan.source_video_sha256 == actual_sha


def test_preflight_fails_on_unsupported_map(
    tmp_path: Path, sample_manifest: VODRoundManifest, sample_profile: VODBroadcastProfile
) -> None:
    fake_vod = tmp_path / "video.mp4"
    fake_vod.write_bytes(b"dummy")
    output_dir = tmp_path / "output_run"

    with pytest.raises(PreflightValidationError, match="Unsupported map"):
        validate_vod_preflight(
            vod_path=fake_vod,
            map_name="bind",
            match_id="match-1",
            map_id="map3",
            from_round=1,
            to_round=3,
            selected_team_id="100T",
            manifest=sample_manifest,
            profile=sample_profile,
            output_dir=output_dir,
            verify_sha256=False,
        )


def test_preflight_fails_on_unknown_team(
    tmp_path: Path, sample_manifest: VODRoundManifest, sample_profile: VODBroadcastProfile
) -> None:
    fake_vod = tmp_path / "video.mp4"
    fake_vod.write_bytes(b"dummy")
    output_dir = tmp_path / "output_run"

    with pytest.raises(PreflightValidationError, match="Selected team 'SEN' not found"):
        validate_vod_preflight(
            vod_path=fake_vod,
            map_name="ascent",
            match_id="match-1",
            map_id="map3",
            from_round=1,
            to_round=3,
            selected_team_id="SEN",
            manifest=sample_manifest,
            profile=sample_profile,
            output_dir=output_dir,
            verify_sha256=False,
        )


def test_preflight_fails_on_uncalibrated_team(
    tmp_path: Path, sample_manifest: VODRoundManifest, sample_profile: VODBroadcastProfile
) -> None:
    fake_vod = tmp_path / "video.mp4"
    fake_vod.write_bytes(b"dummy")
    output_dir = tmp_path / "output_run"

    del sample_profile.team_calibrations["LOUD"]
    with pytest.raises(PreflightValidationError, match="Opponent team 'LOUD' missing calibration"):
        validate_vod_preflight(
            vod_path=fake_vod,
            map_name="ascent",
            match_id="match-1",
            map_id="map3",
            from_round=1,
            to_round=3,
            selected_team_id="100T",
            manifest=sample_manifest,
            profile=sample_profile,
            output_dir=output_dir,
            verify_sha256=False,
        )


def test_preflight_fails_on_invalid_round_range(
    tmp_path: Path, sample_manifest: VODRoundManifest, sample_profile: VODBroadcastProfile
) -> None:
    fake_vod = tmp_path / "video.mp4"
    fake_vod.write_bytes(b"dummy")
    output_dir = tmp_path / "output_run"

    with pytest.raises(RoundRangeResolutionError, match="Invalid round range"):
        validate_vod_preflight(
            vod_path=fake_vod,
            map_name="ascent",
            match_id="match-1",
            map_id="map3",
            from_round=5,
            to_round=3,
            selected_team_id="100T",
            manifest=sample_manifest,
            profile=sample_profile,
            output_dir=output_dir,
            verify_sha256=False,
        )


def test_preflight_fails_on_round_missing_from_manifest(
    tmp_path: Path, sample_manifest: VODRoundManifest, sample_profile: VODBroadcastProfile
) -> None:
    fake_vod = tmp_path / "video.mp4"
    fake_vod.write_bytes(b"dummy")
    output_dir = tmp_path / "output_run"

    with pytest.raises(RoundRangeResolutionError) as exc_info:
        validate_vod_preflight(
            vod_path=fake_vod,
            map_name="ascent",
            match_id="match-1",
            map_id="map3",
            from_round=13,
            to_round=16,
            selected_team_id="100T",
            manifest=sample_manifest,
            profile=sample_profile,
            output_dir=output_dir,
            verify_sha256=False,
        )
    assert "Round 15 is missing from manifest" in str(exc_info.value)
    assert "Round 16 is missing from manifest" in str(exc_info.value)
