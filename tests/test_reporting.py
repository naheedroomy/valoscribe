from __future__ import annotations

import pytest
from pydantic import ValidationError

from valoscribe.analytics.aggregates import RoundAggregate
from valoscribe.reporting.deterministic import (
    ReportClaim,
    ReportInput,
    render_html,
    render_markdown,
)


def aggregate() -> RoundAggregate:
    return RoundAggregate(
        sample_size=2,
        matching_round_ids=["r2", "r1"],
        representative_round_ids=["r1"],
        outlier_round_ids=["r2"],
        categorical_distributions={"formation": {"spread": 1, "grouped": 1}},
        numeric_medians={},
        confidence=0.45,
        evidence_ids=["source:r1", "source:r2"],
    )


def report(claims=None, **kwargs) -> ReportInput:
    return ReportInput(aggregate=aggregate(), claims=claims or [], **kwargs)


def test_empty_report_generates_supported_aggregate_prose() -> None:
    rendered = render_markdown(report())
    assert "Unknown / not observed" in rendered
    assert "Aggregate distribution: formation" in rendered
    assert "spread: 1/2" in rendered and "grouped: 1/2" in rendered
    assert "aggregate union" in rendered
    assert "category\\-specific round attribution is unavailable" in rendered
    assert "always rotates" not in rendered


def test_claim_includes_selection_sample_evidence_rounds_and_timestamp() -> None:
    claim = ReportClaim(
        section="Rotations",
        text="Observed regroup through spawn.",
        sample_size=2,
        selection_criteria="Ascent attack rounds with early B pressure",
        confidence=0.7,
        caveat="One round has incomplete minimap coverage",
        evidence_ids=["source:r1"],
        representative_round_ids=["r1"],
        timestamp="00:12:34",
    )
    rendered = render_markdown(report([claim]))
    assert "source:r1" in rendered and "r1" in rendered and "00:12:34" in rendered
    assert "selection: Ascent attack rounds" in rendered
    assert "confidence: 0.70" in rendered and "incomplete minimap" in rendered


def test_unknown_evidence_and_round_references_fail_closed() -> None:
    claim = ReportClaim(
        section="Entry", text="Entered site", sample_size=1, selection_criteria="all",
        confidence=0.8, caveat="limited", evidence_ids=["foreign"],
        representative_round_ids=["foreign-round"],
    )
    with pytest.raises(ValidationError, match="evidence absent"):
        report([claim])


def test_zero_sample_claim_is_invalid() -> None:
    with pytest.raises(ValidationError):
        ReportClaim(section="Entry", text="claim", sample_size=0, selection_criteria="all",
                    confidence=0.8, caveat="limited", evidence_ids=["source:r1"])


def test_markdown_html_escape_and_stable_ordering() -> None:
    first = ReportClaim(section="Z <script>", text="A & B", sample_size=1,
                        selection_criteria="all * rounds", confidence=0.4,
                        caveat="low confidence", evidence_ids=["source:r1"])
    second = ReportClaim(section="A", text="Second", sample_size=1,
                         selection_criteria="all", confidence=0.9, caveat="ok",
                         evidence_ids=["source:r2"])
    input_report = report([first, second], map_id="Ascent <script>")
    markdown = render_markdown(input_report)
    assert markdown.index("### A") < markdown.index("### Z")
    assert "\\*" in markdown
    html = render_html(input_report)
    assert "&amp;lt;script&amp;gt;" in html and "<script>" not in html
    assert "source:r1" in html


def test_side_samples_are_sorted_and_offline_rendering_is_pure() -> None:
    result = report(side_sample_sizes={"defense": 1, "attack": 1})
    rendered = render_markdown(result)
    assert rendered.index("attack: 1") < rendered.index("defense: 1")
    assert render_html(result) == render_html(result)
    assert "<h1>Tactical analysis report</h1>" in render_html(result)


def test_zero_known_category_sample_does_not_create_distribution_claim() -> None:
    empty = RoundAggregate(
        sample_size=0, matching_round_ids=[], representative_round_ids=[],
        outlier_round_ids=[], categorical_distributions={"formation": {}},
        numeric_medians={}, confidence=0.0, evidence_ids=[],
    )
    rendered = render_markdown(ReportInput(aggregate=empty))
    assert "Aggregate distribution" not in rendered
    assert "No supported tactical claims" in rendered


def test_sample_counts_cannot_exceed_aggregate() -> None:
    with pytest.raises(ValidationError, match="side sample size exceeds"):
        report(side_sample_sizes={"attack": 3})


def test_html_escapes_once_and_contains_semantic_report_markup() -> None:
    rendered = render_html(report(map_id="<script>&"))
    assert "<h2>Processing quality</h2>" in rendered
    assert "&amp;lt;script&amp;gt;&amp;amp;" in rendered
    assert "&amp;amp;lt;script" not in rendered
    assert "<script>" not in rendered
