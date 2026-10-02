"""Tests for the opt-in sequential source-PTS reader."""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import threading
from fractions import Fraction
from pathlib import Path
from typing import BinaryIO, Callable, Literal, cast
from unittest.mock import patch

import numpy as np
import pytest
from pydantic import ValidationError

from valoscribe.types.source_video import SourceVideoFrame, SourceVideoMetadata
from valoscribe.video.pts_reader import SequentialPtsVideoSource


def _probe_frame(
    pts: int | str | None, *, best: int | str | None = None, width: int = 16, height: int = 16
) -> dict[str, object]:
    result: dict[str, object] = {"width": width, "height": height}
    if pts is not None:
        result["pts"] = pts
    if best is not None:
        result["best_effort_timestamp"] = best
    return result


def _probe_source(
    tmp_path: Path,
    frames: list[dict[str, object]],
    *,
    nb_frames: str | None = None,
    empty_streams: bool = False,
) -> SequentialPtsVideoSource:
    path = tmp_path / "input.mp4"
    path.touch()
    source = object.__new__(SequentialPtsVideoSource)
    source.source_path = path
    source._fingerprint = source._stat_fingerprint()
    source._ffprobe = "ffprobe"
    source._ffprobe_version = "ffprobe test"
    source._ffmpeg_version = "ffmpeg test"
    stream: dict[str, object] = {
        "width": 16,
        "height": 16,
        "time_base": "1/1000",
        "avg_frame_rate": "30/1",
        "duration": "1.25",
    }
    if nb_frames is not None:
        stream["nb_frames"] = nb_frames
    response = {
        "streams": [] if empty_streams else [stream],
        "format": {"duration": "1.5"},
        "frames": frames,
    }
    with patch(
        "valoscribe.video.pts_reader.subprocess.run",
        return_value=type(
            "ProbeResult",
            (),
            {"returncode": 0, "stdout": json.dumps(response).encode(), "stderr": b""},
        )(),
    ):
        source.metadata, source._timestamps = source._probe()
    return source


def test_probe_preserves_rational_rate_and_distinct_durations(tmp_path: Path):
    source = _probe_source(tmp_path, [_probe_frame(0), _probe_frame(41)])
    assert (source.metadata.fps_numerator, source.metadata.fps_denominator) == (30, 1)
    assert source.metadata.stream_duration_seconds == Fraction(5, 4)
    assert source.metadata.container_duration_seconds == Fraction(3, 2)
    assert source._timestamps == [(0, "pts"), (41, "pts")]


def test_probe_rejects_empty_stream_inventory(tmp_path: Path):
    with pytest.raises(RuntimeError, match="no selected video stream"):
        _probe_source(tmp_path, [], empty_streams=True)


def test_probe_rejects_optional_stream_count_disagreement(tmp_path: Path):
    with pytest.raises(RuntimeError, match="stream frame count disagrees"):
        _probe_source(tmp_path, [_probe_frame(0), _probe_frame(1)], nb_frames="3")


def test_probe_uses_explicit_best_effort_timestamp_provenance(tmp_path: Path):
    source = _probe_source(tmp_path, [_probe_frame(None, best="3")])
    assert source.metadata.timestamp_kind == "best_effort_timestamp"
    assert source._timestamps == [(3, "best_effort_timestamp")]


@pytest.mark.parametrize(
    "frames",
    [
        [_probe_frame(None)],
        [_probe_frame(1), _probe_frame(1)],
        [_probe_frame(2), _probe_frame(1)],
        [_probe_frame(1), _probe_frame(2, width=17)],
    ],
)
def test_probe_rejects_malformed_timestamp_or_dimension_inventory(tmp_path: Path, frames):
    path = tmp_path / "input.mp4"
    path.touch()
    source = object.__new__(SequentialPtsVideoSource)
    source.source_path = path
    source._fingerprint = source._stat_fingerprint()
    source._ffprobe = "ffprobe"
    source._ffprobe_version = "ffprobe test"
    source._ffmpeg_version = "ffmpeg test"
    response = {
        "streams": [{"width": 16, "height": 16, "time_base": "1/1000", "avg_frame_rate": "30/1"}],
        "frames": frames,
    }
    with patch(
        "valoscribe.video.pts_reader.subprocess.run",
        return_value=type(
            "ProbeResult",
            (),
            {"returncode": 0, "stdout": json.dumps(response).encode(), "stderr": b""},
        )(),
    ):
        with pytest.raises(RuntimeError, match="Invalid ffprobe video inventory"):
            source._probe()


def _valid_frame() -> SourceVideoFrame:
    return SourceVideoFrame(
        frame_index=0,
        source_pts=0,
        time_base_numerator=1,
        time_base_denominator=10,
        timestamp_seconds=Fraction(0),
        timestamp_kind="pts",
        bgr=np.zeros((2, 2, 3), dtype=np.uint8),
    )


def _valid_metadata() -> SourceVideoMetadata:
    return SourceVideoMetadata(
        source_path="local.mp4",
        width=2,
        height=2,
        time_base_numerator=1,
        time_base_denominator=10,
        fps_numerator=10,
        fps_denominator=1,
        frame_count=1,
        timestamp_kind="pts",
        ffprobe_version="probe",
        ffmpeg_version="mpeg",
        file_size=0,
        file_mtime_ns=0,
    )


def test_source_frame_requires_timestamp_to_match_pts_clock():
    with pytest.raises(ValidationError, match="disagrees with source PTS/timebase"):
        SourceVideoFrame(
            frame_index=0,
            source_pts=2,
            time_base_numerator=1,
            time_base_denominator=10,
            timestamp_seconds=Fraction(1, 10),
            timestamp_kind="pts",
            bgr=np.zeros((2, 2, 3), dtype=np.uint8),
        )


def test_consumer_boundary_revalidates_copied_frame_clock_and_identity():
    frame = _valid_frame()
    for invalid_frame in (
        frame.model_copy(update={"frame_index": -1}),
        frame.model_copy(update={"frame_index": 1}),
        frame.model_copy(update={"timestamp_seconds": Fraction(99)}),
    ):
        with pytest.raises((ValidationError, ValueError)):
            invalid_frame.validate_against(_valid_metadata())


def test_consumer_boundary_revalidates_copied_metadata_contract():
    frame = _valid_frame()
    metadata = _valid_metadata()
    for invalid_metadata in (
        metadata.model_copy(update={"frame_count": 0}),
        metadata.model_copy(update={"fps_denominator": 0}),
    ):
        with pytest.raises(ValidationError):
            frame.validate_against(invalid_metadata)


def test_frame_revalidates_mutable_pixels_at_consumer_boundary():
    frame = _valid_frame()
    frame.bgr.resize((3, 2, 3), refcheck=False)
    with pytest.raises(ValueError, match="pixels do not match"):
        frame.validate_against(_valid_metadata())


class _DecoderProcess:
    def __init__(self, payload: bytes, status: int) -> None:
        self.stdout: BinaryIO = io.BytesIO(payload)
        self.stderr: BinaryIO | None = None
        self.returncode: int | None = status
        self.wait_status = status
        self.terminated = False
        self.on_terminate: Callable[[], None] | None = None

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, *args: object, **kwargs: object) -> int:
        self.returncode = self.wait_status
        return self.wait_status

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0
        if self.on_terminate is not None:
            self.on_terminate()

    def kill(self) -> None:
        self.returncode = -9


def _decoder_source(
    tmp_path: Path, payload: bytes, *, frame_count: int = 1, status: int = 0
) -> tuple[SequentialPtsVideoSource, _DecoderProcess]:
    source = object.__new__(SequentialPtsVideoSource)
    source.source_path = tmp_path / "input.mp4"
    source.source_path.touch()
    source._fingerprint = source._stat_fingerprint()
    source.metadata = SourceVideoMetadata(
        source_path=str(source.source_path),
        width=2,
        height=2,
        time_base_numerator=1,
        time_base_denominator=10,
        fps_numerator=10,
        fps_denominator=1,
        frame_count=frame_count,
        timestamp_kind="pts",
        ffprobe_version="probe",
        ffmpeg_version="mpeg",
        file_size=0,
        file_mtime_ns=0,
    )
    timestamps: list[tuple[int, Literal["pts", "best_effort_timestamp"]]] = [
        (index, "pts") for index in range(frame_count)
    ]
    source._timestamps = timestamps

    process = _DecoderProcess(payload, status)
    source._stderr_tail = bytearray(b"decoder diagnostic")
    source._stderr_lock = threading.Lock()
    source._stderr_thread = None
    source._process = cast(subprocess.Popen[bytes], process)
    source._next_index = 0
    source.complete_stream_verified = False
    source._closed = False
    return source, process


@pytest.mark.parametrize(
    "payload,frame_count,message",
    [
        (bytes(5), 1, "ended early at frame 0"),
        (bytes(25), 1, "more frames than ffprobe inventory"),
        (bytes(12), 2, "ended early at frame 1"),
    ],
)
def test_decode_rejects_short_extra_or_count_mismatch(
    tmp_path: Path, payload: bytes, frame_count: int, message: str
):
    source, _ = _decoder_source(tmp_path, payload, frame_count=frame_count)
    with pytest.raises(RuntimeError, match=message):
        list(source)
    assert not source.complete_stream_verified
    assert source._closed


def test_decode_rejects_nonzero_process_exit(tmp_path: Path):
    source, _ = _decoder_source(tmp_path, bytes(12), status=9)
    with pytest.raises(RuntimeError, match=r"ffmpeg failed \(9\)"):
        list(source)
    assert not source.complete_stream_verified


def test_read_exception_closes_process_and_keeps_stream_unverified(tmp_path: Path):
    source, process = _decoder_source(tmp_path, bytes(12))

    class FailedReader(io.BytesIO):
        def read(self, size: int | None = -1) -> bytes:
            raise OSError("injected read failure")

    process.stdout = FailedReader()
    process.returncode = None
    with pytest.raises(OSError, match="injected read failure"):
        next(source)
    assert process.terminated
    assert process.stdout.closed
    assert source._closed and not source.complete_stream_verified


def test_frame_validation_exception_closes_handles_and_keeps_stream_unverified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source, process = _decoder_source(tmp_path, bytes(12))

    def fail_validation(self, metadata):
        raise ValueError("injected frame validation failure")

    monkeypatch.setattr(SourceVideoFrame, "validate_against", fail_validation)
    with pytest.raises(ValueError, match="injected frame validation failure"):
        next(source)
    assert process.stdout.closed
    assert source._closed and not source.complete_stream_verified


def test_stat_change_during_final_verification_closes_handles(tmp_path: Path):
    source, process = _decoder_source(tmp_path, bytes(12))

    class MutatingReader(io.BytesIO):
        def read(self, size: int | None = -1) -> bytes:
            data = super().read(-1 if size is None else size)
            if data:
                source.source_path.write_bytes(b"changed")
            return data

    process.stdout = MutatingReader(bytes(12))
    with pytest.raises(RuntimeError, match="Source video changed"):
        list(source)
    assert process.stdout.closed
    assert source._closed and not source.complete_stream_verified


def test_source_stat_change_before_decode_is_rejected(tmp_path: Path):
    path = tmp_path / "source.mp4"
    path.write_bytes(b"before")
    source = object.__new__(SequentialPtsVideoSource)
    source.source_path = path
    source._fingerprint = source._stat_fingerprint()
    path.write_bytes(b"changed size")
    with pytest.raises(RuntimeError, match="Source video changed"):
        source._check_source_unchanged()


def test_stderr_shutdown_drains_before_collecting_failure_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source, process = _decoder_source(tmp_path, b"")
    entered_read = threading.Event()
    release_read = threading.Event()
    drained = threading.Event()
    premature_close = threading.Event()

    class EventControlledStderr(io.BytesIO):
        def read(self, size: int | None = -1) -> bytes:
            entered_read.set()
            if not release_read.wait(timeout=3):
                raise TimeoutError("stderr drain was not released")
            chunk = super().read(-1 if size is None else size)
            if not chunk:
                drained.set()
            return chunk

        def close(self) -> None:
            if not drained.is_set():
                premature_close.set()
            super().close()

    stderr = EventControlledStderr(b"final diagnostic")
    process.stderr = stderr
    process.returncode = None

    process.on_terminate = release_read.set
    thread_errors: list[BaseException] = []
    monkeypatch.setattr(threading, "excepthook", lambda args: thread_errors.append(args.exc_value))
    source._stderr_thread = threading.Thread(target=source._drain_stderr, args=(stderr,))
    source._stderr_thread.start()
    assert entered_read.wait(timeout=3)
    with pytest.raises(RuntimeError, match="final diagnostic"):
        source._fail("injected decoder failure")
    assert process.terminated
    assert drained.is_set()
    assert not premature_close.is_set()
    assert thread_errors == []
    assert source._closed and not source.complete_stream_verified


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="ffmpeg/ffprobe unavailable"
)
def test_generated_vfr_video_preserves_distinct_pixel_to_pts_pairs_and_b_frames(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    video = tmp_path / "generated.mkv"
    levels = [20, 60, 100, 140, 180, 220, 40, 80, 120, 160, 200, 240]
    raw_frames = np.concatenate([np.full((64, 64, 3), value, dtype=np.uint8) for value in levels])
    raw_path = tmp_path / "frames.rgb"
    raw_path.write_bytes(raw_frames.tobytes())
    subprocess.run(
        [
            shutil.which("ffmpeg") or "ffmpeg",
            "-v",
            "error",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            "64x64",
            "-r",
            "10",
            "-i",
            str(raw_path),
            "-vf",
            "setpts=N+floor(N/3)",
            "-fps_mode",
            "passthrough",
            "-c:v",
            "mpeg4",
            "-bf",
            "2",
            "-q:v",
            "1",
            "-y",
            str(video),
        ],
        check=True,
        capture_output=True,
    )
    probe = subprocess.run(
        [
            shutil.which("ffprobe") or "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=time_base,has_b_frames",
            "-show_packets",
            "-show_entries",
            "packet=pts,dts",
            "-of",
            "json",
            str(video),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    probe_data = json.loads(probe.stdout)
    assert int(probe_data["streams"][0]["has_b_frames"]) > 0
    assert any(
        int(packet["dts"]) < int(packet["pts"])
        for packet in probe_data["packets"]
        if packet.get("dts") is not None
    )

    decoded_by_thread_count = {}
    for thread_count in (1, 4):
        monkeypatch.setattr("valoscribe.video.pts_reader.DECODER_THREADS", thread_count)
        with SequentialPtsVideoSource(video) as source:
            frames = list(source)
            assert source.complete_stream_verified
            decoded_by_thread_count[thread_count] = frames

    frames = decoded_by_thread_count[4]
    single_thread_frames = decoded_by_thread_count[1]
    time_base = Fraction(source.metadata.time_base_numerator, source.metadata.time_base_denominator)
    expected_times = [Fraction(tick, 10) for tick in [0, 1, 2, 4, 5, 6, 8, 9, 10, 12, 13, 14]]
    actual_times = [frame.timestamp_seconds for frame in frames]
    assert actual_times == expected_times
    assert [frame.frame_index for frame in frames] == list(range(len(levels)))
    assert [frame.timestamp_seconds for frame in frames] == [
        frame.source_pts * time_base for frame in frames
    ]
    identified_levels = [
        min(levels, key=lambda level: abs(float(frame.bgr.mean()) - level)) for frame in frames
    ]
    assert identified_levels == levels
    intervals = [right - left for left, right in zip(actual_times, actual_times[1:])]
    assert len(set(intervals)) > 1
    assert [frame.source_pts for frame in single_thread_frames] == [
        frame.source_pts for frame in frames
    ]
    assert all(np.array_equal(one.bgr, four.bgr) for one, four in zip(single_thread_frames, frames))


def test_early_close_does_not_certify_stream(tmp_path: Path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg/ffprobe unavailable")
    video = tmp_path / "generated.mkv"
    subprocess.run(
        [
            shutil.which("ffmpeg") or "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=32x32:r=10:d=1",
            "-c:v",
            "mpeg4",
            "-y",
            str(video),
        ],
        check=True,
        capture_output=True,
    )
    source = SequentialPtsVideoSource(video)
    next(source)
    source.close()
    assert not source.complete_stream_verified
