"""Validation session management.

This module manages the state of validation sessions - the "Tinder-style"
interface where humans validate workflow outputs case by case.

Session flow:
1. Start session for a workflow (generates cases)
2. Get current case (shows inputs to user)
3. User submits their expected output
4. System executes workflow, compares, records result
5. Advance to next case
6. Repeat until all cases validated
7. Complete session, update workflow validation score
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, TYPE_CHECKING
from uuid import uuid4

from lemon.core.exceptions import SessionNotFoundError, SessionCompletedError
from lemon.validation.case_generator import CaseGenerator, ValidationCase
from lemon.validation.scoring import ValidationScore, calculate_score

if TYPE_CHECKING:
    from lemon.core.blocks import Workflow
    from lemon.storage.repository import SQLiteWorkflowRepository, InMemoryWorkflowRepository
    from lemon.execution.executor import WorkflowExecutor

    Repository = SQLiteWorkflowRepository | InMemoryWorkflowRepository


def generate_session_id() -> str:
    """Generate a unique session ID."""
    return uuid4().hex[:12]


@dataclass
class ValidationAnswer:
    """Record of a single validation answer."""
    case_id: str
    user_answer: str
    workflow_output: str
    matched: bool
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "user_answer": self.user_answer,
            "workflow_output": self.workflow_output,
            "matched": self.matched,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class ValidationSession:
    """A validation session for a workflow."""
    id: str
    workflow_id: str
    cases: List[ValidationCase]
    answers: List[ValidationAnswer] = field(default_factory=list)
    current_index: int = 0
    status: Literal["in_progress", "completed", "abandoned"] = "in_progress"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_complete(self) -> bool:
        """Whether all cases have been answered."""
        return self.current_index >= len(self.cases)

    @property
    def progress(self) -> Dict[str, int]:
        """Get progress information."""
        return {
            "current": self.current_index,
            "total": len(self.cases),
            "remaining": len(self.cases) - self.current_index,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "workflow_id": self.workflow_id,
            "status": self.status,
            "progress": self.progress,
            "created_at": self.created_at.isoformat(),
        }


class ValidationSessionManager:
    """Manages validation sessions.

    This is the main interface for the Tinder-style validation flow.

    Usage:
        manager = ValidationSessionManager(repo, executor)

        # Start session
        session_id = manager.start_session("workflow-id", case_count=20)

        # Validation loop
        while case := manager.get_current_case(session_id):
            print(f"Inputs: {case.inputs}")
            user_answer = input("What should the output be? ")
            result = manager.submit_answer(session_id, user_answer)
            print(f"{'Match!' if result.matched else 'Mismatch'}")

        # Complete and get score
        score = manager.complete_session(session_id)
        print(f"Score: {score.score}%")
    """

    def __init__(
        self,
        repository: "Repository",
        executor: "WorkflowExecutor",
        case_generator: Optional[CaseGenerator] = None,
    ):
        """Initialize session manager.

        Args:
            repository: Repository for loading/updating workflows.
            executor: Executor for running workflows.
            case_generator: Optional custom case generator.
        """
        self.repository = repository
        self.executor = executor
        self.case_generator = case_generator or CaseGenerator()
        self._sessions: Dict[str, ValidationSession] = {}

    def start_session(
        self,
        workflow_id: str,
        case_count: int = 20,
        strategy: Literal["random", "boundary", "comprehensive"] = "comprehensive",
    ) -> str:
        """Start a new validation session.

        Args:
            workflow_id: ID of workflow to validate.
            case_count: Number of cases to generate.
            strategy: Case generation strategy.

        Returns:
            Session ID.

        Raises:
            WorkflowNotFoundError: If workflow not found.
        """
        workflow = self.repository.get(workflow_id)
        if workflow is None:
            from lemon.core.exceptions import WorkflowNotFoundError
            raise WorkflowNotFoundError(
                f"Workflow not found: {workflow_id}",
                context={"workflow_id": workflow_id},
            )

        # Generate cases based on strategy
        if strategy == "random":
            cases = self.case_generator.generate(workflow, count=case_count)
        elif strategy == "boundary":
            cases = self.case_generator.generate_boundary(workflow)
        else:  # comprehensive
            cases = self.case_generator.generate_comprehensive(
                workflow, random_count=case_count
            )

        # Create session
        session = ValidationSession(
            id=generate_session_id(),
            workflow_id=workflow_id,
            cases=cases,
        )
        self._sessions[session.id] = session

        return session.id

    def get_session(self, session_id: str) -> ValidationSession:
        """Get a session by ID.

        Args:
            session_id: Session ID.

        Returns:
            The session.

        Raises:
            SessionNotFoundError: If session not found.
        """
        if session_id not in self._sessions:
            raise SessionNotFoundError(
                f"Session not found: {session_id}",
                context={"session_id": session_id},
            )
        return self._sessions[session_id]

    def get_current_case(self, session_id: str) -> Optional[ValidationCase]:
        """Get the current case to validate.

        Args:
            session_id: Session ID.

        Returns:
            Current case, or None if session complete.

        Raises:
            SessionNotFoundError: If session not found.
        """
        session = self.get_session(session_id)

        if session.status == "completed":
            return None

        if session.is_complete:
            return None

        return session.cases[session.current_index]

    def submit_answer(
        self,
        session_id: str,
        user_answer: str,
    ) -> ValidationAnswer:
        """Submit user's answer for current case.

        Executes the workflow, compares output to user's answer,
        records the result, and advances to the next case.

        Args:
            session_id: Session ID.
            user_answer: User's expected output.

        Returns:
            ValidationAnswer with match result.

        Raises:
            SessionNotFoundError: If session not found.
            SessionCompletedError: If session already completed.
        """
        session = self.get_session(session_id)

        if session.status == "completed":
            raise SessionCompletedError(
                "Session already completed",
                context={"session_id": session_id},
            )

        if session.is_complete:
            raise SessionCompletedError(
                "All cases already answered",
                context={"session_id": session_id},
            )

        # Get current case
        case = session.cases[session.current_index]

        # Load workflow and execute
        workflow = self.repository.get(session.workflow_id)
        if workflow is None:
            from lemon.core.exceptions import WorkflowNotFoundError
            raise WorkflowNotFoundError(
                f"Workflow not found: {session.workflow_id}",
                context={"workflow_id": session.workflow_id},
            )

        result = self.executor.execute(workflow, case.inputs)

        # Get workflow output (or error message)
        if result.success:
            workflow_output = result.output or ""
        else:
            workflow_output = f"ERROR: {result.error}"

        # Compare (case-insensitive, trimmed)
        matched = self._compare_outputs(user_answer, workflow_output)

        # Record answer
        answer = ValidationAnswer(
            case_id=case.id,
            user_answer=user_answer.strip(),
            workflow_output=workflow_output,
            matched=matched,
        )
        session.answers.append(answer)

        # Advance to next case
        session.current_index += 1

        return answer

    def skip_case(self, session_id: str) -> bool:
        """Skip the current case without answering.

        Args:
            session_id: Session ID.

        Returns:
            True if skipped, False if no more cases.
        """
        session = self.get_session(session_id)

        if session.is_complete:
            return False

        session.current_index += 1
        return True

    def get_score(self, session_id: str) -> ValidationScore:
        """Get current validation score.

        Args:
            session_id: Session ID.

        Returns:
            Current score based on answered cases.
        """
        session = self.get_session(session_id)
        return calculate_score(session.answers)

    def complete_session(self, session_id: str) -> ValidationScore:
        """Complete the session and update workflow validation.

        Marks the session as completed and updates the workflow's
        validation score in the repository.

        Args:
            session_id: Session ID.

        Returns:
            Final validation score.
        """
        session = self.get_session(session_id)

        if session.status == "completed":
            return calculate_score(session.answers)

        # Mark as completed
        session.status = "completed"

        # Calculate score
        score = calculate_score(session.answers)

        # Update workflow in repository
        workflow = self.repository.get(session.workflow_id)
        if workflow:
            # Combine with existing validations
            existing_matches = int(
                workflow.metadata.validation_score / 100 * workflow.metadata.validation_count
            ) if workflow.metadata.validation_count > 0 else 0

            new_matches = existing_matches + score.matches
            new_total = workflow.metadata.validation_count + score.total

            if new_total > 0:
                new_score = (new_matches / new_total) * 100
            else:
                new_score = 0.0

            self.repository.update_validation(
                session.workflow_id,
                score=new_score,
                count=new_total,
            )

        return score

    def abandon_session(self, session_id: str) -> None:
        """Abandon a session without completing.

        Args:
            session_id: Session ID.
        """
        session = self.get_session(session_id)
        session.status = "abandoned"

    def _compare_outputs(self, user_answer: str, workflow_output: str) -> bool:
        """Compare user answer to workflow output.

        Comparison is case-insensitive and ignores leading/trailing whitespace.

        Args:
            user_answer: What the user said the output should be.
            workflow_output: What the workflow actually produced.

        Returns:
            True if they match.
        """
        return user_answer.strip().lower() == workflow_output.strip().lower()
