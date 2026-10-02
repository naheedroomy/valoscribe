from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Callable
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from typing import cast

import cv2
import numpy as np
import pytest
from typer.testing import CliRunner

from valoscribe.commands import minimap as minimap_commands
from valoscribe.commands.minimap import app as minimap_app
from valoscribe.reporting.anonymous_diagnostic import (
    build_anonymous_diagnostic_report,
    render_anonymous_diagnostic_markdown,
)
from valoscribe.reporting.anonymous_replay import (
    _information_lines,
    _short_id_map,
    _text_width,
    _wrap_line,
    render_anonymous_replay,
    validate_replay_cadence,
)
from valoscribe.tracking import anonymous_runner
from valoscribe.tracking.anonymous_artifacts import (
    AnonymousParquetUnavailableError,
    read_anonymous_rows,
    validate_anonymous_rows,
    write_anonymous_run,
)
from valoscribe.tracking.anonymous_runner import (
    _short_tracklet_label,
    _tracklet_label_position,
    run_anonymous_round,
)
from valoscribe.tracking.provenance import local_content_tree_sha256, read_bound_artifact
from valoscribe.types.anonymous_tracking import (
    AnonymousFrameContext,
    AnonymousRoundBounds,
    AnonymousRunManifest,
)
from valoscribe.types.persistent import NormalizedBox, NormalizedPoint, RawMinimapColorCandidate
from valoscribe.types.tracking_provenance import TrackingRunManifest
from valoscribe.video.pts_reader import SequentialPtsVideoSource


def _fixture(
    tmp_path: Path, frame_count: int = 4
) -> tuple[Path, Path, Path, Path, Path, AnonymousRoundBounds]:
    video = tmp_path / "synthetic.avi"
    fourcc = cast(Callable[[str, str, str, str], int], getattr(cv2, "VideoWriter_fourcc"))
    writer = cv2.VideoWriter(str(video), fourcc("M", "J", "P", "G"), 5, (64, 64))
    assert writer.isOpened()
    for index in range(frame_count):
        x = 20 + (index % 4) * 2
        image = np.zeros((64, 64, 3), dtype=np.uint8)
        cv2.circle(image, (x, 24), 5, (0, 0, 255), -1)
        cv2.rectangle(image, (4, 50), (12, 52), (0, 0, 255), -1)
        writer.write(image)
    writer.release()

    hud = tmp_path / "hud.json"
    hud.write_text(
        json.dumps(
            {
                "name": "synthetic-diagnostic-hud",
                "frame_width": 64,
                "frame_height": 64,
                "minimap": {"x": 0, "y": 0, "width": 64, "height": 64},
                "regions": {},
            }
        ),
        encoding="utf-8",
    )
    colors = tmp_path / "colors.json"
    colors.write_text(
        json.dumps(
            {
                "profile_id": "synthetic-diagnostic-colors",
                "colors": [
                    {
                        "color_id": "warm",
                        "ranges": [
                            {"lower": [0, 100, 100], "upper": [10, 255, 255]},
                        ],
                    }
                ],
                "minimum_area_px": 30,
                "maximum_area_fraction": 0.2,
                "minimum_circularity": 0.1,
                "minimum_aspect_ratio": 0.2,
                "maximum_aspect_ratio": 1.0,
                "morphology_kernel_size": 3,
            }
        ),
        encoding="utf-8",
    )
    asset = tmp_path / "map.png"
    assert cv2.imwrite(str(asset), np.zeros((8, 8, 3), dtype=np.uint8))
    map_config = tmp_path / "map.json"
    map_config.write_text(
        json.dumps(
            {
                "map_id": "synthetic-map",
                "canonical_minimap": {
                    "local_asset_path": "map.png",
                    "sha256": hashlib.sha256(asset.read_bytes()).hexdigest(),
                    "asset_version": "synthetic-v1",
                },
                "geometry_status": "pending",
            }
        ),
        encoding="utf-8",
    )

    with SequentialPtsVideoSource(video) as reader:
        inventory = [(frame.frame_index, frame.source_pts) for frame in reader]
        assert reader.complete_stream_verified
    bounds = AnonymousRoundBounds(
        map_number=1,
        round_number=4,
        map_id="synthetic-map",
        start_frame_index=inventory[0][0],
        end_frame_index=inventory[-1][0],
        start_source_pts=inventory[0][1],
        end_source_pts=inventory[-1][1],
        reviewer_id="synthetic-fixture-reviewer",
        evidence_reference="synthetic-fixture-frame-index-list-v1",
        review_status="externally_reviewed",
    )
    return video, hud, colors, map_config, asset, bounds


def test_short_tracklet_marker_stays_inside_crop_at_edges() -> None:
    tracklet_id = "anon-demo-m3-r4-0007"
    label = _short_tracklet_label(tracklet_id)
    assert label == "T0007"
    size, baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.3, 1)
    x, y = _tracklet_label_position((63, 1), 64, 64, label)
    assert 0 <= x and x + size[0] <= 64
    assert y - size[1] >= 0 and y + baseline <= 64


def test_cli_writes_typed_diagnostic_report_and_exact_pts_crop_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("local FFmpeg tools are unavailable")
    pytest.importorskip("pyarrow")
    video, hud, colors, map_config, asset, bounds = _fixture(tmp_path)
    review_manifest = tmp_path / "review.json"
    review_manifest.write_text(
        json.dumps(
            {
                "bounds": bounds.model_dump(mode="json"),
                "context_by_frame": [
                    AnonymousFrameContext(
                        frame_index=index,
                        state="live",
                        reviewer_id="synthetic-fixture-reviewer",
                        evidence_reference=f"synthetic-live-frame-{index}",
                        review_status="externally_reviewed",
                    ).model_dump(mode="json")
                    for index in range(4)
                ],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "diagnostic-output"
    options = [
        "track-anonymous-round",
        "--video", str(video),
        "--review-manifest", str(review_manifest),
        "--hud-config", str(hud),
        "--color-config", str(colors),
        "--map-config", str(map_config),
        "--map-asset", str(asset),
        "--output-root", str(output),
        "--run-id", "synthetic-cli-run",
        "--project-commit", "synthetic-project-commit",
        "--upstream-commit", "synthetic-upstream-commit",
    ]
    result = CliRunner().invoke(minimap_app, options)
    assert result.exit_code == 0, result.output
    run_dir = output / "synthetic-cli-run"
    report = json.loads((run_dir / "diagnostic_report.json").read_text(encoding="utf-8"))
    markdown = (run_dir / "report.md").read_text(encoding="utf-8")
    assert report["decoded_frame_count"] == report["requested_frame_count"] == 4
    assert report["context_unknown_frame_count"] == 0
    assert report["player_identity"] == "unavailable"
    assert report["canonical_map_coordinates"] == "unavailable"
    assert "not confirmed players" in markdown
    assert "PTS" in markdown
    replay = run_dir / "anonymous_minimap_replay.mp4"
    assert replay.is_file() and replay.stat().st_size > 0
    wrapper_model = AnonymousRunManifest.model_validate_json(
        (run_dir / "anonymous_run.json").read_bytes()
    )
    raw_frames, samples = read_anonymous_rows(output, wrapper_model)
    assert validate_replay_cadence(wrapper_model, raw_frames) == Fraction(1, 5)
    playback = cv2.VideoCapture(str(replay))
    playback_fps = playback.get(cv2.CAP_PROP_FPS)
    decoded_count = 0
    try:
        while True:
            decoded, replay_frame = playback.read()
            if not decoded:
                break
            assert replay_frame.shape[1] == 64 + 680
            decoded_count += 1
    finally:
        playback.release()
    assert decoded_count == 4
    assert playback_fps == pytest.approx(5.0)
    assert decoded_count / playback_fps == pytest.approx(4 / 5)
    repeated_candidates = []
    repeated_samples = []
    for index in range(1, 11):
        candidate_id = f"f{raw_frames[0].provenance.frame_index:08d}-c{index - 1:04d}"
        repeated_candidates.append(
            raw_frames[0].candidates[-1].model_copy(
                update={
                    "candidate_id": candidate_id,
                    "candidate": raw_frames[0].candidates[-1].candidate.model_copy(
                        update={"accepted": True, "rejection_reasons": []}
                    ),
                }
            )
        )
        repeated_samples.append(
            samples[0].model_copy(
                update={
                    "tracklet_id": f"anon-replay-T{index:04d}-{index:04d}",
                    "candidate_id": candidate_id,
                }
            )
        )
    ten_candidates_raw = raw_frames[0].model_copy(update={"candidates": tuple(repeated_candidates)})
    short_ids = _short_id_map(repeated_samples)
    lines = _information_lines(ten_candidates_raw, repeated_samples, short_ids)
    sample_lines = [line for line in lines if "full_id=" in line]
    candidate_lines = [line for line in lines if "raw_candidate=" in line]
    assert len(sample_lines) == 10
    assert len(candidate_lines) == len(ten_candidates_raw.candidates) == 10
    assert all(_text_width(wrapped) <= 644 for line in lines for wrapped in _wrap_line(line))
    assert all("detector=" in line and "association=" in line for line in sample_lines)
    unknown_raw = raw_frames[0].model_copy(update={"context": "unknown", "context_evidence": None})
    assert any(
        "omitted and unreviewed" in line
        for line in _information_lines(unknown_raw, [], {})
    )
    unknown_report = build_anonymous_diagnostic_report(
        wrapper_model, [unknown_raw, *raw_frames[1:]], samples, artifacts={}
    )
    assert "unknown includes omitted, unreviewed context" in render_anonymous_diagnostic_markdown(
        unknown_report
    )
    vfr_rows = list(raw_frames)
    changed_provenance = vfr_rows[1].provenance.model_copy(
        update={"source_pts": vfr_rows[1].provenance.source_pts + 1}
    )
    vfr_rows[1] = vfr_rows[1].model_copy(update={"provenance": changed_provenance})
    with pytest.raises(ValueError, match="constant source PTS cadence"):
        validate_replay_cadence(wrapper_model, vfr_rows)

    replay.unlink()
    missing_external = tmp_path / "must-not-be-created.mp4"
    replay.symlink_to(missing_external)
    with pytest.raises(FileExistsError):
        render_anonymous_replay(output, wrapper_model, raw_frames, samples)
    assert not missing_external.exists()
    replay.unlink()
    assert (run_dir / "raw_observations.jsonl").is_file()
    assert (run_dir / "anonymous_tracklets.parquet").is_file()
    second_attempt = CliRunner().invoke(minimap_app, options)
    assert second_attempt.exit_code != 0
    assert (run_dir / "diagnostic_report.json").is_file()
    failed_output = tmp_path / "failed-output"
    failed_options = options.copy()
    failed_options[failed_options.index(str(output))] = str(failed_output)
    failed_options[failed_options.index("synthetic-project-commit")] = ""
    failed_attempt = CliRunner().invoke(minimap_app, failed_options)
    assert failed_attempt.exit_code != 0
    assert not failed_output.exists()
    assert not (tmp_path / ".failed-output.anonymous-run.lock").exists()

    dangling_output = tmp_path / "dangling-output"
    dangling_target = tmp_path / "dangling-target"
    dangling_output.symlink_to(dangling_target)
    dangling_attempt = CliRunner().invoke(
        minimap_app,
        [argument if argument != str(output) else str(dangling_output) for argument in options],
    )
    assert dangling_attempt.exit_code != 0
    assert dangling_output.is_symlink() and not dangling_target.exists()

    staging_failure = tmp_path / "staging-failure"
    monkeypatch.setattr(
        minimap_commands.tempfile,
        "mkdtemp",
        lambda **kwargs: (_ for _ in ()).throw(OSError("synthetic staging failure")),
    )
    staging_args = [
        str(staging_failure) if argument == str(output) else argument for argument in options
    ]
    staging_attempt = CliRunner().invoke(minimap_app, staging_args)
    assert staging_attempt.exit_code != 0
    assert not staging_failure.exists()
    assert not (tmp_path / ".staging-failure.anonymous-run.lock").exists()


def test_cli_publication_collision_does_not_remove_external_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("local FFmpeg tools are unavailable")
    pytest.importorskip("pyarrow")
    video, hud, colors, map_config, asset, bounds = _fixture(tmp_path)
    review_manifest = tmp_path / "collision-review.json"
    review_manifest.write_text(
        json.dumps({"bounds": bounds.model_dump(mode="json"), "context_by_frame": []}),
        encoding="utf-8",
    )
    target = tmp_path / "publication-race"
    options = [
        "track-anonymous-round", "--video", str(video), "--review-manifest", str(review_manifest),
        "--hud-config", str(hud), "--color-config", str(colors), "--map-config", str(map_config),
        "--map-asset", str(asset), "--output-root", str(target), "--run-id", "publish-collision",
        "--project-commit", "synthetic-project-commit",
        "--upstream-commit", "synthetic-upstream-commit",
    ]
    publish = minimap_commands._publish_anonymous_run

    def collide(stage: Path, destination: Path, run_id: str) -> None:
        destination.mkdir()
        (destination / "external-sentinel").write_text("keep", encoding="utf-8")
        publish(stage, destination, run_id)

    monkeypatch.setattr(minimap_commands, "_publish_anonymous_run", collide)
    result = CliRunner().invoke(minimap_app, options)
    assert result.exit_code != 0
    assert (target / "external-sentinel").read_text(encoding="utf-8") == "keep"
    assert not (tmp_path / ".publication-race.anonymous-run.lock").exists()


def test_runner_decodes_detector_associates_writes_and_reads_manifest_bound_outputs(
    tmp_path: Path,
) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("local FFmpeg tools are unavailable")
    pytest.importorskip("pyarrow")
    video, hud, colors, map_config, asset, bounds = _fixture(tmp_path)
    result = run_anonymous_round(
        source_path=video,
        bounds=bounds,
        hud_config_path=hud,
        color_config_path=colors,
        map_config_path=map_config,
        map_asset_path=asset,
        output_root=tmp_path / "runs",
        run_id="synthetic-run",
        project_commit="synthetic-project-commit",
        upstream_commit="synthetic-upstream-commit",
        mode="synthetic",
        context_by_frame={
            index: AnonymousFrameContext(
                frame_index=index,
                state="live",
                reviewer_id="synthetic-fixture-reviewer",
                evidence_reference=f"synthetic-live-frame-{index}",
                review_status="externally_reviewed",
            )
            for index in range(4)
        },
    )
    root = tmp_path / "runs"
    run_dir = root / "synthetic-run"
    assert result["tracklets"] == "anonymous_tracklets.parquet"
    assert (run_dir / "anonymous_tracklets.parquet.provenance.json").is_file()
    assert list((run_dir / "debug").glob("*.png.provenance.json"))

    wrapper = json.loads((run_dir / "anonymous_run.json").read_text(encoding="utf-8"))
    assert wrapper["mode"] == "synthetic"
    assert wrapper["runner_thresholds_validated_for_production"] is False
    assert wrapper["decoder"]["pixel_format"] == "bgr24"
    raw_payload = read_bound_artifact(
        root,
        TrackingRunManifest.model_validate_json((run_dir / "manifest.json").read_bytes()),
        "raw_observations.jsonl",
        expected_run_id="synthetic-run",
        expected_source_sha256=wrapper["tracking_manifest"]["source_video_sha256"],
        expected_config_sha256=wrapper["tracking_manifest"]["config_sha256"],
        expected_artifact_kind="anonymous_raw_jsonl",
    )
    raw = [json.loads(line) for line in raw_payload.splitlines()]
    assert len(raw) == 4
    assert any(candidate["candidate"]["accepted"] for candidate in raw[0]["candidates"])
    assert any(not candidate["candidate"]["accepted"] for candidate in raw[0]["candidates"])
    assert all(
        row["provenance"]["manifest_sha256"] == wrapper["tracking_manifest_sha256"] for row in raw
    )
    assert all(
        row["coordinate_frame"] == "configured_minimap_crop_pixels_normalized" for row in raw
    )
    wrapper_sha256 = hashlib.sha256((run_dir / "anonymous_run.json").read_bytes()).hexdigest()
    assert all(row["runner_manifest_sha256"] == wrapper_sha256 for row in raw)
    assert all("player_id" not in row and "team_id" not in row for row in raw)
    import pyarrow.parquet as pq

    track_rows = pq.read_table(run_dir / "anonymous_tracklets.parquet").to_pylist()
    assert len(track_rows) >= 4
    assert all(row["runner_manifest_sha256"] == wrapper_sha256 for row in track_rows)
    assert all("player_id" not in row and "team_id" not in row for row in track_rows)
    assert all(row["source_pts"] >= 0 and row["timebase_denominator"] > 0 for row in track_rows)
    assert len({row["tracklet_id"] for row in track_rows}) == 1
    from valoscribe.types.anonymous_tracking import AnonymousRunManifest, AnonymousTrackSample

    wrapper_model = AnonymousRunManifest.model_validate_json(
        (run_dir / "anonymous_run.json").read_bytes()
    )
    _, persisted_samples = read_anonymous_rows(root, wrapper_model)
    assert persisted_samples and all(
        isinstance(row, AnonymousTrackSample) for row in persisted_samples
    )
    assert "player_id" not in AnonymousTrackSample.model_fields
    assert "team_id" not in AnonymousTrackSample.model_fields


def test_runner_requires_reviewed_bounds_and_does_not_overwrite(tmp_path: Path) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("local FFmpeg tools are unavailable")
    pytest.importorskip("pyarrow")
    video, hud, colors, map_config, asset, bounds = _fixture(tmp_path)
    bad_bounds = bounds.model_copy(update={"end_frame_index": 999})
    with pytest.raises(ValueError, match="exceed source inventory"):
        run_anonymous_round(
            source_path=video,
            bounds=bad_bounds,
            hud_config_path=hud,
            color_config_path=colors,
            map_config_path=map_config,
            map_asset_path=asset,
            output_root=tmp_path / "invalid-runs",
            run_id="invalid-run",
            project_commit="synthetic-project-commit",
            upstream_commit="synthetic-upstream-commit",
            mode="synthetic",
        )
    assert not (tmp_path / "invalid-runs").exists()
    run_anonymous_round(
        source_path=video,
        bounds=bounds,
        hud_config_path=hud,
        color_config_path=colors,
        map_config_path=map_config,
        map_asset_path=asset,
        output_root=tmp_path / "runs",
        run_id="synthetic-run",
        project_commit="synthetic-project-commit",
        upstream_commit="synthetic-upstream-commit",
        mode="synthetic",
    )
    with pytest.raises(FileExistsError):
        run_anonymous_round(
            source_path=video,
            bounds=bounds,
            hud_config_path=hud,
            color_config_path=colors,
            map_config_path=map_config,
            map_asset_path=asset,
            output_root=tmp_path / "runs",
            run_id="synthetic-run",
            project_commit="synthetic-project-commit",
            upstream_commit="synthetic-upstream-commit",
            mode="synthetic",
        )


def test_runner_rejects_partial_decode_without_creating_final_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("local FFmpeg tools are unavailable")
    pytest.importorskip("pyarrow")
    video, hud, colors, map_config, asset, bounds = _fixture(tmp_path)
    original_next = SequentialPtsVideoSource.__dict__["__next__"]

    def incomplete(self):
        for index in range(2):
            yield original_next(self)

    monkeypatch.setattr(SequentialPtsVideoSource, "__iter__", incomplete)
    output = tmp_path / "partial-runs"
    with pytest.raises(RuntimeError, match="verified EOF"):
        run_anonymous_round(
            source_path=video,
            bounds=bounds,
            hud_config_path=hud,
            color_config_path=colors,
            map_config_path=map_config,
            map_asset_path=asset,
            output_root=output,
            run_id="partial-run",
            project_commit="project",
            upstream_commit="upstream",
            mode="synthetic",
        )
    assert not output.exists()


@pytest.mark.parametrize("changed_input", ["source", "config", "map"])
def test_runner_rechecks_changed_inputs_before_creating_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed_input: str
) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("local FFmpeg tools are unavailable")
    pytest.importorskip("pyarrow")
    video, hud, colors, map_config, asset, bounds = _fixture(tmp_path)
    detector = anonymous_runner.MinimapColorCandidateDetector
    original_detect = detector.detect
    changed = False
    target = {"source": video, "config": hud, "map": asset}[changed_input]

    def change_input(self, *args, **kwargs):
        nonlocal changed
        result = original_detect(self, *args, **kwargs)
        if not changed:
            target.write_bytes(target.read_bytes() + b" changed")
            changed = True
        return result

    monkeypatch.setattr(detector, "detect", change_input)
    output = tmp_path / "changed-runs"
    message = (
        "Source video changed between probe and decode"
        if changed_input == "source"
        else "config or map asset bytes changed"
    )
    with pytest.raises(RuntimeError, match=message):
        run_anonymous_round(
            source_path=video,
            bounds=bounds,
            hud_config_path=hud,
            color_config_path=colors,
            map_config_path=map_config,
            map_asset_path=asset,
            output_root=output,
            run_id="changed-run",
            project_commit="project",
            upstream_commit="upstream",
            mode="synthetic",
        )
    assert not output.exists()


def test_runner_contract_is_in_fingerprint_and_changes_its_digest(tmp_path: Path) -> None:
    fingerprint_paths = anonymous_runner.ANONYMOUS_CODE_FINGERPRINT_PATHS
    cropper_path = "src/valoscribe/detectors/cropper.py"
    source_contract_path = "src/valoscribe/types/source_video.py"
    assert cropper_path in fingerprint_paths
    assert source_contract_path in fingerprint_paths
    for relative_path in fingerprint_paths:
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("initial behavior", encoding="utf-8")
    before = local_content_tree_sha256(tmp_path, fingerprint_paths)
    cropper = tmp_path / cropper_path
    cropper.write_text("changed crop behavior", encoding="utf-8")
    assert local_content_tree_sha256(tmp_path, fingerprint_paths) != before
    before_source_change = local_content_tree_sha256(tmp_path, fingerprint_paths)
    source_contract = tmp_path / source_contract_path
    source_contract.write_text("changed source video validation", encoding="utf-8")
    assert local_content_tree_sha256(tmp_path, fingerprint_paths) != before_source_change


@pytest.mark.parametrize("gap_kind", ["empty_candidates", "nonlive"])
def test_candidate_gaps_and_nonlive_frames_break_tracklet_continuity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, gap_kind: str
) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("local FFmpeg tools are unavailable")
    pytest.importorskip("pyarrow")
    video, hud, colors, map_config, asset, bounds = _fixture(tmp_path)
    contexts = {
        index: AnonymousFrameContext(
            frame_index=index,
            state="nonlive" if gap_kind == "nonlive" and index == 1 else "live",
            reviewer_id="r",
            evidence_reference=f"e{index}",
            review_status="externally_reviewed",
        )
        for index in range(4)
    }
    if gap_kind == "empty_candidates":
        detector = anonymous_runner.MinimapColorCandidateDetector
        original_detect = detector.detect

        def omit_frame_one(self, image, *, vod_timestamp_s, source_frame):
            result = original_detect(
                self, image, vod_timestamp_s=vod_timestamp_s, source_frame=source_frame
            )
            return replace(result, candidates=()) if source_frame == 1 else result

        monkeypatch.setattr(detector, "detect", omit_frame_one)
    result = run_anonymous_round(
        source_path=video,
        bounds=bounds,
        hud_config_path=hud,
        color_config_path=colors,
        map_config_path=map_config,
        map_asset_path=asset,
        output_root=tmp_path / "gap-runs",
        run_id="gap-run",
        project_commit="project",
        upstream_commit="upstream",
        mode="synthetic",
        context_by_frame=contexts,
    )
    wrapper_path = Path(result["run_dir"]) / "anonymous_run.json"
    from valoscribe.types.anonymous_tracking import AnonymousRunManifest

    _, rows = read_anonymous_rows(
        tmp_path / "gap-runs", AnonymousRunManifest.model_validate_json(wrapper_path.read_bytes())
    )
    frame_zero = {row.tracklet_id for row in rows if row.frame_index == 0}
    frame_two = {row.tracklet_id for row in rows if row.frame_index == 2}
    frame_three = {row.tracklet_id for row in rows if row.frame_index == 3}
    assert frame_zero and frame_two and frame_zero.isdisjoint(frame_two)
    if gap_kind == "nonlive":
        assert all(row.frame_index != 1 for row in rows)
    assert frame_three and frame_two == frame_three


def test_empty_tracklet_output_preserves_explicit_arrow_columns(tmp_path: Path) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("local FFmpeg tools are unavailable")
    pytest.importorskip("pyarrow")
    import pyarrow.parquet as pq

    video, hud, colors, map_config, asset, bounds = _fixture(tmp_path)
    result = run_anonymous_round(
        source_path=video,
        bounds=bounds,
        hud_config_path=hud,
        color_config_path=colors,
        map_config_path=map_config,
        map_asset_path=asset,
        output_root=tmp_path / "empty-runs",
        run_id="empty-run",
        project_commit="project",
        upstream_commit="upstream",
        mode="synthetic",
    )
    table = pq.read_table(Path(result["run_dir"]) / "anonymous_tracklets.parquet")
    assert table.num_rows == 0
    assert "candidate_id" in table.column_names
    assert table.schema.field("frame_index").type == __import__("pyarrow").int64()


def test_consumer_readback_rejects_tampered_artifact(tmp_path: Path) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("local FFmpeg tools are unavailable")
    pytest.importorskip("pyarrow")
    video, hud, colors, map_config, asset, bounds = _fixture(tmp_path)
    result = run_anonymous_round(
        source_path=video,
        bounds=bounds,
        hud_config_path=hud,
        color_config_path=colors,
        map_config_path=map_config,
        map_asset_path=asset,
        output_root=tmp_path / "tampered-runs",
        run_id="tampered-run",
        project_commit="project",
        upstream_commit="upstream",
        mode="synthetic",
    )
    from valoscribe.types.anonymous_tracking import AnonymousRunManifest

    wrapper = AnonymousRunManifest.model_validate_json(
        (Path(result["run_dir"]) / "anonymous_run.json").read_bytes()
    )
    artifact = Path(result["run_dir"]) / "raw_observations.jsonl"
    artifact.write_bytes(artifact.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="artifact payload or provenance binding mismatch"):
        read_anonymous_rows(tmp_path / "tampered-runs", wrapper)


def _single_frame_two_tracklets(tmp_path: Path, run_name: str):
    from datetime import datetime, timezone

    from valoscribe.tracking.anonymous_artifacts import anonymous_run_manifest_sha256
    from valoscribe.tracking.provenance import manifest_sha256
    from valoscribe.types.anonymous_tracking import (
        AnonymousCandidateObservation,
        AnonymousDecoderProvenance,
        AnonymousRawFrameObservation,
        AnonymousRoundBounds,
        AnonymousRunManifest,
        AnonymousTrackSample,
    )
    from valoscribe.types.tracking_provenance import (
        ConfigFileProvenance,
        TrackingObservationProvenance,
        TrackingRunManifest,
        canonical_config_sha256,
    )

    digest = "a" * 64
    hud = ConfigFileProvenance(config_id="hud", filename="hud.json", file_sha256=digest)
    colors = ConfigFileProvenance(config_id="colors", filename="colors.json", file_sha256=digest)
    map_config = ConfigFileProvenance(config_id="map", filename="map.json", file_sha256=digest)
    manifest = TrackingRunManifest(
        run_id=run_name,
        source_path="synthetic-input-not-decoded",
        source_video_sha256=digest,
        source_width=64,
        source_height=64,
        fps_numerator=5,
        fps_denominator=1,
        timebase_numerator=1,
        timebase_denominator=5,
        map_id="synthetic-map",
        map_number=1,
        round_number=4,
        start_frame_index=1,
        end_frame_index=1,
        start_source_pts=1,
        end_source_pts=1,
        start_timestamp_s=0.2,
        end_timestamp_s=0.2,
        hud_config=hud,
        color_config=colors,
        map_config=map_config,
        config_sha256=canonical_config_sha256(hud, colors, map_config),
        map_asset_sha256=digest,
        map_asset_version="synthetic-v1",
        project_commit="project",
        upstream_commit="upstream",
        code_fingerprint_sha256=digest,
        detector_version="synthetic-detector-v1",
        tracker_version="synthetic-tracker-v1",
        started_at=datetime.now(timezone.utc),
    )
    bounds = AnonymousRoundBounds(
        map_number=1,
        round_number=4,
        map_id="synthetic-map",
        start_frame_index=1,
        end_frame_index=1,
        start_source_pts=1,
        end_source_pts=1,
        reviewer_id="synthetic-reviewer",
        evidence_reference="synthetic-single-frame-v1",
        review_status="externally_reviewed",
    )
    wrapper = AnonymousRunManifest(
        mode="synthetic",
        tracking_manifest=manifest,
        tracking_manifest_sha256=manifest_sha256(manifest),
        decoder=AnonymousDecoderProvenance(
            ffmpeg_version="synthetic",
            ffprobe_version="synthetic",
            timestamp_kind="pts",
            timestamp_timebase_numerator=1,
            timestamp_timebase_denominator=5,
        ),
        bounds=bounds,
        max_step_crop_fraction=0.2,
        max_gap_seconds=1.0,
        ambiguity_margin=0.1,
    )
    candidates = [
        RawMinimapColorCandidate(
            vod_timestamp_s=0.2,
            source_frame=1,
            color_profile_id="colors",
            broadcast_color="warm",
            crop_point=NormalizedPoint(x=x, y=0.5),
            bounding_box=NormalizedBox(x=x, y=0.5, width=0.02, height=0.02),
            contour_area_px=30,
            mask_pixel_count=30,
            detector_confidence=0.9,
            accepted=True,
        )
        for x in (0.3, 0.6)
    ]
    candidate_ids = ("f00000001-c0000", "f00000001-c0001")
    raw = [
        AnonymousRawFrameObservation(
            provenance=TrackingObservationProvenance(
                run_id=run_name,
                manifest_sha256=manifest_sha256(manifest),
                source_video_sha256=digest,
                config_sha256=manifest.config_sha256,
                map_id=manifest.map_id,
                map_number=manifest.map_number,
                round_number=manifest.round_number,
                frame_index=1,
                source_pts=1,
                timebase_numerator=1,
                timebase_denominator=5,
                timestamp_s=0.2,
            ),
            runner_manifest_sha256=anonymous_run_manifest_sha256(wrapper),
            crop_x=0,
            crop_y=0,
            crop_width=64,
            crop_height=64,
            coordinate_frame="configured_minimap_crop_pixels_normalized",
            context="live",
            context_evidence=AnonymousFrameContext(
                frame_index=1,
                state="live",
                reviewer_id="synthetic-reviewer",
                evidence_reference="synthetic-single-frame-v1",
                review_status="externally_reviewed",
            ),
            candidates=tuple(
                AnonymousCandidateObservation(candidate_id=candidate_id, candidate=candidate)
                for candidate_id, candidate in zip(candidate_ids, candidates, strict=True)
            ),
            debug_png_sha256=hashlib.sha256(b"synthetic debug overlay").hexdigest(),
        )
    ]
    samples = [
        AnonymousTrackSample(
            manifest_sha256=manifest_sha256(manifest),
            runner_manifest_sha256=anonymous_run_manifest_sha256(wrapper),
            frame_index=1,
            source_pts=1,
            timebase_numerator=1,
            timebase_denominator=5,
            timestamp_s=0.2,
            tracklet_id=f"anon-{run_name}-m1-r4-{index:04d}",
            candidate_id=candidate_id,
            broadcast_color=candidate.broadcast_color,
            crop_x_normalized=candidate.crop_point.x,
            crop_y_normalized=candidate.crop_point.y,
            confidence=candidate.detector_confidence,
            association_confidence=0,
            evidence_candidate_ids=(candidate_id,),
            motion_distance_crop_fraction=0,
        )
        for index, (candidate_id, candidate) in enumerate(
            zip(candidate_ids, candidates, strict=True), start=1
        )
    ]
    debug = {"debug/candidates_00000001.png": b"synthetic debug overlay"}
    validate_anonymous_rows(wrapper, raw, samples, debug)
    return tmp_path, wrapper, raw, samples, debug


def test_validator_rejects_duplicate_tracklet_samples_per_frame(
    tmp_path: Path,
) -> None:
    _, wrapper, raw, samples, debug = _single_frame_two_tracklets(tmp_path, "same-frame")
    assert samples[0].frame_index == samples[1].frame_index
    assert samples[0].candidate_id != samples[1].candidate_id
    assert samples[0].tracklet_id != samples[1].tracklet_id
    collision = [samples[0], samples[1].model_copy(
        update={"tracklet_id": samples[0].tracklet_id}
    )]
    with pytest.raises(ValueError, match="duplicate tracklet sample for frame"):
        validate_anonymous_rows(wrapper, raw, collision, debug)


def test_writer_preflight_rejects_duplicate_tracklet_samples_per_frame(
    tmp_path: Path,
) -> None:
    pytest.importorskip("pyarrow")
    _, wrapper, raw, samples, debug = _single_frame_two_tracklets(tmp_path, "same-frame-writer")
    collision = [samples[0], samples[1].model_copy(
        update={"tracklet_id": samples[0].tracklet_id}
    )]
    output = tmp_path / "rejected-collision"
    with pytest.raises(ValueError, match="duplicate tracklet sample for frame"):
        write_anonymous_run(
            runs_root=output, wrapper=wrapper, raw_frames=raw, samples=collision,
            debug_pngs=debug,
        )
    assert not output.exists()


def test_consumer_rejects_resealed_duplicate_tracklet_samples_per_frame(
    tmp_path: Path,
) -> None:
    pytest.importorskip("pyarrow")
    import pyarrow as pa
    import pyarrow.parquet as pq

    from valoscribe.types.tracking_provenance import TrackingArtifactBinding

    _, wrapper, raw, samples, debug = _single_frame_two_tracklets(tmp_path, "resealed-same-frame")
    runs_root = tmp_path / "valid-distinct-tracklets"
    write_anonymous_run(
        runs_root=runs_root, wrapper=wrapper, raw_frames=raw, samples=samples,
        debug_pngs=debug,
    )
    run_dir = runs_root / wrapper.tracking_manifest.run_id
    parquet_path = run_dir / "anonymous_tracklets.parquet"
    table = pq.read_table(parquet_path)
    rows = table.to_pylist()
    assert rows[0]["candidate_id"] != rows[1]["candidate_id"]
    rows[1]["tracklet_id"] = rows[0]["tracklet_id"]
    resealed = pa.Table.from_pylist(rows, schema=table.schema)
    sink = pa.BufferOutputStream()
    pq.write_table(resealed, sink)
    payload = sink.getvalue().to_pybytes()
    parquet_path.write_bytes(payload)
    binding_path = Path(str(parquet_path) + ".provenance.json")
    binding = TrackingArtifactBinding.model_validate_json(binding_path.read_bytes())
    binding_path.write_text(
        json.dumps(
            binding.model_copy(update={"payload_sha256": hashlib.sha256(payload).hexdigest()})
            .model_dump(mode="json"),
            sort_keys=True, separators=(",", ":"),
        ) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate tracklet sample for frame"):
        read_anonymous_rows(runs_root, wrapper)


def test_semantic_preflight_rejects_tracklet_wrapper_digest_mismatch(tmp_path: Path) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("local FFmpeg tools are unavailable")
    pytest.importorskip("pyarrow")
    video, hud, colors, map_config, asset, bounds = _fixture(tmp_path)
    output = tmp_path / "semantic-runs"
    result = run_anonymous_round(
        source_path=video,
        bounds=bounds,
        hud_config_path=hud,
        color_config_path=colors,
        map_config_path=map_config,
        map_asset_path=asset,
        output_root=output,
        run_id="semantic-run",
        project_commit="project",
        upstream_commit="upstream",
        mode="synthetic",
        context_by_frame={
            index: AnonymousFrameContext(
                frame_index=index,
                state="live",
                reviewer_id="r",
                evidence_reference=f"live-{index}",
                review_status="externally_reviewed",
            )
            for index in range(4)
        },
    )
    from valoscribe.types.anonymous_tracking import AnonymousRunManifest

    wrapper = AnonymousRunManifest.model_validate_json(
        (Path(result["run_dir"]) / "anonymous_run.json").read_bytes()
    )
    raw, samples = read_anonymous_rows(output, wrapper)
    malformed = [samples[0].model_copy(update={"runner_manifest_sha256": "0" * 64})]
    with pytest.raises(ValueError, match="tracklet wrapper digest mismatch"):
        validate_anonymous_rows(wrapper, raw, malformed)


@pytest.mark.parametrize(
    ("field", "value"),
    [("source_frame", 999), ("vod_timestamp_s", 0.123), ("color_profile_id", "other-profile")],
)
def test_semantic_preflight_rejects_candidate_source_contradictions(
    tmp_path: Path, field: str, value: object
) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("local FFmpeg tools are unavailable")
    pytest.importorskip("pyarrow")
    video, hud, colors, map_config, asset, bounds = _fixture(tmp_path)
    result = run_anonymous_round(
        source_path=video, bounds=bounds, hud_config_path=hud, color_config_path=colors,
        map_config_path=map_config, map_asset_path=asset, output_root=tmp_path / "runs",
        run_id="candidate-provenance", project_commit="project", upstream_commit="upstream",
        mode="synthetic", context_by_frame={
            index: AnonymousFrameContext(frame_index=index, state="live", reviewer_id="r",
                                         evidence_reference=f"live-{index}",
                                         review_status="externally_reviewed")
            for index in range(4)
        },
    )
    from valoscribe.types.anonymous_tracking import AnonymousRunManifest

    wrapper = AnonymousRunManifest.model_validate_json(
        (Path(result["run_dir"]) / "anonymous_run.json").read_bytes()
    )
    raw, samples = read_anonymous_rows(tmp_path / "runs", wrapper)
    row_index = next(i for i, row in enumerate(raw) if row.candidates)
    row = raw[row_index]
    observation = row.candidates[0]
    candidate = observation.candidate.model_copy(update={field: value})
    changed_observation = observation.model_copy(update={"candidate": candidate})
    raw[row_index] = row.model_copy(
        update={"candidates": (changed_observation, *row.candidates[1:])}
    )
    with pytest.raises(ValueError, match="raw candidate provenance"):
        validate_anonymous_rows(wrapper, raw, samples)
    if field == "source_frame":
        from valoscribe.types.tracking_provenance import TrackingArtifactBinding

        raw_path = Path(result["run_dir"]) / "raw_observations.jsonl"
        lines = [json.loads(line) for line in raw_path.read_bytes().splitlines()]
        raw_candidate = lines[row_index]["candidates"][0]["candidate"]
        raw_candidate[field] = value
        payload = b"".join(
            json.dumps(line, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
            + b"\n"
            for line in lines
        )
        raw_path.write_bytes(payload)
        binding_path = Path(str(raw_path) + ".provenance.json")
        binding = TrackingArtifactBinding.model_validate_json(binding_path.read_bytes())
        binding_path.write_text(
            json.dumps(
                binding.model_copy(update={"payload_sha256": hashlib.sha256(payload).hexdigest()})
                .model_dump(mode="json"),
                sort_keys=True, separators=(",", ":"),
            ) + "\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="raw candidate provenance"):
            read_anonymous_rows(tmp_path / "runs", wrapper)


def test_semantic_preflight_rejects_impossible_association_evidence(tmp_path: Path) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("local FFmpeg tools are unavailable")
    pytest.importorskip("pyarrow")
    video, hud, colors, map_config, asset, bounds = _fixture(tmp_path)
    result = run_anonymous_round(
        source_path=video, bounds=bounds, hud_config_path=hud, color_config_path=colors,
        map_config_path=map_config, map_asset_path=asset, output_root=tmp_path / "runs",
        run_id="association-semantics", project_commit="project", upstream_commit="upstream",
        mode="synthetic", context_by_frame={
            index: AnonymousFrameContext(frame_index=index, state="live", reviewer_id="r",
                                         evidence_reference=f"live-{index}",
                                         review_status="externally_reviewed")
            for index in range(4)
        },
    )
    from valoscribe.types.anonymous_tracking import AnonymousRunManifest

    wrapper = AnonymousRunManifest.model_validate_json(
        (Path(result["run_dir"]) / "anonymous_run.json").read_bytes()
    )
    raw, samples = read_anonymous_rows(tmp_path / "runs", wrapper)
    linked_index = next(
        i for i, sample in enumerate(samples) if len(sample.evidence_candidate_ids) == 2
    )
    linked = samples[linked_index]
    future_sample = next(
        sample for sample in samples
        if sample.tracklet_id == linked.tracklet_id and sample.frame_index > linked.frame_index
    )
    future_evidence = list(samples)
    future_evidence[linked_index] = linked.model_copy(
        update={"evidence_candidate_ids": (future_sample.candidate_id, linked.candidate_id)}
    )
    with pytest.raises(ValueError, match="adjacent live evidence"):
        validate_anonymous_rows(wrapper, raw, future_evidence)
    invalid_evidence_output = tmp_path / "invalid-evidence-runs"
    valid_debug = {
        f"debug/{path.name}": path.read_bytes()
        for path in (Path(result["run_dir"]) / "debug").glob("candidates_*.png")
    }
    with pytest.raises(ValueError, match="adjacent live evidence"):
        write_anonymous_run(
            runs_root=invalid_evidence_output, wrapper=wrapper, raw_frames=raw,
            samples=future_evidence, debug_pngs=valid_debug,
        )
    assert not invalid_evidence_output.exists()
    old_index = next(
        i for i, sample in enumerate(samples)
        if len(sample.evidence_candidate_ids) == 2 and sample.frame_index >= 2
    )
    old_sample = samples[old_index]
    older_candidate = next(
        sample for sample in samples
        if sample.tracklet_id == old_sample.tracklet_id
        and sample.frame_index < old_sample.frame_index - 1
    )
    old_evidence = list(samples)
    old_evidence[old_index] = old_sample.model_copy(
        update={"evidence_candidate_ids": (older_candidate.candidate_id, old_sample.candidate_id)}
    )
    with pytest.raises(ValueError, match="adjacent live evidence"):
        validate_anonymous_rows(wrapper, raw, old_evidence)
    wrong_distance = list(samples)
    wrong_distance[linked_index] = linked.model_copy(
        update={"motion_distance_crop_fraction": linked.motion_distance_crop_fraction + 0.02}
    )
    with pytest.raises(ValueError, match="distance or confidence"):
        validate_anonymous_rows(wrapper, raw, wrong_distance)
    wrong_confidence = list(samples)
    wrong_confidence[linked_index] = linked.model_copy(
        update={"association_confidence": min(1.0, linked.association_confidence + 0.2)}
    )
    with pytest.raises(ValueError, match="distance or confidence"):
        validate_anonymous_rows(wrapper, raw, wrong_confidence)

    debug_files = {
        f"debug/{path.name}": path.read_bytes()
        for path in (Path(result["run_dir"]) / "debug").glob("candidates_*.png")
    }
    invalid_output = tmp_path / "invalid-debug-runs"
    with pytest.raises(ValueError, match="debug overlay paths"):
        write_anonymous_run(
            runs_root=invalid_output, wrapper=wrapper, raw_frames=raw, samples=samples,
            debug_pngs={},
        )
    assert not invalid_output.exists()
    bad_debug = dict(debug_files)
    debug_key = next(iter(bad_debug))
    bad_debug[debug_key] += b"tampered"
    with pytest.raises(ValueError, match="debug overlay digest"):
        write_anonymous_run(
            runs_root=invalid_output, wrapper=wrapper, raw_frames=raw, samples=samples,
            debug_pngs=bad_debug,
        )
    assert not invalid_output.exists()


def test_ambiguous_candidate_match_starts_new_anonymous_tracklet() -> None:
    def candidate(x: float, frame: int) -> RawMinimapColorCandidate:
        return RawMinimapColorCandidate(
            vod_timestamp_s=frame / 5,
            source_frame=frame,
            color_profile_id="profile",
            broadcast_color="warm",
            crop_point=NormalizedPoint(x=x, y=0.5),
            bounding_box=NormalizedBox(x=x, y=0.5, width=0.02, height=0.02),
            contour_area_px=30,
            mask_pixel_count=30,
            detector_confidence=0.9,
            accepted=True,
        )

    active = {
        "anon-run-m1-r4-0001": (0.40, 0.5, "warm", "old-a", 0.9, 0, 0.0),
        "anon-run-m1-r4-0002": (0.42, 0.5, "warm", "old-b", 0.9, 0, 0.0),
    }
    rows, _ = anonymous_runner._associate(
        [("f00000001-c0000", candidate(0.41, 1))],
        1,
        1,
        1,
        5,
        0.2,
        "run-m1-r4",
        active,
        3,
        anonymous_runner.AnonymousRunnerThresholds(),
    )
    assert len(rows) == 1
    assert rows[0].tracklet_id.endswith("0003")
    assert rows[0].association_confidence == 0


def test_missing_parquet_dependency_fails_before_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("local FFmpeg tools are unavailable")
    video, hud, colors, map_config, asset, bounds = _fixture(tmp_path)

    def unavailable():
        raise AnonymousParquetUnavailableError("install valoscribe[parquet]")

    monkeypatch.setattr(anonymous_runner, "_arrow", unavailable)
    output = tmp_path / "runs"
    with pytest.raises(AnonymousParquetUnavailableError, match="parquet"):
        run_anonymous_round(
            source_path=video,
            bounds=bounds,
            hud_config_path=hud,
            color_config_path=colors,
            map_config_path=map_config,
            map_asset_path=asset,
            output_root=output,
            run_id="no-arrow-run",
            project_commit="synthetic-project-commit",
            upstream_commit="synthetic-upstream-commit",
            mode="synthetic",
        )
    assert not output.exists()
