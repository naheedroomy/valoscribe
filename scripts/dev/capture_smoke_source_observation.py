#!/usr/bin/env python3
"""Hash reviewed source crops and write local, annotated debug images."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2

from valoscribe.analytics.smoke_source_observation import decoded_crop_sha256
from valoscribe.types.smoke_source_observation import SmokeSourceObservation


def capture(video_path: Path, manifest_path: Path, debug_dir: Path) -> None:
    observation = SmokeSourceObservation.model_validate_json(manifest_path.read_text())
    capture_handle = cv2.VideoCapture(str(video_path))
    if not capture_handle.isOpened():
        raise ValueError(f"cannot open source video: {video_path}")
    try:
        if video_path.name != observation.source_filename:
            raise ValueError(
                f"source filename {video_path.name!r} does not match manifest "
                f"{observation.source_filename!r}"
            )
        width = int(capture_handle.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture_handle.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if (width, height) != (observation.source_frame_width, observation.source_frame_height):
            raise ValueError(
                f"source video dimensions {(width, height)} do not match manifest "
                f"{(observation.source_frame_width, observation.source_frame_height)}"
            )

        debug_dir.mkdir(parents=True, exist_ok=True)
        samples = []
        for sample in observation.samples:
            capture_handle.set(cv2.CAP_PROP_POS_FRAMES, sample.frame_index)
            ok, frame = capture_handle.read()
            if not ok or frame.shape[:2] != (height, width):
                raise ValueError(f"could not decode expected frame {sample.frame_index}")
            digest = decoded_crop_sha256(frame, observation.crop)
            samples.append(sample.model_copy(update={"decoded_crop_sha256": digest}))
            crop = frame[
                observation.crop.y : observation.crop.y + observation.crop.height,
                observation.crop.x : observation.crop.x + observation.crop.width,
            ].copy()
            color = {
                "present": (0, 220, 0),
                "absent": (0, 0, 255),
                "unsettled": (0, 190, 255),
            }[sample.kind.value]
            cv2.putText(
                crop,
                f"{sample.timestamp_s:g}s frame {sample.frame_index}: {sample.kind.value}",
                (5, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.42, color, 1, cv2.LINE_AA,
            )
            if sample.kind.value == "present":
                cv2.drawMarker(
                    crop, observation.center_source_crop_px, (255, 0, 255),
                    cv2.MARKER_CROSS, 12, 1, cv2.LINE_AA,
                )
                cv2.putText(
                    crop, "approx. reviewer center; uncertainty ±3 source px", (5, 36),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.34, (255, 0, 255), 1, cv2.LINE_AA,
                )
            output = debug_dir / f"frame-{sample.frame_index}-{sample.kind.value}.png"
            if not cv2.imwrite(str(output), crop):
                raise ValueError(f"could not write debug overlay: {output}")
    finally:
        capture_handle.release()

    updated = observation.model_copy(update={"samples": samples})
    manifest_path.write_text(json.dumps(updated.model_dump(mode="json"), indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True, help="local authorized source VOD")
    parser.add_argument(
        "--manifest", type=Path,
        default=Path("docs/smoke_source_observation_vta502.json"),
    )
    parser.add_argument(
        "--debug-dir", type=Path,
        default=Path("/tmp/valoscribe-vta502-source-space"),
    )
    args = parser.parse_args()
    capture(args.video, args.manifest, args.debug_dir)


if __name__ == "__main__":
    main()
