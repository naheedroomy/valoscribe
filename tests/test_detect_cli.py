from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from valoscribe.commands import detect
from valoscribe.types.detections import KillfeedAgentDetection


class _FakeVideoReader:
    width = 1920
    height = 1080
    fps = 30.0
    duration_sec = 1.0

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    def __enter__(self) -> _FakeVideoReader:
        return self

    def __exit__(self, *_args: object) -> None:
        pass

    def __iter__(self):
        yield SimpleNamespace(
            frame=object(),
            timestamp_sec=1.0,
        )


class _FakeCropper:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.config = {"name": "test"}


class _FakeKillfeedDetector:
    templates = {"jett": object()}

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    def detect(self, _frame: object) -> list[tuple[int, KillfeedAgentDetection]]:
        return [
            (
                4,
                KillfeedAgentDetection(
                    killer_agent="jett",
                    killer_side="attack",
                    victim_agent="sova",
                    victim_side="defense",
                    confidence=0.97,
                ),
            )
        ]


def test_killfeed_cli_reports_actual_entry_index_for_tuple_detection(
    tmp_path: Path, monkeypatch
) -> None:
    video_path = tmp_path / "match.mp4"
    video_path.touch()

    monkeypatch.setattr(detect, "setup_logging", lambda: None)
    monkeypatch.setattr(detect, "Cropper", _FakeCropper)
    monkeypatch.setattr(detect, "KillfeedDetector", _FakeKillfeedDetector)
    monkeypatch.setattr(detect, "VideoReader", _FakeVideoReader)

    result = CliRunner().invoke(detect.app, ["killfeed", str(video_path)])

    assert result.exit_code == 0, result.output
    assert "Entry 4:" in result.output
    assert "jett killed" in result.output
    assert "Total kills detected: 1" in result.output
