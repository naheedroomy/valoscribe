"""Complete-stream diagnostic runner for anonymous minimap candidate tracklets."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Literal, cast

import cv2
import numpy as np
from pydantic import ValidationError

from valoscribe.detectors.cropper import Cropper
from valoscribe.detectors.minimap_color_detector import (
    MinimapColorCandidateDetector,
    MinimapColorProfile,
)
from valoscribe.tracking.anonymous_artifacts import (
    _arrow,
    anonymous_run_manifest_sha256,
    write_anonymous_run,
)
from valoscribe.tracking.provenance import (
    local_content_tree_sha256,
    local_file_sha256,
    manifest_sha256,
)
from valoscribe.types.anonymous_tracking import (
    AnonymousCandidateObservation,
    AnonymousDecoderProvenance,
    AnonymousFrameContext,
    AnonymousRawFrameObservation,
    AnonymousRoundBounds,
    AnonymousRunManifest,
    AnonymousTrackSample,
)
from valoscribe.types.persistent import RawMinimapColorCandidate
from valoscribe.types.tracking_provenance import (
    ConfigFileProvenance,
    TrackingObservationProvenance,
    TrackingRunManifest,
    canonical_config_sha256,
)
from valoscribe.video.pts_reader import SequentialPtsVideoSource

ANONYMOUS_CODE_FINGERPRINT_PATHS = (
    "src/valoscribe/tracking/anonymous_runner.py",
    "src/valoscribe/tracking/anonymous_artifacts.py",
    "src/valoscribe/tracking/provenance.py",
    "src/valoscribe/types/anonymous_tracking.py",
    "src/valoscribe/types/source_video.py",
    "src/valoscribe/types/persistent.py",
    "src/valoscribe/types/tracking_provenance.py",
    "src/valoscribe/video/pts_reader.py",
    "src/valoscribe/detectors/cropper.py",
    "src/valoscribe/detectors/minimap_color_detector.py",
)


class AnonymousRunnerThresholds:
    """Unvalidated diagnostic defaults; values are not production tuning."""

    def __init__(
        self,
        *,
        max_step_crop_fraction: float = 0.08,
        max_gap_seconds: float = 0.5,
        ambiguity_margin: float = 0.01,
    ):
        if (
            not 0 < max_step_crop_fraction <= 1
            or not 0 < max_gap_seconds
            or not 0 <= ambiguity_margin < 1
        ):
            raise ValueError("anonymous association thresholds are outside valid diagnostic ranges")
        self.max_step_crop_fraction = max_step_crop_fraction
        self.max_gap_seconds = max_gap_seconds
        self.ambiguity_margin = ambiguity_margin


def run_anonymous_round(
    *,
    source_path: Path,
    bounds: AnonymousRoundBounds,
    hud_config_path: Path,
    color_config_path: Path,
    map_config_path: Path,
    map_asset_path: Path,
    output_root: Path,
    run_id: str,
    project_commit: str,
    upstream_commit: str,
    mode: Literal["diagnostic_only", "synthetic"],
    context_by_frame: dict[int, AnonymousFrameContext] | None = None,
    thresholds: AnonymousRunnerThresholds | None = None,
) -> dict[str, str]:
    """Run one externally bounded round and certify only a fully decoded diagnostic.

    Context must be independently reviewed per frame; omitted context safely resets
    association. Coordinates remain normalized within the configured crop.
    """
    bounds = AnonymousRoundBounds.model_validate(bounds.model_dump())
    if mode not in {"diagnostic_only", "synthetic"}:
        raise ValueError("anonymous runner only supports explicit diagnostic or synthetic mode")
    if not project_commit.strip() or not upstream_commit.strip():
        raise ValueError("project and upstream commits are required provenance")
    thresholds = thresholds or AnonymousRunnerThresholds()
    # Fail before decode/output if the required derived format cannot be produced.
    _arrow()
    source_path = source_path.resolve(strict=True)
    source_digest = local_file_sha256(source_path)
    hud_digest = local_file_sha256(hud_config_path)
    color_digest = local_file_sha256(color_config_path)
    map_digest = local_file_sha256(map_config_path)
    asset_digest = local_file_sha256(map_asset_path)

    try:
        hud = json.loads(hud_config_path.read_bytes())
        color_profile = MinimapColorProfile.model_validate_json(color_config_path.read_bytes())
        map_config = json.loads(map_config_path.read_bytes())
        crop = hud["minimap"]
        canonical_asset = map_config["canonical_minimap"]
        map_version = canonical_asset["asset_version"]
        configured_asset_path = canonical_asset["local_asset_path"]
        configured_asset_sha256 = canonical_asset["sha256"]
    except (OSError, ValueError, KeyError, TypeError, ValidationError) as error:
        raise ValueError(
            "invalid HUD, color, or map configuration for anonymous diagnostics"
        ) from error
    if not isinstance(crop, dict):
        raise ValueError("HUD minimap rectangle is missing")
    if map_config.get("map_id") != bounds.map_id:
        raise ValueError("HUD crop or externally supplied map identity does not match config")
    configured_path = (map_config_path.parent / configured_asset_path).resolve()
    if configured_path != map_asset_path.resolve() or configured_asset_sha256 != asset_digest:
        raise ValueError("supplied map asset path or bytes do not match map configuration")
    rectangle = [crop.get(name) for name in ("x", "y", "width", "height")]
    if any(type(value) is not int for value in rectangle):
        raise ValueError("HUD minimap rectangle coordinates must be integers")
    x, y, width, height = cast(tuple[int, int, int, int], tuple(rectangle))
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise ValueError("HUD minimap rectangle is invalid")
    hud_provenance = ConfigFileProvenance(
        config_id=str(hud.get("profile_id", hud.get("name", hud_config_path.stem))),
        filename=hud_config_path.name,
        file_sha256=hud_digest,
    )
    color_provenance = ConfigFileProvenance(
        config_id=color_profile.profile_id,
        filename=color_config_path.name,
        file_sha256=color_digest,
    )
    map_provenance = ConfigFileProvenance(
        config_id=bounds.map_id,
        filename=map_config_path.name,
        file_sha256=map_digest,
    )
    config_digest = canonical_config_sha256(hud_provenance, color_provenance, map_provenance)
    code_digest = local_content_tree_sha256(
        Path(__file__).resolve().parents[3],
        ANONYMOUS_CODE_FINGERPRINT_PATHS,
    )
    raw_frames: list[AnonymousRawFrameObservation] = []
    samples: list[AnonymousTrackSample] = []
    debug: dict[str, bytes] = {}
    contexts = {
        frame_index: AnonymousFrameContext.model_validate(context.model_dump())
        for frame_index, context in (context_by_frame or {}).items()
    }
    active_tracks: dict[str, tuple[float, float, str, str, float, int, float]] = {}
    next_ordinal = 1

    with SequentialPtsVideoSource(source_path) as reader:
        metadata = reader.metadata
        if x + width > metadata.width or y + height > metadata.height:
            raise ValueError("HUD minimap crop is outside source frame")
        if bounds.end_frame_index >= metadata.frame_count:
            raise ValueError("externally reviewed round frame bounds exceed source inventory")
        timestamps_seen: dict[int, int] = {}
        cropper = Cropper(hud_config_path)
        for frame in reader:
            frame.validate_against(metadata)
            timestamps_seen[frame.frame_index] = frame.source_pts
            if (
                frame.frame_index < bounds.start_frame_index
                or frame.frame_index > bounds.end_frame_index
            ):
                continue
            if frame.frame_index in {bounds.start_frame_index, bounds.end_frame_index}:
                expected_pts = (
                    bounds.start_source_pts
                    if frame.frame_index == bounds.start_frame_index
                    else bounds.end_source_pts
                )
                if frame.source_pts != expected_pts:
                    raise ValueError(
                        "externally reviewed frame/PTS bounds do not match source inventory"
                    )
            if not (bounds.start_source_pts <= frame.source_pts <= bounds.end_source_pts):
                raise ValueError("frame inside reviewed bounds falls outside reviewed PTS range")
            supplied_context = contexts.get(frame.frame_index)
            if supplied_context is not None and supplied_context.frame_index != frame.frame_index:
                raise ValueError("frame context key does not match its reviewed frame index")
            context = "unknown" if supplied_context is None else supplied_context.state
            if context != "live" or (
                raw_frames and frame.frame_index != raw_frames[-1].provenance.frame_index + 1
            ):
                active_tracks.clear()
            minimap = cropper.crop_minimap(frame.bgr)
            timestamp = float(frame.timestamp_seconds)
            detection = MinimapColorCandidateDetector(color_profile).detect(
                minimap,
                vod_timestamp_s=timestamp,
                source_frame=frame.frame_index,
            )
            candidate_rows: list[AnonymousCandidateObservation] = []
            accepted: list[tuple[str, RawMinimapColorCandidate]] = []
            for index, candidate in enumerate(detection.candidates):
                candidate_id = f"f{frame.frame_index:08d}-c{index:04d}"
                candidate_rows.append(
                    AnonymousCandidateObservation(
                        candidate_id=candidate_id,
                        candidate=candidate,
                    )
                )
                if candidate.accepted:
                    accepted.append((candidate_id, candidate))
            frame_samples: list[AnonymousTrackSample] = []
            if context == "live" and accepted:
                frame_samples, next_ordinal = _associate(
                    accepted,
                    frame.frame_index,
                    frame.source_pts,
                    metadata.time_base_numerator,
                    metadata.time_base_denominator,
                    timestamp,
                    f"{run_id}-m{bounds.map_number}-r{bounds.round_number}",
                    active_tracks,
                    next_ordinal,
                    thresholds,
                )
                samples.extend(frame_samples)
            elif context == "live":
                active_tracks.clear()
            for sample in frame_samples:
                point = (
                    round(sample.crop_x_normalized * (width - 1)),
                    round(sample.crop_y_normalized * (height - 1)),
                )
                cv2.circle(detection.debug_overlay, point, 5, (0, 255, 255), 1)
                label = _short_tracklet_label(sample.tracklet_id)
                cv2.putText(
                    detection.debug_overlay,
                    label,
                    _tracklet_label_position(point, width, height, label),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.3,
                    (255, 255, 255),
                    1,
                    cv2.LINE_AA,
                )
            encoded_ok, encoded = cv2.imencode(".png", detection.debug_overlay)
            if not encoded_ok:
                raise RuntimeError("failed to encode anonymous detector debug overlay")
            png = encoded.tobytes()
            debug_path = f"debug/candidates_{frame.frame_index:08d}.png"
            debug[debug_path] = png
            provenance = TrackingObservationProvenance(
                run_id=run_id,
                manifest_sha256="0" * 64,
                source_video_sha256=source_digest,
                config_sha256=config_digest,
                map_id=bounds.map_id,
                map_number=bounds.map_number,
                round_number=bounds.round_number,
                frame_index=frame.frame_index,
                source_pts=frame.source_pts,
                timebase_numerator=metadata.time_base_numerator,
                timebase_denominator=metadata.time_base_denominator,
                timestamp_s=timestamp,
            )
            # Manifest digest is attached after the complete stream is verified.
            raw_frames.append(
                AnonymousRawFrameObservation(
                    provenance=provenance,
                    runner_manifest_sha256="0" * 64,
                    crop_x=x,
                    crop_y=y,
                    crop_width=width,
                    crop_height=height,
                    coordinate_frame="configured_minimap_crop_pixels_normalized",
                    context=context,
                    context_evidence=supplied_context,
                    candidates=tuple(candidate_rows),
                    debug_png_sha256=hashlib.sha256(png).hexdigest(),
                )
            )
        if not reader.complete_stream_verified:
            raise RuntimeError("source stream did not reach verified EOF")
        metadata = reader.metadata
        if (
            timestamps_seen.get(bounds.start_frame_index) != bounds.start_source_pts
            or timestamps_seen.get(bounds.end_frame_index) != bounds.end_source_pts
        ):
            raise ValueError(
                "reviewed round bounds were not verified against full-source inventory"
            )

    # Recheck exact bytes and config/map bytes at the final certification boundary.
    if local_file_sha256(source_path) != source_digest:
        raise RuntimeError("source bytes changed before anonymous run finalization")
    if (
        local_file_sha256(hud_config_path),
        local_file_sha256(color_config_path),
        local_file_sha256(map_config_path),
        local_file_sha256(map_asset_path),
    ) != (hud_digest, color_digest, map_digest, asset_digest):
        raise RuntimeError("config or map asset bytes changed before anonymous run finalization")
    manifest = TrackingRunManifest(
        run_id=run_id,
        source_path=str(source_path),
        source_video_sha256=source_digest,
        source_width=metadata.width,
        source_height=metadata.height,
        fps_numerator=metadata.fps_numerator,
        fps_denominator=metadata.fps_denominator,
        timebase_numerator=metadata.time_base_numerator,
        timebase_denominator=metadata.time_base_denominator,
        map_id=bounds.map_id,
        map_number=bounds.map_number,
        round_number=bounds.round_number,
        start_frame_index=bounds.start_frame_index,
        end_frame_index=bounds.end_frame_index,
        start_source_pts=bounds.start_source_pts,
        end_source_pts=bounds.end_source_pts,
        start_timestamp_s=float(
            Fraction(
                bounds.start_source_pts * metadata.time_base_numerator,
                metadata.time_base_denominator,
            )
        ),
        end_timestamp_s=float(
            Fraction(
                bounds.end_source_pts * metadata.time_base_numerator, metadata.time_base_denominator
            )
        ),
        hud_config=hud_provenance,
        color_config=color_provenance,
        map_config=map_provenance,
        config_sha256=config_digest,
        map_asset_sha256=asset_digest,
        map_asset_version=map_version,
        project_commit=project_commit,
        upstream_commit=upstream_commit,
        code_fingerprint_sha256=code_digest,
        detector_version="MinimapColorCandidateDetector/1.0",
        tracker_version="anonymous-adjacent-candidate/1.0",
        started_at=datetime.now(timezone.utc),
    )
    digest = manifest_sha256(manifest)
    wrapper = AnonymousRunManifest(
        mode=mode,
        tracking_manifest=manifest,
        tracking_manifest_sha256=digest,
        decoder=AnonymousDecoderProvenance(
            ffmpeg_version=metadata.ffmpeg_version,
            ffprobe_version=metadata.ffprobe_version,
            timestamp_kind=metadata.timestamp_kind,
            timestamp_timebase_numerator=metadata.time_base_numerator,
            timestamp_timebase_denominator=metadata.time_base_denominator,
        ),
        bounds=bounds,
        max_step_crop_fraction=thresholds.max_step_crop_fraction,
        max_gap_seconds=thresholds.max_gap_seconds,
        ambiguity_margin=thresholds.ambiguity_margin,
    )
    wrapper_digest = anonymous_run_manifest_sha256(wrapper)
    raw_frames = [
        row.model_copy(
            update={
                "provenance": row.provenance.model_copy(update={"manifest_sha256": digest}),
                "runner_manifest_sha256": wrapper_digest,
            }
        )
        for row in raw_frames
    ]
    samples = [
        row.model_copy(
            update={
                "manifest_sha256": digest,
                "runner_manifest_sha256": wrapper_digest,
            }
        )
        for row in samples
    ]
    return write_anonymous_run(
        runs_root=output_root,
        wrapper=wrapper,
        raw_frames=raw_frames,
        samples=samples,
        debug_pngs=debug,
    )


def _short_tracklet_label(tracklet_id: str) -> str:
    """Show the run-local ordinal on the crop; the replay panel maps it to full ID."""
    ordinal = tracklet_id.rsplit("-", 1)[-1]
    return f"T{int(ordinal):04d}"


def _tracklet_label_position(
    point: tuple[int, int], width: int, height: int, label: str
) -> tuple[int, int]:
    """Keep the complete short marker within image bounds, including edge candidates."""
    text_size, baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.3, 1)
    x = max(0, min(point[0] + 5, width - text_size[0]))
    y = point[1] - 5
    if y - text_size[1] < 0:
        y = point[1] + text_size[1] + 5
    y = max(text_size[1], min(y, height - baseline))
    return x, y


def _associate(
    accepted: list[tuple[str, RawMinimapColorCandidate]],
    frame_index: int,
    source_pts: int,
    timebase_numerator: int,
    timebase_denominator: int,
    timestamp: float,
    run_id: str,
    active: dict[str, tuple[float, float, str, str, float, int, float]],
    ordinal: int,
    thresholds: AnonymousRunnerThresholds,
) -> tuple[list[AnonymousTrackSample], int]:
    candidates = sorted(accepted, key=lambda item: item[0])
    previous = [
        (key, value)
        for key, value in active.items()
        if value[5] == frame_index - 1 and 0 < timestamp - value[6] <= thresholds.max_gap_seconds
    ]
    distances: dict[tuple[str, str], float] = {}
    for candidate_id, candidate in candidates:
        for track_id, (px, py, color, _prev_candidate, _, _, _) in previous:
            if color == candidate.broadcast_color:
                distances[(candidate_id, track_id)] = float(
                    np.hypot(candidate.crop_point.x - px, candidate.crop_point.y - py)
                )
    proposed: list[tuple[float, str, str]] = []
    for candidate_id, _ in candidates:
        choices = sorted(
            (distance, track_id)
            for (cid, track_id), distance in distances.items()
            if cid == candidate_id
        )
        if not choices or choices[0][0] > thresholds.max_step_crop_fraction:
            continue
        if len(choices) > 1 and choices[1][0] - choices[0][0] <= thresholds.ambiguity_margin:
            continue
        reverse = sorted(
            (distance, cid)
            for (cid, track_id), distance in distances.items()
            if track_id == choices[0][1]
        )
        if len(reverse) > 1 and reverse[1][0] - reverse[0][0] <= thresholds.ambiguity_margin:
            continue
        proposed.append((choices[0][0], candidate_id, choices[0][1]))
    assignments: dict[str, tuple[str, float]] = {}
    used_tracks: set[str] = set()
    for distance, candidate_id, track_id in sorted(proposed):
        if track_id not in used_tracks:
            assignments[candidate_id] = (track_id, distance)
            used_tracks.add(track_id)
    result: list[AnonymousTrackSample] = []
    for candidate_id, candidate in candidates:
        previous_association = assignments.get(candidate_id)
        evidence_ids: tuple[str, ...]
        if previous_association is None:
            track_id = f"anon-{run_id}-{ordinal:04d}"
            ordinal += 1
            distance = 0.0
            evidence_ids = (candidate_id,)
            association_confidence = 0.0
        else:
            track_id, distance = previous_association
            previous_candidate = active[track_id][3]
            evidence_ids = (previous_candidate, candidate_id)
            association_confidence = max(
                0.0, min(1.0, 1.0 - distance / thresholds.max_step_crop_fraction)
            )
        active[track_id] = (
            candidate.crop_point.x,
            candidate.crop_point.y,
            candidate.broadcast_color,
            candidate_id,
            candidate.detector_confidence,
            frame_index,
            timestamp,
        )
        result.append(
            AnonymousTrackSample(
                manifest_sha256="0" * 64,
                runner_manifest_sha256="0" * 64,
                frame_index=frame_index,
                source_pts=source_pts,
                timebase_numerator=timebase_numerator,
                timebase_denominator=timebase_denominator,
                timestamp_s=timestamp,
                tracklet_id=track_id,
                candidate_id=candidate_id,
                broadcast_color=candidate.broadcast_color,
                crop_x_normalized=candidate.crop_point.x,
                crop_y_normalized=candidate.crop_point.y,
                confidence=candidate.detector_confidence,
                association_confidence=association_confidence,
                evidence_candidate_ids=evidence_ids,
                motion_distance_crop_fraction=distance,
            )
        )
    return result, ordinal
