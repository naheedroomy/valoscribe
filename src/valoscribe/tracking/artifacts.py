"""Validated Parquet output, label-based identity metrics, and track overlays."""

from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from pydantic import ValidationError

from valoscribe.types.persistent import (
    PlayerTrackArtifactRow,
    Side,
    SmoothedTrackSample,
    TrackDiagnosticMetrics,
    TrackIdentityLabel,
    TrackIdentityPrediction,
    TrackSmoothingInput,
)


class ParquetUnavailableError(RuntimeError):
    """Raised when the optional Arrow runtime is not installed."""


def build_track_rows(
    inputs: list[TrackSmoothingInput],
    outputs: tuple[SmoothedTrackSample, ...],
    *,
    match_id: str,
    map_id: str,
    agent_by_player: dict[str, str],
    team_by_player: dict[str, str],
    side_by_player: dict[str, Side],
) -> list[PlayerTrackArtifactRow]:
    """Flatten paired raw/derived estimates without discarding either record."""
    if len(inputs) != len(outputs):
        raise ValueError("each raw smoothing input requires one derived output")
    rows: list[PlayerTrackArtifactRow] = []
    for raw, derived in zip(inputs, outputs):
        estimate = raw.estimate
        if derived.raw_estimate != estimate:
            raise ValueError("derived sample must retain its corresponding raw estimate")
        if raw.round_id is None:
            raise ValueError("track artifacts require an explicit round ID")
        player_id = estimate.player_id
        try:
            agent_id = agent_by_player[player_id]
            team_id = team_by_player[player_id]
            side = side_by_player[player_id]
        except KeyError as error:
            raise ValueError(f"missing roster metadata for player {player_id}") from error
        point = derived.position
        rows.append(
            PlayerTrackArtifactRow(
                match_id=match_id,
                map_id=map_id,
                round_id=raw.round_id,
                vod_timestamp_s=estimate.vod_timestamp_s,
                player_id=player_id,
                agent_id=agent_id,
                team_id=team_id,
                side=side,
                x=None if point is None else point.x,
                y=None if point is None else point.y,
                observed=derived.observed,
                interpolated=derived.interpolated,
                confidence=derived.confidence,
                rejection_reason=derived.rejection_reason,
                raw_estimate_json=estimate.model_dump_json(),
                raw_evidence_json=json.dumps(estimate.evidence, separators=(",", ":")),
                derived_evidence_json=json.dumps(derived.evidence, separators=(",", ":")),
            )
        )
    return rows


def write_player_tracks_parquet(path: Path, rows: list[PlayerTrackArtifactRow]) -> None:
    """Write genuine Parquet, raising an actionable error if pyarrow is absent."""
    pa, parquet = _load_arrow()
    table = pa.Table.from_pylist([row.model_dump(mode="json") for row in rows])
    metadata = dict(table.schema.metadata or {})
    metadata[b"valoscribe.schema"] = b"player_tracks/1.0"
    table = table.replace_schema_metadata(metadata)
    path.parent.mkdir(parents=True, exist_ok=True)
    parquet.write_table(table, path)


def read_player_tracks_parquet(path: Path) -> list[PlayerTrackArtifactRow]:
    """Read and validate every row and the Valoscribe Parquet schema marker."""
    _, parquet = _load_arrow()
    table = parquet.read_table(path)
    if (table.schema.metadata or {}).get(b"valoscribe.schema") != b"player_tracks/1.0":
        raise ValueError("missing or unsupported Valoscribe player_tracks Parquet schema")
    rows: list[PlayerTrackArtifactRow] = []
    for value in table.to_pylist():
        try:
            rows.append(PlayerTrackArtifactRow.model_validate(value))
        except ValidationError as error:
            raise ValueError("invalid player_tracks Parquet row") from error
    return rows


def evaluate_identity_labels(
    labels: list[TrackIdentityLabel], predictions: list[TrackIdentityPrediction]
) -> TrackDiagnosticMetrics:
    """Compute accuracy, visible coverage, and switches only from reviewed labels."""
    if not labels:
        return TrackDiagnosticMetrics(
            available=False,
            reason="labeled_identity_frames_unavailable",
        )
    keyed_predictions = {
        (
            prediction.match_id,
            prediction.round_id,
            prediction.vod_timestamp_s,
            prediction.candidate_id,
        ): prediction.assigned_player_id
        for prediction in predictions
    }
    visible = [label for label in labels if label.visible and label.expected_player_id is not None]
    if not visible:
        return TrackDiagnosticMetrics(
            available=False,
            reason="labels_contain_no_visible_player_identities",
        )

    def prediction_for(label: TrackIdentityLabel) -> str | None:
        return keyed_predictions.get(
            (label.match_id, label.round_id, label.vod_timestamp_s, label.candidate_id)
        )

    assigned = [label for label in visible if prediction_for(label) is not None]
    correct = sum(prediction_for(label) == label.expected_player_id for label in assigned)
    by_player: dict[tuple[str, str, str], list[tuple[float, str]]] = {}
    for label in visible:
        player = prediction_for(label)
        if player is not None and label.expected_player_id is not None:
            by_player.setdefault(
                (label.match_id, label.round_id, label.expected_player_id), []
            ).append((label.vod_timestamp_s, player))
    switches = 0
    for sequence in by_player.values():
        sequence.sort()
        switches += sum(left[1] != right[1] for left, right in zip(sequence, sequence[1:]))
    return TrackDiagnosticMetrics(
        available=True,
        labeled_visible_count=len(visible),
        identity_accuracy=correct / len(assigned) if assigned else 0.0,
        visible_player_coverage=len(assigned) / len(visible),
        identity_switches=switches,
    )


def render_track_overlay(map_image: np.ndarray, rows: list[PlayerTrackArtifactRow]) -> np.ndarray:
    """Render stable player IDs at normalized canonical positions for playback."""
    if (
        not isinstance(map_image, np.ndarray)
        or map_image.dtype != np.uint8
        or map_image.ndim != 3
        or map_image.shape[2] != 3
        or map_image.shape[0] == 0
        or map_image.shape[1] == 0
    ):
        raise ValueError("map_image must be a non-empty uint8 BGR image")
    overlay = map_image.copy()
    height, width = overlay.shape[:2]
    for row in sorted(rows, key=lambda value: (value.vod_timestamp_s, value.player_id)):
        if row.x is None or row.y is None:
            continue
        point = (round(row.x * (width - 1)), round(row.y * (height - 1)))
        color = (0, 255, 0) if row.observed else (0, 165, 255)
        cv2.circle(overlay, point, 5, color, -1)
        cv2.putText(
            overlay,
            row.player_id,
            (min(point[0] + 7, width - 1), max(point[1] - 5, 9)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
    return np.asarray(overlay)


def write_track_debug_playback(
    directory: Path,
    map_image: np.ndarray,
    rows: list[PlayerTrackArtifactRow],
) -> list[Path]:
    """Write deterministic timestamped PNG frames; each frame contains only that instant."""
    if not rows:
        raise ValueError("track debug playback requires at least one row")
    match_ids = {row.match_id for row in rows}
    round_ids = {row.round_id for row in rows}
    if len(match_ids) != 1 or len(round_ids) != 1:
        raise ValueError("track debug playback rows must belong to one match and round")
    timestamps = sorted({row.vod_timestamp_s for row in rows})
    directory.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for index, timestamp in enumerate(timestamps):
        frame_rows = [row for row in rows if row.vod_timestamp_s == timestamp]
        frame = render_track_overlay(map_image, frame_rows)
        path = directory / f"frame_{index:06d}_{timestamp:012.3f}.png"
        if not cv2.imwrite(str(path), frame):
            raise OSError(f"failed to write track debug frame: {path}")
        paths.append(path)
    return paths


def _load_arrow() -> tuple[Any, Any]:
    try:
        pa = import_module("pyarrow")
        parquet = import_module("pyarrow.parquet")
    except ImportError as error:
        raise ParquetUnavailableError(
            "Parquet support requires the optional 'parquet' extra: "
            "install valoscribe[parquet] (pyarrow); no output was written"
        ) from error
    return pa, parquet
