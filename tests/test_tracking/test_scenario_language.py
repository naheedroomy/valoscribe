from valoscribe.analytics.scenario_language import parse_scenario_question
from valoscribe.llm.provider import FakeLLMProvider
from valoscribe.types.persistent import ScenarioQuery


def test_validated_question_returns_explicit_filters_before_execution() -> None:
    provider = FakeLLMProvider([{"map_ids": ["ascent"], "alive_attack": 2}])

    preview = parse_scenario_question(
        "Ascent rounds with two attackers alive",
        fallback_query=ScenarioQuery(),
        provider=provider,
        enabled=True,
    )

    assert preview.parsed is True
    assert preview.query == ScenarioQuery(map_ids=["ascent"], alive_attack=2)
    assert preview.filters == {"map_ids": ["ascent"], "alive_attack": 2}
    assert provider.calls[0].response_model is ScenarioQuery


def test_invalid_model_output_falls_back_to_deterministic_query() -> None:
    fallback = ScenarioQuery(map_ids=["haven"])
    provider = FakeLLMProvider()
    provider.queue_raw_output({"confidence_floor": 4})

    preview = parse_scenario_question(
        "invalid filters", fallback_query=fallback, provider=provider, enabled=True
    )

    assert preview.parsed is False
    assert preview.query == fallback
    assert preview.filters == {"map_ids": ["haven"]}
    assert "ValidationError" in preview.fallback_reason


def test_disabled_parsing_does_not_invoke_provider() -> None:
    provider = FakeLLMProvider([{"map_ids": ["ascent"]}])
    fallback = ScenarioQuery(round_numbers=[3])

    preview = parse_scenario_question(
        "round three", fallback_query=fallback, provider=provider
    )

    assert preview.parsed is False
    assert preview.query == fallback
    assert provider.calls == []


def test_transport_failure_falls_back_without_propagating() -> None:
    class BrokenProvider:
        def generate_structured(self, **kwargs):
            raise OSError("private transport detail")

    fallback = ScenarioQuery(phases=["post_plant"])
    preview = parse_scenario_question(
        "post plant", fallback_query=fallback, provider=BrokenProvider(), enabled=True
    )

    assert preview.parsed is False
    assert preview.query == fallback
    assert preview.fallback_reason == "structured parsing failed (OSError)"
    assert "private transport detail" not in preview.fallback_reason
