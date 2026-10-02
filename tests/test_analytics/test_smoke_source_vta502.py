import json
from pathlib import Path

import numpy as np
import pytest
from pydantic_core import PydanticSerializationError

from valoscribe.analytics import smoke_source_vta502 as evaluator
from valoscribe.analytics.smoke_source_observation import decoded_crop_sha256


class Capture:
    def __init__(self, _path):
        self.index = 0
        self.released = False

    def isOpened(self):  # noqa: N802
        return True

    def get(self, prop):
        return {
            evaluator.cv2.CAP_PROP_FRAME_WIDTH: 1920,
            evaluator.cv2.CAP_PROP_FRAME_HEIGHT: 1080,
            evaluator.cv2.CAP_PROP_FPS: 60,
            evaluator.cv2.CAP_PROP_POS_FRAMES: self.index,
        }.get(prop, 0)

    def set(self, _prop, value):
        self.index = int(value)
        return True

    def read(self):
        if self.index == 0:
            return False, None
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        self.index += 1
        return True, frame

    def release(self):
        self.released = True


def _fixture(tmp_path, monkeypatch):
    data = json.loads(
        (Path(__file__).parents[2] / "docs/smoke_source_observation_vta502.json").read_text()
    )
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    digest = decoded_crop_sha256(frame, evaluator.SmokeSourceObservation.model_validate(data).crop)
    for sample in data["samples"]:
        sample["decoded_crop_sha256"] = digest
    for evidence in data["independent_visual_review"]["evidence"]:
        evidence["decoded_crop_sha256"] = digest
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(data))
    capture = Capture("unused")
    monkeypatch.setattr(evaluator.cv2, "VideoCapture", lambda _path: capture)
    monkeypatch.setattr(
        evaluator,
        "detect_smoke_candidates",
        lambda *a, **k: type("Result", (), {"candidates": []})(),
    )
    return manifest, capture


def test_evaluate_success_and_filename_mismatch(tmp_path, monkeypatch):
    manifest, capture = _fixture(tmp_path, monkeypatch)
    source = Path(
        "YTDown.com_YouTube_Media_4LEGEQ8KBS0_100T-vs-LOUD-VCT-Americas-Stage-2-Playoffs-Grand-Final-Map-3-Ascent_001_1080p.mp4"
    )
    result = evaluator.evaluate(source, manifest)
    assert result["evaluation"] == "EXPLORATORY_VISUAL_FOOTPRINT_CANDIDATE_SCORING"
    assert result["smoke_identity"] == "UNRESOLVED"
    assert result["smoke_precision_recall"] == "NOT_ESTABLISHED_IDENTITY_UNRESOLVED"
    assert result["smoke_timing"] == "NOT_ESTABLISHED_IDENTITY_UNRESOLVED"
    assert result["production_acceptance"] is False
    assert "split_metrics" not in result
    assert "appearance_bracket_s" not in result
    assert result["candidate_counts_by_split"] == {
        "train": {"frames_scored": 2, "candidates": 0, "near_visual_footprint_center": 0},
        "holdout": {"frames_scored": 2, "candidates": 0, "near_visual_footprint_center": 0},
    }
    assert capture.released
    with pytest.raises(ValueError, match="filename"):
        evaluator.evaluate(Path("wrong.mp4"), manifest)


def test_evaluate_rejects_dimensions_decode_and_hash(tmp_path, monkeypatch):
    manifest, _ = _fixture(tmp_path, monkeypatch)
    source = Path(json.loads(manifest.read_text())["source_filename"])
    capture = Capture("unused")
    monkeypatch.setattr(capture, "get", lambda _prop: 10)
    monkeypatch.setattr(evaluator.cv2, "VideoCapture", lambda _path: capture)
    with pytest.raises(ValueError, match="dimensions"):
        evaluator.evaluate(source, manifest)
    manifest, _ = _fixture(tmp_path, monkeypatch)
    capture = Capture("unused")
    def failed_read():
        capture.index += 1
        return False, None

    monkeypatch.setattr(capture, "read", failed_read)
    monkeypatch.setattr(evaluator.cv2, "VideoCapture", lambda _path: capture)
    with pytest.raises(ValueError, match="decode"):
        evaluator.evaluate(source, manifest)
    manifest, _ = _fixture(tmp_path, monkeypatch)
    data = json.loads(manifest.read_text())
    next(s for s in data["samples"] if s["frame_index"] == 149400)["decoded_crop_sha256"] = "0" * 64
    next(e for e in data["independent_visual_review"]["evidence"] if e["frame_index"] == 149400)[
        "decoded_crop_sha256"
    ] = "0" * 64
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="hash mismatch"):
        evaluator.evaluate(source, manifest)


def test_cli_does_not_write_output_when_evaluation_fails(tmp_path, monkeypatch):
    from scripts import evaluate_smoke_source_vta502 as cli

    output = tmp_path / "result.json"
    monkeypatch.setattr(
        "sys.argv",
        ["eval", "--video", "wrong.mp4", "--manifest", "missing", "--output", str(output)],
    )
    with pytest.raises(Exception):
        cli.main()
    assert not output.exists()


def test_evaluator_rejects_duplicate_review_frames_even_with_conflicting_hashes(
    tmp_path, monkeypatch
):
    manifest, _ = _fixture(tmp_path, monkeypatch)
    data = json.loads(manifest.read_text())
    reviewed_frame = next(
        evidence
        for evidence in data["independent_visual_review"]["evidence"]
        if evidence["frame_index"] == 149310
    )
    conflicting_hash = dict(reviewed_frame, decoded_crop_sha256="0" * 64)
    data["independent_visual_review"]["evidence"].insert(0, conflicting_hash)
    manifest.write_text(json.dumps(data))

    with pytest.raises(ValueError, match="frame indices must be unique"):
        evaluator.evaluate(Path(data["source_filename"]), manifest)


def test_evaluator_revalidates_mutated_review_before_indexing(tmp_path, monkeypatch):
    manifest, _ = _fixture(tmp_path, monkeypatch)
    data = json.loads(manifest.read_text())
    observation = evaluator.SmokeSourceObservation.model_validate(data)
    assert observation.independent_visual_review is not None
    existing = observation.independent_visual_review.evidence[3]
    observation.independent_visual_review.evidence.insert(
        0, existing.model_copy(update={"decoded_crop_sha256": "0" * 64})
    )
    monkeypatch.setattr(
        evaluator.SmokeSourceObservation,
        "model_validate_json",
        classmethod(lambda _cls, _raw: observation),
    )

    with pytest.raises(PydanticSerializationError, match="frame indices must be unique"):
        evaluator.evaluate(Path(data["source_filename"]), manifest)


def test_independent_review_hashes_are_verified(tmp_path, monkeypatch):
    manifest, _ = _fixture(tmp_path, monkeypatch)
    source = Path(json.loads(manifest.read_text())["source_filename"])
    data = json.loads(manifest.read_text())
    next(e for e in data["independent_visual_review"]["evidence"] if e["frame_index"] == 149310)[
        "decoded_crop_sha256"
    ] = "0" * 64
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="hash mismatch for frame 149310"):
        evaluator.evaluate(source, manifest)

    manifest, _ = _fixture(tmp_path, monkeypatch)
    data = json.loads(manifest.read_text())
    next(s for s in data["samples"] if s["frame_index"] == 149400)["decoded_crop_sha256"] = "0" * 64
    next(e for e in data["independent_visual_review"]["evidence"] if e["frame_index"] == 149400)[
        "decoded_crop_sha256"
    ] = "0" * 64
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="hash mismatch"):
        evaluator.evaluate(source, manifest)


def test_candidate_scoring_requires_reviewed_center_and_counts_extras(tmp_path, monkeypatch):
    from types import SimpleNamespace

    manifest, _ = _fixture(tmp_path, monkeypatch)
    data = json.loads(manifest.read_text())
    source = Path(data["source_filename"])
    wrong = SimpleNamespace(center=SimpleNamespace(x=0.8, y=0.8))

    def candidates(_crop, _mask, _profile, **_kwargs):
        return SimpleNamespace(candidates=[wrong])

    monkeypatch.setattr(evaluator, "detect_smoke_candidates", candidates)
    result = evaluator.evaluate(source, manifest)
    assert result["candidate_counts_by_split"] == {
        "train": {"frames_scored": 2, "candidates": 2, "near_visual_footprint_center": 0},
        "holdout": {"frames_scored": 2, "candidates": 2, "near_visual_footprint_center": 0},
    }


def test_evaluate_rejects_fps_and_seek_mismatch(tmp_path, monkeypatch):
    manifest, _ = _fixture(tmp_path, monkeypatch)
    source = Path(json.loads(manifest.read_text())["source_filename"])
    capture = Capture("unused")
    original_get = capture.get
    monkeypatch.setattr(
        capture, "get",
        lambda prop: 30 if prop == evaluator.cv2.CAP_PROP_FPS else original_get(prop),
    )
    monkeypatch.setattr(evaluator.cv2, "VideoCapture", lambda _path: capture)
    with pytest.raises(ValueError, match="FPS"):
        evaluator.evaluate(source, manifest)

    manifest, _ = _fixture(tmp_path, monkeypatch)
    capture = Capture("unused")
    original_get = capture.get
    monkeypatch.setattr(
        capture, "get",
        lambda prop: 1 if prop == evaluator.cv2.CAP_PROP_POS_FRAMES else original_get(prop),
    )
    monkeypatch.setattr(evaluator.cv2, "VideoCapture", lambda _path: capture)
    with pytest.raises(ValueError, match="seek position"):
        evaluator.evaluate(source, manifest)


def test_historical_sample_kind_does_not_create_smoke_scoring_label(tmp_path, monkeypatch):
    manifest, _ = _fixture(tmp_path, monkeypatch)
    data = json.loads(manifest.read_text())
    next(s for s in data["samples"] if s["frame_index"] == 149400)["kind"] = "unsettled"
    manifest.write_text(json.dumps(data))
    result = evaluator.evaluate(Path(data["source_filename"]), manifest)
    assert result["smoke_precision_recall"] == "NOT_ESTABLISHED_IDENTITY_UNRESOLVED"
    assert "split_metrics" not in result


def test_timing_endpoints_are_manifest_derived_and_verified(tmp_path, monkeypatch):
    manifest, _ = _fixture(tmp_path, monkeypatch)
    data = json.loads(manifest.read_text())
    sample = next(s for s in data["samples"] if s["frame_index"] == 149385)
    sample["kind"] = "unsettled"
    data["first_present_timestamp_s"] = 2490.0
    data["onset_last_unsettled_timestamp_s"] = 2489.75
    data["onset_first_persistent_timestamp_s"] = 2490.0
    manifest.write_text(json.dumps(data))
    source = Path(data["source_filename"])
    result = evaluator.evaluate(source, manifest)
    assert result["smoke_timing"] == "NOT_ESTABLISHED_IDENTITY_UNRESOLVED"
    assert "appearance_bracket_s" not in result
    assert "transition_to_persistent_bracket_s" not in result

    manifest, _ = _fixture(tmp_path, monkeypatch)
    data = json.loads(manifest.read_text())
    data["samples"].insert(
        next(i for i, sample in enumerate(data["samples"]) if sample["frame_index"] == 150315),
        {
            "timestamp_s": 2505.15,
            "frame_index": 150309,
            "kind": "present",
            "review_note": "Independent review: feature present.",
            "decoded_crop_sha256": None,
        },
    )
    data["last_present_timestamp_s"] = 2505.15
    data["end_last_present_timestamp_s"] = 2505.15
    manifest.write_text(json.dumps(data))
    result = evaluator.evaluate(source, manifest)
    assert result["smoke_timing"] == "NOT_ESTABLISHED_IDENTITY_UNRESOLVED"


def test_missing_tolerance_rejected_before_video_open_for_any_candidate_count(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    for candidates in ([], [SimpleNamespace(center=SimpleNamespace(x=0.5, y=0.5))]):
        manifest, _ = _fixture(tmp_path, monkeypatch)
        data = json.loads(manifest.read_text())
        data["center_tolerance_px"] = None
        manifest.write_text(json.dumps(data))
        monkeypatch.setattr(
            evaluator.cv2,
            "VideoCapture",
            lambda _path: (_ for _ in ()).throw(AssertionError("video opened")),
        )
        monkeypatch.setattr(
            evaluator, "detect_smoke_candidates",
            lambda *a, **k: SimpleNamespace(candidates=candidates),
        )
        with pytest.raises(ValueError, match="center_tolerance_px is required"):
            evaluator.evaluate(Path(data["source_filename"]), manifest)


def test_historical_absence_label_is_not_required_for_candidate_replay(tmp_path, monkeypatch):
    manifest, _ = _fixture(tmp_path, monkeypatch)
    data = json.loads(manifest.read_text())
    next(s for s in data["samples"] if s["frame_index"] == 149220)["kind"] = "unsettled"
    manifest.write_text(json.dumps(data))
    result = evaluator.evaluate(Path(data["source_filename"]), manifest)
    assert result["smoke_timing"] == "NOT_ESTABLISHED_IDENTITY_UNRESOLVED"


def test_unresolved_identity_cannot_produce_accepted_smoke_metrics(tmp_path, monkeypatch):
    manifest, _ = _fixture(tmp_path, monkeypatch)
    source = Path(json.loads(manifest.read_text())["source_filename"])
    data = json.loads(manifest.read_text())
    data.pop("independent_visual_review")
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="independent visual review is required"):
        evaluator.evaluate(source, manifest)

    manifest, _ = _fixture(tmp_path, monkeypatch)
    data = json.loads(manifest.read_text())
    data["independent_visual_review"]["smoke_identity"] = "SMOKE_CONFIRMED"
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="UNRESOLVED"):
        evaluator.evaluate(source, manifest)
