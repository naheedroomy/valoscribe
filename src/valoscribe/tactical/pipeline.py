"""Low-rate, streaming real-source calibration and team-color analysis."""

from __future__ import annotations

import hashlib
import json
import resource
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Iterator, Literal, cast

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from valoscribe.tactical import __version__
from valoscribe.tactical.config import RoundConfig, TacticalConfig, load_map_config
from valoscribe.tactical.contracts import RawMarkerObservation, RunManifest, TeamFrameState
from valoscribe.tactical.detection import crop_map_mask, detect_markers


def peak_rss_bytes() -> int:
    """Normalize the process high-water RSS to bytes across macOS and Unix."""
    peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return peak if sys.platform == "darwin" else peak * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else project_root() / path


def load_assets(config: TacticalConfig) -> tuple[Path, Path, dict, np.ndarray, np.ndarray]:
    map_path = resolve_path(config.map.zone_config)
    asset_path = resolve_path(config.map.asset_path)
    map_data = load_map_config(map_path)
    asset = cv2.imread(str(asset_path), cv2.IMREAD_UNCHANGED)
    if asset is None:
        raise ValueError(f"canonical map asset cannot be decoded: {asset_path}")
    if (
        asset.shape[1] != config.map.canonical_width
        or asset.shape[0] != config.map.canonical_height
    ):
        raise ValueError("canonical map dimensions do not match config")
    if sha256_file(asset_path) != config.map.asset_sha256:
        raise ValueError("canonical map asset hash does not match config")
    if asset.ndim == 3 and asset.shape[2] == 4:
        bgr = cv2.cvtColor(asset, cv2.COLOR_BGRA2BGR)
        alpha = asset[:, :, 3]
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        floorplan_mask = cv2.bitwise_and(
            cv2.threshold(gray, 18, 255, cv2.THRESH_BINARY)[1],
            cv2.threshold(alpha, 8, 255, cv2.THRESH_BINARY)[1],
        )
    else:
        bgr = asset
        floorplan_mask = cv2.threshold(
            cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY), 18, 255, cv2.THRESH_BINARY
        )[1]
    map_data["floorplan_mask"] = floorplan_mask
    return map_path, asset_path, map_data, bgr, floorplan_mask


def validate_source(config: TacticalConfig) -> tuple[Path, str, tuple[int, int], float]:
    source = resolve_path(config.source.video_path)
    if not source.is_file():
        raise ValueError(f"source video does not exist: {source}")
    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise ValueError(f"source video cannot be opened: {source}")
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    capture.release()
    if (width, height) != (config.source.expected_width, config.source.expected_height):
        raise ValueError(f"source dimensions {(width, height)} do not match configured dimensions")
    digest = sha256_file(source)
    if config.source.sha256 and digest != config.source.sha256:
        raise ValueError("source video SHA-256 does not match configured hash")
    if fps <= 0:
        raise ValueError("source video reports an invalid frame rate")
    return source, digest, (width, height), fps


def render_zones(asset: np.ndarray, map_data: dict, *, small: bool = False) -> np.ndarray:
    image = asset.copy()
    colors = {
        "A": (40, 80, 255),
        "MID": (50, 210, 240),
        "B": (255, 130, 40),
        "SPAWN": (180, 100, 230),
    }
    for zone in map_data["zones"]:
        points = np.asarray(zone["vertices_px"], dtype=np.int32).reshape((-1, 1, 2))
        color = colors[zone["macro_group"]]
        cv2.polylines(image, [points], True, color, 3 if not small else 2)
        if not small:
            cv2.putText(
                image,
                zone["name"],
                tuple(points[0, 0]),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )
    return cast(np.ndarray, image)


def assign_zone(
    x: float, y: float, map_data: dict, boundary_tolerance_px: float | None = None
) -> tuple[str, str]:
    """Assign only unambiguous interior points; boundary, overlap, or gaps stay unknown."""
    if boundary_tolerance_px is None:
        boundary_tolerance_px = float(
            map_data.get("zone_assignment", {}).get("boundary_tolerance_px", 2.0)
        )
    matches: list[tuple[str, str]] = []
    near_boundary = False
    point = (float(x), float(y))
    floorplan_mask = map_data.get("floorplan_mask")
    if floorplan_mask is not None:
        pixel_x, pixel_y = round(x), round(y)
        if (
            pixel_x < 0
            or pixel_y < 0
            or pixel_y >= floorplan_mask.shape[0]
            or pixel_x >= floorplan_mask.shape[1]
            or floorplan_mask[pixel_y, pixel_x] == 0
        ):
            return "unknown", "OTHER"
    for zone in map_data["zones"]:
        polygon = np.asarray(zone["vertices_px"], dtype=np.float32)
        distance = float(cv2.pointPolygonTest(polygon, point, True))
        if 0 <= distance <= boundary_tolerance_px:
            near_boundary = True
        elif distance > boundary_tolerance_px:
            matches.append((zone["zone_id"], zone["macro_group"]))
    if near_boundary or len(matches) != 1:
        return "unknown", "OTHER"
    return matches[0]


def _crop(frame: np.ndarray, config: TacticalConfig) -> np.ndarray | None:
    region = config.broadcast.minimap_crop
    height, width = frame.shape[:2]
    if region.x + region.width > width or region.y + region.height > height:
        return None
    return cast(
        np.ndarray,
        frame[region.y : region.y + region.height, region.x : region.x + region.width].copy(),
    )


def _inside_exclusion(timestamp: float, round_config: RoundConfig) -> str | None:
    return next(
        (
            interval.reason
            for interval in round_config.excluded_intervals
            if interval.start_seconds <= timestamp < interval.end_seconds
        ),
        None,
    )


def _capture_samples(
    source: Path, round_config: RoundConfig, source_fps: float, sample_fps: float
) -> Iterator[tuple[int, float, np.ndarray]]:
    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise ValueError(f"cannot reopen source: {source}")
    capture.set(cv2.CAP_PROP_POS_MSEC, round_config.source_start_seconds * 1000)
    frame_step = max(1, round(source_fps / sample_fps))
    frame_number = 0
    next_sample = round_config.source_start_seconds
    try:
        while True:
            ok, frame = capture.read()
            if not ok or frame is None:
                break
            frame_number += 1
            timestamp = float(capture.get(cv2.CAP_PROP_POS_MSEC)) / 1000.0
            if timestamp >= round_config.source_end_seconds:
                break
            if timestamp + 1e-3 < round_config.source_start_seconds:
                continue
            if frame_number % frame_step != 1 and frame_number != 1:
                continue
            if timestamp + 1e-3 < next_sample:
                continue
            while next_sample <= timestamp + 1e-3:
                next_sample += 1.0 / sample_fps
            yield frame_number, timestamp, frame
    finally:
        capture.release()


def _draw_minimap(
    crop: np.ndarray, markers: list[tuple[float, float, float]], text: list[str]
) -> np.ndarray:
    frame = crop.copy()
    for x, y, confidence in markers:
        center = (round(x), round(y))
        cv2.circle(frame, center, 7, (0, 255, 0), 1, cv2.LINE_AA)
        cv2.putText(
            frame,
            f"{confidence:.2f}",
            (center[0] + 5, center[1] - 4),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.32,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
    for index, line in enumerate(text):
        cv2.putText(
            frame,
            line,
            (5, 15 + index * 16),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.42,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
    return cast(np.ndarray, frame)


def _draw_canonical(
    zone_image: np.ndarray,
    markers: list[tuple[float, float, float]],
    map_data: dict,
    text: list[str],
) -> np.ndarray:
    frame = zone_image.copy()
    counts: Counter[str] = Counter()
    for x, y, confidence in markers:
        zone_id, macro = assign_zone(x, y, map_data)
        counts[macro] += 1
        cv2.circle(frame, (round(x), round(y)), 8, (0, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(
            frame,
            f"{confidence:.2f}",
            (round(x) + 8, round(y)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.38,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
    cv2.putText(
        frame,
        "Observed only; no player identity or inferred missing markers",
        (20, 35),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    for index, line in enumerate(text):
        cv2.putText(
            frame,
            line,
            (20, 70 + index * 27),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.68,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
    summary = "Macro observed A={} MID={} B={} SPAWN={} OTHER={}".format(
        *(counts[k] for k in ["A", "MID", "B", "SPAWN", "OTHER"])
    )
    cv2.putText(
        frame, summary, (20, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2, cv2.LINE_AA
    )
    return cast(np.ndarray, frame)


def create_run_directory(output_root: Path, run_id: str) -> Path:
    """Create a unique run directory or fail without overwriting prior output."""
    output_root.mkdir(parents=True, exist_ok=True)
    run_dir = output_root / run_id
    run_dir.mkdir(parents=False, exist_ok=False)
    return run_dir


def _open_writer(path: Path, fps: float, size: tuple[int, int]) -> cv2.VideoWriter:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter.fourcc(*"mp4v"), fps, size)
    if not writer.isOpened():
        raise ValueError(f"cannot create playback video: {path}")
    return writer


def _jsonl_write(stream, payload: dict) -> None:
    stream.write(json.dumps(payload, separators=(",", ":"), allow_nan=False) + "\n")


def _process_round(
    source: Path,
    run_id: str,
    round_config: RoundConfig,
    config: TacticalConfig,
    source_fps: float,
    map_data: dict,
    asset: np.ndarray,
    floorplan_mask: np.ndarray,
    round_dir: Path,
) -> tuple[Counter[str], int, int, float | None, float | None]:
    round_dir.mkdir(parents=True, exist_ok=False)
    raw_path = round_dir / "raw_observations.jsonl"
    coverage_path = round_dir / "sample_coverage.jsonl"
    minimap_path = round_dir / "minimap_playback.mp4"
    canonical_path = round_dir / "canonical_playback.mp4"
    zone_image = render_zones(asset, map_data)
    crop_config = config.broadcast.minimap_crop
    crop_mask = crop_map_mask(
        floorplan_mask, config.broadcast.transform.matrix, crop_config.width, crop_config.height
    )
    writers: tuple[cv2.VideoWriter, cv2.VideoWriter] | None = None
    status_counts: Counter[str] = Counter()
    total_markers = 0
    total_samples = 0
    rejected_candidates: Counter[str] = Counter()
    start_seen: float | None = None
    end_seen: float | None = None
    canonical_matrix = np.asarray(config.broadcast.transform.matrix, dtype=np.float64)
    with (
        raw_path.open("w", encoding="utf-8") as raw_stream,
        coverage_path.open("w", encoding="utf-8") as coverage_stream,
    ):
        try:
            for sample_index, (frame_index, timestamp, frame) in enumerate(
                _capture_samples(source, round_config, source_fps, config.run.sample_fps)
            ):
                crop = _crop(frame, config)
                excluded_reason = _inside_exclusion(timestamp, round_config)
                marker_data: list[tuple[float, float, float]] = []
                transformed: list[tuple[float, float, float]] = []
                status: Literal["good", "partial", "unknown", "excluded"]
                if crop is None:
                    status = "unknown"
                    warning = "configured minimap crop is outside source-frame bounds"
                elif excluded_reason:
                    status = "excluded"
                    warning = excluded_reason
                else:
                    detection = detect_markers(
                        crop,
                        config.broadcast.color_ranges_hsv_candidate_only,
                        config.marker_detection,
                        crop_mask,
                    )
                    rejected_candidates.update(detection.rejected_by_reason)
                    for candidate in detection.markers:
                        marker_data.append(
                            (candidate.crop_x, candidate.crop_y, candidate.confidence)
                        )
                        x, y = candidate.crop_x, candidate.crop_y
                        canonical_x = (
                            canonical_matrix[0, 0] * x
                            + canonical_matrix[0, 1] * y
                            + canonical_matrix[0, 2]
                        )
                        canonical_y = (
                            canonical_matrix[1, 0] * x
                            + canonical_matrix[1, 1] * y
                            + canonical_matrix[1, 2]
                        )
                        canonical_valid = (
                            0 <= canonical_x < config.map.canonical_width
                            and 0 <= canonical_y < config.map.canonical_height
                        )
                        if canonical_valid:
                            transformed.append((canonical_x, canonical_y, candidate.confidence))
                        raw = RawMarkerObservation(
                            run_id=run_id,
                            round_id=round_config.round_id,
                            sample_index=sample_index,
                            source_frame_index=max(0, int(round(timestamp * source_fps))),
                            source_timestamp_seconds=timestamp,
                            crop_x=candidate.crop_x,
                            crop_y=candidate.crop_y,
                            canonical_x=canonical_x if canonical_valid else None,
                            canonical_y=canonical_y if canonical_valid else None,
                            confidence=candidate.confidence,
                            detector_version="hsv-floorplan-components-v1",
                            quality_flags=list(candidate.flags)
                            + ([] if canonical_valid else ["transform_out_of_bounds"]),
                        )
                        _jsonl_write(raw_stream, raw.model_dump(mode="json"))
                    # Candidate detections are not manually validated in this MVP phase.
                    status = "partial" if marker_data else "unknown"
                    warning = "candidate detector unreviewed; no absence inference"
                coverage = TeamFrameState(
                    run_id=run_id,
                    round_id=round_config.round_id,
                    sample_index=sample_index,
                    source_timestamp_seconds=timestamp,
                    observed_marker_count=len(marker_data),
                    coverage_status=status,
                    warning=warning,
                )
                _jsonl_write(coverage_stream, coverage.model_dump(mode="json"))
                status_counts[status] += 1
                total_markers += len(marker_data)
                total_samples += 1
                start_seen = timestamp if start_seen is None else start_seen
                end_seen = timestamp
                if crop is None:
                    crop = np.zeros((crop_config.height, crop_config.width, 3), dtype=np.uint8)
                minimap_display = _draw_minimap(
                    crop,
                    marker_data,
                    [
                        f"{round_config.round_id} {timestamp:.2f}s "
                        f"{config.team.short_name} {round_config.side}",
                        f"RAW; coverage={status}" + (f" ({warning})" if warning else ""),
                    ],
                )
                canonical_display = _draw_canonical(
                    zone_image,
                    transformed,
                    map_data,
                    [
                        f"{round_config.round_id} {timestamp:.2f}s | "
                        f"{config.team.short_name} {round_config.side}",
                        f"Raw markers={len(marker_data)} | coverage={status}",
                    ],
                )
                if writers is None:
                    writers = (
                        _open_writer(
                            minimap_path, config.run.sample_fps, (crop.shape[1], crop.shape[0])
                        ),
                        _open_writer(
                            canonical_path,
                            config.run.sample_fps,
                            (zone_image.shape[1], zone_image.shape[0]),
                        ),
                    )
                writers[0].write(minimap_display)
                writers[1].write(canonical_display)
        finally:
            if writers is not None:
                for writer in writers:
                    writer.release()
    summary = {
        "round_id": round_config.round_id,
        "source_interval_seconds": [
            round_config.source_start_seconds,
            round_config.source_end_seconds,
        ],
        "observed_source_span_seconds": [start_seen, end_seen],
        "sample_count": total_samples,
        "coverage_counts": dict(status_counts),
        "observed_marker_candidates": total_markers,
        "rejected_candidate_counts_by_reason": dict(rejected_candidates),
        "exclusions": [
            interval.model_dump(mode="json") for interval in round_config.excluded_intervals
        ],
        "selection_note": round_config.selection_note,
        "warnings": [
            "Candidate color segmentation is not reviewed ground truth.",
            "No player identity, missing-player inference, or tactical intent is generated.",
        ],
        "artifacts": {
            "raw_observations": raw_path.name,
            "sample_coverage": coverage_path.name,
            "minimap_playback": minimap_path.name,
            "canonical_playback": canonical_path.name,
        },
    }
    (round_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return status_counts, total_samples, total_markers, start_seen, end_seen


def _make_calibration_artifacts(
    source: Path,
    config: TacticalConfig,
    source_fps: float,
    map_data: dict,
    asset: np.ndarray,
    floorplan_mask: np.ndarray,
    output: Path,
) -> None:
    output.mkdir(parents=True, exist_ok=False)
    samples: list[tuple[str, float, np.ndarray, np.ndarray]] = []
    for round_config in config.rounds:
        live_start = round_config.source_start_seconds + round_config.live_start_offset_seconds
        usable_end = min(
            round_config.source_end_seconds, live_start + config.run.opening_window_seconds
        )
        times = [
            live_start,
            (live_start + usable_end) / 2,
            max(live_start, usable_end - 1 / config.run.sample_fps),
        ]
        for label, timestamp in zip(["begin", "mid", "end"], times):
            if _inside_exclusion(timestamp, round_config):
                # Move to the first non-excluded sample inside the configured opening window.
                timestamp = float(
                    next(
                        (
                            t
                            for t in np.arange(timestamp, usable_end, 1 / config.run.sample_fps)
                            if not _inside_exclusion(float(t), round_config)
                        ),
                        usable_end,
                    )
                )
            cap = cv2.VideoCapture(str(source))
            cap.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
            ok, frame = cap.read()
            cap.release()
            crop = _crop(frame, config) if ok and frame is not None else None
            if crop is None:
                continue
            transformed_edges = cv2.Canny(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), 80, 180)
            warped = cv2.warpAffine(
                transformed_edges,
                np.asarray(config.broadcast.transform.matrix, dtype=np.float64),
                (config.map.canonical_width, config.map.canonical_height),
                flags=cv2.INTER_NEAREST,
            )
            warped = cv2.bitwise_and(warped, floorplan_mask)
            overlay = cv2.cvtColor(asset, cv2.COLOR_BGR2RGB).copy()
            overlay[warped > 0] = (255, 30, 30)
            title = f"{round_config.round_id} {label} {timestamp:.2f}s"
            samples.append((title, timestamp, crop, overlay))
    if samples:
        crop_contact = Image.new("RGB", (720 * 3, 428 * len(config.rounds)), "black")
        transform_contact = Image.new("RGB", (384 * 3, 408 * len(config.rounds)), "black")
        crop_draw = ImageDraw.Draw(crop_contact)
        transform_draw = ImageDraw.Draw(transform_contact)
        font = ImageFont.load_default()
        for index, (title, _, crop, overlay) in enumerate(samples):
            col, row = index % 3, index // 3
            cx, cy = col * 720, row * 428
            crop_contact.paste(
                Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)).resize((720, 400)),
                (cx, cy + 28),
            )
            crop_draw.text((cx + 4, cy + 4), title, fill="white", font=font)
            tx, ty = col * 384, row * 408
            transform_contact.paste(Image.fromarray(overlay).resize((384, 384)), (tx, ty + 24))
            transform_draw.text((tx + 4, ty + 4), title, fill="white", font=font)
        crop_contact.save(output / "minimap-crop-contact-sheet.jpg", quality=90)
        transform_contact.save(output / "transform-overlay-contact.jpg", quality=90)
    zones = render_zones(asset, map_data)
    cv2.imwrite(str(output / "ascent-zones.png"), zones)


def inspect_config(config_path: Path, config: TacticalConfig, raw_config: bytes) -> dict:
    source, source_hash, dimensions, source_fps = validate_source(config)
    map_path, _, map_data, asset, mask = load_assets(config)
    out_dir = resolve_path(config.run.output_root) / f"{config.run.run_id}-inspect"
    out_dir.mkdir(parents=True, exist_ok=False)
    calibration_dir = out_dir / "calibration"
    _make_calibration_artifacts(source, config, source_fps, map_data, asset, mask, calibration_dir)
    result = {
        "run_id": config.run.run_id,
        "source_identifier": source.name,
        "source_sha256": source_hash,
        "source_dimensions": dimensions,
        "source_fps": source_fps,
        "config_sha256": hashlib.sha256(raw_config).hexdigest(),
        "map_config_sha256": sha256_file(map_path),
        "rounds": [
            {
                "round_id": r.round_id,
                "source_start_seconds": r.source_start_seconds,
                "source_end_seconds": r.source_end_seconds,
                "live_start_offset_seconds": r.live_start_offset_seconds,
                "excluded_intervals": [
                    item.model_dump(mode="json") for item in r.excluded_intervals
                ],
                "selection_note": r.selection_note,
            }
            for r in config.rounds
        ],
        "calibration_directory": str(calibration_dir),
        "warnings": ["Manual calibration remains candidate; no registration accuracy claim."],
    }
    (out_dir / "inspect.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def analyze_config(
    config_path: Path, config: TacticalConfig, raw_config: bytes
) -> tuple[Path, dict]:
    source, source_hash, dimensions, source_fps = validate_source(config)
    map_path, _, map_data, asset, floorplan_mask = load_assets(config)
    map_hash = sha256_file(map_path)
    output_root = resolve_path(config.run.output_root)
    run_dir = create_run_directory(output_root, config.run.run_id)
    started = time.monotonic()
    (run_dir / "config.snapshot.yaml").write_bytes(raw_config)
    calibration_dir = run_dir / "calibration"
    _make_calibration_artifacts(
        source, config, source_fps, map_data, asset, floorplan_mask, calibration_dir
    )
    rounds_dir = run_dir / "rounds"
    rounds_dir.mkdir()
    round_results: list[dict] = []
    warnings = [
        "Candidate HSV segmentation and affine require output review.",
        "Unknown, gaps, black space, and ambiguous zone boundaries remain OTHER/unknown.",
    ]
    for round_config in config.rounds:
        status_counts, samples, markers, first, last = _process_round(
            source,
            config.run.run_id,
            round_config,
            config,
            source_fps,
            map_data,
            asset,
            floorplan_mask,
            rounds_dir / round_config.round_id,
        )
        round_results.append(
            {
                "round_id": round_config.round_id,
                "sample_count": samples,
                "candidate_observations": markers,
                "coverage_counts": dict(status_counts),
                "observed_span_seconds": [first, last],
            }
        )
    elapsed = time.monotonic() - started
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root(),
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        commit = "unknown"
    manifest = RunManifest(
        run_id=config.run.run_id,
        project_commit=commit,
        source_identifier=source.name,
        source_video_sha256=source_hash,
        source_dimensions=dimensions,
        configuration_sha256=hashlib.sha256(raw_config).hexdigest(),
        map_config_sha256=map_hash,
        code_version=__version__,
        sample_fps=config.run.sample_fps,
        round_ids=[r.round_id for r in config.rounds],
        output_paths={
            "manifest": "manifest.json",
            "configuration_snapshot": "config.snapshot.yaml",
            "calibration": "calibration/",
            "rounds": "rounds/",
            "run_log": "logs/run.log",
        },
        warnings=warnings
        + [
            f"elapsed_seconds={elapsed:.2f}",
            f"peak_rss_bytes={peak_rss_bytes()}",
        ],
    )
    (run_dir / "logs").mkdir()
    (run_dir / "logs" / "run.log").write_text(
        json.dumps({"elapsed_seconds": elapsed, "rounds": round_results}, indent=2) + "\n",
        encoding="utf-8",
    )
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8"
    )
    artifact_bytes = sum(path.stat().st_size for path in run_dir.rglob("*") if path.is_file())
    result = {
        "run_directory": str(run_dir),
        "elapsed_seconds": elapsed,
        "rounds": round_results,
        "artifact_bytes": artifact_bytes,
        "peak_rss_bytes": peak_rss_bytes(),
    }
    return run_dir, result
