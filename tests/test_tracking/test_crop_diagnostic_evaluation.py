from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from valoscribe.tracking.crop_diagnostic_evaluation import (
    SCORING_POLICY,
    evaluate_crop_diagnostic,
)
from valoscribe.types.crop_diagnostic import CropDiagnosticPolicy


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_case(directory: Path) -> tuple[Path, Path]:
    directory.mkdir()
    crop = {"x": 70, "y": 50, "width": 360, "height": 400}
    source_hash, frame_hash, crop_hash = "a" * 64, "b" * 64, "c" * 64
    binding = {
        "schema_version": "1.0",
        "source_video_sha256": source_hash,
        "frame_index": 5,
        "timestamp_s": 5.0,
        "crop_x": 70,
        "crop_y": 50,
        "crop_width": 360,
        "crop_height": 400,
        "coordinate_frame": "configured_minimap_crop_pixels",
        "decoded_frame_bgr_sha256": frame_hash,
        "decoded_crop_bgr_sha256": crop_hash,
        "uncertainty_px_each_axis": 5.0,
        "crop": crop,
    }
    fixture_data = {
        "source_filename": "match.mp4",
        "crop": crop,
        "label": {"team_id": "100T", "player_id": "bang"},
        "samples": [
            {
                "frame_index": 5,
                "timestamp_s": 5.0,
                "visibility": "visible",
                "decoded_frame_sha256": frame_hash,
                "decoded_crop_sha256": crop_hash,
                "icon_center_crop_px": [10.0, 10.0],
            }
        ],
    }
    raw_data = [
        {
            "frame_index": 5,
            "timestamp_s": 5.0,
            "crop": crop,
            "source_video_sha256": source_hash,
            "seed_binding": binding,
            "decoded_frame_bgr_sha256": frame_hash,
            "decoded_crop_bgr_sha256": crop_hash,
            "candidates": [
                {
                    "candidate_id": "candidate-5",
                    "schema_version": "1.0",
                    "vod_timestamp_s": 5.0,
                    "source_frame": 5,
                    "color_profile_id": "test",
                    "broadcast_color": "blue",
                    "crop_point": {"x": 10 / 360, "y": 10 / 400},
                    "bounding_box": {
                        "x": 0.2,
                        "y": 0.2,
                        "width": 0.1,
                        "height": 0.1,
                    },
                    "contour_area_px": 10,
                    "mask_pixel_count": 11,
                    "detector_confidence": 0.5,
                    "accepted": True,
                }
            ],
        }
    ]
    prediction_data = [
        {
            "schema_version": "2.0",
            "frame_index": 5,
            "timestamp_s": 5.0,
            "player_id": "100T:bang",
            "candidate_id": "candidate-5",
            "selected_evidence_candidate_id": "candidate-5",
            "center_crop_px": [10.0, 10.0],
            "status": "seeded",
            "seed_uncertainty_px_each_axis": 5.0,
            "identity_confidence": "uncalibrated",
        }
    ]
    fixture = directory / "fixture.json"
    fixture.write_text(json.dumps(fixture_data))
    run = directory / "run"
    run.mkdir()
    raw_bytes = b"".join(
        json.dumps(item, separators=(",", ":")).encode() + b"\n" for item in raw_data
    )
    prediction_bytes = b"".join(
        json.dumps(item, separators=(",", ":")).encode() + b"\n" for item in prediction_data
    )
    policy_bytes = json.dumps(
        CropDiagnosticPolicy().model_dump(mode="json"), separators=(",", ":")
    ).encode()
    metadata = {
        "source_filename": "match.mp4",
        "source_video_sha256": source_hash,
        "crop": crop,
        "seed_sha256": "d" * 64,
        "seed_binding": binding,
    }
    (run / "raw_detections.jsonl").write_bytes(raw_bytes)
    (run / "predictions.jsonl").write_bytes(prediction_bytes)
    (run / "policy.json").write_bytes(policy_bytes)
    (run / "run_metadata.json").write_text(json.dumps(metadata))
    (run / "manifest.json").write_text(
        json.dumps(
            {
                "raw_detections_sha256": _digest(raw_bytes),
                "predictions_sha256": _digest(prediction_bytes),
                "policy_sha256": _digest(policy_bytes),
                "source_video_sha256": source_hash,
                "seed_sha256": metadata["seed_sha256"],
            }
        )
    )
    return run, fixture


def _rewrite_records(path: Path, records: list[dict[str, Any]]) -> bytes:
    data = b"".join(
        json.dumps(record, separators=(",", ":")).encode() + b"\n" for record in records
    )
    path.write_bytes(data)
    return data


def _refresh_manifest(run: Path, *, policy: bool = False) -> None:
    manifest_path = run / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for name, key in (
        ("raw_detections.jsonl", "raw_detections_sha256"),
        ("predictions.jsonl", "predictions_sha256"),
    ):
        manifest[key] = _digest((run / name).read_bytes())
    if policy:
        manifest["policy_sha256"] = _digest((run / "policy.json").read_bytes())
    manifest_path.write_text(json.dumps(manifest))


def test_coherent_measured_same_frame_evidence_is_scored(tmp_path: Path) -> None:
    run, fixture = _write_case(tmp_path / "case")
    result = evaluate_crop_diagnostic(run, fixture)
    assert result["status"] == "scored"
    assert result["metrics"] == {
        "visible_label_count": 1,
        "scored_visible_label_count": 1,
        "associated_count": 1,
        "inside_tolerance_count": 1,
    }
    assert result["scoring_policy"] == SCORING_POLICY


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_candidate",
        "wrong_candidate",
        "wrong_center",
        "wrong_player",
        "wrong_time",
        "wrong_source",
        "wrong_crop",
        "wrong_seed_binding",
        "duplicate_prediction",
        "duplicate_raw",
        "abstention_center",
        "malformed_center",
    "nan_candidate_point",
    "string_accepted",
    "missing_seed_digest",
    "missing_seed_frame",
    "wrong_seed_frame_hash",
    ],
)
def test_incoherent_or_duplicate_evidence_remains_pending(tmp_path: Path, mutation: str) -> None:
    run, fixture = _write_case(tmp_path / "case")
    raw_path, pred_path = run / "raw_detections.jsonl", run / "predictions.jsonl"
    raw = [json.loads(line) for line in raw_path.read_text().splitlines()]
    predictions = [json.loads(line) for line in pred_path.read_text().splitlines()]
    if mutation in {"nan_candidate_point", "string_accepted"}:
        candidate = raw[0]["candidates"][0]
        if mutation == "nan_candidate_point":
            candidate["crop_point"]["x"] = float("nan")
        else:
            candidate["accepted"] = "false"
        _rewrite_records(raw_path, raw)
        _refresh_manifest(run)
    elif mutation == "missing_seed_digest":
        manifest = json.loads((run / "manifest.json").read_text())
        manifest.pop("seed_sha256")
        (run / "manifest.json").write_text(json.dumps(manifest))
    elif mutation in {"missing_seed_frame", "wrong_seed_frame_hash"}:
        binding = raw[0]["seed_binding"]
        if mutation == "missing_seed_frame":
            binding["frame_index"] = 999
        else:
            binding["decoded_frame_bgr_sha256"] = "f" * 64
        metadata_path = run / "run_metadata.json"
        metadata = json.loads(metadata_path.read_text())
        metadata["seed_binding"] = binding
        metadata_path.write_text(json.dumps(metadata))
        _rewrite_records(raw_path, raw)
        _refresh_manifest(run)
    elif mutation in {
        "missing_candidate",
        "wrong_source",
        "wrong_crop",
        "wrong_seed_binding",
        "duplicate_raw",
    }:
        record = raw[0]
        if mutation == "missing_candidate":
            record["candidates"] = []
        elif mutation == "wrong_source":
            record["source_video_sha256"] = "e" * 64
        elif mutation == "wrong_crop":
            record["crop"]["width"] = 21
        elif mutation == "wrong_seed_binding":
            record["seed_binding"]["source_video_sha256"] = "e" * 64
        else:
            raw.append(record.copy())
        _rewrite_records(raw_path, raw)
        _refresh_manifest(run)
    elif mutation == "duplicate_prediction":
        predictions.append(predictions[0].copy())
        _rewrite_records(pred_path, predictions)
        _refresh_manifest(run)
    else:
        prediction = predictions[0]
        if mutation == "wrong_candidate":
            prediction["candidate_id"] = "not-in-raw"
            prediction["selected_evidence_candidate_id"] = "not-in-raw"
        elif mutation == "wrong_center":
            prediction["center_crop_px"] = [11.0, 10.0]
        elif mutation == "wrong_player":
            prediction["player_id"] = "LOUD:other"
        elif mutation == "wrong_time":
            prediction["timestamp_s"] = 5.5
        elif mutation == "abstention_center":
            prediction.update(status="abstained", reason="ambiguous")
        else:
            prediction["center_crop_px"] = []
        _rewrite_records(pred_path, predictions)
        _refresh_manifest(run)
    result = evaluate_crop_diagnostic(run, fixture)
    assert result["status"] == "pending_raster_binding"
    assert result["metrics"] is None


def test_valid_abstention_does_not_count_as_localization(tmp_path: Path) -> None:
    run, fixture = _write_case(tmp_path / "case")
    fixture_data = json.loads(fixture.read_text())
    fixture_data["samples"].append(
        {
            **fixture_data["samples"][0],
            "frame_index": 35,
            "timestamp_s": 5.5,
            "decoded_frame_sha256": "e" * 64,
            "decoded_crop_sha256": "f" * 64,
        }
    )
    fixture.write_text(json.dumps(fixture_data))
    raw_path, prediction_path = run / "raw_detections.jsonl", run / "predictions.jsonl"
    raw = json.loads(raw_path.read_text())
    raw["frame_index"], raw["timestamp_s"] = 35, 5.5
    raw["decoded_frame_bgr_sha256"], raw["decoded_crop_bgr_sha256"] = "e" * 64, "f" * 64
    raw["candidates"][0]["candidate_id"] = "candidate-35"
    raw["candidates"][0]["source_frame"] = 35
    raw["candidates"][0]["vod_timestamp_s"] = 5.5
    raw_path.write_bytes(
        (run / "raw_detections.jsonl").read_bytes()
        + json.dumps(raw, separators=(",", ":")).encode()
        + b"\n"
    )
    predictions = [json.loads(line) for line in prediction_path.read_text().splitlines()]
    second = predictions[0].copy()
    second.update(
        frame_index=35,
        timestamp_s=5.5,
        candidate_id="candidate-35",
        selected_evidence_candidate_id="candidate-35",
        status="associated",
        motion_cost_px=0.0,
    )
    predictions.append(second)
    _rewrite_records(prediction_path, predictions)
    _refresh_manifest(run)
    prediction = predictions[1]
    prediction.update(
        status="abstained",
        reason="ambiguous",
        candidate_id=None,
        selected_evidence_candidate_id=None,
        center_crop_px=None,
        motion_cost_px=None,
    )
    _rewrite_records(prediction_path, predictions)
    _refresh_manifest(run)
    result = evaluate_crop_diagnostic(run, fixture)
    assert result["status"] == "scored"
    assert result["metrics"] == {
        "visible_label_count": 2,
        "scored_visible_label_count": 2,
        "associated_count": 1,
        "inside_tolerance_count": 1,
    }


@pytest.mark.parametrize("samples", [[], [{"visibility": "hidden"}]])
def test_empty_visible_reference_set_stays_pending(
    tmp_path: Path, samples: list[dict[str, Any]]
) -> None:
    run, fixture = _write_case(tmp_path / "case")
    fixture_data = json.loads(fixture.read_text())
    fixture_data["samples"] = samples
    fixture.write_text(json.dumps(fixture_data))

    result = evaluate_crop_diagnostic(run, fixture)

    assert result["status"] == "pending_raster_binding"
    assert result["metrics"] is None


def test_visible_references_without_run_overlap_stay_pending(tmp_path: Path) -> None:
    run, fixture = _write_case(tmp_path / "case")
    fixture_data = json.loads(fixture.read_text())
    absent = dict(fixture_data["samples"][0])
    absent.update(
        frame_index=6,
        timestamp_s=6.0,
        decoded_frame_sha256="e" * 64,
        decoded_crop_sha256="f" * 64,
    )
    fixture_data["samples"] = [absent]
    fixture.write_text(json.dumps(fixture_data))

    result = evaluate_crop_diagnostic(run, fixture)

    assert result["status"] == "pending_raster_binding"
    assert result["unmatched_frame_indices"] == [6]
    assert result["metrics"] is None


@pytest.mark.parametrize("duplicate_kind", ["absent", "scored", "conflicting"])
def test_duplicate_visible_reference_frames_stay_pending(
    tmp_path: Path, duplicate_kind: str
) -> None:
    run, fixture = _write_case(tmp_path / "case")
    fixture_data = json.loads(fixture.read_text())
    duplicate = dict(fixture_data["samples"][0])
    if duplicate_kind == "absent":
        duplicate.update(
            frame_index=6,
            timestamp_s=6.0,
            decoded_frame_sha256="e" * 64,
            decoded_crop_sha256="f" * 64,
        )
        fixture_data["samples"] = [duplicate, dict(duplicate)]
    else:
        if duplicate_kind == "conflicting":
            duplicate["icon_center_crop_px"] = [100.0, 100.0]
        fixture_data["samples"].append(duplicate)
    fixture.write_text(json.dumps(fixture_data))

    result = evaluate_crop_diagnostic(run, fixture)

    assert result["status"] == "pending_raster_binding"
    assert result["metrics"] is None


def test_partial_overlap_with_only_abstentions_remains_scored(tmp_path: Path) -> None:
    run, fixture = _write_case(tmp_path / "case")
    fixture_data = json.loads(fixture.read_text())
    raw_path, prediction_path = run / "raw_detections.jsonl", run / "predictions.jsonl"
    raw_records = [json.loads(line) for line in raw_path.read_text().splitlines()]
    predictions = [json.loads(line) for line in prediction_path.read_text().splitlines()]
    visible_samples = []

    for frame, timestamp, frame_hash, crop_hash in (
        (35, 5.5, "e" * 64, "f" * 64),
        (40, 6.0, "1" * 64, "2" * 64),
    ):
        candidate_id = f"candidate-{frame}"
        raw = json.loads(json.dumps(raw_records[0]))
        raw.update(
            frame_index=frame,
            timestamp_s=timestamp,
            decoded_frame_bgr_sha256=frame_hash,
            decoded_crop_bgr_sha256=crop_hash,
        )
        candidate = raw["candidates"][0]
        candidate.update(
            candidate_id=candidate_id,
            source_frame=frame,
            vod_timestamp_s=timestamp,
        )
        raw_records.append(raw)

        prediction = predictions[0].copy()
        prediction.update(
            frame_index=frame,
            timestamp_s=timestamp,
            candidate_id=None,
            selected_evidence_candidate_id=None,
            center_crop_px=None,
            status="abstained",
            reason="ambiguous",
            motion_cost_px=None,
        )
        predictions.append(prediction)
        visible_samples.append(
            {
                "frame_index": frame,
                "timestamp_s": timestamp,
                "visibility": "visible",
                "decoded_frame_sha256": frame_hash,
                "decoded_crop_sha256": crop_hash,
                "icon_center_crop_px": [12.0, 13.0],
            }
        )

    missing_sample = {
        **visible_samples[0],
        "frame_index": 41,
        "timestamp_s": 6.5,
        "decoded_frame_sha256": "3" * 64,
        "decoded_crop_sha256": "4" * 64,
    }
    fixture_data["samples"] = [*visible_samples, missing_sample]
    fixture.write_text(json.dumps(fixture_data))
    _rewrite_records(raw_path, raw_records)
    _rewrite_records(prediction_path, predictions)
    _refresh_manifest(run)

    result = evaluate_crop_diagnostic(run, fixture)

    assert result["status"] == "scored"
    assert result["unmatched_frame_indices"] == [41]
    assert result["metrics"] == {
        "visible_label_count": 3,
        "scored_visible_label_count": 2,
        "associated_count": 0,
        "inside_tolerance_count": 0,
    }


def test_reference_frames_without_prediction_pair_are_reported_unscored(tmp_path: Path) -> None:
    run, fixture = _write_case(tmp_path / "case")
    fixture_data = json.loads(fixture.read_text())
    missing = {
        **fixture_data["samples"][0],
        "frame_index": 6,
        "timestamp_s": 6.0,
        "decoded_frame_sha256": "e" * 64,
        "decoded_crop_sha256": "f" * 64,
    }
    fixture_data["samples"].append(missing)
    fixture.write_text(json.dumps(fixture_data))

    result = evaluate_crop_diagnostic(run, fixture)

    assert result["status"] == "scored"
    assert result["unmatched_frame_indices"] == [6]
    assert result["metrics"] == {
        "visible_label_count": 2,
        "scored_visible_label_count": 1,
        "associated_count": 1,
        "inside_tolerance_count": 1,
    }


def test_wrong_policy_digest_fails_closed(tmp_path: Path) -> None:
    run, fixture = _write_case(tmp_path / "case")
    manifest = json.loads((run / "manifest.json").read_text())
    manifest["policy_sha256"] = "f" * 64
    (run / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="policy_sha256"):
        evaluate_crop_diagnostic(run, fixture)


def test_legacy_run_without_historical_seed_binding_stays_pending(tmp_path: Path) -> None:
    run, fixture = _write_case(tmp_path / "case")
    (run / "run_metadata.json").write_text(json.dumps({"source_filename": "match.mp4"}))
    result = evaluate_crop_diagnostic(run, fixture)
    assert result["status"] == "pending_raster_binding"
    assert result["metrics"] is None
