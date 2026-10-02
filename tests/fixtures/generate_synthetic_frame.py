"""Generate a small deterministic synthetic frame for image-pipeline tests.

All coordinates and colors are synthetic test geometry, not production HUD or map data.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import cv2
import numpy as np

WIDTH = 320
HEIGHT = 180
ANCHORS = {
    "anchor_red": {"center_px": [48, 42], "center_normalized": [0.15, 0.233333]},
    "anchor_green": {"center_px": [160, 90], "center_normalized": [0.5, 0.5]},
    "anchor_blue": {"center_px": [272, 138], "center_normalized": [0.85, 0.766667]},
}
COLORS_BGR = {
    "anchor_red": [0, 0, 255],
    "anchor_green": [0, 255, 0],
    "anchor_blue": [255, 0, 0],
}


def generate_synthetic_frame(output_dir: Path) -> tuple[Path, Path]:
    """Create a synthetic PNG frame and its semantic metadata in ``output_dir``."""
    output_dir.mkdir(parents=True, exist_ok=True)
    frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    for name, anchor in ANCHORS.items():
        center = cast(list[int], anchor["center_px"])
        x, y = center
        cv2.rectangle(frame, (x - 5, y - 5), (x + 5, y + 5), COLORS_BGR[name], -1)

    frame_path = output_dir / "synthetic_anchor_frame.png"
    metadata_path = output_dir / "synthetic_anchor_frame.json"
    if not cv2.imwrite(str(frame_path), frame):
        raise OSError(f"could not write synthetic frame: {frame_path}")

    metadata = {
        "fixture_id": "synthetic-anchor-frame-v1",
        "width": WIDTH,
        "height": HEIGHT,
        "color_order": "BGR",
        "anchors": ANCHORS,
    }
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return frame_path, metadata_path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    generate_synthetic_frame(args.output_dir)
