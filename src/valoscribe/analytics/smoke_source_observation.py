"""Local-only hashing helpers for reviewed source-space smoke evidence."""

from __future__ import annotations

import hashlib

import numpy as np
from numpy.typing import NDArray

from valoscribe.types.smoke_source_observation import SmokeSourceCrop

Image = NDArray[np.uint8]


def decoded_crop_sha256(frame: Image, crop: SmokeSourceCrop) -> str:
    """Hash contiguous decoded BGR crop bytes, rejecting incompatible source frames."""
    if frame.ndim != 3 or frame.shape[2] != 3 or frame.dtype != np.uint8:
        raise ValueError("source frame must be an 8-bit, three-channel BGR image")
    height, width = frame.shape[:2]
    if crop.x + crop.width > width or crop.y + crop.height > height:
        raise ValueError("source crop exceeds decoded frame dimensions")
    pixels = np.ascontiguousarray(
        frame[crop.y : crop.y + crop.height, crop.x : crop.x + crop.width]
    )
    return hashlib.sha256(pixels.tobytes()).hexdigest()
