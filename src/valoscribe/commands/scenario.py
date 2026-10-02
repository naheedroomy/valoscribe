"""Run validated offline scenario queries against JSON or JSONL summaries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
from pydantic import ValidationError

from valoscribe.analytics.scenario_language import parse_scenario_question
from valoscribe.analytics.scenarios import ScenarioSearchRecord, match_scenarios
from valoscribe.llm.config import LLMSettings
from valoscribe.llm.openai_compatible import create_llm_provider
from valoscribe.types.persistent import ScenarioQuery

app = typer.Typer(help="Search round and segment scenario summaries")


@app.command("parse")
def parse_command(
    question: str = typer.Argument(..., help="Tactical question to preview as filters"),
    fallback_query_file: Path = typer.Argument(..., help="Deterministic ScenarioQuery JSON file"),
    enabled: bool = typer.Option(
        False, "--enabled", help="Enable configured natural-language parsing"
    ),
) -> None:
    """Preview filters; never execute a scenario query."""
    try:
        fallback = ScenarioQuery.model_validate(
            json.loads(fallback_query_file.read_text(encoding="utf-8"))
        )
    except (OSError, ValueError, TypeError, ValidationError) as exc:
        typer.echo(f"Invalid fallback scenario query: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    settings: LLMSettings | None = None
    provider = None
    configuration_error = False
    if enabled:
        try:
            settings = LLMSettings.from_environment()
            if settings.enabled:
                provider = create_llm_provider(settings)
        except (ValueError, TypeError, ValidationError):
            # Invalid or incomplete configuration must not prevent deterministic preview.
            configuration_error = True
            provider = None
    parsing_enabled = (
        enabled
        and not configuration_error
        and settings is not None
        and settings.enabled
        and provider is not None
    )
    preview = parse_scenario_question(
        question,
        fallback_query=fallback,
        provider=provider,
        enabled=parsing_enabled,
    )
    typer.echo(json.dumps({
        "schema_version": "1.0",
        "question": question,
        "filters": preview.filters,
        "parsed": preview.parsed,
        "fallback_reason": preview.fallback_reason,
    }, sort_keys=True, separators=(",", ":")))


@app.command("query")
def query_command(
    query_file: Path = typer.Argument(..., help="ScenarioQuery JSON file"),
    records_file: Path = typer.Argument(..., help="JSON array or JSONL summary records"),
) -> None:
    """Print matching round and segment identifiers as deterministic JSON."""
    try:
        query_data = json.loads(query_file.read_text(encoding="utf-8"))
        query = ScenarioQuery.model_validate(query_data)
        text = records_file.read_text(encoding="utf-8")
        data: Any
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                data = [data]
            if not isinstance(data, list):
                raise ValueError("records JSON must be an array or object")
        except json.JSONDecodeError:
            data = [json.loads(line) for line in text.splitlines() if line.strip()]
        records = [ScenarioSearchRecord.model_validate(item) for item in data]
    except (OSError, ValueError, TypeError, ValidationError) as exc:
        typer.echo(f"Invalid scenario query input: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    matches = match_scenarios(query, records)
    output = {
        "schema_version": "1.0",
        "matches": [
            {"round_id": row.round_id, "segment_id": row.segment_id}
            for row in matches
        ],
    }
    typer.echo(json.dumps(output, sort_keys=True, separators=(",", ":")))
