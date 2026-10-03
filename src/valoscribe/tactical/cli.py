"""Typer commands for offline tactical calibration and analysis."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from valoscribe.tactical.config import load_config
from valoscribe.tactical.corrections import rebuild_round
from valoscribe.tactical.pipeline import analyze_config, inspect_config
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
