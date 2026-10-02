"""Pinned metadata for one canonical player-track export."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from valoscribe.types.persistent import PersistentModel


class PlayerTrackRunBinding(PersistentModel):
    """Binds player_tracks/1.0 bytes to a separately expected RunManifest hash."""

    schema_version: Literal["1.0"] = "1.0"
    run_id: str = Field(min_length=1)
    manifest_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    parquet_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    source_file_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    match_id: str = Field(min_length=1)
    map_id: str = Field(min_length=1)
    round_id: str = Field(min_length=1)
    player_ids: list[str] = Field(min_length=1)

    @field_validator("player_ids")
    @classmethod
    def roster_ids_are_stable_and_unique(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value) or any(
            not player or player.lower().startswith(("anon-", "tracklet-", "unknown"))
            for player in value
        ):
            raise ValueError("binding roster must contain unique known player IDs")
        return value
