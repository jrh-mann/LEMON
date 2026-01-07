"""Logging configuration.

LEMON uses standard library `logging` with a small convenience wrapper:
- `configure_logging()` sets up root logging once.
- `get_logger()` returns a module logger.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, is_dataclass
from typing import Any, Mapping, Optional


class JsonLogFormatter(logging.Formatter):
    """Minimal JSON formatter for machine-readable logs."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Include `extra=` fields if present
        for key, value in record.__dict__.items():
            if key.startswith("_"):
                continue
            if key in {
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
            }:
                continue

            if is_dataclass(value) and not isinstance(value, type):
                payload[key] = asdict(value)
            else:
                payload[key] = value

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)


def configure_logging(
    *,
    level: str = "INFO",
    json_logs: bool = False,
    extra: Optional[Mapping[str, Any]] = None,
) -> None:
    """Configure root logging once.

    Args:
        level: Root log level (e.g. 'INFO', 'DEBUG').
        json_logs: If True, emit JSON logs; otherwise emit plain text.
        extra: Optional key-value pairs to attach to *all* log records.
    """
    root = logging.getLogger()
    if root.handlers:
        return

    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter() if json_logs else logging.Formatter("%(message)s"))
    root.addHandler(handler)
    root.setLevel(level.upper())

    if extra:
        logging.LoggerAdapter(root, dict(extra))


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
