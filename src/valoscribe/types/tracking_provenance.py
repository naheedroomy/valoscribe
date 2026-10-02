"""Typed provenance contracts for anonymous tracking runs and observations."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

_SHA256 = r"^[0-9a-f]{64}$"
_SAFE_ID = r"^[A-Za-z0-9][A-Za-z0-9._-]*$"


class ConfigFileProvenance(BaseModel):
    """Identity and content digest for one actual input configuration file."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    config_id: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    file_sha256: str = Field(pattern=_SHA256)


class TrackingRunManifest(BaseModel):
    """Complete immutable source, configuration, code, and run binding."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    run_id: str
    source_path: str = Field(min_length=1)
    source_video_sha256: str = Field(pattern=_SHA256)
    source_width: int = Field(gt=0)
    source_height: int = Field(gt=0)
    fps_numerator: int = Field(gt=0)
    fps_denominator: int = Field(gt=0)
    timebase_numerator: int = Field(gt=0)
    timebase_denominator: int = Field(gt=0)
    map_id: str = Field(min_length=1)
    map_number: int = Field(gt=0)
    round_number: int = Field(gt=0)
    start_frame_index: int = Field(ge=0)
    end_frame_index: int = Field(gt=0)
    start_source_pts: int = Field(ge=0)
    end_source_pts: int = Field(gt=0)
    start_timestamp_s: float = Field(ge=0)
    end_timestamp_s: float = Field(gt=0)
    hud_config: ConfigFileProvenance
    color_config: ConfigFileProvenance
    map_config: ConfigFileProvenance
    config_sha256: str = Field(pattern=_SHA256)
    map_asset_sha256: str = Field(pattern=_SHA256)
    map_asset_version: str = Field(min_length=1)
    project_commit: str = Field(min_length=1)
    upstream_commit: str = Field(min_length=1)
    code_fingerprint_sha256: str = Field(pattern=_SHA256)
    detector_version: str = Field(min_length=1)
    tracker_version: str = Field(min_length=1)
    annotation_version: str | None = None
    started_at: AwareDatetime

    @field_validator("run_id")
    @classmethod
    def safe_run_id(cls, value: str) -> str:
        if re.fullmatch(_SAFE_ID, value) is None:
            raise ValueError("run_id must be a safe path component")
        return value

    @field_validator("started_at")
    @classmethod
    def utc_start(cls, value: datetime) -> datetime:
        offset = value.utcoffset()
        if offset is None or offset.total_seconds() != 0:
            raise ValueError("started_at must be UTC")
        return value

    @field_validator("start_timestamp_s", "end_timestamp_s")
    @classmethod
    def finite_time(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("timestamps must be finite")
        return value

    @model_validator(mode="after")
    def consistent_binding(self) -> TrackingRunManifest:
        if self.end_frame_index < self.start_frame_index:
            raise ValueError("round frame bounds are reversed")
        if self.end_source_pts < self.start_source_pts:
            raise ValueError("round source PTS bounds are reversed")
        if self.end_timestamp_s < self.start_timestamp_s:
            raise ValueError("round timestamp bounds are reversed")
        expected_start = self.start_source_pts * self.timebase_numerator / self.timebase_denominator
        expected_end = self.end_source_pts * self.timebase_numerator / self.timebase_denominator
        if not math.isclose(self.start_timestamp_s, expected_start, rel_tol=0, abs_tol=1e-9):
            raise ValueError("start timestamp disagrees with source PTS/timebase")
        if not math.isclose(self.end_timestamp_s, expected_end, rel_tol=0, abs_tol=1e-9):
            raise ValueError("end timestamp disagrees with source PTS/timebase")
        if self.config_sha256 != canonical_config_sha256(
            self.hud_config, self.color_config, self.map_config
        ):
            raise ValueError("config_sha256 does not bind actual config file contents")
        return self


class TrackingObservationProvenance(BaseModel):
    """Exact source/run binding attached to one frame observation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(pattern=_SAFE_ID)
    manifest_sha256: str = Field(pattern=_SHA256)
    source_video_sha256: str = Field(pattern=_SHA256)
    config_sha256: str = Field(pattern=_SHA256)
    map_id: str = Field(min_length=1)
    map_number: int = Field(gt=0)
    round_number: int = Field(gt=0)
    frame_index: int = Field(ge=0)
    source_pts: int = Field(ge=0)
    timebase_numerator: int = Field(gt=0)
    timebase_denominator: int = Field(gt=0)
    timestamp_s: float = Field(ge=0)

    @field_validator("timestamp_s")
    @classmethod
    def finite_timestamp(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("observation timestamp must be finite")
        return value


class TrackingArtifactBinding(BaseModel):
    """Manifest-bound digest record for an arbitrary binary or tabular artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    artifact_kind: str = Field(min_length=1)
    relative_path: str = Field(min_length=1)
    payload_sha256: str = Field(pattern=_SHA256)
    run_id: str = Field(pattern=_SAFE_ID)
    manifest_sha256: str = Field(pattern=_SHA256)


def canonical_config_sha256(
    hud: ConfigFileProvenance, color: ConfigFileProvenance, map_config: ConfigFileProvenance
) -> str:
    """Hash canonical config IDs and actual file digests (not filenames alone)."""
    payload = {
        "hud": hud.model_dump(mode="json"),
        "color": color.model_dump(mode="json"),
        "map": map_config.model_dump(mode="json"),
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
