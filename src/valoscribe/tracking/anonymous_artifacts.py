"""Immutable, manifest-bound artifacts for diagnostic anonymous round runs."""

from __future__ import annotations

import hashlib
import json
from importlib import import_module
from pathlib import Path
from typing import Any, Mapping

from pydantic import ValidationError

from valoscribe.tracking.provenance import (
    manifest_sha256,
    read_bound_artifact,
    validate_observation,
    write_bound_artifact,
    write_tracking_manifest,
)
from valoscribe.types.anonymous_tracking import (
    AnonymousRawFrameObservation,
    AnonymousRunManifest,
    AnonymousTrackSample,
)
from valoscribe.types.persistent import RawMinimapColorCandidate
from valoscribe.types.tracking_provenance import TrackingRunManifest


class AnonymousParquetUnavailableError(RuntimeError):
    """Raised when the optional Arrow runtime required by derived output is absent."""


def _arrow() -> tuple[Any, Any]:
    try:
        return import_module("pyarrow"), import_module("pyarrow.parquet")
    except ImportError as error:
        raise AnonymousParquetUnavailableError(
            "Anonymous round certification requires Parquet support; install "
            "valoscribe[parquet] (pyarrow). No runner output was written."
        ) from error


def anonymous_run_manifest_sha256(wrapper: AnonymousRunManifest) -> str:
    """Digest the exact serialized diagnostic wrapper payload referenced by every row."""
    return hashlib.sha256(_canonical(wrapper)).hexdigest()


def anonymous_tracklet_schema(pa: Any) -> Any:
    """Return the versioned tracklet schema, including when there are no samples."""
    return pa.schema(
        [
            pa.field("schema_version", pa.string(), nullable=False),
            pa.field("manifest_sha256", pa.string(), nullable=False),
            pa.field("runner_manifest_sha256", pa.string(), nullable=False),
            pa.field("frame_index", pa.int64(), nullable=False),
            pa.field("source_pts", pa.int64(), nullable=False),
            pa.field("timebase_numerator", pa.int64(), nullable=False),
            pa.field("timebase_denominator", pa.int64(), nullable=False),
            pa.field("timestamp_s", pa.float64(), nullable=False),
            pa.field("tracklet_id", pa.string(), nullable=False),
            pa.field("candidate_id", pa.string(), nullable=False),
            pa.field("broadcast_color", pa.string(), nullable=False),
            pa.field("crop_x_normalized", pa.float64(), nullable=False),
            pa.field("crop_y_normalized", pa.float64(), nullable=False),
            pa.field("confidence", pa.float64(), nullable=False),
            pa.field("association_confidence", pa.float64(), nullable=False),
            pa.field("evidence_candidate_ids", pa.list_(pa.string()), nullable=False),
            pa.field("motion_distance_crop_fraction", pa.float64(), nullable=False),
            pa.field("observed", pa.bool_(), nullable=False),
            pa.field("inference_scope", pa.string(), nullable=False),
        ]
    )


def validate_anonymous_rows(
    wrapper: AnonymousRunManifest,
    raw_frames: list[AnonymousRawFrameObservation],
    samples: list[AnonymousTrackSample],
    debug_pngs: Mapping[str, bytes] | None = None,
    *,
    debug_png_hashes: Mapping[str, str] | None = None,
) -> None:
    """Bind all observations and tracklets to the wrapper and each other.

    This is deliberately shared by preflight and consumer readback; sidecar hashes
    alone establish byte integrity, not semantic consistency between rows.
    """
    try:
        checked_wrapper = AnonymousRunManifest.model_validate(wrapper.model_dump(mode="python"))
        checked_raw = [
            AnonymousRawFrameObservation.model_validate(row.model_dump(mode="python"))
            for row in raw_frames
        ]
        checked_samples = [
            AnonymousTrackSample.model_validate(row.model_dump(mode="python")) for row in samples
        ]
    except (ValidationError, AttributeError, TypeError) as error:
        raise ValueError("invalid anonymous wrapper or observation rows") from error

    manifest = checked_wrapper.tracking_manifest
    wrapper_digest = anonymous_run_manifest_sha256(checked_wrapper)
    candidate_by_id: dict[str, tuple[AnonymousRawFrameObservation, RawMinimapColorCandidate]] = {}
    context_by_frame: dict[int, AnonymousRawFrameObservation] = {}
    for raw_row in checked_raw:
        if raw_row.runner_manifest_sha256 != wrapper_digest:
            raise ValueError("raw frame wrapper digest mismatch")
        validate_observation(
            raw_row.provenance,
            manifest,
            expected_run_id=manifest.run_id,
            expected_source_sha256=manifest.source_video_sha256,
            expected_config_sha256=manifest.config_sha256,
        )
        if raw_row.context_evidence is not None and (
            raw_row.context_evidence.frame_index != raw_row.provenance.frame_index
            or raw_row.context_evidence.state != raw_row.context
        ):
            raise ValueError("raw frame context disagrees with reviewed context evidence")
        if raw_row.context_evidence is None and raw_row.context != "unknown":
            raise ValueError("known frame context is missing its reviewed evidence")
        if (
            raw_row.crop_x + raw_row.crop_width > manifest.source_width
            or raw_row.crop_y + raw_row.crop_height > manifest.source_height
        ):
            raise ValueError("raw frame crop exceeds source dimensions")
        if raw_row.provenance.frame_index in context_by_frame:
            raise ValueError("duplicate raw frame index")
        context_by_frame[raw_row.provenance.frame_index] = raw_row
        for item in raw_row.candidates:
            candidate = item.candidate
            if (
                candidate.source_frame != raw_row.provenance.frame_index
                or candidate.vod_timestamp_s != raw_row.provenance.timestamp_s
                or candidate.color_profile_id != manifest.color_config.config_id
                or candidate.source.value != "minimap"
            ):
                raise ValueError("raw candidate provenance disagrees with containing frame")
            if item.candidate_id in candidate_by_id:
                raise ValueError("duplicate raw candidate id")
            candidate_by_id[item.candidate_id] = (raw_row, candidate)

    if debug_pngs is not None and debug_png_hashes is not None:
        raise ValueError("supply debug PNG bytes or digests, not both")
    if debug_pngs is not None or debug_png_hashes is not None:
        expected_debug_paths = {
            f"debug/candidates_{row.provenance.frame_index:08d}.png": row
            for row in checked_raw
        }
        supplied_paths = debug_pngs if debug_pngs is not None else debug_png_hashes
        assert supplied_paths is not None
        if set(supplied_paths) != set(expected_debug_paths):
            raise ValueError("debug overlay paths do not match raw frame observations")
        for path, raw_row in expected_debug_paths.items():
            if debug_pngs is not None:
                payload_digest = hashlib.sha256(debug_pngs[path]).hexdigest()
            else:
                assert debug_png_hashes is not None
                payload_digest = debug_png_hashes[path]
            if payload_digest != raw_row.debug_png_sha256:
                raise ValueError("raw frame debug overlay digest mismatch")

    seen_sample_candidates: set[str] = set()
    sample_by_candidate: dict[str, AnonymousTrackSample] = {}
    for sample in checked_samples:
        if sample.manifest_sha256 != manifest_sha256(manifest):
            raise ValueError("tracklet shared manifest digest mismatch")
        if sample.runner_manifest_sha256 != wrapper_digest:
            raise ValueError("tracklet wrapper digest mismatch")
        sample_frame = context_by_frame.get(sample.frame_index)
        if sample_frame is None or sample_frame.context != "live":
            raise ValueError("tracklet references missing or non-live raw frame")
        if (
            sample.source_pts != sample_frame.provenance.source_pts
            or sample.timebase_numerator != sample_frame.provenance.timebase_numerator
            or sample.timebase_denominator != sample_frame.provenance.timebase_denominator
            or sample.timestamp_s != sample_frame.provenance.timestamp_s
        ):
            raise ValueError("tracklet timebase or timestamp disagrees with raw frame")
        candidate_entry = candidate_by_id.get(sample.candidate_id)
        if candidate_entry is None or candidate_entry[0] is not sample_frame:
            raise ValueError("tracklet candidate is missing from its raw frame")
        candidate = candidate_entry[1]
        if not candidate.accepted:
            raise ValueError("tracklet references a rejected raw candidate")
        if (
            sample.broadcast_color != candidate.broadcast_color
            or sample.crop_x_normalized != candidate.crop_point.x
            or sample.crop_y_normalized != candidate.crop_point.y
            or sample.confidence != candidate.detector_confidence
        ):
            raise ValueError("tracklet coordinates or confidence disagree with raw candidate")
        if sample.candidate_id in seen_sample_candidates:
            raise ValueError("raw candidate is referenced by multiple tracklet samples")
        seen_sample_candidates.add(sample.candidate_id)
        sample_by_candidate[sample.candidate_id] = sample

    samples_by_tracklet: dict[str, list[AnonymousTrackSample]] = {}
    for sample in checked_samples:
        samples_by_tracklet.setdefault(sample.tracklet_id, []).append(sample)
    for tracklet_samples in samples_by_tracklet.values():
        tracklet_samples.sort(key=lambda sample: sample.frame_index)
        previous: AnonymousTrackSample | None = None
        prior_frame = -1
        for sample in tracklet_samples:
            if sample.frame_index == prior_frame:
                raise ValueError("duplicate tracklet sample for frame")
            prior_frame = sample.frame_index
            evidence_ids = sample.evidence_candidate_ids
            if len(evidence_ids) not in {1, 2} or evidence_ids[-1] != sample.candidate_id:
                raise ValueError("tracklet evidence must be a start or immediate continuation")
            for evidence_id in evidence_ids:
                evidence = candidate_by_id.get(evidence_id)
                if evidence is None or not evidence[1].accepted:
                    raise ValueError("tracklet evidence references missing or rejected candidate")
                evidence_sample = sample_by_candidate.get(evidence_id)
                if evidence_sample is None or evidence_sample.tracklet_id != sample.tracklet_id:
                    raise ValueError("tracklet evidence candidate does not belong to its tracklet")
            if len(evidence_ids) == 1:
                if previous is not None:
                    raise ValueError(
                        "tracklet start follows an earlier sample in the same tracklet"
                    )
                if sample.motion_distance_crop_fraction != 0 or sample.association_confidence != 0:
                    raise ValueError("tracklet start cannot claim an association")
                previous = sample
                continue
            if previous is None:
                raise ValueError(
                    "tracklet continuation is not adjacent live evidence within time gate"
                )
            previous_id = evidence_ids[0]
            previous_raw = context_by_frame[previous.frame_index]
            current_candidate = candidate_by_id[sample.candidate_id][1]
            previous_candidate = candidate_by_id[previous_id][1]
            elapsed = sample.timestamp_s - previous.timestamp_s
            if (
                previous.candidate_id != previous_id
                or previous.frame_index != sample.frame_index - 1
                or previous_raw.context != "live"
                or elapsed <= 0
                or elapsed > checked_wrapper.max_gap_seconds
            ):
                raise ValueError(
                    "tracklet continuation is not adjacent live evidence within time gate"
                )
            if previous_candidate.broadcast_color != current_candidate.broadcast_color:
                raise ValueError("tracklet continuation broadcast color changed")
            distance = ((
                current_candidate.crop_point.x - previous_candidate.crop_point.x
            ) ** 2 + (
                current_candidate.crop_point.y - previous_candidate.crop_point.y
            ) ** 2) ** 0.5
            expected_confidence = max(
                0.0, min(1.0, 1.0 - distance / checked_wrapper.max_step_crop_fraction)
            )
            if (
                distance > checked_wrapper.max_step_crop_fraction
                or abs(sample.motion_distance_crop_fraction - distance) > 1e-9
                or abs(sample.association_confidence - expected_confidence) > 1e-9
            ):
                raise ValueError("tracklet association distance or confidence is inconsistent")
            previous = sample


def read_anonymous_rows(
    runs_root: Path, wrapper: AnonymousRunManifest
) -> tuple[list[AnonymousRawFrameObservation], list[AnonymousTrackSample]]:
    """Read integrity-bound rows and apply the same semantic checks used before writing."""
    _, parquet = _arrow()
    manifest = wrapper.tracking_manifest
    arguments = {
        "expected_run_id": manifest.run_id,
        "expected_source_sha256": manifest.source_video_sha256,
        "expected_config_sha256": manifest.config_sha256,
    }
    raw_payload = read_bound_artifact(
        runs_root,
        manifest,
        "raw_observations.jsonl",
        expected_artifact_kind="anonymous_raw_jsonl",
        **arguments,
    )
    try:
        raw_rows = [
            AnonymousRawFrameObservation.model_validate_json(line)
            for line in raw_payload.splitlines()
        ]
    except ValidationError as error:
        raise ValueError("invalid anonymous raw observation payload") from error
    debug_png_hashes: dict[str, str] = {}
    for row in raw_rows:
        debug_path = f"debug/candidates_{row.provenance.frame_index:08d}.png"
        debug_payload = read_bound_artifact(
            runs_root,
            manifest,
            debug_path,
            expected_run_id=manifest.run_id,
            expected_source_sha256=manifest.source_video_sha256,
            expected_config_sha256=manifest.config_sha256,
            expected_artifact_kind="anonymous_debug_png",
        )
        debug_png_hashes[debug_path] = hashlib.sha256(debug_payload).hexdigest()
    parquet_payload = read_bound_artifact(
        runs_root,
        manifest,
        "anonymous_tracklets.parquet",
        expected_artifact_kind="anonymous_tracklets_parquet",
        **arguments,
    )
    pa, _ = _arrow()
    table = parquet.read_table(pa.BufferReader(parquet_payload))
    if table.schema.remove_metadata() != anonymous_tracklet_schema(pa):
        raise ValueError("anonymous tracklet Parquet columns or types mismatch")
    metadata = table.schema.metadata or {}
    if metadata.get(b"valoscribe.schema") != b"anonymous_tracklets/1.0":
        raise ValueError("missing or unsupported anonymous_tracklets Parquet schema")
    wrapper_digest = anonymous_run_manifest_sha256(wrapper).encode()
    if metadata.get(b"valoscribe.wrapper_sha256") != wrapper_digest:
        raise ValueError("anonymous tracklet Parquet wrapper digest mismatch")
    try:
        samples = [AnonymousTrackSample.model_validate(row) for row in table.to_pylist()]
    except ValidationError as error:
        raise ValueError("invalid anonymous tracklet row") from error
    validate_anonymous_rows(
        wrapper, raw_rows, samples, debug_png_hashes=debug_png_hashes
    )
    return raw_rows, samples


def write_anonymous_run(
    *,
    runs_root: Path,
    wrapper: AnonymousRunManifest,
    raw_frames: list[AnonymousRawFrameObservation],
    samples: list[AnonymousTrackSample],
    debug_pngs: dict[str, bytes],
) -> dict[str, str]:
    """Write and read back all outputs without overwriting existing run data."""
    pa, parquet = _arrow()
    validate_anonymous_rows(wrapper, raw_frames, samples, debug_pngs)
    manifest = wrapper.tracking_manifest
    write_tracking_manifest(manifest, runs_root)
    run_dir = runs_root / manifest.run_id
    manifest_payload = _canonical(wrapper)
    _bound(runs_root, manifest, "anonymous_run.json", manifest_payload, "anonymous_run_manifest")

    raw_payload = b"".join(_canonical(row) for row in raw_frames)
    _bound(runs_root, manifest, "raw_observations.jsonl", raw_payload, "anonymous_raw_jsonl")

    table = pa.Table.from_pylist(
        [row.model_dump(mode="json") for row in samples], schema=anonymous_tracklet_schema(pa)
    )
    metadata = dict(table.schema.metadata or {})
    metadata[b"valoscribe.schema"] = b"anonymous_tracklets/1.0"
    metadata[b"valoscribe.wrapper_sha256"] = anonymous_run_manifest_sha256(wrapper).encode()
    table = table.replace_schema_metadata(metadata)
    sink = pa.BufferOutputStream()
    parquet.write_table(table, sink)
    _bound(
        runs_root,
        manifest,
        "anonymous_tracklets.parquet",
        sink.getvalue().to_pybytes(),
        "anonymous_tracklets_parquet",
    )

    for relative_path, payload in sorted(debug_pngs.items()):
        _bound(runs_root, manifest, relative_path, payload, "anonymous_debug_png")

    read_anonymous_rows(runs_root, wrapper)
    for relative_path in sorted(debug_pngs):
        read_bound_artifact(
            runs_root,
            manifest,
            relative_path,
            expected_run_id=manifest.run_id,
            expected_source_sha256=manifest.source_video_sha256,
            expected_config_sha256=manifest.config_sha256,
            expected_artifact_kind="anonymous_debug_png",
        )
    wrapper_readback = read_bound_artifact(
        runs_root,
        manifest,
        "anonymous_run.json",
        expected_run_id=manifest.run_id,
        expected_source_sha256=manifest.source_video_sha256,
        expected_config_sha256=manifest.config_sha256,
        expected_artifact_kind="anonymous_run_manifest",
    )
    read_wrapper = AnonymousRunManifest.model_validate_json(wrapper_readback)
    if anonymous_run_manifest_sha256(read_wrapper) != anonymous_run_manifest_sha256(wrapper):
        raise ValueError("anonymous run wrapper changed during readback")
    return {
        "run_dir": str(run_dir),
        "raw_observations": "raw_observations.jsonl",
        "tracklets": "anonymous_tracklets.parquet",
        "manifest": "anonymous_run.json",
    }


def _bound(root: Path, manifest: TrackingRunManifest, path: str, payload: bytes, kind: str) -> None:
    write_bound_artifact(
        root,
        manifest,
        path,
        payload,
        artifact_kind=kind,
        expected_run_id=manifest.run_id,
        expected_source_sha256=manifest.source_video_sha256,
        expected_config_sha256=manifest.config_sha256,
    )


def _canonical(value: Any) -> bytes:
    return (
        json.dumps(
            value.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )
