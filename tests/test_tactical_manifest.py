"""Tests for VOD round manifest and broadcast profile contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from valoscribe.tactical.config import CropConfig, HSVRange, TransformConfig
from valoscribe.tactical.manifest import (
    ExcludedSpan,
    RoundManifestEntry,
    TeamColorCalibration,
    TeamManifestDefinition,
    VODBroadcastProfile,
    VODRoundManifest,
    load_manifest,
    load_profile,
)


def test_round_manifest_entry_validates_intervals() -> None:
    # Valid entry
    entry = RoundManifestEntry(
        map_round=1,
        round_id="map3-round1",
        source_start_seconds=100.0,
        source_end_seconds=180.0,
        live_start_seconds=115.0,
        status="confirmed",
        team_sides={"100T": "attack", "LOUD": "defense"},
        boundary_evidence="live timer 1:40 at 115s",
        excluded_spans=[
            ExcludedSpan(start_seconds=120.0, end_seconds=125.0, reason="replay")
        ],
    )
    assert entry.map_round == 1
    assert entry.status == "confirmed"

    # End before start fails
    with pytest.raises(ValidationError, match="end_seconds must be greater than start_seconds"):
        RoundManifestEntry(
            map_round=1,
            round_id="map3-round1",
            source_start_seconds=200.0,
            source_end_seconds=180.0,
            live_start_seconds=190.0,
            status="confirmed",
            team_sides={"100T": "attack", "LOUD": "defense"},
            boundary_evidence="evidence",
        )

    # Excluded span outside round interval fails
    with pytest.raises(ValidationError, match="excluded span must fall within"):
        RoundManifestEntry(
            map_round=1,
            round_id="map3-round1",
            source_start_seconds=100.0,
            source_end_seconds=180.0,
            live_start_seconds=115.0,
            status="confirmed",
            team_sides={"100T": "attack", "LOUD": "defense"},
            boundary_evidence="evidence",
            excluded_spans=[
                ExcludedSpan(start_seconds=50.0, end_seconds=60.0, reason="outside")
            ],
        )


def test_vod_round_manifest_validates_unique_rounds_and_teams() -> None:
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

    round_1 = RoundManifestEntry(
        map_round=1,
        round_id="map3-round1",
        source_start_seconds=100.0,
        source_end_seconds=180.0,
        live_start_seconds=115.0,
        status="confirmed",
        team_sides={"100T": "attack", "LOUD": "defense"},
        boundary_evidence="evidence",
    )

    manifest = VODRoundManifest(
        schema_version=1,
        source_video_sha256="a" * 64,
        match_id="match-1",
        map_id="map3",
        map_name="ascent",
        teams=teams,
        halftime_after_round=12,
        rounds=[round_1],
        reviewer="reviewer1",
    )
    assert len(manifest.rounds) == 1

    # Duplicate map_round fails
    with pytest.raises(ValidationError, match="round numbers must be unique"):
        VODRoundManifest(
            schema_version=1,
            source_video_sha256="a" * 64,
            match_id="match-1",
            map_id="map3",
            map_name="ascent",
            teams=teams,
            rounds=[round_1, round_1],
            reviewer="reviewer1",
        )


def test_vod_broadcast_profile_validates_both_teams() -> None:
    crop = CropConfig(x=70, y=50, width=360, height=400)
    transform = TransformConfig(
        method="affine",
        input_coordinates="crop_px",
        output_coordinates="canonical_px",
        matrix=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
        training_points=4,
        training_residual_mean_rms_max_px=[0.5, 0.5, 0.5],
        calibration_status="calibrated",
    )
    calibrations = {
        "100T": TeamColorCalibration(
            team_id="100T",
            color_ranges_hsv=[HSVRange(lower=(0, 100, 100), upper=(10, 255, 255))],
        ),
        "LOUD": TeamColorCalibration(
            team_id="LOUD",
            color_ranges_hsv=[HSVRange(lower=(40, 100, 100), upper=(80, 255, 255))],
        ),
    }
    profile = VODBroadcastProfile(
        profile_id="ascent-vct-2024",
        calibration_status="calibrated",
        minimap_crop=crop,
        transform=transform,
        team_calibrations=calibrations,
    )
    assert "100T" in profile.team_calibrations
    assert "LOUD" in profile.team_calibrations


def test_excluded_span_validation() -> None:
    span = ExcludedSpan(start_seconds=10.0, end_seconds=20.0, reason="replay")
    assert span.start_seconds == 10.0
    assert span.end_seconds == 20.0

    with pytest.raises(ValidationError, match="end_seconds must be greater than start_seconds"):
        ExcludedSpan(start_seconds=20.0, end_seconds=10.0, reason="invalid")


def test_round_manifest_entry_live_start_validation() -> None:
    with pytest.raises(ValidationError, match="live_start_seconds must fall within"):
        RoundManifestEntry(
            map_round=1,
            round_id="map3-round1",
            source_start_seconds=100.0,
            source_end_seconds=180.0,
            live_start_seconds=90.0,
            status="confirmed",
            team_sides={"100T": "attack", "LOUD": "defense"},
            boundary_evidence="evidence",
        )


def test_vod_round_manifest_validates_round_ids_and_unknown_teams() -> None:
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

    round_1 = RoundManifestEntry(
        map_round=1,
        round_id="map3-round1",
        source_start_seconds=100.0,
        source_end_seconds=180.0,
        live_start_seconds=115.0,
        status="confirmed",
        team_sides={"100T": "attack", "LOUD": "defense"},
        boundary_evidence="evidence",
    )
    round_2_duplicate_id = RoundManifestEntry(
        map_round=2,
        round_id="map3-round1",
        source_start_seconds=190.0,
        source_end_seconds=270.0,
        live_start_seconds=205.0,
        status="confirmed",
        team_sides={"100T": "attack", "LOUD": "defense"},
        boundary_evidence="evidence",
    )

    with pytest.raises(ValidationError, match="round IDs must be unique"):
        VODRoundManifest(
            schema_version=1,
            source_video_sha256="a" * 64,
            match_id="match-1",
            map_id="map3",
            map_name="ascent",
            teams=teams,
            rounds=[round_1, round_2_duplicate_id],
            reviewer="reviewer1",
        )

    round_unknown_team = RoundManifestEntry(
        map_round=2,
        round_id="map3-round2",
        source_start_seconds=190.0,
        source_end_seconds=270.0,
        live_start_seconds=205.0,
        status="confirmed",
        team_sides={"UNKNOWN": "attack", "LOUD": "defense"},
        boundary_evidence="evidence",
    )

    with pytest.raises(ValidationError, match="references unknown team"):
        VODRoundManifest(
            schema_version=1,
            source_video_sha256="a" * 64,
            match_id="match-1",
            map_id="map3",
            map_name="ascent",
            teams=teams,
            rounds=[round_1, round_unknown_team],
            reviewer="reviewer1",
        )


def test_load_manifest_and_load_profile_roundtrip(tmp_path: Path) -> None:
    manifest_data = {
        "schema_version": 1,
        "source_video_sha256": "f" * 64,
        "match_id": "test-match",
        "map_id": "map-1",
        "map_name": "ascent",
        "teams": {
            "T1": {
                "team_id": "T1",
                "name": "Team One",
                "starting_side": "attack",
                "broadcast_slot": "left",
                "broadcast_color_label": "red",
            },
            "T2": {
                "team_id": "T2",
                "name": "Team Two",
                "starting_side": "defense",
                "broadcast_slot": "right",
                "broadcast_color_label": "green",
            },
        },
        "halftime_after_round": 12,
        "rounds": [
            {
                "map_round": 1,
                "round_id": "r1",
                "source_start_seconds": 10.0,
                "source_end_seconds": 90.0,
                "live_start_seconds": 25.0,
                "status": "confirmed",
                "team_sides": {"T1": "attack", "T2": "defense"},
                "boundary_evidence": "timer",
                "excluded_spans": [],
            }
        ],
        "reviewer": "test_reviewer",
        "review_method": "manual",
        "notes": "test note",
    }
    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")

    loaded_manifest = load_manifest(manifest_file)
    assert loaded_manifest.match_id == "test-match"
    assert loaded_manifest.rounds[0].round_id == "r1"

    profile_data = {
        "profile_id": "prof-1",
        "calibration_status": "calibrated",
        "minimap_crop": {
            "x": 70,
            "y": 50,
            "width": 360,
            "height": 400,
            "orientation": "identity",
        },
        "transform": {
            "method": "affine",
            "input_coordinates": "crop_px",
            "output_coordinates": "canonical_px",
            "matrix": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
            "training_points": 4,
            "training_residual_mean_rms_max_px": [0.5, 0.5, 0.5],
            "calibration_status": "calibrated",
        },
        "team_calibrations": {
            "T1": {
                "team_id": "T1",
                "color_ranges_hsv": [{"lower": [0, 100, 100], "upper": [10, 255, 255]}],
            },
            "T2": {
                "team_id": "T2",
                "color_ranges_hsv": [{"lower": [40, 100, 100], "upper": [80, 255, 255]}],
            },
        },
    }
    profile_file = tmp_path / "profile.json"
    profile_file.write_text(json.dumps(profile_data), encoding="utf-8")

    loaded_profile = load_profile(profile_file)
    assert loaded_profile.profile_id == "prof-1"
    assert "T1" in loaded_profile.team_calibrations

    # Test invalid json error
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("invalid json content", encoding="utf-8")
    with pytest.raises(ValueError, match="manifest must be valid JSON"):
        load_manifest(bad_file)
    with pytest.raises(ValueError, match="profile must be valid JSON"):
        load_profile(bad_file)


def test_example_manifest_and_profile_fixtures_load() -> None:
    from pathlib import Path

    from valoscribe.tactical.manifest import load_manifest, load_profile

    root = Path(__file__).parents[1]
    manifest_path = root / "configs/examples/ascent-map3-rounds.example.json"
    profile_path = root / "configs/examples/ascent-vct-profile.example.json"

    assert manifest_path.is_file()
    assert profile_path.is_file()

    manifest = load_manifest(manifest_path)
    assert manifest.map_name == "ascent"
    assert "100T" in manifest.teams
    assert "LOUD" in manifest.teams
    assert len(manifest.rounds) >= 5

    profile = load_profile(profile_path)
    assert "100T" in profile.team_calibrations
    assert "LOUD" in profile.team_calibrations

