"""Offline minimap calibration commands."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import typer

from valoscribe.detectors.cropper import Cropper
from valoscribe.maps.config import MapDefinition
from valoscribe.maps.landmarks import (
    RegistrationLandmarkLabels,
    decoded_image_sha256,
    evaluate_registration_landmarks,
)
from valoscribe.maps.registration import MinimapRegistrar, RegistrationResult
from valoscribe.reporting.anonymous_diagnostic import (
    build_anonymous_diagnostic_report,
    write_anonymous_diagnostic_report,
)
from valoscribe.reporting.anonymous_replay import render_anonymous_replay
from valoscribe.tracking.anonymous_artifacts import read_anonymous_rows
from valoscribe.tracking.anonymous_runner import run_anonymous_round
from valoscribe.types.anonymous_report import AnonymousRoundInput
from valoscribe.types.anonymous_tracking import AnonymousRunManifest

app = typer.Typer(help="Minimap calibration and diagnostics", no_args_is_help=True)
calibrate_app = typer.Typer(help="Extract and register one minimap frame", no_args_is_help=True)
app.add_typer(calibrate_app, name="calibrate")


@app.command("track-anonymous-round")
def track_anonymous_round(
    video: Path = typer.Option(..., exists=True, dir_okay=False, help="Local source VOD"),
    review_manifest: Path = typer.Option(
        ..., exists=True, dir_okay=False, help="JSON with externally reviewed bounds/context"
    ),
    hud_config: Path = typer.Option(..., exists=True, dir_okay=False, help="HUD profile JSON"),
    color_config: Path = typer.Option(..., exists=True, dir_okay=False, help="Color profile JSON"),
    map_config: Path = typer.Option(..., exists=True, dir_okay=False, help="Map config JSON"),
    map_asset: Path = typer.Option(..., exists=True, dir_okay=False, help="Bound canonical asset"),
    output_root: Path = typer.Option(..., help="New output directory; existing paths are refused"),
    run_id: str = typer.Option(..., help="Safe diagnostic run identifier"),
    project_commit: str = typer.Option(..., help="Project commit or dirty-tree provenance label"),
    upstream_commit: str = typer.Option(..., help="Upstream commit provenance label"),
) -> None:
    """Run one evidence-bounded anonymous diagnostic and write reports/replay."""
    try:
        input_contract = AnonymousRoundInput.model_validate_json(
            review_manifest.read_bytes()
        )
    except (OSError, ValueError) as error:
        raise typer.BadParameter(f"invalid reviewed round manifest: {error}") from error
    target = output_root.absolute()
    if target.exists() or target.is_symlink():
        raise typer.BadParameter(f"output path already exists: {target}")
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    lock = target.with_name(f".{target.name}.anonymous-run.lock")
    try:
        lock.mkdir()
    except FileExistsError as error:
        raise typer.BadParameter(f"output path is locked by another run: {lock}") from error
    stage: Path | None = None
    try:
        stage = Path(tempfile.mkdtemp(prefix=f".{target.name}.staging-", dir=parent))
        context = {item.frame_index: item for item in input_contract.context_by_frame}
        run_anonymous_round(
            source_path=video,
            bounds=input_contract.bounds,
            hud_config_path=hud_config,
            color_config_path=color_config,
            map_config_path=map_config,
            map_asset_path=map_asset,
            output_root=stage,
            run_id=run_id,
            project_commit=project_commit,
            upstream_commit=upstream_commit,
            mode="diagnostic_only",
            context_by_frame=context,
        )
        run_dir = stage / run_id
        wrapper = AnonymousRunManifest.model_validate_json(
            (run_dir / "anonymous_run.json").read_bytes()
        )
        raw_frames, samples = read_anonymous_rows(stage, wrapper)
        replay_path = render_anonymous_replay(stage, wrapper, raw_frames, samples)
        report = build_anonymous_diagnostic_report(
            wrapper,
            raw_frames,
            samples,
            artifacts={
                "run_manifest": "anonymous_run.json",
                "raw_candidates": "raw_observations.jsonl",
                "anonymous_tracklets": "anonymous_tracklets.parquet",
                "minimap_replay": replay_path.name,
                "diagnostic_json": "diagnostic_report.json",
                "diagnostic_markdown": "report.md",
            },
        )
        write_anonymous_diagnostic_report(report, run_dir)
        _publish_anonymous_run(stage, target, run_id)
    except BaseException:
        if stage is not None:
            shutil.rmtree(stage, ignore_errors=True)
        raise
    finally:
        lock.rmdir()
    typer.echo(f"Anonymous diagnostic artifacts: {target / run_id}")


def _publish_anonymous_run(stage: Path, target: Path, run_id: str) -> None:
    """Publish into a newly created root; sibling lock coordinates this CLI's writers."""
    target.mkdir()
    source = stage / run_id
    destination = target / run_id
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"run destination appeared during publication: {destination}")
    try:
        source.rename(destination)
    except BaseException:
        try:
            target.rmdir()
        except OSError:
            pass
        raise
    shutil.rmtree(stage, ignore_errors=True)


@calibrate_app.callback(invoke_without_command=True)
def calibrate(
    video: Path = typer.Option(..., exists=False, help="Input video path"),
    timestamp: str = typer.Option(..., help="Timestamp as HH:MM:SS[.mmm] or seconds"),
    hud_config: Path = typer.Option(..., exists=False, help="HUD profile JSON"),
    map_config: Path = typer.Option(..., exists=False, help="Map definition JSON"),
    output: Path = typer.Option(..., help="Directory for calibration artifacts"),
    landmarks: Path | None = typer.Option(
        None, exists=False, help="Optional JSON file containing reviewed landmark labels"
    ),
) -> None:
    """Write source frame, minimap crop, registered crop, overlay, and diagnostics."""
    diagnostics = calibrate_video(
        video, timestamp, hud_config, map_config, output, landmarks_path=landmarks
    )
    if diagnostics["passed"]:
        typer.echo(f"Calibration passed: {output}")
    else:
        typer.echo(f"Calibration not accepted: {diagnostics['failure_reason']}", err=True)
        raise typer.Exit(code=1)


def calibrate_video(
    video_path: Path,
    timestamp: str,
    hud_config_path: Path,
    map_config_path: Path,
    output_dir: Path,
    *,
    landmarks_path: Path | None = None,
) -> dict[str, Any]:
    """Run offline calibration and always write diagnostics for expected failures."""
    output_dir.mkdir(parents=True, exist_ok=True)
    diagnostics: dict[str, Any] = {
        "timestamp_seconds": None,
        "profile_id": None,
        "map_id": None,
        "map_name": None,
        "map_asset_version": None,
        "transform_matrix": None,
        "confidence": None,
        "alignment_error": None,
        "registration_method": "rejected",
        "passed": False,
        "failure_reason": None,
        "landmark_evaluation": None,
    }

    try:
        timestamp_seconds = parse_timestamp(timestamp)
        diagnostics["timestamp_seconds"] = timestamp_seconds
        hud = json.loads(hud_config_path.read_text(encoding="utf-8"))
        diagnostics["profile_id"] = hud.get("profile_id", hud.get("name"))
        map_data = json.loads(map_config_path.read_text(encoding="utf-8"))
        map_definition = MapDefinition.model_validate(map_data)
        diagnostics.update(
            map_id=map_definition.map_id,
            map_name=map_definition.map_name,
            map_asset_version=map_definition.canonical_minimap.asset_version,
            map_patch_version=map_definition.canonical_minimap.patch_version,
            map_geometry_status=map_definition.geometry_status,
            hud_calibration_status=hud.get("calibration_status", "pending"),
        )
        canonical_path_value = map_data["canonical_minimap"].get("local_asset_path")
        if not canonical_path_value:
            raise ValueError("map_config_missing_local_asset_path")
        canonical_path = map_config_path.parent / canonical_path_value
        canonical_file_sha256 = hashlib.sha256(canonical_path.read_bytes()).hexdigest()
        diagnostics["canonical_asset_file_sha256"] = canonical_file_sha256
        expected_asset_sha256 = map_definition.canonical_minimap.sha256
        if canonical_file_sha256 != expected_asset_sha256:
            raise ValueError(
                "canonical_map_asset_sha256_mismatch:"
                f"expected={expected_asset_sha256}:actual={canonical_file_sha256}"
            )
        canonical = cv2.imread(str(canonical_path), cv2.IMREAD_COLOR)
        if canonical is None:
            raise ValueError("canonical_map_asset_unavailable")
        diagnostics["canonical_asset_decoded_sha256"] = decoded_image_sha256(canonical)

        capture = cv2.VideoCapture(str(video_path))
        if not capture.isOpened():
            raise ValueError("video_unavailable_or_unsupported")
        capture.set(cv2.CAP_PROP_POS_MSEC, timestamp_seconds * 1000.0)
        ok, frame = capture.read()
        capture.release()
        if not ok or frame is None:
            raise ValueError("video_frame_unavailable_at_timestamp")
        cv2.imwrite(str(output_dir / "frame.png"), frame)
        diagnostics["source_frame_decoded_sha256"] = decoded_image_sha256(frame)

        cropper = Cropper(config_path=hud_config_path)
        if hud.get("minimap") is not None:
            crop = cropper.crop_minimap(frame)
            diagnostics["crop_source"] = "configured_minimap_profile"
        elif "minimap" in cropper.regions:
            crop = cropper.crop_simple_region(frame, "minimap")
            diagnostics["crop_source"] = "legacy_regions_minimap_unvalidated"
        else:
            raise ValueError("hud_profile_has_no_minimap_region")
        if crop.size == 0:
            raise ValueError("minimap_crop_is_empty")
        diagnostics["crop_width"] = int(crop.shape[1])
        diagnostics["crop_height"] = int(crop.shape[0])
        cv2.imwrite(str(output_dir / "minimap_crop.png"), crop)

        minimap_profile = hud.get("minimap") or {}
        orientation = minimap_profile.get("orientation", "identity")
        oriented_crop, crop_to_oriented = orient_minimap_crop(crop, orientation)
        diagnostics["orientation"] = orientation
        thresholds = map_definition.registration_thresholds
        registrar = MinimapRegistrar(
            thresholds=thresholds,
            feature_config=map_definition.feature_registration,
        )
        result = registrar.register(oriented_crop, canonical)
        result = _compose_source_transform(result, crop_to_oriented)
        _record_registration(diagnostics, result)
        if landmarks_path is not None:
            try:
                label_data = json.loads(landmarks_path.read_text(encoding="utf-8"))
                labels = RegistrationLandmarkLabels.model_validate(label_data)
                if labels.source_frame_sha256 != diagnostics["source_frame_decoded_sha256"]:
                    raise ValueError("landmark_source_frame_sha256_mismatch")
                if labels.canonical_asset_sha256 != diagnostics["canonical_asset_decoded_sha256"]:
                    raise ValueError("landmark_canonical_asset_sha256_mismatch")
                if result.transform_matrix is None:
                    raise ValueError("landmark_evaluation_requires_registration_transform")
                threshold = (
                    thresholds.maximum_landmark_error_px if thresholds is not None else None
                )
                diagnostics["landmark_evaluation"] = evaluate_registration_landmarks(
                    labels, result.transform_matrix, crop.shape, canonical.shape, threshold
                )
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                if isinstance(exc, ValueError) and str(exc).startswith("landmark_"):
                    raise
                raise ValueError(f"invalid_landmark_labels:{exc}") from exc
        if result.aligned_minimap is not None:
            aligned = cv2.resize(
                result.aligned_minimap,
                (canonical.shape[1], canonical.shape[0]),
                interpolation=cv2.INTER_AREA,
            )
        else:
            aligned = np.zeros_like(canonical)
            cv2.putText(
                aligned,
                "REGISTRATION REJECTED",
                (20, min(60, canonical.shape[0] - 10)),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.0,
                (0, 0, 255),
                2,
                cv2.LINE_AA,
            )
        cv2.imwrite(str(output_dir / "registered_minimap.png"), aligned)
        overlay = cv2.addWeighted(canonical, 0.5, aligned, 0.5, 0.0)
        cv2.imwrite(str(output_dir / "alignment_overlay.png"), overlay)

        if result.aligned_minimap is None:
            diagnostics["failure_reason"] = result.failure_reason or "registration_rejected"
        elif landmarks_path is not None and diagnostics["landmark_evaluation"] is None:
            diagnostics["failure_reason"] = "landmark_evaluation_unavailable"
        elif landmarks_path is not None and not diagnostics["landmark_evaluation"][
            "acceptance_threshold_configured"
        ]:
            diagnostics["failure_reason"] = "landmark_acceptance_threshold_unconfigured"
        elif landmarks_path is not None and not diagnostics["landmark_evaluation"]["passed"]:
            diagnostics["failure_reason"] = "landmark_error_above_configured_threshold"
        elif diagnostics["hud_calibration_status"] != "validated":
            diagnostics["failure_reason"] = "hud_minimap_profile_pending"
        elif map_definition.geometry_status != "validated":
            diagnostics["failure_reason"] = "map_geometry_pending"
        elif thresholds is None:
            diagnostics["failure_reason"] = "registration_thresholds_unconfigured"
        elif diagnostics["crop_source"] != "configured_minimap_profile":
            diagnostics["failure_reason"] = "hud_minimap_crop_unvalidated"
        elif landmarks_path is None:
            diagnostics["failure_reason"] = "reviewed_landmarks_required"
        else:
            diagnostics["passed"] = True
            diagnostics["failure_reason"] = None
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        diagnostics["failure_reason"] = str(exc) or exc.__class__.__name__
    except Exception as exc:  # OpenCV and validation errors should become diagnostics.
        diagnostics["failure_reason"] = f"calibration_error:{exc.__class__.__name__}"

    (output_dir / "diagnostics.json").write_text(
        json.dumps(diagnostics, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return diagnostics


def orient_minimap_crop(crop: np.ndarray, orientation: str) -> tuple[np.ndarray, np.ndarray]:
    """Rotate and square-pad a crop, returning crop-to-oriented coordinates.

    Coordinates use image pixel origins. The returned 3x3 matrix maps points
    in the original crop to the pixels supplied to the registrar.
    """
    height, width = crop.shape[:2]
    if orientation == "identity":
        return crop.copy(), np.eye(3, dtype=np.float64)

    if orientation == "rotate_90_ccw":
        rotated = cv2.rotate(crop, cv2.ROTATE_90_COUNTERCLOCKWISE)
        rotation = np.array([[0.0, 1.0, 0.0], [-1.0, 0.0, float(width - 1)], [0.0, 0.0, 1.0]])
    elif orientation == "rotate_90_cw":
        rotated = cv2.rotate(crop, cv2.ROTATE_90_CLOCKWISE)
        rotation = np.array([[0.0, -1.0, float(height - 1)], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
    elif orientation == "rotate_180":
        rotated = cv2.rotate(crop, cv2.ROTATE_180)
        rotation = np.array(
            [
                [-1.0, 0.0, float(width - 1)],
                [0.0, -1.0, float(height - 1)],
                [0.0, 0.0, 1.0],
            ]
        )
    else:
        raise ValueError(f"unsupported_minimap_orientation:{orientation}")

    rotated_height, rotated_width = rotated.shape[:2]
    side = max(rotated_height, rotated_width)
    left = (side - rotated_width) // 2
    top = (side - rotated_height) // 2
    padded = np.zeros((side, side, *rotated.shape[2:]), dtype=rotated.dtype)
    padded[top : top + rotated_height, left : left + rotated_width] = rotated
    padding = np.array([[1.0, 0.0, float(left)], [0.0, 1.0, float(top)], [0.0, 0.0, 1.0]])
    return padded, padding @ rotation


def _compose_source_transform(
    result: RegistrationResult, crop_to_oriented: np.ndarray
) -> RegistrationResult:
    """Report registration matrix relative to the unrotated source crop."""
    if result.transform_matrix is None:
        return result
    oriented_to_canonical = np.vstack(
        (np.asarray(result.transform_matrix, dtype=np.float64), [0.0, 0.0, 1.0])
    )
    composed = oriented_to_canonical @ crop_to_oriented
    return replace(
        result,
        transform_matrix=(
            (
                float(composed[0, 0]),
                float(composed[0, 1]),
                float(composed[0, 2]),
            ),
            (
                float(composed[1, 0]),
                float(composed[1, 1]),
                float(composed[1, 2]),
            ),
        ),
    )


def parse_timestamp(value: str) -> float:
    """Parse seconds or HH:MM:SS[.mmm] into seconds."""
    try:
        parts = value.split(":")
        if len(parts) == 1:
            seconds = float(parts[0])
        elif len(parts) == 3:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = hours * 3600.0 + minutes * 60.0 + float(parts[2])
        else:
            raise ValueError
    except ValueError as exc:
        raise ValueError("timestamp must be seconds or HH:MM:SS[.mmm]") from exc
    if not np.isfinite(seconds) or seconds < 0:
        raise ValueError("timestamp must be a finite non-negative value")
    return seconds


def _record_registration(diagnostics: dict[str, Any], result: RegistrationResult) -> None:
    diagnostics.update(
        transform_matrix=result.transform_matrix,
        confidence=result.confidence,
        alignment_error=result.alignment_error,
        registration_method=result.method,
        registration_failure_reason=result.failure_reason,
        feature_confidence=result.feature_confidence,
        feature_alignment_error=result.feature_alignment_error,
        feature_failure_reason=result.feature_failure_reason,
        raw_confidence=result.raw_confidence,
        raw_alignment_error=result.raw_alignment_error,
        raw_failure_reason=result.raw_failure_reason,
    )
