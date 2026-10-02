from __future__ import annotations

import pytest
from pydantic import BaseModel, Field, ValidationError

from valoscribe.llm import FakeLLMProvider


class ExampleResponse(BaseModel):
    answer: str = Field(min_length=1)


def test_fake_provider_returns_scripted_validated_response_and_captures_call() -> None:
    provider = FakeLLMProvider([{"answer": "site execute"}])

    result = provider.generate_structured(
        system_prompt="system",
        user_prompt="user",
        response_model=ExampleResponse,
    )

    assert result == ExampleResponse(answer="site execute")
    assert provider.calls[0].system_prompt == "system"
    assert provider.calls[0].user_prompt == "user"
    assert provider.calls[0].response_model is ExampleResponse


def test_fake_provider_surfaces_pydantic_validation_error_for_invalid_raw_output() -> None:
    provider = FakeLLMProvider()
    provider.queue_raw_output({"answer": ""})

    with pytest.raises(ValidationError):
        provider.generate_structured(
            system_prompt="system",
            user_prompt="user",
            response_model=ExampleResponse,
        )

    assert len(provider.calls) == 1


def test_fake_provider_fails_clearly_when_script_is_exhausted() -> None:
    provider = FakeLLMProvider()

    with pytest.raises(RuntimeError, match="no scripted outputs remaining"):
        provider.generate_structured(
            system_prompt="system",
            user_prompt="user",
            response_model=ExampleResponse,
        )


def test_llm_settings_parse_environment_and_remain_disabled_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from valoscribe.llm.config import LLMSettings

    assert LLMSettings().enabled is False
    monkeypatch.setenv("LLM_ENABLED", "true")
    monkeypatch.setenv("LLM_MAX_RETRIES", "4")
    settings = LLMSettings.from_environment()
    assert settings.enabled is True
    assert settings.max_retries == 4
    assert settings.api_key == ""


def test_openai_compatible_request_validates_and_logs_usage(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    caplog.set_level(logging.INFO)
    import json

    from valoscribe.llm.config import LLMSettings
    from valoscribe.llm.openai_compatible import OpenAICompatibleProvider

    captured = []

    def transport(url, headers, body, timeout):
        captured.append((url, headers, json.loads(body), timeout))
        return json.dumps(
            {
                "choices": [{"message": {"content": '{"answer":"ok"}'}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            }
        ).encode()

    settings = LLMSettings(
        enabled=True, api_key="secret", model="configured", base_url="https://host/v1"
    )
    provider = OpenAICompatibleProvider(settings, transport=transport)
    assert provider.generate_structured(
        system_prompt="sys", user_prompt="usr", response_model=ExampleResponse
    ) == ExampleResponse(answer="ok")
    url, headers, body, timeout = captured[0]
    assert url == "https://host/v1/chat/completions"
    assert headers["Authorization"] == "Bearer secret"
    assert body["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "usr"},
    ]
    assert body["response_format"]["type"] == "json_schema"
    assert timeout == 60
    assert "prompt_tokens=3" in caplog.text
    assert "secret" not in caplog.text and "usr" not in caplog.text


def test_invalid_structured_response_gets_one_corrective_retry() -> None:
    import json

    from valoscribe.llm.config import LLMSettings
    from valoscribe.llm.openai_compatible import OpenAICompatibleProvider, ProviderError

    requests = []
    answers = [
        b'{"choices":[{"message":{"content":"{}"}}]}',
        b'{"choices":[{"message":{"content":"{\\"answer\\":\\"fixed\\"}"}}]}',
    ]

    def transport(url, headers, body, timeout):
        requests.append(json.loads(body))
        return answers.pop(0)

    provider = OpenAICompatibleProvider(
        LLMSettings(enabled=True, api_key="k", model="m"), transport=transport
    )
    result = provider.generate_structured(
        system_prompt="s", user_prompt="evidence", response_model=ExampleResponse
    )
    assert result.answer == "fixed"
    assert "no new evidence" in requests[1]["messages"][1]["content"]

    def always_bad(*args):
        return b'{"choices":[{"message":{"content":"{}"}}]}'

    with pytest.raises(ProviderError, match="failed validation"):
        OpenAICompatibleProvider(
            LLMSettings(enabled=True, api_key="k", model="m"), transport=always_bad
        ).generate_structured(system_prompt="s", user_prompt="e", response_model=ExampleResponse)


@pytest.mark.parametrize(
    "failure",
    [
        pytest.param("429", id="http-429"),
        pytest.param("500", id="http-500"),
        pytest.param("timeout", id="timeout"),
        pytest.param("urlerror", id="urlerror"),
    ],
)
def test_transient_transport_failures_retry(failure: str, monkeypatch: pytest.MonkeyPatch) -> None:
    import json
    import urllib.error

    from valoscribe.llm.config import LLMSettings
    from valoscribe.llm.openai_compatible import OpenAICompatibleProvider

    attempts = []
    sleeps = []

    def transport(url, headers, body, timeout):
        attempts.append(body)
        if len(attempts) == 1:
            if failure in {"429", "500"}:
                raise urllib.error.HTTPError(url, int(failure), "error", {}, None)
            if failure == "timeout":
                raise TimeoutError("private transport details")
            raise urllib.error.URLError("private transport details")
        return json.dumps({"choices": [{"message": {"content": '{"answer":"ok"}'}}]}).encode()

    monkeypatch.setattr("valoscribe.llm.openai_compatible.time.sleep", sleeps.append)
    provider = OpenAICompatibleProvider(
        LLMSettings(enabled=True, api_key="secret", model="m", max_retries=1),
        transport=transport,
    )
    assert (
        provider.generate_structured(
            system_prompt="sys", user_prompt="private prompt", response_model=ExampleResponse
        ).answer
        == "ok"
    )
    assert len(attempts) == 2
    assert sleeps == [0.25]


@pytest.mark.parametrize("status", [400, 401])
def test_non_transient_http_failure_does_not_retry(status: int) -> None:
    import urllib.error

    from valoscribe.llm.config import LLMSettings
    from valoscribe.llm.openai_compatible import OpenAICompatibleProvider, ProviderError

    attempts = []

    def transport(url, headers, body, timeout):
        attempts.append(1)
        raise urllib.error.HTTPError(url, status, "error", {}, None)

    with pytest.raises(ProviderError, match="request failed"):
        OpenAICompatibleProvider(
            LLMSettings(enabled=True, api_key="secret", model="m", max_retries=3),
            transport=transport,
        ).generate_structured(system_prompt="s", user_prompt="e", response_model=ExampleResponse)
    assert len(attempts) == 1


def test_truncated_response_fails_closed_without_retry() -> None:
    import json

    from valoscribe.llm.config import LLMSettings
    from valoscribe.llm.openai_compatible import OpenAICompatibleProvider, ProviderError

    def truncated(url, headers, body, timeout):
        return json.dumps(
            {"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]}
        ).encode()

    with pytest.raises(ProviderError, match="truncated"):
        OpenAICompatibleProvider(
            LLMSettings(enabled=True, api_key="k", model="m"), transport=truncated
        ).generate_structured(system_prompt="s", user_prompt="u", response_model=ExampleResponse)


@pytest.mark.parametrize("finish_reason", ["content_filter", "tool_calls", "unknown", None])
def test_explicit_non_stop_finish_reason_rejects_valid_json(
    finish_reason: str | None,
) -> None:
    import json

    from valoscribe.llm.config import LLMSettings
    from valoscribe.llm.openai_compatible import OpenAICompatibleProvider, ProviderError

    def response(url, headers, body, timeout):
        return json.dumps(
            {
                "choices": [
                    {
                        "finish_reason": finish_reason,
                        "message": {"content": json.dumps({"answer": "otherwise valid"})},
                    }
                ]
            }
        ).encode()

    with pytest.raises(ProviderError, match="did not finish successfully"):
        OpenAICompatibleProvider(
            LLMSettings(enabled=True, api_key="k", model="m"), transport=response
        ).generate_structured(system_prompt="s", user_prompt="u", response_model=ExampleResponse)


def test_invalid_json_envelope_corrects_once_and_refusal_precedes_content() -> None:
    import json

    from valoscribe.llm.config import LLMSettings
    from valoscribe.llm.openai_compatible import OpenAICompatibleProvider, ProviderError

    requests = []
    valid_envelope = {"choices": [{"message": {"content": '{"answer":"ok"}'}}]}
    responses = [b"not json", json.dumps(valid_envelope).encode()]

    def transport(url, headers, body, timeout):
        requests.append(json.loads(body))
        return responses.pop(0)

    result = OpenAICompatibleProvider(
        LLMSettings(enabled=True, api_key="k", model="m"), transport=transport
    ).generate_structured(system_prompt="s", user_prompt="evidence", response_model=ExampleResponse)
    assert result.answer == "ok"
    assert len(requests) == 2
    assert "no new evidence" in requests[1]["messages"][1]["content"]
    assert "evidence" in requests[1]["messages"][1]["content"]

    def refusal(url, headers, body, timeout):
        return b'{"choices":[{"message":{"refusal":"not allowed"}}]}'

    with pytest.raises(ProviderError, match="refused"):
        OpenAICompatibleProvider(
            LLMSettings(enabled=True, api_key="k", model="m"), transport=refusal
        ).generate_structured(system_prompt="s", user_prompt="e", response_model=ExampleResponse)


def test_invalid_json_after_transient_retry_still_gets_correction() -> None:
    import json
    import urllib.error

    from valoscribe.llm.config import LLMSettings
    from valoscribe.llm.openai_compatible import OpenAICompatibleProvider

    attempts = []

    def transport(url, headers, body, timeout):
        attempts.append(json.loads(body))
        if len(attempts) == 1:
            raise urllib.error.HTTPError(url, 503, "busy", {}, None)
        if len(attempts) == 2:
            return b"malformed"
        return json.dumps({"choices": [{"message": {"content": '{"answer":"ok"}'}}]}).encode()

    provider = OpenAICompatibleProvider(
        LLMSettings(enabled=True, api_key="k", model="m", max_retries=1), transport=transport
    )
    assert (
        provider.generate_structured(
            system_prompt="s", user_prompt="e", response_model=ExampleResponse
        ).answer
        == "ok"
    )
    assert len(attempts) == 3
    assert "no new evidence" in attempts[2]["messages"][1]["content"]


def test_disabled_factory_does_not_create_transport_or_require_key() -> None:
    from valoscribe.llm.config import LLMSettings
    from valoscribe.llm.openai_compatible import create_llm_provider

    def forbidden(*args):
        raise AssertionError("transport must not run")

    assert create_llm_provider(LLMSettings(), transport=forbidden) is None
    with pytest.raises(ValueError, match="required"):
        create_llm_provider(LLMSettings(enabled=True, model="model"), transport=forbidden)
