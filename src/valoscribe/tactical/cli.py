"""Typer commands for offline tactical calibration and analysis."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Literal

import typer

from valoscribe.tactical.config import load_config
from valoscribe.tactical.contracts import MarkerAdjudication, RoundMovementSummary
from valoscribe.tactical.corrections import append_adjudications, rebuild_round
from valoscribe.tactical.manifest import load_manifest, load_profile
from valoscribe.tactical.pipeline import analyze_config, inspect_config
from valoscribe.tactical.preflight import (
    PreflightValidationError,
    RoundRangeResolutionError,
    VODExecutionPlan,
    validate_vod_preflight,
)
from valoscribe.tactical.reporting import write_aggregate_report
from valoscribe.tactical.review import review_round

app = typer.Typer(help="Offline minimap-first tactical analysis", no_args_is_help=True)


@app.command("inspect")
def inspect_command(
    config_path: Path = typer.Option(..., "--config", exists=True, dir_okay=False),
) -> None:
    """Validate config/source and write crop, transform, and zone artifacts."""
    try:
        config, raw = load_config(config_path)
        result = inspect_config(config_path, config, raw)
    except (OSError, ValueError) as error:
        raise typer.BadParameter(str(error)) from error
    typer.echo(json.dumps(result, indent=2))


@app.command("review")
def review_command(
    run_dir: Path = typer.Option(..., "--run-dir", exists=True, file_okay=False),
    round_id: str = typer.Option(..., "--round-id"),
    reviewer: str = typer.Option("local-reviewer", "--reviewer"),
) -> None:
    """Review a round's sampled minimap frames and append corrections."""
    try:
        config, _ = load_config(run_dir / "config.snapshot.yaml")
        review_round(run_dir, round_id, config, reviewer)
    except (OSError, ValueError) as error:
        raise typer.BadParameter(str(error)) from error


@app.command("enable-source-adjudication")
def enable_source_adjudication_command(
    run_dir: Path = typer.Option(..., "--run-dir", exists=True, file_okay=False),
    round_id: str = typer.Option(..., "--round-id"),
) -> None:
    """Opt a round into fail-closed source adjudication before adding markers."""
    try:
        config, _ = load_config(run_dir / "config.snapshot.yaml")
        append_adjudications(run_dir / "rounds" / round_id, [], config, round_id)
    except (OSError, ValueError) as error:
        raise typer.BadParameter(str(error)) from error
    typer.echo(f"Source adjudication enabled for {round_id}")


@app.command("adjudicate-marker")
def adjudicate_marker_command(
    run_dir: Path = typer.Option(..., "--run-dir", exists=True, file_okay=False),
    round_id: str = typer.Option(..., "--round-id"),
    sample_index: int = typer.Option(..., "--sample-index", min=0),
    observation_id: str = typer.Option(..., "--observation-id"),
    disposition: Literal["supported", "deferred"] = typer.Option(..., "--disposition"),
    reviewer: str = typer.Option(..., "--reviewer"),
    source_locator: str = typer.Option(..., "--source-locator"),
    source_timestamp_seconds: float = typer.Option(..., "--source-timestamp-seconds", min=0),
    source_frame_index: int | None = typer.Option(None, "--source-frame-index", min=0),
    confidence: float = typer.Option(..., "--confidence", min=0, max=1),
    note: str | None = typer.Option(None, "--note"),
    adjudication_id: str | None = typer.Option(None, "--adjudication-id"),
) -> None:
    """Append source-supported/deferred evidence for one stable marker id."""
    try:
        config, _ = load_config(run_dir / "config.snapshot.yaml")
        item = MarkerAdjudication(
            adjudication_id=adjudication_id or uuid.uuid4().hex,
            run_id=config.run.run_id,
            round_id=round_id,
            sample_index=sample_index,
            target_observation_id=observation_id,
            disposition=disposition,
            reviewer=reviewer,
            source_locator=source_locator,
            source_timestamp_seconds=source_timestamp_seconds,
            source_frame_index=source_frame_index,
            confidence=confidence,
            note=note,
        )
        append_adjudications(run_dir / "rounds" / round_id, [item], config, round_id)
    except (OSError, ValueError) as error:
        raise typer.BadParameter(str(error)) from error
    typer.echo(item.model_dump_json())


@app.command("rebuild")
def rebuild_command(
    run_dir: Path = typer.Option(..., "--run-dir", exists=True, file_okay=False),
    round_id: str | None = typer.Option(None, "--round-id"),
) -> None:
    """Apply append-only corrections and write a new derived revision."""
    try:
        config, _ = load_config(run_dir / "config.snapshot.yaml")
        rounds = [round_id] if round_id else [item.round_id for item in config.rounds]
        results = [rebuild_round(run_dir, item, config) for item in rounds]
        summaries = []
        correction_counts: dict[str, int] = {}
        consumed_round_revisions: dict[str, str] = {}
        for round_config in config.rounds:
            round_root = run_dir / "rounds" / round_config.round_id
            revisions = sorted(
                (round_root / "derived").glob("revision-*"),
                key=lambda item: int(item.name.rsplit("-", 1)[-1]),
            )
            selected_revision = revisions[-1] if revisions else None
            summary_path = (
                selected_revision / "summary.json"
                if selected_revision
                else round_root / "summary.json"
            )
            if summary_path.is_file():
                summaries.append(RoundMovementSummary.model_validate_json(summary_path.read_text()))
                consumed_round_revisions[round_config.round_id] = str(
                    summary_path.relative_to(run_dir)
                )
            revision_manifest = (
                json.loads((selected_revision / "revision.json").read_text(encoding="utf-8"))
                if selected_revision
                else {}
            )
            correction_counts[round_config.round_id] = int(
                revision_manifest.get("correction_count", 0)
            )
        aggregate_root = run_dir / "aggregate"
        aggregate_root.mkdir(exist_ok=True)
        revision_number = len(list(aggregate_root.glob("derived-revision-*"))) + 1
        temporary = (
            aggregate_root / f".derived-revision-{revision_number:03d}-{uuid.uuid4().hex}.tmp"
        )
        temporary.mkdir()
        write_aggregate_report(
            temporary,
            config.run.run_id,
            summaries,
            [item.round_id for item in config.rounds],
            [item["round_id"] for item in config.excluded_rounds],
            correction_counts,
            consumed_round_revisions,
        )
        final_aggregate = aggregate_root / f"derived-revision-{revision_number:03d}"
        temporary.rename(final_aggregate)
        results.append({"aggregate_revision_directory": str(final_aggregate)})
    except (OSError, ValueError, ImportError) as error:
        raise typer.BadParameter(str(error)) from error
    typer.echo(json.dumps(results, indent=2))


@app.command("analyze")
def analyze_command(
    config_path: Path = typer.Option(..., "--config", exists=True, dir_okay=False),
) -> None:
    """Analyze only manually configured intervals; never overwrite a run."""
    try:
        config, raw = load_config(config_path)
        run_dir, result = analyze_config(config_path, config, raw)
    except FileExistsError as error:
        raise typer.BadParameter(f"refusing to overwrite an existing run: {error}") from error
    except (OSError, ValueError) as error:
        raise typer.BadParameter(str(error)) from error
    typer.echo(f"Run artifacts: {run_dir}")
    typer.echo(json.dumps(result, indent=2))


def _format_round_summary_table(plan: VODExecutionPlan) -> str:
    headers = [
        "Round",
        "Map Round",
        "Start (s)",
        "End (s)",
        "Live Start (s)",
        "Selected Side",
        "Opponent Side",
        "Exclusions",
    ]
    rows: list[list[str]] = []
    for r in plan.selected_rounds:
        rows.append([
            r.round_id,
            str(r.map_round),
            f"{r.source_interval_seconds[0]:.1f}",
            f"{r.source_interval_seconds[1]:.1f}",
            f"{r.source_interval_seconds[0] + r.live_start_offset_seconds:.1f}",
            r.selected_team_side,
            r.opponent_team_side,
            str(len(r.excluded_intervals)),
        ])

    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(cell))

    header_line = " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    separator_line = "-+-".join("-" * col_widths[i] for i in range(len(headers)))
    row_lines = [
        " | ".join(cell.ljust(col_widths[i]) for i, cell in enumerate(row))
        for row in rows
    ]
    return "\n".join([header_line, separator_line] + row_lines)


@app.command("analyze-vod")
def analyze_vod_command(
    vod: Path = typer.Option(
        ..., "--vod", exists=True, dir_okay=False, help="Path to local VOD video file"
    ),
    map_name: str = typer.Option(..., "--map", help="Map name (currently 'ascent')"),
    match_id: str = typer.Option(..., "--match", help="Match identifier"),
    map_id: str = typer.Option(..., "--map-id", help="Map instance identifier"),
    from_round: int = typer.Option(
        ..., "--from-round", min=1, help="First round to analyze (inclusive)"
    ),
    to_round: int = typer.Option(
        ..., "--to-round", min=1, help="Last round to analyze (inclusive)"
    ),
    team: str = typer.Option(..., "--team", help="Selected team identifier"),
    profile_path: Path = typer.Option(
        ..., "--profile", exists=True, dir_okay=False, help="Broadcast profile JSON path"
    ),
    round_manifest_path: Path = typer.Option(
        ...,
        "--round-manifest",
        exists=True,
        dir_okay=False,
        help="Round manifest JSON path",
    ),
    output: Path = typer.Option(..., "--output", file_okay=False, help="Output directory path"),
    preflight: bool = typer.Option(
        True,
        "--preflight/--no-preflight",
        help="Preview execution plan and summary without running analysis",
    ),
    verify_sha: bool = typer.Option(
        True,
        "--verify-sha/--no-verify-sha",
        help="Verify source video SHA-256 against manifest",
    ),
) -> None:
    """Validate and execute VOD round-range tactical analysis."""
    try:
        manifest = load_manifest(round_manifest_path)
        profile = load_profile(profile_path)
        plan = validate_vod_preflight(
            vod_path=vod,
            map_name=map_name,
            match_id=match_id,
            map_id=map_id,
            from_round=from_round,
            to_round=to_round,
            selected_team_id=team,
            manifest=manifest,
            profile=profile,
            output_dir=output,
            verify_sha256=verify_sha,
        )
    except (
        PreflightValidationError,
        RoundRangeResolutionError,
        FileExistsError,
        ValueError,
    ) as error:
        typer.echo(f"Error: {error}")
        raise typer.Exit(1)

    typer.echo("Preflight validation PASSED")
    typer.echo(f"Selected Team: {plan.selected_team_id}")
    typer.echo(f"Opponent: {plan.opponent_team_id}")

    if preflight:
        typer.echo("\nExecution Plan:")
        typer.echo(plan.model_dump_json(indent=2))
        typer.echo("\nRound Summary Table:")
        typer.echo(_format_round_summary_table(plan))
        return

    output.mkdir(parents=True, exist_ok=True)
    plan_path = output / "execution-plan.json"
    plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    typer.echo("\nRound Summary Table:")
    typer.echo(_format_round_summary_table(plan))
    typer.echo(
        f"\nStage 1 foundation complete. Execution plan written to {plan_path}."
        "\nOutputs are ready for Stage 2 baseline extraction."
    )

