"""Versioned metadata and atomic persistence for processing runs."""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


class RunManifest(BaseModel):
    """Reproducibility metadata for one processing run.

    Incomplete manifests support synthetic runs and work in progress. A complete
    run must include the provenance needed to reproduce its results.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(..., pattern=r"^1\.0$")
    status: Literal["incomplete", "complete"]
    run_id: str = Field(..., min_length=1)
    source_vod_identifier: str | None
    source_file_sha256: str | None = Field(..., pattern=r"^[a-fA-F0-9]{64}$")
    upstream_valoscribe_commit: str | None
    project_commit: str | None
    hud_profile_version: str | None
    map_asset_version: str | None
    zone_config_version: str | None
    detector_versions: dict[str, str]
    tracker_versions: dict[str, str]
    model_hashes: dict[str, str]
    sampling_rates: dict[str, float]
    cli_arguments: dict[str, Any]
    environment_lock_sha256: str | None = Field(..., pattern=r"^[a-fA-F0-9]{64}$")
    started_at: AwareDatetime
    ended_at: AwareDatetime
    stage_durations_seconds: dict[str, float]

    @field_validator("run_id")
    @classmethod
    def validate_run_id(cls, value: str) -> str:
        if value in {".", ".."} or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value) is None:
            raise ValueError("run_id must be a single safe path component")
        return value

    @field_validator("started_at", "ended_at")
    @classmethod
    def validate_utc_timestamp(cls, value: datetime) -> datetime:
        offset = value.utcoffset()
        if offset is None or offset.total_seconds() != 0:
            raise ValueError("timestamps must be UTC")
        return value

    @field_validator("sampling_rates")
    @classmethod
    def validate_sampling_rates(cls, value: dict[str, float]) -> dict[str, float]:
        if any(not math.isfinite(number) or number <= 0 for number in value.values()):
            raise ValueError("sampling rates must be finite and positive")
        return value

    @field_validator("stage_durations_seconds")
    @classmethod
    def validate_stage_durations(cls, value: dict[str, float]) -> dict[str, float]:
        if any(not math.isfinite(number) or number < 0 for number in value.values()):
            raise ValueError("stage durations must be finite and non-negative")
        return value

    @model_validator(mode="after")
    def validate_manifest_consistency(self) -> RunManifest:
        if self.ended_at < self.started_at:
            raise ValueError("ended_at must not precede started_at")
        if self.status == "complete":
            required_values = {
                "source_vod_identifier": self.source_vod_identifier,
                "source_file_sha256": self.source_file_sha256,
                "upstream_valoscribe_commit": self.upstream_valoscribe_commit,
                "project_commit": self.project_commit,
                "hud_profile_version": self.hud_profile_version,
                "map_asset_version": self.map_asset_version,
                "zone_config_version": self.zone_config_version,
                "environment_lock_sha256": self.environment_lock_sha256,
            }
            missing = [name for name, value in required_values.items() if not value]
            if not self.detector_versions or any(
                not name or not version for name, version in self.detector_versions.items()
            ):
                missing.append("detector_versions")
            if not self.tracker_versions or any(
                not name or not version for name, version in self.tracker_versions.items()
            ):
                missing.append("tracker_versions")
            if not self.sampling_rates:
                missing.append("sampling_rates")
            if missing:
                raise ValueError(
                    "complete manifest requires provenance: " + ", ".join(missing)
                )
        return self


def write_run_manifest(manifest: RunManifest, runs_root: Path) -> Path:
    """Atomically create ``runs/<run_id>/manifest.json`` without overwriting."""
    runs_root = Path(runs_root)
    if runs_root.is_symlink():
        raise ValueError("runs root must not be a symlink")
    runs_root.mkdir(parents=True, exist_ok=True)
    run_dir = runs_root / manifest.run_id
    if run_dir.is_symlink():
        raise ValueError("run directory must not be a symlink")
    run_dir.mkdir(exist_ok=True)
    if run_dir.is_symlink():
        raise ValueError("run directory must not be a symlink")

    destination = run_dir / "manifest.json"
    temporary_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=run_dir,
            prefix=".manifest.json.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(
                manifest.model_dump(mode="json"), temporary, indent=2, sort_keys=True,
                allow_nan=False,
            )
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        # A same-filesystem hard link atomically creates the destination only
        # when absent; unlike replace(), it cannot overwrite another run.
        os.link(temporary_path, destination)
        temporary_path.unlink()
    except BaseException:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise

    return destination
