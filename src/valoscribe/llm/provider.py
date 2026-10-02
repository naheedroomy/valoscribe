"""Provider-neutral structured response contract and deterministic fake."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel, TypeAdapter

T = TypeVar("T", bound=BaseModel)


class StructuredLLM(Protocol):
    """Generate a response validated against the requested Pydantic model."""

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
    ) -> T: ...


@dataclass(frozen=True)
class LLMCall:
    """Inputs captured for one fake-provider invocation."""

    system_prompt: str
    user_prompt: str
    response_model: type[BaseModel]


@dataclass(frozen=True)
class _ScriptedOutput:
    value: object
    raw: bool


class FakeLLMProvider:
    """Return scripted values deterministically without network access."""

    def __init__(self, outputs: list[object] | None = None) -> None:
        self._outputs: deque[_ScriptedOutput] = deque(
            _ScriptedOutput(value=output, raw=False) for output in outputs or []
        )
        self.calls: list[LLMCall] = []

    def queue_output(self, output: object) -> None:
        """Queue a value that will be validated against the requested model."""
        self._outputs.append(_ScriptedOutput(value=output, raw=False))

    def queue_raw_output(self, output: object) -> None:
        """Queue raw data to exercise Pydantic validation failures deterministically."""
        self._outputs.append(_ScriptedOutput(value=output, raw=True))

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
    ) -> T:
        self.calls.append(
            LLMCall(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=response_model,
            )
        )
        if not self._outputs:
            raise RuntimeError("FakeLLMProvider has no scripted outputs remaining")
        scripted = self._outputs.popleft()
        if scripted.raw:
            return TypeAdapter(response_model).validate_python(scripted.value)
        if isinstance(scripted.value, response_model):
            return scripted.value
        return TypeAdapter(response_model).validate_python(scripted.value)
