"""Append-only marker review and deterministic corrected occupancy rebuilds."""

from __future__ import annotations

import csv
import hashlib
import json
import uuid
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

import cv2
import numpy as np
from pydantic import BaseModel

from valoscribe.tactical.config import TacticalConfig
from valoscribe.tactical.contracts import CorrectionDelta, ReviewedFrame
from valoscribe.tactical.pipeline import assign_zone, load_assets, resolve_path
from valoscribe.tactical.reporting import write_round_report


def observation_id(round_id: str, sample_index: int, ordinal: int) -> str:
    return f"{round_id}:{sample_index}:{ordinal}"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid JSONL at {path}:{number}") from error
    return rows


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


def corrected_rows(
    round_dir: Path,
    round_id: str,
    config: TacticalConfig,
    correction_history: list[dict[str, Any]] | None = None,
    review_history: list[dict[str, Any]] | None = None,
) -> tuple[list[dict], set[int]]:
    run_id = config.run.run_id
    raw = _read_jsonl(round_dir / "raw_observations.jsonl")
    coverage = _read_jsonl(round_dir / "sample_coverage.jsonl")
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
    reviewed = [ReviewedFrame.model_validate(row) for row in review_records]
    if any(item.run_id != run_id or item.round_id != round_id for item in reviewed):
        raise ValueError("review record run_id/round_id does not match its run directory")
    if any(item.sample_index not in sample_indices for item in reviewed):
        raise ValueError("review record refers to a sample with no frame evidence")
    rows: list[dict] = []
    for ordinal, raw_row in enumerate(raw):
        if raw_row["round_id"] != round_id:
            continue
        item = dict(raw_row)
        item["observation_id"] = observation_id(round_id, item["sample_index"], ordinal)
        item["source"] = "raw"
        rows.append(item)
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
            row.get("canonical_x") is None or row.get("canonical_y") is None
            for row in rows
            if int(row["sample_index"]) == reviewed_item.sample_index
        ):
            raise ValueError(
                "cannot approve a frame with observations missing canonical coordinates"
            )
        approved_samples.add(reviewed_item.sample_index)
    return rows, approved_samples


def _effective_coverage(
    frame: dict[str, Any],
    observations: list[dict[str, Any]],
    approved_samples: set[int],
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
    if sample not in approved_samples and frame["coverage_status"] != "excluded" and not warnings:
        warnings.append("frame not explicitly approved")
    return status, warnings


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
    summary=None,
) -> None:
    source = resolve_path(config.source.video_path)
    crop = config.broadcast.minimap_crop
    matrix = np.asarray(config.broadcast.transform.matrix, dtype=np.float64)
    zone_frame = asset.copy()
    for zone in map_data["zones"]:
        polygon = np.asarray(zone["vertices_px"], dtype=np.int32).reshape((-1, 1, 2))
        cv2.polylines(zone_frame, [polygon], True, (255, 150, 40), 2)
    mini_path = round_dir / "corrected_minimap.mp4"
    canonical_path = round_dir / "corrected_canonical.mp4"
    mini_writer = cv2.VideoWriter(
        str(mini_path),
        cv2.VideoWriter.fourcc(*"mp4v"),
        config.run.sample_fps,
        (crop.width, crop.height),
    )
    map_writer = cv2.VideoWriter(
        str(canonical_path),
        cv2.VideoWriter.fourcc(*"mp4v"),
        config.run.sample_fps,
        (asset.shape[1], asset.shape[0]),
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
            status, warnings = _effective_coverage(
                frame,
                canonical_by_sample.get(int(frame["sample_index"]), []),
                approved_samples,
            )
            warning_text = f" warnings={'; '.join(warnings)}" if warnings else ""
            macro_counts: Counter[str] = Counter()
            for obs in canonical_by_sample.get(frame["sample_index"], []):
                if obs.get("canonical_x") is None or obs.get("canonical_y") is None:
                    continue
                x, y = float(obs["canonical_x"]), float(obs["canonical_y"])
                p = (round(x), round(y))
                confidence = float(obs.get("confidence", 1.0))
                _zone_id, macro = assign_zone(x, y, map_data)
                macro_counts[macro] += 1
                cv2.circle(map_image, p, 8, (0, 255, 255), 2)
                source_point = np.linalg.solve(matrix[:, :2], np.array([x, y]) - matrix[:, 2])
                minimap_point = (round(float(source_point[0])), round(float(source_point[1])))
                cv2.circle(minimap, minimap_point, 7, (0, 255, 0), 2)
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
                if any(item.get("source") == "corrected" for item in sample_observations)
                else "REVIEWED"
                if int(frame["sample_index"]) in approved_samples
                else "RAW"
            )
            minimap_caption = (
                f"{config.team.short_name} {config.team.side} {round_id} "
                f"{timestamp:.2f}s {source_state} coverage={status}{warning_text}"
            )
            cv2.putText(
                minimap,
                minimap_caption,
                (4, 14),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.4,
                (255, 255, 255),
                1,
            )
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
            canonical_caption = (
                f"{config.team.short_name} {config.team.side} | {timestamp:.2f}s | "
                f"{macro_text} | {source_state} coverage={status}{warning_text}"
            )
            cv2.putText(
                map_image,
                canonical_caption,
                (20, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 255),
                2,
            )
            for index, annotation in enumerate(phase_annotations):
                cv2.putText(
                    map_image,
                    annotation,
                    (20, 60 + index * 25),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 255, 255),
                    2,
                )
            mini_writer.write(minimap)
            map_writer.write(map_image)
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
    revision_root = round_dir / "derived"
    revision_root.mkdir(exist_ok=True)
    numbers = [int(item.name.split("-")[-1]) for item in revision_root.glob("revision-*")]
    revision = max(numbers, default=0) + 1
    final_output = revision_root / f"revision-{revision:03d}"
    output = revision_root / f".revision-{revision:03d}-{uuid.uuid4().hex}.tmp"
    output.mkdir()
    correction_history = _read_jsonl(round_dir / "corrections.jsonl")
    review_history = _read_jsonl(round_dir / "reviewed_frames.jsonl")
    rows, approved_samples = corrected_rows(
        round_dir,
        round_id,
        config,
        correction_history=correction_history,
        review_history=review_history,
    )
    coverage = _read_jsonl(round_dir / "sample_coverage.jsonl")
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
        observations = grouped.get(sample, [])
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
        status, warnings = _effective_coverage(frame, observations, approved_samples)
        occupancy.append(
            {
                "run_id": config.run.run_id,
                "round_id": round_id,
                "sample_index": sample,
                "source_timestamp_seconds": frame["source_timestamp_seconds"],
                "observed_marker_count": len(observations),
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
                "corrected": any(obs.get("source") == "corrected" for obs in observations),
            }
        )
    corrected_path = output / "corrected_observations.jsonl"
    with corrected_path.open("w", encoding="utf-8") as stream:
        for row in sorted(rows, key=lambda x: (x["sample_index"], x["observation_id"])):
            stream.write(json.dumps(row, separators=(",", ":"), allow_nan=False) + "\n")
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
        summary,
    )
    manifest = {
        "revision": revision,
        "round_id": round_id,
        "raw_observations_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
        "corrections_sha256": hashlib.sha256(
            (round_dir / "corrections.jsonl").read_bytes()
        ).hexdigest()
        if (round_dir / "corrections.jsonl").exists()
        else hashlib.sha256(b"").hexdigest(),
        "reviewed_frames_sha256": hashlib.sha256(
            (round_dir / "reviewed_frames.jsonl").read_bytes()
        ).hexdigest()
        if (round_dir / "reviewed_frames.jsonl").exists()
        else hashlib.sha256(b"").hexdigest(),
        "correction_count": len(correction_history),
        "reviewed_frame_count": len({int(row["sample_index"]) for row in review_history}),
        "frame_count": len(occupancy),
        "detector_invoked": False,
        "artifacts": [
            "corrected_observations.jsonl",
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
