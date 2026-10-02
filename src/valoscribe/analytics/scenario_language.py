"""Optional natural-language parsing for deterministic scenario queries."""

from __future__ import annotations

from dataclasses import dataclass

from valoscribe.llm.provider import StructuredLLM
from valoscribe.types.persistent import ScenarioQuery


@dataclass(frozen=True)
class ScenarioQueryPreview:
    """Validated filters shown to the caller before scenario execution."""

    query: ScenarioQuery
    filters: dict[str, object]
    parsed: bool
    fallback_reason: str | None = None


def parse_scenario_question(
    question: str,
    *,
    fallback_query: ScenarioQuery,
    provider: StructuredLLM | None = None,
    enabled: bool = False,
) -> ScenarioQueryPreview:
    """Parse a question when explicitly enabled; otherwise return deterministic filters."""
    if not enabled:
        return _preview(fallback_query, parsed=False, reason="natural-language parsing disabled")
    if provider is None:
        return _preview(fallback_query, parsed=False, reason="no structured provider configured")

    try:
        query = provider.generate_structured(
            system_prompt=(
                "Convert the user's tactical scenario question into ScenarioQuery filters. "
                "Use only the schema fields and values supported by the question; leave "
                "unspecified list fields empty and unspecified scalar fields null/default."
            ),
            user_prompt=question,
            response_model=ScenarioQuery,
        )
        # Validate even providers that claim to return the response model.
        query = ScenarioQuery.model_validate(query.model_dump())
    except Exception as error:
        return _preview(
            fallback_query,
            parsed=False,
            reason=f"structured parsing failed ({type(error).__name__})",
        )
    return _preview(query, parsed=True)


def _preview(
    query: ScenarioQuery, *, parsed: bool, reason: str | None = None
) -> ScenarioQueryPreview:
    return ScenarioQueryPreview(
        query=query,
        filters=query.model_dump(mode="json", exclude_defaults=True),
        parsed=parsed,
        fallback_reason=reason,
    )
