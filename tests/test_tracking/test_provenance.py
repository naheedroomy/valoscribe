from __future__ import annotations

import hashlib
import json
from collections.abc import MutableMapping
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

import valoscribe.tracking.provenance as provenance
from valoscribe.tracking.provenance import (
    local_content_tree_sha256,
    local_file_sha256,
    manifest_sha256,
    read_bound_artifact,
    read_tracking_manifest,
    validate_observation,
    write_bound_artifact,
    write_observation_jsonl,
    write_tracking_manifest,
)
from valoscribe.types.tracking_provenance import (
    ConfigFileProvenance,
    TrackingObservationProvenance,
    TrackingRunManifest,
    canonical_config_sha256,
)


def _config(config_id: str = "same-config", digest: str = "a" * 64) -> ConfigFileProvenance:
    return ConfigFileProvenance(config_id=config_id, filename="same.json", file_sha256=digest)


def _manifest(run_id: str = "local-run", *, config_digest: str = "a" * 64) -> TrackingRunManifest:
    hud = _config("hud", config_digest)
    color = _config("color", config_digest)
    map_config = _config("map", config_digest)
    return TrackingRunManifest(
        run_id=run_id,
        source_path="synthetic-local-source.mp4",
        source_video_sha256="b" * 64,
        source_width=1920,
        source_height=1080,
        fps_numerator=60,
        fps_denominator=1,
        timebase_numerator=1,
        timebase_denominator=15360,
        map_id="ascent",
        map_number=1,
        round_number=2,
        start_frame_index=100,
        end_frame_index=200,
        start_source_pts=25600,
        end_source_pts=51200,
        start_timestamp_s=25600 / 15360,
        end_timestamp_s=51200 / 15360,
        hud_config=hud,
        color_config=color,
        map_config=map_config,
        config_sha256=canonical_config_sha256(hud, color, map_config),
        map_asset_sha256="c" * 64,
        map_asset_version="synthetic-map-v1",
        project_commit="synthetic-project-commit",
        upstream_commit="synthetic-upstream-commit",
        code_fingerprint_sha256="d" * 64,
        detector_version="synthetic-detector-v1",
        tracker_version="synthetic-tracker-v1",
        annotation_version=None,
        started_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )


def _observation(
    manifest: TrackingRunManifest, **overrides: object
) -> TrackingObservationProvenance:
    values: dict[str, object] = {
        "run_id": manifest.run_id,
        "manifest_sha256": manifest_sha256(manifest),
        "source_video_sha256": manifest.source_video_sha256,
        "config_sha256": manifest.config_sha256,
        "map_id": manifest.map_id,
        "map_number": manifest.map_number,
        "round_number": manifest.round_number,
        "frame_index": 120,
        "source_pts": 30000,
        "timebase_numerator": manifest.timebase_numerator,
        "timebase_denominator": manifest.timebase_denominator,
        "timestamp_s": 30000 / 15360,
    }
    values.update(overrides)
    return TrackingObservationProvenance.model_validate(values)


def _validate(obs: TrackingObservationProvenance, manifest: TrackingRunManifest) -> None:
    validate_observation(
        obs,
        manifest,
        expected_run_id=manifest.run_id,
        expected_source_sha256=manifest.source_video_sha256,
        expected_config_sha256=manifest.config_sha256,
    )


def test_config_hashes_bind_contents_not_reused_filename(tmp_path: Path) -> None:
    left = tmp_path / "left" / "same.json"
    right = tmp_path / "right" / "same.json"
    left.parent.mkdir()
    right.parent.mkdir()
    left.write_bytes(b'{"threshold": 1}')
    right.write_bytes(b'{"threshold": 2}')
    left_hash, right_hash = local_file_sha256(left), local_file_sha256(right)
    assert left.name == right.name
    assert left_hash != right_hash
    assert canonical_config_sha256(
        ConfigFileProvenance(config_id="same", filename=left.name, file_sha256=left_hash),
        _config("color"),
        _config("map"),
    ) != canonical_config_sha256(
        ConfigFileProvenance(config_id="same", filename=right.name, file_sha256=right_hash),
        _config("color"),
        _config("map"),
    )


def test_dirty_code_content_fingerprint_tracks_actual_bytes(tmp_path: Path) -> None:
    source = tmp_path / "src" / "tracker.py"
    source.parent.mkdir()
    source.write_text("candidate-ID-v1", encoding="utf-8")
    first = local_content_tree_sha256(tmp_path, ["src/tracker.py"])
    source.write_text("candidate-ID-v2", encoding="utf-8")
    assert local_content_tree_sha256(tmp_path, ["src/tracker.py"]) != first
    with pytest.raises(ValueError, match="safe relative"):
        local_content_tree_sha256(tmp_path, ["../outside.py"])


def test_distinct_local_sources_have_distinct_content_hashes(tmp_path: Path) -> None:
    first, second = tmp_path / "first.mp4", tmp_path / "second.mp4"
    first.write_bytes(b"synthetic local video one")
    second.write_bytes(b"synthetic local video two")
    assert local_file_sha256(first) != local_file_sha256(second)


def test_local_file_hash_rejects_symlinks(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_bytes(b"local fixture")
    link = tmp_path / "link"
    link.symlink_to(target)
    assert local_file_sha256(target) == hashlib.sha256(b"local fixture").hexdigest()
    with pytest.raises(ValueError, match="symlinks"):
        local_file_sha256(link)


def test_observation_binds_exact_manifest_source_config_map_round_and_timebase() -> None:
    manifest = _manifest()
    obs = _observation(manifest)
    _validate(obs, manifest)
    for changed in (
        {"manifest_sha256": "e" * 64},
        {"source_video_sha256": "e" * 64},
        {"config_sha256": "e" * 64},
        {"map_number": 3},
        {"round_number": 3},
        {"frame_index": 201},
        {"source_pts": 51201, "timestamp_s": 51201 / 15360},
        {"timestamp_s": 1.0},
    ):
        with pytest.raises(ValueError):
            _validate(_observation(manifest, **changed), manifest)


def test_run_binding_rejects_incomplete_and_inconsistent_contracts() -> None:
    manifest = _manifest()
    with pytest.raises(ValidationError):
        TrackingRunManifest.model_validate({"run_id": "incomplete"})
    missing_map_number = manifest.model_dump(mode="python")
    del missing_map_number["map_number"]
    with pytest.raises(ValidationError):
        TrackingRunManifest.model_validate(missing_map_number)
    with pytest.raises(ValidationError):
        TrackingRunManifest.model_validate(
            {**manifest.model_dump(mode="python"), "map_number": 0}
        )
    observation = _observation(manifest).model_dump(mode="python")
    missing_observation_map = dict(observation)
    del missing_observation_map["map_number"]
    with pytest.raises(ValidationError):
        TrackingObservationProvenance.model_validate(missing_observation_map)
    with pytest.raises(ValidationError):
        TrackingObservationProvenance.model_validate(
            {**observation, "map_number": 0}
        )
    with pytest.raises(ValidationError, match="start timestamp"):
        TrackingRunManifest.model_validate(
            {**manifest.model_dump(mode="python"), "start_timestamp_s": 1.0}
        )
    with pytest.raises(ValidationError, match="config_sha256"):
        TrackingRunManifest.model_validate(
            {**manifest.model_dump(mode="python"), "config_sha256": "e" * 64}
        )


def test_revalidation_catches_model_copy_and_mutable_nested_dict_tampering() -> None:
    manifest = _manifest()
    copied = manifest.model_copy(update={"source_video_sha256": "e" * 64})
    with pytest.raises(ValueError, match="does not match"):
        _validate(_observation(manifest), copied)
    # Frozen Pydantic models do not freeze nested dictionaries in general; revalidation
    # must still detect a modified configuration object before any boundary operation.
    cast(MutableMapping[str, object], manifest.hud_config.__dict__)[
        "file_sha256"
    ] = "e" * 64
    with pytest.raises(ValueError, match="invalid tracking run manifest"):
        manifest_sha256(manifest)


def test_manifest_write_is_immutable_and_reader_checks_binding(tmp_path: Path) -> None:
    manifest = _manifest()
    output = write_tracking_manifest(manifest, tmp_path / "runs")
    assert read_tracking_manifest(
        output,
        expected_run_id=manifest.run_id,
        expected_source_sha256=manifest.source_video_sha256,
        expected_config_sha256=manifest.config_sha256,
    ) == manifest
    with pytest.raises(FileExistsError):
        write_tracking_manifest(manifest, tmp_path / "runs")
    with pytest.raises(ValueError, match="expected run/source/config"):
        read_tracking_manifest(
            output,
            expected_run_id=manifest.run_id,
            expected_source_sha256="e" * 64,
            expected_config_sha256=manifest.config_sha256,
        )
    output.write_bytes(output.read_bytes().replace(b"synthetic-map-v1", b"tampered-map-v1"))
    with pytest.raises(ValueError, match="persisted run manifest digest mismatch"):
        read_bound_artifact(
            tmp_path / "runs", manifest, "not-present.bin", expected_run_id=manifest.run_id,
            expected_source_sha256=manifest.source_video_sha256,
            expected_config_sha256=manifest.config_sha256, expected_artifact_kind="visualization",
        )


def test_manifest_and_artifact_symlinks_and_traversal_are_rejected(tmp_path: Path) -> None:
    manifest = _manifest()
    runs = tmp_path / "runs"
    outside = tmp_path / "outside"
    outside.mkdir()
    runs.mkdir()
    (runs / manifest.run_id).symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="run directory"):
        write_tracking_manifest(manifest, runs)
    (runs / manifest.run_id).unlink()
    write_tracking_manifest(manifest, runs)
    with pytest.raises(ValueError, match="safe relative"):
        write_bound_artifact(
            runs, manifest, "../escape.bin", b"x", artifact_kind="video",
            expected_run_id=manifest.run_id, expected_source_sha256=manifest.source_video_sha256,
            expected_config_sha256=manifest.config_sha256,
        )
    (runs / manifest.run_id / "linked-dir").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlinks"):
        write_bound_artifact(
            runs, manifest, "linked-dir/escape.bin", b"x", artifact_kind="video",
            expected_run_id=manifest.run_id, expected_source_sha256=manifest.source_video_sha256,
            expected_config_sha256=manifest.config_sha256,
        )
    assert list(outside.iterdir()) == []
    assert list((runs / manifest.run_id).glob("*.bin")) == []


def test_symlinked_ancestors_are_rejected_at_manifest_artifact_and_jsonl_boundaries(
    tmp_path: Path,
) -> None:
    base = tmp_path.resolve()
    outside = base / "outside"
    outside.mkdir()
    linked_parent = base / "linked-parent"
    linked_parent.symlink_to(outside, target_is_directory=True)
    manifest = _manifest()

    with pytest.raises(ValueError, match="symlinks"):
        write_tracking_manifest(manifest, linked_parent / "runs")
    assert list(outside.iterdir()) == []

    with pytest.raises(ValueError, match="symlinks"):
        read_tracking_manifest(
            linked_parent / "manifest.json", expected_run_id=manifest.run_id,
            expected_source_sha256=manifest.source_video_sha256,
            expected_config_sha256=manifest.config_sha256,
        )
    with pytest.raises(ValueError, match="symlinks"):
        write_observation_jsonl(
            linked_parent / "observations.jsonl", [], manifest,
            expected_run_id=manifest.run_id,
            expected_source_sha256=manifest.source_video_sha256,
            expected_config_sha256=manifest.config_sha256,
        )
    assert list(outside.iterdir()) == []


def test_artifact_reader_and_writer_reject_symlinked_runs_ancestor(tmp_path: Path) -> None:
    base = tmp_path.resolve()
    outside = base / "outside"
    outside.mkdir()
    linked_parent = base / "linked-parent"
    linked_parent.symlink_to(outside, target_is_directory=True)
    manifest = _manifest()
    runs = linked_parent / "runs"
    with pytest.raises(ValueError, match="symlinks"):
        write_bound_artifact(
            runs, manifest, "payload.bin", b"payload", artifact_kind="test",
            expected_run_id=manifest.run_id,
            expected_source_sha256=manifest.source_video_sha256,
            expected_config_sha256=manifest.config_sha256,
        )
    with pytest.raises(ValueError, match="symlinks"):
        read_bound_artifact(
            runs, manifest, "payload.bin", expected_run_id=manifest.run_id,
            expected_source_sha256=manifest.source_video_sha256,
            expected_config_sha256=manifest.config_sha256, expected_artifact_kind="test",
        )
    assert list(outside.iterdir()) == []


def test_local_hashes_reject_symlinked_ancestors_and_content_directories(tmp_path: Path) -> None:
    base = tmp_path.resolve()
    outside = base / "outside"
    outside.mkdir()
    target = outside / "code.py"
    target.write_text("synthetic code", encoding="utf-8")
    linked_parent = base / "linked-parent"
    linked_parent.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlinks"):
        local_file_sha256(linked_parent / "code.py")
    with pytest.raises(ValueError, match="symlinks"):
        local_content_tree_sha256(linked_parent, ["code.py"])

    root = base / "tree"
    root.mkdir()
    (root / "linked-dir").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlinks"):
        local_content_tree_sha256(root, ["linked-dir/code.py"])


@pytest.mark.parametrize("sidecar_kind", ["symlink", "existing"])
def test_bound_artifact_preflights_sidecar_before_payload_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sidecar_kind: str
) -> None:
    manifest = _manifest()
    runs = tmp_path / "runs"
    write_tracking_manifest(manifest, runs)
    target = runs / manifest.run_id / "artifact.bin"
    sidecar = target.with_name(target.name + ".provenance.json")
    outside = tmp_path / "outside-sidecar.json"
    if sidecar_kind == "symlink":
        outside.write_text("untouched", encoding="utf-8")
        sidecar.symlink_to(outside)
    else:
        sidecar.write_text("existing sidecar", encoding="utf-8")

    attempted_creations: list[Path] = []
    atomic_create = provenance._atomic_create

    def record_creation(destination: Path, payload: bytes) -> None:
        attempted_creations.append(destination)
        atomic_create(destination, payload)

    monkeypatch.setattr(provenance, "_atomic_create", record_creation)
    error = ValueError if sidecar_kind == "symlink" else FileExistsError
    with pytest.raises(error):
        write_bound_artifact(
            runs, manifest, "artifact.bin", b"payload", artifact_kind="test",
            expected_run_id=manifest.run_id,
            expected_source_sha256=manifest.source_video_sha256,
            expected_config_sha256=manifest.config_sha256,
        )

    assert attempted_creations == []
    assert not target.exists()
    if sidecar_kind == "symlink":
        assert sidecar.is_symlink()
        assert outside.read_text(encoding="utf-8") == "untouched"
    else:
        assert sidecar.read_text(encoding="utf-8") == "existing sidecar"


def test_bound_artifact_checks_payload_manifest_kind_and_cross_run_reuse(tmp_path: Path) -> None:
    manifest = _manifest()
    runs = tmp_path / "runs"
    write_tracking_manifest(manifest, runs)
    write_bound_artifact(
        runs, manifest, "visualization.bin", b"artifact-bytes", artifact_kind="visualization",
        expected_run_id=manifest.run_id, expected_source_sha256=manifest.source_video_sha256,
        expected_config_sha256=manifest.config_sha256,
    )
    assert read_bound_artifact(
        runs, manifest, "visualization.bin", expected_run_id=manifest.run_id,
        expected_source_sha256=manifest.source_video_sha256,
        expected_config_sha256=manifest.config_sha256, expected_artifact_kind="visualization",
    ) == b"artifact-bytes"
    with pytest.raises(ValueError, match="mismatch"):
        read_bound_artifact(
            runs, manifest, "visualization.bin", expected_run_id=manifest.run_id,
            expected_source_sha256=manifest.source_video_sha256,
            expected_config_sha256=manifest.config_sha256, expected_artifact_kind="parquet",
        )
    other = _manifest("other-run")
    with pytest.raises(ValueError, match="missing or invalid persisted run manifest"):
        read_bound_artifact(
            runs, other, "visualization.bin", expected_run_id=other.run_id,
            expected_source_sha256=other.source_video_sha256,
            expected_config_sha256=other.config_sha256, expected_artifact_kind="visualization",
        )
    artifact_path = runs / manifest.run_id / "visualization.bin"
    artifact_path.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="mismatch"):
        read_bound_artifact(
            runs, manifest, "visualization.bin", expected_run_id=manifest.run_id,
            expected_source_sha256=manifest.source_video_sha256,
            expected_config_sha256=manifest.config_sha256, expected_artifact_kind="visualization",
        )


def test_empty_jsonl_still_validates_manifest_and_expected_binding(tmp_path: Path) -> None:
    manifest = _manifest()
    for overrides in (
        {"expected_run_id": "foreign-run"},
        {"expected_source_sha256": "e" * 64},
        {"expected_config_sha256": "e" * 64},
    ):
        output = tmp_path / f"empty-{len(list(tmp_path.iterdir()))}.jsonl"
        with pytest.raises(ValueError, match="expected run/source/config"):
            write_observation_jsonl(
                output, [], manifest,
                expected_run_id=overrides.get("expected_run_id", manifest.run_id),
                expected_source_sha256=overrides.get(
                    "expected_source_sha256", manifest.source_video_sha256
                ),
                expected_config_sha256=overrides.get(
                    "expected_config_sha256", manifest.config_sha256
                ),
            )
        assert not output.exists()

    invalid = manifest.model_copy(update={"source_video_sha256": "invalid"})
    output = tmp_path / "empty-invalid-manifest.jsonl"
    with pytest.raises(ValueError, match="invalid tracking run manifest"):
        write_observation_jsonl(
            output, [], invalid, expected_run_id=manifest.run_id,
            expected_source_sha256=manifest.source_video_sha256,
            expected_config_sha256=manifest.config_sha256,
        )
    assert not output.exists()


def test_empty_jsonl_is_valid_and_creates_empty_file(tmp_path: Path) -> None:
    manifest = _manifest()
    output = tmp_path / "empty.jsonl"
    write_observation_jsonl(
        output, [], manifest, expected_run_id=manifest.run_id,
        expected_source_sha256=manifest.source_video_sha256,
        expected_config_sha256=manifest.config_sha256,
    )
    assert output.read_bytes() == b""


def test_jsonl_rejects_model_copy_tampering_before_creating_output(tmp_path: Path) -> None:
    manifest = _manifest()
    tampered = _observation(manifest).model_copy(update={"map_number": 0})
    output = tmp_path / "invalid-copy.jsonl"
    with pytest.raises(ValueError, match="invalid provenance"):
        write_observation_jsonl(
            output, [{"provenance": tampered}], manifest,
            expected_run_id=manifest.run_id,
            expected_source_sha256=manifest.source_video_sha256,
            expected_config_sha256=manifest.config_sha256,
        )
    assert not output.exists()


def test_jsonl_uses_detached_rows_after_generator_mutation(tmp_path: Path) -> None:
    manifest = _manifest()
    first = {"provenance": _observation(manifest).model_dump(mode="json"), "nested": {"x": 1}}
    second = {"provenance": _observation(manifest).model_dump(mode="json")}

    def rows():
        yield first
        first["provenance"]["run_id"] = "foreign-run"
        first["nested"]["x"] = 2
        yield second

    output = tmp_path / "mutated.jsonl"
    write_observation_jsonl(
        output, rows(), manifest, expected_run_id=manifest.run_id,
        expected_source_sha256=manifest.source_video_sha256,
        expected_config_sha256=manifest.config_sha256,
    )
    written = [json.loads(line) for line in output.read_text().splitlines()]
    assert written[0]["provenance"]["run_id"] == manifest.run_id
    assert written[0]["nested"]["x"] == 1


def test_invalid_jsonl_preflight_leaves_no_partial_output(tmp_path: Path) -> None:
    manifest = _manifest()
    output = tmp_path / "observations.jsonl"
    rows = [
        {"provenance": _observation(manifest).model_dump(mode="json")},
        {"provenance": _observation(manifest, run_id="foreign-run").model_dump(mode="json")},
    ]
    with pytest.raises(ValueError, match="expected run/source/config"):
        write_observation_jsonl(
            output, rows, manifest, expected_run_id=manifest.run_id,
            expected_source_sha256=manifest.source_video_sha256,
            expected_config_sha256=manifest.config_sha256,
        )
    assert not output.exists()
