"""Fail-closed validation and persistence for anonymous tracking provenance."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from pydantic import ValidationError

from valoscribe.types.tracking_provenance import (
    TrackingArtifactBinding,
    TrackingObservationProvenance,
    TrackingRunManifest,
)


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize finite JSON deterministically for content-addressed bindings."""
    def detach(item: Any) -> Any:
        if hasattr(item, "model_dump"):
            return detach(item.model_dump(mode="json"))
        if isinstance(item, dict):
            return {key: detach(nested) for key, nested in item.items()}
        if isinstance(item, (list, tuple)):
            return [detach(nested) for nested in item]
        return item

    try:
        return json.dumps(
            detach(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValueError("value is not canonical finite JSON") from error


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _reject_symlink_components(path: Path, *, message: str) -> Path:
    """Reject symlinks in the complete supplied path without resolving them."""
    path = Path(path)
    if any(part == ".." for part in path.parts):
        raise ValueError(message)
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        if current.is_symlink():
            raise ValueError(message)
    return absolute


def local_file_sha256(path: Path) -> str:
    """Hash bytes of a local regular file; reject symlinks in all ancestors."""
    path = _reject_symlink_components(
        Path(path), message="source/config path must not contain symlinks"
    )
    if not path.is_file():
        raise ValueError("source/config file must be a regular non-symlink file")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def local_content_tree_sha256(root: Path, relative_paths: Iterable[str]) -> str:
    """Hash selected local code/config contents and names for dirty-tree provenance."""
    root = _reject_symlink_components(
        Path(root), message="content fingerprint path must not contain symlinks"
    )
    entries: list[tuple[str, str]] = []
    for relative_path in sorted(set(relative_paths)):
        path = PurePosixPath(relative_path)
        if path.is_absolute() or not path.parts or any(
            part in {"", ".", ".."} for part in path.parts
        ):
            raise ValueError("content fingerprint paths must be safe relative paths")
        file_path = _reject_symlink_components(
            root.joinpath(*path.parts), message="content fingerprint path must not contain symlinks"
        )
        entries.append((path.as_posix(), local_file_sha256(file_path)))
    if not entries:
        raise ValueError("content fingerprint requires at least one file")
    return canonical_sha256(entries)


def validate_manifest(manifest: TrackingRunManifest) -> TrackingRunManifest:
    """Revalidate nested data to catch model_copy and mutable-dict bypasses."""
    try:
        return TrackingRunManifest.model_validate(manifest.model_dump(mode="python"))
    except (ValidationError, AttributeError, TypeError) as error:
        raise ValueError("invalid tracking run manifest") from error


def manifest_sha256(manifest: TrackingRunManifest) -> str:
    return canonical_sha256(validate_manifest(manifest))


def validate_observation(
    observation: TrackingObservationProvenance,
    manifest: TrackingRunManifest,
    *,
    expected_run_id: str,
    expected_source_sha256: str,
    expected_config_sha256: str,
) -> TrackingObservationProvenance:
    """Require exact agreement across observation, manifest, and caller binding."""
    verified_manifest = validate_manifest(manifest)
    try:
        value = TrackingObservationProvenance.model_validate(
            observation.model_dump(mode="python")
        )
    except (ValidationError, AttributeError, TypeError) as error:
        raise ValueError("invalid tracking observation provenance") from error
    digest = manifest_sha256(verified_manifest)
    expected = (
        value.run_id == verified_manifest.run_id == expected_run_id
        and value.manifest_sha256 == digest
        and value.source_video_sha256
        == verified_manifest.source_video_sha256
        == expected_source_sha256
        and value.config_sha256 == verified_manifest.config_sha256 == expected_config_sha256
        and value.map_id == verified_manifest.map_id
        and value.map_number == verified_manifest.map_number
        and value.round_number == verified_manifest.round_number
        and value.timebase_numerator == verified_manifest.timebase_numerator
        and value.timebase_denominator == verified_manifest.timebase_denominator
        and verified_manifest.start_frame_index
        <= value.frame_index
        <= verified_manifest.end_frame_index
        and verified_manifest.start_source_pts
        <= value.source_pts
        <= verified_manifest.end_source_pts
    )
    if not expected:
        raise ValueError("observation provenance does not match expected run/source/config/round")
    exact_timestamp = value.source_pts * value.timebase_numerator / value.timebase_denominator
    if abs(value.timestamp_s - exact_timestamp) > 1e-9:
        raise ValueError("observation timestamp disagrees with source PTS/timebase")
    return value


def validate_observation_rows(
    rows: Iterable[dict[str, Any]],
    manifest: TrackingRunManifest,
    *,
    expected_run_id: str,
    expected_source_sha256: str,
    expected_config_sha256: str,
) -> list[dict[str, Any]]:
    """Validate every JSONL row before an output file is opened or created."""
    _validate_expected_binding(
        manifest, expected_run_id, expected_source_sha256, expected_config_sha256
    )
    verified: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or "provenance" not in row:
            raise ValueError(f"observation row {index} is missing provenance")
        try:
            snapshot = json.loads(canonical_json_bytes(row))
            provenance = TrackingObservationProvenance.model_validate(snapshot["provenance"])
        except (ValidationError, TypeError, ValueError, KeyError) as error:
            raise ValueError(f"observation row {index} has invalid provenance or JSON") from error
        validate_observation(
            provenance,
            manifest,
            expected_run_id=expected_run_id,
            expected_source_sha256=expected_source_sha256,
            expected_config_sha256=expected_config_sha256,
        )
        verified.append(snapshot)
    return verified


def _validate_expected_binding(
    manifest: TrackingRunManifest,
    expected_run_id: str,
    expected_source_sha256: str,
    expected_config_sha256: str,
) -> TrackingRunManifest:
    verified = validate_manifest(manifest)
    if (verified.run_id, verified.source_video_sha256, verified.config_sha256) != (
        expected_run_id, expected_source_sha256, expected_config_sha256
    ):
        raise ValueError("manifest does not match expected run/source/config")
    return verified


def write_observation_jsonl(
    path: Path,
    rows: Iterable[dict[str, Any]],
    manifest: TrackingRunManifest,
    *,
    expected_run_id: str,
    expected_source_sha256: str,
    expected_config_sha256: str,
) -> None:
    """Validate all rows then atomically create JSONL without overwriting."""
    destination = _reject_symlink_components(
        Path(path), message="observation output path must not contain symlinks"
    )
    verified = validate_observation_rows(
        rows, manifest, expected_run_id=expected_run_id,
        expected_source_sha256=expected_source_sha256,
        expected_config_sha256=expected_config_sha256,
    )
    payload = b"".join(canonical_json_bytes(row) + b"\n" for row in verified)
    _atomic_create(destination, payload)


def write_tracking_manifest(manifest: TrackingRunManifest, runs_root: Path) -> Path:
    """Create an immutable manifest at runs/<run_id>/manifest.json."""
    verified = validate_manifest(manifest)
    root = _reject_symlink_components(
        Path(runs_root), message="runs root path must not contain symlinks"
    )
    root.mkdir(parents=True, exist_ok=True)
    _reject_symlink_components(root, message="runs root path must not contain symlinks")
    run_dir = root / verified.run_id
    run_dir.mkdir(exist_ok=True)
    _reject_symlink_components(run_dir, message="run directory path must not contain symlinks")
    destination = run_dir / "manifest.json"
    _atomic_create(destination, canonical_json_bytes(verified) + b"\n")
    return destination


def read_tracking_manifest(
    path: Path, *, expected_run_id: str, expected_source_sha256: str, expected_config_sha256: str
) -> TrackingRunManifest:
    """Read manifest and reject mismatched caller expectations or tampering."""
    path = _reject_symlink_components(
        Path(path), message="manifest path must not contain symlinks"
    )
    try:
        manifest = TrackingRunManifest.model_validate_json(path.read_bytes())
    except (OSError, ValidationError) as error:
        raise ValueError("invalid tracking manifest") from error
    manifest = validate_manifest(manifest)
    if (manifest.run_id, manifest.source_video_sha256, manifest.config_sha256) != (
        expected_run_id, expected_source_sha256, expected_config_sha256
    ):
        raise ValueError("manifest does not match expected run/source/config")
    return manifest


def write_bound_artifact(
    runs_root: Path,
    manifest: TrackingRunManifest,
    relative_path: str,
    payload: bytes,
    *,
    artifact_kind: str,
    expected_run_id: str,
    expected_source_sha256: str,
    expected_config_sha256: str,
) -> TrackingArtifactBinding:
    """Atomically register a checked binary artifact beside its own sidecar."""
    verified = validate_manifest(manifest)
    if (verified.run_id, verified.source_video_sha256, verified.config_sha256) != (
        expected_run_id, expected_source_sha256, expected_config_sha256
    ):
        raise ValueError("artifact manifest does not match expected run/source/config")
    root = _reject_symlink_components(
        Path(runs_root), message="runs root path must not contain symlinks"
    )
    target = _safe_run_path(root, verified.run_id, relative_path)
    _verify_persisted_manifest(root, verified)
    binding = TrackingArtifactBinding(
        artifact_kind=artifact_kind,
        relative_path=relative_path,
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        run_id=verified.run_id,
        manifest_sha256=manifest_sha256(verified),
    )
    # Preflight both complete paths and collisions before either output is created.
    target.parent.mkdir(parents=True, exist_ok=True)
    target = _reject_symlink_components(
        target, message="artifact path must not contain symlinks"
    )
    sidecar = _reject_symlink_components(
        _sidecar_path(target), message="artifact sidecar path must not contain symlinks"
    )
    if target.exists():
        raise FileExistsError(target)
    if sidecar.exists():
        raise FileExistsError(sidecar)
    _atomic_create(target, payload)
    try:
        _atomic_create(sidecar, canonical_json_bytes(binding) + b"\n")
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return binding


def read_bound_artifact(
    runs_root: Path,
    manifest: TrackingRunManifest,
    relative_path: str,
    *,
    expected_run_id: str,
    expected_source_sha256: str,
    expected_config_sha256: str,
    expected_artifact_kind: str,
) -> bytes:
    """Read payload only when its sidecar and caller/manifest binding all agree."""
    verified = validate_manifest(manifest)
    if (verified.run_id, verified.source_video_sha256, verified.config_sha256) != (
        expected_run_id, expected_source_sha256, expected_config_sha256
    ):
        raise ValueError("artifact manifest does not match expected run/source/config")
    root = _reject_symlink_components(
        Path(runs_root), message="runs root path must not contain symlinks"
    )
    target = _safe_run_path(root, verified.run_id, relative_path)
    _verify_persisted_manifest(root, verified)
    sidecar = _sidecar_path(target)
    if target.is_symlink() or sidecar.is_symlink():
        raise ValueError("artifact and sidecar must not be symlinks")
    try:
        binding = TrackingArtifactBinding.model_validate_json(sidecar.read_bytes())
        payload = target.read_bytes()
    except (OSError, ValidationError) as error:
        raise ValueError("missing or invalid artifact binding") from error
    if (
        binding.relative_path != relative_path
        or binding.artifact_kind != expected_artifact_kind
        or binding.run_id != expected_run_id
        or binding.manifest_sha256 != manifest_sha256(verified)
        or hashlib.sha256(payload).hexdigest() != binding.payload_sha256
    ):
        raise ValueError("artifact payload or provenance binding mismatch")
    return payload


def _verify_persisted_manifest(root: Path, manifest: TrackingRunManifest) -> None:
    manifest_path = _reject_symlink_components(
        root / manifest.run_id / "manifest.json",
        message="manifest path must not contain symlinks",
    )
    try:
        persisted = TrackingRunManifest.model_validate_json(manifest_path.read_bytes())
    except (OSError, ValidationError) as error:
        raise ValueError("missing or invalid persisted run manifest") from error
    if manifest_sha256(persisted) != manifest_sha256(manifest):
        raise ValueError("persisted run manifest digest mismatch")


def _safe_run_path(root: Path, run_id: str, relative_path: str) -> Path:
    root = _reject_symlink_components(root, message="runs root path must not contain symlinks")
    path = PurePosixPath(relative_path)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("artifact path must be a safe relative path")
    run_dir = root / run_id
    _reject_symlink_components(run_dir, message="run directory path must not contain symlinks")
    current = run_dir
    for part in path.parts[:-1]:
        current = current / part
        _reject_symlink_components(current, message="artifact path must not traverse symlinks")
    target = run_dir.joinpath(*path.parts)
    return _reject_symlink_components(target, message="artifact path must not contain symlinks")


def _sidecar_path(path: Path) -> Path:
    return path.with_name(path.name + ".provenance.json")


def _atomic_create(destination: Path, payload: bytes) -> None:
    """Durably create one file without replacement or temporary-file leaks."""
    destination = _reject_symlink_components(
        destination, message="output path must not contain symlinks"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    _reject_symlink_components(destination, message="output path must not contain symlinks")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=destination.parent, prefix=".provenance.", delete=False
        ) as file:
            temporary = Path(file.name)
            file.write(payload)
            file.flush()
            os.fsync(file.fileno())
        os.link(temporary, destination)
        temporary.unlink()
    except BaseException:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise
