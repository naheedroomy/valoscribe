"""Preflight validation engine and execution planning for VOD round processing."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from valoscribe.tactical.config import CropConfig, HSVRange, StrictModel, TransformConfig
from valoscribe.tactical.manifest import VODBroadcastProfile, VODRoundManifest


class PreflightValidationError(ValueError):
    """Raised when preflight validation of VOD, profiles, or manifests fails."""


class RoundRangeResolutionError(PreflightValidationError):
    """Raised when the requested round range cannot be fully resolved."""


class ResolvedRoundPlan(StrictModel):
    """Resolved execution plan for an individual confirmed round."""

    map_round: int = Field(ge=1)
    round_id: str = Field(min_length=1)
    source_interval_seconds: tuple[float, float]
    live_start_offset_seconds: float = Field(ge=0)
    selected_team_side: Literal["attack", "defense"]
    opponent_team_side: Literal["attack", "defense"]
    boundary_evidence: str = Field(default="")
    excluded_intervals: list[dict[str, Any]] = Field(default_factory=list)


class VODExecutionPlan(StrictModel):
    """Execution plan containing all resolved parameters for VOD processing."""

    match_id: str = Field(min_length=1)
    map_id: str = Field(min_length=1)
    map_name: str = Field(min_length=1)
    source_video_path: Path
    source_video_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_team_id: str = Field(min_length=1)
    opponent_team_id: str = Field(min_length=1)
    minimap_crop: CropConfig
    transform: TransformConfig
    selected_team_calibrations: list[HSVRange] = Field(min_length=1)
    opponent_team_calibrations: list[HSVRange] = Field(min_length=1)
    selected_rounds: list[ResolvedRoundPlan] = Field(min_length=1)
    output_dir: Path


def compute_sha256(path: Path, chunk_size: int = 65536) -> str:
    """Compute the SHA-256 digest of a file in chunks."""
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(chunk_size):
            hasher.update(chunk)
    return hasher.hexdigest()


def validate_vod_preflight(
    vod_path: Path,
    map_name: str,
    match_id: str,
    map_id: str,
    from_round: int,
    to_round: int,
    selected_team_id: str,
    manifest: VODRoundManifest,
    profile: VODBroadcastProfile,
    output_dir: Path,
    verify_sha256: bool = True,
) -> VODExecutionPlan:
    """Validate all preflight requirements and compile a VODExecutionPlan.

    Fails closed if any requirement is not met:
    - VOD file must exist on disk.
    - If verify_sha256 is True, SHA-256 must match manifest.source_video_sha256.
    - map_name and manifest.map_name must both equal 'ascent'.
    - Minimap crop coordinates must fit within 1920x1080 broadcast frame.
    - selected_team_id must be declared in manifest.teams.
    - Manifest must define exactly two teams, identifying the opponent team.
    - Both selected and opponent teams must have HSV color calibrations in profile.
    - from_round must be <= to_round.
    - Every round in range(from_round, to_round + 1) must exist and be 'confirmed'.
    - output_dir must not already exist with content (collision guard).
    """
    vod_path = Path(vod_path)
    output_dir = Path(output_dir)

    # 1. VOD file check
    if not vod_path.is_file():
        raise PreflightValidationError(f"VOD source file does not exist: {vod_path}")

    # 2. SHA-256 verification
    if verify_sha256:
        computed_sha = compute_sha256(vod_path)
        if computed_sha != manifest.source_video_sha256:
            raise PreflightValidationError(
                f"VOD SHA-256 mismatch for {vod_path}: "
                f"expected {manifest.source_video_sha256}, got {computed_sha}"
            )

    # 3. Map validation
    if map_name.lower() != "ascent":
        raise PreflightValidationError(
            f"Unsupported map: {map_name!r}. Only 'ascent' is supported."
        )
    if manifest.map_name.lower() != "ascent":
        raise PreflightValidationError(
            f"Manifest specifies unsupported map: {manifest.map_name!r}. "
            "Only 'ascent' is supported."
        )
    if map_name.lower() != manifest.map_name.lower():
        raise PreflightValidationError(
            f"Requested map {map_name!r} does not match manifest map {manifest.map_name!r}"
        )

    # 4. Minimap crop bounds check (1920x1080 standard spectator frame)
    crop = profile.minimap_crop
    if crop.x + crop.width > 1920 or crop.y + crop.height > 1080:
        raise PreflightValidationError(
            f"Minimap crop [{crop.x}, {crop.y}, {crop.width}, {crop.height}] "
            f"exceeds broadcast frame bounds 1920x1080"
        )

    # 5. Team validation and calibration checks
    if selected_team_id not in manifest.teams:
        raise PreflightValidationError(
            f"Selected team {selected_team_id!r} not found in manifest teams: "
            f"{list(manifest.teams.keys())}"
        )

    opponent_candidates = [t for t in manifest.teams if t != selected_team_id]
    if len(opponent_candidates) != 1:
        raise PreflightValidationError(
            f"Manifest must define exactly two teams, but found {len(manifest.teams)}: "
            f"{list(manifest.teams.keys())}"
        )
    opponent_team_id = opponent_candidates[0]

    if selected_team_id not in profile.team_calibrations:
        raise PreflightValidationError(
            f"Selected team {selected_team_id!r} missing calibration in broadcast profile"
        )
    if opponent_team_id not in profile.team_calibrations:
        raise PreflightValidationError(
            f"Opponent team {opponent_team_id!r} missing calibration in broadcast profile"
        )

    # 6. Round range resolution
    if from_round > to_round:
        raise RoundRangeResolutionError(
            f"Invalid round range: from_round ({from_round}) > to_round ({to_round})"
        )

    rounds_by_num = {r.map_round: r for r in manifest.rounds}
    resolution_errors: list[str] = []

    for r in range(from_round, to_round + 1):
        if r not in rounds_by_num:
            resolution_errors.append(f"Round {r} is missing from manifest")
        else:
            entry = rounds_by_num[r]
            if entry.status != "confirmed":
                resolution_errors.append(
                    f"Round {r} is '{entry.status}' (boundary: {entry.boundary_evidence!r})"
                )

    if resolution_errors:
        raise RoundRangeResolutionError(
            f"Round range [{from_round}, {to_round}] contains unconfirmed or missing rounds: "
            + "; ".join(resolution_errors)
        )

    # 7. Output directory collision guard
    if output_dir.is_file():
        raise FileExistsError(f"Refusing to overwrite existing output file: {output_dir}")
    if output_dir.is_dir() and any(output_dir.iterdir()):
        raise FileExistsError(
            f"Refusing to overwrite existing output directory with contents: {output_dir}"
        )

    # 8. Compile resolved round plans
    selected_rounds: list[ResolvedRoundPlan] = []
    for r in range(from_round, to_round + 1):
        entry = rounds_by_num[r]

        # Determine sides
        if selected_team_id in entry.team_sides:
            selected_side = entry.team_sides[selected_team_id]
        else:
            start_side = manifest.teams[selected_team_id].starting_side
            if entry.map_round <= manifest.halftime_after_round:
                selected_side = start_side
            else:
                selected_side = "defense" if start_side == "attack" else "attack"

        if opponent_team_id in entry.team_sides:
            opponent_side = entry.team_sides[opponent_team_id]
        else:
            opponent_side = "defense" if selected_side == "attack" else "attack"

        selected_rounds.append(
            ResolvedRoundPlan(
                map_round=entry.map_round,
                round_id=entry.round_id,
                source_interval_seconds=(entry.source_start_seconds, entry.source_end_seconds),
                live_start_offset_seconds=entry.live_start_seconds - entry.source_start_seconds,
                selected_team_side=selected_side,
                opponent_team_side=opponent_side,
                boundary_evidence=entry.boundary_evidence,
                excluded_intervals=[span.model_dump() for span in entry.excluded_spans],
            )
        )

    return VODExecutionPlan(
        match_id=match_id,
        map_id=map_id,
        map_name=map_name,
        source_video_path=vod_path,
        source_video_sha256=manifest.source_video_sha256,
        selected_team_id=selected_team_id,
        opponent_team_id=opponent_team_id,
        minimap_crop=profile.minimap_crop,
        transform=profile.transform,
        selected_team_calibrations=profile.team_calibrations[selected_team_id].color_ranges_hsv,
        opponent_team_calibrations=profile.team_calibrations[opponent_team_id].color_ranges_hsv,
        selected_rounds=selected_rounds,
        output_dir=output_dir,
    )
