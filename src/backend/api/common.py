"""Shared API helpers."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path

from ..utils.paths import repo_root as _repo_root


def repo_root() -> Path:
    return _repo_root()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def cors_origins() -> list[str]:
    raw = os.getenv("LEMON_CORS_ORIGINS", "").strip()
    if raw:
        return [origin.strip() for origin in raw.split(",") if origin.strip()]
    return [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
