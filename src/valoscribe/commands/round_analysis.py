"""Evidence-bounded round analysis CLI."""

from __future__ import annotations

from pathlib import Path

import typer
from pydantic import ValidationError

from valoscribe.llm.config import LLMSettings
from valoscribe.llm.openai_compatible import create_llm_provider
from valoscribe.reporting.round_analysis import build_round_analysis, write_round_analysis
from valoscribe.types.round_analysis import RoundAnalysisBundle

app = typer.Typer(help="Build evidence-backed reports for one round")


@app.command("run")
def run_round_analysis(
    bundle_file: Path = typer.Argument(
        ..., exists=True, dir_okay=False, help="RoundAnalysisBundle JSON"
    ),
    output_dir: Path = typer.Option(
        ..., file_okay=False, help="Directory for new JSON and Markdown outputs"
    ),
    enabled: bool = typer.Option(
        False, "--enabled", help="Opt in to configured hypotheses and recommendations"
    ),
) -> None:
    """Write deterministic report; optional LLM returns cited, tentative analysis."""
    try:
        bundle = RoundAnalysisBundle.model_validate_json(bundle_file.read_bytes())
        provider = None
        use_provider = False
        provider_unavailable = False
        if enabled:
            try:
                settings = LLMSettings.from_environment()
                if settings.enabled:
                    provider = create_llm_provider(settings)
                    use_provider = provider is not None
            except (ValueError, TypeError, ValidationError):
                provider_unavailable = True
        result, diagnostics = build_round_analysis(
            bundle,
            bundle_file,
            provider=provider,
            enabled=use_provider,
            provider_unavailable=provider_unavailable,
        )
        json_path, markdown_path = write_round_analysis(result, diagnostics, output_dir)
    except (OSError, ValueError, TypeError, ValidationError) as error:
        typer.echo(f"Round analysis failed: {error}", err=True)
        raise typer.Exit(code=2) from error
    typer.echo(f"Wrote {json_path} and {markdown_path}")
