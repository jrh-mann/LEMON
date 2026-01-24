"""Shared filesystem paths for backend storage."""

from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def lemon_data_dir(repo_root_path: Path | None = None) -> Path:
    raw = os.getenv("LEMON_DATA_DIR", "").strip()
    if raw:
        path = Path(raw)
        if not path.is_absolute():
            base = repo_root_path or repo_root()
            path = (base / path).resolve()
        return path
    base = repo_root_path or repo_root()
    return base / ".lemon"
