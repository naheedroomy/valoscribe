from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from valoscribe.detectors.portrait_center_localizer import RimHypothesis
from valoscribe.tracking.native_temporal_background import (
    ROW_GROUPS,
    AuthenticatedCrop,
    _register_group,
    _rim_temporal_evidence,
    _run_native_temporal_background,
    analyze_temporal_center,
    run_native_temporal_background,
)


def _crop(frame_index: int, pts: int, image: np.ndarray, pos: int) -> AuthenticatedCrop:
    return AuthenticatedCrop(pos, frame_index, pts, "1/15360", image, 0.0, "0" * 64, "0" * 64)


def _map_image(seed: int = 11, shape: tuple[int, int] = (400, 360)) -> np.ndarray:
    rng = np.random.default_rng(seed)
    noise = rng.integers(0, 256, shape, dtype=np.uint8)
    image = cv2.normalize(cv2.GaussianBlur(noise, (0, 0), 4), None, 35, 85, cv2.NORM_MINMAX)
    cv2.polylines(
        image,
        [np.array([[12, 28], [92, 28], [92, 88]], dtype=np.int32)],
        False,
        175,
        3,
    )
    cv2.line(image, (230, 20), (340, 20), 165, 3)
    cv2.line(image, (300, 285), (350, 365), 155, 3)
    return image


def _group(
    *, moving: bool, stationary: bool = False, brightness: bool = False
) -> list[AuthenticatedCrop]:
    background = _map_image()
    frames: list[AuthenticatedCrop] = []
    for position in range(5):
        image = background.copy()
        x = 180 if stationary else 140 + position * 9 if moving else 140 + position * 2
        cv2.circle(image, (x, 200), 8, 220, 2)
        if brightness:
            image = np.clip(image.astype(np.int16) + position * 8, 0, 255).astype(np.uint8)
        frames.append(_crop(100 + position, 1000 + position * 7680, image, position))
    return frames


def test_relative_translation_direction_cycle_valid_mask_and_determinism() -> None:
    base = _map_image(seed=22)
    group = []
    for position, shift in enumerate((-2, -1, 0, 1, 2)):
        matrix = np.array([[1, 0, shift], [0, 1, 0]], np.float32)
        image = cv2.warpAffine(base, matrix, (360, 400), borderMode=cv2.BORDER_REFLECT)
        group.append(_crop(500 + position, 10000 + position * 7680, image, position))
    registrations, background, residual, alignment = _register_group(group)
    assert alignment["accepted"] is True
    assert len(registrations) == 4
    assert background is not None and residual is not None
    assert all(registration.accepted for registration in registrations)
    by_pos = {registration.neighbor_position: registration for registration in registrations}
    assert by_pos[1].translation_to_center_xy[0] == pytest.approx(1, abs=0.4)
    assert by_pos[3].translation_to_center_xy[0] == pytest.approx(-1, abs=0.4)
    assert all(item.cycle_error_px <= 1 for item in registrations)
    assert all(item.valid_overlap_fraction >= 0.95 for item in registrations)
    rerun = _register_group(group)
    assert [r.translation_to_center_xy for r in registrations] == [
        r.translation_to_center_xy for r in rerun[0]
    ]


def test_moving_rim_is_nonpersistent_but_stationary_rim_is_vetoed() -> None:
    moving = analyze_temporal_center(_group(moving=True))
    assert moving[0]["alignment"]["accepted"] is True
    assert moving[0]["raw_hypothesis_count"] > 0
    moving_statuses = {d["status"] for d in moving[0]["derived_decisions"]}
    assert "temporally_nonpersistent_structural_hypothesis" in moving_statuses

    stationary = analyze_temporal_center(_group(moving=False, stationary=True))
    assert stationary[0]["alignment"]["accepted"] is True
    assert stationary[0]["raw_hypothesis_count"] > 0
    assert any(
        decision["status"] == "vetoed_persistent_or_stationary"
        for decision in stationary[0]["derived_decisions"]
    )


def test_photometric_shift_and_small_noise_do_not_break_registration() -> None:
    group = _group(moving=False, stationary=True, brightness=True)
    for index, frame in enumerate(group):
        noisy = np.clip(frame.image.astype(np.int16) + (index % 2), 0, 255).astype(np.uint8)
        group[index] = _crop(frame.frame_index, frame.source_pts, noisy, frame.manifest_position)
    registrations, _, _, alignment = _register_group(group)
    assert alignment["accepted"] is True
    assert all(registration.accepted for registration in registrations)
    assert max(abs(r.photometric_offset_gray) for r in registrations) > 0


def test_missing_duplicate_and_nonmonotonic_neighbors_fail_closed() -> None:
    group = _group(moving=True)
    missing = _register_group(group[:4])
    assert missing[3]["rejection_reasons"] == ["missing_neighbor_frame"]
    duplicate = list(group)
    duplicate[3] = _crop(duplicate[2].frame_index, duplicate[3].source_pts, duplicate[3].image, 3)
    assert _register_group(duplicate)[3]["rejection_reasons"] == ["duplicate_source_frame"]
    nonmonotonic = list(group)
    nonmonotonic[3] = _crop(103, nonmonotonic[2].source_pts, nonmonotonic[3].image, 3)
    assert _register_group(nonmonotonic)[3]["rejection_reasons"] == [
        "nonmonotonic_or_duplicate_pts"
    ]
    flat = [_crop(200 + i, 2000 + i * 10, np.zeros((400, 360), np.uint8), i) for i in range(5)]
    poor = analyze_temporal_center(flat)
    assert poor[0]["alignment"]["accepted"] is False
    assert "insufficient_registration_texture" in poor[0]["alignment"]["rejection_reasons"]
    assert all(d["status"] == "abstain_poor_registration" for d in poor[0]["derived_decisions"])


def _fixture_packet(tmp_path: Path) -> tuple[Path, list[dict[str, object]]]:
    root = tmp_path / "packet"
    root.mkdir()
    source_rows: list[dict[str, object]] = []
    selected = {i for group in ROW_GROUPS for i in group}
    for position in range(160):
        frame_index = 10000 + 30 * position
        pts = 200000 + position * 7680
        row: dict[str, object] = {
            "frame_index": frame_index,
            "source_pts": pts,
            "time_base": "1/15360",
            "candidate_crop_rect_xywh": [0, 0, 360, 400],
        }
        if position in selected:
            group_index = next(i for i, group in enumerate(ROW_GROUPS) if position in group)
            group_pos = ROW_GROUPS[group_index].index(position)
            image = _map_image(seed=group_index + 40)
            x = 120 + group_pos * 10
            cv2.circle(image, (x, 200), 8, 220, 2)
            ok, encoded = cv2.imencode(".png", cv2.cvtColor(image, cv2.COLOR_GRAY2BGR))
            assert ok
            png = encoded.tobytes()
            crop_path = f"crops/frame-{frame_index}.png"
            full_path = f"full/frame-{frame_index}.png"
            (root / "crops").mkdir(exist_ok=True)
            (root / "full").mkdir(exist_ok=True)
            (root / crop_path).write_bytes(png)
            (root / full_path).write_bytes(png)
            decoded = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
            assert decoded is not None
            row["candidate_crop_png"] = {
                "path": crop_path,
                "sha256": hashlib.sha256(png).hexdigest(),
                "crop_bgr_sha256": hashlib.sha256(decoded.tobytes()).hexdigest(),
                "dimensions_px": [360, 400],
            }
            row["full_frame_png"] = {
                "path": full_path,
                "sha256": hashlib.sha256(png).hexdigest(),
                "dimensions_px": [360, 400],
            }
            row["decoded_bgr_sha256"] = hashlib.sha256(decoded.tobytes()).hexdigest()
        source_rows.append(row)
    manifest = {"packet_kind": "synthetic_test_packet", "images": source_rows}
    (root / "manifest.json").write_text(json.dumps(manifest, sort_keys=True))
    return root, source_rows


def test_runner_authenticates_realistic_packet_and_writes_separate_diagnostics(
    tmp_path: Path,
) -> None:
    source, _ = _fixture_packet(tmp_path)
    output = tmp_path / "run"
    report = _run_native_temporal_background(source, output, expected_manifest_sha256=None)
    assert report["summary"]["center_frames"] == [10060, 12400, 14710]
    assert len(report["records"]) == 3
    assert (output / "raw-hypotheses.jsonl").is_file()
    assert (output / "derived-decisions.jsonl").is_file()
    assert (output / "frame-10060-background.png").is_file()
    assert (output / "manifest.json").is_file()
    assert "grayscale_conversion" in report["frame_costs_ms"]["10060"]
    assert "context_decode" not in report["frame_costs_ms"]["10060"]
    assert "context_grayscale_conversion_ms" in report["records"][0]
    second_output = tmp_path / "run-repeat"
    _run_native_temporal_background(source, second_output, expected_manifest_sha256=None)
    assert (output / "raw-hypotheses.jsonl").read_bytes() == (
        second_output / "raw-hypotheses.jsonl"
    ).read_bytes()
    assert (output / "derived-decisions.jsonl").read_bytes() == (
        second_output / "derived-decisions.jsonl"
    ).read_bytes()


@pytest.mark.parametrize(
    "corruption",
    [
        "crop_hash",
        "crop_bgr_hash",
        "full_png_hash",
        "bgr_hash",
        "pts",
        "path",
        "crop_symlink",
        "duplicate_frame",
        "duplicate_pts",
    ],
)
def test_runner_rejects_source_tampering_before_output(tmp_path: Path, corruption: str) -> None:
    source, rows = _fixture_packet(tmp_path)
    manifest_path = source / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    row = manifest["images"][2]
    if corruption == "crop_hash":
        row["candidate_crop_png"]["sha256"] = "0" * 64
    elif corruption == "crop_bgr_hash":
        row["candidate_crop_png"]["crop_bgr_sha256"] = "0" * 64
    elif corruption == "full_png_hash":
        row["full_frame_png"]["sha256"] = "0" * 64
    elif corruption == "bgr_hash":
        row["decoded_bgr_sha256"] = "0" * 64
    elif corruption == "pts":
        row["source_pts"] = manifest["images"][1]["source_pts"]
    elif corruption == "path":
        row["candidate_crop_png"]["path"] = "../outside.png"
    elif corruption == "crop_symlink":
        original = source / row["candidate_crop_png"]["path"]
        target = tmp_path / "outside-crop.png"
        target.write_bytes(original.read_bytes())
        original.unlink()
        original.symlink_to(target)
    elif corruption == "duplicate_frame":
        manifest["images"][3]["frame_index"] = row["frame_index"]
    elif corruption == "duplicate_pts":
        manifest["images"][3]["source_pts"] = row["source_pts"]
    manifest_path.write_text(json.dumps(manifest, sort_keys=True))
    output = tmp_path / "must-not-exist"
    with pytest.raises((ValueError, KeyError)):
        _run_native_temporal_background(source, output, expected_manifest_sha256=None)
    assert not output.exists()


def test_runner_refuses_existing_and_symlink_outputs(tmp_path: Path) -> None:
    source, _ = _fixture_packet(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(FileExistsError):
        run_native_temporal_background(tmp_path / "missing", link)
    assert not list(target.iterdir())


def test_source_symlink_is_rejected_before_output_creation(tmp_path: Path) -> None:
    source, _ = _fixture_packet(tmp_path)
    manifest = json.loads((source / "manifest.json").read_text())
    crop_path = source / manifest["images"][2]["candidate_crop_png"]["path"]
    external = tmp_path / "external.png"
    external.write_bytes(crop_path.read_bytes())
    crop_path.unlink()
    crop_path.symlink_to(external)
    output = tmp_path / "must-not-exist"
    with pytest.raises(ValueError, match="symlinked or escapes"):
        _run_native_temporal_background(source, output, expected_manifest_sha256=None)
    assert not output.exists()


def test_wrong_source_identity_digest_is_rejected_before_output(tmp_path: Path) -> None:
    source, _ = _fixture_packet(tmp_path)
    output = tmp_path / "must-not-exist"
    with pytest.raises(ValueError, match="source manifest digest"):
        _run_native_temporal_background(source, output, expected_manifest_sha256="0" * 64)
    assert not output.exists()


def test_failed_debug_write_never_emits_success_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, _ = _fixture_packet(tmp_path)
    monkeypatch.setattr(cv2, "imwrite", lambda *_args, **_kwargs: False)
    output = tmp_path / "write-failed"
    with pytest.raises(OSError, match="failed to write temporal diagnostic image"):
        _run_native_temporal_background(source, output, expected_manifest_sha256=None)
    assert not output.exists()


def test_invalid_rim_background_samples_abstain_not_persist(tmp_path: Path) -> None:
    del tmp_path
    candidate = RimHypothesis(
        center_x=40.0,
        center_y=50.0,
        boundary_xywh=(32, 42, 16, 16),
        circularity=1.0,
        status="structural_hypothesis",
        reasons=["synthetic"],
        radius_px=8.0,
    )
    residual = np.full((100, 100), 255, np.uint8)
    invalid = _rim_temporal_evidence(candidate, residual, np.zeros((100, 100), bool))
    assert invalid["valid_support_coverage"] == 0.0
    assert invalid["fraction_nonpersistent"] is None
    assert invalid["reason"] == "insufficient_valid_rim_background_coverage"

    boundary_mask = np.zeros((100, 100), bool)
    boundary_mask[:50] = True
    partial = _rim_temporal_evidence(candidate, residual, boundary_mask)
    assert partial["valid_support_coverage"] < 0.75
    assert partial["fraction_nonpersistent"] is None
    assert partial["reason"] == "insufficient_valid_rim_background_coverage"

    supported = _rim_temporal_evidence(
        candidate, np.zeros((100, 100), np.uint8), np.ones((100, 100), bool)
    )
    assert supported["valid_support_coverage"] == 1.0
    assert supported["fraction_nonpersistent"] == 0.0
    assert supported["reason"] is None


def test_negative_phase_consensus_and_cycle_rejections(monkeypatch: pytest.MonkeyPatch) -> None:
    from valoscribe.tracking import native_temporal_background as temporal

    group = _group(moving=False, stationary=True)
    monkeypatch.setattr(
        temporal,
        "_phase",
        lambda *_args: (0.0, 0.0, -1.0, 0.0, 0.0, 0.0, -1.0, 0.0),
    )
    negative = _register_group(group)
    assert negative[3]["accepted"] is False
    assert "poor_phase_response" in negative[3]["rejection_reasons"]

    calls = 0

    def inconsistent_cycle(*_args: object) -> tuple[float, ...]:
        nonlocal calls
        calls += 1
        shift_x = 2.0 if calls == 5 else 0.0
        return (shift_x, 0.0, 1.0, 0.0, shift_x, 0.0, 1.0, 1.0)

    monkeypatch.setattr(temporal, "_phase", inconsistent_cycle)
    cycle = _register_group(group)
    assert cycle[3]["accepted"] is False
    assert "cycle_inconsistency" in cycle[0][0].rejection_reasons


@pytest.mark.parametrize("failure", ["code_digest", "output_hash", "manifest_write"])
def test_late_publication_failures_leave_no_final_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    from valoscribe.tracking import native_temporal_background as temporal

    source, _ = _fixture_packet(tmp_path)
    output = tmp_path / "late-failure"
    if failure == "code_digest":
        monkeypatch.setattr(
            temporal,
            "_compute_code_sha256",
            lambda: (_ for _ in ()).throw(OSError("code digest")),
            raising=False,
        )
    elif failure == "output_hash":
        monkeypatch.setattr(
            temporal,
            "_hash_output_files",
            lambda *_args: (_ for _ in ()).throw(OSError("output hash")),
            raising=False,
        )
    else:

        def fail_manifest(path: Path, payload: object) -> None:
            if path.name == "manifest.json":
                raise OSError("manifest write")

        monkeypatch.setattr(temporal, "_write_json", fail_manifest, raising=False)
    with pytest.raises(OSError):
        temporal._run_native_temporal_background(source, output, expected_manifest_sha256=None)
    assert not output.exists()
