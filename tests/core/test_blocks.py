"""Tests for core block models.

Tests cover:
- Block creation and validation
- Workflow serialization roundtrip
- Connection validation
- Metadata and validation scoring
"""

import pytest
from datetime import datetime
from pydantic import ValidationError

from lemon.core.blocks import (
    Block,
    BlockType,
    InputBlock,
    DecisionBlock,
    OutputBlock,
    WorkflowRefBlock,
    InputType,
    Range,
    Position,
    Connection,
    PortType,
    Workflow,
    WorkflowMetadata,
    WorkflowSummary,
    ValidationConfidence,
)


# -----------------------------------------------------------------------------
# InputBlock Tests
# -----------------------------------------------------------------------------


class TestInputBlock:
    """Tests for InputBlock model."""

    def test_create_int_input(self):
        """Can create an integer input block."""
        block = InputBlock(
            name="age",
            input_type=InputType.INT,
            range=Range(min=0, max=120),
        )
        assert block.name == "age"
        assert block.input_type == InputType.INT
        assert block.range.min == 0
        assert block.range.max == 120
        assert block.type == BlockType.INPUT

    def test_create_enum_input(self):
        """Can create an enum input block."""
        block = InputBlock(
            name="status",
            input_type=InputType.ENUM,
            enum_values=["active", "inactive", "pending"],
        )
        assert block.name == "status"
        assert block.input_type == InputType.ENUM
        assert block.enum_values == ["active", "inactive", "pending"]

    def test_enum_requires_values(self):
        """Enum input must have enum_values."""
        with pytest.raises(ValidationError) as exc_info:
            InputBlock(name="status", input_type=InputType.ENUM)
        assert "enum_values required" in str(exc_info.value)

    def test_numeric_rejects_enum_values(self):
        """Numeric inputs should not have enum_values."""
        with pytest.raises(ValidationError) as exc_info:
            InputBlock(
                name="age",
                input_type=InputType.INT,
                enum_values=["a", "b"],
            )
        assert "should not be set for numeric types" in str(exc_info.value)

    def test_input_block_has_unique_id(self):
        """Each input block gets a unique ID."""
        block1 = InputBlock(name="a", input_type=InputType.INT)
        block2 = InputBlock(name="b", input_type=InputType.INT)
        assert block1.id != block2.id

    def test_input_block_default_position(self):
        """Input block has default position (0, 0)."""
        block = InputBlock(name="x", input_type=InputType.INT)
        assert block.position.x == 0.0
        assert block.position.y == 0.0

    def test_input_block_custom_position(self):
        """Can set custom position."""
        block = InputBlock(
            name="x",
            input_type=InputType.INT,
            position=Position(x=100, y=200),
        )
        assert block.position.x == 100
        assert block.position.y == 200


# -----------------------------------------------------------------------------
# DecisionBlock Tests
# -----------------------------------------------------------------------------


class TestDecisionBlock:
    """Tests for DecisionBlock model."""

    def test_create_decision(self):
        """Can create a decision block."""
        block = DecisionBlock(condition="age >= 18")
        assert block.condition == "age >= 18"
        assert block.type == BlockType.DECISION

    def test_decision_strips_whitespace(self):
        """Condition is stripped of whitespace."""
        block = DecisionBlock(condition="  age >= 18  ")
        assert block.condition == "age >= 18"

    def test_decision_rejects_empty(self):
        """Empty condition is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            DecisionBlock(condition="")
        assert "cannot be empty" in str(exc_info.value)

    def test_decision_rejects_whitespace_only(self):
        """Whitespace-only condition is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            DecisionBlock(condition="   ")
        assert "cannot be empty" in str(exc_info.value)


# -----------------------------------------------------------------------------
# OutputBlock Tests
# -----------------------------------------------------------------------------


class TestOutputBlock:
    """Tests for OutputBlock model."""

    def test_create_output(self):
        """Can create an output block."""
        block = OutputBlock(value="approved")
        assert block.value == "approved"
        assert block.type == BlockType.OUTPUT

    def test_output_strips_whitespace(self):
        """Output value is stripped."""
        block = OutputBlock(value="  approved  ")
        assert block.value == "approved"

    def test_output_rejects_empty(self):
        """Empty output is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            OutputBlock(value="")
        assert "cannot be empty" in str(exc_info.value)


# -----------------------------------------------------------------------------
# WorkflowRefBlock Tests
# -----------------------------------------------------------------------------


class TestWorkflowRefBlock:
    """Tests for WorkflowRefBlock model."""

    def test_create_ref(self):
        """Can create a workflow reference block."""
        block = WorkflowRefBlock(
            ref_id="ckd-staging-123",
            input_mapping={"eGFR": "egfr_value"},
            output_name="ckd_stage",
        )
        assert block.ref_id == "ckd-staging-123"
        assert block.input_mapping == {"eGFR": "egfr_value"}
        assert block.output_name == "ckd_stage"
        assert block.type == BlockType.WORKFLOW_REF

    def test_ref_rejects_empty_id(self):
        """Empty ref_id is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            WorkflowRefBlock(ref_id="")
        assert "cannot be empty" in str(exc_info.value)

    def test_ref_default_output_name(self):
        """Default output_name is 'result'."""
        block = WorkflowRefBlock(ref_id="abc")
        assert block.output_name == "result"


# -----------------------------------------------------------------------------
# Range Tests
# -----------------------------------------------------------------------------


class TestRange:
    """Tests for Range model."""

    def test_valid_range(self):
        """Can create a valid range."""
        r = Range(min=0, max=100)
        assert r.min == 0
        assert r.max == 100

    def test_range_min_only(self):
        """Can have min without max."""
        r = Range(min=0)
        assert r.min == 0
        assert r.max is None

    def test_range_max_only(self):
        """Can have max without min."""
        r = Range(max=100)
        assert r.min is None
        assert r.max == 100

    def test_range_invalid_min_greater_than_max(self):
        """Rejects min > max."""
        with pytest.raises(ValidationError) as exc_info:
            Range(min=100, max=0)
        assert "cannot be greater than max" in str(exc_info.value)


# -----------------------------------------------------------------------------
# Connection Tests
# -----------------------------------------------------------------------------


class TestConnection:
    """Tests for Connection model."""

    def test_create_connection(self):
        """Can create a connection."""
        conn = Connection(
            from_block="block-1",
            to_block="block-2",
        )
        assert conn.from_block == "block-1"
        assert conn.to_block == "block-2"
        assert conn.from_port == PortType.DEFAULT
        assert conn.to_port == PortType.DEFAULT

    def test_connection_with_ports(self):
        """Can specify ports."""
        conn = Connection(
            from_block="decision-1",
            from_port=PortType.TRUE,
            to_block="output-1",
        )
        assert conn.from_port == PortType.TRUE

    def test_connection_rejects_self_loop(self):
        """Cannot connect block to itself."""
        with pytest.raises(ValidationError) as exc_info:
            Connection(from_block="block-1", to_block="block-1")
        assert "self-loop" in str(exc_info.value)


# -----------------------------------------------------------------------------
# WorkflowMetadata Tests
# -----------------------------------------------------------------------------


class TestWorkflowMetadata:
    """Tests for WorkflowMetadata model."""

    def test_create_metadata(self):
        """Can create metadata."""
        meta = WorkflowMetadata(
            name="Test Workflow",
            domain="testing",
            tags=["test", "example"],
        )
        assert meta.name == "Test Workflow"
        assert meta.domain == "testing"
        assert meta.tags == ["test", "example"]

    def test_validation_score_range(self):
        """Validation score must be 0-100."""
        meta = WorkflowMetadata(name="Test", validation_score=50.0)
        assert meta.validation_score == 50.0

        with pytest.raises(ValidationError):
            WorkflowMetadata(name="Test", validation_score=101.0)

        with pytest.raises(ValidationError):
            WorkflowMetadata(name="Test", validation_score=-1.0)

    def test_confidence_none(self):
        """Zero validations = no confidence."""
        meta = WorkflowMetadata(name="Test", validation_count=0)
        assert meta.confidence == ValidationConfidence.NONE

    def test_confidence_low(self):
        """<10 validations = low confidence."""
        meta = WorkflowMetadata(name="Test", validation_count=5)
        assert meta.confidence == ValidationConfidence.LOW

    def test_confidence_medium(self):
        """10-49 validations = medium confidence."""
        meta = WorkflowMetadata(name="Test", validation_count=30)
        assert meta.confidence == ValidationConfidence.MEDIUM

    def test_confidence_high(self):
        """50+ validations = high confidence."""
        meta = WorkflowMetadata(name="Test", validation_count=100)
        assert meta.confidence == ValidationConfidence.HIGH

    def test_is_validated_true(self):
        """Validated = score >= 80 AND medium+ confidence."""
        meta = WorkflowMetadata(
            name="Test",
            validation_score=85.0,
            validation_count=20,
        )
        assert meta.is_validated is True

    def test_is_validated_false_low_score(self):
        """Not validated if score < 80."""
        meta = WorkflowMetadata(
            name="Test",
            validation_score=75.0,
            validation_count=20,
        )
        assert meta.is_validated is False

    def test_is_validated_false_low_count(self):
        """Not validated if count < 10."""
        meta = WorkflowMetadata(
            name="Test",
            validation_score=90.0,
            validation_count=5,
        )
        assert meta.is_validated is False


# -----------------------------------------------------------------------------
# Workflow Tests
# -----------------------------------------------------------------------------


class TestWorkflow:
    """Tests for Workflow model."""

    @pytest.fixture
    def simple_workflow(self):
        """Create a simple workflow for testing."""
        input_block = InputBlock(
            id="input-age",
            name="age",
            input_type=InputType.INT,
            range=Range(min=0, max=120),
        )
        decision_block = DecisionBlock(
            id="decision-adult",
            condition="age >= 18",
        )
        output_adult = OutputBlock(id="output-adult", value="adult")
        output_minor = OutputBlock(id="output-minor", value="minor")

        connections = [
            Connection(from_block="input-age", to_block="decision-adult"),
            Connection(
                from_block="decision-adult",
                from_port=PortType.TRUE,
                to_block="output-adult",
            ),
            Connection(
                from_block="decision-adult",
                from_port=PortType.FALSE,
                to_block="output-minor",
            ),
        ]

        return Workflow(
            id="test-workflow",
            metadata=WorkflowMetadata(name="Adult Check"),
            blocks=[input_block, decision_block, output_adult, output_minor],
            connections=connections,
        )

    def test_create_workflow(self, simple_workflow):
        """Can create a workflow."""
        assert simple_workflow.id == "test-workflow"
        assert len(simple_workflow.blocks) == 4
        assert len(simple_workflow.connections) == 3

    def test_workflow_input_blocks(self, simple_workflow):
        """Can get input blocks."""
        inputs = simple_workflow.input_blocks
        assert len(inputs) == 1
        assert inputs[0].name == "age"

    def test_workflow_output_blocks(self, simple_workflow):
        """Can get output blocks."""
        outputs = simple_workflow.output_blocks
        assert len(outputs) == 2
        assert set(o.value for o in outputs) == {"adult", "minor"}

    def test_workflow_decision_blocks(self, simple_workflow):
        """Can get decision blocks."""
        decisions = simple_workflow.decision_blocks
        assert len(decisions) == 1
        assert decisions[0].condition == "age >= 18"

    def test_workflow_input_names(self, simple_workflow):
        """Can get input names."""
        assert simple_workflow.input_names == ["age"]

    def test_workflow_output_values(self, simple_workflow):
        """Can get output values."""
        assert set(simple_workflow.output_values) == {"adult", "minor"}

    def test_workflow_get_block(self, simple_workflow):
        """Can get block by ID."""
        block = simple_workflow.get_block("input-age")
        assert block is not None
        assert isinstance(block, InputBlock)
        assert block.name == "age"

    def test_workflow_get_block_not_found(self, simple_workflow):
        """Returns None for non-existent block."""
        assert simple_workflow.get_block("nonexistent") is None

    def test_workflow_get_connections_from(self, simple_workflow):
        """Can get connections from a block."""
        conns = simple_workflow.get_connections_from("decision-adult")
        assert len(conns) == 2

    def test_workflow_get_connections_to(self, simple_workflow):
        """Can get connections to a block."""
        conns = simple_workflow.get_connections_to("decision-adult")
        assert len(conns) == 1

    def test_workflow_validates_connection_blocks(self):
        """Workflow rejects connections to non-existent blocks."""
        with pytest.raises(ValidationError) as exc_info:
            Workflow(
                metadata=WorkflowMetadata(name="Bad"),
                blocks=[InputBlock(id="a", name="x", input_type=InputType.INT)],
                connections=[Connection(from_block="a", to_block="nonexistent")],
            )
        assert "non-existent block" in str(exc_info.value)

    def test_workflow_serialization_roundtrip(self, simple_workflow):
        """Workflow can be serialized to JSON and back."""
        json_str = simple_workflow.model_dump_json()
        restored = Workflow.model_validate_json(json_str)

        assert restored.id == simple_workflow.id
        assert restored.metadata.name == simple_workflow.metadata.name
        assert len(restored.blocks) == len(simple_workflow.blocks)
        assert len(restored.connections) == len(simple_workflow.connections)

    def test_workflow_with_ref_block(self):
        """Workflow can contain workflow reference blocks."""
        ref_block = WorkflowRefBlock(
            id="ref-ckd",
            ref_id="ckd-staging-abc",
            input_mapping={"eGFR": "egfr"},
        )
        workflow = Workflow(
            metadata=WorkflowMetadata(name="With Ref"),
            blocks=[ref_block],
        )
        assert len(workflow.workflow_ref_blocks) == 1
        assert workflow.referenced_workflow_ids == ["ckd-staging-abc"]


# -----------------------------------------------------------------------------
# WorkflowSummary Tests
# -----------------------------------------------------------------------------


class TestWorkflowSummary:
    """Tests for WorkflowSummary model."""

    def test_from_workflow(self):
        """Can create summary from workflow."""
        workflow = Workflow(
            id="test-123",
            metadata=WorkflowMetadata(
                name="Test",
                domain="testing",
                validation_score=85.0,
                validation_count=25,
            ),
            blocks=[
                InputBlock(name="x", input_type=InputType.INT),
                OutputBlock(value="done"),
            ],
        )

        summary = WorkflowSummary.from_workflow(workflow)

        assert summary.id == "test-123"
        assert summary.name == "Test"
        assert summary.domain == "testing"
        assert summary.validation_score == 85.0
        assert summary.validation_count == 25
        assert summary.confidence == ValidationConfidence.MEDIUM
        assert summary.is_validated is True
        assert summary.input_names == ["x"]
        assert summary.output_values == ["done"]


# -----------------------------------------------------------------------------
# Block Discrimination Tests
# -----------------------------------------------------------------------------


class TestBlockDiscrimination:
    """Tests for block type discrimination during deserialization."""

    def test_deserialize_mixed_blocks(self):
        """Different block types deserialize correctly from JSON."""
        workflow_data = {
            "id": "test",
            "metadata": {"name": "Test"},
            "blocks": [
                {"id": "1", "type": "input", "name": "x", "input_type": "int"},
                {"id": "2", "type": "decision", "condition": "x > 5"},
                {"id": "3", "type": "output", "value": "yes"},
                {"id": "4", "type": "output", "value": "no"},
            ],
            "connections": [
                {"from_block": "1", "to_block": "2"},
                {"from_block": "2", "from_port": "true", "to_block": "3"},
                {"from_block": "2", "from_port": "false", "to_block": "4"},
            ],
        }

        workflow = Workflow.model_validate(workflow_data)

        assert len(workflow.blocks) == 4
        assert isinstance(workflow.blocks[0], InputBlock)
        assert isinstance(workflow.blocks[1], DecisionBlock)
        assert isinstance(workflow.blocks[2], OutputBlock)
        assert isinstance(workflow.blocks[3], OutputBlock)
