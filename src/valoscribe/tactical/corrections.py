"""Append-only marker review and deterministic corrected occupancy rebuilds."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import uuid
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

import cv2
import numpy as np
from pydantic import BaseModel

from valoscribe.tactical.config import TacticalConfig
from valoscribe.tactical.contracts import (
    CorrectionDelta,
    MarkerAdjudication,
    ReviewedFrame,
    SourceAdjudicationMode,
)
from valoscribe.tactical.pipeline import assign_zone, load_assets, resolve_path
from valoscribe.tactical.reporting import write_round_report


def observation_id(round_id: str, sample_index: int, ordinal: int) -> str:
    return f"{round_id}:{sample_index}:{ordinal}"


def _parse_jsonl(payload: bytes, source: Path) -> list[dict[str, Any]]:
    rows = []
    for number, line in enumerate(payload.decode("utf-8").splitlines(), 1):
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid JSONL at {source}:{number}") from error
    return rows


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return _parse_jsonl(path.read_bytes(), path) if path.exists() else []


def _append_records(path: Path, records: Sequence[BaseModel]) -> None:
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(record.model_dump_json() + "\n" for record in records)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(payload)
        stream.flush()


def _point_to_canonical(config: TacticalConfig, x: float, y: float) -> tuple[float, float]:
    matrix = np.asarray(config.broadcast.transform.matrix, dtype=np.float64)
    return (
        float(matrix[0, 0] * x + matrix[0, 1] * y + matrix[0, 2]),
        float(matrix[1, 0] * x + matrix[1, 1] * y + matrix[1, 2]),
    )


def validate_delta(
    delta: CorrectionDelta,
    raw: list[dict],
    config: TacticalConfig,
    existing_deltas: list[dict[str, Any]] | None = None,
) -> None:
    if delta.run_id != config.run.run_id:
        raise ValueError("correction run_id does not match run configuration")
    round_config = next((item for item in config.rounds if item.round_id == delta.round_id), None)
    if round_config is None:
        raise ValueError(f"unknown correction round: {delta.round_id}")
    width, height = config.map.canonical_width, config.map.canonical_height
    if delta.operation in {"add", "move"}:
        x, y = delta.corrected_canonical_x, delta.corrected_canonical_y
        if x is None or y is None or not (0 <= x < width and 0 <= y < height):
            raise ValueError("corrected marker coordinates are missing or outside canonical map")
        raw_ids = {
            observation_id(delta.round_id, int(row["sample_index"]), ordinal)
            for ordinal, row in enumerate(raw)
            if row.get("round_id") == delta.round_id
        }
        historical_ids = {
            str(prior["correction_id"])
            for prior in existing_deltas or []
            if prior.get("run_id") == delta.run_id
            and prior.get("round_id") == delta.round_id
            and prior.get("operation") in {"add", "move"}
        }
        if delta.correction_id in raw_ids or delta.correction_id in historical_ids:
            raise ValueError("correction id collides with an existing observation or correction")
    if delta.operation in {"remove", "move"}:
        if not delta.target_observation_id:
            raise ValueError("remove/move correction requires a target observation id")
        available: dict[str, tuple[float | None, float | None]] = {}
        for ordinal, row in enumerate(raw):
            if row["round_id"] == delta.round_id and row["sample_index"] == delta.sample_index:
                available[observation_id(delta.round_id, delta.sample_index, ordinal)] = (
                    row.get("canonical_x"),
                    row.get("canonical_y"),
                )
        for prior in existing_deltas or []:
            if (
                prior.get("run_id") != delta.run_id
                or prior.get("round_id") != delta.round_id
                or prior.get("sample_index") != delta.sample_index
            ):
                continue
            if prior["operation"] in {"remove", "move"}:
                prior_target = prior.get("target_observation_id")
                if isinstance(prior_target, str):
                    available.pop(prior_target, None)
            if prior["operation"] in {"add", "move"}:
                available[prior["correction_id"]] = (
                    prior["corrected_canonical_x"],
                    prior["corrected_canonical_y"],
                )
        original = available.get(delta.target_observation_id)
        if original is None:
            raise ValueError("correction target observation does not exist in this frame")
        if delta.original_canonical_x is None or delta.original_canonical_y is None:
            raise ValueError("remove/move correction requires original coordinates")
        if original[0] is None or original[1] is None:
            raise ValueError("target observation has no canonical position")
        original_x = delta.original_canonical_x
        original_y = delta.original_canonical_y
        if original_x is None or original_y is None:
            raise ValueError("remove/move correction requires original coordinates")
        if not np.allclose(
            [float(original[0]), float(original[1])],
            [original_x, original_y],
            atol=1e-6,
        ):
            raise ValueError("correction original position does not match current observation")


def _valid_canonical_position(row: dict[str, Any], config: TacticalConfig) -> bool:
    x, y = row.get("canonical_x"), row.get("canonical_y")
    return (
        isinstance(x, (int, float))
        and isinstance(y, (int, float))
        and math.isfinite(float(x))
        and math.isfinite(float(y))
        and 0 <= float(x) < config.map.canonical_width
        and 0 <= float(y) < config.map.canonical_height
    )


def validate_adjudication(
    adjudication: MarkerAdjudication,
    raw: list[dict[str, Any]],
    coverage: list[dict[str, Any]],
    config: TacticalConfig,
    existing: list[dict[str, Any]],
    corrections: list[dict[str, Any]] | None = None,
) -> None:
    if adjudication.run_id != config.run.run_id:
        raise ValueError("adjudication run_id does not match run configuration")
    if not any(item.round_id == adjudication.round_id for item in config.rounds):
        raise ValueError(f"unknown adjudication round: {adjudication.round_id}")
    if any(row.get("adjudication_id") == adjudication.adjudication_id for row in existing):
        raise ValueError(f"duplicate adjudication id: {adjudication.adjudication_id}")
    frame = next(
        (row for row in coverage if int(row["sample_index"]) == adjudication.sample_index), None
    )
    if frame is None:
        raise ValueError("adjudication sample has no frame evidence")
    if abs(float(frame["source_timestamp_seconds"]) - adjudication.source_timestamp_seconds) > 1e-6:
        raise ValueError("adjudication source timestamp does not match sampled frame")
    if frame.get("coverage_status") == "excluded":
        raise ValueError("excluded frames cannot receive marker adjudications")
    target_ids = {
        observation_id(adjudication.round_id, adjudication.sample_index, ordinal)
        for ordinal, row in enumerate(raw)
        if row.get("round_id") == adjudication.round_id
        and int(row.get("sample_index", -1)) == adjudication.sample_index
    }
    for correction in corrections or []:
        if (
            correction.get("round_id") != adjudication.round_id
            or int(correction.get("sample_index", -1)) != adjudication.sample_index
        ):
            continue
        if correction.get("operation") in {"remove", "move"}:
            target_ids.discard(str(correction.get("target_observation_id")))
        if correction.get("operation") in {"add", "move"}:
            target_ids.add(str(correction["correction_id"]))
    if adjudication.target_observation_id not in target_ids:
        raise ValueError("adjudication target observation does not exist in this frame")
    if adjudication.source_frame_index is not None:
        target = next(
            (
                row
                for ordinal, row in enumerate(raw)
                if observation_id(adjudication.round_id, adjudication.sample_index, ordinal)
                == adjudication.target_observation_id
            ),
            None,
        )
        if (
            target is not None
            and target.get("source_frame_index") != adjudication.source_frame_index
        ):
            raise ValueError("adjudication source frame does not match target observation")


def _activate_source_adjudication_mode(run_dir: Path, run_id: str, round_id: str) -> bytes:
    mode_path = run_dir / "source_adjudication_mode.json"
    previous = mode_path.read_bytes() if mode_path.exists() else b""
    if previous:
        mode = SourceAdjudicationMode.model_validate_json(previous)
        if mode.run_id != run_id:
            raise ValueError("source-adjudication mode run_id does not match run configuration")
        round_ids = set(mode.round_ids)
    else:
        round_ids = set()
    round_ids.add(round_id)
    updated = SourceAdjudicationMode(run_id=run_id, round_ids=tuple(sorted(round_ids)))
    temporary = mode_path.with_name(f".{mode_path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(updated.model_dump_json(indent=2) + "\n", encoding="utf-8")
    temporary.replace(mode_path)
    return mode_path.read_bytes()


def append_adjudications(
    round_dir: Path,
    adjudications: Sequence[MarkerAdjudication],
    config: TacticalConfig,
    round_id: str,
) -> None:
    if not any(item.round_id == round_id for item in config.rounds):
        raise ValueError(f"unknown adjudication round: {round_id}")
    if not round_dir.is_dir():
        raise ValueError(f"round directory does not exist: {round_id}")
    raw = _read_jsonl(round_dir / "raw_observations.jsonl")
    coverage = _read_jsonl(round_dir / "sample_coverage.jsonl")
    corrections = _read_jsonl(round_dir / "corrections.jsonl")
    path = round_dir / "marker_adjudications.jsonl"
    history = _read_jsonl(path)
    for item in adjudications:
        if item.round_id != round_id:
            raise ValueError("adjudication round_id does not match command round")
        validate_adjudication(item, raw, coverage, config, history, corrections)
        history.append(item.model_dump(mode="json"))
    _activate_source_adjudication_mode(round_dir.parent.parent, config.run.run_id, round_id)
    path.touch(exist_ok=True)
    _append_records(path, adjudications)


def corrected_rows(
    round_dir: Path,
    round_id: str,
    config: TacticalConfig,
    correction_history: list[dict[str, Any]] | None = None,
    review_history: list[dict[str, Any]] | None = None,
    raw_history: list[dict[str, Any]] | None = None,
    adjudication_history: list[dict[str, Any]] | None = None,
    coverage_history: list[dict[str, Any]] | None = None,
) -> tuple[list[dict], set[int]]:
    run_id = config.run.run_id
    raw = (
        raw_history
        if raw_history is not None
        else _read_jsonl(round_dir / "raw_observations.jsonl")
    )
    coverage = (
        coverage_history
        if coverage_history is not None
        else _read_jsonl(round_dir / "sample_coverage.jsonl")
    )
    timestamps = {
        int(row["sample_index"]): float(row["source_timestamp_seconds"]) for row in coverage
    }
    correction_records = (
        correction_history
        if correction_history is not None
        else _read_jsonl(round_dir / "corrections.jsonl")
    )
    corrections = [CorrectionDelta.model_validate(row) for row in correction_records]
    if not coverage:
        raise ValueError(f"sample frame evidence is missing for {round_id}")
    sample_indices = set(timestamps)
    if any(delta.run_id != run_id or delta.round_id != round_id for delta in corrections):
        raise ValueError("correction run_id/round_id does not match its run directory")
    if any(delta.sample_index not in sample_indices for delta in corrections):
        raise ValueError("correction refers to a sample with no sampled frame evidence")
    history: list[dict[str, Any]] = []
    for delta in corrections:
        validate_delta(delta, raw, config, history)
        history.append(delta.model_dump(mode="json"))
    review_records = (
        review_history
        if review_history is not None
        else _read_jsonl(round_dir / "reviewed_frames.jsonl")
    )
    adjudication_path = round_dir / "marker_adjudications.jsonl"
    adjudication_mode = adjudication_history is not None or adjudication_path.exists()
    adjudication_records = (
        adjudication_history if adjudication_history is not None else _read_jsonl(adjudication_path)
    )
    adjudications = [MarkerAdjudication.model_validate(row) for row in adjudication_records]
    known_ids = {
        observation_id(round_id, int(row["sample_index"]), ordinal): int(row["sample_index"])
        for ordinal, row in enumerate(raw)
        if row.get("round_id") == round_id
    }
    known_ids.update(
        {
            str(delta.correction_id): delta.sample_index
            for delta in corrections
            if delta.operation in {"add", "move"}
        }
    )
    effective_adjudications: dict[str, MarkerAdjudication] = {}
    seen_ids: set[str] = set()
    for adjudication in adjudications:
        if adjudication.run_id != run_id or adjudication.round_id != round_id:
            raise ValueError("adjudication run_id/round_id does not match its run directory")
        if adjudication.sample_index not in sample_indices:
            raise ValueError("adjudication refers to a sample with no sampled frame evidence")
        if adjudication.adjudication_id in seen_ids:
            raise ValueError(f"duplicate adjudication id: {adjudication.adjudication_id}")
        seen_ids.add(adjudication.adjudication_id)
        if (
            abs(timestamps[adjudication.sample_index] - adjudication.source_timestamp_seconds)
            > 1e-6
        ):
            raise ValueError("adjudication source timestamp does not match sampled frame")
        frame_evidence = next(
            row for row in coverage if int(row["sample_index"]) == adjudication.sample_index
        )
        if frame_evidence.get("coverage_status") == "excluded":
            raise ValueError("excluded frames cannot receive marker adjudications")
        if adjudication.source_frame_index is not None:
            raw_target = next(
                (
                    raw_row
                    for ordinal, raw_row in enumerate(raw)
                    if observation_id(round_id, int(raw_row["sample_index"]), ordinal)
                    == adjudication.target_observation_id
                ),
                None,
            )
            if (
                raw_target is not None
                and raw_target.get("source_frame_index") != adjudication.source_frame_index
            ):
                raise ValueError("adjudication source frame does not match target observation")
        if known_ids.get(adjudication.target_observation_id) != adjudication.sample_index:
            raise ValueError("adjudication target observation does not exist in this frame")
        effective_adjudications[adjudication.target_observation_id] = adjudication
    reviewed = [ReviewedFrame.model_validate(row) for row in review_records]
    if any(item.run_id != run_id or item.round_id != round_id for item in reviewed):
        raise ValueError("review record run_id/round_id does not match its run directory")
    if any(item.sample_index not in sample_indices for item in reviewed):
        raise ValueError("review record refers to a sample with no frame evidence")
    rows: list[dict] = []
    for ordinal, raw_row in enumerate(raw):
        if raw_row["round_id"] != round_id:
            continue
        raw_item = dict(raw_row)
        raw_item["observation_id"] = observation_id(round_id, raw_item["sample_index"], ordinal)
        raw_item["source"] = "raw"
        rows.append(raw_item)
    for delta in corrections:
        if delta.run_id != run_id or delta.round_id != round_id:
            continue
        if delta.operation in {"remove", "move"}:
            target = next(
                (item for item in rows if item["observation_id"] == delta.target_observation_id),
                None,
            )
            if target is None or target["sample_index"] != delta.sample_index:
                raise ValueError(
                    f"correction target missing from sample {delta.sample_index}: "
                    f"{delta.target_observation_id}"
                )
            current_x, current_y = target.get("canonical_x"), target.get("canonical_y")
            if current_x is None or current_y is None:
                raise ValueError("correction target has no canonical position")
            original_x = delta.original_canonical_x
            original_y = delta.original_canonical_y
            if original_x is None or original_y is None:
                raise ValueError("remove/move correction lacks original coordinates")
            if not np.allclose(
                [float(current_x), float(current_y)], [original_x, original_y], atol=1e-6
            ):
                raise ValueError("correction chain original position mismatch")
            rows.remove(target)
        if delta.operation in {"add", "move"}:
            rows.append(
                {
                    "run_id": run_id,
                    "round_id": round_id,
                    "sample_index": delta.sample_index,
                    "source_timestamp_seconds": timestamps.get(delta.sample_index),
                    "canonical_x": delta.corrected_canonical_x,
                    "canonical_y": delta.corrected_canonical_y,
                    "confidence": delta.confidence,
                    "observation_id": delta.correction_id,
                    "source": "corrected",
                }
            )
    if any(row["source_timestamp_seconds"] is None for row in rows):
        raise ValueError("correction refers to a sample with no sampled frame evidence")
    coverage_by_sample = {int(frame["sample_index"]): frame for frame in coverage}
    latest_review_by_sample = {
        item.sample_index: item
        for item in reviewed
        if item.run_id == run_id and item.round_id == round_id
    }
    approved_samples: set[int] = set()
    for reviewed_item in latest_review_by_sample.values():
        if (
            not reviewed_item.approved
            or reviewed_item.run_id != run_id
            or reviewed_item.round_id != round_id
        ):
            continue
        frame = coverage_by_sample[reviewed_item.sample_index]
        if frame["coverage_status"] not in {"good", "partial"}:
            raise ValueError("only good or partial frames can be explicitly approved")
        if any(
            not _valid_canonical_position(row, config)
            for row in rows
            if int(row["sample_index"]) == reviewed_item.sample_index
        ):
            raise ValueError(
                "cannot approve a frame with observations missing canonical coordinates"
            )
        approved_samples.add(reviewed_item.sample_index)
    for row in rows:
        effective_adjudication = effective_adjudications.get(row["observation_id"])
        row["source_adjudication_mode"] = adjudication_mode
        row["adjudication_disposition"] = (
            effective_adjudication.disposition if effective_adjudication else None
        )
        row["adjudication_evidence"] = (
            effective_adjudication.model_dump(mode="json") if effective_adjudication else None
        )
        row["tactical_eligible"] = (
            (
                not adjudication_mode
                or int(row["sample_index"]) in approved_samples
                or bool(
                    effective_adjudication
                    and effective_adjudication.disposition == "supported"
                )
            )
            and (not adjudication_mode or _valid_canonical_position(row, config))
        )
    return rows, approved_samples


def _effective_coverage(
    frame: dict[str, Any],
    observations: list[dict[str, Any]],
    approved_samples: set[int],
    *,
    source_adjudication_mode: bool = False,
    eligible_count: int | None = None,
) -> tuple[str, list[str]]:
    points = [
        obs
        for obs in observations
        if obs.get("canonical_x") is not None and obs.get("canonical_y") is not None
    ]
    unavailable = len(observations) - len(points)
    sample = int(frame["sample_index"])
    status = (
        "excluded"
        if frame["coverage_status"] == "excluded"
        else "unknown"
        if source_adjudication_mode and sample not in approved_samples and not eligible_count
        else "partial"
        if source_adjudication_mode and sample not in approved_samples
        else "good"
        if sample in approved_samples
        else "unknown"
        if unavailable and not points
        else "partial"
        if unavailable
        else frame["coverage_status"]
    )
    warnings = [frame["warning"]] if frame.get("warning") else []
    if unavailable:
        warnings.append(f"{unavailable} observation(s) lack canonical coordinates")
    if source_adjudication_mode:
        warnings.append(
            "tactical evidence uses source-supported markers or whole-frame-approved observations"
        )
    if sample not in approved_samples and frame["coverage_status"] != "excluded" and not warnings:
        warnings.append("frame not explicitly approved")
    return status, warnings


CAPTION_STRIP_HEIGHT = 224


def _caption_lines(
    width: int, lines: list[str], *, scale: float, strip_height: int
) -> list[str]:
    """Wrap caption text to the actual frame width instead of clipping it."""
    width -= 12
    font = cv2.FONT_HERSHEY_SIMPLEX
    wrapped: list[str] = []
    for text in lines:
        words = text.split()
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if cv2.getTextSize(candidate, font, scale, 1)[0][0] <= width:
                current = candidate
                continue
            if current:
                wrapped.append(current)
                current = ""
            fragment = ""
            for character in word:
                candidate = fragment + character
                if fragment and cv2.getTextSize(candidate, font, scale, 1)[0][0] > width:
                    wrapped.append(fragment)
                    fragment = character
                else:
                    fragment = candidate
            current = fragment
        if current:
            wrapped.append(current)
    line_height = max(cv2.getTextSize("Ag", font, scale, 1)[0][1] + 4, 10)
    if len(wrapped) * line_height + 8 > strip_height:
        raise ValueError("playback captions exceed the fixed caption strip")
    return wrapped


def _caption_frame(
    image: np.ndarray,
    lines: list[str],
    *,
    scale: float,
    phase_lines: list[str] | None = None,
) -> np.ndarray:
    """Add a fixed caption strip without painting over source or map pixels."""
    phase_labels = [f"phase: {line}" for line in (phase_lines or [])]
    regular = _caption_lines(
        image.shape[1], lines, scale=scale, strip_height=CAPTION_STRIP_HEIGHT
    )
    phases = _caption_lines(
        image.shape[1], phase_labels, scale=scale, strip_height=CAPTION_STRIP_HEIGHT
    )
    font = cv2.FONT_HERSHEY_SIMPLEX
    line_height = max(cv2.getTextSize("Ag", font, scale, 1)[0][1] + 4, 10)
    if (len(regular) + len(phases)) * line_height + 8 > CAPTION_STRIP_HEIGHT:
        raise ValueError("playback captions and phase annotations exceed the fixed caption strip")
    strip = np.zeros((CAPTION_STRIP_HEIGHT, image.shape[1], 3), dtype=image.dtype)
    for index, text in enumerate(regular + phases):
        color = (0, 255, 255) if index >= len(regular) else (255, 255, 255)
        cv2.putText(
            strip,
            text,
            (6, 4 + (index + 1) * line_height - 2),
            font,
            scale,
            color,
            1,
        )
    return np.concatenate((strip, image), axis=0)


def _write_playbacks(
    run_dir: Path,
    round_id: str,
    round_dir: Path,
    config: TacticalConfig,
    asset: np.ndarray,
    map_data: dict,
    canonical_by_sample: dict[int, list[dict]],
    coverage: list[dict],
    approved_samples: set[int],
    corrected_samples: set[int] | None = None,
    summary=None,
    source_adjudication_mode: bool = False,
) -> None:
    source = resolve_path(config.source.video_path)
    crop = config.broadcast.minimap_crop
    matrix = np.asarray(config.broadcast.transform.matrix, dtype=np.float64)
    zone_frame = asset.copy()
    for zone in map_data["zones"]:
        vertices = np.asarray(zone["vertices_px"], dtype=np.int32)
        polygon = vertices.reshape((-1, 1, 2))
        cv2.polylines(zone_frame, [polygon], True, (255, 150, 40), 2)
        label_position = tuple(np.rint(vertices.mean(axis=0)).astype(int))
        cv2.putText(
            zone_frame,
            str(zone.get("name", zone["zone_id"])),
            label_position,
            cv2.FONT_HERSHEY_SIMPLEX,
            0.38,
            (255, 255, 255),
            1,
        )
    mini_path = round_dir / "corrected_minimap.mp4"
    canonical_path = round_dir / "corrected_canonical.mp4"
    mini_writer = cv2.VideoWriter(
        str(mini_path),
        cv2.VideoWriter.fourcc(*"mp4v"),
        config.run.sample_fps,
        (crop.width, crop.height + CAPTION_STRIP_HEIGHT),
    )
    map_writer = cv2.VideoWriter(
        str(canonical_path),
        cv2.VideoWriter.fourcc(*"mp4v"),
        config.run.sample_fps,
        (asset.shape[1], asset.shape[0] + CAPTION_STRIP_HEIGHT),
    )
    cap = cv2.VideoCapture(str(source))
    if not mini_writer.isOpened() or not map_writer.isOpened() or not cap.isOpened():
        mini_writer.release()
        map_writer.release()
        cap.release()
        raise ValueError("cannot open source or corrected playback writers")
    try:
        for frame in coverage:
            timestamp = float(frame["source_timestamp_seconds"])
            cap.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
            ok, image = cap.read()
            if not ok or image is None:
                raise ValueError(f"source frame unavailable at {timestamp:.3f}s")
            minimap = image[crop.y : crop.y + crop.height, crop.x : crop.x + crop.width].copy()
            map_image = zone_frame.copy()
            sample_observations = canonical_by_sample.get(int(frame["sample_index"]), [])
            source_mode = source_adjudication_mode
            status, warnings = _effective_coverage(
                frame,
                sample_observations,
                approved_samples,
                source_adjudication_mode=source_mode,
                eligible_count=sum(
                    bool(item.get("tactical_eligible")) for item in sample_observations
                ),
            )
            macro_counts: Counter[str] = Counter()
            current_zone_names: set[str] = set()
            for obs in canonical_by_sample.get(frame["sample_index"], []):
                if obs.get("canonical_x") is None or obs.get("canonical_y") is None:
                    continue
                x, y = float(obs["canonical_x"]), float(obs["canonical_y"])
                p = (round(x), round(y))
                confidence = float(obs.get("confidence", 1.0))
                zone_id, macro = assign_zone(x, y, map_data)
                eligible = bool(obs.get("tactical_eligible", True))
                if eligible:
                    macro_counts[macro] += 1
                if eligible and zone_id != "unknown":
                    current_zone_names.add(
                        next(
                            (
                                str(zone.get("name", zone["zone_id"]))
                                for zone in map_data["zones"]
                                if zone["zone_id"] == zone_id
                            ),
                            zone_id,
                        )
                    )
                marker_color = (0, 255, 0) if eligible else (0, 165, 255)
                cv2.circle(map_image, p, 8, marker_color, 2)
                source_point = np.linalg.solve(matrix[:, :2], np.array([x, y]) - matrix[:, 2])
                minimap_point = (round(float(source_point[0])), round(float(source_point[1])))
                point_is_in_minimap = (
                    0 <= minimap_point[0] < minimap.shape[1]
                    and 0 <= minimap_point[1] < minimap.shape[0]
                )
                if point_is_in_minimap:
                    cv2.circle(minimap, minimap_point, 7, marker_color, 2)
                    cv2.putText(
                        minimap,
                        f"{confidence:.2f}",
                        minimap_point,
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.32,
                        (255, 255, 255),
                        1,
                    )
            sample_observations = canonical_by_sample.get(int(frame["sample_index"]), [])
            source_state = (
                "CORRECTED"
                if int(frame["sample_index"]) in (corrected_samples or set())
                or any(item.get("source") == "corrected" for item in sample_observations)
                else "REVIEWED"
                if int(frame["sample_index"]) in approved_samples
                else "RAW"
            )
            eligible_count = sum(
                bool(item.get("tactical_eligible", True)) for item in sample_observations
            )
            candidate_count = sum(
                item.get("canonical_x") is not None and item.get("canonical_y") is not None
                for item in sample_observations
            )
            eligibility_label = "eligible evidence" if source_mode else "candidate markers"
            playback_caption = [
                f"team: {config.team.short_name} | side: {config.team.side}",
                f"round: {round_id}",
                f"source: {timestamp:.2f}s | state: {source_state} | coverage: {status}",
                f"markers: eligible={eligible_count} candidates={candidate_count}",
                f"zones: {', '.join(sorted(current_zone_names)) or 'none'}",
                f"legend: green={eligibility_label}; orange=deferred/unreviewed candidate",
            ]
            playback_caption.extend(f"warning: {warning}" for warning in warnings)
            minimap_frame = _caption_frame(minimap, playback_caption, scale=0.31)
            phase_annotations = []
            if (
                summary
                and summary.first_major_shift_evidence
                and summary.first_major_shift_evidence["after"]["sample_index"]
                == frame["sample_index"]
            ):
                phase_annotations.append(
                    f"observed shift toward {summary.first_major_shift_direction}"
                )
            if (
                summary
                and summary.commitment_evidence
                and summary.commitment_evidence["sample"]["sample_index"] == frame["sample_index"]
            ):
                phase_annotations.append(f"apparent {summary.apparent_commitment_site} commitment")
            macro_text = "A={} MID={} B={}".format(
                macro_counts["A"], macro_counts["MID"], macro_counts["B"]
            )
            canonical_caption = playback_caption + [f"macro counts: {macro_text}"]
            map_frame = _caption_frame(
                map_image, canonical_caption, scale=0.45, phase_lines=phase_annotations
            )
            mini_writer.write(minimap_frame)
            map_writer.write(map_frame)
    finally:
        cap.release()
        mini_writer.release()
        map_writer.release()


def rebuild_round(run_dir: Path, round_id: str, config: TacticalConfig) -> dict[str, Any]:
    round_dir = run_dir / "rounds" / round_id
    if not round_dir.is_dir():
        raise ValueError(f"round directory does not exist: {round_id}")
    raw_path = round_dir / "raw_observations.jsonl"
    if not raw_path.is_file():
        raise ValueError(f"raw observations are missing for {round_id}")
    raw_snapshot = raw_path.read_bytes()
    corrections_path = round_dir / "corrections.jsonl"
    corrections_snapshot = corrections_path.read_bytes() if corrections_path.exists() else b""
    reviews_path = round_dir / "reviewed_frames.jsonl"
    reviews_snapshot = reviews_path.read_bytes() if reviews_path.exists() else b""
    raw_history = _parse_jsonl(raw_snapshot, raw_path)
    correction_history = _parse_jsonl(corrections_snapshot, corrections_path)
    review_history = _parse_jsonl(reviews_snapshot, reviews_path)
    mode_path = run_dir / "source_adjudication_mode.json"
    mode_snapshot = mode_path.read_bytes() if mode_path.exists() else b""
    source_mode_manifest = (
        SourceAdjudicationMode.model_validate_json(mode_snapshot)
        if mode_snapshot
        else SourceAdjudicationMode(run_id=config.run.run_id)
    )
    if source_mode_manifest.run_id != config.run.run_id:
        raise ValueError("source-adjudication mode run_id does not match run configuration")
    configured_round_ids = {item.round_id for item in config.rounds}
    if not set(source_mode_manifest.round_ids) <= configured_round_ids:
        raise ValueError("source-adjudication mode contains an unknown round")
    source_mode_required = round_id in source_mode_manifest.round_ids
    adjudications_path = round_dir / "marker_adjudications.jsonl"
    adjudication_sidecar_exists = adjudications_path.exists()
    if source_mode_required and not adjudication_sidecar_exists:
        raise ValueError("source-adjudicated round is missing its adjudication sidecar")
    adjudications_snapshot = (
        adjudications_path.read_bytes() if adjudication_sidecar_exists else b""
    )
    adjudication_history = _parse_jsonl(adjudications_snapshot, adjudications_path)
    coverage_path = round_dir / "sample_coverage.jsonl"
    coverage_snapshot = coverage_path.read_bytes()
    coverage_history = _parse_jsonl(coverage_snapshot, coverage_path)
    corrected_samples = {int(row["sample_index"]) for row in correction_history}
    rows, approved_samples = corrected_rows(
        round_dir,
        round_id,
        config,
        correction_history=correction_history,
        review_history=review_history,
        raw_history=raw_history,
        adjudication_history=adjudication_history if adjudication_sidecar_exists else None,
        coverage_history=coverage_history,
    )
    revision_root = round_dir / "derived"
    revision_root.mkdir(exist_ok=True)
    numbers = [int(item.name.split("-")[-1]) for item in revision_root.glob("revision-*")]
    revision = max(numbers, default=0) + 1
    final_output = revision_root / f"revision-{revision:03d}"
    output = revision_root / f".revision-{revision:03d}-{uuid.uuid4().hex}.tmp"
    output.mkdir()
    coverage = coverage_history
    _, _, map_data, asset, _ = load_assets(config)
    by_sample: dict[int, list[dict]] = {}
    for row in rows:
        by_sample.setdefault(int(row["sample_index"]), []).append(row)
    grouped: dict[int, list[dict]] = {}
    for row in coverage:
        grouped[int(row["sample_index"])] = []
    for row in rows:
        grouped.setdefault(int(row["sample_index"]), []).append(row)
    occupancy: list[dict[str, Any]] = []
    for frame in coverage:
        sample = int(frame["sample_index"])
        candidate_observations = grouped.get(sample, [])
        round_source_mode = adjudication_sidecar_exists or source_mode_required
        observations = [
            item
            for item in candidate_observations
            if item.get("tactical_eligible", True)
            and (
                not round_source_mode
                or _valid_canonical_position(item, config)
            )
        ]
        zone_counts: Counter[str] = Counter()
        macro_counts: Counter[str] = Counter()
        points: list[tuple[float, float]] = []
        for obs in observations:
            x, y = obs.get("canonical_x"), obs.get("canonical_y")
            if x is None or y is None:
                continue
            zone, macro = assign_zone(float(x), float(y), map_data)
            zone_counts[zone] += 1
            macro_counts[macro] += 1
            points.append((float(x), float(y)))
        centroid = (
            [float(np.mean([p[0] for p in points])), float(np.mean([p[1] for p in points]))]
            if points
            else None
        )
        spread = (
            float(np.sqrt(np.mean([np.sum((np.asarray(p) - centroid) ** 2) for p in points])))
            if points
            else None
        )
        status, warnings = _effective_coverage(
            frame,
            candidate_observations,
            approved_samples,
            source_adjudication_mode=round_source_mode,
            eligible_count=len(observations),
        )
        occupancy.append(
            {
                "run_id": config.run.run_id,
                "round_id": round_id,
                "sample_index": sample,
                "source_timestamp_seconds": frame["source_timestamp_seconds"],
                "observed_marker_count": len(observations),
                "candidate_observed_marker_count": len(candidate_observations),
                "source_adjudication_mode": round_source_mode,
                "tactical_eligible_observation_ids": [
                    item["observation_id"] for item in observations
                ],
                "source_supported_observation_ids": [
                    item["observation_id"]
                    for item in observations
                    if item.get("adjudication_disposition") == "supported"
                ],
                "whole_frame_approved": sample in approved_samples,
                "adjudication_evidence": [
                    item["adjudication_evidence"]
                    for item in observations
                    if item.get("adjudication_evidence")
                ],
                "zone_counts": {
                    zone_id: zone_counts[zone_id]
                    for zone_id in [zone["zone_id"] for zone in map_data["zones"]] + ["unknown"]
                },
                "macro_counts": {
                    key: macro_counts[key] for key in ("A", "MID", "B", "SPAWN", "OTHER")
                },
                "centroid_x": centroid[0] if centroid else None,
                "centroid_y": centroid[1] if centroid else None,
                "spread": spread,
                "coverage_status": status,
                "warnings": warnings,
                "corrected": sample in corrected_samples,
            }
        )
    corrected_path = output / "corrected_observations.jsonl"
    with corrected_path.open("w", encoding="utf-8") as stream:
        for row in sorted(rows, key=lambda x: (x["sample_index"], x["observation_id"])):
            stream.write(json.dumps(row, separators=(",", ":"), allow_nan=False) + "\n")
    (output / "marker_adjudications.jsonl").write_bytes(adjudications_snapshot)
    (output / "source_adjudication_mode.json").write_bytes(mode_snapshot)
    csv_path = output / "occupancy.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=list(occupancy[0]) if occupancy else ["round_id"]
        )
        writer.writeheader()
        for row in occupancy:
            writer.writerow(
                {
                    k: json.dumps(v, separators=(",", ":")) if isinstance(v, (dict, list)) else v
                    for k, v in row.items()
                }
            )
    try:
        import pyarrow as pa  # type: ignore[import-untyped]
        import pyarrow.parquet as pq  # type: ignore[import-untyped]
    except ImportError as error:
        raise ImportError(
            "occupancy.parquet requires the project's parquet extra (uv sync --extra parquet)"
        ) from error
    pq.write_table(pa.Table.from_pylist(occupancy), output / "occupancy.parquet")
    round_config = next(item for item in config.rounds if item.round_id == round_id)
    summary = write_round_report(
        round_dir,
        round_id,
        round_config,
        config,
        occupancy,
        map_data,
        report_root=output,
        evidence_paths={
            "minimap_playback": "corrected_minimap.mp4",
            "canonical_playback": "corrected_canonical.mp4",
        },
    )
    _write_playbacks(
        run_dir,
        round_id,
        output,
        config,
        asset,
        map_data,
        by_sample,
        coverage,
        approved_samples,
        corrected_samples,
        summary,
        adjudication_sidecar_exists or source_mode_required,
    )
    manifest = {
        "revision": revision,
        "round_id": round_id,
        "raw_observations_sha256": hashlib.sha256(raw_snapshot).hexdigest(),
        "sample_coverage_sha256": hashlib.sha256(coverage_snapshot).hexdigest(),
        "corrections_sha256": hashlib.sha256(corrections_snapshot).hexdigest(),
        "reviewed_frames_sha256": hashlib.sha256(reviews_snapshot).hexdigest(),
        "marker_adjudications_sha256": hashlib.sha256(adjudications_snapshot).hexdigest(),
        "source_adjudication_mode_sha256": hashlib.sha256(mode_snapshot).hexdigest(),
        "source_adjudication_mode": adjudication_sidecar_exists or source_mode_required,
        "adjudication_count": len(adjudication_history),
        "correction_count": len(correction_history),
        "reviewed_frame_count": len({int(row["sample_index"]) for row in review_history}),
        "frame_count": len(occupancy),
        "detector_invoked": False,
        "artifacts": [
            "corrected_observations.jsonl",
            "marker_adjudications.jsonl",
            "source_adjudication_mode.json",
            "occupancy.csv",
            "occupancy.parquet",
            "corrected_minimap.mp4",
            "corrected_canonical.mp4",
            "summary.json",
            "summary.md",
        ],
    }
    (output / "revision.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    output.rename(final_output)
    return {"revision_directory": str(final_output), **manifest}
