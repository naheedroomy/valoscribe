import json

from typer.testing import CliRunner

from valoscribe.__main__ import app
from valoscribe.llm.provider import FakeLLMProvider
from valoscribe.types.persistent import ScenarioQuery


def test_parse_cli_disabled_uses_fallback_and_does_not_execute(tmp_path, monkeypatch):
    fallback_path = tmp_path / "fallback.json"
    fallback_path.write_text('{"map_ids":["haven"]}', encoding="utf-8")

    def unexpected_provider(*args, **kwargs):
        raise AssertionError("disabled parsing must not create a provider")

    monkeypatch.setattr("valoscribe.commands.scenario.create_llm_provider", unexpected_provider)
    result = CliRunner().invoke(
        app, ["scenario", "parse", "Ascent exec", str(fallback_path)]
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "schema_version": "1.0",
        "question": "Ascent exec",
        "filters": {"map_ids": ["haven"]},
        "parsed": False,
        "fallback_reason": "natural-language parsing disabled",
    }


def test_parse_cli_enabled_shows_provider_preview_without_query_execution(tmp_path, monkeypatch):
    fallback_path = tmp_path / "fallback.json"
    fallback_path.write_text('{"map_ids":["haven"]}', encoding="utf-8")
    monkeypatch.setenv("LLM_ENABLED", "true")
    monkeypatch.setenv("LLM_API_KEY", "test-only-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    fake = FakeLLMProvider([{"map_ids": ["ascent"], "phases": ["execute"]}])
    monkeypatch.setattr("valoscribe.commands.scenario.create_llm_provider", lambda settings: fake)
    monkeypatch.setattr(
        "valoscribe.commands.scenario.match_scenarios",
        lambda *args: (_ for _ in ()).throw(AssertionError("parse must not execute")),
    )

    result = CliRunner().invoke(
        app, ["scenario", "parse", "Ascent execute", str(fallback_path), "--enabled"]
    )

    assert result.exit_code == 0
    output = json.loads(result.stdout)
    assert output["filters"] == {"map_ids": ["ascent"], "phases": ["execute"]}
    assert output["parsed"] is True
    assert output["fallback_reason"] is None
    assert fake.calls[0].response_model is ScenarioQuery
    assert "test-only-key" not in result.stdout


def test_parse_cli_invalid_settings_falls_back_without_leaking_env(tmp_path, monkeypatch):
    fallback_path = tmp_path / "fallback.json"
    fallback_path.write_text('{"round_numbers":[2]}', encoding="utf-8")
    monkeypatch.setenv("LLM_ENABLED", "true")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "not-a-number")
    monkeypatch.setenv("LLM_API_KEY", "secret-test-value")

    result = CliRunner().invoke(
        app, ["scenario", "parse", "round two", str(fallback_path), "--enabled"]
    )

    assert result.exit_code == 0
    output = json.loads(result.stdout)
    assert output["filters"] == {"round_numbers": [2]}
    assert output["parsed"] is False
    assert "secret-test-value" not in result.stdout


def test_parse_cli_provider_failure_shows_deterministic_fallback(tmp_path, monkeypatch):
    fallback_path = tmp_path / "fallback.json"
    fallback_path.write_text('{"phases":["post_plant"]}', encoding="utf-8")
    monkeypatch.setenv("LLM_ENABLED", "true")
    fake = FakeLLMProvider()
    fake.queue_raw_output({"confidence_floor": 3})
    monkeypatch.setattr("valoscribe.commands.scenario.create_llm_provider", lambda settings: fake)

    result = CliRunner().invoke(
        app, ["scenario", "parse", "post-plant", str(fallback_path), "--enabled"]
    )

    assert result.exit_code == 0
    output = json.loads(result.stdout)
    assert output["filters"] == {"phases": ["post_plant"]}
    assert output["parsed"] is False
    assert "ValidationError" in output["fallback_reason"]
