"""Typer commands for offline tactical calibration and analysis."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from valoscribe.tactical.config import load_config
from valoscribe.tactical.pipeline import analyze_config, inspect_config

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
