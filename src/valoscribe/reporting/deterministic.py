"""Evidence-validated deterministic Markdown and HTML report rendering."""

from __future__ import annotations

import html
import re
from typing import Literal

from pydantic import Field, field_validator, model_validator

from valoscribe.analytics.aggregates import RoundAggregate
from valoscribe.llm.provider import StructuredLLM
from valoscribe.types.persistent import PersistentModel


class ReportClaim(PersistentModel):
    """One explicit tactical assertion, backed by aggregate selection evidence."""

    schema_version: Literal["1.0"] = "1.0"
    section: str = Field(min_length=1)
    text: str = Field(min_length=1)
    sample_size: int = Field(gt=0)
    selection_criteria: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    caveat: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    representative_round_ids: list[str] = Field(default_factory=list)
    outlier_round_ids: list[str] = Field(default_factory=list)
    timestamp: str | None = None

    @field_validator("section", "text", "selection_criteria", "caveat", mode="before")
    @classmethod
    def required_text_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("claim text fields must not be blank")
        return value

    @field_validator("evidence_ids", "representative_round_ids", "outlier_round_ids")
    @classmethod
    def identifiers_are_not_blank(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("report identifiers must not be blank")
        return values


class NarrativeFact(PersistentModel):
    """One exact, selected aggregate fact eligible for optional narration."""

    schema_version: Literal["1.0"] = "1.0"
    fact_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)


class NarrativeClaim(PersistentModel):
    """A claim restricted to the exact supplied fact and evidence references."""

    schema_version: Literal["1.0"] = "1.0"
    fact_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    status: Literal["observed", "inferred", "unknown"]


class NarrativeOutput(PersistentModel):
    """Structured optional narrative; free-form claims are not accepted."""

    schema_version: Literal["1.0"] = "1.0"
    claims: list[NarrativeClaim] = Field(default_factory=list)


class ReportInput(PersistentModel):
    """Structured inputs to report templates; no conclusions are inferred here."""

    schema_version: Literal["1.0"] = "1.0"
    map_id: str | None = None
    side_sample_sizes: dict[str, int] = Field(default_factory=dict)
    processing_quality: list[str] = Field(default_factory=list)
    aggregate: RoundAggregate
    claims: list[ReportClaim] = Field(default_factory=list)
    narrative_claims: list[NarrativeClaim] = Field(default_factory=list)

    @model_validator(mode="after")
    def claims_reference_aggregate(self) -> ReportInput:
        known = set(self.aggregate.evidence_ids)
        rounds = set(self.aggregate.matching_round_ids)
        if self.aggregate.sample_size != len(rounds):
            raise ValueError("aggregate sample size does not match unique matching rounds")
        if any(value < 0 for value in self.side_sample_sizes.values()):
            raise ValueError("side sample sizes must be non-negative")
        if any(value > self.aggregate.sample_size for value in self.side_sample_sizes.values()):
            raise ValueError("side sample size exceeds aggregate sample size")
        if len(self.aggregate.matching_round_ids) != len(set(self.aggregate.matching_round_ids)):
            raise ValueError("aggregate matching rounds must be unique")
        if sum(self.side_sample_sizes.values()) > self.aggregate.sample_size:
            raise ValueError("side sample sizes exceed aggregate sample size")
        facts = {item.fact_id: item for item in aggregate_narrative_facts(self.aggregate)}
        for narrative_claim in self.narrative_claims:
            fact = facts.get(narrative_claim.fact_id)
            if fact is None or narrative_claim.text != fact.text:
                raise ValueError("narrative claim is not an exact supplied fact")
            if not set(narrative_claim.evidence_ids).issubset(known) or not set(
                narrative_claim.evidence_ids
            ).issubset(fact.evidence_ids):
                raise ValueError("narrative claim references unsupported evidence")
        for claim in self.claims:
            if claim.sample_size > self.aggregate.sample_size:
                raise ValueError("claim sample size exceeds aggregate sample size")
            if not set(claim.evidence_ids).issubset(known):
                raise ValueError("claim references evidence absent from aggregate")
            if not set(claim.representative_round_ids + claim.outlier_round_ids).issubset(rounds):
                raise ValueError("claim references rounds absent from aggregate")
        return self


def render_markdown(report: ReportInput) -> str:
    """Render stable Markdown with supplied claims and supported aggregate summaries."""
    lines = ["# Tactical analysis report", "", f"Map: {_md(report.map_id or 'unknown')}", ""]
    lines.extend(["## Processing quality", ""])
    lines.extend(f"- {_md(item)}" for item in sorted(report.processing_quality))
    if not report.processing_quality:
        lines.append("- Unknown / not observed.")
    lines.extend(["", "## Map and side sample", "",
                 f"- Map sample: {report.aggregate.sample_size} rounds."])
    if report.side_sample_sizes:
        lines.extend(
            f"- {_md(side)}: {count} rounds."
            for side, count in sorted(report.side_sample_sizes.items())
        )
    else:
        lines.append("- Side sample: Unknown / not observed.")
    lines.extend(["", "## Tactical observations", ""])
    claims = sorted(
        [*report.claims, *_aggregate_claims(report.aggregate)],
        key=lambda item: (item.section.casefold(), item.text.casefold(), item.text),
    )
    if claims:
        for claim in claims:
            lines.extend(_claim_markdown(claim))
        for narrative_claim in report.narrative_claims:
            lines.extend(_narrative_markdown(narrative_claim))
    elif report.narrative_claims:
        for narrative_claim in report.narrative_claims:
            lines.extend(_narrative_markdown(narrative_claim))
    else:
        lines.append("No supported tactical claims; tactical behavior is unknown / not observed.")
    lines.extend(["", "## Representative rounds and outliers", ""])
    lines.append("- Representative rounds: " + _id_list(report.aggregate.representative_round_ids))
    lines.append("- Outlier rounds: " + _id_list(report.aggregate.outlier_round_ids))
    lines.append("- Confidence caveat: aggregate confidence "
                 + f"{report.aggregate.confidence:.2f}.")
    return "\n".join(lines) + "\n"


def generate_narrative(
    aggregate: RoundAggregate,
    *,
    provider: StructuredLLM | None = None,
    enabled: bool = False,
) -> list[NarrativeClaim]:
    """Generate fact-bound narrative only when explicitly enabled and a provider exists."""
    if not enabled or provider is None:
        return []
    facts = aggregate_narrative_facts(aggregate)
    if not facts:
        return []
    fact_payload = [item.model_dump(mode="json") for item in facts]
    try:
        output = provider.generate_structured(
            system_prompt=(
                "Write only supplied aggregate facts. Do not infer missing events or add "
                "tactical claims. Every claim must reproduce one supplied fact's exact "
                "fact_id and text and cite only its supplied evidence IDs. Empty evidence "
                "cannot support a claim. State sample size; label claims observed, inferred, "
                "or unknown. Return the specified schema only."
            ),
            user_prompt=(f"Sample size: {aggregate.sample_size}. Facts: "
                         f"{fact_payload!r}"),
            response_model=NarrativeOutput,
        )
        output = NarrativeOutput.model_validate(output.model_dump())
        known_facts = {item.fact_id: item for item in facts}
        valid: list[NarrativeClaim] = []
        for claim in output.claims:
            fact = known_facts.get(claim.fact_id)
            if (
                fact is None
                or claim.text != fact.text
                or not claim.evidence_ids
                or not set(claim.evidence_ids).issubset(aggregate.evidence_ids)
                or not set(claim.evidence_ids).issubset(fact.evidence_ids)
            ):
                return []
            valid.append(claim)
        return valid
    except Exception:
        return []


def aggregate_narrative_facts(aggregate: RoundAggregate) -> list[NarrativeFact]:
    """Render immutable fact text from aggregate values for exact claim verification."""
    facts: list[NarrativeFact] = []
    if aggregate.sample_size <= 0 or not aggregate.evidence_ids:
        return facts
    for field, distribution in sorted(aggregate.categorical_distributions.items()):
        counts = {value: count for value, count in distribution.items() if count > 0}
        denominator = sum(counts.values())
        if denominator:
            summary = ", ".join(
                f"{value}: {count}/{denominator}"
                for value, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
            )
            facts.append(NarrativeFact(
                fact_id=f"categorical:{field}",
                text=(f"Among {denominator} rounds with a known {field} value, "
                      f"the observed distribution was {summary}."),
                evidence_ids=aggregate.evidence_ids,
            ))
    for field, value in sorted(aggregate.numeric_medians.items()):
        facts.append(NarrativeFact(
            fact_id=f"median:{field}",
            text=f"The aggregate median for {field} was {value:g} across "
                 f"{aggregate.sample_size} matching rounds.",
            evidence_ids=aggregate.evidence_ids,
        ))
    return facts


def _narrative_markdown(claim: NarrativeClaim) -> list[str]:
    return [f"### Optional narrative ({claim.status})", "", _md(claim.text), "",
            "- Evidence: " + ", ".join(
                f"`{_md(item)}`" for item in sorted(claim.evidence_ids)
            ) + ".", ""]


def render_html(report: ReportInput) -> str:
    """Render escaped semantic headings and paragraphs from deterministic Markdown."""
    content = render_markdown(report)
    rendered: list[str] = []
    for line in content.splitlines():
        if line.startswith("# "):
            rendered.append(f"<h1>{html.escape(line[2:], quote=True)}</h1>")
        elif line.startswith("## "):
            rendered.append(f"<h2>{html.escape(line[3:], quote=True)}</h2>")
        elif line.startswith("### "):
            rendered.append(f"<h3>{html.escape(line[4:], quote=True)}</h3>")
        elif line.startswith("- "):
            rendered.append(f"<p>{html.escape(line[2:], quote=True)}</p>")
        elif line:
            rendered.append(f"<p>{html.escape(line, quote=True)}</p>")
    body = "\n".join(rendered)
    return (
        '<!doctype html>\n<html><head><meta charset="utf-8"><title>'
        'Tactical analysis report</title></head><body>\n'
        + body + "\n</body></html>\n"
    )


def _aggregate_claims(aggregate: RoundAggregate) -> list[ReportClaim]:
    """Describe categorical distributions without inventing category provenance."""
    claims: list[ReportClaim] = []
    for field, distribution in sorted(aggregate.categorical_distributions.items()):
        counts = {value: count for value, count in distribution.items() if count > 0}
        denominator = sum(counts.values())
        if not counts or denominator == 0 or not aggregate.evidence_ids:
            continue
        categories = ", ".join(
            f"{value}: {count}/{denominator}"
            for value, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
        )
        claims.append(ReportClaim(
            section=f"Aggregate distribution: {field}",
            text=f"Among {denominator} rounds with a known {field} value, "
                 f"the observed distribution was {categories}.",
            sample_size=denominator,
            selection_criteria=f"Rounds in the aggregate with a known {field} value",
            confidence=aggregate.confidence,
            caveat=("Evidence references are the aggregate union; this aggregate does not "
                    "identify which evidence supports each category, so category-specific "
                    "round attribution is unavailable."),
            evidence_ids=aggregate.evidence_ids,
        ))
    for field, median in sorted(aggregate.numeric_medians.items()):
        if aggregate.sample_size == 0 or not aggregate.evidence_ids:
            continue
        claims.append(ReportClaim(
            section=f"Aggregate median: {field}",
            text=f"The aggregate median for {field} was {median:g} across "
                 f"{aggregate.sample_size} matching rounds.",
            sample_size=aggregate.sample_size,
            selection_criteria="All matching rounds represented by the aggregate",
            confidence=aggregate.confidence,
            caveat="Evidence references are the aggregate union; per-round values are unavailable.",
            evidence_ids=aggregate.evidence_ids,
        ))
    return claims


def _claim_markdown(claim: ReportClaim) -> list[str]:
    details = [
        f"Sample: {claim.sample_size}; selection: {_md(claim.selection_criteria)}; "
        f"confidence: {claim.confidence:.2f}; caveat: {_md(claim.caveat)}.",
        "Evidence: " + ", ".join(f"`{_md(item)}`" for item in sorted(claim.evidence_ids)) + ".",
    ]
    if claim.representative_round_ids:
        details.append("Representative rounds: " + _id_list(claim.representative_round_ids) + ".")
    if claim.outlier_round_ids:
        details.append("Outliers: " + _id_list(claim.outlier_round_ids) + ".")
    if claim.timestamp is not None:
        details.append("Timestamp: " + _md(claim.timestamp) + ".")
    return [f"### {_md(claim.section)}", "", _md(claim.text), "",
            *[f"- {item}" for item in details], ""]


def _id_list(values: list[str]) -> str:
    return ", ".join(f"`{_md(value)}`" for value in sorted(values)) or "None observed"


def _md(value: str) -> str:
    """Escape Markdown metacharacters and HTML-escape untrusted text."""
    escaped = html.escape(value, quote=True)
    return re.sub(r"([\\`*_{}\[\]()#+.!|>-])", r"\\\1", escaped)
