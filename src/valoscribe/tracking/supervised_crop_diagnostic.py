"""Explicitly supervised, crop-local diagnostic; never emits canonical tracks."""

from __future__ import annotations

import ctypes
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, cast

import cv2
import numpy as np

from valoscribe.detectors.cropper import Cropper
from valoscribe.detectors.minimap_color_detector import (
    MinimapColorCandidateDetector,
    MinimapColorProfile,
)
from valoscribe.tracking.assignment import _hungarian
from valoscribe.types.crop_diagnostic import (
    CropDiagnosticPolicy,
    CropDiagnosticPrediction,
    CropDiagnosticProvenance,
    CropDiagnosticSeedBinding,
)
from valoscribe.video.pts_reader import SequentialPtsVideoSource

POLICY = CropDiagnosticPolicy()
_DEPENDENCY_FILES = (
    "src/valoscribe/tracking/supervised_crop_diagnostic.py",
    "src/valoscribe/tracking/assignment.py",
    "src/valoscribe/detectors/minimap_color_detector.py",
    "src/valoscribe/detectors/cropper.py",
    "src/valoscribe/video/pts_reader.py",
    "src/valoscribe/types/crop_diagnostic.py",
    "src/valoscribe/types/persistent.py",
    "src/valoscribe/types/source_video.py",
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_noreplace_rename(source: Path, destination: Path) -> None:
    """Atomically publish a directory without replacing a concurrent destination."""
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        rename = getattr(libc, "renameatx_np", None)
        if rename is None:
            raise OSError("atomic no-replace rename is unavailable on this macOS")
        rename.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        result = rename(-2, os.fsencode(source), -2, os.fsencode(destination), 0x4)
    elif sys.platform.startswith("linux"):
        rename = getattr(libc, "renameat2", None)
        if rename is None:
            raise OSError("atomic no-replace rename is unavailable on this Linux")
        rename.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        result = rename(-100, os.fsencode(source), -100, os.fsencode(destination), 1)
    else:
        raise OSError("atomic no-replace rename is unsupported on this platform")
    if result != 0:
        error = ctypes.get_errno()
        if error == 17:
            raise FileExistsError(error, "destination already exists", str(destination))
        raise OSError(error, "atomic no-replace rename failed", str(destination))


def _algorithm_digest(inventory: dict[str, str]) -> str:
    return sha256_bytes(canonical_json(inventory))


def _dependency_inventory(project_root: Path) -> tuple[dict[str, str], str]:
    inventory = {name: _file_sha256(project_root / name) for name in _DEPENDENCY_FILES}
    return inventory, _algorithm_digest(inventory)


def _runtime_provenance(reader: Any) -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "opencv": cv2.__version__,
        "numpy": np.__version__,
        "pydantic": importlib.metadata.version("pydantic"),
        "ffmpeg": reader.metadata.ffmpeg_version,
        "ffprobe": reader.metadata.ffprobe_version,
    }


def associate_crop_candidates(
    player_id: str,
    frame_index: int,
    timestamp_s: float,
    candidates: list[tuple[str, tuple[float, float]]],
    previous: tuple[float, float] | None,
    previous_timestamp_s: float | None,
    policy: CropDiagnosticPolicy = POLICY,
    seed_uncertainty_px_each_axis: float | None = None,
) -> CropDiagnosticPrediction:
    """Assign via deterministic Hungarian motion cost or explicitly abstain."""
    common: dict[str, Any] = dict(
        frame_index=frame_index,
        timestamp_s=timestamp_s,
        player_id=player_id,
        seed_uncertainty_px_each_axis=seed_uncertainty_px_each_axis,
        identity_confidence="uncalibrated",
    )
    if not candidates:
        return CropDiagnosticPrediction(
            **common, status="missed", reason="no_accepted_color_candidates"
        )
    if previous is None or previous_timestamp_s is None:
        return CropDiagnosticPrediction(
            **common,
            status="abstained",
            reason="known_player_seed_candidate_missing",
        )
    gap = timestamp_s - previous_timestamp_s
    if gap <= 0 or gap > policy.max_gap_s:
        return CropDiagnosticPrediction(
            **common, status="abstained", reason="motion_history_gap_exceeded"
        )
    costs = [math.dist(previous, center) for _, center in candidates]
    selected = _hungarian([costs + [policy.maximum_cost_px]])[0]
    if selected >= len(candidates):
        return CropDiagnosticPrediction(
            **common, status="abstained", reason="motion_cost_exceeds_gate"
        )
    candidate_id, center = candidates[selected]
    alternatives = sorted(cost for index, cost in enumerate(costs) if index != selected)
    margin = alternatives[0] - costs[selected] if alternatives else None
    if costs[selected] > policy.max_motion_px_per_s * gap:
        return CropDiagnosticPrediction(
            **common,
            status="abstained",
            reason="motion_cost_exceeds_gate",
            selected_evidence_candidate_id=candidate_id,
            motion_cost_px=costs[selected],
            competitor_margin_px=margin,
        )
    if margin is not None and margin <= policy.ambiguity_margin_px:
        return CropDiagnosticPrediction(
            **common,
            status="abstained",
            reason="candidate_assignment_ambiguous",
            selected_evidence_candidate_id=candidate_id,
            motion_cost_px=costs[selected],
            competitor_margin_px=margin,
        )
    return CropDiagnosticPrediction(
        **common,
        candidate_id=candidate_id,
        selected_evidence_candidate_id=candidate_id,
        center_crop_px=center,
        status="associated",
        motion_cost_px=costs[selected],
        competitor_margin_px=margin,
    )


def _seed_prediction(
    player_id: str,
    frame_index: int,
    timestamp_s: float,
    center: tuple[float, float],
    candidates: list[tuple[str, tuple[float, float]]],
    policy: CropDiagnosticPolicy,
    uncertainty_px_each_axis: float,
) -> CropDiagnosticPrediction:
    if not candidates:
        raise ValueError("known-player seed has no accepted color candidate")
    ranked = sorted(
        (math.dist(center, point), candidate_id, point) for candidate_id, point in candidates
    )
    if ranked[0][0] > policy.seed_radius_px:
        raise ValueError("known-player seed has no candidate within fixed seed radius")
    if len(ranked) > 1 and ranked[1][0] - ranked[0][0] <= policy.ambiguity_margin_px:
        raise ValueError("known-player seed candidate is ambiguous")
    cost, candidate_id, point = ranked[0]
    return CropDiagnosticPrediction(
        frame_index=frame_index,
        timestamp_s=timestamp_s,
        player_id=player_id,
        candidate_id=candidate_id,
        selected_evidence_candidate_id=candidate_id,
        center_crop_px=point,
        status="seeded",
        motion_cost_px=cost,
        competitor_margin_px=ranked[1][0] - cost if len(ranked) > 1 else None,
        seed_uncertainty_px_each_axis=uncertainty_px_each_axis,
        identity_confidence="uncalibrated",
    )


def _validate_seed(
    seed: dict[str, Any],
    *,
    binding: CropDiagnosticSeedBinding,
    source_digest: str,
    crop_rect: tuple[int, int, int, int],
    start_timestamp_s: float,
) -> tuple[str, tuple[float, float]]:
    player_id, center = seed.get("player_id"), seed.get("center_crop_px")
    if not isinstance(player_id, str) or not player_id.strip():
        raise ValueError("seed requires a known player_id")
    if (
        not isinstance(center, list)
        or len(center) != 2
        or any(type(value) not in (int, float) or not math.isfinite(value) for value in center)
    ):
        raise ValueError("seed requires finite center_crop_px")
    if seed.get("timestamp_s") != start_timestamp_s or binding.timestamp_s != start_timestamp_s:
        raise ValueError("diagnostic start timestamp must equal the bound seed timestamp")
    if binding.frame_index != round(start_timestamp_s * 60):
        raise ValueError("seed frame index does not match its source timestamp")
    if seed.get("frame_index") != binding.frame_index:
        raise ValueError("seed annotation frame index does not match source binding")
    if seed.get("uncertainty_px_each_axis") != binding.uncertainty_px_each_axis:
        raise ValueError("seed annotation uncertainty does not match source binding")
    if binding.source_video_sha256 != source_digest:
        raise ValueError("seed source-video hash does not match diagnostic source")
    if (binding.crop_x, binding.crop_y, binding.crop_width, binding.crop_height) != crop_rect:
        raise ValueError("seed crop origin and dimensions do not match the configured crop")
    if seed.get("coordinate_frame") != "configured_minimap_crop_pixels":
        raise ValueError("seed coordinate frame is not the configured minimap crop")
    if (
        tuple(center)[0] < 0
        or tuple(center)[0] >= crop_rect[2]
        or tuple(center)[1] < 0
        or tuple(center)[1] >= crop_rect[3]
    ):
        raise ValueError("seed center lies outside the configured minimap crop")
    return player_id, (float(center[0]), float(center[1]))


def run_supervised_crop_diagnostic(
    *,
    source_path: Path,
    hud_config_path: Path,
    color_profile_path: Path,
    seed_path: Path,
    output_path: Path,
    start_timestamp_s: float,
    end_timestamp_s: float,
) -> Path:
    """Freeze a fully bound run in a staging directory, atomically publishing on success."""
    output_path = output_path.absolute()
    if output_path.exists():
        raise FileExistsError(f"frozen diagnostic output already exists: {output_path}")
    if start_timestamp_s < 0 or end_timestamp_s < start_timestamp_s:
        raise ValueError("diagnostic timestamp bounds are invalid")
    source_path = source_path.resolve(strict=True)
    hud_config_path = hud_config_path.resolve(strict=True)
    color_profile_path = color_profile_path.resolve(strict=True)
    seed_path = seed_path.resolve(strict=True)
    seed_bytes = seed_path.read_bytes()
    seed = json.loads(seed_bytes)
    binding_data = seed.get("source_binding")
    if not isinstance(binding_data, dict):
        raise ValueError(
            "seed requires measured source_binding; unbound legacy seeds are not accepted"
        )
    binding = CropDiagnosticSeedBinding.model_validate(binding_data)
    hud_bytes = hud_config_path.read_bytes()
    hud = json.loads(hud_bytes)
    profile_bytes = color_profile_path.read_bytes()
    profile = MinimapColorProfile.model_validate_json(profile_bytes)
    crop = hud.get("minimap")
    if not isinstance(crop, dict):
        raise ValueError("HUD config requires a minimap rectangle")
    x, y, width, height = (crop.get(key) for key in ("x", "y", "width", "height"))
    crop_rect = (x, y, width, height)
    if any(type(value) is not int for value in crop_rect) or (width, height) != (360, 400):
        raise ValueError("development seed is valid only for an integer 360x400 minimap crop")
    crop_rect_typed = cast(tuple[int, int, int, int], crop_rect)
    source_digest = _file_sha256(source_path)
    player_id, center = _validate_seed(
        seed,
        binding=binding,
        source_digest=source_digest,
        crop_rect=crop_rect_typed,
        start_timestamp_s=start_timestamp_s,
    )
    seed_frame = binding.frame_index
    last_frame = round(end_timestamp_s * 60)
    if (
        abs(seed_frame / 60 - start_timestamp_s) > 1e-7
        or abs(last_frame / 60 - end_timestamp_s) > 1e-7
    ):
        raise ValueError("diagnostic timestamps must align to the source 60-fps frame grid")

    project_root = Path(__file__).resolve().parents[3]
    dependency_digests, algorithm_digest = _dependency_inventory(project_root)
    code_digest = dependency_digests["src/valoscribe/tracking/supervised_crop_diagnostic.py"]
    policy_bytes = canonical_json(POLICY.model_dump(mode="json")) + b"\n"
    parent = output_path.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output_path.name}.staging-", dir=parent))
    try:
        debug_dir = staging / "debug"
        debug_dir.mkdir()
        detector = MinimapColorCandidateDetector(profile)
        cropper = Cropper(hud_config_path)
        raw: list[dict[str, Any]] = []
        predictions: list[CropDiagnosticPrediction] = []
        previous: tuple[float, float] | None = None
        previous_time: float | None = None
        with SequentialPtsVideoSource(source_path) as reader:
            if (
                reader.metadata.width,
                reader.metadata.height,
                reader.metadata.fps_numerator / reader.metadata.fps_denominator,
            ) != (1920, 1080, 60):
                raise ValueError(
                    "source does not match registered 1920x1080 60-fps diagnostic inputs"
                )
            runtime = _runtime_provenance(reader)
            for frame in reader:
                if frame.frame_index < seed_frame or frame.frame_index > last_frame:
                    continue
                if (frame.frame_index - seed_frame) % 30:
                    continue
                timestamp = float(frame.timestamp_seconds)
                if abs(timestamp - frame.frame_index / 60) > 1e-6:
                    raise ValueError(
                        "decoded source PTS does not match the frozen half-second frame grid"
                    )
                minimap = cropper.crop_minimap(frame.bgr)
                if minimap.shape != (crop_rect_typed[3], crop_rect_typed[2], 3):
                    raise ValueError(
                        "decoded crop raster does not match the exact bound crop dimensions"
                    )
                decoded_frame_hash = sha256_bytes(np.ascontiguousarray(frame.bgr).tobytes())
                decoded_crop_hash = sha256_bytes(np.ascontiguousarray(minimap).tobytes())
                encoded_ok, encoded_png = cv2.imencode(".png", minimap)
                if not encoded_ok:
                    raise RuntimeError("failed encoding minimap crop PNG")
                encoded_crop_hash = sha256_bytes(encoded_png.tobytes())
                if frame.frame_index == seed_frame:
                    if timestamp != binding.timestamp_s:
                        raise ValueError("decoded seed timestamp differs from bound timestamp")
                    if decoded_frame_hash != binding.decoded_frame_bgr_sha256:
                        raise ValueError("decoded seed BGR frame hash does not match seed binding")
                    if decoded_crop_hash != binding.decoded_crop_bgr_sha256:
                        raise ValueError("decoded seed BGR crop hash does not match seed binding")
                detection = detector.detect(
                    minimap, vod_timestamp_s=timestamp, source_frame=frame.frame_index
                )
                rows: list[dict[str, Any]] = []
                accepted: list[tuple[str, tuple[float, float]]] = []
                for index, candidate in enumerate(detection.candidates):
                    candidate_id = f"f{frame.frame_index:08d}-c{index:04d}"
                    row = candidate.model_dump(mode="json")
                    row["candidate_id"] = candidate_id
                    rows.append(row)
                    if candidate.accepted:
                        accepted.append(
                            (
                                candidate_id,
                                (
                                    candidate.crop_point.x * crop_rect_typed[2],
                                    candidate.crop_point.y * crop_rect_typed[3],
                                ),
                            )
                        )
                if frame.frame_index == seed_frame:
                    prediction = _seed_prediction(
                        player_id,
                        frame.frame_index,
                        timestamp,
                        center,
                        accepted,
                        POLICY,
                        binding.uncertainty_px_each_axis,
                    )
                else:
                    prediction = associate_crop_candidates(
                        player_id,
                        frame.frame_index,
                        timestamp,
                        accepted,
                        previous,
                        previous_time,
                        POLICY,
                        binding.uncertainty_px_each_axis,
                    )
                if prediction.center_crop_px is not None:
                    previous, previous_time = prediction.center_crop_px, timestamp
                    point = tuple(round(value) for value in prediction.center_crop_px)
                    cv2.circle(detection.debug_overlay, point, 8, (255, 255, 255), 2)
                    cv2.putText(
                        detection.debug_overlay,
                        f"{player_id}:{prediction.status}",
                        (point[0] + 5, max(12, point[1] - 8)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.35,
                        (255, 255, 255),
                        1,
                        cv2.LINE_AA,
                    )
                predictions.append(prediction)
                raw.append(
                    {
                        "frame_index": frame.frame_index,
                        "timestamp_s": timestamp,
                        "crop": {"x": x, "y": y, "width": width, "height": height},
                        "source_video_sha256": source_digest,
                        "seed_binding": {
                            **binding.model_dump(mode="json"),
                            "crop": {"x": x, "y": y, "width": width, "height": height},
                        },
                        "coordinate_frame": "configured_minimap_crop_pixels",
                        "decoded_frame_bgr_sha256": decoded_frame_hash,
                        "decoded_crop_bgr_sha256": decoded_crop_hash,
                        "decoded_crop_bgr_convention": "uint8 contiguous HxWx3 BGR row-major bytes",
                        "encoded_crop_png_sha256": encoded_crop_hash,
                        "candidates": rows,
                    }
                )
                if frame.frame_index == seed_frame and prediction.status != "seeded":
                    raise ValueError("known-player seed was not established")
                if (
                    frame.frame_index in {seed_frame, last_frame}
                    or (frame.frame_index - seed_frame) % 60 == 0
                ):
                    if not cv2.imwrite(
                        str(debug_dir / f"crop_{frame.frame_index:08d}.png"),
                        detection.debug_overlay,
                    ):
                        raise RuntimeError("failed writing crop-space debug overlay")
            if not reader.complete_stream_verified:
                raise RuntimeError("source video did not verify to EOF")
        expected_count = (last_frame - seed_frame) // 30 + 1
        if len(predictions) != expected_count:
            raise ValueError(
                f"decoded {len(predictions)} half-second samples; expected {expected_count}"
            )
        raw_bytes = b"".join(canonical_json(row) + b"\n" for row in raw)
        prediction_bytes = b"".join(
            canonical_json(row.model_dump(mode="json")) + b"\n" for row in predictions
        )
        outputs = {
            "raw_detections.jsonl": raw_bytes,
            "predictions.jsonl": prediction_bytes,
            "policy.json": policy_bytes,
        }
        for name, payload in outputs.items():
            (staging / name).write_bytes(payload)
        manifest = CropDiagnosticProvenance(
            source_video_sha256=source_digest,
            diagnostic_code_sha256=code_digest,
            dependency_file_sha256=dependency_digests,
            algorithm_sha256=algorithm_digest,
            runtime_provenance=runtime,
            color_profile_sha256=sha256_bytes(profile_bytes),
            hud_config_sha256=sha256_bytes(hud_bytes),
            crop_coordinate_config_sha256=sha256_bytes(hud_bytes),
            seed_sha256=sha256_bytes(seed_bytes),
            policy_sha256=sha256_bytes(policy_bytes),
            predictions_sha256=sha256_bytes(prediction_bytes),
            raw_detections_sha256=sha256_bytes(raw_bytes),
        )
        (staging / "manifest.json").write_bytes(
            canonical_json(manifest.model_dump(mode="json")) + b"\n"
        )
        metadata = {
            "schema_version": "1.0",
            "sample_count": len(predictions),
            "player_id": player_id,
            "start_timestamp_s": start_timestamp_s,
            "end_timestamp_s": end_timestamp_s,
            "coordinate_frame": "configured_minimap_crop_pixels",
            "source_filename": source_path.name,
            "source_video_sha256": source_digest,
            "crop": {"x": x, "y": y, "width": width, "height": height},
            "seed_sha256": sha256_bytes(seed_bytes),
            "seed_binding": {
                **binding.model_dump(mode="json"),
                "crop": {"x": x, "y": y, "width": width, "height": height},
            },
        }
        (staging / "run_metadata.json").write_bytes(canonical_json(metadata) + b"\n")
        if output_path.exists():
            raise FileExistsError(f"frozen diagnostic output already exists: {output_path}")
        _atomic_noreplace_rename(staging, output_path)
        return output_path
    finally:
        if staging.exists():
            shutil.rmtree(staging)
