import json
from pathlib import Path

from typer.testing import CliRunner

from valoscribe.tactical.cli import app

runner = CliRunner()


def test_analyze_vod_preflight_success(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    manifest_path = root / "configs/examples/ascent-map3-rounds.example.json"
    profile_path = root / "configs/examples/ascent-vct-profile.example.json"
    fake_vod = tmp_path / "vod.mp4"
    fake_vod.write_bytes(b"dummy video")
    output_dir = tmp_path / "run_out"

    result = runner.invoke(
        app,
        [
            "analyze-vod",
            "--vod", str(fake_vod),
            "--map", "ascent",
            "--match", "vct-americas-grand-final",
            "--map-id", "map3",
            "--from-round", "4",
            "--to-round", "7",
            "--team", "100T",
            "--profile", str(profile_path),
            "--round-manifest", str(manifest_path),
            "--output", str(output_dir),
            "--preflight",
            "--no-verify-sha",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Preflight validation PASSED" in result.output
    assert "Selected Team: 100T" in result.output
    assert "Opponent: LOUD" in result.output


def test_analyze_vod_missing_round_failure(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    manifest_path = root / "configs/examples/ascent-map3-rounds.example.json"
    profile_path = root / "configs/examples/ascent-vct-profile.example.json"
    fake_vod = tmp_path / "vod.mp4"
    fake_vod.write_bytes(b"dummy video")
    output_dir = tmp_path / "run_out"

    # Requesting round 8, which is not in the confirmed 5-round example
    result = runner.invoke(
        app,
        [
            "analyze-vod",
            "--vod", str(fake_vod),
            "--map", "ascent",
            "--match", "vct-americas-grand-final",
            "--map-id", "map3",
            "--from-round", "4",
            "--to-round", "8",
            "--team", "100T",
            "--profile", str(profile_path),
            "--round-manifest", str(manifest_path),
            "--output", str(output_dir),
            "--preflight",
            "--no-verify-sha",
        ],
    )
    assert result.exit_code != 0
    assert "unconfirmed or missing" in result.output


def test_analyze_vod_no_preflight_writes_plan(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    manifest_path = root / "configs/examples/ascent-map3-rounds.example.json"
    profile_path = root / "configs/examples/ascent-vct-profile.example.json"
    fake_vod = tmp_path / "vod.mp4"
    fake_vod.write_bytes(b"dummy video")
    output_dir = tmp_path / "run_out"

    result = runner.invoke(
        app,
        [
            "analyze-vod",
            "--vod", str(fake_vod),
            "--map", "ascent",
            "--match", "vct-americas-grand-final",
            "--map-id", "map3",
            "--from-round", "4",
            "--to-round", "7",
            "--team", "100T",
            "--profile", str(profile_path),
            "--round-manifest", str(manifest_path),
            "--output", str(output_dir),
            "--no-preflight",
            "--no-verify-sha",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Stage 1 foundation complete" in result.output
    plan_file = output_dir / "execution-plan.json"
    assert plan_file.is_file()
    data = json.loads(plan_file.read_text(encoding="utf-8"))
    assert data["match_id"] == "vct-americas-grand-final"
    assert len(data["selected_rounds"]) == 4


def test_analyze_vod_collision_failure(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    manifest_path = root / "configs/examples/ascent-map3-rounds.example.json"
    profile_path = root / "configs/examples/ascent-vct-profile.example.json"
    fake_vod = tmp_path / "vod.mp4"
    fake_vod.write_bytes(b"dummy video")
    output_dir = tmp_path / "run_out"
    output_dir.mkdir()
    (output_dir / "existing_file.txt").write_text("already here")

    result = runner.invoke(
        app,
        [
            "analyze-vod",
            "--vod", str(fake_vod),
            "--map", "ascent",
            "--match", "vct-americas-grand-final",
            "--map-id", "map3",
            "--from-round", "4",
            "--to-round", "7",
            "--team", "100T",
            "--profile", str(profile_path),
            "--round-manifest", str(manifest_path),
            "--output", str(output_dir),
            "--preflight",
            "--no-verify-sha",
        ],
    )
    assert result.exit_code != 0
    assert "Refusing to overwrite" in result.output


def test_analyze_vod_sha_mismatch_failure(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    manifest_path = root / "configs/examples/ascent-map3-rounds.example.json"
    profile_path = root / "configs/examples/ascent-vct-profile.example.json"
    fake_vod = tmp_path / "vod.mp4"
    fake_vod.write_bytes(b"dummy video")
    output_dir = tmp_path / "run_out"

    # Default is --verify-sha
    result = runner.invoke(
        app,
        [
            "analyze-vod",
            "--vod", str(fake_vod),
            "--map", "ascent",
            "--match", "vct-americas-grand-final",
            "--map-id", "map3",
            "--from-round", "4",
            "--to-round", "7",
            "--team", "100T",
            "--profile", str(profile_path),
            "--round-manifest", str(manifest_path),
            "--output", str(output_dir),
            "--preflight",
        ],
    )
    assert result.exit_code != 0
    assert "VOD SHA-256 mismatch" in result.output

