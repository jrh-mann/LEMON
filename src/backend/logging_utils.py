"""Logging helpers for the backend."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
from typing import Optional

_CONFIGURED = False


def setup_logging(log_path: Optional[Path] = None) -> Path:
    """Configure backend logging to rotating file handlers."""
    global _CONFIGURED
    if _CONFIGURED:
        return _resolve_log_path(log_path)

    resolved = _resolve_log_path(log_path)
    resolved.parent.mkdir(parents=True, exist_ok=True)

    level_name = os.environ.get("LEMON_LOG_LEVEL", "DEBUG").upper()
    level = getattr(logging, level_name, logging.DEBUG)

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"
    )

    root_handler = RotatingFileHandler(
        resolved,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    root_handler.setFormatter(formatter)

    tool_handler = RotatingFileHandler(
        resolved.parent / "tool_calls.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    tool_handler.setFormatter(formatter)

    llm_handler = RotatingFileHandler(
        resolved.parent / "llm.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    llm_handler.setFormatter(formatter)
    subagent_handler = RotatingFileHandler(
        resolved.parent / "subagent.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    subagent_handler.setFormatter(formatter)
    history_handler = RotatingFileHandler(
        resolved.parent / "history.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    history_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(root_handler)

    _attach_logger("backend.tool_calls", level, tool_handler)
    _attach_logger("backend.llm", level, llm_handler)
    _attach_logger("backend.subagent", level, subagent_handler)
    _attach_logger("backend.history", level, history_handler)

    _CONFIGURED = True
    logging.getLogger(__name__).info("Logging initialized: %s", resolved)
    return resolved


def _resolve_log_path(log_path: Optional[Path]) -> Path:
    if log_path is not None:
        return log_path
    env_path = os.environ.get("LEMON_LOG_FILE")
    if env_path:
        return Path(env_path)
    repo_root = Path(__file__).parent.parent.parent
    return repo_root / ".lemon" / "logs" / "backend.log"


def _attach_logger(name: str, level: int, handler: logging.Handler) -> None:
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.addHandler(handler)
    logger.propagate = False
