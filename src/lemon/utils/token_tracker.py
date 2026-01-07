"""Token tracking utilities.

Token usage is persisted to `tokens.json` at the repo root.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from .logging import get_logger

logger = get_logger(__name__)

TOKENS_FILE = Path(__file__).resolve().parents[3] / "tokens.json"


@dataclass
class TokenStats:
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    request_count: int = 0

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.total_output_tokens


def load_token_tracking() -> Dict[str, Any]:
    """Load cumulative token usage from `tokens.json`."""
    if TOKENS_FILE.exists():
        try:
            with open(TOKENS_FILE, "r") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
                return {}
        except Exception:
            pass
    return {
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_tokens": 0,
        "request_count": 0,
    }


def save_token_tracking(token_data: Dict[str, Any]) -> None:
    """Persist token usage totals to `tokens.json`."""
    try:
        with open(TOKENS_FILE, "w") as f:
            json.dump(token_data, f, indent=2)
    except Exception as e:
        logger.warning(
            "Could not save token tracking", extra={"path": str(TOKENS_FILE), "error": str(e)}
        )


def track_tokens(response: Any) -> Dict[str, Any]:
    """Update token tracking totals using an Anthropic response object."""
    if hasattr(response, "usage"):
        usage = response.usage
        input_tokens = getattr(usage, "input_tokens", 0)
        output_tokens = getattr(usage, "output_tokens", 0)
    else:
        input_tokens = getattr(response, "input_tokens", 0)
        output_tokens = getattr(response, "output_tokens", 0)

    token_data = load_token_tracking()
    token_data["total_input_tokens"] += input_tokens
    token_data["total_output_tokens"] += output_tokens
    token_data["total_tokens"] = (
        token_data["total_input_tokens"] + token_data["total_output_tokens"]
    )
    token_data["request_count"] += 1
    save_token_tracking(token_data)
    return token_data


def get_token_stats() -> Dict[str, Any]:
    """Get current cumulative token usage statistics."""
    return load_token_tracking()
