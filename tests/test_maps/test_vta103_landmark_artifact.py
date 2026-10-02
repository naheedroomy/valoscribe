"""Provisional VTA-103 VOD landmark artifact and split-summary checks."""

import json
from pathlib import Path
from runpy import run_path

import pytest

from valoscribe.maps.landmarks import RegistrationLandmarkLabels

ARTIFACT = (
    Path(__file__).parent
    / "../fixtures/registration_landmarks/ascent-vct-americas-stage2-grand-final-vta103.json"
)
EVALUATOR = run_path(str(Path(__file__).parents[2] / "scripts/evaluate_minimap_landmarks.py"))
SUMMARIZE_SAMPLES = EVALUATOR["summarize_samples"]
EVALUATE_MANIFEST = EVALUATOR["evaluate_manifest"]
MAIN = EVALUATOR["main"]


def test_ascent_candidate_thresholds_are_configured_without_marking_calibration_validated() -> None:
    root = Path(__file__).parents[2]
    map_config = json.loads((root / "src/valoscribe/config/ascent_map.json").read_text())
    hud_config = json.loads(
        (root / "src/valoscribe/config/ascent_vct_americas_2026_stage2_final_1080p_candidate.json")
        .read_text()
    )

    assert map_config["registration_thresholds"] == {
        "minimum_confidence": 0.3,
        "maximum_alignment_error": 0.25,
        "maximum_landmark_error_px": 25,
    }
    assert map_config["geometry_status"] == "pending"
    assert hud_config["calibration_status"] == "pending"


def test_vta103_artifact_labels_match_landmark_contract_and_are_split() -> None:
    artifact = json.loads(ARTIFACT.read_text(encoding="utf-8"))

    assert artifact["label_status"] == "provisional_visually_reviewed"
    assert artifact["source_video"]["frame_dimensions_px"] == {"width": 1920, "height": 1080}
    assert artifact["source_video"]["crop_dimensions_px"] == {"width": 360, "height": 400}
    assert artifact["canonical_asset"]["dimensions_px"] == {"width": 2048, "height": 2048}
    assert artifact["uncertainty"]["source_crop_px_approx"] == (
        "±2 px (L1, L2, L3, L5); ±3 px (L4)"
    )
    assert artifact["uncertainty"]["canonical_asset_px_approx"] == (
        "±8 px (L1, L2, L3, L5); ±10 px (L4)"
    )
    assert artifact["acceptance_threshold"]["maximum_per_landmark_error_px"] == 25
    assert artifact["acceptance_threshold"]["coordinate_space"] == "canonical image pixels"
    assert {sample["split"] for sample in artifact["samples"]} == {
        "train",
        "validation",
        "test",
    }

    for sample in artifact["samples"]:
        labels = RegistrationLandmarkLabels.model_validate(sample["labels"])
        assert labels.source_frame_sha256 == sample["source_frame_decoded_sha256"]
        expected_count = 4 if sample["split"] == "validation" else 5
        assert len(labels.landmarks) == expected_count
    test_timestamps = {
        sample["timestamp_seconds"]
        for sample in artifact["samples"]
        if sample["split"] == "test"
    }
    assert test_timestamps == {2820, 2940}
    assert all(sample["split"] == "test" for sample in artifact["samples"][-2:])
    assert "L4_B_leftmost_protrusion_upper" not in {
        point["landmark_id"] for point in artifact["samples"][2]["labels"]["landmarks"]
    }


def test_split_summary_reports_metrics_without_acceptance_threshold() -> None:
    summarize_samples = SUMMARIZE_SAMPLES
    summary = summarize_samples(
        [
            {
                "sample_id": "sample-a",
                "sample_error": None,
                "reprojection": {
                    "per_point_errors": [{"error_px": 3.0}, {"error_px": 4.0}],
                    "maximum_error_px": 4.0,
                },
            },
            {
                "sample_id": "sample-b",
                "sample_error": None,
                "reprojection": {
                    "per_point_errors": [{"error_px": 0.0}],
                    "maximum_error_px": 0.0,
                },
            },
        ]
    )

    assert summary["sample_count"] == 2
    assert summary["point_count"] == 3
    assert summary["mean_error_px"] == pytest.approx(7 / 3)
    assert summary["rms_error_px"] == pytest.approx((25 / 3) ** 0.5)
    assert summary["maximum_error_px"] == 4.0
    assert summary["gate_passed"] is True
    empty = summarize_samples([])
    assert empty["sample_count"] == 0
    assert empty["maximum_error_px"] is None
    assert empty["gate_passed"] is False


def _manifest_for(samples: list[dict[str, object]], path: Path) -> Path:
    artifact = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    artifact["samples"] = samples
    path.write_text(json.dumps(artifact), encoding="utf-8")
    return path


def _mock_diagnostics(**overrides: object) -> dict[str, object]:
    diagnostics: dict[str, object] = {
        "registration_method": "affine",
        "confidence": 0.8,
        "alignment_error": 0.1,
        "failure_reason": "hud_minimap_profile_pending",
        "source_frame_decoded_sha256": "a" * 64,
        "landmark_evaluation": {
            "per_point_errors": [{"landmark_id": "L1", "error_px": 4.0}],
            "point_count": 1,
            "mean_error_px": 4.0,
            "rms_error_px": 4.0,
            "maximum_error_px": 4.0,
        },
    }
    diagnostics.update(overrides)
    return diagnostics


def _evaluate_with_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, diagnostics: dict[str, object], samples=None
):
    sample = json.loads(ARTIFACT.read_text(encoding="utf-8"))["samples"][0]
    monkeypatch.setitem(
        EVALUATE_MANIFEST.__globals__, "calibrate_video", lambda *args, **kwargs: diagnostics
    )
    manifest = _manifest_for(samples or [sample], tmp_path / "manifest.json")
    return EVALUATE_MANIFEST(
        Path("unused-vod"), manifest, Path("unused-hud"), Path("unused-map"), tmp_path / "out"
    )


def test_missing_sample_is_reported_and_fails_offline_gate(tmp_path: Path, monkeypatch) -> None:
    report = _evaluate_with_diagnostics(
        tmp_path,
        monkeypatch,
        _mock_diagnostics(
            registration_method="rejected",
            failure_reason="video_frame_unavailable_at_timestamp",
            landmark_evaluation=None,
        ),
    )

    assert report["samples"][0]["sample_error"] == "video_frame_unavailable_at_timestamp"
    assert report["splits"]["train"]["sample_count"] == 1
    assert report["splits"]["train"]["error_sample_count"] == 1
    assert report["offline_manifest_gate"]["status"] == "failed"


def test_missing_reprojection_is_reported_even_when_registration_exists(
    tmp_path: Path, monkeypatch
) -> None:
    report = _evaluate_with_diagnostics(
        tmp_path,
        monkeypatch,
        _mock_diagnostics(landmark_evaluation=None),
    )

    assert report["samples"][0]["sample_error"].startswith("reprojection_unavailable:")
    assert report["splits"]["train"]["error_sample_count"] == 1
    assert report["offline_manifest_gate"]["status"] == "failed"


def test_failed_registration_is_not_summarized_as_success(tmp_path: Path, monkeypatch) -> None:
    report = _evaluate_with_diagnostics(
        tmp_path,
        monkeypatch,
        _mock_diagnostics(
            registration_method="rejected",
            failure_reason="registration_rejected",
            landmark_evaluation=None,
        ),
    )

    assert report["samples"][0]["sample_error"] == "registration_rejected"
    assert report["splits"]["train"]["evaluated_sample_count"] == 0
    assert report["offline_manifest_gate"]["status"] == "failed"


def test_hash_mismatch_fails_closed_and_production_acceptance_stays_pending(
    tmp_path: Path, monkeypatch
) -> None:
    report = _evaluate_with_diagnostics(
        tmp_path,
        monkeypatch,
        _mock_diagnostics(
            failure_reason="landmark_source_frame_sha256_mismatch",
            landmark_evaluation=None,
        ),
    )

    assert report["samples"][0]["sample_error"] == "landmark_source_frame_sha256_mismatch"
    assert report["offline_manifest_gate"]["status"] == "failed"
    assert report["acceptance_status"] == "not_assessed"
    assert report["thresholds_used"] is None


def test_malformed_manifest_sample_is_preserved_in_unknown_split(tmp_path: Path) -> None:
    manifest = _manifest_for([{"sample_id": "broken"}], tmp_path / "manifest.json")
    report = EVALUATE_MANIFEST(
        Path("unused-vod"), manifest, Path("unused-hud"), Path("unused-map"), tmp_path / "out"
    )

    assert report["samples"][0]["sample_error"].startswith("KeyError:")
    assert report["splits"]["unknown"]["sample_count"] == 1
    assert report["offline_manifest_gate"]["status"] == "failed"


def test_cli_failed_gate_persists_report_then_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    output_dir = tmp_path / "evaluation"
    output_dir.mkdir()
    report = {"offline_manifest_gate": {"status": "failed"}, "samples": []}
    monkeypatch.setitem(MAIN.__globals__, "evaluate_manifest", lambda *args: report)
    monkeypatch.setattr(
        "sys.argv",
        [
            "evaluate_minimap_landmarks.py",
            "--video", "video.mp4",
            "--manifest", "manifest.json",
            "--hud-config", "hud.json",
            "--map-config", "map.json",
            "--output", str(output_dir),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        MAIN()

    assert exc_info.value.code == 1
    artifact = json.loads((output_dir / "evaluation.json").read_text(encoding="utf-8"))
    assert artifact == report
    assert json.loads(capsys.readouterr().out) == report


def test_cli_successful_gate_exits_normally_and_persists_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    output_dir = tmp_path / "evaluation"
    output_dir.mkdir()
    report = {"offline_manifest_gate": {"status": "passed"}, "samples": []}
    monkeypatch.setitem(MAIN.__globals__, "evaluate_manifest", lambda *args: report)
    monkeypatch.setattr(
        "sys.argv",
        [
            "evaluate_minimap_landmarks.py",
            "--video", "video.mp4",
            "--manifest", "manifest.json",
            "--hud-config", "hud.json",
            "--map-config", "map.json",
            "--output", str(output_dir),
        ],
    )

    MAIN()

    artifact = json.loads((output_dir / "evaluation.json").read_text(encoding="utf-8"))
    assert artifact == report
    assert json.loads(capsys.readouterr().out) == report


def test_smoke_window_provisional_landmark_labels_bind_expected_frames() -> None:
    fixture_path = (
        Path(__file__).parent
        / "../fixtures/registration_landmarks/ascent-vta103-smoke-window.json"
    ).resolve()
    artifact = json.loads(fixture_path.read_text(encoding="utf-8"))

    assert artifact["label_status"] == "provisional_visually_reviewed_nonblind"
    assert "not blind or pixel-verified" in artifact["label_limitations"]
    assert [sample["timestamp_seconds"] for sample in artifact["samples"]] == [2490, 2505]
    for sample in artifact["samples"]:
        labels = RegistrationLandmarkLabels.model_validate(sample["labels"])
        assert labels.source_frame_sha256 == sample["source_frame_decoded_sha256"]
        assert len(labels.landmarks) == 4


def test_local_vod_integration_smoke_window_feature_registration(tmp_path: Path) -> None:
    import os

    default_video = Path(__file__).parents[2] / "../VOD" / json.loads(
        ARTIFACT.read_text(encoding="utf-8")
    )["source_video"]["filename"]
    video = Path(os.environ.get("VTA103_VOD_PATH", str(default_video)))
    if not video.is_file():
        pytest.skip("VTA103_VOD_PATH local VOD is unavailable; no download is attempted")
    root = Path(__file__).parents[2]
    smoke_manifest = (
        Path(__file__).parent
        / "../fixtures/registration_landmarks/ascent-vta103-smoke-window.json"
    ).resolve()
    report = EVALUATE_MANIFEST(
        video,
        smoke_manifest,
        root / "src/valoscribe/config/ascent_vct_americas_2026_stage2_final_1080p_candidate.json",
        root / "src/valoscribe/config/ascent_map.json",
        tmp_path / "vta103-smoke-window",
    )

    from valoscribe.commands.minimap import calibrate_video

    raw_2487 = calibrate_video(
        video,
        "2487",
        root / "src/valoscribe/config/ascent_vct_americas_2026_stage2_final_1080p_candidate.json",
        root / "src/valoscribe/config/ascent_map.json",
        tmp_path / "vta103-2487-raw-fallback",
    )
    assert raw_2487["registration_method"] in {"fixed", "affine"}
    assert raw_2487["feature_failure_reason"] is not None
    assert raw_2487["raw_confidence"] >= 0.30
    assert raw_2487["raw_alignment_error"] <= 0.25
    assert raw_2487["raw_failure_reason"] is None

    assert report["offline_manifest_gate"]["status"] == "passed"
    assert report["offline_manifest_gate"]["evaluated_sample_count"] == 2
    assert report["offline_manifest_gate"]["maximum_per_point_error_px"] == 25.0
    assert all(sample["sample_error"] is None for sample in report["samples"])
    for sample in report["samples"]:
        assert sample["registration_method"] == "feature_affine"
        assert sample["registration_confidence"] >= 0.70
        diagnostics = json.loads(
            (tmp_path / "vta103-smoke-window" / sample["sample_id"] / "diagnostics.json")
            .read_text(encoding="utf-8")
        )
        assert diagnostics["feature_confidence"] >= 0.70
        assert diagnostics["feature_alignment_error"] <= 0.15
        assert diagnostics["feature_failure_reason"] is None
        assert sample["alignment_error"] <= 0.15
        assert sample["reprojection"]["maximum_error_px"] <= 25.0
        assert sample["calibration_failure_reason"] == "hud_minimap_profile_pending"


def test_local_vod_integration_hashes_and_five_sample_report(tmp_path: Path) -> None:
    import os

    default_video = Path(__file__).parents[2] / "../VOD" / json.loads(
        ARTIFACT.read_text(encoding="utf-8")
    )["source_video"]["filename"]
    video = Path(os.environ.get("VTA103_VOD_PATH", str(default_video)))
    if not video.is_file():
        pytest.skip("VTA103_VOD_PATH local VOD is unavailable; no download is attempted")
    artifact = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    root = Path(__file__).parents[2]
    report = EVALUATE_MANIFEST(
        video,
        ARTIFACT.resolve(),
        root / "src/valoscribe/config/ascent_vct_americas_2026_stage2_final_1080p_candidate.json",
        root / "src/valoscribe/config/ascent_map.json",
        tmp_path / "vta103-local-vod",
    )

    assert len(report["samples"]) == 5
    assert report["offline_manifest_gate"]["expected_sample_count"] == 5
    assert [sample["source_frame_decoded_sha256"] for sample in report["samples"]] == [
        sample["source_frame_decoded_sha256"] for sample in artifact["samples"]
    ]
    assert all(sample["sample_error"] is None for sample in report["samples"])
    for sample, expected in zip(report["samples"], artifact["samples"], strict=True):
        diagnostics = json.loads(
            (tmp_path / "vta103-local-vod" / sample["sample_id"] / "diagnostics.json")
            .read_text(encoding="utf-8")
        )
        assert diagnostics["source_frame_decoded_sha256"] == expected[
            "source_frame_decoded_sha256"
        ]
        assert diagnostics["confidence"] >= 0.30
        assert diagnostics["alignment_error"] <= 0.25
        assert diagnostics["landmark_evaluation"]["passed"] is True
        assert diagnostics["passed"] is False
        assert diagnostics["failure_reason"] in {
            "hud_minimap_profile_pending",
            "map_geometry_pending",
        }
