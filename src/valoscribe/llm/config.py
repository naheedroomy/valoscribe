"""Typed environment contract for optional LLM configuration; no provider is created."""

from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LLMSettings(BaseModel):
    """LLM configuration defaults, disabled unless explicitly enabled."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    enabled: bool = Field(default=False, validation_alias="LLM_ENABLED")
    provider: Literal["openai_compatible"] = Field(
        default="openai_compatible", validation_alias="LLM_PROVIDER"
    )
    api_key: str = Field(default="", validation_alias="LLM_API_KEY")
    base_url: str = Field(default="", validation_alias="LLM_BASE_URL")
    model: str = Field(default="", validation_alias="LLM_MODEL")
    timeout_seconds: float = Field(default=60, gt=0, validation_alias="LLM_TIMEOUT_SECONDS")
    max_retries: int = Field(default=2, ge=0, validation_alias="LLM_MAX_RETRIES")
    temperature: float = Field(default=0.1, ge=0, le=2, validation_alias="LLM_TEMPERATURE")
    allow_image_upload: bool = Field(default=False, validation_alias="LLM_ALLOW_IMAGE_UPLOAD")
    log_usage: bool = Field(default=True, validation_alias="LLM_LOG_USAGE")

    @classmethod
    def from_environment(cls) -> LLMSettings:
        """Parse supported LLM settings from process environment variables."""
        names = {
            "enabled": "LLM_ENABLED",
            "provider": "LLM_PROVIDER",
            "api_key": "LLM_API_KEY",
            "base_url": "LLM_BASE_URL",
            "model": "LLM_MODEL",
            "timeout_seconds": "LLM_TIMEOUT_SECONDS",
            "max_retries": "LLM_MAX_RETRIES",
            "temperature": "LLM_TEMPERATURE",
            "allow_image_upload": "LLM_ALLOW_IMAGE_UPLOAD",
            "log_usage": "LLM_LOG_USAGE",
        }
        environment = {alias: os.environ[alias] for alias in names.values() if alias in os.environ}
        return cls.model_validate(environment)

    def __init__(self, **data: object) -> None:
        # Environment aliases are intentionally accepted alongside Python field names.
        super().__init__(**data)
