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


# -----------------------------------------------------------------------------
# V2 Exceptions (Block-based workflows)
# -----------------------------------------------------------------------------


class WorkflowNotFoundError(LEMONException):
    """Raised when a workflow is not found in the repository."""


class WorkflowValidationError(LEMONException):
    """Raised when a workflow fails validation (invalid structure)."""


class ExecutionError(LEMONException):
    """Raised when workflow execution fails."""


class MissingInputError(ExecutionError):
    """Raised when required inputs are missing during execution."""


class InputTypeError(ExecutionError):
    """Raised when input has wrong type during execution."""


class InvalidConditionError(ExecutionError):
    """Raised when a decision condition is invalid or unsafe."""


class CircularReferenceError(ExecutionError):
    """Raised when workflow references form a cycle."""


class UnknownVariableError(ExecutionError):
    """Raised when condition references an unknown variable."""


class ValidationSessionError(LEMONException):
    """Raised when validation session operations fail."""


class SessionNotFoundError(ValidationSessionError):
    """Raised when validation session is not found."""


class SessionCompletedError(ValidationSessionError):
    """Raised when trying to operate on a completed session."""
