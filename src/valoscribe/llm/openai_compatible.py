"""OpenAI-compatible chat-completions adapter using only the standard library."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import BaseModel, TypeAdapter, ValidationError

from valoscribe.llm.config import LLMSettings

T = TypeVar("T", bound=BaseModel)
LOGGER = logging.getLogger(__name__)
_DEFAULT_BASE_URL = "https://api.openai.com/v1"


class ProviderError(RuntimeError):
    """Provider failed or returned data that could not be safely validated."""


class OpenAICompatibleProvider:
    """Generate validated JSON through the common OpenAI chat-completions subset."""

    def __init__(
        self,
        settings: LLMSettings,
        *,
        transport: Callable[[str, dict[str, str], bytes, float], bytes] | None = None,
    ) -> None:
        if not settings.enabled:
            raise ValueError("LLM provider cannot be created while LLM_ENABLED is false")
        if not settings.api_key.strip() or not settings.model.strip():
            raise ValueError("LLM_API_KEY and LLM_MODEL are required when LLM_ENABLED is true")
        if settings.max_retries > 10:
            raise ValueError("LLM_MAX_RETRIES must not exceed 10")
        self.settings = settings
        base = (settings.base_url.strip() or _DEFAULT_BASE_URL).rstrip("/")
        self.url = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
        self._transport = transport or _urlopen_transport

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
    ) -> T:
        schema = response_model.model_json_schema()
        request_body: dict[str, Any] = {
            "model": self.settings.model,
            "temperature": self.settings.temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": response_model.__name__, "strict": True, "schema": schema},
            },
        }
        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
        }
        body = json.dumps(request_body).encode("utf-8")
        transient_retries = 0
        correction_used = False
        while True:
            try:
                response = self._transport(self.url, headers, body, self.settings.timeout_seconds)
            except ProviderError:
                raise
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                if transient_retries >= self.settings.max_retries or not _transient(error):
                    raise ProviderError("OpenAI-compatible request failed") from error
                time.sleep(min(0.25 * (2**transient_retries), 2.0))
                transient_retries += 1
                continue

            try:
                payload = json.loads(response)
                choices = payload["choices"]
                choice = choices[0]
                if not isinstance(choice, dict):
                    raise TypeError("choice must be an object")
                if "finish_reason" in choice:
                    finish_reason = choice["finish_reason"]
                    if finish_reason == "length":
                        raise ProviderError("Provider response was truncated")
                    if finish_reason != "stop":
                        raise ProviderError("Provider did not finish successfully")
                message = choice["message"]
                if not isinstance(message, dict):
                    raise TypeError("message must be an object")
                if message.get("refusal"):
                    raise ProviderError("Provider refused structured response")
                content = message["content"]
                if not isinstance(content, str):
                    raise ValueError("content must be text")
            except ProviderError:
                raise
            except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as error:
                if not correction_used:
                    correction_used = True
                    request_body["messages"][1]["content"] = (
                        user_prompt + "\n\nYour previous response failed validation. "
                        "Return corrected JSON only; no new evidence. Validation errors: "
                        "invalid JSON or response envelope"
                    )
                    body = json.dumps(request_body).encode("utf-8")
                    continue
                raise ProviderError("Provider returned an invalid response envelope") from error

            try:
                result = TypeAdapter(response_model).validate_json(content)
            except (ValidationError, ValueError) as error:
                if correction_used:
                    raise ProviderError("Provider response failed validation") from error
                correction_used = True
                request_body["messages"][1]["content"] = (
                    user_prompt + "\n\nYour previous response failed validation. "
                    "Return corrected JSON only; no new evidence. Validation errors: "
                    "response did not match the required schema"
                )
                body = json.dumps(request_body).encode("utf-8")
                continue

            usage = payload.get("usage")
            if self.settings.log_usage and isinstance(usage, dict):
                LOGGER.info(
                    "LLM usage model=%s prompt_tokens=%s completion_tokens=%s total_tokens=%s",
                    self.settings.model,
                    usage.get("prompt_tokens"),
                    usage.get("completion_tokens"),
                    usage.get("total_tokens"),
                )
            return result


def _transient(error: BaseException) -> bool:
    if isinstance(error, urllib.error.HTTPError):
        return error.code == 429 or 500 <= error.code <= 599
    return isinstance(error, (TimeoutError, urllib.error.URLError, OSError))


def _urlopen_transport(url: str, headers: dict[str, str], body: bytes, timeout: float) -> bytes:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read()
            if not isinstance(data, bytes):
                raise ProviderError("Provider returned a non-byte response")
            return data
    except urllib.error.HTTPError as error:
        if error.code == 429 or 500 <= error.code <= 599:
            raise
        raise ProviderError(f"Provider returned HTTP {error.code}") from error


def create_llm_provider(settings: LLMSettings, *, transport=None):
    """Return no provider while disabled; validate credentials only when enabled."""
    if not settings.enabled:
        return None
    return OpenAICompatibleProvider(settings, transport=transport)
