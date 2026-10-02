"""CFR crop-space MP4 replay with validated source-clock annotations."""

from __future__ import annotations

import hashlib
import os
from fractions import Fraction
from pathlib import Path

import cv2
import numpy as np

from valoscribe.tracking.provenance import read_bound_artifact
from valoscribe.types.anonymous_tracking import (
    AnonymousRawFrameObservation,
    AnonymousRunManifest,
    AnonymousTrackSample,
)

_PANEL_WIDTH = 680
_PANEL_TEXT_WIDTH = _PANEL_WIDTH - 36
_FONT = cv2.FONT_HERSHEY_SIMPLEX
_FONT_SCALE = 0.48
_LINE_HEIGHT = 22


def validate_replay_cadence(
    wrapper: AnonymousRunManifest,
    raw_frames: list[AnonymousRawFrameObservation],
) -> Fraction:
    """Require complete contiguous CFR observations; return exact final-frame duration."""
    manifest = wrapper.tracking_manifest
    expected_count = manifest.end_frame_index - manifest.start_frame_index + 1
    if len(raw_frames) != expected_count or len(raw_frames) < 2:
        raise ValueError("replay requires at least two complete bounded source frames")
    if raw_frames[0].provenance.source_pts != manifest.start_source_pts:
        raise ValueError("replay first frame does not match reviewed source PTS")
    if raw_frames[-1].provenance.source_pts != manifest.end_source_pts:
        raise ValueError("replay final frame does not match reviewed source PTS")
    for offset, row in enumerate(raw_frames):
        if row.provenance.frame_index != manifest.start_frame_index + offset:
            raise ValueError("replay source frame indices are not contiguous")
        if (
            row.provenance.timebase_numerator,
            row.provenance.timebase_denominator,
        ) != (manifest.timebase_numerator, manifest.timebase_denominator):
            raise ValueError("replay frame timebase differs from source manifest")

    frame_duration = Fraction(manifest.fps_denominator, manifest.fps_numerator)
    for prior, current in zip(raw_frames, raw_frames[1:]):
        observed_duration = Fraction(
            (current.provenance.source_pts - prior.provenance.source_pts)
            * manifest.timebase_numerator,
            manifest.timebase_denominator,
        )
        if observed_duration != frame_duration:
            raise ValueError("replay requires verified constant source PTS cadence")
    return frame_duration


def render_anonymous_replay(
    run_root: Path,
    wrapper: AnonymousRunManifest,
    raw_frames: list[AnonymousRawFrameObservation],
    samples: list[AnonymousTrackSample],
) -> Path:
    """Render a validated row snapshot; output times are exact only for verified CFR input."""
    manifest = wrapper.tracking_manifest
    frame_duration = validate_replay_cadence(wrapper, raw_frames)
    run_dir = run_root / manifest.run_id
    if run_dir.is_symlink():
        raise ValueError("anonymous replay directory must not be a symlink")
    output_path = run_dir / "anonymous_minimap_replay.mp4"
    frame_samples: dict[int, list[AnonymousTrackSample]] = {}
    for sample in samples:
        frame_samples.setdefault(sample.frame_index, []).append(sample)
    short_ids = _short_id_map(samples)
    panel_lines = {
        row.provenance.frame_index: _information_lines(
            row, frame_samples.get(row.provenance.frame_index, []), short_ids
        )
        for row in raw_frames
    }
    panel_height = max(
        raw_frames[0].crop_height,
        max(
            26 + sum(len(_wrap_line(line)) for line in lines) * _LINE_HEIGHT
            for lines in panel_lines.values()
        ),
    )
    video_size = (raw_frames[0].crop_width + _PANEL_WIDTH, panel_height)
    fps = manifest.fps_numerator / manifest.fps_denominator
    if not np.isfinite(fps) or fps <= 0:
        raise ValueError("source frame rate is invalid for diagnostic replay")

    try:
        descriptor = os.open(output_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise FileExistsError(f"replay output already exists: {output_path}") from error
    os.close(descriptor)

    try:
        writer = cv2.VideoWriter(
            str(output_path),
            getattr(cv2, "VideoWriter_fourcc")(*"mp4v"),
            fps,
            video_size,
        )
    except BaseException:
        output_path.unlink(missing_ok=True)
        raise
    if not writer.isOpened():
        output_path.unlink(missing_ok=True)
        raise RuntimeError("MP4 encoder unavailable for anonymous minimap replay")

    try:
        for row in raw_frames:
            relative_path = f"debug/candidates_{row.provenance.frame_index:08d}.png"
            payload = read_bound_artifact(
                run_root,
                manifest,
                relative_path,
                expected_run_id=manifest.run_id,
                expected_source_sha256=manifest.source_video_sha256,
                expected_config_sha256=manifest.config_sha256,
                expected_artifact_kind="anonymous_debug_png",
            )
            if hashlib.sha256(payload).hexdigest() != row.debug_png_sha256:
                raise ValueError("replay debug overlay digest differs from validated row")
            crop = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
            if crop is None or crop.shape[:2] != (row.crop_height, row.crop_width):
                raise ValueError("bound anonymous debug overlay cannot be decoded at crop size")
            frame = np.zeros((panel_height, video_size[0], 3), dtype=np.uint8)
            frame[: row.crop_height, : row.crop_width] = crop
            frame[:, row.crop_width :] = (22, 24, 29)
            _draw_information_panel(
                frame[:, row.crop_width :],
                row,
                panel_lines[row.provenance.frame_index],
            )
            writer.write(frame)
    except BaseException:
        writer.release()
        output_path.unlink(missing_ok=True)
        raise
    writer.release()
    _verify_finalized_video(output_path, len(raw_frames), video_size, fps, frame_duration)
    return output_path


def _short_id_map(samples: list[AnonymousTrackSample]) -> dict[str, str]:
    first_seen: dict[str, int] = {}
    for sample in samples:
        first_seen[sample.tracklet_id] = min(
            sample.frame_index, first_seen.get(sample.tracklet_id, sample.frame_index)
        )
    ordered_ids = sorted(first_seen, key=lambda track_id: (first_seen[track_id], track_id))
    return {track_id: f"T{ordinal:04d}" for ordinal, track_id in enumerate(ordered_ids, 1)}


def _information_lines(
    row: AnonymousRawFrameObservation,
    samples: list[AnonymousTrackSample],
    short_ids: dict[str, str],
) -> list[str]:
    timestamp = Fraction(
        row.provenance.source_pts * row.provenance.timebase_numerator,
        row.provenance.timebase_denominator,
    )
    lines = [
        "ANONYMOUS CANDIDATE TRACKLETS — NOT CONFIRMED PLAYERS",
        "Crop-space only; no identity, canonical map position, or tactics",
        (
            f"frame={row.provenance.frame_index} PTS={row.provenance.source_pts} "
            f"time={timestamp.numerator}/{timestamp.denominator}s context={row.context}"
        ),
    ]
    if row.context == "unknown":
        if row.context_evidence is None:
            lines.append("UNKNOWN CONTEXT: omitted and unreviewed")
        else:
            lines.append("UNKNOWN CONTEXT: reviewer could not classify this frame")
    if not samples:
        lines.append("NO OBSERVED TRACKLET SAMPLE; gaps are preserved, not interpolated")
    sample_by_candidate = {sample.candidate_id: sample for sample in samples}
    for candidate_index, item in enumerate(row.candidates, start=1):
        candidate = item.candidate
        candidate_short = f"C{candidate_index:04d}"
        lines.append(
            f"{candidate_short} raw_candidate={item.candidate_id} "
            f"accepted={candidate.accepted} detector={candidate.detector_confidence:.3f}"
        )
        sample = sample_by_candidate.get(item.candidate_id)
        if sample is not None:
            lines.append(
                f"{short_ids[sample.tracklet_id]} full_id={sample.tracklet_id} "
                f"candidate={candidate_short} detector={sample.confidence:.3f} "
                f"association={sample.association_confidence:.3f}"
            )
    return lines


def _wrap_line(text: str) -> list[str]:
    """Wrap all text to the panel width, including one unbroken long ID."""
    tokens = text.split(" ")
    output: list[str] = []
    current = ""
    for token in tokens:
        pieces = [token]
        if _text_width(token) > _PANEL_TEXT_WIDTH:
            pieces = []
            remaining = token
            while remaining:
                split_at = len(remaining)
                while split_at > 1 and _text_width(remaining[:split_at]) > _PANEL_TEXT_WIDTH:
                    split_at -= 1
                pieces.append(remaining[:split_at])
                remaining = remaining[split_at:]
        for piece in pieces:
            candidate = f"{current} {piece}".strip()
            if current and _text_width(candidate) > _PANEL_TEXT_WIDTH:
                output.append(current)
                current = piece
            else:
                current = candidate
    if current:
        output.append(current)
    return output


def _text_width(text: str) -> int:
    return cv2.getTextSize(text, _FONT, _FONT_SCALE, 1)[0][0]


def _draw_information_panel(
    panel: np.ndarray,
    row: AnonymousRawFrameObservation,
    lines: list[str],
) -> None:
    y = 26
    for index, text in enumerate(lines):
        color = (0, 220, 255) if index == 0 or text.startswith("UNKNOWN") else (235, 235, 235)
        for wrapped in _wrap_line(text):
            cv2.putText(
                panel,
                wrapped,
                (14, y),
                _FONT,
                _FONT_SCALE,
                color,
                1,
                cv2.LINE_AA,
            )
            y += _LINE_HEIGHT
    if y > panel.shape[0]:
        raise ValueError(
            f"replay information panel overflow at frame {row.provenance.frame_index}"
        )


def _verify_finalized_video(
    path: Path,
    expected_frames: int,
    expected_size: tuple[int, int],
    expected_fps: float,
    frame_duration: Fraction,
) -> None:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        path.unlink(missing_ok=True)
        raise RuntimeError("finalized anonymous replay cannot be opened")
    count = 0
    try:
        observed_fps = capture.get(cv2.CAP_PROP_FPS)
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if frame.shape[1::-1] != expected_size:
                raise RuntimeError("finalized anonymous replay frame dimensions changed")
            count += 1
    except BaseException:
        capture.release()
        path.unlink(missing_ok=True)
        raise
    capture.release()
    expected_duration = Fraction(expected_frames) * frame_duration
    observed_duration = count / observed_fps if observed_fps > 0 else 0
    if (
        not np.isfinite(observed_fps)
        or count != expected_frames
        or abs(observed_fps - expected_fps) > 1e-6
        or abs(observed_duration - float(expected_duration)) > float(frame_duration) / 1000
    ):
        path.unlink(missing_ok=True)
        raise RuntimeError(
            "finalized anonymous replay frame coverage or CFR duration does not match source"
        )
    if path.stat().st_size == 0:
        path.unlink(missing_ok=True)
        raise RuntimeError("anonymous minimap replay was not finalized")
