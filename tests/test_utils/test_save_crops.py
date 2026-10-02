"""Regression coverage for saving crops when a HUD region is absent."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
from typer.testing import CliRunner

from valoscribe.commands import utils


def test_crop_save_skips_empty_minimap_and_saves_other_hud_regions(
    tmp_path: Path, monkeypatch
) -> None:
    video_path = tmp_path / "synthetic.mp4"
    video_path.touch()
    frame = np.zeros((20, 4, 3), dtype=np.uint8)

    class FakeReader:
        width = 4
        height = 20
        fps = 1.0
        duration_sec = 1.0

        def __enter__(self):
            return self

        def __iter__(self):
            return iter([SimpleNamespace(frame_number=1, timestamp_sec=0.0, frame=frame)])

        def __exit__(self, *_args):
            return None

    class FakeCropper:
        config = {"name": "synthetic-profile"}
        regions = {
            "player_info": {"x": 0, "y": 0, "width": 1, "individual_height": 1, "offset": 0},
            "player_info_preround": {
                "x": 0,
                "y": 0,
                "width": 1,
                "individual_height": 1,
                "offset": 0,
            },
        }

        def crop_all_regions(self, _frame):
            crops = {name: np.ones((1, 1, 3), dtype=np.uint8) for name in (
                "round_number", "team1_score", "team2_score", "round_timer"
            )}
            crops.update(minimap=np.empty((0, 0, 3), dtype=np.uint8), killfeed=[], player_info=[])
            return crops

        def crop_player_info_preround(self, _frame):
            return []

    saved_names: list[str] = []

    def fake_imwrite(filename: str, crop: np.ndarray) -> bool:
        if crop.size == 0:
            raise ValueError("cannot save an empty crop")
        saved_names.append(Path(filename).name)
        return True

    monkeypatch.setattr(utils, "VideoReader", lambda *_args, **_kwargs: FakeReader())
    monkeypatch.setattr(utils, "Cropper", lambda **_kwargs: FakeCropper())
    monkeypatch.setattr(utils.cv2, "imwrite", fake_imwrite)
    monkeypatch.setattr(utils.cv2, "imshow", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(utils.cv2, "waitKey", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(utils.cv2, "destroyAllWindows", lambda: None)

    result = CliRunner().invoke(
        utils.app, ["crop", str(video_path), "--save-crops", str(tmp_path / "crops")]
    )

    assert result.exit_code == 0, result.output
    assert {"round_number.jpg", "team1_score.jpg", "team2_score.jpg", "round_timer.jpg"} <= set(
        saved_names
    )
    assert "minimap.jpg" not in saved_names
