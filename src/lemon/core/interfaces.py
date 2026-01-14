"""Interfaces (Protocols) for LEMON v2 services.

This module defines abstract interfaces that services must implement.
Using Protocols allows for easy mocking in tests and swapping implementations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Protocol, runtime_checkable

if TYPE_CHECKING:
    from lemon.core.blocks import Workflow, WorkflowSummary


# -----------------------------------------------------------------------------
# Filters for querying
# -----------------------------------------------------------------------------


class WorkflowFilters:
    """Filters for querying workflows."""

    def __init__(
        self,
        domain: Optional[str] = None,
        tags: Optional[List[str]] = None,
        has_input: Optional[str] = None,
        has_input_type: Optional[str] = None,
        has_output: Optional[str] = None,
        min_validation: Optional[float] = None,
        max_validation: Optional[float] = None,
        creator_id: Optional[str] = None,
        name_contains: Optional[str] = None,
        is_validated: Optional[bool] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        self.domain = domain
        self.tags = tags
        self.has_input = has_input
        self.has_input_type = has_input_type
        self.has_output = has_output
        self.min_validation = min_validation
        self.max_validation = max_validation
        self.creator_id = creator_id
        self.name_contains = name_contains
        self.is_validated = is_validated
        self.limit = limit
        self.offset = offset

    def is_empty(self) -> bool:
        """Check if no filters are set."""
        return all(
            v is None
            for v in [
                self.domain,
                self.tags,
                self.has_input,
                self.has_input_type,
                self.has_output,
                self.min_validation,
                self.max_validation,
                self.creator_id,
                self.name_contains,
                self.is_validated,
            ]
        )


# -----------------------------------------------------------------------------
# Repository Protocol
# -----------------------------------------------------------------------------


@runtime_checkable
class WorkflowRepository(Protocol):
    """Interface for workflow persistence.

    Implementations:
    - SQLiteWorkflowRepository: SQLite-backed storage
    - InMemoryWorkflowRepository: For testing
    """

    def save(self, workflow: "Workflow") -> str:
        """Save a workflow, return its ID.

        If workflow.id already exists, this updates it.
        """
        ...

    def get(self, workflow_id: str) -> Optional["Workflow"]:
        """Get a workflow by ID, or None if not found."""
        ...

    def delete(self, workflow_id: str) -> bool:
        """Delete a workflow by ID. Returns True if deleted, False if not found."""
        ...

    def list(self, filters: Optional[WorkflowFilters] = None) -> List["WorkflowSummary"]:
        """List workflows matching filters."""
        ...

    def exists(self, workflow_id: str) -> bool:
        """Check if a workflow exists."""
        ...

    def update_validation(
        self, workflow_id: str, score: float, count: int
    ) -> bool:
        """Update validation score and count for a workflow."""
        ...


# -----------------------------------------------------------------------------
# Search Service Protocol
# -----------------------------------------------------------------------------


@runtime_checkable
class SearchService(Protocol):
    """Interface for searching the workflow library."""

    def search(self, filters: WorkflowFilters) -> List["WorkflowSummary"]:
        """Search workflows matching filters."""
        ...

    def list_domains(self) -> List[str]:
        """Get all unique domains."""
        ...

    def list_tags(self) -> List[str]:
        """Get all unique tags."""
        ...

    def find_by_input(self, input_name: str) -> List["WorkflowSummary"]:
        """Find workflows that have a specific input."""
        ...

    def find_by_output(self, output_value: str) -> List["WorkflowSummary"]:
        """Find workflows that produce a specific output."""
        ...

    def find_composable(
        self, required_outputs: List[str]
    ) -> List["WorkflowSummary"]:
        """Find workflows that could provide the required outputs."""
        ...


# -----------------------------------------------------------------------------
# Executor Protocol
# -----------------------------------------------------------------------------


class ExecutionResult:
    """Result of executing a workflow."""

    def __init__(
        self,
        output: Optional[str] = None,
        path: Optional[List[str]] = None,
        error: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ):
        self.output = output
        self.path = path or []
        self.error = error
        self.context = context or {}

    @property
    def success(self) -> bool:
        return self.error is None and self.output is not None


@runtime_checkable
class WorkflowExecutor(Protocol):
    """Interface for executing workflows."""

    def execute(
        self, workflow: "Workflow", inputs: Dict[str, Any]
    ) -> ExecutionResult:
        """Execute a workflow with given inputs."""
        ...

    def validate_inputs(
        self, workflow: "Workflow", inputs: Dict[str, Any]
    ) -> List[str]:
        """Validate inputs against workflow schema. Returns list of errors."""
        ...


# -----------------------------------------------------------------------------
# Validation Session Protocol
# -----------------------------------------------------------------------------


class ValidationCase:
    """A case to be validated by a human."""

    def __init__(self, case_id: str, inputs: Dict[str, Any]):
        self.id = case_id
        self.inputs = inputs


class ValidationAnswer:
    """Human's answer for a validation case."""

    def __init__(
        self,
        case_id: str,
        user_answer: str,
        workflow_output: str,
        matched: bool,
    ):
        self.case_id = case_id
        self.user_answer = user_answer
        self.workflow_output = workflow_output
        self.matched = matched


class ValidationScore:
    """Score from a validation session."""

    def __init__(self, matches: int, total: int):
        self.matches = matches
        self.total = total

    @property
    def score(self) -> float:
        if self.total == 0:
            return 0.0
        return (self.matches / self.total) * 100

    @property
    def confidence(self) -> str:
        if self.total < 10:
            return "low"
        elif self.total < 50:
            return "medium"
        else:
            return "high"


@runtime_checkable
class ValidationSessionManager(Protocol):
    """Interface for managing validation sessions."""

    def start_session(
        self, workflow_id: str, case_count: int = 20
    ) -> str:
        """Start a new validation session. Returns session ID."""
        ...

    def get_current_case(self, session_id: str) -> Optional[ValidationCase]:
        """Get the current case to validate."""
        ...

    def submit_answer(
        self, session_id: str, user_answer: str
    ) -> ValidationAnswer:
        """Submit answer for current case, advance to next."""
        ...

    def get_score(self, session_id: str) -> ValidationScore:
        """Get current validation score."""
        ...

    def complete_session(self, session_id: str) -> ValidationScore:
        """Complete session and update workflow validation."""
        ...
