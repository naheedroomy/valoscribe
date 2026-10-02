"""Hash and validate reviewed player-identity source-frame evidence."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from valoscribe.types.player_identity_observation import (
    PlayerIdentityCrop,
    PlayerIdentityObservation,
)

Image = NDArray[np.uint8]


def _validated_frame(frame: NDArray[Any]) -> Image:
    if frame.ndim != 3 or frame.shape[2] != 3 or frame.dtype != np.uint8:
        raise ValueError("source frame must be an 8-bit, three-channel BGR image")
    return np.ascontiguousarray(frame)


def decoded_frame_sha256(frame: NDArray[Any]) -> str:
    """Hash the exact decoded BGR frame bytes, without image re-encoding."""
    return hashlib.sha256(_validated_frame(frame).tobytes()).hexdigest()


def decoded_identity_crop_sha256(frame: NDArray[Any], crop: PlayerIdentityCrop) -> str:
    """Hash the exact decoded BGR bytes inside the configured source crop."""
    frame = _validated_frame(frame)
    height, width = frame.shape[:2]
    if crop.x + crop.width > width or crop.y + crop.height > height:
        raise ValueError("identity crop exceeds decoded frame dimensions")
    pixels = frame[crop.y : crop.y + crop.height, crop.x : crop.x + crop.width]
    return hashlib.sha256(np.ascontiguousarray(pixels).tobytes()).hexdigest()


def verify_identity_observation(video_path: Path, observation: PlayerIdentityObservation) -> None:
    """Re-decode and verify every manifest hash; raise on any mismatch."""
    import cv2

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise ValueError(f"cannot open source video: {video_path}")
    try:
        if video_path.name != observation.source_filename:
            raise ValueError("source video filename does not match identity observation")
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = capture.get(cv2.CAP_PROP_FPS)
        if (width, height) != (observation.source_frame_width, observation.source_frame_height):
            raise ValueError("source video dimensions do not match identity observation")
        if not np.isfinite(fps) or abs(fps - observation.nominal_fps) > 0.01:
            raise ValueError("source video frame rate does not match identity observation")

        capture.set(cv2.CAP_PROP_POS_FRAMES, observation.samples[0].frame_index)
        next_frame_index = observation.samples[0].frame_index
        for sample in observation.samples:
            while next_frame_index <= sample.frame_index:
                ok, frame = capture.read()
                if not ok or frame.shape[:2] != (height, width):
                    raise ValueError(f"could not decode expected frame {next_frame_index}")
                if next_frame_index == sample.frame_index:
                    frame_array = np.asarray(frame)
                    frame_hash = decoded_frame_sha256(frame_array)
                    crop_hash = decoded_identity_crop_sha256(frame_array, observation.crop)
                    if frame_hash != sample.decoded_frame_sha256:
                        raise ValueError(
                            f"decoded frame hash mismatch at frame {sample.frame_index}"
                        )
                    if crop_hash != sample.decoded_crop_sha256:
                        raise ValueError(
                            f"decoded crop hash mismatch at frame {sample.frame_index}"
                        )
                next_frame_index += 1
    finally:
        capture.release()
