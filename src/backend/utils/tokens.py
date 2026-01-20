"""Token usage tracking helpers."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List

_LOCK = Lock()
_SESSION_ID = os.environ.get("LEMON_TOKEN_SESSION_ID") or uuid.uuid4().hex
_SESSION_STARTED_AT = datetime.now(timezone.utc).isoformat()


def _repo_root() -> Path:
    return Path(__file__).parent.parent.parent.parent


def _tokens_summary_path() -> Path:
    env_path = os.environ.get("LEMON_TOKENS_FILE")
    if env_path:
        return Path(env_path)
    return _repo_root() / ".lemon" / "tokens.json"

def _tokens_log_path() -> Path:
    env_path = os.environ.get("LEMON_TOKENS_LOG_FILE")
    if env_path:
        return Path(env_path)
    return _repo_root() / ".lemon" / "tokens_usage.json"


def _empty_usage() -> Dict[str, int]:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }


def _load_json_list(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return []
        loaded = json.loads(raw)
        return loaded if isinstance(loaded, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _update_summary(entry: Dict[str, Any]) -> None:
    summary_path = _tokens_summary_path()
    summary: Dict[str, Any] = {}
    if summary_path.exists():
        try:
            raw = summary_path.read_text(encoding="utf-8").strip()
            if raw:
                loaded = json.loads(raw)
                if isinstance(loaded, dict):
                    summary = loaded
        except (OSError, json.JSONDecodeError):
            summary = {}

    total_usage = summary.get("total") if isinstance(summary.get("total"), dict) else _empty_usage()
    recent_usage = summary.get("recent_session") if isinstance(summary.get("recent_session"), dict) else _empty_usage()

    if summary.get("recent_session_id") != _SESSION_ID:
        recent_usage = _empty_usage()

    usage = entry.get("usage")
    if isinstance(usage, dict):
        for key, value in usage.items():
            if not isinstance(value, int):
                continue
            total_usage[key] = int(total_usage.get(key, 0)) + value
            recent_usage[key] = int(recent_usage.get(key, 0)) + value

    summary = {
        "total": total_usage,
        "recent_session": recent_usage,
        "recent_session_id": _SESSION_ID,
        "recent_session_started_at": _SESSION_STARTED_AT,
        "updated_at": entry.get("timestamp") or datetime.now(timezone.utc).isoformat(),
    }
    _write_json(summary_path, summary)


def record_token_usage(entry: Dict[str, Any]) -> None:
    entry = dict(entry)
    entry.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    entry.setdefault("session_id", _SESSION_ID)
    log_path = _tokens_log_path()

    with _LOCK:
        log_entries = _load_json_list(log_path)
        log_entries.append(entry)
        _write_json(log_path, log_entries)
        _update_summary(entry)
