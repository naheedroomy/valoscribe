"""Reproducible isolated scoring for explicitly raster-bound crop diagnostics."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from valoscribe.types.crop_diagnostic import (
    CropDiagnosticPolicy,
    CropDiagnosticPrediction,
    CropDiagnosticSeedBinding,
)
from valoscribe.types.persistent import RawMinimapColorCandidate

COORDINATE_TOLERANCE_PX_EACH_AXIS = 5.0
SCORING_POLICY = {
    "schema_version": "1.0",
    "source": "supplied approximate evaluator assumption; not a field in the gold fixture",
    "coordinate_tolerance_px_each_axis": COORDINATE_TOLERANCE_PX_EACH_AXIS,
    "matching": "exact frame, player, timestamp, accepted candidate and measured BGR rasters",
    "unmatched_reference_frame": "unscored; no interpolation or relabeling",
    "unbound_or_mismatched_raster": "pending; do not score",
}


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(data: bytes, name: str) -> Any:
    try:
        return json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError(f"{name} is not valid JSON") from None


def _records(data: bytes, name: str) -> list[dict[str, Any]]:
    try:
        records = [json.loads(line) for line in data.splitlines() if line.strip()]
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError(f"{name} contains invalid JSONL") from None
    if any(not isinstance(record, dict) for record in records):
        raise ValueError(f"{name} records must be JSON objects")
    return records


def _unique_by_frame(records: list[dict[str, Any]], name: str) -> dict[int, dict[str, Any]] | None:
    indexed: dict[int, dict[str, Any]] = {}
    for record in records:
        frame = record.get("frame_index")
        if type(frame) is not int or frame in indexed:
            return None
        indexed[frame] = record
    return indexed


def _pending(hashes: dict[str, str], frames: list[int]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "status": "pending_raster_binding",
        "scoring_policy": SCORING_POLICY,
        "input_sha256": hashes,
        "unmatched_frame_indices": frames,
        "metrics": None,
    }


def evaluate_crop_diagnostic(run_dir: Path, fixture_path: Path) -> dict[str, Any]:
    """Score only records with coherent provenance, candidate and raster evidence."""
    paths = {
        "fixture": fixture_path,
        "manifest": run_dir / "manifest.json",
        "metadata": run_dir / "run_metadata.json",
        "policy": run_dir / "policy.json",
        "predictions": run_dir / "predictions.jsonl",
        "raw": run_dir / "raw_detections.jsonl",
    }
    blobs = {name: path.read_bytes() for name, path in paths.items()}
    hashes = {
        "fixture_sha256": _sha_bytes(blobs["fixture"]),
        "manifest_sha256": _sha_bytes(blobs["manifest"]),
        "predictions_sha256": _sha_bytes(blobs["predictions"]),
        "raw_detections_sha256": _sha_bytes(blobs["raw"]),
        "scoring_policy_sha256": _sha_bytes(
            json.dumps(SCORING_POLICY, sort_keys=True, separators=(",", ":")).encode()
        ),
    }
    manifest = _json(blobs["manifest"], "manifest.json")
    try:
        CropDiagnosticPolicy.model_validate(_json(blobs["policy"], "policy.json"))
    except (ValueError, ValidationError):
        return _pending(hashes, [])
    expected = {
        "raw_detections_sha256": hashes["raw_detections_sha256"],
        "predictions_sha256": hashes["predictions_sha256"],
        "policy_sha256": _sha_bytes(blobs["policy"]),
    }
    for key, digest in expected.items():
        if manifest.get(key) != digest:
            raise ValueError(f"manifest {key} does not match consumed input bytes")
    fixture = _json(blobs["fixture"], "fixture")
    metadata = _json(blobs["metadata"], "run_metadata.json")
    if not isinstance(fixture, dict) or not isinstance(metadata, dict):
        return _pending(hashes, [])
    samples = fixture.get("samples")
    if not isinstance(samples, list) or any(not isinstance(sample, dict) for sample in samples):
        return _pending(hashes, [])
    visible = [sample for sample in samples if sample.get("visibility") == "visible"]
    visible_frames = [sample.get("frame_index") for sample in visible]
    if any(type(frame) is not int for frame in visible_frames):
        return _pending(hashes, [])
    frames = sorted(visible_frames)
    if len(set(frames)) != len(frames):
        return _pending(hashes, frames)
    raw_records = _records(blobs["raw"], "raw_detections.jsonl")
    prediction_records = _records(blobs["predictions"], "predictions.jsonl")
    raw, predictions = (
        _unique_by_frame(raw_records, "raw"),
        _unique_by_frame(prediction_records, "predictions"),
    )
    if raw is None or predictions is None:
        return _pending(hashes, frames)

    # Require the run's measured source/seed/crop context; old runs without it stay pending.
    crop = fixture.get("crop")
    binding = metadata.get("seed_binding")
    source_hash = manifest.get("source_video_sha256")
    source_name = fixture.get("source_filename")
    seed_digest = metadata.get("seed_sha256")
    if (
        not isinstance(crop, dict)
        or not isinstance(binding, dict)
        or not isinstance(source_hash, str)
        or len(source_hash) != 64
        or any(char not in "0123456789abcdef" for char in source_hash)
        or not isinstance(seed_digest, str)
        or len(seed_digest) != 64
        or any(char not in "0123456789abcdef" for char in seed_digest)
        or metadata.get("source_filename") != source_name
        or metadata.get("source_video_sha256") != source_hash
        or metadata.get("crop") != crop
        or binding.get("source_video_sha256") != source_hash
        or binding.get("crop") != crop
        or binding.get("coordinate_frame") != "configured_minimap_crop_pixels"
        or manifest.get("seed_sha256") != metadata.get("seed_sha256")
    ):
        return _pending(hashes, frames)
    scored_visible = []
    unmatched_frames = []
    for sample in visible:
        frame = sample["frame_index"]
        if frame not in raw and frame not in predictions:
            unmatched_frames.append(frame)
        elif frame not in raw or frame not in predictions:
            return _pending(hashes, [frame])
        else:
            scored_visible.append(sample)

    validated_predictions: dict[int, CropDiagnosticPrediction] = {}
    try:
        typed_binding = CropDiagnosticSeedBinding.model_validate(
            {key: value for key, value in binding.items() if key != "crop"}
        )
        if typed_binding.source_video_sha256 != source_hash or (
            typed_binding.crop_x,
            typed_binding.crop_y,
            typed_binding.crop_width,
            typed_binding.crop_height,
        ) != (crop["x"], crop["y"], crop["width"], crop["height"]):
            return _pending(hashes, frames)
        binding_frame = typed_binding.frame_index
        binding_ts = typed_binding.timestamp_s
        seed_raw = raw.get(binding_frame)
        seed_prediction = predictions.get(binding_frame)
        expected_player = f"{fixture['label']['team_id']}:{fixture['label']['player_id']}"
        if (
            seed_raw is None
            or seed_prediction is None
            or seed_raw.get("timestamp_s") != binding_ts
            or seed_raw.get("crop") != crop
            or seed_raw.get("source_video_sha256") != source_hash
            or seed_raw.get("seed_binding") != binding
            or seed_raw.get("decoded_frame_bgr_sha256")
            != typed_binding.decoded_frame_bgr_sha256
            or seed_raw.get("decoded_crop_bgr_sha256") != typed_binding.decoded_crop_bgr_sha256
        ):
            return _pending(hashes, [binding_frame])
        typed_seed_prediction = CropDiagnosticPrediction.model_validate(seed_prediction)
        if (
            typed_seed_prediction.frame_index != binding_frame
            or typed_seed_prediction.timestamp_s != binding_ts
            or typed_seed_prediction.player_id != expected_player
            or typed_seed_prediction.status != "seeded"
        ):
            return _pending(hashes, [binding_frame])
        seed_candidates = seed_raw.get("candidates")
        seed_match = (
            [
                candidate
                for candidate in seed_candidates
                if isinstance(candidate, dict)
                and candidate.get("candidate_id") == typed_seed_prediction.candidate_id
            ]
            if isinstance(seed_candidates, list)
            else []
        )
        if (
            len(seed_match) != 1
            or seed_match[0].get("accepted") is not True
            or seed_match[0].get("source_frame") != binding_frame
            or seed_match[0].get("vod_timestamp_s") != binding_ts
        ):
            return _pending(hashes, [binding_frame])
        seed_point = seed_match[0].get("crop_point")
        if (
            not isinstance(seed_point, dict)
            or typed_seed_prediction.center_crop_px is None
            or any(
                abs(actual - expected) > 1e-6
                for actual, expected in zip(
                    typed_seed_prediction.center_crop_px,
                    (seed_point.get("x", -1) * crop["width"],
                     seed_point.get("y", -1) * crop["height"]),
                )
            )
        ):
            return _pending(hashes, [binding_frame])
        candidate_ids: set[str] = set()
        for raw_record in raw_records:
            candidates = raw_record.get("candidates")
            if not isinstance(candidates, list):
                return _pending(hashes, [raw_record["frame_index"]])
            for candidate_row in candidates:
                if not isinstance(candidate_row, dict):
                    return _pending(hashes, [raw_record["frame_index"]])
                candidate_id = candidate_row.get("candidate_id")
                if (
                    not isinstance(candidate_id, str)
                    or not candidate_id
                    or candidate_id in candidate_ids
                    or type(candidate_row.get("accepted")) is not bool
                ):
                    return _pending(hashes, [raw_record["frame_index"]])
                candidate_ids.add(candidate_id)
                typed_candidate = RawMinimapColorCandidate.model_validate(
                    {key: value for key, value in candidate_row.items() if key != "candidate_id"}
                )
                if (
                    typed_candidate.source_frame != raw_record["frame_index"]
                    or typed_candidate.vod_timestamp_s != raw_record.get("timestamp_s")
                ):
                    return _pending(hashes, [raw_record["frame_index"]])
        for sample in scored_visible:
            frame = sample["frame_index"]
            raw_record = raw[frame]
            pred = CropDiagnosticPrediction.model_validate(predictions[frame])
            sample_ts = sample["timestamp_s"]
            if (
                raw_record.get("frame_index") != frame
                or raw_record.get("timestamp_s") != sample_ts
                or raw_record.get("crop") != crop
                or raw_record.get("source_video_sha256") != source_hash
                or raw_record.get("seed_binding") != binding
                or raw_record.get("decoded_frame_bgr_sha256") != sample.get("decoded_frame_sha256")
                or raw_record.get("decoded_crop_bgr_sha256") != sample.get("decoded_crop_sha256")
                or pred.frame_index != frame
                or pred.timestamp_s != sample_ts
                or pred.player_id
                != f"{fixture['label']['team_id']}:{fixture['label']['player_id']}"
            ):
                return _pending(hashes, [frame])
            validated_predictions[frame] = pred
            if pred.status not in {"seeded", "associated"}:
                continue
            candidates = raw_record.get("candidates")
            if not isinstance(candidates, list) or pred.center_crop_px is None:
                return _pending(hashes, [frame])
            selected = [c for c in candidates if c.get("candidate_id") == pred.candidate_id]
            if len(selected) != 1:
                return _pending(hashes, [frame])
            candidate = selected[0]
            point = candidate.get("crop_point")
            if (
                candidate.get("accepted") is not True
                or candidate.get("source_frame") != frame
                or candidate.get("vod_timestamp_s") != sample_ts
                or not isinstance(point, dict)
            ):
                return _pending(hashes, [frame])
            measured_center = (
                point.get("x", -1) * crop["width"],
                point.get("y", -1) * crop["height"],
            )
            if any(abs(a - b) > 1e-6 for a, b in zip(pred.center_crop_px, measured_center)):
                return _pending(hashes, [frame])
            if frame == binding_frame and sample_ts == binding_ts:
                if binding.get("decoded_frame_bgr_sha256") != sample.get(
                    "decoded_frame_sha256"
                ) or binding.get("decoded_crop_bgr_sha256") != sample.get("decoded_crop_sha256"):
                    return _pending(hashes, [frame])
    except (KeyError, TypeError, ValueError, ValidationError):
        return _pending(hashes, frames)

    targets = [sample.get("icon_center_crop_px") for sample in scored_visible]
    if any(
        not isinstance(target, list)
        or len(target) != 2
        or any(type(value) not in (int, float) or not math.isfinite(value) for value in target)
        for target in targets
    ):
        return _pending(hashes, frames)
    if not scored_visible:
        return _pending(hashes, unmatched_frames)

    def within_tolerance(sample: dict[str, Any], target: list[float]) -> bool:
        center = validated_predictions[sample["frame_index"]].center_crop_px
        return center is not None and all(
            abs(actual - expected) <= COORDINATE_TOLERANCE_PX_EACH_AXIS
            for actual, expected in zip(center, target)
        )

    inside = sum(
        within_tolerance(sample, target)
        for sample, target in zip(scored_visible, targets)
    )
    return {
        "schema_version": "1.0",
        "status": "scored",
        "scoring_policy": SCORING_POLICY,
        "input_sha256": hashes,
        "unmatched_frame_indices": unmatched_frames,
        "metrics": {
            "visible_label_count": len(visible),
            "scored_visible_label_count": len(scored_visible),
            "associated_count": sum(
                prediction.status in {"seeded", "associated"}
                for prediction in validated_predictions.values()
            ),
            "inside_tolerance_count": inside,
        },
    }
