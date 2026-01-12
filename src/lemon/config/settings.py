"""Application settings.

All configuration is sourced from environment variables (and optionally `.env`).
"""

from __future__ import annotations

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed environment-backed settings for LEMON."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    endpoint: str = Field(
        validation_alias=AliasChoices("ENDPOINT", "AZURE_OPENAI_ENDPOINT")
    )
    deployment_name: str = Field(
        validation_alias=AliasChoices(
            "DEPLOYMENT_NAME", "AZURE_OPENAI_DEPLOYMENT", "AZURE_OPENAI_DEPLOYMENT_NAME"
        )
    )
    api_key: str = Field(
        validation_alias=AliasChoices("API_KEY", "AZURE_OPENAI_API_KEY")
    )
    e2b_api_key: str = Field(alias="E2B_API_KEY")

    # Azure OpenAI
    azure_openai_api_version: str = Field(
        default="2024-12-01-preview",
        validation_alias=AliasChoices("AZURE_OPENAI_API_VERSION", "API_VERSION"),
    )

    # Optional secondary model used by test-case labeling.
    haiku_deployment_name: str | None = Field(default=None, alias="HAIKU_DEPLOYMENT_NAME")
