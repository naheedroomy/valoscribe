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
from valoscribe.tactical.pipeline import analyze_config, inspect_config
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
