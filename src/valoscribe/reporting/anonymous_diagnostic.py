"""Deterministic JSON and Markdown summary for anonymous diagnostic artifacts."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from valoscribe.types.anonymous_report import (
    AnonymousConfidenceRange,
    AnonymousDiagnosticReport,
)
from valoscribe.types.anonymous_tracking import (
    AnonymousRawFrameObservation,
    AnonymousRunManifest,
    AnonymousTrackSample,
)


def build_anonymous_diagnostic_report(
    wrapper: AnonymousRunManifest,
    raw_frames: list[AnonymousRawFrameObservation],
    samples: list[AnonymousTrackSample],
    *,
    artifacts: dict[str, str],
) -> AnonymousDiagnosticReport:
    """Summarize observed rows without converting anonymous evidence to player claims."""
    manifest = wrapper.tracking_manifest
    all_candidates = [candidate.candidate for row in raw_frames for candidate in row.candidates]
    sample_frame_indices = {sample.frame_index for sample in samples}
    return AnonymousDiagnosticReport(
        run_id=manifest.run_id,
        source_path=manifest.source_path,
        source_video_sha256=manifest.source_video_sha256,
        config_sha256=manifest.config_sha256,
        map_id=manifest.map_id,
        map_number=manifest.map_number,
        round_number=manifest.round_number,
        start_frame_index=manifest.start_frame_index,
        end_frame_index=manifest.end_frame_index,
        start_source_pts=manifest.start_source_pts,
        end_source_pts=manifest.end_source_pts,
        timebase_numerator=manifest.timebase_numerator,
        timebase_denominator=manifest.timebase_denominator,
        requested_frame_count=manifest.end_frame_index - manifest.start_frame_index + 1,
        decoded_frame_count=len(raw_frames),
        context_live_frame_count=sum(row.context == "live" for row in raw_frames),
        context_nonlive_frame_count=sum(row.context == "nonlive" for row in raw_frames),
        context_unknown_frame_count=sum(row.context == "unknown" for row in raw_frames),
        candidate_count=len(all_candidates),
        accepted_candidate_count=sum(candidate.accepted for candidate in all_candidates),
        rejected_candidate_count=sum(not candidate.accepted for candidate in all_candidates),
        observed_sample_count=len(samples),
        anonymous_tracklet_count=len({sample.tracklet_id for sample in samples}),
        frames_without_tracklet_sample=len(
            {row.provenance.frame_index for row in raw_frames} - sample_frame_indices
        ),
        detector_confidence=_confidence_range(
            candidate.detector_confidence for candidate in all_candidates
        ),
        association_confidence=_confidence_range(
            sample.association_confidence for sample in samples
        ),
        hud_config_sha256=manifest.hud_config.file_sha256,
        color_config_sha256=manifest.color_config.file_sha256,
        map_config_sha256=manifest.map_config.file_sha256,
        map_asset_sha256=manifest.map_asset_sha256,
        artifacts=artifacts,
    )


def render_anonymous_diagnostic_markdown(report: AnonymousDiagnosticReport) -> str:
    """Render explicit scope caveats alongside exact evidence counts and source clock."""
    report = AnonymousDiagnosticReport.model_validate(report.model_dump())
    timebase = f"{report.timebase_numerator}/{report.timebase_denominator} seconds per PTS tick"
    artifact_lines = "\n".join(
        f"- `{name}`: `{path}`" for name, path in sorted(report.artifacts.items())
    )
    return f"""# Anonymous minimap diagnostic — {report.run_id}

> **Diagnostic only.** Labels are anonymous candidate tracklets, not confirmed players.
> Coordinates are normalized within the configured minimap crop, not canonical map coordinates.
> No team, side, agent, alive-state, map-location, or tactical claim is made.
> No interpolation fills detection gaps.

## Source and reviewed bounds

- Source: `{report.source_path}`
- SHA-256: `{report.source_video_sha256}`
- Map/round metadata: `{report.map_id}` / map {report.map_number}, round {report.round_number}
- Inclusive source frames: {report.start_frame_index}–{report.end_frame_index}
- Inclusive source PTS: {report.start_source_pts}–{report.end_source_pts} ({timebase})
- Decoded frames: {report.decoded_frame_count}/{report.requested_frame_count}

## Observations

- Context classification (live/nonlive/unknown):
  {report.context_live_frame_count}/{report.context_nonlive_frame_count}/
  {report.context_unknown_frame_count}; unknown includes omitted, unreviewed context.
- Raw candidates: {report.candidate_count} (accepted {report.accepted_candidate_count},
  rejected {report.rejected_candidate_count})
- Observed anonymous tracklet samples: {report.observed_sample_count};
  ephemeral tracklet labels: {report.anonymous_tracklet_count}
- Frames with no observed tracklet sample: {report.frames_without_tracklet_sample};
  this is not evidence that no player was present.
- Detector confidence: {_format_range(report.detector_confidence)}
- Association confidence: {_format_range(report.association_confidence)}

## Provenance and unavailable claims

- HUD/color/map config SHA-256:
  `{report.hud_config_sha256}` / `{report.color_config_sha256}` /
  `{report.map_config_sha256}`
- Canonical map asset SHA-256: `{report.map_asset_sha256}`
- Player identity: unavailable; canonical map coordinates: unavailable;
  tactical claims: not made.
- Detection/tracking quality metrics: unavailable without independent reviewed ground truth.

## Artifacts

{artifact_lines}
"""


def write_anonymous_diagnostic_report(
    report: AnonymousDiagnosticReport, run_dir: Path
) -> tuple[Path, Path]:
    """Create report files exclusively; never replace existing artifacts."""
    report_path = run_dir / "diagnostic_report.json"
    markdown_path = run_dir / "report.md"
    payload = json.dumps(report.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"
    markdown = render_anonymous_diagnostic_markdown(report)
    with report_path.open("x", encoding="utf-8") as output:
        output.write(payload)
    try:
        with markdown_path.open("x", encoding="utf-8") as output:
            output.write(markdown)
    except BaseException:
        report_path.unlink(missing_ok=True)
        raise
    return report_path, markdown_path


def _confidence_range(values: Iterable[float]) -> AnonymousConfidenceRange | None:
    numeric = list(values)
    if not numeric:
        return None
    return AnonymousConfidenceRange(minimum=min(numeric), maximum=max(numeric))


def _format_range(value: AnonymousConfidenceRange | None) -> str:
    if value is None:
        return "unavailable (no observations)"
    return f"{value.minimum:.3f}–{value.maximum:.3f}"
