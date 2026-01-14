"""Tests for WorkflowExecutor.

Tests cover:
- Simple workflow execution
- Decision branching
- Input validation
- WorkflowRefBlock execution
- Circular reference detection
- Tracing
"""

import pytest

from lemon.core.blocks import (
    InputBlock,
    DecisionBlock,
    OutputBlock,
    WorkflowRefBlock,
    InputType,
    Range,
    Connection,
    PortType,
    Workflow,
    WorkflowMetadata,
)
from lemon.storage.repository import InMemoryWorkflowRepository
from lemon.execution.executor import WorkflowExecutor, ExecutionResult


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def repo():
    """Fresh in-memory repository."""
    return InMemoryWorkflowRepository()


@pytest.fixture
def executor(repo):
    """Executor with repository."""
    return WorkflowExecutor(repo)


@pytest.fixture
def executor_no_repo():
    """Executor without repository."""
    return WorkflowExecutor()


@pytest.fixture
def simple_workflow():
    """Simple workflow: age >= 18 -> adult/minor."""
    return Workflow(
        id="age-check",
        metadata=WorkflowMetadata(name="Age Check"),
        blocks=[
            InputBlock(id="input-age", name="age", input_type=InputType.INT, range=Range(min=0, max=120)),
            DecisionBlock(id="decision", condition="age >= 18"),
            OutputBlock(id="output-adult", value="adult"),
            OutputBlock(id="output-minor", value="minor"),
        ],
        connections=[
            Connection(from_block="input-age", to_block="decision"),
            Connection(from_block="decision", from_port=PortType.TRUE, to_block="output-adult"),
            Connection(from_block="decision", from_port=PortType.FALSE, to_block="output-minor"),
        ],
    )


@pytest.fixture
def multi_decision_workflow():
    """Workflow with multiple decisions."""
    return Workflow(
        id="multi-decision",
        metadata=WorkflowMetadata(name="Multi Decision"),
        blocks=[
            InputBlock(id="input-score", name="score", input_type=InputType.INT),
            DecisionBlock(id="d1", condition="score >= 90"),
            DecisionBlock(id="d2", condition="score >= 70"),
            DecisionBlock(id="d3", condition="score >= 50"),
            OutputBlock(id="out-a", value="A"),
            OutputBlock(id="out-b", value="B"),
            OutputBlock(id="out-c", value="C"),
            OutputBlock(id="out-f", value="F"),
        ],
        connections=[
            Connection(from_block="input-score", to_block="d1"),
            Connection(from_block="d1", from_port=PortType.TRUE, to_block="out-a"),
            Connection(from_block="d1", from_port=PortType.FALSE, to_block="d2"),
            Connection(from_block="d2", from_port=PortType.TRUE, to_block="out-b"),
            Connection(from_block="d2", from_port=PortType.FALSE, to_block="d3"),
            Connection(from_block="d3", from_port=PortType.TRUE, to_block="out-c"),
            Connection(from_block="d3", from_port=PortType.FALSE, to_block="out-f"),
        ],
    )


@pytest.fixture
def child_workflow():
    """Child workflow to be referenced."""
    return Workflow(
        id="child-workflow",
        metadata=WorkflowMetadata(name="Child"),
        blocks=[
            InputBlock(id="c-input", name="x", input_type=InputType.INT),
            DecisionBlock(id="c-decision", condition="x > 10"),
            OutputBlock(id="c-out-high", value="high"),
            OutputBlock(id="c-out-low", value="low"),
        ],
        connections=[
            Connection(from_block="c-input", to_block="c-decision"),
            Connection(from_block="c-decision", from_port=PortType.TRUE, to_block="c-out-high"),
            Connection(from_block="c-decision", from_port=PortType.FALSE, to_block="c-out-low"),
        ],
    )


@pytest.fixture
def parent_workflow_with_ref():
    """Parent workflow that references child."""
    return Workflow(
        id="parent-workflow",
        metadata=WorkflowMetadata(name="Parent"),
        blocks=[
            InputBlock(id="p-input", name="value", input_type=InputType.INT),
            WorkflowRefBlock(
                id="p-ref",
                ref_id="child-workflow",
                input_mapping={"x": "value"},
                output_name="child_result",
            ),
            DecisionBlock(id="p-decision", condition="child_result == 'high'"),
            OutputBlock(id="p-out-yes", value="qualified"),
            OutputBlock(id="p-out-no", value="not qualified"),
        ],
        connections=[
            Connection(from_block="p-input", to_block="p-ref"),
            Connection(from_block="p-ref", to_block="p-decision"),
            Connection(from_block="p-decision", from_port=PortType.TRUE, to_block="p-out-yes"),
            Connection(from_block="p-decision", from_port=PortType.FALSE, to_block="p-out-no"),
        ],
    )


# -----------------------------------------------------------------------------
# Basic Execution Tests
# -----------------------------------------------------------------------------


class TestBasicExecution:
    """Tests for basic workflow execution."""

    def test_execute_true_branch(self, executor, simple_workflow):
        """Executes true branch when condition is met."""
        result = executor.execute(simple_workflow, {"age": 25})
        assert result.success
        assert result.output == "adult"

    def test_execute_false_branch(self, executor, simple_workflow):
        """Executes false branch when condition is not met."""
        result = executor.execute(simple_workflow, {"age": 15})
        assert result.success
        assert result.output == "minor"

    def test_execute_boundary_value(self, executor, simple_workflow):
        """Boundary value (exactly 18) goes to true branch."""
        result = executor.execute(simple_workflow, {"age": 18})
        assert result.success
        assert result.output == "adult"

    def test_execute_records_path(self, executor, simple_workflow):
        """Path through workflow is recorded."""
        result = executor.execute(simple_workflow, {"age": 25})
        assert "decision" in result.path
        assert "output-adult" in result.path

    def test_execute_multi_decision(self, executor, multi_decision_workflow):
        """Multiple decisions work correctly."""
        assert executor.execute(multi_decision_workflow, {"score": 95}).output == "A"
        assert executor.execute(multi_decision_workflow, {"score": 85}).output == "B"
        assert executor.execute(multi_decision_workflow, {"score": 60}).output == "C"
        assert executor.execute(multi_decision_workflow, {"score": 30}).output == "F"


# -----------------------------------------------------------------------------
# Input Validation Tests
# -----------------------------------------------------------------------------


class TestInputValidation:
    """Tests for input validation."""

    def test_missing_required_input(self, executor, simple_workflow):
        """Missing required input returns error."""
        result = executor.execute(simple_workflow, {})
        assert not result.success
        assert "Missing required input" in result.error

    def test_wrong_input_type(self, executor, simple_workflow):
        """Wrong input type returns error."""
        result = executor.execute(simple_workflow, {"age": "twenty"})
        assert not result.success
        assert "must be an integer" in result.error

    def test_value_below_range(self, executor, simple_workflow):
        """Value below range returns error."""
        result = executor.execute(simple_workflow, {"age": -5})
        assert not result.success
        assert "below minimum" in result.error

    def test_value_above_range(self, executor, simple_workflow):
        """Value above range returns error."""
        result = executor.execute(simple_workflow, {"age": 150})
        assert not result.success
        assert "above maximum" in result.error

    def test_validate_inputs_method(self, executor, simple_workflow):
        """validate_inputs method returns errors list."""
        errors = executor.validate_inputs(simple_workflow, {})
        assert len(errors) > 0
        assert "Missing required input" in errors[0]

    def test_validate_inputs_valid(self, executor, simple_workflow):
        """validate_inputs returns empty list for valid inputs."""
        errors = executor.validate_inputs(simple_workflow, {"age": 25})
        assert errors == []

    def test_enum_validation(self, executor):
        """Enum values are validated."""
        workflow = Workflow(
            id="enum-test",
            metadata=WorkflowMetadata(name="Enum Test"),
            blocks=[
                InputBlock(
                    id="input-status",
                    name="status",
                    input_type=InputType.ENUM,
                    enum_values=["active", "inactive"],
                ),
                OutputBlock(id="out", value="done"),
            ],
            connections=[
                Connection(from_block="input-status", to_block="out"),
            ],
        )

        # Valid enum value
        errors = executor.validate_inputs(workflow, {"status": "active"})
        assert errors == []

        # Invalid enum value
        errors = executor.validate_inputs(workflow, {"status": "pending"})
        assert len(errors) > 0
        assert "not in allowed values" in errors[0]


# -----------------------------------------------------------------------------
# WorkflowRef Tests
# -----------------------------------------------------------------------------


class TestWorkflowRef:
    """Tests for WorkflowRefBlock execution."""

    def test_execute_with_ref(self, executor, repo, child_workflow, parent_workflow_with_ref):
        """Parent workflow executes child via ref."""
        repo.save(child_workflow)

        # value=15 -> child returns "high" -> parent returns "qualified"
        result = executor.execute(parent_workflow_with_ref, {"value": 15})
        assert result.success
        assert result.output == "qualified"

        # value=5 -> child returns "low" -> parent returns "not qualified"
        result = executor.execute(parent_workflow_with_ref, {"value": 5})
        assert result.success
        assert result.output == "not qualified"

    def test_execute_ref_missing_workflow(self, executor, parent_workflow_with_ref):
        """Returns error when referenced workflow not found."""
        # Don't save child workflow
        result = executor.execute(parent_workflow_with_ref, {"value": 15})
        assert not result.success
        assert "not found" in result.error

    def test_execute_ref_without_repo(self, executor_no_repo, parent_workflow_with_ref):
        """Returns error when no repository available."""
        result = executor_no_repo.execute(parent_workflow_with_ref, {"value": 15})
        assert not result.success
        assert "no repository" in result.error

    def test_circular_reference_detection(self, executor, repo):
        """Detects circular references."""
        # Create workflow that references itself
        circular = Workflow(
            id="circular",
            metadata=WorkflowMetadata(name="Circular"),
            blocks=[
                InputBlock(id="in", name="x", input_type=InputType.INT),
                WorkflowRefBlock(id="ref", ref_id="circular", input_mapping={"x": "x"}),
                OutputBlock(id="out", value="done"),
            ],
            connections=[
                Connection(from_block="in", to_block="ref"),
                Connection(from_block="ref", to_block="out"),
            ],
        )
        repo.save(circular)

        result = executor.execute(circular, {"x": 5})
        assert not result.success
        assert "Circular reference" in result.error


# -----------------------------------------------------------------------------
# Tracing Tests
# -----------------------------------------------------------------------------


class TestTracing:
    """Tests for execution tracing."""

    def test_trace_records_steps(self, executor, simple_workflow):
        """Trace includes all steps."""
        trace = executor.trace(simple_workflow, {"age": 25})
        assert trace.result.success
        assert len(trace.steps) > 0

    def test_trace_includes_decision_info(self, executor, simple_workflow):
        """Trace includes decision results."""
        trace = executor.trace(simple_workflow, {"age": 25})

        decision_steps = [s for s in trace.steps if s.get("action") == "decision"]
        assert len(decision_steps) == 1
        assert decision_steps[0]["condition"] == "age >= 18"
        assert decision_steps[0]["result"] is True

    def test_trace_shows_path(self, executor, simple_workflow):
        """Trace result includes path."""
        trace = executor.trace(simple_workflow, {"age": 25})
        assert "decision" in trace.result.path
        assert "output-adult" in trace.result.path


# -----------------------------------------------------------------------------
# Edge Cases
# -----------------------------------------------------------------------------


class TestEdgeCases:
    """Tests for edge cases."""

    def test_output_only_workflow(self, executor):
        """Workflow with only output block."""
        workflow = Workflow(
            id="output-only",
            metadata=WorkflowMetadata(name="Output Only"),
            blocks=[
                OutputBlock(id="out", value="static output"),
            ],
            connections=[],
        )

        result = executor.execute(workflow, {})
        assert result.success
        assert result.output == "static output"

    def test_empty_workflow(self, executor):
        """Workflow with no blocks returns error."""
        workflow = Workflow(
            id="empty",
            metadata=WorkflowMetadata(name="Empty"),
            blocks=[],
            connections=[],
        )

        result = executor.execute(workflow, {})
        assert not result.success
        assert "no executable blocks" in result.error

    def test_input_only_workflow(self, executor):
        """Workflow with only input blocks returns error."""
        workflow = Workflow(
            id="input-only",
            metadata=WorkflowMetadata(name="Input Only"),
            blocks=[
                InputBlock(id="in", name="x", input_type=InputType.INT),
            ],
            connections=[],
        )

        result = executor.execute(workflow, {"x": 5})
        assert not result.success
        # Should return error about no output

    def test_float_input(self, executor):
        """Float inputs work correctly."""
        workflow = Workflow(
            id="float-test",
            metadata=WorkflowMetadata(name="Float Test"),
            blocks=[
                InputBlock(id="input", name="egfr", input_type=InputType.FLOAT, range=Range(min=0, max=200)),
                DecisionBlock(id="decision", condition="egfr < 45"),
                OutputBlock(id="out-low", value="low"),
                OutputBlock(id="out-ok", value="ok"),
            ],
            connections=[
                Connection(from_block="input", to_block="decision"),
                Connection(from_block="decision", from_port=PortType.TRUE, to_block="out-low"),
                Connection(from_block="decision", from_port=PortType.FALSE, to_block="out-ok"),
            ],
        )

        assert executor.execute(workflow, {"egfr": 30.5}).output == "low"
        assert executor.execute(workflow, {"egfr": 60.0}).output == "ok"

    def test_boolean_input(self, executor):
        """Boolean inputs work correctly."""
        workflow = Workflow(
            id="bool-test",
            metadata=WorkflowMetadata(name="Bool Test"),
            blocks=[
                InputBlock(id="input", name="is_admin", input_type=InputType.BOOL),
                DecisionBlock(id="decision", condition="is_admin"),
                OutputBlock(id="out-yes", value="admin"),
                OutputBlock(id="out-no", value="user"),
            ],
            connections=[
                Connection(from_block="input", to_block="decision"),
                Connection(from_block="decision", from_port=PortType.TRUE, to_block="out-yes"),
                Connection(from_block="decision", from_port=PortType.FALSE, to_block="out-no"),
            ],
        )

        assert executor.execute(workflow, {"is_admin": True}).output == "admin"
        assert executor.execute(workflow, {"is_admin": False}).output == "user"
