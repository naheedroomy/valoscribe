"""Opt-in, offline spatial template-rank experiment over a frozen PTS crop grid."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path, PurePosixPath
from typing import Any, Literal

import cv2
import numpy as np

from valoscribe.types.portrait_experiment import (
    PortraitDebugFrame,
    PortraitExperimentDiagnostics,
    PortraitExperimentManifest,
    PortraitFrameRanking,
    PortraitRawRank,
    PortraitTemplateProvenance,
)

WINDOWS = (
    ("Neon", 15728, 4026368, 110, 114),
    ("Cypher", 15728, 4026368, 67, 184),
    ("Jett", 17588, 4502528, 190, 137),
    ("Chamber", 19268, 4932608, 328, 102),
)

_APPROVED_SOURCE_MANIFEST_SHA256 = (
    "95adb564bf8a2a1858063b280fb5e8eacb186f395e52711f80b9329579228f10"
)
_APPROVED_REVIEW_SHA256 = "e0999d3859a08e905ba0c04deece83c052f3afbebb8a7e6b97dd8f6b06f3c872"
_APPROVED_SOURCE_VIDEO_SHA256 = "a2feb25b842b6c1c2baa17f8ef0c5ecfe1816bd058a1c256350fa95900454c44"
_APPROVED_TIME_BASE = "1/15360"
_APPROVED_CROP_RECT = (70, 50, 360, 400)


@dataclass(frozen=True)
class _ExperimentProtocol:
    """Private input binding; only production entrypoint can claim AI review."""

    source_manifest_sha256: str
    review_sha256: str
    source_video_sha256: str
    time_base: str
    crop_rect: tuple[int, int, int, int]
    review_status: Literal["ai_reviewed_not_human_gold", "unreviewed_synthetic_test"]


_PRODUCTION_PROTOCOL = _ExperimentProtocol(
    source_manifest_sha256=_APPROVED_SOURCE_MANIFEST_SHA256,
    review_sha256=_APPROVED_REVIEW_SHA256,
    source_video_sha256=_APPROVED_SOURCE_VIDEO_SHA256,
    time_base=_APPROVED_TIME_BASE,
    crop_rect=_APPROVED_CROP_RECT,
    review_status="ai_reviewed_not_human_gold",
)


def run_portrait_experiment(
    source_root: Path,
    output_dir: Path,
    review_path: Path,
) -> PortraitExperimentManifest:
    """Run only against the pinned reviewed source packet and adjudication."""
    return _run_experiment(source_root, output_dir, review_path, _PRODUCTION_PROTOCOL)


def _run_synthetic_fixture_experiment_for_tests(
    source_root: Path,
    output_dir: Path,
    review_path: Path,
) -> PortraitExperimentManifest:
    """Exercise the algorithm using explicitly unreviewed synthetic fixtures only."""
    source_root = source_root.resolve()
    source_manifest = (source_root / "manifest.json").read_bytes()
    decoded = json.loads(source_manifest)
    if decoded.get("packet_kind") != "synthetic_unit_fixture":
        raise ValueError("synthetic experiment helper requires synthetic_unit_fixture packet")
    protocol = _ExperimentProtocol(
        source_manifest_sha256=hashlib.sha256(source_manifest).hexdigest(),
        review_sha256=_sha256_file(review_path),
        source_video_sha256="0" * 64,
        time_base=_APPROVED_TIME_BASE,
        crop_rect=_APPROVED_CROP_RECT,
        review_status="unreviewed_synthetic_test",
    )
    return _run_experiment(source_root, output_dir, review_path, protocol)


def _run_experiment(
    source_root: Path,
    output_dir: Path,
    review_path: Path,
    protocol: _ExperimentProtocol,
) -> PortraitExperimentManifest:
    source_root = source_root.resolve()
    output_dir = output_dir.resolve()
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite experiment directory: {output_dir}")
    manifest_path = source_root / "manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
    if manifest_digest != protocol.source_manifest_sha256:
        raise ValueError("source manifest digest does not match the fixed experiment protocol")
    review_digest = _sha256_file(review_path)
    if review_digest != protocol.review_sha256:
        raise ValueError("review digest does not match the fixed experiment protocol")
    source_manifest = json.loads(manifest_bytes)
    image_rows = _validate_source_manifest(source_manifest, protocol)
    frame_rows = {int(row["frame_index"]): row for row in image_rows}
    templates: list[tuple[PortraitTemplateProvenance, np.ndarray]] = []
    for agent, frame, pts, x, y in WINDOWS:
        row = frame_rows.get(frame)
        if row is None or int(row["source_pts"]) != pts:
            raise ValueError(f"template PTS join mismatch: frame={frame} pts={pts}")
        crop_meta = row["candidate_crop_png"]
        crop_path = _within_root(source_root, crop_meta["path"])
        payload = crop_path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if digest != crop_meta["sha256"]:
            raise ValueError(f"candidate crop PNG hash mismatch: {crop_path.name}")
        image = _decode_crop(payload, crop_path.name)
        _verify_crop_pixels(image, crop_meta, crop_path.name)
        window = image[y : y + 20, x : x + 20]
        if window.shape != (20, 20, 3):
            raise ValueError(f"template window outside crop: {agent}")
        template_id = f"{agent.lower()}-f{frame}-pts{pts}-xy{x}-{y}-20x20"
        provenance = PortraitTemplateProvenance(
            template_id=template_id,
            agent_id=agent,
            frame_index=frame,
            source_pts=pts,
            x=x,
            y=y,
            width=20,
            height=20,
            source_crop_png_sha256=digest,
            review_status=protocol.review_status,
        )
        templates.append((provenance, window.copy()))

    template_bytes = _canonical_json([item.model_dump(mode="json") for item, _ in templates])
    seed_frames = {item.frame_index for item, _ in templates}
    raw_ranks: list[PortraitRawRank] = []
    debug_payloads: dict[str, bytes] = {}
    top_by_frame: list[PortraitFrameRanking] = []
    for row in image_rows:
        frame = int(row["frame_index"])
        pts = int(row["source_pts"])
        crop_meta = row["candidate_crop_png"]
        crop_path = _within_root(source_root, crop_meta["path"])
        payload = crop_path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if digest != crop_meta["sha256"]:
            raise ValueError(f"candidate crop PNG hash mismatch: {crop_path.name}")
        image = _decode_crop(payload, crop_path.name)
        _verify_crop_pixels(image, crop_meta, crop_path.name)
        timestamp = str(row["timestamp_seconds"])
        frame_ranks: list[PortraitRawRank] = []
        for provenance, template in templates:
            result = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
            _, score, _, location = cv2.minMaxLoc(result)
            rank = PortraitRawRank(
                frame_index=frame,
                source_pts=pts,
                timestamp_seconds=timestamp,
                template_id=provenance.template_id,
                agent_id=provenance.agent_id,
                score=float(score),
                x=int(location[0]),
                y=int(location[1]),
                width=20,
                height=20,
                candidate_crop_png_sha256=digest,
                seed_frame=frame in seed_frames,
            )
            raw_ranks.append(rank)
            frame_ranks.append(rank)
        frame_ranks.sort(key=lambda item: (-item.score, item.agent_id, item.template_id))
        overlay = image.copy()
        colors = ((0, 255, 0), (255, 180, 0), (255, 0, 255), (0, 220, 255))
        for rank_index, rank in enumerate(frame_ranks):
            color = colors[rank_index]
            cv2.rectangle(
                overlay,
                (rank.x, rank.y),
                (rank.x + rank.width - 1, rank.y + rank.height - 1),
                color,
                1,
            )
            cv2.putText(
                overlay,
                f"{rank_index + 1}:{rank.agent_id} {rank.score:.3f}",
                (2, 12 + rank_index * 12),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.32,
                color,
                1,
                cv2.LINE_AA,
            )
        ok, debug_png = cv2.imencode(".png", overlay)
        if not ok:
            raise ValueError(f"could not encode debug frame: {frame}")
        debug_name = f"frame-{frame:06d}-pts-{pts}-rankings.png"
        debug_payloads[debug_name] = debug_png.tobytes()
        top_by_frame.append(
            PortraitFrameRanking(
                frame_index=frame,
                source_pts=pts,
                seed_frame=frame in seed_frames,
                top_raw_match=frame_ranks[0],
                runner_up_raw_match=frame_ranks[1],
                resolution="unknown_uncalibrated_no_identity_assignment",
            )
        )

    ranks_bytes = _canonical_json([item.model_dump(mode="json") for item in raw_ranks])
    debug_index = [
        PortraitDebugFrame(path=name, sha256=hashlib.sha256(payload).hexdigest())
        for name, payload in sorted(debug_payloads.items())
    ]
    debug_index_bytes = _canonical_json([item.model_dump(mode="json") for item in debug_index])
    debug_digest = hashlib.sha256(debug_index_bytes).hexdigest()
    nonseed = [item.score for item in raw_ranks if not item.seed_frame]
    diagnostics = PortraitExperimentDiagnostics(
        schema_version="1.0",
        interpretation="diagnostic ranking only; not accuracy or identity predictions",
        frame_count=len(image_rows),
        raw_score_count=len(raw_ranks),
        seed_frames_excluded_from_nonseed_distribution=len(seed_frames),
        nonseed_score_count=len(nonseed),
        nonseed_score_min=min(nonseed),
        nonseed_score_median=float(np.median(nonseed)),
        nonseed_score_max=max(nonseed),
        top_raw_matches_by_frame=top_by_frame,
        all_sides="unknown",
        identity_resolution="none; calibration absent and templates incomplete",
        map_coordinates="not_emitted",
        full_window_templates_include_background=True,
        template_reviewer_status=protocol.review_status,
        debug_frame_count=len(debug_index),
        debug_frames=debug_index,
        debug_frame_semantics="top four sliding-window matches; not player detections",
    )
    diagnostics_bytes = _canonical_json(diagnostics.model_dump(mode="json"))
    output_dir.mkdir(parents=True)
    (output_dir / "template_bank.json").write_bytes(template_bytes)
    (output_dir / "raw_rankings.json").write_bytes(ranks_bytes)
    (output_dir / "derived_diagnostics.json").write_bytes(diagnostics_bytes)
    debug_dir = output_dir / "debug_frames"
    debug_dir.mkdir()
    for name, payload in debug_payloads.items():
        (debug_dir / name).write_bytes(payload)
    run_manifest = PortraitExperimentManifest(
        experiment_id="vta304-round4-neutral-portrait-experiment-v1",
        source_manifest_sha256=manifest_digest,
        template_bank_sha256=hashlib.sha256(template_bytes).hexdigest(),
        review_sha256=review_digest,
        raw_rankings_sha256=hashlib.sha256(ranks_bytes).hexdigest(),
        derived_diagnostics_sha256=hashlib.sha256(diagnostics_bytes).hexdigest(),
        debug_frames_sha256=debug_digest,
        frame_count=len(image_rows),
        template_count=len(templates),
        raw_rank_count=len(raw_ranks),
        seed_frame_count=len(seed_frames),
    )
    manifest_bytes_out = _canonical_json(run_manifest.model_dump(mode="json"))
    (output_dir / "manifest.json").write_bytes(manifest_bytes_out)
    _verify_readback(output_dir, run_manifest, image_rows)
    return run_manifest


def _validate_source_manifest(
    source_manifest: dict[str, Any], protocol: _ExperimentProtocol
) -> list[dict[str, Any]]:
    source = source_manifest.get("source")
    identity = source_manifest.get("source_identity")
    if not isinstance(source, dict) or source.get("sha256") != protocol.source_video_sha256:
        raise ValueError("source manifest video digest does not match protocol")
    if not isinstance(identity, dict) or any(
        identity.get(key) != protocol.source_video_sha256
        for key in ("expected_sha256", "sha256_before", "sha256_after")
    ) or identity.get("unchanged") is not True:
        raise ValueError("source manifest source identity provenance is incomplete or changed")
    metadata = source.get("reader_metadata")
    if not isinstance(metadata, dict):
        raise ValueError("source manifest native reader metadata is missing")
    if (
        metadata.get("timestamp_kind") != "pts"
        or f"{metadata.get('time_base_numerator')}/{metadata.get('time_base_denominator')}"
        != protocol.time_base
    ):
        raise ValueError("source manifest native timestamp provenance mismatch")
    image_rows = source_manifest.get("images")
    if not isinstance(image_rows, list) or len(image_rows) != 160:
        raise ValueError("source manifest must contain exactly 160 image rows")
    seen_frames: set[int] = set()
    seen_paths: set[str] = set()
    previous_frame = -1
    previous_pts = -1
    time_base = Fraction(protocol.time_base)
    for row in image_rows:
        required = {
            "frame_index",
            "source_pts",
            "timestamp_kind",
            "time_base",
            "timestamp_seconds",
            "timestamp_seconds_decimal",
            "decoded_bgr_sha256",
            "inventory_bgr_sha256",
            "candidate_crop_png",
            "candidate_crop_rect_xywh",
            "crop_config_sha256",
            "full_frame_png",
            "grid_targets_seconds",
        }
        if not isinstance(row, dict) or not required.issubset(row):
            raise ValueError("source frame row is missing timing or source inventory provenance")
        frame = row["frame_index"]
        pts = row["source_pts"]
        if not isinstance(frame, int) or not isinstance(pts, int) or frame < 0 or pts < 0:
            raise ValueError("source frame index and PTS must be nonnegative integers")
        if frame in seen_frames or frame <= previous_frame or pts <= previous_pts:
            raise ValueError("source frame/PTS rows must be unique and strictly increasing")
        seen_frames.add(frame)
        previous_frame, previous_pts = frame, pts
        if row["timestamp_kind"] != "pts" or row["time_base"] != protocol.time_base:
            raise ValueError(f"source timing provenance mismatch at frame {frame}")
        expected_time = Fraction(pts) * time_base
        try:
            actual_time = Fraction(row["timestamp_seconds"])
            decimal_time = float(row["timestamp_seconds_decimal"])
        except (TypeError, ValueError, ZeroDivisionError) as error:
            raise ValueError(f"invalid rational timestamp at frame {frame}") from error
        if actual_time != expected_time or not math.isclose(
            decimal_time, float(expected_time), rel_tol=0.0, abs_tol=1e-12
        ):
            raise ValueError(f"source timestamp does not match PTS/timebase at frame {frame}")
        if (
            not _is_sha256(row["decoded_bgr_sha256"])
            or row["decoded_bgr_sha256"] != row["inventory_bgr_sha256"]
        ):
            raise ValueError(f"native inventory pixel provenance mismatch at frame {frame}")
        if tuple(row["candidate_crop_rect_xywh"]) != protocol.crop_rect:
            raise ValueError(f"crop geometry mismatch at frame {frame}")
        if not _is_sha256(row["crop_config_sha256"]):
            raise ValueError(f"crop config provenance missing at frame {frame}")
        crop = row["candidate_crop_png"]
        full = row["full_frame_png"]
        if not isinstance(crop, dict) or not isinstance(full, dict):
            raise ValueError(f"source image provenance malformed at frame {frame}")
        for image_meta, dimensions in ((crop, [360, 400]), (full, [1920, 1080])):
            if (
                not isinstance(image_meta.get("path"), str)
                or not _is_sha256(image_meta.get("sha256"))
                or image_meta.get("dimensions_px") != dimensions
                or not isinstance(image_meta.get("size_bytes"), int)
            ):
                raise ValueError(f"source image provenance incomplete at frame {frame}")
        if not _is_sha256(crop.get("crop_bgr_sha256")) or crop["size_bytes"] <= 0:
            raise ValueError(f"candidate crop pixel/size provenance incomplete at frame {frame}")
        if crop["path"] in seen_paths:
            raise ValueError("source candidate crop paths must be unique")
        seen_paths.add(crop["path"])
        targets = row["grid_targets_seconds"]
        if not isinstance(targets, list) or any(not isinstance(t, str) for t in targets):
            raise ValueError(f"source grid targets malformed at frame {frame}")
    frames = {int(row["frame_index"]) for row in image_rows}
    if any(seed_frame not in frames for _, seed_frame, _, _, _ in WINDOWS):
        raise ValueError("approved template seed frame is absent from source grid")
    return image_rows


def _verify_readback(
    output_dir: Path,
    manifest: PortraitExperimentManifest,
    source_rows: list[dict[str, Any]],
) -> None:
    template_payload = (output_dir / "template_bank.json").read_bytes()
    ranking_payload = (output_dir / "raw_rankings.json").read_bytes()
    diagnostics_payload = (output_dir / "derived_diagnostics.json").read_bytes()
    if hashlib.sha256(template_payload).hexdigest() != manifest.template_bank_sha256:
        raise ValueError("template bank read-back hash mismatch")
    if hashlib.sha256(ranking_payload).hexdigest() != manifest.raw_rankings_sha256:
        raise ValueError("raw rankings read-back hash mismatch")
    if hashlib.sha256(diagnostics_payload).hexdigest() != manifest.derived_diagnostics_sha256:
        raise ValueError("derived diagnostics read-back hash mismatch")
    template_rows = [
        PortraitTemplateProvenance.model_validate(item)
        for item in json.loads(template_payload)
    ]
    ranks = [PortraitRawRank.model_validate(row) for row in json.loads(ranking_payload)]
    diagnostics = PortraitExperimentDiagnostics.model_validate_json(diagnostics_payload)
    if len(template_rows) != manifest.template_count or len(ranks) != manifest.raw_rank_count:
        raise ValueError("template/raw ranking read-back count mismatch")
    if (
        len(source_rows) != manifest.frame_count
        or len(diagnostics.top_raw_matches_by_frame) != manifest.frame_count
    ):
        raise ValueError("source frame/read-back diagnostic count mismatch")
    if (
        diagnostics.frame_count != manifest.frame_count
        or diagnostics.raw_score_count != manifest.raw_rank_count
        or diagnostics.seed_frames_excluded_from_nonseed_distribution != manifest.seed_frame_count
        or diagnostics.debug_frame_count != manifest.frame_count
    ):
        raise ValueError("derived diagnostics counts do not match run manifest")
    if {item.review_status for item in template_rows} != {diagnostics.template_reviewer_status}:
        raise ValueError("template review status does not match derived diagnostics")
    expected_windows = {
        (agent, frame, pts, x, y, 20, 20) for agent, frame, pts, x, y in WINDOWS
    }
    observed_windows = {
        (item.agent_id, item.frame_index, item.source_pts, item.x, item.y, item.width, item.height)
        for item in template_rows
    }
    if observed_windows != expected_windows:
        raise ValueError("template bank does not match fixed reviewed window selection")
    template_by_id = {item.template_id: item for item in template_rows}
    template_ids = set(template_by_id)
    if len(template_ids) != manifest.template_count:
        raise ValueError("template IDs must be unique")
    expected_by_frame = {int(row["frame_index"]): row for row in source_rows}
    for template in template_rows:
        source_row = expected_by_frame.get(template.frame_index)
        if (
            source_row is None
            or source_row["source_pts"] != template.source_pts
            or source_row["candidate_crop_png"]["sha256"]
            != template.source_crop_png_sha256
        ):
            raise ValueError("template provenance does not join to source manifest")
    if len(ranks) != manifest.frame_count * manifest.template_count:
        raise ValueError("raw rankings must cover every frame/template pair")
    seen_pairs: set[tuple[int, str]] = set()
    seed_frames = {item.frame_index for item in template_rows}
    for rank in ranks:
        row = expected_by_frame.get(rank.frame_index)
        if row is None or rank.source_pts != row["source_pts"]:
            raise ValueError("raw ranking frame/PTS does not join to source manifest")
        if rank.timestamp_seconds != row["timestamp_seconds"]:
            raise ValueError("raw ranking timestamp does not join to source manifest")
        if rank.candidate_crop_png_sha256 != row["candidate_crop_png"]["sha256"]:
            raise ValueError("raw ranking crop digest does not join to source manifest")
        matched_template = template_by_id.get(rank.template_id)
        if (
            matched_template is None
            or matched_template.agent_id != rank.agent_id
            or rank.seed_frame != (rank.frame_index in seed_frames)
        ):
            raise ValueError("raw ranking template/seed provenance mismatch")
        pair = (rank.frame_index, rank.template_id)
        if pair in seen_pairs:
            raise ValueError("duplicate frame/template raw ranking")
        seen_pairs.add(pair)
    for frame_diagnostic in diagnostics.top_raw_matches_by_frame:
        expected = expected_by_frame.get(frame_diagnostic.frame_index)
        if expected is None or expected["source_pts"] != frame_diagnostic.source_pts:
            raise ValueError("derived frame diagnostic does not join to source manifest")
        frame_rankings = {
            rank.template_id: rank
            for rank in ranks
            if rank.frame_index == frame_diagnostic.frame_index
        }
        if (
            frame_rankings.get(frame_diagnostic.top_raw_match.template_id)
            != frame_diagnostic.top_raw_match
            or frame_rankings.get(frame_diagnostic.runner_up_raw_match.template_id)
            != frame_diagnostic.runner_up_raw_match
        ):
            raise ValueError("derived top matches do not join to raw rankings")
        if frame_diagnostic.seed_frame != (frame_diagnostic.frame_index in seed_frames):
            raise ValueError("derived seed flag does not match source-template frames")

    debug_index_payload = _canonical_json(
        [item.model_dump(mode="json") for item in diagnostics.debug_frames]
    )
    if hashlib.sha256(debug_index_payload).hexdigest() != manifest.debug_frames_sha256:
        raise ValueError("debug frame index read-back hash mismatch")
    debug_dir = output_dir / "debug_frames"
    if debug_dir.is_symlink():
        raise ValueError("symbolic links are forbidden for the debug frame root")
    debug_root = debug_dir.resolve()
    try:
        debug_root.relative_to(output_dir.resolve())
    except ValueError as error:
        raise ValueError("debug frame root escapes experiment output") from error
    for item in diagnostics.debug_frames:
        debug_path = _within_root(debug_root, item.path)
        payload = debug_path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != item.sha256:
            raise ValueError("debug frame read-back hash mismatch")
    manifest_payload = (output_dir / "manifest.json").read_bytes()
    if manifest_payload != _canonical_json(manifest.model_dump(mode="json")):
        raise ValueError("run manifest read-back mismatch")


def _verify_crop_pixels(image: np.ndarray, metadata: dict[str, Any], name: str) -> None:
    digest = hashlib.sha256(image.tobytes()).hexdigest()
    if digest != metadata["crop_bgr_sha256"]:
        raise ValueError(f"candidate crop decoded-pixel hash mismatch: {name}")


def _decode_crop(payload: bytes, name: str) -> np.ndarray:
    image = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None or image.shape[:2] != (400, 360):
        raise ValueError(f"candidate crop dimensions invalid: {name}")
    return image


def _within_root(root: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or any(part in {".", ".."} for part in PurePosixPath(relative).parts):
        raise ValueError(f"output/source path must be relative and contained: {relative}")
    candidate = root / path
    current = root
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"symbolic links are forbidden in artifact paths: {relative}")
    resolved_root = root.resolve()
    candidate = candidate.resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as error:
        raise ValueError(f"artifact path escapes its root: {relative}") from error
    return candidate


def _canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        c in "0123456789abcdef" for c in value
    )


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
