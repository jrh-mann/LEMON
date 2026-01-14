"""Tests for validation session management."""

import pytest
from unittest.mock import Mock, MagicMock
from datetime import datetime, timezone

from lemon.core.blocks import (
    Workflow, WorkflowMetadata, InputBlock, DecisionBlock, OutputBlock,
    Connection, InputType, Range, PortType
)
from lemon.core.exceptions import SessionNotFoundError, SessionCompletedError, WorkflowNotFoundError
from lemon.execution.executor import WorkflowExecutor, ExecutionResult
from lemon.storage.repository import InMemoryWorkflowRepository
from lemon.validation.session import (
    ValidationSessionManager,
    ValidationSession,
    ValidationAnswer,
    generate_session_id,
)
from lemon.validation.case_generator import CaseGenerator, ValidationCase
from lemon.validation.scoring import ValidationScore


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def age_workflow() -> Workflow:
    """Simple age classification workflow."""
    return Workflow(
        id="age-classifier",
        metadata=WorkflowMetadata(
            name="Age Classifier",
            description="Classifies by age",
            domain="test",
        ),
        blocks=[
            InputBlock(
                id="input1",
                name="age",
                input_type=InputType.INT,
                range=Range(min=0, max=120),
            ),
            DecisionBlock(id="decision1", condition="age >= 18"),
            OutputBlock(id="output1", value="Adult"),
            OutputBlock(id="output2", value="Minor"),
        ],
        connections=[
            Connection(from_block="input1", to_block="decision1"),
            Connection(from_block="decision1", to_block="output1", from_port=PortType.TRUE),
            Connection(from_block="decision1", to_block="output2", from_port=PortType.FALSE),
        ],
    )


@pytest.fixture
def repository(age_workflow: Workflow) -> InMemoryWorkflowRepository:
    """Repository with test workflow."""
    repo = InMemoryWorkflowRepository()
    repo.save(age_workflow)
    return repo


@pytest.fixture
def executor() -> WorkflowExecutor:
    """Workflow executor."""
    return WorkflowExecutor()


@pytest.fixture
def manager(repository: InMemoryWorkflowRepository, executor: WorkflowExecutor) -> ValidationSessionManager:
    """Session manager with seeded case generator."""
    generator = CaseGenerator(seed=42)
    return ValidationSessionManager(repository, executor, generator)


# -----------------------------------------------------------------------------
# Test: Session ID Generation
# -----------------------------------------------------------------------------

class TestSessionIdGeneration:
    """Tests for session ID generation."""

    def test_generates_unique_ids(self):
        """Session IDs should be unique."""
        ids = [generate_session_id() for _ in range(100)]
        assert len(ids) == len(set(ids))

    def test_id_format(self):
        """Session IDs should be 12 character hex strings."""
        session_id = generate_session_id()
        assert len(session_id) == 12
        assert all(c in "0123456789abcdef" for c in session_id)


# -----------------------------------------------------------------------------
# Test: ValidationAnswer
# -----------------------------------------------------------------------------

class TestValidationAnswer:
    """Tests for ValidationAnswer dataclass."""

    def test_to_dict(self):
        """Should serialize to dictionary."""
        answer = ValidationAnswer(
            case_id="case123",
            user_answer="Adult",
            workflow_output="Adult",
            matched=True,
        )
        result = answer.to_dict()

        assert result["case_id"] == "case123"
        assert result["user_answer"] == "Adult"
        assert result["workflow_output"] == "Adult"
        assert result["matched"] is True
        assert "timestamp" in result


# -----------------------------------------------------------------------------
# Test: ValidationSession
# -----------------------------------------------------------------------------

class TestValidationSession:
    """Tests for ValidationSession dataclass."""

    def test_is_complete_false(self):
        """Should not be complete when cases remain."""
        session = ValidationSession(
            id="test123",
            workflow_id="wf1",
            cases=[ValidationCase(id="c1", inputs={}), ValidationCase(id="c2", inputs={})],
            current_index=0,
        )
        assert session.is_complete is False

    def test_is_complete_true(self):
        """Should be complete when all cases answered."""
        session = ValidationSession(
            id="test123",
            workflow_id="wf1",
            cases=[ValidationCase(id="c1", inputs={})],
            current_index=1,
        )
        assert session.is_complete is True

    def test_progress(self):
        """Should report progress correctly."""
        session = ValidationSession(
            id="test123",
            workflow_id="wf1",
            cases=[ValidationCase(id=f"c{i}", inputs={}) for i in range(10)],
            current_index=3,
        )
        progress = session.progress
        assert progress["current"] == 3
        assert progress["total"] == 10
        assert progress["remaining"] == 7

    def test_to_dict(self):
        """Should serialize to dictionary."""
        session = ValidationSession(
            id="test123",
            workflow_id="wf1",
            cases=[ValidationCase(id="c1", inputs={})],
            status="in_progress",
        )
        result = session.to_dict()

        assert result["id"] == "test123"
        assert result["workflow_id"] == "wf1"
        assert result["status"] == "in_progress"
        assert "progress" in result
        assert "created_at" in result


# -----------------------------------------------------------------------------
# Test: Start Session
# -----------------------------------------------------------------------------

class TestStartSession:
    """Tests for starting validation sessions."""

    def test_start_session_creates_session(self, manager: ValidationSessionManager):
        """Should create a new session."""
        session_id = manager.start_session("age-classifier", case_count=10)

        assert session_id is not None
        session = manager.get_session(session_id)
        assert session.workflow_id == "age-classifier"
        assert session.status == "in_progress"

    def test_start_session_generates_cases(self, manager: ValidationSessionManager):
        """Should generate requested number of cases."""
        session_id = manager.start_session("age-classifier", case_count=15)
        session = manager.get_session(session_id)

        # Comprehensive strategy may generate more or less due to boundary cases
        assert len(session.cases) > 0

    def test_start_session_random_strategy(self, manager: ValidationSessionManager):
        """Should use random strategy when specified."""
        session_id = manager.start_session("age-classifier", case_count=10, strategy="random")
        session = manager.get_session(session_id)

        assert len(session.cases) == 10

    def test_start_session_boundary_strategy(self, manager: ValidationSessionManager):
        """Should use boundary strategy when specified."""
        session_id = manager.start_session("age-classifier", strategy="boundary")
        session = manager.get_session(session_id)

        # Should have boundary cases for age
        ages = [c.inputs["age"] for c in session.cases]
        assert 0 in ages  # min
        assert 120 in ages  # max

    def test_start_session_workflow_not_found(self, manager: ValidationSessionManager):
        """Should raise error for non-existent workflow."""
        with pytest.raises(WorkflowNotFoundError):
            manager.start_session("nonexistent")


# -----------------------------------------------------------------------------
# Test: Get Session
# -----------------------------------------------------------------------------

class TestGetSession:
    """Tests for retrieving sessions."""

    def test_get_existing_session(self, manager: ValidationSessionManager):
        """Should return existing session."""
        session_id = manager.start_session("age-classifier")
        session = manager.get_session(session_id)

        assert session.id == session_id

    def test_get_nonexistent_session(self, manager: ValidationSessionManager):
        """Should raise error for non-existent session."""
        with pytest.raises(SessionNotFoundError):
            manager.get_session("nonexistent")


# -----------------------------------------------------------------------------
# Test: Get Current Case
# -----------------------------------------------------------------------------

class TestGetCurrentCase:
    """Tests for getting current case."""

    def test_get_first_case(self, manager: ValidationSessionManager):
        """Should return first case initially."""
        session_id = manager.start_session("age-classifier", case_count=5, strategy="random")
        case = manager.get_current_case(session_id)

        assert case is not None
        assert "age" in case.inputs

    def test_get_none_when_complete(self, manager: ValidationSessionManager):
        """Should return None when session is complete."""
        session_id = manager.start_session("age-classifier", case_count=1, strategy="random")

        # Answer the only case
        manager.submit_answer(session_id, "Adult")

        # Should return None now
        case = manager.get_current_case(session_id)
        assert case is None

    def test_get_none_when_completed_status(self, manager: ValidationSessionManager):
        """Should return None when session status is completed."""
        session_id = manager.start_session("age-classifier", case_count=1, strategy="random")
        manager.submit_answer(session_id, "Adult")
        manager.complete_session(session_id)

        case = manager.get_current_case(session_id)
        assert case is None


# -----------------------------------------------------------------------------
# Test: Submit Answer
# -----------------------------------------------------------------------------

class TestSubmitAnswer:
    """Tests for submitting answers."""

    def test_submit_matching_answer(self, manager: ValidationSessionManager):
        """Should detect matching answers."""
        session_id = manager.start_session("age-classifier", case_count=1, strategy="random")
        session = manager.get_session(session_id)

        # Get current case and expected output
        case = session.cases[0]
        age = case.inputs["age"]
        expected = "Adult" if age >= 18 else "Minor"

        answer = manager.submit_answer(session_id, expected)

        assert answer.matched is True
        assert answer.user_answer == expected
        assert answer.workflow_output == expected

    def test_submit_mismatching_answer(self, manager: ValidationSessionManager):
        """Should detect mismatching answers."""
        session_id = manager.start_session("age-classifier", case_count=1, strategy="random")
        session = manager.get_session(session_id)

        case = session.cases[0]
        age = case.inputs["age"]
        # Give the wrong answer
        wrong = "Minor" if age >= 18 else "Adult"

        answer = manager.submit_answer(session_id, wrong)

        assert answer.matched is False

    def test_submit_advances_index(self, manager: ValidationSessionManager):
        """Should advance to next case after submit."""
        session_id = manager.start_session("age-classifier", case_count=3, strategy="random")
        session = manager.get_session(session_id)

        assert session.current_index == 0
        manager.submit_answer(session_id, "Adult")
        assert session.current_index == 1

    def test_submit_records_answer(self, manager: ValidationSessionManager):
        """Should record answer in session."""
        session_id = manager.start_session("age-classifier", case_count=2, strategy="random")

        manager.submit_answer(session_id, "Adult")
        manager.submit_answer(session_id, "Minor")

        session = manager.get_session(session_id)
        assert len(session.answers) == 2

    def test_submit_to_completed_session(self, manager: ValidationSessionManager):
        """Should raise error when session is completed."""
        session_id = manager.start_session("age-classifier", case_count=1, strategy="random")
        manager.submit_answer(session_id, "Adult")
        manager.complete_session(session_id)

        with pytest.raises(SessionCompletedError):
            manager.submit_answer(session_id, "Adult")

    def test_submit_case_insensitive_comparison(self, manager: ValidationSessionManager):
        """Should compare case-insensitively."""
        session_id = manager.start_session("age-classifier", case_count=1, strategy="random")
        session = manager.get_session(session_id)

        case = session.cases[0]
        age = case.inputs["age"]
        expected = "adult" if age >= 18 else "minor"  # lowercase

        answer = manager.submit_answer(session_id, expected)

        assert answer.matched is True

    def test_submit_trims_whitespace(self, manager: ValidationSessionManager):
        """Should trim whitespace from answers."""
        session_id = manager.start_session("age-classifier", case_count=1, strategy="random")
        session = manager.get_session(session_id)

        case = session.cases[0]
        age = case.inputs["age"]
        expected = "  Adult  " if age >= 18 else "  Minor  "  # with whitespace

        answer = manager.submit_answer(session_id, expected)

        assert answer.matched is True


# -----------------------------------------------------------------------------
# Test: Skip Case
# -----------------------------------------------------------------------------

class TestSkipCase:
    """Tests for skipping cases."""

    def test_skip_advances_index(self, manager: ValidationSessionManager):
        """Should advance to next case."""
        session_id = manager.start_session("age-classifier", case_count=3, strategy="random")
        session = manager.get_session(session_id)

        assert session.current_index == 0
        result = manager.skip_case(session_id)
        assert result is True
        assert session.current_index == 1

    def test_skip_returns_false_when_complete(self, manager: ValidationSessionManager):
        """Should return False when no more cases."""
        session_id = manager.start_session("age-classifier", case_count=1, strategy="random")

        manager.skip_case(session_id)
        result = manager.skip_case(session_id)

        assert result is False

    def test_skip_does_not_record_answer(self, manager: ValidationSessionManager):
        """Should not record answer when skipping."""
        session_id = manager.start_session("age-classifier", case_count=2, strategy="random")

        manager.skip_case(session_id)

        session = manager.get_session(session_id)
        assert len(session.answers) == 0


# -----------------------------------------------------------------------------
# Test: Get Score
# -----------------------------------------------------------------------------

class TestGetScore:
    """Tests for getting current score."""

    def test_score_empty_session(self, manager: ValidationSessionManager):
        """Should return zero score for no answers."""
        session_id = manager.start_session("age-classifier", case_count=5, strategy="random")
        score = manager.get_score(session_id)

        assert score.matches == 0
        assert score.total == 0

    def test_score_with_answers(self, manager: ValidationSessionManager):
        """Should calculate score from answers."""
        session_id = manager.start_session("age-classifier", case_count=2, strategy="random")
        session = manager.get_session(session_id)

        # Submit correct answer for first case
        case1 = session.cases[0]
        correct1 = "Adult" if case1.inputs["age"] >= 18 else "Minor"
        manager.submit_answer(session_id, correct1)

        # Submit wrong answer for second case
        case2 = session.cases[1]
        wrong2 = "Minor" if case2.inputs["age"] >= 18 else "Adult"
        manager.submit_answer(session_id, wrong2)

        score = manager.get_score(session_id)
        assert score.matches == 1
        assert score.total == 2
        assert score.score == 50.0


# -----------------------------------------------------------------------------
# Test: Complete Session
# -----------------------------------------------------------------------------

class TestCompleteSession:
    """Tests for completing sessions."""

    def test_complete_marks_session_completed(self, manager: ValidationSessionManager):
        """Should mark session as completed."""
        session_id = manager.start_session("age-classifier", case_count=1, strategy="random")
        manager.submit_answer(session_id, "Adult")

        manager.complete_session(session_id)

        session = manager.get_session(session_id)
        assert session.status == "completed"

    def test_complete_returns_score(self, manager: ValidationSessionManager):
        """Should return final score."""
        session_id = manager.start_session("age-classifier", case_count=2, strategy="random")
        session = manager.get_session(session_id)

        # Submit two correct answers
        for case in session.cases:
            correct = "Adult" if case.inputs["age"] >= 18 else "Minor"
            manager.submit_answer(session_id, correct)

        score = manager.complete_session(session_id)

        assert score.matches == 2
        assert score.total == 2
        assert score.score == 100.0

    def test_complete_updates_workflow_validation(
        self,
        manager: ValidationSessionManager,
        repository: InMemoryWorkflowRepository
    ):
        """Should update workflow validation score."""
        session_id = manager.start_session("age-classifier", case_count=2, strategy="random")
        session = manager.get_session(session_id)

        # Submit correct answers
        for case in session.cases:
            correct = "Adult" if case.inputs["age"] >= 18 else "Minor"
            manager.submit_answer(session_id, correct)

        manager.complete_session(session_id)

        # Check workflow was updated
        workflow = repository.get("age-classifier")
        assert workflow.metadata.validation_count == 2
        assert workflow.metadata.validation_score == 100.0

    def test_complete_accumulates_validation(
        self,
        manager: ValidationSessionManager,
        repository: InMemoryWorkflowRepository
    ):
        """Should accumulate validation across sessions."""
        # First session: 2 matches, 2 total
        session1_id = manager.start_session("age-classifier", case_count=2, strategy="random")
        session1 = manager.get_session(session1_id)
        for case in session1.cases:
            correct = "Adult" if case.inputs["age"] >= 18 else "Minor"
            manager.submit_answer(session1_id, correct)
        manager.complete_session(session1_id)

        # Second session: 1 match, 2 total
        session2_id = manager.start_session("age-classifier", case_count=2, strategy="random")
        session2 = manager.get_session(session2_id)
        # First answer correct
        correct = "Adult" if session2.cases[0].inputs["age"] >= 18 else "Minor"
        manager.submit_answer(session2_id, correct)
        # Second answer wrong
        wrong = "Minor" if session2.cases[1].inputs["age"] >= 18 else "Adult"
        manager.submit_answer(session2_id, wrong)
        manager.complete_session(session2_id)

        # Total: 3 matches, 4 total = 75%
        workflow = repository.get("age-classifier")
        assert workflow.metadata.validation_count == 4
        assert workflow.metadata.validation_score == 75.0

    def test_complete_already_completed(self, manager: ValidationSessionManager):
        """Should return score for already completed session."""
        session_id = manager.start_session("age-classifier", case_count=1, strategy="random")
        manager.submit_answer(session_id, "Adult")

        score1 = manager.complete_session(session_id)
        score2 = manager.complete_session(session_id)

        assert score1.total == score2.total


# -----------------------------------------------------------------------------
# Test: Abandon Session
# -----------------------------------------------------------------------------

class TestAbandonSession:
    """Tests for abandoning sessions."""

    def test_abandon_marks_session_abandoned(self, manager: ValidationSessionManager):
        """Should mark session as abandoned."""
        session_id = manager.start_session("age-classifier", case_count=5, strategy="random")

        manager.abandon_session(session_id)

        session = manager.get_session(session_id)
        assert session.status == "abandoned"

    def test_abandon_nonexistent_session(self, manager: ValidationSessionManager):
        """Should raise error for non-existent session."""
        with pytest.raises(SessionNotFoundError):
            manager.abandon_session("nonexistent")


# -----------------------------------------------------------------------------
# Test: Output Comparison
# -----------------------------------------------------------------------------

class TestOutputComparison:
    """Tests for output comparison logic."""

    def test_exact_match(self, manager: ValidationSessionManager):
        """Should match exact strings."""
        assert manager._compare_outputs("Adult", "Adult") is True

    def test_case_insensitive(self, manager: ValidationSessionManager):
        """Should match case-insensitively."""
        assert manager._compare_outputs("adult", "ADULT") is True
        assert manager._compare_outputs("Adult", "adult") is True

    def test_whitespace_trimmed(self, manager: ValidationSessionManager):
        """Should trim whitespace."""
        assert manager._compare_outputs("  Adult  ", "Adult") is True
        assert manager._compare_outputs("Adult", "  Adult  ") is True

    def test_different_strings(self, manager: ValidationSessionManager):
        """Should not match different strings."""
        assert manager._compare_outputs("Adult", "Minor") is False
        assert manager._compare_outputs("Yes", "No") is False


# -----------------------------------------------------------------------------
# Test: Error Handling
# -----------------------------------------------------------------------------

class TestErrorHandling:
    """Tests for error handling in sessions."""

    def test_workflow_deleted_during_session(self, manager: ValidationSessionManager, repository: InMemoryWorkflowRepository):
        """Should handle workflow deletion during session."""
        session_id = manager.start_session("age-classifier", case_count=2, strategy="random")

        # Delete workflow
        repository.delete("age-classifier")

        # Should raise error when submitting
        with pytest.raises(WorkflowNotFoundError):
            manager.submit_answer(session_id, "Adult")
