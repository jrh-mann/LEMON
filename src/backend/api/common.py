"""Shared API helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
