from __future__ import annotations

import hashlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import numpy as np
import pytest

from valoscribe.tracking.artifacts import (
    ParquetUnavailableError,
    read_player_tracks_parquet,
    write_player_tracks_parquet,
)
from valoscribe.tracking.run_export import export_player_track_run, read_player_track_run
from valoscribe.types.persistent import (
    NormalizedPoint,
    PlayerTrackEstimate,
    Side,
    SmoothedTrackSample,
    TrackSmoothingInput,
)
from valoscribe.types.run_manifest import RunManifest

_SOURCE_HASH = "a" * 64


def _manifest(*, status: Literal["incomplete", "complete"] = "complete") -> RunManifest:
    now = datetime.now(timezone.utc)
    return RunManifest(
        schema_version="1.0",
        status=status,
        run_id="test-run",
        source_vod_identifier="source-vod",
        source_file_sha256=_SOURCE_HASH,
        upstream_valoscribe_commit="upstream-sha",
        project_commit="project-sha",
        hud_profile_version="hud-v1",
        map_asset_version="map-v1",
        zone_config_version="zones-v1",
        detector_versions={"detector": "1"},
        tracker_versions={"tracker": "1"},
        model_hashes={},
        sampling_rates={"fps": 1.0},
        cli_arguments={},
        environment_lock_sha256="b" * 64,
        started_at=now,
        ended_at=now,
        stage_durations_seconds={},
    )


def _inputs(
    round_id: str = "r1",
) -> tuple[list[TrackSmoothingInput], tuple[SmoothedTrackSample, ...]]:
    estimate = PlayerTrackEstimate(
        player_id="player-1",
        vod_timestamp_s=2.0,
        source_frame=60,
        position=NormalizedPoint(x=0.25, y=0.5),
        observed=True,
        predicted=False,
        confidence=0.9,
        evidence=["assignment:known_roster_player"],
    )
    raw = TrackSmoothingInput(
        estimate=estimate,
        round_id=round_id,
        alive=True,
        interval_state="live",
        context_evidence=["round_state:live"],
    )
    return [raw], (
        SmoothedTrackSample(
            raw_estimate=estimate,
            position=estimate.position,
            observed=True,
            confidence=0.9,
            evidence=["smoothing:observed"],
        ),
    )


def _export(root: Path, **overrides: object):
    inputs, outputs = _inputs()
    args: dict[str, object] = {
        "runs_root": root,
        "manifest": _manifest(),
        "expected_source_file_sha256": _SOURCE_HASH,
        "match_id": "match-1",
        "map_id": "ascent",
        "round_id": "r1",
        "inputs": inputs,
        "outputs": outputs,
        "agent_by_player": {"player-1": "omen"},
        "team_by_player": {"player-1": "team-1"},
        "side_by_player": {"player-1": Side.ATTACK},
        "map_image": np.zeros((64, 64, 3), dtype=np.uint8),
    }
    args.update(overrides)
    return export_player_track_run(**args)  # type: ignore[arg-type]


@pytest.mark.skipif(
    importlib.util.find_spec("pyarrow") is None, reason="optional PyArrow extra required"
)
def test_export_readback_pins_parquet_manifest_and_stable_id_playback(tmp_path: Path) -> None:
    run = _export(tmp_path)
    manifest_bytes = (run.directory / "manifest.json").read_bytes()
    expected_hash = hashlib.sha256(manifest_bytes).hexdigest()

    binding_bytes = (run.directory / "player_tracks.binding.json").read_bytes()
    manifest, binding, rows = read_player_track_run(
        tmp_path,
        run_id="test-run",
        expected_manifest_sha256=expected_hash,
        expected_binding_sha256=hashlib.sha256(binding_bytes).hexdigest(),
    )

    assert manifest.status == "complete"
    assert binding == run.binding
    assert rows[0].player_id == "player-1"
    assert rows[0].round_id == "r1"
    assert (run.directory / "player_tracks.parquet").read_bytes()[:4] == b"PAR1"
    frames = sorted((run.directory / "debug_playback").glob("*.png"))
    assert [frame.name for frame in frames] == ["frame_000000_00000002.000.png"]
    import cv2

    image = cv2.imread(str(frames[0]))
    assert image is not None and np.any(image != 0)


def test_export_rejects_empty_unknown_missing_roster_and_mixed_round_before_output(
    tmp_path: Path,
) -> None:
    inputs, outputs = _inputs()
    with pytest.raises(ValueError, match="non-empty"):
        _export(tmp_path, inputs=[], outputs=())
    unknown_inputs = [
        inputs[0].model_copy(
            update={"estimate": inputs[0].estimate.model_copy(update={"player_id": "anon-track-1"})}
        )
    ]
    with pytest.raises(ValueError, match="anonymous or unknown"):
        _export(tmp_path, inputs=unknown_inputs)
    with pytest.raises(ValueError, match="not in the explicit roster"):
        _export(
            tmp_path,
            agent_by_player={"someone-else": "omen"},
            team_by_player={"someone-else": "team-1"},
            side_by_player={"someone-else": Side.ATTACK},
        )
    with pytest.raises(ValueError, match="explicitly requested round"):
        _export(tmp_path, inputs=_inputs("r2")[0])
    assert not (tmp_path / "test-run").exists()


def test_export_rejects_incomplete_provenance_and_source_mismatch(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="requires a complete RunManifest"):
        _export(tmp_path, manifest=_manifest(status="incomplete"))
    with pytest.raises(ValueError, match="source hash"):
        _export(tmp_path, expected_source_file_sha256="c" * 64)
    assert not (tmp_path / "test-run").exists()


@pytest.mark.skipif(
    importlib.util.find_spec("pyarrow") is None, reason="optional PyArrow extra required"
)
def test_export_cleans_invocation_owned_files_after_playback_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import valoscribe.tracking.run_export as run_export

    def fail_playback(directory: Path, *args, **kwargs):
        (directory / "foreign.marker").write_bytes(b"keep")
        raise OSError("playback failed")

    monkeypatch.setattr(run_export, "write_track_debug_playback", fail_playback)
    with pytest.raises(OSError, match="playback failed"):
        _export(tmp_path)
    run_directory = tmp_path / "test-run"
    assert (run_directory / "debug_playback" / "foreign.marker").read_bytes() == b"keep"
    assert not (run_directory / "player_tracks.parquet").exists()
    assert not (run_directory / "manifest.json").exists()


@pytest.mark.skipif(
    importlib.util.find_spec("pyarrow") is None, reason="optional PyArrow extra required"
)
def test_readback_rejects_coherent_binding_and_parquet_replacement(tmp_path: Path) -> None:
    run = _export(tmp_path)
    manifest_bytes = (run.directory / "manifest.json").read_bytes()
    binding_path = run.directory / "player_tracks.binding.json"
    expected_manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    expected_binding_sha256 = hashlib.sha256(binding_path.read_bytes()).hexdigest()
    parquet_path = run.parquet_path
    rows = read_player_tracks_parquet(parquet_path)
    rows[0] = rows[0].model_copy(update={"x": 0.9})
    write_player_tracks_parquet(parquet_path, rows)
    binding = json.loads(binding_path.read_text())
    binding["parquet_sha256"] = hashlib.sha256(parquet_path.read_bytes()).hexdigest()
    binding_path.write_text(json.dumps(binding, indent=2) + "\n")

    with pytest.raises(ValueError, match="binding.*hash|independently expected"):
        read_player_track_run(
            tmp_path,
            run_id="test-run",
            expected_manifest_sha256=expected_manifest_sha256,
            expected_binding_sha256=expected_binding_sha256,
        )


@pytest.mark.skipif(
    importlib.util.find_spec("pyarrow") is None, reason="optional PyArrow extra required"
)
def test_readback_decodes_verified_parquet_payload_if_path_is_replaced(
    tmp_path: Path, monkeypatch
) -> None:
    import pyarrow.parquet as parquet

    run = _export(tmp_path)
    binding_path = run.directory / "player_tracks.binding.json"
    manifest_hash = hashlib.sha256((run.directory / "manifest.json").read_bytes()).hexdigest()
    binding_hash = hashlib.sha256(binding_path.read_bytes()).hexdigest()
    original_read_table = parquet.read_table
    replaced = False

    def replace_path_after_payload_read(source, *args, **kwargs):
        nonlocal replaced
        if not replaced:
            replaced = True
            run.parquet_path.write_bytes(b"replacement after payload read")
        return original_read_table(source, *args, **kwargs)

    monkeypatch.setattr(parquet, "read_table", replace_path_after_payload_read)
    _, _, rows = read_player_track_run(
        tmp_path,
        run_id="test-run",
        expected_manifest_sha256=manifest_hash,
        expected_binding_sha256=binding_hash,
    )
    assert replaced
    assert rows[0].x == pytest.approx(0.25)


@pytest.mark.skipif(
    importlib.util.find_spec("pyarrow") is None, reason="optional PyArrow extra required"
)
def test_readback_rejects_incomplete_manifest_and_invalid_requested_run_ids(tmp_path: Path) -> None:
    run = _export(tmp_path)
    manifest_path = run.directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["status"] = "incomplete"
    manifest_path.write_text(json.dumps(manifest))
    binding_bytes = (run.directory / "player_tracks.binding.json").read_bytes()
    with pytest.raises(ValueError, match="complete"):
        read_player_track_run(
            tmp_path,
            run_id="test-run",
            expected_manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            expected_binding_sha256=hashlib.sha256(binding_bytes).hexdigest(),
        )
    for invalid in ("../test-run", "/tmp/test-run", "a/b"):
        with pytest.raises(ValueError, match="safe path component"):
            read_player_track_run(
                tmp_path,
                run_id=invalid,
                expected_manifest_sha256="0" * 64,
                expected_binding_sha256="0" * 64,
            )


@pytest.mark.skipif(
    importlib.util.find_spec("pyarrow") is None, reason="optional PyArrow extra required"
)
def test_readback_rejects_tampering_and_wrong_independent_manifest_pin(tmp_path: Path) -> None:
    run = _export(tmp_path)
    manifest_bytes = (run.directory / "manifest.json").read_bytes()
    expected_hash = hashlib.sha256(manifest_bytes).hexdigest()
    with pytest.raises(ValueError, match="independently expected hash"):
        read_player_track_run(
            tmp_path,
            run_id="test-run",
            expected_manifest_sha256="0" * 64,
            expected_binding_sha256="0" * 64,
        )
    parquet = run.directory / "player_tracks.parquet"
    parquet.write_bytes(parquet.read_bytes() + b"tampered")
    binding_bytes = (run.directory / "player_tracks.binding.json").read_bytes()
    with pytest.raises(ValueError, match="digest"):
        read_player_track_run(
            tmp_path,
            run_id="test-run",
            expected_manifest_sha256=expected_hash,
            expected_binding_sha256=hashlib.sha256(binding_bytes).hexdigest(),
        )


@pytest.mark.skipif(
    importlib.util.find_spec("pyarrow") is None, reason="optional PyArrow extra required"
)
def test_export_rejects_symlinked_runs_root(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="symlinks"):
        _export(linked)
    assert list(target.iterdir()) == []


@pytest.mark.skipif(
    importlib.util.find_spec("pyarrow") is None, reason="optional PyArrow extra required"
)
def test_export_refuses_repeated_destination_without_changing_first_run(tmp_path: Path) -> None:
    first = _export(tmp_path)
    original = first.parquet_path.read_bytes()
    with pytest.raises(FileExistsError, match="already exists"):
        _export(tmp_path)
    assert first.parquet_path.read_bytes() == original


def test_export_rejects_duplicate_player_timestamp_rows(tmp_path: Path) -> None:
    inputs, outputs = _inputs()
    with pytest.raises(ValueError, match="duplicate player/timestamp"):
        _export(tmp_path, inputs=inputs * 2, outputs=outputs * 2)
    assert not (tmp_path / "test-run").exists()


@pytest.mark.skipif(
    importlib.util.find_spec("pyarrow") is None, reason="optional PyArrow extra required"
)
def test_readback_rejects_raw_json_that_disagrees_with_row_identity(tmp_path: Path) -> None:
    run = _export(tmp_path)
    rows = read_player_tracks_parquet(run.parquet_path)
    raw = json.loads(rows[0].raw_estimate_json)
    raw["player_id"] = "different-player"
    rows[0] = rows[0].model_copy(update={"raw_estimate_json": json.dumps(raw)})
    write_player_tracks_parquet(run.parquet_path, rows)
    binding_path = run.directory / "player_tracks.binding.json"
    binding = json.loads(binding_path.read_text())
    binding["parquet_sha256"] = hashlib.sha256(run.parquet_path.read_bytes()).hexdigest()
    binding_path.write_text(json.dumps(binding) + "\n")
    with pytest.raises(ValueError, match="raw estimate.*row"):
        read_player_track_run(
            tmp_path,
            run_id="test-run",
            expected_manifest_sha256=hashlib.sha256(
                (run.directory / "manifest.json").read_bytes()
            ).hexdigest(),
            expected_binding_sha256=hashlib.sha256(binding_path.read_bytes()).hexdigest(),
        )


@pytest.mark.skipif(
    importlib.util.find_spec("pyarrow") is None, reason="optional PyArrow extra required"
)
def test_readback_rejects_duplicate_player_timestamp_rows(tmp_path: Path) -> None:
    run = _export(tmp_path)
    rows = read_player_tracks_parquet(run.parquet_path)
    write_player_tracks_parquet(run.parquet_path, rows * 2)
    binding_path = run.directory / "player_tracks.binding.json"
    binding = json.loads(binding_path.read_text())
    binding["parquet_sha256"] = hashlib.sha256(run.parquet_path.read_bytes()).hexdigest()
    binding_path.write_text(json.dumps(binding) + "\n")
    with pytest.raises(ValueError, match="duplicate player/timestamp"):
        read_player_track_run(
            tmp_path,
            run_id="test-run",
            expected_manifest_sha256=hashlib.sha256(
                (run.directory / "manifest.json").read_bytes()
            ).hexdigest(),
            expected_binding_sha256=hashlib.sha256(binding_path.read_bytes()).hexdigest(),
        )


@pytest.mark.skipif(
    importlib.util.find_spec("pyarrow") is None, reason="optional PyArrow extra required"
)
def test_export_does_not_clean_competing_run_directory(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "test-run"
    original_mkdir = Path.mkdir
    competing_files = {
        Path("player_tracks.parquet"): b"winner parquet",
        Path("player_tracks.binding.json"): b"winner binding",
        Path("debug_playback/frame_000000_00000002.000.png"): b"winner playback",
    }

    def competing_mkdir(path: Path, *args, **kwargs):
        if path == run_dir:
            original_mkdir(path)
            for relative_path, contents in competing_files.items():
                target = path / relative_path
                original_mkdir(target.parent, parents=True, exist_ok=True)
                target.write_bytes(contents)
            raise FileExistsError(path)
        return original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", competing_mkdir)
    with pytest.raises(FileExistsError):
        _export(tmp_path)
    for relative_path, contents in competing_files.items():
        assert (run_dir / relative_path).read_bytes() == contents


def test_pure_input_validation_does_not_require_pyarrow(tmp_path: Path, monkeypatch) -> None:
    import valoscribe.tracking.run_export as run_export

    def unavailable():
        raise ParquetUnavailableError("optional pyarrow missing")

    monkeypatch.setattr(run_export, "_load_arrow", unavailable)
    with pytest.raises(ValueError, match="non-empty"):
        _export(tmp_path, inputs=[], outputs=())
    assert list(tmp_path.iterdir()) == []


def test_pyarrow_missing_fails_before_creating_run_outputs(tmp_path: Path, monkeypatch) -> None:
    import valoscribe.tracking.run_export as run_export

    def unavailable():
        raise ParquetUnavailableError("optional pyarrow missing")

    monkeypatch.setattr(run_export, "_load_arrow", unavailable)
    with pytest.raises(ParquetUnavailableError, match="pyarrow"):
        _export(tmp_path)
    assert list(tmp_path.iterdir()) == []
