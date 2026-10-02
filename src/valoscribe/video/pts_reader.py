"""Opt-in, sequential decoder that preserves observed ffprobe source timestamps."""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
from fractions import Fraction
from pathlib import Path
from typing import BinaryIO, Iterator, Literal

import numpy as np

from valoscribe.types.source_video import SourceVideoFrame, SourceVideoMetadata

DECODER_THREADS = 4


class SequentialPtsVideoSource:
    """Join ffprobe decode-order timestamps to a no-seek ffmpeg BGR pipe.

    ``complete_stream_verified`` is true only after EOF, exact frame-count
    validation, process success, and an unchanged source-file stat fingerprint.
    Closing early intentionally leaves it false.
    """

    def __init__(self, source_path: Path | str):
        path = Path(source_path)
        if not path.is_file():
            raise FileNotFoundError(f"Source video must be a local regular file: {path}")
        self.source_path = path.resolve()
        self._fingerprint = self._stat_fingerprint()
        ffprobe = shutil.which("ffprobe")
        ffmpeg = shutil.which("ffmpeg")
        if ffprobe is None or ffmpeg is None:
            raise RuntimeError("Sequential PTS reader requires ffprobe and ffmpeg on PATH")
        self._ffprobe = ffprobe
        self._ffmpeg = ffmpeg
        self._ffprobe_version = self._tool_version(ffprobe)
        self._ffmpeg_version = self._tool_version(ffmpeg)
        self.metadata, self._timestamps = self._probe()
        self._check_source_unchanged()
        self._stderr_tail = bytearray()
        self._stderr_lock = threading.Lock()
        self._stderr_thread: threading.Thread | None = None
        self._process: subprocess.Popen[bytes] | None = None
        self._next_index = 0
        self.complete_stream_verified = False
        self._closed = False

    def _stat_fingerprint(self) -> tuple[int, int, int, int]:
        stat = self.source_path.stat()
        return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)

    def _check_source_unchanged(self) -> None:
        if self._stat_fingerprint() != self._fingerprint:
            raise RuntimeError("Source video changed between probe and decode")

    @staticmethod
    def _tool_version(executable: str) -> str:
        result = subprocess.run(
            [executable, "-version"], capture_output=True, text=True, check=False, timeout=15
        )
        if result.returncode:
            diagnostic = result.stderr[-2000:]
            raise RuntimeError(f"Could not identify media tool {executable}: {diagnostic}")
        return result.stdout.splitlines()[0]

    def _probe(
        self,
    ) -> tuple[SourceVideoMetadata, list[tuple[int, Literal["pts", "best_effort_timestamp"]]]]:
        command = [
            self._ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_streams",
            "-show_format",
            "-show_frames",
            "-show_entries",
            "stream=width,height,time_base,avg_frame_rate,r_frame_rate,duration,nb_frames:stream_tags=rotate:stream_side_data=rotation:format=duration:frame=pts,best_effort_timestamp,width,height",
            "-of",
            "json",
            "-threads",
            str(DECODER_THREADS),
            str(self.source_path),
        ]
        result = subprocess.run(command, capture_output=True, check=False, timeout=None)
        if result.returncode:
            diagnostic = result.stderr[-4000:].decode(errors="replace")
            raise RuntimeError(f"ffprobe failed ({result.returncode}): {diagnostic}")
        try:
            data = json.loads(result.stdout)
            streams = data["streams"]
            if not streams:
                raise ValueError("ffprobe returned no selected video stream")
            stream = streams[0]
            width, height = int(stream["width"]), int(stream["height"])
            time_base = Fraction(stream["time_base"])
            rate_text = stream.get("avg_frame_rate") or stream.get("r_frame_rate")
            rate = Fraction(rate_text)
            if rate <= 0 or time_base <= 0:
                raise ValueError("invalid rate/timebase")
            rotation = int(stream.get("tags", {}).get("rotate", "0")) % 360
            if rotation:
                raise ValueError("rotated streams are unsupported")
            if any(int(item.get("rotation", 0)) % 360 for item in stream.get("side_data_list", [])):
                raise ValueError("rotated streams are unsupported")
            raw_frames = data["frames"]
            timestamps: list[tuple[int, Literal["pts", "best_effort_timestamp"]]] = []
            kind: Literal["pts", "best_effort_timestamp"] | None = None
            previous: int | None = None
            for ordinal, frame in enumerate(raw_frames):
                this_kind: Literal["pts", "best_effort_timestamp"]
                frame_width = int(frame.get("width", width))
                frame_height = int(frame.get("height", height))
                if frame_width != width or frame_height != height:
                    raise ValueError(f"frame {ordinal} dimensions vary within stream")
                if frame.get("pts") not in (None, "N/A"):
                    pts, this_kind = int(frame["pts"]), "pts"
                elif frame.get("best_effort_timestamp") not in (None, "N/A"):
                    pts, this_kind = int(frame["best_effort_timestamp"]), "best_effort_timestamp"
                else:
                    raise ValueError(f"frame {ordinal} has no observed source timestamp")
                if kind is not None and kind != this_kind:
                    raise ValueError("timestamp provenance changes within stream")
                if previous is not None and pts <= previous:
                    raise ValueError(f"frame {ordinal} has duplicate or nonmonotonic source PTS")
                timestamps.append((pts, this_kind))
                kind, previous = this_kind, pts
            if not timestamps or kind is None:
                raise ValueError("ffprobe returned no video frames")
            reported_count = stream.get("nb_frames")
            if reported_count not in (None, "N/A") and int(reported_count) != len(timestamps):
                raise ValueError("stream frame count disagrees with frame inventory")
            stream_duration = stream.get("duration")
            container_duration = data.get("format", {}).get("duration")
            metadata = SourceVideoMetadata(
                source_path=str(self.source_path),
                width=width,
                height=height,
                time_base_numerator=time_base.numerator,
                time_base_denominator=time_base.denominator,
                fps_numerator=rate.numerator,
                fps_denominator=rate.denominator,
                stream_duration_seconds=stream_duration,
                container_duration_seconds=container_duration,
                frame_count=len(timestamps),
                timestamp_kind=kind,
                ffprobe_version=self._ffprobe_version,
                ffmpeg_version=self._ffmpeg_version,
                file_size=self._fingerprint[2],
                file_mtime_ns=self._fingerprint[3],
            )
            return metadata, timestamps
        except (KeyError, ValueError, TypeError, ZeroDivisionError) as exc:
            raise RuntimeError(f"Invalid ffprobe video inventory: {exc}") from exc

    def _start(self) -> None:
        if self._process is None:
            self._check_source_unchanged()
            self._process = subprocess.Popen(
                [
                    self._ffmpeg,
                    "-v",
                    "error",
                    "-nostdin",
                    "-noautorotate",
                    "-threads",
                    str(DECODER_THREADS),
                    "-i",
                    str(self.source_path),
                    "-map",
                    "0:v:0",
                    "-an",
                    "-sn",
                    "-dn",
                    "-fps_mode",
                    "passthrough",
                    "-pix_fmt",
                    "bgr24",
                    "-f",
                    "rawvideo",
                    "pipe:1",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            assert self._process.stderr is not None
            self._stderr_thread = threading.Thread(
                target=self._drain_stderr, args=(self._process.stderr,), daemon=True
            )
            self._stderr_thread.start()

    def __iter__(self) -> Iterator[SourceVideoFrame]:
        return self

    def __next__(self) -> SourceVideoFrame:
        if self._closed:
            raise StopIteration
        try:
            return self._read_next_frame()
        except StopIteration:
            raise
        except BaseException:
            try:
                self.close()
            except BaseException:
                # Preserve the decoder/validation failure that initiated cleanup.
                pass
            raise

    def _read_next_frame(self) -> SourceVideoFrame:
        if self._next_index >= self.metadata.frame_count:
            self._verify_end()
            raise StopIteration
        self._start()
        assert self._process is not None and self._process.stdout is not None
        frame_bytes = self.metadata.width * self.metadata.height * 3
        payload = bytearray()
        while len(payload) < frame_bytes:
            chunk = self._process.stdout.read(frame_bytes - len(payload))
            if not chunk:
                self._fail(f"ffmpeg ended early at frame {self._next_index}")
            payload.extend(chunk)
        index = self._next_index
        pts, kind = self._timestamps[index]
        frame = np.frombuffer(payload, dtype=np.uint8).reshape(
            self.metadata.height, self.metadata.width, 3
        )
        item = SourceVideoFrame(
            frame_index=index,
            source_pts=pts,
            time_base_numerator=self.metadata.time_base_numerator,
            time_base_denominator=self.metadata.time_base_denominator,
            timestamp_seconds=Fraction(
                pts * self.metadata.time_base_numerator, self.metadata.time_base_denominator
            ),
            timestamp_kind=kind,
            bgr=frame,
        )
        item.validate_against(self.metadata)
        self._next_index += 1
        if self._next_index == self.metadata.frame_count:
            self._verify_end()
        return item

    def _drain_stderr(self, stream: BinaryIO) -> None:
        while True:
            chunk = stream.read(1024)
            if not chunk:
                return
            with self._stderr_lock:
                self._stderr_tail.extend(chunk)
                del self._stderr_tail[:-4000]

    def _verify_end(self) -> None:
        if self.complete_stream_verified:
            return
        self._start()
        assert self._process is not None and self._process.stdout is not None
        extra = self._process.stdout.read(1)
        if extra:
            self._fail("ffmpeg decoded more frames than ffprobe inventory")
        status = self._process.wait()
        if status:
            self._fail(f"ffmpeg failed ({status})")
        self._check_source_unchanged()
        self.complete_stream_verified = True
        self._close_handles()

    def _fail(self, message: str) -> None:
        self.close()
        with self._stderr_lock:
            stderr = bytes(self._stderr_tail).decode(errors="replace")
        raise RuntimeError(f"{message}; ffmpeg stderr: {stderr}")

    def _close_handles(self) -> None:
        if self._process is not None and self._process.stdout is not None:
            self._process.stdout.close()
        if self._stderr_thread is not None:
            self._stderr_thread.join()
        if self._process is not None and self._process.stderr is not None:
            self._process.stderr.close()
        self._closed = True

    def close(self) -> None:
        """Stop decoding, releasing processes without certifying completion."""
        if self._closed:
            return
        if self._process is not None:
            if self._process.poll() is None:
                self._process.terminate()
                try:
                    self._process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait()
            if self._process.stdout is not None:
                self._process.stdout.close()
        if self._stderr_thread is not None:
            self._stderr_thread.join()
        if self._process is not None and self._process.stderr is not None:
            self._process.stderr.close()
        self._closed = True

    def __enter__(self) -> SequentialPtsVideoSource:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()
