"""Application settings.

All configuration is sourced from environment variables (and optionally `.env`).
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed environment-backed settings for LEMON."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    endpoint: str = Field(alias="ENDPOINT")
    deployment_name: str = Field(alias="DEPLOYMENT_NAME")
    api_key: str = Field(alias="API_KEY")
    e2b_api_key: str = Field(alias="E2B_API_KEY")

    # Optional secondary model used by test-case labeling.
    haiku_deployment_name: str | None = Field(default=None, alias="HAIKU_DEPLOYMENT_NAME")



