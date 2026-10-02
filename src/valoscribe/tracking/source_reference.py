"""Pinned source-reference, detector correspondence, and identity evaluation artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections import defaultdict
from fractions import Fraction
from pathlib import Path
from typing import Iterable, Literal

from pydantic import ValidationError

from valoscribe.types.source_reference import (
    FrozenSourceJoinArtifact,
    FrozenSourcePredictionArtifact,
    FrozenSourceReference,
    ReferenceCandidate,
    ReferenceCandidateJoin,
    SourceJoinProtocol,
    SourceJoinReview,
    SourcePlayerReferenceObservation,
    SourcePredictionOutput,
    SourcePredictionRunManifest,
    SourceReferenceManifest,
    SourceReferenceReport,
)


def _canonical(value: object) -> bytes:
    def detach(item: object) -> object:
        if hasattr(item, "model_dump"):
            return detach(item.model_dump(mode="json"))  # type: ignore[union-attr]
        if isinstance(item, dict):
            return {key: detach(child) for key, child in item.items()}
        if isinstance(item, (list, tuple)):
            return [detach(child) for child in item]
        return item

    try:
        return json.dumps(
            detach(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValueError("artifact is not canonical finite JSON") from error


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _artifact_digest(value: dict[str, object]) -> str:
    return _sha(_canonical(value))


def _validate_digest(value: str, name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def validate_source_reference(
    manifest: SourceReferenceManifest,
    observations: Iterable[SourcePlayerReferenceObservation],
) -> tuple[SourceReferenceManifest, list[SourcePlayerReferenceObservation]]:
    """Revalidate nested Pydantic values, source clocks, key collisions, and marker overlaps."""
    try:
        manifest = SourceReferenceManifest.model_validate(manifest.model_dump(mode="python"))
        rows = [
            SourcePlayerReferenceObservation.model_validate(row.model_dump(mode="python"))
            for row in observations
        ]
    except (ValidationError, AttributeError, TypeError) as error:
        raise ValueError("invalid source reference contract") from error
    frame_pts = {frame.frame_index: frame.source_pts for frame in manifest.frames}
    annotation_ids: set[str] = set()
    known_player_frame: set[tuple[int, str]] = set()
    by_frame: dict[int, list[SourcePlayerReferenceObservation]] = defaultdict(list)
    for row in rows:
        if row.annotation_id in annotation_ids:
            raise ValueError("duplicate source annotation key")
        annotation_ids.add(row.annotation_id)
        if (
            row.source_video_sha256 != manifest.source_video_sha256
            or row.match_id != manifest.match_id
            or row.map_id != manifest.map_id
            or row.round_id != manifest.round_id
            or frame_pts.get(row.frame_index) != row.source_pts
            or row.timebase_numerator != manifest.timebase_numerator
            or row.timebase_denominator != manifest.timebase_denominator
        ):
            raise ValueError("source annotation does not match source/frame/PTS/timebase")
        next_frame = row.frame_index + 1
        if next_frame not in frame_pts or frame_pts[next_frame] != row.interval_end_source_pts:
            raise ValueError("annotation interval must use next certified PTS boundary")
        if (
            row.frame_index not in manifest.live_frame_indices
            or next_frame not in manifest.live_frame_indices
        ):
            raise ValueError("annotation interval crosses non-live or unknown context")
        if row.expected_player_id is not None:
            identity_key = (row.frame_index, row.expected_player_id)
            if identity_key in known_player_frame:
                raise ValueError("aliased same player claims on the same frame")
            known_player_frame.add(identity_key)
        by_frame[row.frame_index].append(row)
    for same_frame in by_frame.values():
        for index, left in enumerate(same_frame):
            for right in same_frame[index + 1 :]:
                if _iou(left.bbox, right.bbox) < 0.9:
                    continue
                if left.expected_player_id and left.expected_player_id == right.expected_player_id:
                    raise ValueError("aliased same player claims on the same frame")
                if (
                    left.marker_collision_resolution == "none"
                    or right.marker_collision_resolution == "none"
                ):
                    raise ValueError(
                        "source-marker collision requires reviewed distinctness or "
                        "unresolved disposition"
                    )
                if (
                    left.marker_collision_resolution != right.marker_collision_resolution
                    and "unresolved"
                    not in {left.marker_collision_resolution, right.marker_collision_resolution}
                ):
                    raise ValueError("conflicting source-marker collision dispositions")
    return manifest, rows


def source_reference_digest(
    manifest: SourceReferenceManifest,
    observations: Iterable[SourcePlayerReferenceObservation],
) -> str:
    manifest, rows = validate_source_reference(manifest, observations)
    return _artifact_digest(
        {
            "manifest": manifest.model_dump(mode="json"),
            "observations": [row.model_dump(mode="json") for row in rows],
        }
    )


def _reference_payload(
    manifest: SourceReferenceManifest, observations: list[SourcePlayerReferenceObservation]
) -> dict[str, object]:
    return {
        "manifest": manifest.model_dump(mode="json"),
        "observations": [row.model_dump(mode="json") for row in observations],
    }


def freeze_source_reference(
    destination_dir: Path,
    manifest: SourceReferenceManifest,
    observations: Iterable[SourcePlayerReferenceObservation],
    *,
    expected_development_reference_digest: str,
) -> Path:
    """Atomically create a canonical immutable source reference through pinned directory FDs."""
    manifest, rows = validate_source_reference(manifest, observations)
    _validate_digest(expected_development_reference_digest, "development reference digest")
    if manifest.join_protocol.development_reference_digest != expected_development_reference_digest:
        raise ValueError("join protocol differs from externally pinned development reference")
    payload = _reference_payload(manifest, rows)
    envelope = {**payload, "digest": _artifact_digest(payload)}
    _write_artifact(Path(destination_dir), "source-reference.json", envelope)
    return Path(destination_dir) / "source-reference.json"


def read_frozen_source_reference(
    path: Path,
    *,
    expected_source_sha256: str,
    expected_reference_digest: str,
    expected_development_reference_digest: str,
) -> FrozenSourceReference:
    """Read canonical reference only when caller-pinned digest and source both match."""
    _validate_digest(expected_source_sha256, "expected source hash")
    _validate_digest(expected_reference_digest, "expected reference digest")
    _validate_digest(expected_development_reference_digest, "development reference digest")
    envelope = _read_artifact(Path(path))
    digest = envelope.pop("digest", None)
    if not isinstance(digest, str):
        raise ValueError("source reference digest is missing")
    if digest != expected_reference_digest:
        raise ValueError("source reference does not match externally pinned digest")
    if digest != _artifact_digest(envelope):
        raise ValueError("source reference digest mismatch")
    try:
        manifest = SourceReferenceManifest.model_validate(envelope["manifest"])
        observation_payload = envelope["observations"]
        if not isinstance(observation_payload, list):
            raise TypeError("source observations must be a list")
        rows = [SourcePlayerReferenceObservation.model_validate(row) for row in observation_payload]
    except (KeyError, TypeError, ValidationError) as error:
        raise ValueError("invalid frozen source reference") from error
    if manifest.source_video_sha256 != expected_source_sha256:
        raise ValueError("source reference source hash mismatch")
    if manifest.join_protocol.development_reference_digest != expected_development_reference_digest:
        raise ValueError("join protocol differs from externally pinned development reference")
    manifest, rows = validate_source_reference(manifest, rows)
    return FrozenSourceReference(manifest=manifest, observations=rows, digest=digest)


def validate_frozen_source_reference(
    reference: FrozenSourceReference,
    *,
    expected_reference_digest: str,
    expected_development_reference_digest: str,
) -> FrozenSourceReference:
    try:
        checked = FrozenSourceReference.model_validate(reference.model_dump(mode="python"))
        actual = source_reference_digest(checked.manifest, checked.observations)
    except (ValidationError, AttributeError, TypeError) as error:
        raise ValueError("invalid frozen source reference") from error
    if checked.digest != expected_reference_digest or actual != expected_reference_digest:
        raise ValueError("source reference does not match externally pinned digest")
    if (
        checked.manifest.join_protocol.development_reference_digest
        != expected_development_reference_digest
    ):
        raise ValueError("source join protocol does not match development reference pin")
    return checked


def raw_candidate_sha256(candidates: Iterable[ReferenceCandidate]) -> str:
    rows = [ReferenceCandidate.model_validate(row.model_dump()) for row in candidates]
    return _sha(_canonical(rows))


def join_protocol_sha256(protocol: SourceJoinProtocol) -> str:
    checked = SourceJoinProtocol.model_validate(protocol.model_dump(mode="python"))
    return _sha(_canonical(checked.model_dump(mode="json")))


def join_reference_candidates(
    reference: FrozenSourceReference,
    candidates: Iterable[ReferenceCandidate],
    *,
    expected_reference_digest: str,
    expected_development_reference_digest: str,
    expected_raw_candidate_digest: str,
    candidate_run_digest: str,
) -> list[ReferenceCandidateJoin]:
    """Deterministically replay exact-frame geometric join under the frozen protocol."""
    reference = validate_frozen_source_reference(
        reference,
        expected_reference_digest=expected_reference_digest,
        expected_development_reference_digest=expected_development_reference_digest,
    )
    _validate_digest(candidate_run_digest, "candidate run digest")
    candidate_rows = [ReferenceCandidate.model_validate(row.model_dump()) for row in candidates]
    actual_raw_digest = raw_candidate_sha256(candidate_rows)
    if actual_raw_digest != expected_raw_candidate_digest:
        raise ValueError("raw candidates do not match externally pinned raw digest")
    manifest = reference.manifest
    pts_by_frame = {frame.frame_index: frame.source_pts for frame in manifest.frames}
    if any(
        row.source_video_sha256 != manifest.source_video_sha256
        or pts_by_frame.get(row.frame_index) != row.source_pts
        or row.timebase_numerator != manifest.timebase_numerator
        or row.timebase_denominator != manifest.timebase_denominator
        for row in candidate_rows
    ):
        raise ValueError("raw candidate source/frame/PTS/timebase mismatch")
    keys = [(row.frame_index, row.candidate_id) for row in candidate_rows]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate raw candidate key")
    protocol = manifest.join_protocol
    protocol_digest = join_protocol_sha256(protocol)
    by_frame: dict[int, list[ReferenceCandidate]] = defaultdict(list)
    for candidate in candidate_rows:
        by_frame[candidate.frame_index].append(candidate)
    result: list[ReferenceCandidateJoin] = []
    for observation in reference.observations:
        scored = sorted(
            (
                (_iou(observation.bbox, candidate.bbox), candidate)
                for candidate in by_frame[observation.frame_index]
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        eligible = [item for item in scored if item[0] >= protocol.threshold_iou]
        if not eligible:
            result.append(
                _join_row(
                    reference,
                    observation,
                    candidate_run_digest,
                    actual_raw_digest,
                    protocol_digest,
                    "unmatched",
                )
            )
        elif len(eligible) > 1:
            result.append(
                _join_row(
                    reference,
                    observation,
                    candidate_run_digest,
                    actual_raw_digest,
                    protocol_digest,
                    "ambiguous",
                    geometric_overlap=eligible[0][0],
                )
            )
        else:
            score, candidate = eligible[0]
            result.append(
                _join_row(
                    reference,
                    observation,
                    candidate_run_digest,
                    actual_raw_digest,
                    protocol_digest,
                    "matched",
                    candidate_id=candidate.candidate_id,
                    geometric_overlap=score,
                )
            )
    claims: dict[tuple[int, str], list[int]] = defaultdict(list)
    for index, row in enumerate(result):
        if row.status == "matched" and row.candidate_id is not None:
            claims[(row.frame_index, row.candidate_id)].append(index)
    for indexes in claims.values():
        if len(indexes) < 2:
            continue
        for index in indexes:
            result[index] = result[index].model_copy(
                update={
                    "status": "ambiguous",
                    "candidate_id": None,
                }
            )
    return result


def _join_row(
    reference: FrozenSourceReference,
    observation: SourcePlayerReferenceObservation,
    candidate_run_digest: str,
    raw_digest: str,
    protocol_digest: str,
    status: Literal["matched", "unmatched", "ambiguous"],
    *,
    candidate_id: str | None = None,
    geometric_overlap: float | None = None,
) -> ReferenceCandidateJoin:
    return ReferenceCandidateJoin(
        annotation_id=observation.annotation_id,
        frame_index=observation.frame_index,
        source_video_sha256=reference.manifest.source_video_sha256,
        source_reference_digest=reference.digest,
        candidate_run_digest=candidate_run_digest,
        raw_candidate_digest=raw_digest,
        join_protocol_digest=protocol_digest,
        candidate_id=candidate_id,
        geometric_overlap=geometric_overlap,
        status=status,
    )


def freeze_source_join_artifact(
    destination: Path,
    reference: FrozenSourceReference,
    candidates: Iterable[ReferenceCandidate],
    joins: Iterable[ReferenceCandidateJoin],
    reviews: Iterable[SourceJoinReview],
    *,
    expected_reference_digest: str,
    expected_development_reference_digest: str,
    expected_raw_candidate_digest: str,
    candidate_run_digest: str,
) -> Path:
    """Freeze reviewed correspondence only after deterministic replay equals submitted joins."""
    reference = validate_frozen_source_reference(
        reference,
        expected_reference_digest=expected_reference_digest,
        expected_development_reference_digest=expected_development_reference_digest,
    )
    candidates = [ReferenceCandidate.model_validate(row.model_dump()) for row in candidates]
    actual = join_reference_candidates(
        reference,
        candidates,
        expected_reference_digest=expected_reference_digest,
        expected_development_reference_digest=expected_development_reference_digest,
        expected_raw_candidate_digest=expected_raw_candidate_digest,
        candidate_run_digest=candidate_run_digest,
    )
    checked_joins = [ReferenceCandidateJoin.model_validate(row.model_dump()) for row in joins]
    if checked_joins != actual:
        raise ValueError("submitted join does not replay against pinned raw candidates/protocol")
    checked_reviews = [SourceJoinReview.model_validate(row.model_dump()) for row in reviews]
    review_by_id = {review.annotation_id: review for review in checked_reviews}
    if len(review_by_id) != len(checked_reviews) or set(review_by_id) != {
        join.annotation_id for join in actual
    }:
        raise ValueError("join review records must cover each source annotation exactly once")
    for join in actual:
        review = review_by_id[join.annotation_id]
        if (review.disposition, review.candidate_id) != (join.status, join.candidate_id):
            raise ValueError("join review disposition disagrees with replayed geometry")
    payload: dict[str, object] = {
        "source_reference_digest": reference.digest,
        "source_video_sha256": reference.manifest.source_video_sha256,
        "candidate_run_digest": candidate_run_digest,
        "raw_candidate_digest": expected_raw_candidate_digest,
        "join_protocol_digest": join_protocol_sha256(reference.manifest.join_protocol),
        "joins": [join.model_dump(mode="json") for join in actual],
        "reviews": [review.model_dump(mode="json") for review in checked_reviews],
    }
    artifact = {**payload, "digest": _artifact_digest(payload)}
    _write_artifact(Path(destination).parent, Path(destination).name, artifact)
    return Path(destination)


def read_frozen_source_join_artifact(
    path: Path,
    *,
    expected_join_digest: str,
    expected_reference_digest: str,
    expected_raw_candidate_digest: str,
    expected_join_protocol_digest: str,
) -> FrozenSourceJoinArtifact:
    _validate_digest(expected_join_digest, "expected join digest")
    _validate_digest(expected_join_protocol_digest, "expected join protocol digest")
    envelope = _read_artifact(Path(path))
    digest = envelope.pop("digest", None)
    if digest != expected_join_digest or digest != _artifact_digest(envelope):
        raise ValueError("source join artifact does not match pinned digest")
    if (
        envelope.get("source_reference_digest") != expected_reference_digest
        or envelope.get("raw_candidate_digest") != expected_raw_candidate_digest
    ):
        raise ValueError("source join reference/raw candidate binding mismatch")
    if envelope.get("join_protocol_digest") != expected_join_protocol_digest:
        raise ValueError("source join artifact protocol differs from frozen reference protocol")
    try:
        return FrozenSourceJoinArtifact.model_validate({**envelope, "digest": digest})
    except (TypeError, ValidationError) as error:
        raise ValueError("invalid frozen source join artifact") from error


def validate_frozen_source_join_artifact(
    artifact: FrozenSourceJoinArtifact,
    reference: FrozenSourceReference,
    candidates: Iterable[ReferenceCandidate],
    *,
    expected_join_digest: str,
    expected_reference_digest: str,
    expected_development_reference_digest: str,
    expected_raw_candidate_digest: str,
) -> FrozenSourceJoinArtifact:
    artifact = FrozenSourceJoinArtifact.model_validate(artifact.model_dump(mode="python"))
    reference = validate_frozen_source_reference(
        reference,
        expected_reference_digest=expected_reference_digest,
        expected_development_reference_digest=expected_development_reference_digest,
    )
    payload = artifact.model_dump(mode="json")
    digest = payload.pop("digest")
    if digest != expected_join_digest or _artifact_digest(payload) != expected_join_digest:
        raise ValueError("source join artifact does not match pinned digest")
    protocol_digest = join_protocol_sha256(reference.manifest.join_protocol)
    if (
        artifact.source_reference_digest != expected_reference_digest
        or artifact.raw_candidate_digest != expected_raw_candidate_digest
        or artifact.source_video_sha256 != reference.manifest.source_video_sha256
    ):
        raise ValueError("source join artifact reference/raw/source mismatch")
    if artifact.join_protocol_digest != protocol_digest:
        raise ValueError("source join artifact protocol differs from frozen reference protocol")
    replayed = join_reference_candidates(
        reference,
        candidates,
        expected_reference_digest=expected_reference_digest,
        expected_development_reference_digest=expected_development_reference_digest,
        expected_raw_candidate_digest=expected_raw_candidate_digest,
        candidate_run_digest=artifact.candidate_run_digest,
    )
    if artifact.joins != replayed:
        raise ValueError("frozen source join does not replay against pinned raw candidates")
    review_by_id = {review.annotation_id: review for review in artifact.reviews}
    if len(review_by_id) != len(artifact.reviews) or set(review_by_id) != {
        join.annotation_id for join in replayed
    }:
        raise ValueError("frozen join review coverage mismatch")
    for join in replayed:
        review = review_by_id[join.annotation_id]
        if (review.disposition, review.candidate_id) != (join.status, join.candidate_id):
            raise ValueError("frozen join review does not match replayed result")
    return artifact


def freeze_source_prediction_artifact(
    destination: Path,
    reference: FrozenSourceReference,
    join_artifact: FrozenSourceJoinArtifact,
    prediction_output_path: Path,
    run_manifest_path: Path,
    *,
    expected_reference_digest: str,
    expected_development_reference_digest: str,
    expected_join_digest: str,
    expected_prediction_output_sha256: str,
    expected_run_manifest_sha256: str,
    expected_prediction_run_digest: str,
    expected_configuration_digest: str,
    expected_code_digest: str,
) -> Path:
    """Freeze a persisted tracker output only when external run/output pins match."""
    reference = validate_frozen_source_reference(
        reference,
        expected_reference_digest=expected_reference_digest,
        expected_development_reference_digest=expected_development_reference_digest,
    )
    for digest, name in (
        (expected_join_digest, "join artifact digest"),
        (expected_prediction_output_sha256, "prediction output digest"),
        (expected_run_manifest_sha256, "prediction run-manifest digest"),
        (expected_prediction_run_digest, "prediction run digest"),
        (expected_configuration_digest, "prediction configuration digest"),
        (expected_code_digest, "prediction code digest"),
    ):
        _validate_digest(digest, name)
    join_payload = join_artifact.model_dump(mode="json")
    stored_join_digest = join_payload.pop("digest")
    protocol_digest = join_protocol_sha256(reference.manifest.join_protocol)
    if (
        stored_join_digest != expected_join_digest
        or _artifact_digest(join_payload) != expected_join_digest
    ):
        raise ValueError("prediction input join artifact is not externally pinned")
    if (
        join_artifact.source_reference_digest != expected_reference_digest
        or join_artifact.source_video_sha256 != reference.manifest.source_video_sha256
        or join_artifact.join_protocol_digest != protocol_digest
    ):
        raise ValueError("prediction input join artifact source/protocol mismatch")
    output_payload, output_sha256 = _read_artifact_with_sha256(Path(prediction_output_path))
    if output_sha256 != expected_prediction_output_sha256:
        raise ValueError("persisted prediction output SHA-256 mismatch")
    try:
        output = SourcePredictionOutput.model_validate(output_payload)
    except ValidationError as error:
        raise ValueError("invalid persisted prediction output") from error
    manifest_envelope, run_manifest_sha256 = _read_artifact_with_sha256(Path(run_manifest_path))
    if run_manifest_sha256 != expected_run_manifest_sha256:
        raise ValueError("persisted prediction run-manifest SHA-256 mismatch")
    manifest_digest = manifest_envelope.pop("digest", None)
    if not isinstance(manifest_digest, str) or manifest_digest != _artifact_digest(
        manifest_envelope
    ):
        raise ValueError("prediction run-manifest internal digest mismatch")
    try:
        run_manifest = SourcePredictionRunManifest.model_validate(
            {**manifest_envelope, "digest": manifest_digest}
        )
    except ValidationError as error:
        raise ValueError("invalid persisted prediction run manifest") from error
    if (
        run_manifest.source_reference_digest != expected_reference_digest
        or run_manifest.join_artifact_digest != expected_join_digest
        or run_manifest.source_video_sha256 != reference.manifest.source_video_sha256
        or run_manifest.candidate_run_digest != join_artifact.candidate_run_digest
        or run_manifest.prediction_output_sha256 != expected_prediction_output_sha256
        or run_manifest.prediction_run_digest != expected_prediction_run_digest
        or run_manifest.configuration_digest != expected_configuration_digest
        or run_manifest.code_digest != expected_code_digest
    ):
        raise ValueError("prediction run manifest source/run/output/config/code binding mismatch")
    if (
        output.source_reference_digest != expected_reference_digest
        or output.join_artifact_digest != expected_join_digest
        or output.source_video_sha256 != reference.manifest.source_video_sha256
        or output.prediction_run_digest != run_manifest.prediction_run_digest
    ):
        raise ValueError("prediction output header disagrees with pinned run manifest")
    if any(row.prediction_run_digest != output.prediction_run_digest for row in output.predictions):
        raise ValueError("prediction row run digest disagrees with output header")
    payload: dict[str, object] = {
        "source_reference_digest": expected_reference_digest,
        "join_artifact_digest": expected_join_digest,
        "source_video_sha256": reference.manifest.source_video_sha256,
        "candidate_run_digest": run_manifest.candidate_run_digest,
        "prediction_run_digest": run_manifest.prediction_run_digest,
        "run_manifest_sha256": expected_run_manifest_sha256,
        "prediction_output_sha256": expected_prediction_output_sha256,
        "configuration_digest": run_manifest.configuration_digest,
        "code_digest": run_manifest.code_digest,
        "predictions": [row.model_dump(mode="json") for row in output.predictions],
    }
    envelope = {**payload, "digest": _artifact_digest(payload)}
    _write_artifact(Path(destination).parent, Path(destination).name, envelope)
    return Path(destination)


def _validate_persisted_prediction_bindings(
    artifact: FrozenSourcePredictionArtifact,
    prediction_output_path: Path,
    run_manifest_path: Path,
    *,
    expected_prediction_output_sha256: str,
    expected_run_manifest_sha256: str,
    expected_prediction_run_digest: str,
    expected_configuration_digest: str,
    expected_code_digest: str,
    expected_reference_digest: str,
    expected_join_digest: str,
    expected_source_video_sha256: str,
    expected_candidate_run_digest: str,
) -> None:
    output_payload, output_sha256 = _read_artifact_with_sha256(prediction_output_path)
    if output_sha256 != expected_prediction_output_sha256:
        raise ValueError("persisted prediction output SHA-256 mismatch")
    try:
        output = SourcePredictionOutput.model_validate(output_payload)
    except ValidationError as error:
        raise ValueError("invalid persisted prediction output") from error

    manifest_payload, run_manifest_sha256 = _read_artifact_with_sha256(run_manifest_path)
    if run_manifest_sha256 != expected_run_manifest_sha256:
        raise ValueError("persisted prediction run-manifest SHA-256 mismatch")
    manifest_digest = manifest_payload.pop("digest", None)
    if not isinstance(manifest_digest, str) or manifest_digest != _artifact_digest(
        manifest_payload
    ):
        raise ValueError("prediction run-manifest internal digest mismatch")
    try:
        run_manifest = SourcePredictionRunManifest.model_validate(
            {**manifest_payload, "digest": manifest_digest}
        )
    except ValidationError as error:
        raise ValueError("invalid persisted prediction run manifest") from error

    if (
        run_manifest.source_reference_digest != expected_reference_digest
        or run_manifest.join_artifact_digest != expected_join_digest
        or run_manifest.source_video_sha256 != expected_source_video_sha256
        or run_manifest.candidate_run_digest != expected_candidate_run_digest
        or run_manifest.prediction_output_sha256 != expected_prediction_output_sha256
        or run_manifest.prediction_run_digest != expected_prediction_run_digest
        or run_manifest.configuration_digest != expected_configuration_digest
        or run_manifest.code_digest != expected_code_digest
    ):
        raise ValueError("prediction run manifest source/run/output/config/code binding mismatch")
    if (
        output.source_reference_digest != expected_reference_digest
        or output.join_artifact_digest != expected_join_digest
        or output.source_video_sha256 != expected_source_video_sha256
        or output.prediction_run_digest != expected_prediction_run_digest
        or any(
            row.prediction_run_digest != output.prediction_run_digest
            for row in output.predictions
        )
    ):
        raise ValueError("prediction output header/row provenance mismatch")
    if output.predictions != artifact.predictions:
        raise ValueError("frozen predictions differ from independently pinned prediction output")
    if (
        artifact.source_reference_digest != expected_reference_digest
        or artifact.join_artifact_digest != expected_join_digest
        or artifact.source_video_sha256 != expected_source_video_sha256
        or artifact.candidate_run_digest != expected_candidate_run_digest
        or artifact.prediction_run_digest != expected_prediction_run_digest
        or artifact.run_manifest_sha256 != expected_run_manifest_sha256
        or artifact.prediction_output_sha256 != expected_prediction_output_sha256
        or artifact.configuration_digest != expected_configuration_digest
        or artifact.code_digest != expected_code_digest
    ):
        raise ValueError("prediction artifact source/join/run/output/config/code binding mismatch")


def read_frozen_source_prediction_artifact(
    path: Path,
    prediction_output_path: Path,
    run_manifest_path: Path,
    *,
    expected_prediction_digest: str,
    expected_prediction_output_sha256: str,
    expected_run_manifest_sha256: str,
    expected_prediction_run_digest: str,
    expected_configuration_digest: str,
    expected_code_digest: str,
    expected_reference_digest: str,
    expected_join_digest: str,
    expected_source_video_sha256: str,
    expected_candidate_run_digest: str,
) -> FrozenSourcePredictionArtifact:
    """Read only a persisted prediction envelope whose run and output pins are external."""
    for digest, name in (
        (expected_prediction_digest, "prediction artifact digest"),
        (expected_prediction_output_sha256, "prediction output digest"),
        (expected_run_manifest_sha256, "prediction run-manifest digest"),
        (expected_prediction_run_digest, "prediction run digest"),
        (expected_configuration_digest, "prediction configuration digest"),
        (expected_code_digest, "prediction code digest"),
    ):
        _validate_digest(digest, name)
    payload = _read_artifact(Path(path))
    prediction_artifact_digest = payload.pop("digest", None)
    if not isinstance(prediction_artifact_digest, str):
        raise ValueError("prediction artifact digest is missing")
    if (
        prediction_artifact_digest != expected_prediction_digest
        or _artifact_digest(payload) != expected_prediction_digest
    ):
        raise ValueError("prediction artifact does not match externally pinned digest")
    try:
        artifact = FrozenSourcePredictionArtifact.model_validate(
            {**payload, "digest": prediction_artifact_digest}
        )
    except ValidationError as error:
        raise ValueError("invalid frozen prediction artifact") from error
    _validate_persisted_prediction_bindings(
        artifact,
        prediction_output_path,
        run_manifest_path,
        expected_prediction_output_sha256=expected_prediction_output_sha256,
        expected_run_manifest_sha256=expected_run_manifest_sha256,
        expected_prediction_run_digest=expected_prediction_run_digest,
        expected_configuration_digest=expected_configuration_digest,
        expected_code_digest=expected_code_digest,
        expected_reference_digest=expected_reference_digest,
        expected_join_digest=expected_join_digest,
        expected_source_video_sha256=expected_source_video_sha256,
        expected_candidate_run_digest=expected_candidate_run_digest,
    )
    return artifact


def validate_prediction_artifact(
    artifact: FrozenSourcePredictionArtifact,
    reference: FrozenSourceReference,
    join_artifact: FrozenSourceJoinArtifact,
    prediction_output_path: Path,
    run_manifest_path: Path,
    *,
    expected_prediction_digest: str,
    expected_prediction_output_sha256: str,
    expected_run_manifest_sha256: str,
    expected_prediction_run_digest: str,
    expected_configuration_digest: str,
    expected_code_digest: str,
    expected_reference_digest: str,
    expected_development_reference_digest: str,
    expected_join_digest: str,
) -> FrozenSourcePredictionArtifact:
    reference = validate_frozen_source_reference(
        reference,
        expected_reference_digest=expected_reference_digest,
        expected_development_reference_digest=expected_development_reference_digest,
    )
    try:
        artifact = FrozenSourcePredictionArtifact.model_validate(artifact.model_dump(mode="python"))
    except (ValidationError, AttributeError, TypeError) as error:
        raise ValueError("invalid frozen prediction artifact") from error
    payload = artifact.model_dump(mode="json")
    digest = payload.pop("digest")
    if (
        digest != expected_prediction_digest
        or _artifact_digest(payload) != expected_prediction_digest
    ):
        raise ValueError("prediction artifact does not match externally pinned digest")
    if (
        artifact.candidate_run_digest != join_artifact.candidate_run_digest
        or join_artifact.source_reference_digest != expected_reference_digest
    ):
        raise ValueError("prediction artifact source/join/run/output/config/code binding mismatch")
    _validate_persisted_prediction_bindings(
        artifact,
        prediction_output_path,
        run_manifest_path,
        expected_prediction_output_sha256=expected_prediction_output_sha256,
        expected_run_manifest_sha256=expected_run_manifest_sha256,
        expected_prediction_run_digest=expected_prediction_run_digest,
        expected_configuration_digest=expected_configuration_digest,
        expected_code_digest=expected_code_digest,
        expected_reference_digest=expected_reference_digest,
        expected_join_digest=expected_join_digest,
        expected_source_video_sha256=reference.manifest.source_video_sha256,
        expected_candidate_run_digest=join_artifact.candidate_run_digest,
    )
    frame_pts = {frame.frame_index: frame.source_pts for frame in reference.manifest.frames}
    matched_keys = {
        (join.frame_index, join.candidate_id)
        for join in join_artifact.joins
        if join.status == "matched" and join.candidate_id is not None
    }
    seen: set[tuple[int, str]] = set()
    for row in artifact.predictions:
        key = (row.frame_index, row.candidate_id)
        if key in seen:
            raise ValueError("duplicate prediction candidate key")
        seen.add(key)
        if row.prediction_run_digest != artifact.prediction_run_digest:
            raise ValueError("prediction row run digest disagrees with artifact header")
        if (
            row.source_video_sha256 != artifact.source_video_sha256
            or frame_pts.get(row.frame_index) != row.source_pts
            or row.timebase_numerator != reference.manifest.timebase_numerator
            or row.timebase_denominator != reference.manifest.timebase_denominator
        ):
            raise ValueError("prediction source/frame/PTS/timebase mismatch")
        if key not in matched_keys:
            raise ValueError("prediction has no replayed reviewed source join")
    return artifact


def evaluate_source_reference(
    reference: FrozenSourceReference,
    join_artifact: FrozenSourceJoinArtifact,
    candidates: Iterable[ReferenceCandidate],
    prediction_artifact_path: Path,
    prediction_output_path: Path,
    run_manifest_path: Path,
    *,
    expected_reference_digest: str,
    expected_development_reference_digest: str,
    expected_join_digest: str,
    expected_raw_candidate_digest: str,
    expected_prediction_digest: str,
    expected_prediction_output_sha256: str,
    expected_run_manifest_sha256: str,
    expected_prediction_run_digest: str,
    expected_configuration_digest: str,
    expected_code_digest: str,
) -> SourceReferenceReport:
    """Score only externally pinned source, replayed/reviewed joins, and pinned predictions."""
    reference = validate_frozen_source_reference(
        reference,
        expected_reference_digest=expected_reference_digest,
        expected_development_reference_digest=expected_development_reference_digest,
    )
    join_artifact = validate_frozen_source_join_artifact(
        join_artifact,
        reference,
        candidates,
        expected_join_digest=expected_join_digest,
        expected_reference_digest=expected_reference_digest,
        expected_development_reference_digest=expected_development_reference_digest,
        expected_raw_candidate_digest=expected_raw_candidate_digest,
    )
    prediction_artifact = read_frozen_source_prediction_artifact(
        prediction_artifact_path,
        prediction_output_path,
        run_manifest_path,
        expected_prediction_digest=expected_prediction_digest,
        expected_prediction_output_sha256=expected_prediction_output_sha256,
        expected_run_manifest_sha256=expected_run_manifest_sha256,
        expected_prediction_run_digest=expected_prediction_run_digest,
        expected_configuration_digest=expected_configuration_digest,
        expected_code_digest=expected_code_digest,
        expected_reference_digest=expected_reference_digest,
        expected_join_digest=expected_join_digest,
        expected_source_video_sha256=reference.manifest.source_video_sha256,
        expected_candidate_run_digest=join_artifact.candidate_run_digest,
    )
    prediction_artifact = validate_prediction_artifact(
        prediction_artifact,
        reference,
        join_artifact,
        prediction_output_path,
        run_manifest_path,
        expected_prediction_digest=expected_prediction_digest,
        expected_prediction_output_sha256=expected_prediction_output_sha256,
        expected_run_manifest_sha256=expected_run_manifest_sha256,
        expected_prediction_run_digest=expected_prediction_run_digest,
        expected_configuration_digest=expected_configuration_digest,
        expected_code_digest=expected_code_digest,
        expected_reference_digest=expected_reference_digest,
        expected_development_reference_digest=expected_development_reference_digest,
        expected_join_digest=expected_join_digest,
    )
    rows = reference.observations
    join_by_id = {join.annotation_id: join for join in join_artifact.joins}
    predictions = {
        (row.frame_index, row.candidate_id): row for row in prediction_artifact.predictions
    }
    visible = [row for row in rows if row.marker_class == "player"]
    uncertain = [row for row in rows if row.marker_class == "class_uncertain"]
    d = sum((row.duration_seconds for row in visible), Fraction(0))
    class_uncertain = sum((row.duration_seconds for row in uncertain), Fraction(0))
    d_lower, d_upper, collision_uncertain = _visible_player_duration_bounds(rows)
    established = [row for row in visible if row.expected_player_id is not None]
    k = sum((row.duration_seconds for row in established), Fraction(0))
    correct = assigned = unmapped = unknown = Fraction(0)
    transitions: dict[str, list[tuple[int, int, str | None, str, list[str]]]] = defaultdict(list)
    for row in visible:
        if row.expected_player_id is None:
            unknown += row.duration_seconds
        join = join_by_id.get(row.annotation_id)
        if join is None or join.status != "matched" or join.candidate_id is None:
            unmapped += row.duration_seconds
            prediction = None
        else:
            prediction = predictions.get((row.frame_index, join.candidate_id))
        assigned_id = prediction.assigned_player_id if prediction else None
        if assigned_id is not None:
            assigned += row.duration_seconds
            if row.expected_player_id is not None and assigned_id == row.expected_player_id:
                correct += row.duration_seconds
        if row.expected_player_id is not None:
            transitions[row.expected_player_id].append(
                (
                    row.source_pts,
                    row.interval_end_source_pts,
                    assigned_id,
                    row.continuity_before,
                    row.continuity_evidence,
                )
            )
    switches = eligible = excluded = 0
    for sequence in transitions.values():
        sequence.sort()
        for left, right in zip(sequence, sequence[1:]):
            if (
                left[1] == right[0]
                and right[3] == "continuous"
                and left[2] is not None
                and right[2] is not None
                and right[4]
            ):
                eligible += 1
                switches += left[2] != right[2]
            else:
                excluded += 1
    unknown_identity_rows = [row for row in visible if row.expected_player_id is None]
    unassessed_unknown_count = len(unknown_identity_rows)
    transition_total = eligible + excluded + unassessed_unknown_count
    coverage = eligible / transition_total if transition_total else None
    if eligible == 0:
        stability_scope: Literal[
            "full_reviewed_scope", "partial_continuity", "no_eligible_transitions"
        ] = "no_eligible_transitions"
    elif excluded or unassessed_unknown_count:
        stability_scope = "partial_continuity"
    else:
        stability_scope = "full_reviewed_scope"
    frame_duration = {
        left.frame_index: Fraction(
            (right.source_pts - left.source_pts) * reference.manifest.timebase_numerator,
            reference.manifest.timebase_denominator,
        )
        for left, right in zip(reference.manifest.frames, reference.manifest.frames[1:])
    }
    nonlive = sum(
        (
            frame_duration[index]
            for index in reference.manifest.nonlive_frame_indices
            if index in frame_duration
        ),
        Fraction(0),
    )
    unknown_context = sum(
        (
            frame_duration[index]
            for index in reference.manifest.unknown_context_frame_indices
            if index in frame_duration
        ),
        Fraction(0),
    )
    completeness = (
        len(reference.manifest.reviewed_annotation_frame_indices)
        / len(reference.manifest.live_frame_indices)
        if reference.manifest.live_frame_indices
        else None
    )
    computable = bool(rows and d > 0 and join_artifact.joins and prediction_artifact.predictions)
    target_eligible = bool(
        computable
        and completeness == 1
        and class_uncertain == 0
        and collision_uncertain == 0
        and unknown_context == 0
        and eligible > 0
        and excluded == 0
        and unassessed_unknown_count == 0
    )
    reason = (
        None
        if target_eligible
        else (
            "scoped_metrics_computable_target_not_eligible"
            if computable
            else "source_reference_or_join_or_predictions_unavailable"
        )
    )
    return SourceReferenceReport(
        split=reference.manifest.split,
        source_reference_digest=expected_reference_digest,
        candidate_run_digest=join_artifact.candidate_run_digest,
        raw_candidate_digest=join_artifact.raw_candidate_digest,
        join_protocol_digest=join_artifact.join_protocol_digest,
        join_artifact_digest=expected_join_digest,
        prediction_artifact_digest=expected_prediction_digest,
        prediction_output_sha256=prediction_artifact.prediction_output_sha256,
        prediction_run_manifest_sha256=prediction_artifact.run_manifest_sha256,
        prediction_configuration_digest=prediction_artifact.configuration_digest,
        prediction_code_digest=prediction_artifact.code_digest,
        prediction_run_digest=prediction_artifact.prediction_run_digest,
        computable=computable,
        target_eligible=target_eligible,
        reason=reason,
        visible_player_duration_seconds=d,
        visible_player_duration_lower_seconds=d_lower,
        visible_player_duration_upper_seconds=d_upper,
        established_identity_duration_seconds=k,
        verified_correct_duration_seconds=correct,
        unknown_identity_duration_seconds=unknown,
        unassessed_unknown_identity_duration_seconds=unknown,
        unassessed_unknown_identity_count=unassessed_unknown_count,
        class_uncertain_duration_seconds=class_uncertain,
        marker_collision_uncertain_duration_seconds=collision_uncertain,
        nonlive_duration_seconds=nonlive,
        unknown_context_duration_seconds=unknown_context,
        unmapped_duration_seconds=unmapped,
        assigned_duration_seconds=assigned,
        switch_count=switches,
        eligible_transition_count=eligible,
        excluded_transition_count=excluded,
        continuity_coverage=coverage,
        stability_scope=stability_scope,
        completeness_fraction=completeness,
        correct_fraction_of_visible=float(correct / d) if d else None,
        correct_fraction_lower_bound=float(correct / d_upper) if d_upper else None,
        correct_fraction_upper_bound=float(min(Fraction(1), correct / d_lower))
        if d_lower
        else None,
        identity_coverage=float(k / d) if d else None,
        assignment_coverage=float(assigned / d) if d else None,
    )


def _visible_player_duration_bounds(
    rows: list[SourcePlayerReferenceObservation],
) -> tuple[Fraction, Fraction, Fraction]:
    """Bound visible-player duration through connected collision groups by class."""
    by_frame: dict[int, list[SourcePlayerReferenceObservation]] = defaultdict(list)
    for row in rows:
        by_frame[row.frame_index].append(row)
    lower = upper = collision_excess = Fraction(0)
    for frame_rows in by_frame.values():
        by_id = {row.annotation_id: row for row in frame_rows}
        graph: dict[str, set[str]] = defaultdict(set)
        for index, left in enumerate(frame_rows):
            for right in frame_rows[index + 1 :]:
                if _iou(left.bbox, right.bbox) >= 0.9 and (
                    left.marker_collision_resolution == "unresolved"
                    or right.marker_collision_resolution == "unresolved"
                ):
                    graph[left.annotation_id].add(right.annotation_id)
                    graph[right.annotation_id].add(left.annotation_id)
        grouped: set[str] = set()
        for seed in graph:
            if seed in grouped:
                continue
            component: set[str] = set()
            frontier = [seed]
            while frontier:
                current = frontier.pop()
                if current in component:
                    continue
                component.add(current)
                frontier.extend(graph[current] - component)
            grouped.update(component)
            members = [by_id[annotation_id] for annotation_id in component]
            player_seconds = sum(
                (row.duration_seconds for row in members if row.marker_class == "player"),
                Fraction(0),
            )
            possible_seconds = sum(
                (
                    row.duration_seconds
                    for row in members
                    if row.marker_class in {"player", "class_uncertain"}
                ),
                Fraction(0),
            )
            minimum_confirmed = max(
                (row.duration_seconds for row in members if row.marker_class == "player"),
                default=Fraction(0),
            )
            lower += minimum_confirmed
            upper += possible_seconds
            collision_excess += max(Fraction(0), player_seconds - minimum_confirmed)
        for row in frame_rows:
            if row.annotation_id in grouped:
                continue
            if row.marker_class == "player":
                lower += row.duration_seconds
                upper += row.duration_seconds
            elif row.marker_class == "class_uncertain":
                upper += row.duration_seconds
    return lower, upper, collision_excess


def _open_directory_fd(path: Path, *, create: bool) -> int:
    """Open every directory component relative to an FD with O_NOFOLLOW; pins traversal."""
    if ".." in path.parts:
        raise ValueError("artifact path traversal is forbidden")
    absolute = Path(os.path.abspath(path))
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(absolute.anchor, flags)
    try:
        for part in absolute.parts[1:]:
            try:
                child = os.open(part, flags, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(part, mode=0o700, dir_fd=fd)
                child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _write_artifact(directory: Path, name: str, value: dict[str, object]) -> None:
    if Path(name).name != name or name in {".", ".."}:
        raise ValueError("artifact filename must be a single path component")
    payload = _canonical(value) + b"\n"
    fd = _open_directory_fd(directory, create=True)
    file_fd: int | None = None
    created_by_this_call = False
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        file_fd = os.open(name, flags, 0o600, dir_fd=fd)
        created_by_this_call = True
        with os.fdopen(file_fd, "wb", closefd=True) as output:
            file_fd = None
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        if file_fd is not None:
            os.close(file_fd)
        if created_by_this_call:
            try:
                os.unlink(name, dir_fd=fd)
            except FileNotFoundError:
                pass
        raise
    finally:
        os.close(fd)


def _read_artifact(path: Path) -> dict[str, object]:
    return _read_artifact_with_sha256(path)[0]


def _read_artifact_with_sha256(path: Path) -> tuple[dict[str, object], str]:
    if Path(path.name).name != path.name:
        raise ValueError("artifact filename must be a single path component")
    fd = _open_directory_fd(path.parent, create=False)
    file_fd: int | None = None
    try:
        file_fd = os.open(path.name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=fd)
        if not stat.S_ISREG(os.fstat(file_fd).st_mode):
            raise ValueError("artifact must be a regular file")
        with os.fdopen(file_fd, "rb", closefd=True) as stream:
            file_fd = None
            payload = stream.read()
    except OSError as error:
        raise ValueError("artifact missing, symlinked, or unreadable") from error
    finally:
        if file_fd is not None:
            os.close(file_fd)
        os.close(fd)
    try:
        value = json.loads(payload)
        if not isinstance(value, dict) or payload != _canonical(value) + b"\n":
            raise ValueError("artifact bytes are not canonical")
        return value, _sha(payload)
    except (json.JSONDecodeError, TypeError) as error:
        raise ValueError("invalid canonical artifact JSON") from error


def _iou(
    left: tuple[float, float, float, float], right: tuple[float, float, float, float]
) -> float:
    ax, ay, aw, ah = left
    bx, by, bw, bh = right
    intersection = max(0.0, min(ax + aw, bx + bw) - max(ax, bx)) * max(
        0.0, min(ay + ah, by + bh) - max(ay, by)
    )
    union = aw * ah + bw * bh - intersection
    return min(1.0, intersection / union) if union else 0.0
