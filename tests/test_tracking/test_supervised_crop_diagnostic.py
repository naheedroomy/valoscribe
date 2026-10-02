from __future__ import annotations

import hashlib
import json
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from valoscribe.tracking import supervised_crop_diagnostic as diagnostic
from valoscribe.tracking.crop_diagnostic_evaluation import evaluate_crop_diagnostic
from valoscribe.types.crop_diagnostic import (
    CropDiagnosticPrediction,
    CropDiagnosticProvenance,
)
from valoscribe.types.persistent import NormalizedBox, NormalizedPoint, RawMinimapColorCandidate


def test_hungarian_motion_assignment_selects_unique_nearest_candidate() -> None:
    result = diagnostic.associate_crop_candidates(
        "bang",
        16830,
        280.5,
        [("near", (278.0, 255.0)), ("far", (300.0, 260.0))],
        (275.0, 255.0),
        280.0,
        seed_uncertainty_px_each_axis=5.0,
    )
    assert result.status == "associated"
    assert result.candidate_id == result.selected_evidence_candidate_id == "near"
    assert result.center_crop_px == (278.0, 255.0)
    assert result.motion_cost_px == 3.0
    assert result.seed_uncertainty_px_each_axis == 5.0
    assert result.identity_confidence == "uncalibrated"


def test_ambiguous_candidate_assignment_abstains_with_competitor_margin() -> None:
    result = diagnostic.associate_crop_candidates(
        "bang",
        16830,
        280.5,
        [("left", (278.0, 255.0)), ("right", (278.5, 255.0))],
        (275.0, 255.0),
        280.0,
    )
    assert result.status == "abstained"
    assert result.reason == "candidate_assignment_ambiguous"
    assert result.center_crop_px is result.candidate_id is None
    assert result.selected_evidence_candidate_id == "left"
    assert result.competitor_margin_px == 0.5


def test_missed_frame_is_preserved_and_long_gap_abstains() -> None:
    missed = diagnostic.associate_crop_candidates("bang", 16830, 280.5, [], (275.0, 255.0), 280.0)
    assert missed.status == "missed"
    gap = diagnostic.associate_crop_candidates(
        "bang", 16890, 281.5, [("candidate", (276.0, 255.0))], (275.0, 255.0), 280.0
    )
    assert gap.status == "abstained"
    assert gap.reason == "motion_history_gap_exceeded"


def test_policy_hash_is_over_exact_persisted_bytes_and_dependency_digest_changes() -> None:
    data = diagnostic.canonical_json(diagnostic.POLICY.model_dump(mode="json")) + b"\n"
    assert diagnostic.sha256_bytes(data) == hashlib.sha256(data).hexdigest()
    inventory = {"dependency.py": "a" * 64}
    first = diagnostic._algorithm_digest(inventory)
    inventory["dependency.py"] = "b" * 64
    assert diagnostic._algorithm_digest(inventory) != first


def test_prediction_contract_rejects_incoherent_or_nonfinite_records() -> None:
    with pytest.raises(ValueError):
        CropDiagnosticPrediction(
            frame_index=1, timestamp_s=1, player_id="bang", status="associated"
        )
    with pytest.raises(ValueError):
        CropDiagnosticPrediction(
            frame_index=1,
            timestamp_s=1,
            player_id="bang",
            status="abstained",
            reason="ambiguous",
            center_crop_px=(1, 2),
        )
    with pytest.raises(ValueError):
        CropDiagnosticPrediction(
            frame_index=1,
            timestamp_s=1,
            player_id="bang",
            status="missed",
            reason="missing",
            center_crop_px=(float("nan"), 0),
        )


def test_provenance_is_hash_bound_and_cannot_claim_gold_or_canonical_output() -> None:
    digest = "a" * 64
    provenance = CropDiagnosticProvenance(
        source_video_sha256=digest,
        diagnostic_code_sha256=digest,
        dependency_file_sha256={"dependency.py": digest},
        algorithm_sha256=digest,
        runtime_provenance={"opencv": "test"},
        color_profile_sha256=digest,
        hud_config_sha256=digest,
        crop_coordinate_config_sha256=digest,
        seed_sha256=digest,
        policy_sha256=digest,
        predictions_sha256=digest,
        raw_detections_sha256=digest,
    )
    assert provenance.gold_reference_read_for_prediction is False
    assert provenance.canonical_coordinates_emitted is False
    with pytest.raises(ValueError):
        CropDiagnosticProvenance.model_validate(
            {**provenance.model_dump(), "gold_reference_read_for_prediction": True}
        )


def _integration_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail: str | None = None):
    frame_pixels = np.zeros((1080, 1920, 3), dtype=np.uint8)
    frame_pixels[50:450, 70:430] = (11, 22, 33)
    source = tmp_path / "source.bin"
    source.write_bytes(b"fake source")
    hud = tmp_path / "hud.json"
    hud.write_text(
        json.dumps(
            {
                "frame_width": 1920,
                "frame_height": 1080,
                "minimap": {"x": 70, "y": 50, "width": 360, "height": 400},
            }
        )
    )
    profile = tmp_path / "profile.json"
    profile.write_text(
        '{"schema_version":"1.0","profile_id":"test","colors":[{"color_id":"blue","ranges":[{"lower":[0,0,0],"upper":[179,255,255]}]}],"minimum_area_px":1,"maximum_area_fraction":1,"minimum_circularity":0,"minimum_aspect_ratio":0.01}'
    )
    crop = frame_pixels[50:450, 70:430]

    def digest(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    seed = tmp_path / "seed.json"
    seed.write_text(
        json.dumps(
            {
                "player_id": "100T:bang",
                "center_crop_px": [100, 100],
                "timestamp_s": 0.0,
                "frame_index": 0,
                "uncertainty_px_each_axis": 5,
                "coordinate_frame": "configured_minimap_crop_pixels",
                "source_binding": {
                    "source_video_sha256": digest(source.read_bytes()),
                    "frame_index": 0,
                    "timestamp_s": 0,
                    "crop_x": 70,
                    "crop_y": 50,
                    "crop_width": 360,
                    "crop_height": 400,
                    "coordinate_frame": "configured_minimap_crop_pixels",
                    "decoded_frame_bgr_sha256": digest(frame_pixels.tobytes()),
                    "decoded_crop_bgr_sha256": digest(crop.tobytes()),
                    "uncertainty_px_each_axis": 5,
                },
            }
        )
    )

    class Reader:
        def __init__(self, path):
            self.metadata = SimpleNamespace(
                width=1920,
                height=1080,
                fps_numerator=60,
                fps_denominator=1,
                ffmpeg_version="ffmpeg test",
                ffprobe_version="ffprobe test",
            )
            self.complete_stream_verified = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def __iter__(self):
            if fail == "decode":
                raise RuntimeError("synthetic decode failure")
            self.complete_stream_verified = True
            return iter(
                [SimpleNamespace(frame_index=0, timestamp_seconds=Fraction(0), bgr=frame_pixels)]
            )

    class TestCropper:
        def __init__(self, path):
            pass

        def crop_minimap(self, frame):
            return frame[50:450, 70:430].copy()

    class TestDetector:
        def __init__(self, profile):
            pass

        def detect(self, image, **kwargs):
            candidate = RawMinimapColorCandidate(
                vod_timestamp_s=0,
                source_frame=0,
                color_profile_id="test",
                broadcast_color="blue",
                crop_point=NormalizedPoint(x=100 / 360, y=100 / 400),
                bounding_box=NormalizedBox(x=0.2, y=0.2, width=0.1, height=0.1),
                contour_area_px=10,
                mask_pixel_count=11,
                detector_confidence=0.5,
                accepted=True,
            )
            return SimpleNamespace(candidates=(candidate,), debug_overlay=image.copy())

    monkeypatch.setattr(diagnostic, "SequentialPtsVideoSource", Reader)
    monkeypatch.setattr(diagnostic, "Cropper", TestCropper)
    monkeypatch.setattr(diagnostic, "MinimapColorCandidateDetector", TestDetector)
    return source, hud, profile, seed


def test_fake_reader_success_atomically_publishes_bound_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, hud, profile, seed = _integration_inputs(tmp_path, monkeypatch)
    output = tmp_path / "published"
    diagnostic.run_supervised_crop_diagnostic(
        source_path=source,
        hud_config_path=hud,
        color_profile_path=profile,
        seed_path=seed,
        output_path=output,
        start_timestamp_s=0,
        end_timestamp_s=0,
    )
    manifest = json.loads((output / "manifest.json").read_bytes())
    policy_bytes = (output / "policy.json").read_bytes()
    assert manifest["policy_sha256"] == hashlib.sha256(policy_bytes).hexdigest()
    raw = json.loads((output / "raw_detections.jsonl").read_text())
    assert raw["decoded_crop_bgr_sha256"] != raw["encoded_crop_png_sha256"]
    assert raw["decoded_crop_bgr_convention"].startswith("uint8 contiguous HxWx3 BGR")
    assert (output / "predictions.jsonl").exists()

    # Independently reconstruct the fake reader's source raster and configured crop.
    fixture_frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    fixture_frame[50:450, 70:430] = (11, 22, 33)
    fixture_crop = fixture_frame[50:450, 70:430].copy()
    fixture = tmp_path / "fixture.json"
    fixture.write_text(
        json.dumps(
            {
                "source_filename": source.name,
                "crop": {"x": 70, "y": 50, "width": 360, "height": 400},
                "label": {"team_id": "100T", "player_id": "bang"},
                "samples": [
                    {
                        "frame_index": 0,
                        "timestamp_s": 0.0,
                        "visibility": "visible",
                        "decoded_frame_sha256": hashlib.sha256(
                            fixture_frame.tobytes()
                        ).hexdigest(),
                        "decoded_crop_sha256": hashlib.sha256(
                            fixture_crop.tobytes()
                        ).hexdigest(),
                        "icon_center_crop_px": [100.0, 100.0],
                    }
                ],
            }
        )
    )
    scored = evaluate_crop_diagnostic(output, fixture)
    assert scored["status"] == "scored"
    assert scored["metrics"] == {
        "visible_label_count": 1,
        "scored_visible_label_count": 1,
        "associated_count": 1,
        "inside_tolerance_count": 1,
    }


@pytest.mark.parametrize("failure", ["decode", "seed", "write"])
def test_failures_clean_owned_staging_and_leave_destination_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    source, hud, profile, seed = _integration_inputs(
        tmp_path, monkeypatch, "decode" if failure == "decode" else None
    )
    if failure == "seed":
        data = json.loads(seed.read_text())
        data["source_binding"]["decoded_crop_bgr_sha256"] = "0" * 64
        seed.write_text(json.dumps(data))
    if failure == "write":
        original = Path.write_bytes

        def failing_write(path: Path, data: bytes):
            if ".staging-" in str(path) and path.name == "predictions.jsonl":
                raise OSError("synthetic output failure")
            return original(path, data)

        monkeypatch.setattr(Path, "write_bytes", failing_write)
    output = tmp_path / "failed-output"
    with pytest.raises((RuntimeError, ValueError, OSError)):
        diagnostic.run_supervised_crop_diagnostic(
            source_path=source,
            hud_config_path=hud,
            color_profile_path=profile,
            seed_path=seed,
            output_path=output,
            start_timestamp_s=0,
            end_timestamp_s=0,
        )
    assert not output.exists()
    assert not list(tmp_path.glob(".failed-output.staging-*"))


def test_concurrently_created_empty_destination_survives_failed_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, hud, profile, seed = _integration_inputs(tmp_path, monkeypatch)
    output = tmp_path / "raced-output"
    original = diagnostic._atomic_noreplace_rename

    def create_racing_destination(staging: Path, destination: Path) -> None:
        destination.mkdir()
        original(staging, destination)

    monkeypatch.setattr(diagnostic, "_atomic_noreplace_rename", create_racing_destination)
    with pytest.raises(FileExistsError):
        diagnostic.run_supervised_crop_diagnostic(
            source_path=source,
            hud_config_path=hud,
            color_profile_path=profile,
            seed_path=seed,
            output_path=output,
            start_timestamp_s=0,
            end_timestamp_s=0,
        )
    assert output.is_dir()
    assert list(output.iterdir()) == []
    assert not list(tmp_path.glob(".raced-output.staging-*"))


def test_existing_destination_is_preserved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source, hud, profile, seed = _integration_inputs(tmp_path, monkeypatch)
    output = tmp_path / "existing"
    output.mkdir()
    marker = output / "keep"
    marker.write_text("preserve")
    with pytest.raises(FileExistsError):
        diagnostic.run_supervised_crop_diagnostic(
            source_path=source,
            hud_config_path=hud,
            color_profile_path=profile,
            seed_path=seed,
            output_path=output,
            start_timestamp_s=0,
            end_timestamp_s=0,
        )
    assert marker.read_text() == "preserve"
