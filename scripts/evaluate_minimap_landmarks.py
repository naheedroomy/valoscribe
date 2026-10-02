#!/usr/bin/env python3
"""Run opt-in labeled minimap registration evaluation against an external local VOD."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from valoscribe.commands.minimap import calibrate_video
from valoscribe.maps.landmarks import RegistrationLandmarkLabels

OFFLINE_MAX_ERROR_PX = 25.0


def summarize_samples(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize every expected sample, including failures, within its split."""
    errors = [
        error["error_px"]
        for sample in samples
        for error in (sample.get("reprojection") or {}).get("per_point_errors", [])
    ]
    successful = sum(sample.get("sample_error") is None for sample in samples)
    max_errors = {
        sample["sample_id"]: (sample.get("reprojection") or {}).get("maximum_error_px")
        for sample in samples
    }
    summary: dict[str, Any] = {
        "sample_count": len(samples),
        "evaluated_sample_count": successful,
        "error_sample_count": len(samples) - successful,
        "point_count": len(errors),
        "mean_error_px": sum(errors) / len(errors) if errors else None,
        "rms_error_px": (sum(error * error for error in errors) / len(errors)) ** 0.5
        if errors
        else None,
        "maximum_error_px": max(errors) if errors else None,
        "per_sample_maximum_error_px": max_errors,
        "gate_passed": bool(samples)
        and successful == len(samples)
        and len(errors) > 0
        and max(errors) <= OFFLINE_MAX_ERROR_PX,
    }
    return summary


def evaluate_manifest(
    video: Path,
    manifest_path: Path,
    hud_config: Path,
    map_config: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Evaluate manifest samples independently and fail closed on any sample defect."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    output_dir.mkdir(parents=True, exist_ok=True)
    by_split: dict[str, list[dict[str, Any]]] = {}
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="valoscribe-landmark-labels-") as temp_dir:
        temp_root = Path(temp_dir)
        for index, sample in enumerate(manifest.get("samples", [])):
            sample_id = f"sample-index-{index}"
            split = "unknown"
            timestamp: Any = None
            result: dict[str, Any] = {
                "sample_id": sample_id,
                "split": split,
                "timestamp_seconds": timestamp,
                "landmark_count": None,
                "registration_method": None,
                "registration_confidence": None,
                "alignment_error": None,
                "calibration_failure_reason": None,
                "source_frame_decoded_sha256": None,
                "reprojection": None,
                "sample_error": None,
            }
            try:
                if not isinstance(sample, dict):
                    raise ValueError("sample_must_be_object")
                sample_id = sample["sample_id"]
                split = sample["split"]
                timestamp = sample["timestamp_seconds"]
                if not isinstance(sample_id, str) or not sample_id.strip():
                    raise ValueError("sample_id_must_be_nonempty_string")
                if not isinstance(split, str) or not split.strip():
                    raise ValueError("split_must_be_nonempty_string")
                result.update(sample_id=sample_id, split=split, timestamp_seconds=timestamp)
                labels = RegistrationLandmarkLabels.model_validate(sample["labels"])
                labels_path = temp_root / f"{index}.json"
                labels_path.write_text(labels.model_dump_json(indent=2) + "\n", encoding="utf-8")
                diagnostics = calibrate_video(
                    video,
                    str(timestamp),
                    hud_config,
                    map_config,
                    output_dir / sample_id,
                    landmarks_path=labels_path,
                )
                evaluation = diagnostics.get("landmark_evaluation")
                result.update(
                    landmark_count=len(labels.landmarks),
                    registration_method=diagnostics.get("registration_method"),
                    registration_confidence=diagnostics.get("confidence"),
                    alignment_error=diagnostics.get("alignment_error"),
                    calibration_failure_reason=diagnostics.get("failure_reason"),
                    source_frame_decoded_sha256=diagnostics.get("source_frame_decoded_sha256"),
                )
                if diagnostics.get("registration_method") == "rejected":
                    result["sample_error"] = (
                        diagnostics.get("failure_reason") or "registration_failed"
                    )
                elif evaluation is None:
                    failure_reason = diagnostics.get("failure_reason")
                    if isinstance(failure_reason, str) and failure_reason.startswith("landmark_"):
                        result["sample_error"] = failure_reason
                    else:
                        detail = f":{failure_reason}" if failure_reason else ""
                        result["sample_error"] = f"reprojection_unavailable{detail}"
                else:
                    result["reprojection"] = {
                        key: value
                        for key, value in evaluation.items()
                        if key not in {
                            "acceptance_threshold_configured",
                            "maximum_error_threshold_px",
                            "passed",
                        }
                    }
            except Exception as exc:
                result.update(sample_id=sample_id, split=split)
                result["sample_error"] = f"{exc.__class__.__name__}:{exc}"
            results.append(result)
            by_split.setdefault(split, []).append(result)

    split_summaries = {
        split: summarize_samples(values) for split, values in sorted(by_split.items())
    }
    expected_count = len(manifest.get("samples", []))
    evaluated_count = sum(sample["sample_error"] is None for sample in results)
    gate_passed = (
        expected_count > 0
        and len(results) == expected_count
        and evaluated_count == expected_count
        and all(summary["gate_passed"] for summary in split_summaries.values())
    )
    return {
        "schema_version": "1.0",
        "evaluation_id": manifest.get("evaluation_id"),
        "evaluation_only": True,
        "acceptance_status": "not_assessed",
        "thresholds_used": None,
        "offline_manifest_gate": {
            "status": "passed" if gate_passed else "failed",
            "maximum_per_point_error_px": OFFLINE_MAX_ERROR_PX,
            "coordinate_space": "canonical image pixels",
            "expected_sample_count": expected_count,
            "evaluated_sample_count": evaluated_count,
            "error_sample_count": expected_count - evaluated_count,
            "split_coverage": {
                split: {
                    "expected_sample_count": summary["sample_count"],
                    "evaluated_sample_count": summary["evaluated_sample_count"],
                    "error_sample_count": summary["error_sample_count"],
                    "per_sample_maximum_error_px": summary["per_sample_maximum_error_px"],
                    "maximum_error_px": summary["maximum_error_px"],
                    "passed": summary["gate_passed"],
                }
                for split, summary in split_summaries.items()
            },
        },
        "samples": results,
        "splits": split_summaries,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True, help="External local VOD file")
    parser.add_argument("--manifest", type=Path, required=True, help="Reviewed landmark JSON")
    parser.add_argument("--hud-config", type=Path, required=True)
    parser.add_argument("--map-config", type=Path, required=True)
    parser.add_argument(
        "--output", type=Path, required=True, help="Directory for per-sample diagnostics"
    )
    args = parser.parse_args()
    report = evaluate_manifest(
        args.video, args.manifest, args.hud_config, args.map_config, args.output
    )
    report_path = args.output / "evaluation.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["offline_manifest_gate"]["status"] == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
