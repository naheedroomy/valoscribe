from __future__ import annotations

from valoscribe.analytics.aggregates import RoundAggregate
from valoscribe.llm.provider import FakeLLMProvider
from valoscribe.reporting.deterministic import (
    NarrativeFact,
    NarrativeOutput,
    generate_narrative,
)


def aggregate() -> RoundAggregate:
    return RoundAggregate(
        sample_size=2,
        matching_round_ids=["r1", "r2"],
        representative_round_ids=["r1"],
        outlier_round_ids=["r2"],
        categorical_distributions={"formation": {"spread": 2}},
        numeric_medians={},
        confidence=0.8,
        evidence_ids=["ev:r1", "ev:r2"],
    )


def fact() -> NarrativeFact:
    return NarrativeFact(
        fact_id="categorical:formation",
        text=("Among 2 rounds with a known formation value, the observed distribution "
              "was spread: 2/2."),
        evidence_ids=["ev:r1", "ev:r2"],
    )


def test_valid_claim_is_accepted_and_prompt_contains_only_aggregate_facts() -> None:
    provider = FakeLLMProvider([{"claims": [{
        "fact_id": fact().fact_id, "text": fact().text,
        "evidence_ids": ["ev:r1"], "status": "observed",
    }]}])
    claims = generate_narrative(aggregate(), provider=provider, enabled=True)
    assert len(claims) == 1
    assert claims[0].evidence_ids == ["ev:r1"]
    assert "Sample size: 2" in provider.calls[0].user_prompt
    assert "ev:r1" in provider.calls[0].user_prompt


def test_unknown_evidence_or_unsupported_text_fails_closed() -> None:
    for claim in (
        {"fact_id": fact().fact_id, "text": fact().text,
         "evidence_ids": ["invented"], "status": "observed"},
        {"fact_id": fact().fact_id, "text": "They always rotate to B.",
         "evidence_ids": ["ev:r1"], "status": "inferred"},
        {"fact_id": "invented", "text": fact().text,
         "evidence_ids": ["ev:r1"], "status": "observed"},
        {"fact_id": fact().fact_id, "text": fact().text,
         "evidence_ids": [], "status": "observed"},
    ):
        provider = FakeLLMProvider([{"claims": [claim]}])
        assert generate_narrative(aggregate(), provider=provider, enabled=True) == []


def test_empty_aggregate_and_disabled_mode_do_not_call_provider() -> None:
    provider = FakeLLMProvider()
    empty = RoundAggregate(
        sample_size=0, matching_round_ids=[], representative_round_ids=[],
        outlier_round_ids=[], categorical_distributions={}, numeric_medians={},
        confidence=0, evidence_ids=[],
    )
    assert generate_narrative(empty, provider=provider, enabled=True) == []
    assert generate_narrative(aggregate(), provider=provider) == []
    assert provider.calls == []


def test_provider_failure_falls_back_without_narrative() -> None:
    provider = FakeLLMProvider()
    assert generate_narrative(aggregate(), provider=provider, enabled=True) == []
    assert len(provider.calls) == 1


def test_pydantic_rejects_extra_free_form_claim_fields() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        NarrativeOutput.model_validate({"claims": [], "narrative": "free form"})
