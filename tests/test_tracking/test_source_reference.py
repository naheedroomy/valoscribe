from __future__ import annotations

import hashlib
import json
from fractions import Fraction
from pathlib import Path
from typing import Literal

import pytest
from pydantic import ValidationError

from valoscribe.tracking.source_reference import (
    evaluate_source_reference,
    freeze_source_join_artifact,
    freeze_source_prediction_artifact,
    freeze_source_reference,
    join_protocol_sha256,
    join_reference_candidates,
    raw_candidate_sha256,
    read_frozen_source_join_artifact,
    read_frozen_source_prediction_artifact,
    read_frozen_source_reference,
    source_reference_digest,
    validate_frozen_source_join_artifact,
    validate_prediction_artifact,
    validate_source_reference,
)
from valoscribe.types.source_reference import (
    FrozenSourcePredictionArtifact,
    FrozenSourceReference,
    ReferenceCandidate,
    SourceJoinProtocol,
    SourceJoinReview,
    SourcePlayerReferenceObservation,
    SourcePredictionOutput,
    SourceReferenceFrame,
    SourceReferenceManifest,
    SourceReferencePrediction,
    SourceSplitAllocation,
    SplitRoundRecord,
)


def _allocation(source_hash: str) -> SourceSplitAllocation:
    records = []
    index = 0
    split_rounds: tuple[
        tuple[Literal["development", "validation", "test"], tuple[str, ...]], ...
    ] = (
        ("development", ("r1", "r2", "r3")),
        ("validation", ("r4", "r5")),
        ("test", ("r6",)),
    )
    for split, round_ids in split_rounds:
        for round_id in round_ids:
            frame_start = index * 10
            pts_start = 1_000 + index * 100
            records.append(
                SplitRoundRecord(
                    source_video_sha256=source_hash,
                    match_id="m",
                    round_id=round_id,
                    split=split,
                    start_frame_index=frame_start,
                    end_frame_index=frame_start + 3,
                    start_source_pts=pts_start,
                    end_source_pts=pts_start + 30,
                    timebase_numerator=1,
                    timebase_denominator=10,
                    inventory_digest="1" * 64,
                    prior_exposure="none" if split == "test" else split,
                    custody_record_sha256="2" * 64,
                    custody_review_evidence=[f"{round_id}_custody_review"],
                    allocation_reviewer_id=f"alloc-{round_id}",
                    independent_reviewer_id=f"independent-{round_id}",
                )
            )
            index += 1
    return SourceSplitAllocation(rounds=records, retired_test_intervals=[])


def _source() -> tuple[SourceReferenceManifest, list[SourcePlayerReferenceObservation]]:
    source_hash = "a" * 64
    allocation = _allocation(source_hash)
    protocol = SourceJoinProtocol(
        threshold_iou=0.5,
        approval_record_sha256="5" * 64,
        approval_evidence=["development_join_protocol_review"],
        development_reference_digest="f" * 64,
        reviewer_id="protocol-reviewer-a",
        independent_reviewer_id="protocol-reviewer-b",
    )
    manifest = SourceReferenceManifest(
        source_video_sha256=source_hash,
        match_id="m",
        map_id="ascent",
        round_id="r1",
        split="development",
        timestamp_kind="pts",
        start_frame_index=0,
        end_frame_index=3,
        timebase_numerator=1,
        timebase_denominator=10,
        source_width=1920,
        source_height=1080,
        frames=[SourceReferenceFrame(frame_index=i, source_pts=1_000 + 10 * i) for i in range(4)],
        allocation=allocation,
        join_protocol=protocol,
        inventory_review_record_sha256="6" * 64,
        inventory_review_evidence=["full_source_inventory_review"],
        inventory_reviewer="inventory-a",
        inventory_independent_reviewer="inventory-b",
        inventory_adjudicator="inventory-c",
        live_frame_indices=[0, 1, 2, 3],
        reviewed_annotation_frame_indices=[0, 1, 2, 3],
        nonlive_frame_indices=[],
        unknown_context_frame_indices=[],
    )
    observation = SourcePlayerReferenceObservation(
        source_video_sha256=source_hash,
        match_id="m",
        map_id="ascent",
        round_id="r1",
        frame_index=0,
        source_pts=1_000,
        interval_end_source_pts=1_010,
        timebase_numerator=1,
        timebase_denominator=10,
        annotation_id="local-1",
        coordinate_frame="source_frame_normalized",
        bbox=(0.1, 0.1, 0.2, 0.2),
        marker_class="player",
        expected_player_id=None,
        claim_confidence=0.8,
        claim_evidence=["source_visible_marker"],
        annotation_scope="source_only",
        reviewer_kind="ai",
        reviewer_id="reviewer-a",
        reviewer_version="model-a-v1",
        independent_reviewer_kind="ai",
        independent_reviewer_id="reviewer-b",
        independent_reviewer_version="model-b-v1",
        adjudicator_kind="human",
        adjudicator_id="adjudicator-c",
        adjudicator_version="review-v1",
        adjudication_evidence=["blind_review_record"],
        blind_review_record_sha256="7" * 64,
        disagreement_disposition="agreement",
        continuity_before="continuous",
        continuity_evidence=["adjacent_source_frame_review"],
        reference_label_scope="ai_reviewed_not_human_gold",
    )
    return manifest, [observation]


def _candidate(manifest, frame_index: int, candidate_id: str, *, bbox=None) -> ReferenceCandidate:
    pts = next(frame.source_pts for frame in manifest.frames if frame.frame_index == frame_index)
    return ReferenceCandidate(
        source_video_sha256=manifest.source_video_sha256,
        frame_index=frame_index,
        source_pts=pts,
        timebase_numerator=manifest.timebase_numerator,
        timebase_denominator=manifest.timebase_denominator,
        coordinate_frame="source_frame_normalized",
        candidate_id=candidate_id,
        bbox=bbox or (0.1, 0.1, 0.2, 0.2),
    )


def _prediction(
    manifest, frame_index: int, candidate_id: str, assigned: str | None, *, run_digest="e" * 64
) -> SourceReferencePrediction:
    pts = next(frame.source_pts for frame in manifest.frames if frame.frame_index == frame_index)
    return SourceReferencePrediction(
        source_video_sha256=manifest.source_video_sha256,
        frame_index=frame_index,
        source_pts=pts,
        timebase_numerator=manifest.timebase_numerator,
        timebase_denominator=manifest.timebase_denominator,
        prediction_run_digest=run_digest,
        candidate_id=candidate_id,
        assigned_player_id=assigned,
    )


def _prediction_provenance_files(
    tmp_path: Path,
    reference: FrozenSourceReference,
    join_artifact,
    predictions,
    *,
    header_run_digest: str = "e" * 64,
    manifest_run_digest: str = "e" * 64,
):
    output = SourcePredictionOutput(
        source_reference_digest=reference.digest,
        join_artifact_digest=join_artifact.digest,
        source_video_sha256=reference.manifest.source_video_sha256,
        prediction_run_digest=header_run_digest,
        predictions=predictions,
    )
    output_bytes = (
        json.dumps(
            output.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
        + b"\n"
    )
    output_path = tmp_path / "tracker-output.json"
    output_path.write_bytes(output_bytes)
    output_sha = hashlib.sha256(output_bytes).hexdigest()
    manifest_body = {
        "schema_version": "1.0",
        "source_reference_digest": reference.digest,
        "join_artifact_digest": join_artifact.digest,
        "source_video_sha256": reference.manifest.source_video_sha256,
        "candidate_run_digest": join_artifact.candidate_run_digest,
        "prediction_run_digest": manifest_run_digest,
        "prediction_output_sha256": output_sha,
        "configuration_digest": "3" * 64,
        "code_digest": "4" * 64,
    }
    manifest_digest = hashlib.sha256(
        json.dumps(
            manifest_body,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    manifest_bytes = (
        json.dumps(
            {**manifest_body, "digest": manifest_digest},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
        + b"\n"
    )
    manifest_path = tmp_path / "tracker-run-manifest.json"
    manifest_path.write_bytes(manifest_bytes)
    return (
        output_path,
        manifest_path,
        output_sha,
        hashlib.sha256(manifest_bytes).hexdigest(),
        manifest_run_digest,
    )


def _frozen_reference(tmp_path: Path, manifest, observations) -> FrozenSourceReference:
    digest = source_reference_digest(manifest, observations)
    development_digest = manifest.join_protocol.development_reference_digest
    path = freeze_source_reference(
        tmp_path,
        manifest,
        observations,
        expected_development_reference_digest=development_digest,
    )
    frozen_bytes = path.read_bytes()
    with pytest.raises(FileExistsError):
        freeze_source_reference(
            tmp_path,
            manifest,
            observations,
            expected_development_reference_digest=development_digest,
        )
    assert path.read_bytes() == frozen_bytes
    return read_frozen_source_reference(
        path,
        expected_source_sha256=manifest.source_video_sha256,
        expected_reference_digest=digest,
        expected_development_reference_digest=development_digest,
    )


def _reviewed_join(tmp_path: Path, reference, candidates, *, forged=None):
    expected_raw = raw_candidate_sha256(candidates)
    generated = join_reference_candidates(
        reference,
        candidates,
        expected_reference_digest=reference.digest,
        expected_development_reference_digest=reference.manifest.join_protocol.development_reference_digest,
        expected_raw_candidate_digest=expected_raw,
        candidate_run_digest="c" * 64,
    )
    if forged is not None:
        generated = forged(generated)
    reviews = [
        SourceJoinReview(
            annotation_id=row.annotation_id,
            disposition=row.status,
            candidate_id=row.candidate_id,
            primary_reviewer_id="correspondence-a",
            independent_reviewer_id="correspondence-b",
            adjudicator_id="correspondence-c",
            evidence=["source_candidate_geometry_review"],
            review_scope="source_candidate_geometry_only",
        )
        for row in generated
    ]
    path = tmp_path / "reviewed-join.json"
    freeze_source_join_artifact(
        path,
        reference,
        candidates,
        generated,
        reviews,
        expected_reference_digest=reference.digest,
        expected_development_reference_digest=reference.manifest.join_protocol.development_reference_digest,
        expected_raw_candidate_digest=expected_raw,
        candidate_run_digest="c" * 64,
    )
    frozen_bytes = path.read_bytes()
    with pytest.raises(FileExistsError):
        freeze_source_join_artifact(
            path,
            reference,
            candidates,
            generated,
            reviews,
            expected_reference_digest=reference.digest,
            expected_development_reference_digest=reference.manifest.join_protocol.development_reference_digest,
            expected_raw_candidate_digest=expected_raw,
            candidate_run_digest="c" * 64,
        )
    assert path.read_bytes() == frozen_bytes
    digest = json.loads(path.read_bytes())["digest"]
    artifact = read_frozen_source_join_artifact(
        path,
        expected_join_digest=digest,
        expected_reference_digest=reference.digest,
        expected_raw_candidate_digest=expected_raw,
        expected_join_protocol_digest=join_protocol_sha256(reference.manifest.join_protocol),
    )
    return artifact, expected_raw


def _score(tmp_path, manifest, observations, candidates, predictions):
    reference = _frozen_reference(tmp_path / "reference", manifest, observations)
    join_artifact, raw_digest = _reviewed_join(tmp_path, reference, candidates)
    output_path, run_manifest_path, output_sha, run_manifest_sha, run_digest = (
        _prediction_provenance_files(tmp_path, reference, join_artifact, predictions)
    )
    frozen_path = tmp_path / "frozen-predictions.json"
    freeze_source_prediction_artifact(
        frozen_path,
        reference,
        join_artifact,
        output_path,
        run_manifest_path,
        expected_reference_digest=reference.digest,
        expected_development_reference_digest=reference.manifest.join_protocol.development_reference_digest,
        expected_join_digest=join_artifact.digest,
        expected_prediction_output_sha256=output_sha,
        expected_run_manifest_sha256=run_manifest_sha,
        expected_prediction_run_digest=run_digest,
        expected_configuration_digest="3" * 64,
        expected_code_digest="4" * 64,
    )
    frozen_bytes = frozen_path.read_bytes()
    with pytest.raises(FileExistsError):
        freeze_source_prediction_artifact(
            frozen_path,
            reference,
            join_artifact,
            output_path,
            run_manifest_path,
            expected_reference_digest=reference.digest,
            expected_development_reference_digest=reference.manifest.join_protocol.development_reference_digest,
            expected_join_digest=join_artifact.digest,
            expected_prediction_output_sha256=output_sha,
            expected_run_manifest_sha256=run_manifest_sha,
            expected_prediction_run_digest=run_digest,
            expected_configuration_digest="3" * 64,
            expected_code_digest="4" * 64,
        )
    assert frozen_path.read_bytes() == frozen_bytes
    artifact_digest = json.loads(frozen_bytes)["digest"]
    return evaluate_source_reference(
        reference,
        join_artifact,
        candidates,
        frozen_path,
        output_path,
        run_manifest_path,
        expected_reference_digest=reference.digest,
        expected_development_reference_digest=reference.manifest.join_protocol.development_reference_digest,
        expected_join_digest=join_artifact.digest,
        expected_raw_candidate_digest=raw_digest,
        expected_prediction_digest=artifact_digest,
        expected_prediction_output_sha256=output_sha,
        expected_run_manifest_sha256=run_manifest_sha,
        expected_prediction_run_digest=run_digest,
        expected_configuration_digest="3" * 64,
        expected_code_digest="4" * 64,
    )


def _frozen_prediction_case(tmp_path):
    manifest, observations = _source()
    known = SourcePlayerReferenceObservation.model_validate(
        {
            **observations[0].model_dump(),
            "expected_player_id": "p1",
            "identity_confidence": 0.9,
            "identity_evidence": ["source_name_plate_link"],
        }
    )
    reference = _frozen_reference(tmp_path / "reference", manifest, [known])
    candidate = _candidate(manifest, 0, "c1")
    join_artifact, raw_digest = _reviewed_join(tmp_path, reference, [candidate])
    prediction = _prediction(manifest, 0, "c1", "p2")
    output_path, run_manifest_path, output_sha, manifest_sha, run_digest = (
        _prediction_provenance_files(tmp_path, reference, join_artifact, [prediction])
    )
    frozen_path = tmp_path / "frozen-predictions.json"
    freeze_source_prediction_artifact(
        frozen_path,
        reference,
        join_artifact,
        output_path,
        run_manifest_path,
        expected_reference_digest=reference.digest,
        expected_development_reference_digest=manifest.join_protocol.development_reference_digest,
        expected_join_digest=join_artifact.digest,
        expected_prediction_output_sha256=output_sha,
        expected_run_manifest_sha256=manifest_sha,
        expected_prediction_run_digest=run_digest,
        expected_configuration_digest="3" * 64,
        expected_code_digest="4" * 64,
    )
    payload = json.loads(frozen_path.read_bytes())
    artifact = FrozenSourcePredictionArtifact.model_validate(payload)
    return (
        manifest,
        reference,
        join_artifact,
        [candidate],
        raw_digest,
        output_path,
        run_manifest_path,
        output_sha,
        manifest_sha,
        run_digest,
        frozen_path,
        artifact,
    )


def test_irregular_pts_weights_duration_and_preserves_unknown_identity(tmp_path) -> None:
    manifest, rows = _source()
    report = _score(
        tmp_path,
        manifest,
        rows,
        [_candidate(manifest, 0, "c1")],
        [_prediction(manifest, 0, "c1", None)],
    )
    assert report.visible_player_duration_seconds == Fraction(1, 1)
    assert report.unknown_identity_duration_seconds == Fraction(1, 1)
    assert report.established_identity_duration_seconds == 0
    assert report.computable
    assert not report.target_eligible


def test_pinned_reference_rejects_rehashed_mutation(tmp_path) -> None:
    manifest, rows = _source()
    digest = source_reference_digest(manifest, rows)
    path = freeze_source_reference(
        tmp_path,
        manifest,
        rows,
        expected_development_reference_digest=manifest.join_protocol.development_reference_digest,
    )
    envelope = json.loads(path.read_bytes())
    envelope["observations"][0]["claim_confidence"] = 0.1
    body = {key: value for key, value in envelope.items() if key != "digest"}
    envelope["digest"] = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    path.write_bytes(json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode() + b"\n")
    with pytest.raises(ValueError, match="externally pinned digest"):
        read_frozen_source_reference(
            path,
            expected_source_sha256=manifest.source_video_sha256,
            expected_reference_digest=digest,
            expected_development_reference_digest=manifest.join_protocol.development_reference_digest,
        )


def test_duplicate_established_player_frame_alias_is_rejected() -> None:
    manifest, rows = _source()
    known = SourcePlayerReferenceObservation.model_validate(
        {
            **rows[0].model_dump(),
            "expected_player_id": "p1",
            "identity_confidence": 0.9,
            "identity_evidence": ["source_name_plate_link"],
        }
    )
    alias = SourcePlayerReferenceObservation.model_validate(
        {
            **known.model_dump(),
            "annotation_id": "alias",
        }
    )
    with pytest.raises(ValueError, match="aliased same player"):
        validate_source_reference(manifest, [known, alias])


def test_unresolved_marker_collision_remains_in_bounds_not_dropped(tmp_path) -> None:
    manifest, rows = _source()
    duplicate_unknown = SourcePlayerReferenceObservation.model_validate(
        {
            **rows[0].model_dump(),
            "annotation_id": "unknown-alias",
            "marker_collision_resolution": "unresolved",
            "marker_collision_evidence": ["reviewer-could-not-resolve-overlap"],
        }
    )
    primary = SourcePlayerReferenceObservation.model_validate(
        {
            **rows[0].model_dump(),
            "marker_collision_resolution": "unresolved",
            "marker_collision_evidence": ["reviewer-could-not-resolve-overlap"],
        }
    )
    report = _score(tmp_path, manifest, [primary, duplicate_unknown], [], [])
    assert report.visible_player_duration_lower_seconds == Fraction(1, 1)
    assert report.visible_player_duration_upper_seconds == Fraction(2, 1)
    assert report.marker_collision_uncertain_duration_seconds == Fraction(1, 1)
    assert report.unknown_identity_duration_seconds == Fraction(2, 1)
    assert not report.target_eligible


def test_three_way_player_collision_bounds_all_aliases_conservatively(tmp_path) -> None:
    manifest, observations = _source()
    rows = [
        SourcePlayerReferenceObservation.model_validate(
            {
                **observations[0].model_dump(),
                "annotation_id": f"alias-{index}",
                "marker_collision_resolution": "unresolved",
                "marker_collision_evidence": ["three_way_overlap_not_resolved"],
            }
        )
        for index in range(3)
    ]
    report = _score(tmp_path, manifest, rows, [], [])
    assert report.visible_player_duration_seconds == Fraction(3, 1)
    assert report.visible_player_duration_lower_seconds == Fraction(1, 1)
    assert report.visible_player_duration_upper_seconds == Fraction(3, 1)
    assert report.marker_collision_uncertain_duration_seconds == Fraction(2, 1)
    assert report.unknown_identity_duration_seconds == Fraction(3, 1)


def test_mixed_class_and_collision_dispositions_keep_class_bounds(tmp_path) -> None:
    manifest, observations = _source()
    player = SourcePlayerReferenceObservation.model_validate(
        {
            **observations[0].model_dump(),
            "marker_collision_resolution": "unresolved",
            "marker_collision_evidence": ["mixed_class_overlap"],
        }
    )
    uncertain = SourcePlayerReferenceObservation.model_validate(
        {
            **observations[0].model_dump(),
            "annotation_id": "uncertain-class",
            "marker_class": "class_uncertain",
            "marker_collision_resolution": "unresolved",
            "marker_collision_evidence": ["mixed_class_overlap"],
        }
    )
    non_player = SourcePlayerReferenceObservation.model_validate(
        {
            **observations[0].model_dump(),
            "annotation_id": "non-player",
            "marker_class": "non_player",
            "marker_collision_resolution": "reviewed_distinct",
            "marker_collision_evidence": ["reviewed_non_player_collision"],
        }
    )
    report = _score(tmp_path, manifest, [player, uncertain, non_player], [], [])
    assert report.visible_player_duration_lower_seconds == Fraction(1, 1)
    assert report.visible_player_duration_upper_seconds == Fraction(2, 1)
    assert report.class_uncertain_duration_seconds == Fraction(1, 1)
    assert report.marker_collision_uncertain_duration_seconds == 0


def test_many_to_one_candidate_projection_marks_all_source_labels_ambiguous(tmp_path) -> None:
    manifest, observations = _source()
    second = SourcePlayerReferenceObservation.model_validate(
        {
            **observations[0].model_dump(),
            "annotation_id": "local-2",
            "bbox": (0.18, 0.1, 0.2, 0.2),
        }
    )
    rows = [*observations, second]
    reference = _frozen_reference(tmp_path, manifest, rows)
    candidate = _candidate(manifest, 0, "shared", bbox=(0.14, 0.1, 0.2, 0.2))
    joins = join_reference_candidates(
        reference,
        [candidate],
        expected_reference_digest=reference.digest,
        expected_development_reference_digest=manifest.join_protocol.development_reference_digest,
        expected_raw_candidate_digest=raw_candidate_sha256([candidate]),
        candidate_run_digest="c" * 64,
    )
    assert [join.status for join in joins] == ["ambiguous", "ambiguous"]
    assert all(join.candidate_id is None for join in joins)


def test_geometry_artifact_replay_rejects_forged_ghost_candidate(tmp_path) -> None:
    manifest, rows = _source()
    reference = _frozen_reference(tmp_path / "reference", manifest, rows)
    candidate = _candidate(manifest, 0, "real")
    expected_raw = raw_candidate_sha256([candidate])
    generated = join_reference_candidates(
        reference,
        [candidate],
        expected_reference_digest=reference.digest,
        expected_development_reference_digest=reference.manifest.join_protocol.development_reference_digest,
        expected_raw_candidate_digest=expected_raw,
        candidate_run_digest="c" * 64,
    )
    forged = [generated[0].model_copy(update={"candidate_id": "ghost"})]
    reviews = [
        SourceJoinReview(
            annotation_id="local-1",
            disposition="matched",
            candidate_id="ghost",
            primary_reviewer_id="ra",
            independent_reviewer_id="rb",
            adjudicator_id="rc",
            evidence=["forged"],
            review_scope="source_candidate_geometry_only",
        )
    ]
    with pytest.raises(ValueError, match="does not replay"):
        freeze_source_join_artifact(
            tmp_path / "join.json",
            reference,
            [candidate],
            forged,
            reviews,
            expected_reference_digest=reference.digest,
            expected_development_reference_digest=reference.manifest.join_protocol.development_reference_digest,
            expected_raw_candidate_digest=expected_raw,
            candidate_run_digest="c" * 64,
        )


def test_rehashed_join_envelope_cannot_lie_about_frozen_protocol(tmp_path) -> None:
    manifest, rows = _source()
    reference = _frozen_reference(tmp_path / "reference", manifest, rows)
    candidates = [_candidate(manifest, 0, "c1")]
    artifact, raw_digest = _reviewed_join(tmp_path, reference, candidates)
    forged = artifact.model_copy(update={"join_protocol_digest": "d" * 64})
    payload = forged.model_dump(mode="json")
    payload.pop("digest")
    forged_digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    forged = forged.model_copy(update={"digest": forged_digest})
    forged_path = tmp_path / "forged-join.json"
    forged_path.write_bytes(
        json.dumps(
            forged.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
        + b"\n"
    )
    with pytest.raises(ValueError, match="protocol differs from frozen reference"):
        read_frozen_source_join_artifact(
            forged_path,
            expected_join_digest=forged_digest,
            expected_reference_digest=reference.digest,
            expected_raw_candidate_digest=raw_digest,
            expected_join_protocol_digest=join_protocol_sha256(manifest.join_protocol),
        )
    with pytest.raises(ValueError, match="protocol differs from frozen reference"):
        validate_frozen_source_join_artifact(
            forged,
            reference,
            candidates,
            expected_join_digest=forged_digest,
            expected_reference_digest=reference.digest,
            expected_development_reference_digest=manifest.join_protocol.development_reference_digest,
            expected_raw_candidate_digest=raw_digest,
        )


def test_join_protocol_is_pinned_in_source_reference(tmp_path) -> None:
    manifest, rows = _source()
    reference = _frozen_reference(tmp_path, manifest, rows)
    altered_manifest = manifest.model_copy(
        update={"join_protocol": manifest.join_protocol.model_copy(update={"threshold_iou": 0.9})}
    )
    altered = reference.model_copy(update={"manifest": altered_manifest})
    with pytest.raises(ValueError, match="externally pinned digest"):
        join_reference_candidates(
            altered,
            [],
            expected_reference_digest=reference.digest,
            expected_development_reference_digest=reference.manifest.join_protocol.development_reference_digest,
            expected_raw_candidate_digest=raw_candidate_sha256([]),
            candidate_run_digest="c" * 64,
        )


def test_split_allocation_rejects_renamed_source_interval_overlap() -> None:
    source_hash = "a" * 64
    records = _allocation(source_hash).rounds
    overlapping_renamed_test = records[-1].model_copy(update={"round_id": "renamed-test"})
    with pytest.raises(ValidationError, match="overlap or reuse"):
        SourceSplitAllocation(rounds=[*records, overlapping_renamed_test])


def test_duplicate_round_identity_cannot_inflate_split_counts() -> None:
    records = list(_allocation("a" * 64).rounds)
    duplicate_round = records[0].model_copy(
        update={
            "start_frame_index": 100,
            "end_frame_index": 103,
            "start_source_pts": 20_000,
            "end_source_pts": 20_030,
        }
    )
    with pytest.raises(ValidationError, match="duplicate active round identity"):
        SourceSplitAllocation(rounds=[*records, duplicate_round])


def test_test_reuse_must_be_retired_not_reallocated() -> None:
    records = list(_allocation("a" * 64).rounds)
    records[-1] = records[-1].model_copy(update={"prior_exposure": "development"})
    with pytest.raises(ValidationError, match="prior exposure"):
        SourceSplitAllocation(rounds=records)


def test_uncertain_class_exposes_denominator_sensitivity_and_blocks_target(tmp_path) -> None:
    manifest, rows = _source()
    uncertain = SourcePlayerReferenceObservation.model_validate(
        {
            **rows[0].model_dump(),
            "annotation_id": "uncertain-class",
            "marker_class": "class_uncertain",
            "bbox": (0.6, 0.6, 0.1, 0.1),
        }
    )
    known = SourcePlayerReferenceObservation.model_validate(
        {
            **rows[0].model_dump(),
            "expected_player_id": "p1",
            "identity_confidence": 0.9,
            "identity_evidence": ["source_name_plate_link"],
        }
    )
    report = _score(
        tmp_path,
        manifest,
        [known, uncertain],
        [_candidate(manifest, 0, "c1", bbox=known.bbox)],
        [_prediction(manifest, 0, "c1", "p1")],
    )
    assert report.visible_player_duration_lower_seconds == Fraction(1, 1)
    assert report.visible_player_duration_upper_seconds == Fraction(2, 1)
    assert report.correct_fraction_lower_bound == pytest.approx(0.5)
    assert report.correct_fraction_upper_bound == pytest.approx(1.0)
    assert report.computable and not report.target_eligible


def test_sparse_switches_report_excluded_transitions_and_no_full_stability(tmp_path) -> None:
    manifest, rows = _source()
    first = SourcePlayerReferenceObservation.model_validate(
        {
            **rows[0].model_dump(),
            "expected_player_id": "p1",
            "identity_confidence": 0.9,
            "identity_evidence": ["source_name_plate_link"],
        }
    )
    second = SourcePlayerReferenceObservation.model_validate(
        {
            **first.model_dump(),
            "annotation_id": "later",
            "frame_index": 2,
            "source_pts": 1_020,
            "interval_end_source_pts": 1_030,
            "continuity_before": "unsupported_gap",
            "continuity_evidence": ["sparse_source_gap"],
        }
    )
    predictions = [_prediction(manifest, 0, "c1", "p1"), _prediction(manifest, 2, "c2", "p2")]
    report = _score(
        tmp_path,
        manifest,
        [first, second],
        [_candidate(manifest, 0, "c1"), _candidate(manifest, 2, "c2")],
        predictions,
    )
    assert report.switch_count == 0
    assert report.eligible_transition_count == 0
    assert report.excluded_transition_count == 1
    assert report.stability_scope == "no_eligible_transitions"
    assert not report.target_eligible


def test_unknown_identity_intervals_prevent_full_stability_scope(tmp_path) -> None:
    manifest, rows = _source()
    first = SourcePlayerReferenceObservation.model_validate(
        {
            **rows[0].model_dump(),
            "expected_player_id": "p1",
            "identity_confidence": 0.9,
            "identity_evidence": ["source_name_plate_link"],
        }
    )
    second = SourcePlayerReferenceObservation.model_validate(
        {
            **first.model_dump(),
            "annotation_id": "known-next",
            "frame_index": 1,
            "source_pts": 1_010,
            "interval_end_source_pts": 1_020,
        }
    )
    unknown = SourcePlayerReferenceObservation.model_validate(
        {
            **rows[0].model_dump(),
            "annotation_id": "unknown-next",
            "frame_index": 2,
            "source_pts": 1_020,
            "interval_end_source_pts": 1_030,
            "bbox": (0.6, 0.6, 0.1, 0.1),
        }
    )
    report = _score(
        tmp_path,
        manifest,
        [first, second, unknown],
        [
            _candidate(manifest, 0, "c1"),
            _candidate(manifest, 1, "c2"),
            _candidate(manifest, 2, "c3", bbox=unknown.bbox),
        ],
        [
            _prediction(manifest, 0, "c1", "p1"),
            _prediction(manifest, 1, "c2", "p1"),
            _prediction(manifest, 2, "c3", "p3"),
        ],
    )
    assert report.eligible_transition_count == 1
    assert report.unassessed_unknown_identity_count == 1
    assert report.unassessed_unknown_identity_duration_seconds == Fraction(1, 1)
    assert report.continuity_coverage == pytest.approx(0.5)
    assert report.stability_scope == "partial_continuity"
    assert not report.target_eligible


def test_continuous_switch_needs_evidence_and_is_counted(tmp_path) -> None:
    manifest, rows = _source()
    first = SourcePlayerReferenceObservation.model_validate(
        {
            **rows[0].model_dump(),
            "expected_player_id": "p1",
            "identity_confidence": 0.9,
            "identity_evidence": ["source_name_plate_link"],
        }
    )
    second = SourcePlayerReferenceObservation.model_validate(
        {
            **first.model_dump(),
            "annotation_id": "next",
            "frame_index": 1,
            "source_pts": 1_010,
            "interval_end_source_pts": 1_020,
        }
    )
    with pytest.raises(ValidationError, match="continuity_evidence"):
        SourcePlayerReferenceObservation.model_validate(
            {
                **second.model_dump(),
                "continuity_evidence": [],
            }
        )
    report = _score(
        tmp_path,
        manifest,
        [first, second],
        [_candidate(manifest, 0, "c1"), _candidate(manifest, 1, "c2")],
        [_prediction(manifest, 0, "c1", "p1"), _prediction(manifest, 1, "c2", "p2")],
    )
    assert report.switch_count == 1
    assert report.eligible_transition_count == 1


def test_persisted_prediction_rows_must_match_run_manifest_header(tmp_path) -> None:
    manifest, rows = _source()
    reference = _frozen_reference(tmp_path / "reference", manifest, rows)
    candidates = [_candidate(manifest, 0, "c1")]
    join_artifact, _ = _reviewed_join(tmp_path, reference, candidates)
    row = _prediction(manifest, 0, "c1", "p1", run_digest="f" * 64)
    output_path, run_path, output_sha, manifest_sha, _ = _prediction_provenance_files(
        tmp_path,
        reference,
        join_artifact,
        [row],
        header_run_digest="e" * 64,
        manifest_run_digest="e" * 64,
    )
    with pytest.raises(ValueError, match="row run digest disagrees with output header"):
        freeze_source_prediction_artifact(
            tmp_path / "frozen-predictions.json",
            reference,
            join_artifact,
            output_path,
            run_path,
            expected_reference_digest=reference.digest,
            expected_development_reference_digest=manifest.join_protocol.development_reference_digest,
            expected_join_digest=join_artifact.digest,
            expected_prediction_output_sha256=output_sha,
            expected_run_manifest_sha256=manifest_sha,
            expected_prediction_run_digest="e" * 64,
            expected_configuration_digest="3" * 64,
            expected_code_digest="4" * 64,
        )


def test_prediction_readback_and_validation_crossbind_original_output_bytes(tmp_path) -> None:
    (
        manifest,
        reference,
        join_artifact,
        candidates,
        raw_digest,
        output_path,
        run_manifest_path,
        output_sha,
        manifest_sha,
        run_digest,
        frozen_path,
        artifact,
    ) = _frozen_prediction_case(tmp_path)
    forged_predictions = [
        artifact.predictions[0].model_copy(update={"assigned_player_id": "p1"})
    ]
    forged_payload = artifact.model_dump(mode="json")
    forged_payload["predictions"] = [row.model_dump(mode="json") for row in forged_predictions]
    forged_payload.pop("digest")
    forged_digest = hashlib.sha256(
        json.dumps(
            forged_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    forged = artifact.model_copy(
        update={"predictions": forged_predictions, "digest": forged_digest}
    )
    frozen_path.write_bytes(
        json.dumps(
            {**forged_payload, "digest": forged_digest},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
        + b"\n"
    )
    read_pins = {
        "expected_prediction_digest": forged_digest,
        "expected_prediction_output_sha256": output_sha,
        "expected_run_manifest_sha256": manifest_sha,
        "expected_prediction_run_digest": run_digest,
        "expected_configuration_digest": "3" * 64,
        "expected_code_digest": "4" * 64,
        "expected_reference_digest": reference.digest,
        "expected_join_digest": join_artifact.digest,
        "expected_source_video_sha256": manifest.source_video_sha256,
        "expected_candidate_run_digest": join_artifact.candidate_run_digest,
    }
    with pytest.raises(ValueError, match="frozen predictions differ"):
        read_frozen_source_prediction_artifact(
            frozen_path, output_path, run_manifest_path, **read_pins
        )
    validation_pins = {
        key: value
        for key, value in read_pins.items()
        if key not in {"expected_candidate_run_digest", "expected_source_video_sha256"}
    }
    validation_pins["expected_development_reference_digest"] = (
        manifest.join_protocol.development_reference_digest
    )
    with pytest.raises(ValueError, match="frozen predictions differ"):
        validate_prediction_artifact(
            forged,
            reference,
            join_artifact,
            output_path,
            run_manifest_path,
            **validation_pins,
        )
    with pytest.raises(ValueError, match="frozen predictions differ"):
        evaluate_source_reference(
            reference,
            join_artifact,
            candidates,
            frozen_path,
            output_path,
            run_manifest_path,
            expected_reference_digest=reference.digest,
            expected_development_reference_digest=manifest.join_protocol.development_reference_digest,
            expected_join_digest=join_artifact.digest,
            expected_raw_candidate_digest=raw_digest,
            expected_prediction_digest=forged_digest,
            expected_prediction_output_sha256=output_sha,
            expected_run_manifest_sha256=manifest_sha,
            expected_prediction_run_digest=run_digest,
            expected_configuration_digest="3" * 64,
            expected_code_digest="4" * 64,
        )


def test_prediction_readback_rejects_rehashed_wrong_row_run_digest(tmp_path) -> None:
    (
        manifest,
        reference,
        join_artifact,
        _candidates,
        _raw_digest,
        output_path,
        run_manifest_path,
        output_sha,
        manifest_sha,
        run_digest,
        frozen_path,
        artifact,
    ) = _frozen_prediction_case(tmp_path)
    wrong_rows = [artifact.predictions[0].model_copy(update={"prediction_run_digest": "f" * 64})]
    payload = artifact.model_dump(mode="json")
    payload["predictions"] = [row.model_dump(mode="json") for row in wrong_rows]
    payload.pop("digest")
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    frozen_path.write_bytes(
        json.dumps(
            {**payload, "digest": digest},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
        + b"\n"
    )
    with pytest.raises(ValueError, match="frozen predictions differ"):
        read_frozen_source_prediction_artifact(
            frozen_path,
            output_path,
            run_manifest_path,
            expected_prediction_digest=digest,
            expected_prediction_output_sha256=output_sha,
            expected_run_manifest_sha256=manifest_sha,
            expected_prediction_run_digest=run_digest,
            expected_configuration_digest="3" * 64,
            expected_code_digest="4" * 64,
            expected_reference_digest=reference.digest,
            expected_join_digest=join_artifact.digest,
            expected_source_video_sha256=manifest.source_video_sha256,
            expected_candidate_run_digest=join_artifact.candidate_run_digest,
        )


def test_prediction_output_and_run_manifest_require_external_hash_pins(tmp_path) -> None:
    manifest, rows = _source()
    reference = _frozen_reference(tmp_path / "reference", manifest, rows)
    candidates = [_candidate(manifest, 0, "c1")]
    join_artifact, _ = _reviewed_join(tmp_path, reference, candidates)
    output_path, run_path, output_sha, manifest_sha, _ = _prediction_provenance_files(
        tmp_path,
        reference,
        join_artifact,
        [_prediction(manifest, 0, "c1", "p1")],
    )
    with pytest.raises(ValueError, match="persisted prediction output SHA-256 mismatch"):
        freeze_source_prediction_artifact(
            tmp_path / "frozen-predictions.json",
            reference,
            join_artifact,
            output_path,
            run_path,
            expected_reference_digest=reference.digest,
            expected_development_reference_digest=manifest.join_protocol.development_reference_digest,
            expected_join_digest=join_artifact.digest,
            expected_prediction_output_sha256="0" * 64,
            expected_run_manifest_sha256=manifest_sha,
            expected_prediction_run_digest="e" * 64,
            expected_configuration_digest="3" * 64,
            expected_code_digest="4" * 64,
        )


def test_prediction_artifact_requires_external_pin_and_provenance(tmp_path) -> None:
    manifest, rows = _source()
    reference = _frozen_reference(tmp_path / "reference", manifest, rows)
    candidates = [_candidate(manifest, 0, "c1")]
    join_artifact, raw_digest = _reviewed_join(tmp_path, reference, candidates)
    output_path, run_path, output_sha, manifest_sha, run_digest = _prediction_provenance_files(
        tmp_path,
        reference,
        join_artifact,
        [_prediction(manifest, 0, "c1", "p1")],
    )
    prediction_path = tmp_path / "frozen-predictions.json"
    freeze_source_prediction_artifact(
        prediction_path,
        reference,
        join_artifact,
        output_path,
        run_path,
        expected_reference_digest=reference.digest,
        expected_development_reference_digest=manifest.join_protocol.development_reference_digest,
        expected_join_digest=join_artifact.digest,
        expected_prediction_output_sha256=output_sha,
        expected_run_manifest_sha256=manifest_sha,
        expected_prediction_run_digest=run_digest,
        expected_configuration_digest="3" * 64,
        expected_code_digest="4" * 64,
    )
    with pytest.raises(ValueError, match="externally pinned digest"):
        evaluate_source_reference(
            reference,
            join_artifact,
            candidates,
            prediction_path,
            output_path,
            run_path,
            expected_reference_digest=reference.digest,
            expected_development_reference_digest=manifest.join_protocol.development_reference_digest,
            expected_join_digest=join_artifact.digest,
            expected_raw_candidate_digest=raw_digest,
            expected_prediction_digest="0" * 64,
            expected_prediction_output_sha256=output_sha,
            expected_run_manifest_sha256=manifest_sha,
            expected_prediction_run_digest=run_digest,
            expected_configuration_digest="3" * 64,
            expected_code_digest="4" * 64,
        )


def test_directory_descriptor_persistence_rejects_symlink_components(tmp_path) -> None:
    import os

    from valoscribe.tracking.source_reference import _write_artifact

    outside = tmp_path / "outside"
    outside.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        _write_artifact(linked, "artifact.json", {"digest": "test"})
    assert not (outside / "artifact.json").exists()
    assert hasattr(os, "O_NOFOLLOW")


def test_legacy_identity_evaluator_semantics_remain_covered() -> None:
    from valoscribe.tracking.artifacts import evaluate_identity_labels
    from valoscribe.types.persistent import TrackIdentityLabel, TrackIdentityPrediction

    label = TrackIdentityLabel(
        match_id="m",
        round_id="r",
        vod_timestamp_s=1.0,
        candidate_id="c",
        expected_player_id="p1",
        visible=True,
    )
    prediction = TrackIdentityPrediction(
        match_id="m", round_id="r", vod_timestamp_s=1.0, candidate_id="c", assigned_player_id="p1"
    )
    assert evaluate_identity_labels([label], [prediction]).identity_accuracy == 1.0
