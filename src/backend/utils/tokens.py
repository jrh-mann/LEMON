"""Token usage tracking helpers."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List

_LOCK = Lock()


def _repo_root() -> Path:
    return Path(__file__).parent.parent.parent.parent


def _tokens_path() -> Path:
    env_path = os.environ.get("LEMON_TOKENS_FILE")
    if env_path:
        return Path(env_path)
    return _repo_root() / ".lemon" / "tokens.json"


def record_token_usage(entry: Dict[str, Any]) -> None:
    entry = dict(entry)
    entry.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    path = _tokens_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    with _LOCK:
        existing: List[Dict[str, Any]] = []
        if path.exists():
            try:
                raw = path.read_text(encoding="utf-8").strip()
                if raw:
                    loaded = json.loads(raw)
                    if isinstance(loaded, list):
                        existing = loaded
            except (OSError, json.JSONDecodeError):
                existing = []

        existing.append(entry)
        tmp_path = path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(existing, ensure_ascii=True, indent=2), encoding="utf-8")
        tmp_path.replace(path)
