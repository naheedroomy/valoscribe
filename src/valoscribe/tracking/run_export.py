"""Fail-closed export and readback of identity-bearing canonical player tracks."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import TypeVar

import numpy as np
from pydantic import BaseModel, ValidationError

from valoscribe.tracking.artifacts import (
    _load_arrow,
    build_track_rows,
    write_player_tracks_parquet,
    write_track_debug_playback,
)
from valoscribe.types.persistent import (
    NormalizedPoint,
    PlayerTrackArtifactRow,
    PlayerTrackEstimate,
    Side,
    SmoothedTrackSample,
    TrackSmoothingInput,
)
from valoscribe.types.player_track_run import PlayerTrackRunBinding
from valoscribe.types.run_manifest import RunManifest, write_run_manifest

_Model = TypeVar("_Model", bound=BaseModel)


class PlayerTrackRun:
    """Canonical Parquet, existing RunManifest, binding, and stable-ID playback."""

    def __init__(self, directory: Path, binding: PlayerTrackRunBinding) -> None:
        self.directory = directory
        self.binding = binding

    @property
    def parquet_path(self) -> Path:
        return self.directory / "player_tracks.parquet"


def export_player_track_run(
    runs_root: Path,
    *,
    manifest: RunManifest,
    expected_source_file_sha256: str,
    match_id: str,
    map_id: str,
    round_id: str,
    inputs: list[TrackSmoothingInput],
    outputs: tuple[SmoothedTrackSample, ...],
    agent_by_player: dict[str, str],
    team_by_player: dict[str, str],
    side_by_player: dict[str, Side],
    map_image: np.ndarray,
) -> PlayerTrackRun:
    """Persist already assigned/smoothed samples; never invent identity or positions."""
    verified_manifest = _validate_manifest(manifest)
    if verified_manifest.status != "complete":
        raise ValueError("player-track export requires a complete RunManifest")
    if verified_manifest.source_file_sha256 is None or (
        verified_manifest.source_file_sha256.lower() != expected_source_file_sha256.lower()
    ):
        raise ValueError("RunManifest source hash does not match expected source hash")
    if not match_id.strip() or not map_id.strip() or not round_id.strip():
        raise ValueError("explicit match, map, and round IDs are required")
    if not inputs or not outputs:
        raise ValueError("player-track export requires non-empty resolved identity inputs")
    if len(inputs) != len(outputs):
        raise ValueError("each raw smoothing input requires one derived output")
    roster = set(agent_by_player)
    if not roster or roster != set(team_by_player) or roster != set(side_by_player):
        raise ValueError("agent, team, and side metadata must cover the same known roster")
    identifiers: set[str] = set()
    verified_inputs = tuple(_validate_model(sample, TrackSmoothingInput) for sample in inputs)
    verified_outputs = tuple(_validate_model(output, SmoothedTrackSample) for output in outputs)
    for sample in verified_inputs:
        assert isinstance(sample, TrackSmoothingInput)
        player_id = sample.estimate.player_id
        if sample.round_id != round_id:
            raise ValueError("all samples must belong to the explicitly requested round")
        if player_id.lower().startswith(("anon-", "tracklet-", "unknown")):
            raise ValueError("anonymous or unknown track IDs cannot become player identities")
        if player_id not in roster:
            raise ValueError(f"sample player {player_id} is not in the explicit roster")
        identifiers.add(player_id)
    if not identifiers:
        raise ValueError("player-track export has no resolved roster identities")
    rows = build_track_rows(
        list(verified_inputs),
        verified_outputs,
        match_id=match_id,
        map_id=map_id,
        agent_by_player=agent_by_player,
        team_by_player=team_by_player,
        side_by_player=side_by_player,
    )
    _validate_rows(rows, match_id, map_id, round_id, roster)
    _load_arrow()
    root = _safe_path(runs_root)
    root.mkdir(parents=True, exist_ok=True)
    directory = root / verified_manifest.run_id
    if directory.is_symlink():
        raise ValueError("player-track run directory must not be a symlink")
    if directory.exists():
        raise FileExistsError(f"player-track run already exists: {directory}")
    created_directory = False
    manifest_path: Path | None = None
    parquet_path = directory / "player_tracks.parquet"
    binding_path = directory / "player_tracks.binding.json"
    playback_directory = directory / "debug_playback"
    playback_frame_paths: list[Path] = []
    try:
        directory.mkdir()
        created_directory = True
        manifest_path = write_run_manifest(verified_manifest, root)
        write_player_tracks_parquet(parquet_path, rows)
        manifest_bytes = manifest_path.read_bytes()
        parquet_bytes = parquet_path.read_bytes()
        binding = PlayerTrackRunBinding(
            run_id=verified_manifest.run_id,
            manifest_sha256=_sha256(manifest_bytes),
            parquet_sha256=_sha256(parquet_bytes),
            source_file_sha256=expected_source_file_sha256.lower(),
            match_id=match_id,
            map_id=map_id,
            round_id=round_id,
            player_ids=sorted(identifiers),
        )
        _create_exclusive(binding_path, binding.model_dump_json(indent=2).encode() + b"\n")
        playback_directory.mkdir()
        timestamps = sorted({row.vod_timestamp_s for row in rows})
        playback_frame_paths = [
            playback_directory / f"frame_{index:06d}_{timestamp:012.3f}.png"
            for index, timestamp in enumerate(timestamps)
        ]
        write_track_debug_playback(playback_directory, map_image, rows)
        return PlayerTrackRun(directory, binding)
    except BaseException:
        if created_directory:
            for frame in playback_frame_paths:
                frame.unlink(missing_ok=True)
            if playback_directory.is_dir() and not any(playback_directory.iterdir()):
                playback_directory.rmdir()
            for owned_path in (binding_path, parquet_path):
                owned_path.unlink(missing_ok=True)
            if manifest_path is not None:
                manifest_path.unlink(missing_ok=True)
            if directory.is_dir() and not any(directory.iterdir()):
                directory.rmdir()
        raise


def read_player_track_run(
    runs_root: Path,
    *,
    run_id: str,
    expected_manifest_sha256: str,
    expected_binding_sha256: str,
) -> tuple[RunManifest, PlayerTrackRunBinding, list[PlayerTrackArtifactRow]]:
    """Read back only if caller independently pins manifest and binding bytes."""
    _validate_run_id(run_id)
    for digest, name in (
        (expected_manifest_sha256, "manifest"),
        (expected_binding_sha256, "binding"),
    ):
        if re.fullmatch(r"[a-fA-F0-9]{64}", digest) is None:
            raise ValueError(f"expected {name} SHA-256 must be 64 hexadecimal characters")
    root = _safe_path(runs_root)
    try:
        root_fd = _open_directory_fd(root)
        try:
            run_fd = _open_child_directory_fd(root_fd, run_id)
            try:
                manifest_bytes = _read_file_at(run_fd, "manifest.json")
                binding_bytes = _read_file_at(run_fd, "player_tracks.binding.json")
                parquet_bytes = _read_file_at(run_fd, "player_tracks.parquet")
            finally:
                os.close(run_fd)
        finally:
            os.close(root_fd)
        manifest = _validate_manifest(RunManifest.model_validate_json(manifest_bytes))
        binding = PlayerTrackRunBinding.model_validate_json(binding_bytes)
    except (OSError, ValidationError, ValueError) as error:
        raise ValueError("invalid or incomplete player-track run metadata") from error
    manifest_digest = _sha256(manifest_bytes)
    binding_digest = _sha256(binding_bytes)
    if manifest_digest.lower() != expected_manifest_sha256.lower():
        raise ValueError("RunManifest bytes do not match independently expected hash")
    if binding_digest.lower() != expected_binding_sha256.lower():
        raise ValueError("player-track binding bytes do not match independently expected hash")
    if manifest.status != "complete":
        raise ValueError("player-track readback requires a complete RunManifest")
    if (
        manifest.run_id != run_id
        or binding.run_id != run_id
        or binding.manifest_sha256.lower() != manifest_digest.lower()
    ):
        raise ValueError("player-track binding does not match requested RunManifest")
    if binding.source_file_sha256.lower() != (manifest.source_file_sha256 or "").lower():
        raise ValueError("player-track binding source hash does not match RunManifest")
    if _sha256(parquet_bytes).lower() != binding.parquet_sha256.lower():
        raise ValueError("player_tracks.parquet digest does not match its binding")
    pa, parquet = _load_arrow()
    table = parquet.read_table(pa.BufferReader(parquet_bytes))
    if (table.schema.metadata or {}).get(b"valoscribe.schema") != b"player_tracks/1.0":
        raise ValueError("missing or unsupported Valoscribe player_tracks Parquet schema")
    try:
        rows = [PlayerTrackArtifactRow.model_validate(row) for row in table.to_pylist()]
    except ValidationError as error:
        raise ValueError("invalid player_tracks Parquet row") from error
    _validate_rows(
        rows,
        binding.match_id,
        binding.map_id,
        binding.round_id,
        set(binding.player_ids),
    )
    return manifest, binding, rows


def _validate_manifest(manifest: RunManifest) -> RunManifest:
    try:
        value = RunManifest.model_validate(manifest.model_dump(mode="python"))
    except (ValidationError, AttributeError, TypeError) as error:
        raise ValueError("invalid RunManifest") from error
    return value


def _validate_model(value: _Model, model_type: type[_Model]) -> _Model:
    try:
        return model_type.model_validate(value.model_dump(mode="python"))  # type: ignore[attr-defined]
    except (ValidationError, AttributeError, TypeError) as error:
        raise ValueError("invalid or mutated player-track input") from error


def _validate_rows(
    rows: list[PlayerTrackArtifactRow],
    match_id: str,
    map_id: str,
    round_id: str,
    roster: set[str],
) -> None:
    if not rows:
        raise ValueError("player_tracks.parquet must contain at least one row")
    seen_keys: set[tuple[str, str, str, str, float]] = set()
    for index, row in enumerate(rows):
        try:
            valid = PlayerTrackArtifactRow.model_validate(row.model_dump(mode="python"))
            estimate = PlayerTrackEstimate.model_validate_json(valid.raw_estimate_json)
            raw_evidence = json.loads(valid.raw_evidence_json)
            derived_evidence = json.loads(valid.derived_evidence_json)
            if not isinstance(raw_evidence, list) or not all(
                isinstance(item, str) for item in raw_evidence
            ):
                raise ValueError("raw evidence must be a string list")
            if not isinstance(derived_evidence, list) or not all(
                isinstance(item, str) for item in derived_evidence
            ):
                raise ValueError("derived evidence must be a string list")
            if raw_evidence != estimate.evidence:
                raise ValueError("raw evidence does not match raw estimate")
            if valid.x is None:
                point = None
            else:
                assert valid.y is not None
                point = NormalizedPoint(x=valid.x, y=valid.y)
            SmoothedTrackSample(
                raw_estimate=estimate,
                position=point,
                observed=valid.observed,
                interpolated=valid.interpolated,
                confidence=valid.confidence,
                rejection_reason=valid.rejection_reason,
                evidence=derived_evidence,
            )
        except (
            ValidationError,
            AttributeError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as error:
            raise ValueError(f"invalid or inconsistent player-track row {index}") from error
        if (valid.match_id, valid.map_id, valid.round_id) != (match_id, map_id, round_id):
            raise ValueError("player-track rows mix match, map, or round context")
        if valid.player_id not in roster or valid.player_id.lower().startswith(
            ("anon-", "tracklet-", "unknown")
        ):
            raise ValueError("player-track row contains an identity outside the known roster")
        if (
            estimate.player_id != valid.player_id
            or estimate.vod_timestamp_s != valid.vod_timestamp_s
        ):
            raise ValueError("raw estimate player/timestamp does not match player-track row")
        key = (valid.match_id, valid.map_id, valid.round_id, valid.player_id, valid.vod_timestamp_s)
        if key in seen_keys:
            raise ValueError("duplicate player/timestamp row key")
        seen_keys.add(key)


def _validate_run_id(run_id: str) -> str:
    if not isinstance(run_id, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", run_id) is None:
        raise ValueError("run_id must be a single safe path component")
    return run_id


def _open_directory_fd(path: Path) -> int:
    """Open every directory component relative to an FD without following symlinks."""
    absolute = Path(os.path.abspath(path))
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(absolute.anchor, flags)
    try:
        for component in absolute.parts[1:]:
            child = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _open_child_directory_fd(parent_fd: int, name: str) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    return os.open(name, flags, dir_fd=parent_fd)


def _read_file_at(directory_fd: int, name: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(name, flags, dir_fd=directory_fd)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("player-track artifact must be a regular file")
        with os.fdopen(descriptor, "rb", closefd=True) as source:
            descriptor = -1
            return source.read()
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _safe_path(path: Path) -> Path:
    path = Path(path)
    if ".." in path.parts:
        raise ValueError("run path must not contain parent traversal")
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        current /= component
        if current.is_symlink():
            raise ValueError("run paths must not contain symlinks")
    return absolute


def _create_exclusive(path: Path, payload: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()
