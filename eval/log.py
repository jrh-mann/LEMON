"""Log: save and load EvalResult as JSON files."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from .harness import EvalResult, ToolCallRecord, TokenUsage

# Default log directory.
_LOG_DIR = Path(__file__).resolve().parent / "logs"


def _sanitize_for_json(obj: Any) -> Any:
    """Recursively convert non-serializable types."""
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, bytes):
        return f"<{len(obj)} bytes>"
    if isinstance(obj, set):
        return list(obj)
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_for_json(v) for v in obj]
    return obj


def save_result(result: EvalResult, log_dir: Path = _LOG_DIR) -> Path:
    """Save an EvalResult to a JSON file. Returns the file path."""
    log_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    filename = f"{timestamp}_{result.model}_{result.sample_name}_run{result.run_id}.json"
    path = log_dir / filename

    # Build serializable dict.
    data = {
        "sample_name": result.sample_name,
        "model": result.model,
        "model_id": result.model_id,
        "run_id": result.run_id,
        "error": result.error,
        "wall_time_s": round(result.wall_time_s, 2),
        "cost_usd": round(result.cost_usd, 4),
        "tokens": {
            "input_tokens": result.tokens.input_tokens,
            "output_tokens": result.tokens.output_tokens,
            "cache_creation_input_tokens": result.tokens.cache_creation_input_tokens,
            "cache_read_input_tokens": result.tokens.cache_read_input_tokens,
            "total_tokens": result.tokens.total_tokens,
            "llm_calls": result.tokens.llm_calls,
        },
        "workflow": _sanitize_for_json(result.workflow),
        "tool_calls": [
            {
                "tool_name": tc.tool_name,
                "args": _sanitize_for_json(tc.args),
                "result": _sanitize_for_json(tc.result),
                "success": tc.success,
                "timestamp": round(tc.timestamp, 2),
            }
            for tc in result.tool_calls
        ],
        "llm_response": result.llm_response,
        "transcript": _sanitize_for_json(result.transcript),
        "scores": result.scores.summary_dict() if result.scores else None,
        "summary": result.summary_dict(),
    }

    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return path


def save_summary_csv(results: List[EvalResult], log_dir: Path = _LOG_DIR) -> Path:
    """Save a summary CSV from a batch of results. Returns the file path."""
    log_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    path = log_dir / f"summary_{timestamp}.csv"

    if not results:
        path.write_text("", encoding="utf-8")
        return path

    rows = [r.summary_dict() for r in results]
    headers = list(rows[0].keys())

    lines = [",".join(headers)]
    for row in rows:
        lines.append(",".join(str(row.get(h, "")) for h in headers))

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
