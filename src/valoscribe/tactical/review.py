"""Local OpenCV reviewer and its headless interaction controller."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from valoscribe.tactical.config import TacticalConfig
from valoscribe.tactical.contracts import CorrectionDelta, ReviewedFrame
from valoscribe.tactical.corrections import (
    _append_records,
    _point_to_canonical,
    _read_jsonl,
    observation_id,
    validate_delta,
)
from valoscribe.tactical.pipeline import _crop, resolve_path


class ReviewController:
    """Keep cursor, selection, and staged deltas independent of the GUI."""

    def __init__(self, sample_indices: list[int]) -> None:
        self.sample_indices = sample_indices
        self.position = 0
        self.selected_id: str | None = None
        self.staged: list[dict[str, Any]] = []
        self.dirty = False

    @property
    def sample_index(self) -> int:
        return self.sample_indices[self.position]

    def move(self, step: int) -> None:
        self.position = min(max(0, self.position + step), len(self.sample_indices) - 1)
        self.selected_id = None

    def select(self, observation_key: str | None) -> None:
        self.selected_id = observation_key

    def stage(self, delta: dict[str, Any]) -> None:
        self.staged.append(delta)
        self.dirty = True

    def saved(self) -> None:
        self.staged.clear()
        self.dirty = False


def review_round(
    run_dir: Path, round_id: str, config: TacticalConfig, reviewer: str = "local-reviewer"
) -> None:
    round_dir = run_dir / "rounds" / round_id
    if not round_dir.is_dir():
        raise ValueError(f"round directory does not exist: {round_id}")
    raw_path = round_dir / "raw_observations.jsonl"
    raw = _read_jsonl(raw_path)
    coverage = _read_jsonl(round_dir / "sample_coverage.jsonl")
    if not coverage:
        raise ValueError(f"sample frame evidence is missing for {round_id}")
    round_raw = [(ordinal, row) for ordinal, row in enumerate(raw) if row["round_id"] == round_id]
    frames = {int(row["sample_index"]): row for row in coverage}
    by_sample: dict[int, list[tuple[str, dict]]] = {sample: [] for sample in frames}
    for ordinal, row in round_raw:
        by_sample.setdefault(int(row["sample_index"]), []).append(
            (observation_id(round_id, int(row["sample_index"]), ordinal), row)
        )
    existing_deltas = _read_jsonl(round_dir / "corrections.jsonl")
    for delta in existing_deltas:
        if delta.get("round_id") != round_id:
            continue
        if delta["operation"] in {"remove", "move"}:
            by_sample[int(delta["sample_index"])] = [
                entry
                for entry in by_sample.get(int(delta["sample_index"]), [])
                if entry[0] != delta["target_observation_id"]
            ]
        if delta["operation"] in {"add", "move"}:
            by_sample.setdefault(int(delta["sample_index"]), []).append(
                (
                    delta["correction_id"],
                    {
                        "canonical_x": delta["corrected_canonical_x"],
                        "canonical_y": delta["corrected_canonical_y"],
                        "confidence": delta["confidence"],
                        "source": "corrected",
                    },
                )
            )
    indices = sorted(frames)
    if not indices:
        raise ValueError(f"no sample frames available for {round_id}")
    controller = ReviewController(indices)
    source = resolve_path(config.source.video_path)
    cap = cv2.VideoCapture(str(source))
    if not cap.isOpened():
        raise ValueError(f"source video cannot be opened: {source}")
    crop_cfg = config.broadcast.minimap_crop
    matrix = np.asarray(config.broadcast.transform.matrix, dtype=np.float64)
    selected: str | None = None
    window = f"Tactical review: {round_id}"

    def save() -> None:
        sample = controller.sample_index
        deltas: list[CorrectionDelta] = []
        validation_history = list(existing_deltas)
        for item in controller.staged:
            values = dict(item)
            values.update(
                correction_id=uuid.uuid4().hex,
                run_id=config.run.run_id,
                round_id=round_id,
                sample_index=sample,
                reviewer=reviewer,
            )
            delta = CorrectionDelta.model_validate(values)
            validate_delta(delta, raw, config, validation_history)
            deltas.append(delta)
            validation_history.append(delta.model_dump(mode="json"))
        _append_records(round_dir / "corrections.jsonl", deltas)
        _append_records(
            round_dir / "reviewed_frames.jsonl",
            [
                ReviewedFrame(
                    run_id=config.run.run_id,
                    round_id=round_id,
                    sample_index=sample,
                    reviewer=reviewer,
                    note="Frame reviewed in local reviewer",
                )
            ],
        )
        controller.saved()

    def mouse(event: int, x: int, y: int, flags: int, param: object) -> None:
        nonlocal selected
        if event != cv2.EVENT_LBUTTONDOWN:
            return
        sample = controller.sample_index
        if frames[sample]["coverage_status"] == "excluded":
            return
        close = min(
            (
                (float(np.hypot(px - x, py - y)), key)
                for key, px, py, _confidence in _display_points(by_sample.get(sample, []), matrix)
            ),
            default=(float("inf"), ""),
        )
        if close[0] <= 12:
            selected = close[1]
            controller.select(selected)
            return
        if 0 <= x < crop_cfg.width and 0 <= y < crop_cfg.height:
            canonical_x, canonical_y = _point_to_canonical(config, float(x), float(y))
            controller.stage(
                {
                    "operation": "add",
                    "corrected_canonical_x": canonical_x,
                    "corrected_canonical_y": canonical_y,
                    "note": "Added in reviewer",
                }
            )
            by_sample[sample] = _apply_staged(
                by_sample.get(sample, []),
                [
                    CorrectionDelta(
                        correction_id=f"staged-{len(controller.staged)}",
                        run_id=config.run.run_id,
                        round_id=round_id,
                        sample_index=sample,
                        operation="add",
                        corrected_canonical_x=canonical_x,
                        corrected_canonical_y=canonical_y,
                        reviewer=reviewer,
                    )
                ],
            )

    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(window, mouse)
    try:
        while True:
            sample = controller.sample_index
            frame_data = frames[sample]
            cap.set(cv2.CAP_PROP_POS_MSEC, float(frame_data["source_timestamp_seconds"]) * 1000)
            ok, image = cap.read()
            if not ok or image is None:
                raise ValueError(f"cannot decode reviewer frame {sample}")
            crop = _crop(image, config)
            if crop is None:
                raise ValueError("configured crop is outside source frame")
            for key, px, py, confidence in _display_points(by_sample.get(sample, []), matrix):
                color = (0, 0, 255) if key == selected else (0, 255, 0)
                cv2.circle(crop, (round(px), round(py)), 8, color, 2)
                cv2.putText(
                    crop,
                    f"{key[-6:]} {confidence:.2f}",
                    (round(px) + 6, round(py)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.3,
                    (255, 255, 255),
                    1,
                )
            marker = " * UNSAVED" if controller.dirty else ""
            cv2.putText(
                crop,
                (
                    f"{round_id} sample {sample} "
                    f"t={frame_data['source_timestamp_seconds']:.2f}s "
                    f"coverage={frame_data['coverage_status']}{marker}"
                ),
                (4, 16),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.4,
                (255, 255, 255),
                1,
            )
            cv2.putText(
                crop,
                "Left/Right or A/D: frame | click add/select | Del remove | S save | Q quit",
                (4, crop.shape[0] - 8),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.34,
                (255, 255, 255),
                1,
            )
            cv2.imshow(window, crop)
            keypress = cv2.waitKey(0) & 0xFF
            if keypress in (ord("q"), 27):
                break
            if keypress in (ord("d"), 83):
                controller.move(1)
                selected = None
            elif keypress in (ord("a"), 81):
                controller.move(-1)
                selected = None
            elif keypress in (ord("s"),):
                save()
            elif keypress in (8, 127, 46) and selected:
                target = next(
                    (row for key, row in by_sample.get(sample, []) if key == selected), None
                )
                if target is None or target.get("canonical_x") is None:
                    continue
                controller.stage(
                    {
                        "operation": "remove",
                        "target_observation_id": selected,
                        "original_canonical_x": target["canonical_x"],
                        "original_canonical_y": target["canonical_y"],
                        "note": "Removed in reviewer",
                    }
                )
                by_sample[sample] = [
                    entry for entry in by_sample.get(sample, []) if entry[0] != selected
                ]
                selected = None
    finally:
        cap.release()
        cv2.destroyWindow(window)


def _apply_staged(
    rows: list[tuple[str, dict]], deltas: list[CorrectionDelta]
) -> list[tuple[str, dict]]:
    result = list(rows)
    for delta in deltas:
        if delta.operation in {"remove", "move"}:
            result = [entry for entry in result if entry[0] != delta.target_observation_id]
        if delta.operation in {"add", "move"}:
            result.append(
                (
                    delta.correction_id,
                    {
                        "canonical_x": delta.corrected_canonical_x,
                        "canonical_y": delta.corrected_canonical_y,
                        "confidence": delta.confidence,
                        "source": "corrected",
                    },
                )
            )
    return result


def _display_points(
    rows: list[tuple[str, dict]], matrix: np.ndarray
) -> list[tuple[str, float, float, float]]:
    inverse = cv2.invertAffineTransform(matrix)
    result = []
    for key, row in rows:
        x, y = row.get("canonical_x"), row.get("canonical_y")
        if x is None or y is None:
            continue
        point = inverse @ np.array([float(x), float(y), 1.0])
        result.append((key, float(point[0]), float(point[1]), float(row.get("confidence", 1.0))))
    return result
