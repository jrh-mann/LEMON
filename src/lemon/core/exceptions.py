"""Custom exception hierarchy for LEMON."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class LEMONException(Exception):
    """Base exception type for all LEMON errors."""

    message: str
    context: Optional[Dict[str, Any]] = None

    def __str__(self) -> str:
        if not self.context:
            return self.message
        return f"{self.message} | context={self.context}"


class ConfigurationError(LEMONException):
    """Raised when configuration is missing or invalid."""


class WorkflowAnalysisError(LEMONException):
    """Raised when workflow analysis fails or cannot be parsed."""


class CodeGenerationError(LEMONException):
    """Raised when code generation fails or produces invalid code."""


class TestExecutionError(LEMONException):
    """Raised when sandbox execution or scoring fails."""
