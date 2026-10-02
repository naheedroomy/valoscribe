from __future__ import annotations

import hashlib
import json
from fractions import Fraction
from pathlib import Path

import cv2
import numpy as np
import pytest

from valoscribe.tracking.portrait_experiment import (
    WINDOWS,
    _ExperimentProtocol,
    _run_experiment,
    _run_synthetic_fixture_experiment_for_tests,
    _verify_readback,
    run_portrait_experiment,
)


def _write_fixture(root: Path) -> Path:
    rows = []
    rng = np.random.default_rng(19)
    seed_by_frame = {frame: (agent, x, y) for agent, frame, _pts, x, y in WINDOWS}
    seed_frames = sorted({frame for _agent, frame, _pts, _x, _y in WINDOWS})
    frames = seed_frames + [22000 + i for i in range(157)]
    for index, frame in enumerate(frames):
        pts = frame * 256
        if frame in seed_by_frame:
            pts = next(item[2] for item in WINDOWS if item[1] == frame)
        image = rng.integers(0, 256, (400, 360, 3), dtype=np.uint8)
        if frame in seed_by_frame:
            _agent, x, y = seed_by_frame[frame]
            image[y : y + 20, x : x + 20] = rng.integers(
                0, 256, (20, 20, 3), dtype=np.uint8
            )
        ok, encoded = cv2.imencode(".png", image)
        assert ok
        relative = f"candidate_minimap_crops/{frame}.png"
        payload = encoded.tobytes()
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_bytes(payload)
        source_pixels_digest = hashlib.sha256(f"synthetic-source-{frame}".encode()).hexdigest()
        timestamp = Fraction(pts, 15360)
        rows.append(
            {
                "boundary": "sample",
                "frame_index": frame,
                "source_pts": pts,
                "timestamp_kind": "pts",
                "time_base": "1/15360",
                "timestamp_seconds": str(timestamp),
                "timestamp_seconds_decimal": float(timestamp),
                "decoded_bgr_sha256": source_pixels_digest,
                "inventory_bgr_sha256": source_pixels_digest,
                "candidate_crop_png": {
                    "path": relative,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "crop_bgr_sha256": hashlib.sha256(image.tobytes()).hexdigest(),
                    "dimensions_px": [360, 400],
                    "size_bytes": len(payload),
                },
                "candidate_crop_rect_xywh": [70, 50, 360, 400],
                "crop_config_sha256": "1" * 64,
                "full_frame_png": {
                    "path": f"full_frames/{frame}.png",
                    "sha256": "2" * 64,
                    "dimensions_px": [1920, 1080],
                    "size_bytes": 1,
                },
                "grid_targets_seconds": [],
            }
        )
    manifest = {
        "packet_kind": "synthetic_unit_fixture",
        "source": {
            "sha256": "0" * 64,
            "reader_metadata": {
                "timestamp_kind": "pts",
                "time_base_numerator": 1,
                "time_base_denominator": 15360,
            },
        },
        "source_identity": {
            "expected_sha256": "0" * 64,
            "sha256_before": "0" * 64,
            "sha256_after": "0" * 64,
            "unchanged": True,
        },
        "images": rows,
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    review = root / "review.txt"
    review.write_text("synthetic review fixture; unreviewed", encoding="utf-8")
    return review


def _canonical_json_for_test(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _run_test_fixture(source: Path, output: Path, review: Path):
    return _run_synthetic_fixture_experiment_for_tests(source, output, review)


def test_portrait_experiment_persists_bound_raw_scores_without_identity(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    review = _write_fixture(source)
    output = tmp_path / "experiment"

    manifest = _run_test_fixture(source, output, review)

    ranks = json.loads((output / "raw_rankings.json").read_text())
    diagnostics = json.loads((output / "derived_diagnostics.json").read_text())
    templates = json.loads((output / "template_bank.json").read_text())
    assert manifest.frame_count == 160
    assert manifest.template_count == 4
    assert manifest.raw_rank_count == 640
    assert sum(rank["seed_frame"] for rank in ranks) == 12
    assert all(rank["identity"] == "unknown" and rank["side"] == "unknown" for rank in ranks)
    assert diagnostics["nonseed_score_count"] == 628
    assert diagnostics["identity_resolution"].startswith("none;")
    assert diagnostics["debug_frame_count"] == 160
    assert all(rank["overlap_utility_status"] == "unknown_not_evaluated" for rank in ranks)
    assert {item["review_status"] for item in templates} == {"unreviewed_synthetic_test"}
    repeated = _run_test_fixture(source, tmp_path / "experiment-repeat", review)
    assert repeated.raw_rankings_sha256 == manifest.raw_rankings_sha256
    assert repeated.template_bank_sha256 == manifest.template_bank_sha256
    assert repeated.debug_frames_sha256 == manifest.debug_frames_sha256
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        _run_test_fixture(source, output, review)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda row: row.__setitem__("source_pts", row["source_pts"] + 1), "PTS/timebase"),
        (lambda row: row.__setitem__("time_base", "1/1000"), "timing provenance"),
        (lambda row: row.__setitem__("timestamp_seconds", "999/1"), "timestamp does not match"),
        (lambda row: row.pop("inventory_bgr_sha256"), "missing timing or source inventory"),
        (lambda row: row.pop("time_base"), "missing timing or source inventory"),
        (lambda row: row.pop("timestamp_seconds"), "missing timing or source inventory"),
    ],
)
def test_portrait_experiment_rejects_invalid_nonseed_timing_provenance(
    tmp_path: Path, mutate, message: str
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    review = _write_fixture(source)
    manifest_path = source / "manifest.json"
    packet = json.loads(manifest_path.read_text())
    row = next(item for item in packet["images"] if item["frame_index"] == 22000)
    mutate(row)
    manifest_path.write_text(json.dumps(packet), encoding="utf-8")
    manifest_digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    protocol = _ExperimentProtocol(
        source_manifest_sha256=manifest_digest,
        review_sha256=hashlib.sha256(review.read_bytes()).hexdigest(),
        source_video_sha256="0" * 64,
        time_base="1/15360",
        crop_rect=(70, 50, 360, 400),
        review_status="unreviewed_synthetic_test",
    )

    with pytest.raises(ValueError, match=message):
        _run_experiment(source, tmp_path / "output", review, protocol)
    assert not (tmp_path / "output").exists()


def test_portrait_experiment_rejects_wrong_review_binding(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    review = _write_fixture(source)
    expected_review_digest = hashlib.sha256(review.read_bytes()).hexdigest()
    review.write_text("different review", encoding="utf-8")
    protocol = _ExperimentProtocol(
        source_manifest_sha256=hashlib.sha256((source / "manifest.json").read_bytes()).hexdigest(),
        review_sha256=expected_review_digest,
        source_video_sha256="0" * 64,
        time_base="1/15360",
        crop_rect=(70, 50, 360, 400),
        review_status="unreviewed_synthetic_test",
    )

    with pytest.raises(ValueError, match="review digest does not match"):
        _run_experiment(source, tmp_path / "output", review, protocol)


def test_production_entrypoint_rejects_modified_nonseed_pts_even_with_matching_timestamp(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    review = _write_fixture(source)
    manifest_path = source / "manifest.json"
    packet = json.loads(manifest_path.read_text())
    row = next(item for item in packet["images"] if item["frame_index"] == 22000)
    row["source_pts"] += 256
    timestamp = Fraction(row["source_pts"], 15360)
    row["timestamp_seconds"] = str(timestamp)
    row["timestamp_seconds_decimal"] = float(timestamp)
    manifest_path.write_text(json.dumps(packet), encoding="utf-8")

    with pytest.raises(ValueError, match="source manifest digest does not match"):
        run_portrait_experiment(source, tmp_path / "output", review)
    assert not (tmp_path / "output").exists()


def test_production_entrypoint_rejects_unapproved_manifest_and_review(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    review = _write_fixture(source)

    with pytest.raises(ValueError, match="source manifest digest does not match"):
        run_portrait_experiment(source, tmp_path / "output", review)
    assert not (tmp_path / "output").exists()


def test_portrait_experiment_rejects_tampered_derived_summary(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    review = _write_fixture(source)
    output = tmp_path / "output"
    manifest = _run_test_fixture(source, output, review)
    summary_path = output / "derived_diagnostics.json"
    summary = json.loads(summary_path.read_bytes())
    summary["nonseed_score_median"] = 999
    summary["identity_resolution"] = "fabricated accepted"
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    source_rows = json.loads((source / "manifest.json").read_bytes())["images"]

    with pytest.raises(ValueError, match="derived diagnostics read-back hash mismatch"):
        _verify_readback(output, manifest, source_rows)


@pytest.mark.parametrize("bad_path", ["../outside.png", "/tmp/outside.png"])
def test_portrait_experiment_rejects_unsafe_debug_paths_before_read(
    tmp_path: Path, bad_path: str
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    review = _write_fixture(source)
    output = tmp_path / "output"
    manifest = _run_test_fixture(source, output, review)
    summary_path = output / "derived_diagnostics.json"
    summary = json.loads(summary_path.read_bytes())
    summary["debug_frames"][0]["path"] = bad_path
    summary_bytes = json.dumps(summary, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    summary_path.write_bytes(summary_bytes)
    debug_index = summary["debug_frames"]
    manifest = manifest.model_copy(
        update={
            "derived_diagnostics_sha256": hashlib.sha256(summary_bytes).hexdigest(),
            "debug_frames_sha256": hashlib.sha256(
                _canonical_json_for_test(debug_index)
            ).hexdigest(),
        }
    )
    source_rows = json.loads((source / "manifest.json").read_bytes())["images"]

    with pytest.raises(ValueError, match="path must be relative and contained"):
        _verify_readback(output, manifest, source_rows)


def test_portrait_experiment_rejects_symlinked_debug_root(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    review = _write_fixture(source)
    output = tmp_path / "output"
    manifest = _run_test_fixture(source, output, review)
    debug_root = output / "debug_frames"
    original = output / "debug_frames-original"
    debug_root.rename(original)
    debug_root.symlink_to(tmp_path, target_is_directory=True)
    source_rows = json.loads((source / "manifest.json").read_bytes())["images"]

    with pytest.raises(ValueError, match="debug frame root"):
        _verify_readback(output, manifest, source_rows)


def test_portrait_experiment_rejects_debug_symlink(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    review = _write_fixture(source)
    output = tmp_path / "output"
    manifest = _run_test_fixture(source, output, review)
    debug_root = output / "debug_frames"
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"outside")
    symlink = debug_root / "escape.png"
    symlink.symlink_to(outside)
    summary_path = output / "derived_diagnostics.json"
    summary = json.loads(summary_path.read_bytes())
    summary["debug_frames"][0]["path"] = "escape.png"
    summary_bytes = json.dumps(summary, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    summary_path.write_bytes(summary_bytes)
    manifest = manifest.model_copy(
        update={
            "derived_diagnostics_sha256": hashlib.sha256(summary_bytes).hexdigest(),
            "debug_frames_sha256": hashlib.sha256(
                _canonical_json_for_test(summary["debug_frames"])
            ).hexdigest(),
        }
    )
    source_rows = json.loads((source / "manifest.json").read_bytes())["images"]

    with pytest.raises(ValueError, match="symbolic links are forbidden"):
        _verify_readback(output, manifest, source_rows)
