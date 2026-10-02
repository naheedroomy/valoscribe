"""Unit tests for versioned run manifests and atomic persistence."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from valoscribe.types.run_manifest import RunManifest, write_run_manifest

TEST_HASH = "a" * 64


def synthetic_manifest(**overrides: object) -> RunManifest:
    """Create an explicitly incomplete offline test-run manifest."""
    now = datetime.now(timezone.utc)
    values: dict[str, object] = {
        "schema_version": "1.0",
        "status": "incomplete",
        "run_id": "synthetic-test-run",
        "source_vod_identifier": None,
        "source_file_sha256": None,
        "upstream_valoscribe_commit": None,
        "project_commit": None,
        "hud_profile_version": None,
        "map_asset_version": None,
        "zone_config_version": None,
        "detector_versions": {},
        "tracker_versions": {},
        "model_hashes": {},
        "sampling_rates": {"frames_per_second": 4.0},
        "cli_arguments": {"mode": "synthetic-test"},
        "environment_lock_sha256": None,
        "started_at": now,
        "ended_at": now,
        "stage_durations_seconds": {"synthetic_test": 0.0},
    }
    values.update(overrides)
    return RunManifest.model_validate(values)


def complete_synthetic_manifest(**overrides: object) -> RunManifest:
    """Build complete test-only provenance; hashes/versions are synthetic, not real."""
    values: dict[str, object] = {
        "status": "complete",
        "source_vod_identifier": "synthetic://unit-test-vod",
        "source_file_sha256": TEST_HASH,
        "upstream_valoscribe_commit": "synthetic-upstream-commit",
        "project_commit": "synthetic-project-commit",
        "hud_profile_version": "synthetic-hud-v1",
        "map_asset_version": "synthetic-map-v1",
        "zone_config_version": "synthetic-zones-v1",
        "detector_versions": {"synthetic-detector": "test-v1"},
        "tracker_versions": {"synthetic-tracker": "test-v1"},
        "environment_lock_sha256": TEST_HASH,
    }
    values.update(overrides)
    return synthetic_manifest(**values)


def test_synthetic_offline_run_emits_manifest(tmp_path: Path) -> None:
    manifest = synthetic_manifest()

    manifest_path = write_run_manifest(manifest, tmp_path / "runs")
    serialized = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest_path == tmp_path / "runs" / "synthetic-test-run" / "manifest.json"
    assert serialized["schema_version"] == "1.0"
    assert serialized["status"] == "incomplete"
    assert serialized["run_id"] == "synthetic-test-run"
    assert serialized["source_file_sha256"] is None
    assert serialized["environment_lock_sha256"] is None
    assert serialized["cli_arguments"] == {"mode": "synthetic-test"}


def test_complete_manifest_requires_provenance() -> None:
    with pytest.raises(ValidationError, match="complete manifest requires provenance"):
        synthetic_manifest(status="complete")


def test_complete_synthetic_manifest_accepts_explicit_test_provenance() -> None:
    manifest = complete_synthetic_manifest()

    assert manifest.status == "complete"
    assert manifest.source_vod_identifier == "synthetic://unit-test-vod"


def test_complete_manifest_rejects_empty_sampling_or_version_metadata() -> None:
    with pytest.raises(ValidationError, match="sampling_rates"):
        complete_synthetic_manifest(sampling_rates={})
    with pytest.raises(ValidationError, match="detector_versions"):
        complete_synthetic_manifest(detector_versions={"synthetic-detector": ""})


def test_manifest_requires_all_contract_keys() -> None:
    with pytest.raises(ValidationError):
        RunManifest.model_validate({"schema_version": "1.0", "run_id": "incomplete"})


def test_manifest_rejects_invalid_hash_and_path_run_id() -> None:
    data = synthetic_manifest().model_dump(mode="python")
    data["source_file_sha256"] = "not-a-hash"
    with pytest.raises(ValidationError):
        RunManifest.model_validate(data)

    data = synthetic_manifest().model_dump(mode="python")
    data["run_id"] = "../escape"
    with pytest.raises(ValidationError):
        RunManifest.model_validate(data)


@pytest.mark.parametrize("rate", [0.0, -1.0, float("nan"), float("inf")])
def test_manifest_rejects_invalid_sampling_rates(rate: float) -> None:
    with pytest.raises(ValidationError):
        synthetic_manifest(sampling_rates={"fps": rate})


@pytest.mark.parametrize("duration", [-1.0, float("nan"), float("inf")])
def test_manifest_rejects_invalid_stage_durations(duration: float) -> None:
    with pytest.raises(ValidationError):
        synthetic_manifest(stage_durations_seconds={"decode": duration})


def test_manifest_rejects_end_before_start() -> None:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end = datetime(2024, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(ValidationError, match="ended_at must not precede started_at"):
        synthetic_manifest(started_at=start, ended_at=end)


def test_manifest_is_immutable() -> None:
    manifest = synthetic_manifest()
    with pytest.raises(ValidationError):
        manifest.run_id = "changed"  # type: ignore[misc]


def test_atomic_create_does_not_overwrite_existing_manifest_or_leave_temp(
    tmp_path: Path,
) -> None:
    manifest = synthetic_manifest()
    run_dir = tmp_path / "runs" / manifest.run_id
    run_dir.mkdir(parents=True)
    destination = run_dir / "manifest.json"
    destination.write_text('{"previous": true}\n', encoding="utf-8")

    with pytest.raises(FileExistsError):
        write_run_manifest(manifest, tmp_path / "runs")

    assert destination.read_text(encoding="utf-8") == '{"previous": true}\n'
    assert list(run_dir.glob(".manifest.json.*.tmp")) == []


def test_run_directory_symlink_is_rejected(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    target = tmp_path / "outside"
    target.mkdir()
    (runs_root / "synthetic-test-run").symlink_to(target, target_is_directory=True)

    with pytest.raises(ValueError, match="run directory must not be a symlink"):
        write_run_manifest(synthetic_manifest(), runs_root)

    assert list(target.iterdir()) == []


def test_runs_root_symlink_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "outside"
    target.mkdir()
    root_link = tmp_path / "runs-link"
    root_link.symlink_to(target, target_is_directory=True)

    with pytest.raises(ValueError, match="runs root must not be a symlink"):
        write_run_manifest(synthetic_manifest(), root_link)

    assert list(target.iterdir()) == []


def test_serialization_failure_leaves_no_partial_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_dump(*_args: object, **_kwargs: object) -> None:
        raise TypeError("simulated serialization failure")

    monkeypatch.setattr("valoscribe.types.run_manifest.json.dump", fail_dump)
    run_dir = tmp_path / "runs" / "synthetic-test-run"
    with pytest.raises(TypeError, match="simulated serialization failure"):
        write_run_manifest(synthetic_manifest(), tmp_path / "runs")

    assert not (run_dir / "manifest.json").exists()
    assert list(run_dir.glob(".manifest.json.*.tmp")) == []
