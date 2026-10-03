"""Evidence-linked deterministic summaries for observed team-shape samples."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from valoscribe.tactical.config import TacticalConfig
from valoscribe.tactical.contracts import AggregateMovementSummary, RoundMovementSummary

Coverage = Literal["good", "partial", "unknown", "excluded"]
MACROS = ("A", "MID", "B", "SPAWN", "OTHER")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _usable(row: dict[str, Any]) -> bool:
    return row["coverage_status"] in {"good", "partial"}


def _counts(row: dict[str, Any]) -> dict[str, int]:
    counts = row.get("macro_counts") or {}
    return {macro: int(counts.get(macro, 0)) for macro in MACROS}


def _distribution(counts: dict[str, int]) -> str:
    return "/".join(str(counts[key]) for key in ("A", "MID", "B"))


def _coverage_evidence(rows: list[dict[str, Any]]) -> dict[str, Any]:
    reviewed = sum(row["coverage_status"] == "good" for row in rows)
    return {
        "coverage_numerator": len(rows),
        "coverage_denominator": len(rows),
        "reviewed_sample_count": reviewed,
        "confidence": "reviewed_samples" if reviewed == len(rows) else "candidate_partial_coverage",
        "start_timestamp_seconds": float(rows[0]["source_timestamp_seconds"]),
        "end_timestamp_seconds": float(rows[-1]["source_timestamp_seconds"]),
        "sample_indices": [int(row["sample_index"]) for row in rows],
    }


def _evidence(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "timestamp_seconds": float(row["source_timestamp_seconds"]),
        "sample_index": int(row["sample_index"]),
        "observed_marker_count": int(row["observed_marker_count"]),
        "macro_counts": _counts(row),
        "coverage_status": row["coverage_status"],
        "source": "corrected" if row.get("corrected") else "raw_candidate",
    }


def _runs(
    rows: list[dict[str, Any]], *, sample_period: float, include_unusable: bool = False
) -> list[list[dict[str, Any]]]:
    runs: list[list[dict[str, Any]]] = []
    for row in sorted(rows, key=lambda item: float(item["source_timestamp_seconds"])):
        if not include_unusable and not _usable(row):
            continue
        if (
            not runs
            or float(row["source_timestamp_seconds"])
            - float(runs[-1][-1]["source_timestamp_seconds"])
            > sample_period * 1.6
        ):
            runs.append([row])
        elif include_unusable and row["coverage_status"] != runs[-1][-1]["coverage_status"]:
            runs.append([row])
        else:
            runs[-1].append(row)
    return runs


def _persisted(
    run: list[dict[str, Any]], predicate, duration: float
) -> list[dict[str, Any]] | None:
    if not run or not predicate(run[0]):
        return None
    streak: list[dict[str, Any]] = []
    for row in run:
        if predicate(row):
            streak.append(row)
            elapsed = float(streak[-1]["source_timestamp_seconds"]) - float(
                streak[0]["source_timestamp_seconds"]
            )
            if elapsed + 1e-6 >= duration:
                return streak
        else:
            return None
    return None


def build_round_summary(
    round_id: str,
    round_config,
    config: TacticalConfig,
    occupancy: list[dict[str, Any]],
    *,
    report_root: Path,
    map_data: dict[str, Any],
) -> RoundMovementSummary:
    period = 1.0 / config.run.sample_fps
    live_start = round_config.source_start_seconds + round_config.live_start_offset_seconds
    opening_window_rows: list[dict[str, Any]] = []
    opening_usable_seconds = 0.0
    for row in sorted(occupancy, key=lambda item: float(item["source_timestamp_seconds"])):
        if float(row["source_timestamp_seconds"]) < live_start:
            continue
        opening_window_rows.append(row)
        if _usable(row):
            opening_usable_seconds += period
        if opening_usable_seconds + 1e-6 >= config.run.opening_window_seconds:
            break
    opening_rows = [row for row in opening_window_rows if _usable(row)]
    opening_counts: Counter[tuple[int, int, int]] = Counter(
        (_counts(row)["A"], _counts(row)["MID"], _counts(row)["B"]) for row in opening_rows
    )
    opening = (
        max(opening_counts, key=lambda key: (opening_counts[key], key)) if opening_counts else None
    )
    usable_seconds = sum(1 / config.run.sample_fps for row in occupancy if _usable(row))
    unknown_intervals: list[dict[str, Any]] = []
    ordered_occupancy = sorted(occupancy, key=lambda row: float(row["source_timestamp_seconds"]))
    for before, after in zip(ordered_occupancy, ordered_occupancy[1:]):
        before_time = float(before["source_timestamp_seconds"])
        after_time = float(after["source_timestamp_seconds"])
        if after_time - before_time > period * 1.6:
            unknown_intervals.append(
                {
                    "start_seconds": before_time + period,
                    "end_seconds": after_time,
                    "status": "unknown",
                    "reason": "sample timestamp discontinuity",
                }
            )
    excluded = [row for row in occupancy if row["coverage_status"] in {"unknown", "excluded"}]
    for run in _runs(excluded, sample_period=period, include_unusable=True):
        unknown_intervals.append(
            {
                "start_seconds": float(run[0]["source_timestamp_seconds"]),
                "end_seconds": float(run[-1]["source_timestamp_seconds"]) + period,
                "status": run[0]["coverage_status"],
            }
        )

    observed_runs = _runs(occupancy, sample_period=period)
    shift: dict[str, Any] | None = None
    regroup: dict[str, Any] | None = None
    commitment: dict[str, Any] | None = None
    target_zones = map_data.get("commitment_zones", {"A": [], "B": []})
    site_targets = {macro for macro, zones in target_zones.items() if zones}
    for run in observed_runs:
        if len(run) < 2:
            continue
        for index, candidate in enumerate(run):
            timestamp = float(candidate["source_timestamp_seconds"])
            prior = [
                row
                for row in run[:index]
                if timestamp - config.run.stable_prior_window_seconds
                <= float(row["source_timestamp_seconds"])
                < timestamp
            ]
            prior_span = (
                float(prior[-1]["source_timestamp_seconds"])
                - float(prior[0]["source_timestamp_seconds"])
                if prior
                else 0.0
            )
            if prior_span + period < config.run.stable_prior_window_seconds:
                continue
            prior_vectors = [_counts(row) for row in prior]
            if any(
                max(vector[macro] for vector in prior_vectors)
                - min(vector[macro] for vector in prior_vectors)
                > 1
                for macro in MACROS
            ):
                continue
            old_counts = {
                macro: round(sum(vector[macro] for vector in prior_vectors) / len(prior_vectors))
                for macro in MACROS
            }
            new_counts = _counts(candidate)
            increased = [
                macro
                for macro in ("A", "MID", "B")
                if new_counts[macro] - old_counts[macro] >= config.run.major_shift_min_increase
            ]
            for macro in increased:
                should_record_shift = shift is None
                should_record_regroup = regroup is None and macro in {"A", "B"}
                if not should_record_shift and not should_record_regroup:
                    continue
                stable = _persisted(
                    run[index:],
                    lambda row, m=macro, baseline=old_counts[macro]: _counts(row)[m] - baseline
                    >= config.run.major_shift_min_increase,
                    config.run.shift_persistence_seconds,
                )
                if not stable:
                    continue
                if shift is None:
                    shift = {
                        "direction": macro,
                        "before": _evidence(prior[-1]),
                        "baseline_window": _coverage_evidence(prior),
                        "after": _evidence(stable[-1]),
                        "persistence_window": _coverage_evidence(stable),
                    }
                if should_record_regroup and regroup is None:
                    regroup = {
                        "direction": macro,
                        "evidence": _evidence(stable[-1]),
                        "persistence_window": _coverage_evidence(stable),
                    }
            if shift is not None and regroup is not None:
                break
        for index, candidate in enumerate(run):
            if commitment is not None:
                break
            n = int(candidate["observed_marker_count"])
            if n <= 0:
                continue
            eligible_sites = [
                site
                for site in site_targets
                if sum(
                    (candidate.get("zone_counts") or {}).get(zone, 0) for zone in target_zones[site]
                )
                >= 3
                and sum(
                    (candidate.get("zone_counts") or {}).get(zone, 0) for zone in target_zones[site]
                )
                / n
                >= 0.60
            ]
            if not eligible_sites:
                continue
            site = sorted(eligible_sites)[0]
            stable = _persisted(
                run[index:],
                lambda row, selected=site: (
                    int(row["observed_marker_count"]) > 0
                    and sum(
                        (row.get("zone_counts") or {}).get(zone, 0)
                        for zone in target_zones[selected]
                    )
                    >= 3
                    and sum(
                        (row.get("zone_counts") or {}).get(zone, 0)
                        for zone in target_zones[selected]
                    )
                    / int(row["observed_marker_count"])
                    >= 0.60
                ),
                config.run.commitment_persistence_seconds,
            )
            if stable:
                confirm_end = (
                    float(stable[-1]["source_timestamp_seconds"])
                    + config.run.commitment_reversal_guard_seconds
                )
                guard_seconds = config.run.commitment_reversal_guard_seconds
                confirmation = []
                if guard_seconds > 0:
                    stable_end = float(stable[-1]["source_timestamp_seconds"])
                    for row in run:
                        row_time = float(row["source_timestamp_seconds"])
                        if row_time < stable_end:
                            continue
                        confirmation.append(row)
                        if row_time >= confirm_end - 1e-6:
                            break
                confirmed_through = (
                    (
                        bool(confirmation)
                        and float(confirmation[0]["source_timestamp_seconds"])
                        <= float(stable[-1]["source_timestamp_seconds"]) + 1e-6
                        and float(confirmation[-1]["source_timestamp_seconds"])
                        >= confirm_end - 1e-6
                    )
                    if guard_seconds > 0
                    else True
                )
                if not confirmed_through:
                    continue
                opposite = "B" if site == "A" else "A"
                selected_site_held = all(
                    int(row["observed_marker_count"]) > 0
                    and sum(
                        (row.get("zone_counts") or {}).get(zone, 0) for zone in target_zones[site]
                    )
                    >= 3
                    and sum(
                        (row.get("zone_counts") or {}).get(zone, 0) for zone in target_zones[site]
                    )
                    / int(row["observed_marker_count"])
                    >= 0.60
                    for row in confirmation
                )
                if not selected_site_held:
                    continue
                strongly_covered = all(
                    row["coverage_status"] == "good"
                    and config.run.strong_coverage_marker_count
                    <= int(row["observed_marker_count"])
                    <= 5
                    for row in [*stable, *confirmation]
                )
                presence = (
                    "present"
                    if any(_counts(row)[opposite] > 0 for row in stable)
                    else "not_observed"
                    if strongly_covered
                    else "unknown"
                )
                commitment = {
                    "site": site,
                    "evidence": _evidence(stable[-1]),
                    "persistence_window": _coverage_evidence(stable),
                    "reversal_check_window": (
                        _coverage_evidence(confirmation)
                        if confirmation
                        else {"disabled": True, "duration_seconds": 0.0, "sample_indices": []}
                    ),
                    "opposite_side_presence": presence,
                    "opposite_side_evidence": [
                        _evidence(row) for row in stable if _counts(row)[opposite] > 0
                    ]
                    or [_evidence(row) for row in stable],
                }
                break
        if shift is not None and regroup is not None and commitment is not None:
            break

    opening_confidence = (
        "candidate_partial_coverage"
        if opening_rows and any(row["coverage_status"] == "partial" for row in opening_rows)
        else "reviewed_coverage"
        if opening_rows
        else "unknown"
    )
    all_opening_samples = opening_window_rows
    if not opening_rows:
        opening_confidence = "unknown"
    opening_representative = next(
        (
            row
            for row in opening_rows
            if tuple(_counts(row)[key] for key in ("A", "MID", "B")) == opening
        ),
        None,
    )
    return RoundMovementSummary(
        run_id=config.run.run_id,
        round_id=round_id,
        selected_team=config.team.name,
        side=round_config.side,
        source_interval_seconds=(
            round_config.source_start_seconds,
            round_config.source_end_seconds,
        ),
        live_start_seconds=live_start,
        usable_time_seconds=usable_seconds,
        opening_distribution=(
            {"A": opening[0], "MID": opening[1], "B": opening[2]} if opening else None
        ),
        opening_observed_samples=len(opening_rows),
        opening_sample_denominator=len(all_opening_samples),
        opening_confidence=opening_confidence,
        opening_completeness="unknown",
        opening_evidence={
            "modal_sample_count": opening_counts[opening] if opening else 0,
            "usable_sample_count": len(opening_rows),
            "coverage_numerator": len(opening_rows),
            "coverage_denominator": len(all_opening_samples),
            "samples": [_evidence(row) for row in opening_rows],
        },
        first_major_shift_time=(shift["after"]["timestamp_seconds"] if shift else None),
        first_major_shift_direction=shift["direction"] if shift else None,
        first_major_shift_evidence=shift,
        regroup_direction=regroup["direction"] if regroup else None,
        regroup_evidence=regroup["evidence"] if regroup else None,
        apparent_commitment_site=commitment["site"] if commitment else None,
        apparent_commitment_time=(
            commitment["evidence"]["timestamp_seconds"] if commitment else None
        ),
        commitment_evidence=(
            {
                "sample": commitment["evidence"],
                "persistence_window": commitment["persistence_window"],
                "reversal_check_window": commitment["reversal_check_window"],
            }
            if commitment
            else None
        ),
        opposite_side_presence=(commitment["opposite_side_presence"] if commitment else "unknown"),
        opposite_side_evidence=(commitment["opposite_side_evidence"] if commitment else []),
        representative_timestamps=(
            [_evidence(opening_representative)] if opening_representative else []
        )
        + ([shift["after"]] if shift else []),
        unknown_intervals=unknown_intervals,
        coverage_numerator=len(opening_rows),
        coverage_denominator=len(all_opening_samples),
        warnings=(
            (
                [
                    "Partial candidate observations do not establish complete-team occupancy.",
                    "Map calibration and detector remain pending human review.",
                ]
                if opening_confidence == "candidate_partial_coverage"
                else []
            )
            + (
                [
                    "Observed marker count exceeded the selected-team roster size of five; "
                    "over-count samples cannot establish strong absence evidence."
                ]
                if any(int(row["observed_marker_count"]) > 5 for row in occupancy)
                else []
            )
        ),
        rule_configuration={
            "opening_window_seconds": config.run.opening_window_seconds,
            "stable_prior_window_seconds": config.run.stable_prior_window_seconds,
            "major_shift_min_increase": config.run.major_shift_min_increase,
            "shift_persistence_seconds": config.run.shift_persistence_seconds,
            "commitment_persistence_seconds": config.run.commitment_persistence_seconds,
            "commitment_reversal_guard_seconds": config.run.commitment_reversal_guard_seconds,
            "strong_coverage_marker_count": config.run.strong_coverage_marker_count,
            "commitment_zones": target_zones,
        },
        evidence_paths={
            "minimap_playback": "minimap_playback.mp4",
            "canonical_playback": "canonical_playback.mp4",
        },
    )


def _round_markdown(summary: RoundMovementSummary, occupancy: list[dict[str, Any]]) -> str:
    opening = summary.opening_distribution
    opening_text = (
        f"Observed macro distribution A/MID/B={opening['A']}/{opening['MID']}/{opening['B']} "
        f"({summary.opening_observed_samples}/"
        f"{summary.opening_sample_denominator} usable/total opening samples)."
        if opening
        else "Opening distribution: unknown; no usable opening samples."
    )
    shift_time = summary.first_major_shift_time
    commitment_time = summary.apparent_commitment_time
    shift_text = f"{shift_time:.2f}s" if shift_time is not None else "unknown"
    commitment_text = f"{commitment_time:.2f}s" if commitment_time is not None else "unknown"
    interval_start, interval_end = summary.source_interval_seconds
    source_interval = f"{interval_start:.3f}–{interval_end:.3f}s"
    lines = [
        f"# Round movement summary: {summary.round_id}",
        "",
        f"- Team/side: {summary.selected_team} / {summary.side}.",
        f"- Source interval: {source_interval}; live start: {summary.live_start_seconds:.3f}s.",
        f"- Usable sampled time: {summary.usable_time_seconds:.2f}s.",
        f"- Opening: {opening_text}",
        f"- First sustained observed shift: "
        f"{summary.first_major_shift_direction or 'unknown'} at {shift_text}.",
        f"- Apparent commitment: "
        f"{summary.apparent_commitment_site or 'unknown'} at {commitment_text}.",
        f"- Opposite-side presence: {summary.opposite_side_presence}.",
        f"- Opening evidence confidence: {summary.opening_confidence}; "
        f"coverage {summary.coverage_numerator}/{summary.coverage_denominator}; "
        f"team completeness {summary.opening_completeness}.",
        f"- Playback: {summary.evidence_paths['minimap_playback']}; "
        f"{summary.evidence_paths['canonical_playback']}.",
        "",
        "## Evidence",
        "",
        "Opening evidence lists each included sample and its observed macro counts. Every event "
        "refers to an `occupancy.csv` sample. `summary.json` records sample indices, timestamps, "
        "coverage, source type, and persistence-window coverage.",
        "",
        "## Unknown / excluded intervals",
        "",
        json.dumps(summary.unknown_intervals, indent=2),
        "",
        "## Warnings",
        "",
        *(f"- {warning}" for warning in summary.warnings),
    ]
    return "\n".join(lines).rstrip() + "\n"


def write_round_report(
    round_dir: Path,
    round_id: str,
    round_config,
    config: TacticalConfig,
    occupancy: list[dict[str, Any]],
    map_data: dict[str, Any],
    *,
    report_root: Path | None = None,
    evidence_paths: dict[str, str] | None = None,
) -> RoundMovementSummary:
    target = report_root or round_dir
    target.mkdir(parents=True, exist_ok=True)
    summary = build_round_summary(
        round_id, round_config, config, occupancy, report_root=target, map_data=map_data
    )
    if evidence_paths is not None:
        summary.evidence_paths = evidence_paths
    (target / "summary.json").write_text(summary.model_dump_json(indent=2) + "\n", encoding="utf-8")
    (target / "summary.md").write_text(_round_markdown(summary, occupancy), encoding="utf-8")
    return summary


def write_aggregate_report(
    output_dir: Path,
    run_id: str,
    summaries: list[RoundMovementSummary],
    included_round_ids: list[str],
    excluded_round_ids: list[str],
    correction_counts: dict[str, int] | None = None,
    consumed_round_revisions: dict[str, str] | None = None,
) -> AggregateMovementSummary:
    output_dir.mkdir(parents=True, exist_ok=True)
    eligible = [item for item in summaries if item.round_id in included_round_ids]
    openings = Counter(
        "/".join(str(item.opening_distribution[key]) for key in ("A", "MID", "B"))
        for item in eligible
        if item.opening_distribution is not None
    )
    commitments = Counter(
        item.apparent_commitment_site for item in eligible if item.apparent_commitment_site
    )
    regroups = Counter(item.regroup_direction for item in eligible if item.regroup_direction)
    opposite: Counter[Literal["present", "not_observed", "unknown"]] = Counter(
        item.opposite_side_presence for item in eligible
    )
    summarized_ids = {item.round_id for item in eligible}
    missing_ids = set(included_round_ids) - summarized_ids
    unknown_by_feature = {
        "opening": sorted(
            missing_ids | {item.round_id for item in eligible if item.opening_distribution is None}
        ),
        "opening_completeness": sorted(
            missing_ids
            | {item.round_id for item in eligible if item.opening_completeness == "unknown"}
        ),
        "regroup": sorted(
            missing_ids | {item.round_id for item in eligible if item.regroup_direction is None}
        ),
        "commitment": sorted(
            missing_ids
            | {item.round_id for item in eligible if item.apparent_commitment_site is None}
        ),
        "opposite_side_presence": sorted(
            missing_ids
            | {item.round_id for item in eligible if item.opposite_side_presence == "unknown"}
        ),
    }
    unknown_ids = sorted({round_id for ids in unknown_by_feature.values() for round_id in ids})
    representatives = [
        {
            "round_id": item.round_id,
            "opening": item.representative_timestamps[:1],
            "shift": item.first_major_shift_evidence,
            "regroup": item.regroup_evidence,
            "commitment": item.commitment_evidence,
        }
        for item in eligible
        if item.opening_distribution or item.commitment_evidence
    ]
    commitment_buckets = Counter(
        int((item.apparent_commitment_time - item.live_start_seconds) // 10) * 10
        for item in eligible
        if item.apparent_commitment_time is not None
    )
    summary = AggregateMovementSummary(
        run_id=run_id,
        included_rounds=included_round_ids,
        excluded_rounds=excluded_round_ids,
        opening_pattern_counts=dict(openings),
        apparent_commitment_counts=dict(commitments),
        regroup_direction_counts=dict(regroups),
        opposite_side_presence_counts={key: count for key, count in opposite.items() if count},
        approximate_commitment_time_distribution={
            f"{start}-{start + 9}s": count for start, count in sorted(commitment_buckets.items())
        },
        recurring_patterns=[
            {"key": f"opening={key}", "count": count, "denominator": len(included_round_ids)}
            for key, count in sorted(openings.items())
        ]
        + [
            {"key": f"regroup={key}", "count": count, "denominator": len(included_round_ids)}
            for key, count in sorted(regroups.items())
        ],
        representative_rounds=representatives,
        feature_unknown_round_ids=unknown_ids,
        feature_unknown_by_feature=unknown_by_feature,
        correction_counts_by_round=correction_counts
        or {round_id: 0 for round_id in included_round_ids},
        consumed_round_revisions=consumed_round_revisions or {},
        pattern_denominators={
            "included_round_count": len(included_round_ids),
            "opening_known_round_count": sum(openings.values()),
            "opening_completeness_known_round_count": sum(
                item.opening_completeness == "affirmed" for item in eligible
            ),
            "regroup_known_round_count": sum(regroups.values()),
            "commitment_known_round_count": sum(commitments.values()),
            "opposite_presence_round_count": opposite["present"] + opposite["not_observed"],
        },
        limitations=[
            "Counts describe observed candidate occupancy, not complete rosters or tactical intent."
        ],
    )
    (output_dir / "summary.json").write_text(
        summary.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        f"# Aggregate movement summary: {run_id}",
        "",
        f"Included rounds ({len(included_round_ids)}): {', '.join(included_round_ids) or 'none'}.",
        f"Excluded rounds ({len(excluded_round_ids)}): {', '.join(excluded_round_ids) or 'none'}.",
        f"Opening known denominator: {sum(openings.values())}/{len(included_round_ids)}; "
        f"feature unknown: {', '.join(unknown_ids) or 'none'}.",
        *(
            f"{feature} unknown: {', '.join(ids) or 'none'}."
            for feature, ids in sorted(unknown_by_feature.items())
        ),
        "",
        "## Correction counts",
        "",
        *(
            f"- {round_id}: {count}."
            for round_id, count in sorted(summary.correction_counts_by_round.items())
        ),
        "",
        "## Observed pattern keys",
        "",
    ]
    lines += [
        f"- `{key}`: {count}/{len(included_round_ids)} included rounds."
        for key, count in sorted(openings.items())
    ]
    lines += [
        f"- regroup toward `{key}`: {count}/{len(included_round_ids)} included rounds."
        for key, count in sorted(regroups.items())
    ]
    lines += ["", "No pattern implies intention, player identity, or full-team presence.", ""]
    (output_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    with (output_dir / "pattern_table.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["feature", "key", "count", "denominator"])
        writer.writeheader()
        for feature, counts in (
            ("opening", openings),
            ("regroup", regroups),
            ("commitment", commitments),
            ("opposite_presence", opposite),
        ):
            for key, count in sorted(counts.items()):
                writer.writerow(
                    {
                        "feature": feature,
                        "key": key,
                        "count": count,
                        "denominator": len(included_round_ids),
                    }
                )
    (output_dir / "representative_rounds.json").write_text(
        json.dumps(representatives, indent=2) + "\n", encoding="utf-8"
    )
    return summary
