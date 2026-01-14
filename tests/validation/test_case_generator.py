"""Tests for validation case generator."""

import pytest
from lemon.core.blocks import (
    Workflow, WorkflowMetadata, InputBlock, DecisionBlock, OutputBlock,
    Connection, InputType, Range, PortType
)
from lemon.validation.case_generator import CaseGenerator, ValidationCase, generate_case_id


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def simple_workflow() -> Workflow:
    """Simple workflow with one int input."""
    return Workflow(
        id="simple-1",
        metadata=WorkflowMetadata(
            name="Simple Workflow",
            description="A simple test workflow",
            domain="test",
        ),
        blocks=[
            InputBlock(
                id="input1",
                name="age",
                input_type=InputType.INT,
                range=Range(min=0, max=120),
            ),
            DecisionBlock(
                id="decision1",
                condition="age >= 18",
            ),
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
def multi_input_workflow() -> Workflow:
    """Workflow with multiple input types."""
    return Workflow(
        id="multi-1",
        metadata=WorkflowMetadata(
            name="Multi-Input Workflow",
            description="Workflow with multiple inputs",
            domain="test",
        ),
        blocks=[
            InputBlock(
                id="input1",
                name="temperature",
                input_type=InputType.FLOAT,
                range=Range(min=35.0, max=42.0),
            ),
            InputBlock(
                id="input2",
                name="has_symptoms",
                input_type=InputType.BOOL,
            ),
            InputBlock(
                id="input3",
                name="severity",
                input_type=InputType.ENUM,
                enum_values=["mild", "moderate", "severe"],
            ),
            InputBlock(
                id="input4",
                name="patient_name",
                input_type=InputType.STRING,
            ),
            DecisionBlock(
                id="decision1",
                condition="temperature > 38.5 and has_symptoms",
            ),
            OutputBlock(id="output1", value="Fever Alert"),
            OutputBlock(id="output2", value="Normal"),
        ],
        connections=[
            Connection(from_block="input1", to_block="decision1"),
            Connection(from_block="input2", to_block="decision1"),
            Connection(from_block="decision1", to_block="output1", from_port=PortType.TRUE),
            Connection(from_block="decision1", to_block="output2", from_port=PortType.FALSE),
        ],
    )


@pytest.fixture
def generator() -> CaseGenerator:
    """Generator with fixed seed for reproducibility."""
    return CaseGenerator(seed=42)


# -----------------------------------------------------------------------------
# Test: Case ID Generation
# -----------------------------------------------------------------------------

class TestCaseIdGeneration:
    """Tests for case ID generation."""

    def test_generates_unique_ids(self):
        """Case IDs should be unique."""
        ids = [generate_case_id() for _ in range(100)]
        assert len(ids) == len(set(ids))

    def test_id_format(self):
        """Case IDs should be 8 character hex strings."""
        case_id = generate_case_id()
        assert len(case_id) == 8
        assert all(c in "0123456789abcdef" for c in case_id)


# -----------------------------------------------------------------------------
# Test: ValidationCase
# -----------------------------------------------------------------------------

class TestValidationCase:
    """Tests for ValidationCase dataclass."""

    def test_to_dict(self):
        """Should serialize to dictionary."""
        case = ValidationCase(
            id="abc12345",
            inputs={"age": 25, "name": "Test"},
        )
        result = case.to_dict()
        assert result == {
            "id": "abc12345",
            "inputs": {"age": 25, "name": "Test"},
        }


# -----------------------------------------------------------------------------
# Test: Random Case Generation
# -----------------------------------------------------------------------------

class TestRandomGeneration:
    """Tests for random case generation."""

    def test_generates_requested_count(self, generator: CaseGenerator, simple_workflow: Workflow):
        """Should generate the requested number of cases."""
        cases = generator.generate(simple_workflow, count=10)
        assert len(cases) == 10

    def test_generates_unique_case_ids(self, generator: CaseGenerator, simple_workflow: Workflow):
        """Each case should have a unique ID."""
        cases = generator.generate(simple_workflow, count=20)
        ids = [c.id for c in cases]
        assert len(ids) == len(set(ids))

    def test_respects_int_range(self, generator: CaseGenerator, simple_workflow: Workflow):
        """Generated int values should be within range."""
        cases = generator.generate(simple_workflow, count=50)
        for case in cases:
            assert 0 <= case.inputs["age"] <= 120

    def test_respects_float_range(self, generator: CaseGenerator, multi_input_workflow: Workflow):
        """Generated float values should be within range."""
        cases = generator.generate(multi_input_workflow, count=50)
        for case in cases:
            assert 35.0 <= case.inputs["temperature"] <= 42.0

    def test_generates_bool_values(self, generator: CaseGenerator, multi_input_workflow: Workflow):
        """Should generate boolean values."""
        cases = generator.generate(multi_input_workflow, count=50)
        values = [c.inputs["has_symptoms"] for c in cases]
        assert all(isinstance(v, bool) for v in values)
        # With 50 cases, should have both True and False
        assert True in values
        assert False in values

    def test_generates_enum_values(self, generator: CaseGenerator, multi_input_workflow: Workflow):
        """Should generate valid enum values."""
        cases = generator.generate(multi_input_workflow, count=50)
        valid_values = {"mild", "moderate", "severe"}
        for case in cases:
            assert case.inputs["severity"] in valid_values

    def test_generates_string_values(self, generator: CaseGenerator, multi_input_workflow: Workflow):
        """Should generate string values."""
        cases = generator.generate(multi_input_workflow, count=10)
        for case in cases:
            assert isinstance(case.inputs["patient_name"], str)
            assert case.inputs["patient_name"].startswith("test_string_")

    def test_seed_reproducibility(self, simple_workflow: Workflow):
        """Same seed should produce same results."""
        gen1 = CaseGenerator(seed=12345)
        gen2 = CaseGenerator(seed=12345)

        cases1 = gen1.generate(simple_workflow, count=10)
        cases2 = gen2.generate(simple_workflow, count=10)

        # Same input values (IDs will differ due to uuid)
        for c1, c2 in zip(cases1, cases2):
            assert c1.inputs == c2.inputs


# -----------------------------------------------------------------------------
# Test: Boundary Case Generation
# -----------------------------------------------------------------------------

class TestBoundaryGeneration:
    """Tests for boundary case generation."""

    def test_includes_min_max_values(self, generator: CaseGenerator, simple_workflow: Workflow):
        """Should include min and max values from range."""
        cases = generator.generate_boundary(simple_workflow)
        ages = [c.inputs["age"] for c in cases]
        assert 0 in ages  # min
        assert 120 in ages  # max

    def test_includes_threshold_values(self, generator: CaseGenerator, simple_workflow: Workflow):
        """Should include values around decision thresholds."""
        cases = generator.generate_boundary(simple_workflow)
        ages = [c.inputs["age"] for c in cases]
        # Threshold is 18, should have 17, 18, 19
        assert 17 in ages
        assert 18 in ages
        assert 19 in ages

    def test_includes_all_bool_values(self, generator: CaseGenerator, multi_input_workflow: Workflow):
        """Should include both True and False for booleans."""
        cases = generator.generate_boundary(multi_input_workflow)
        bool_values = [c.inputs["has_symptoms"] for c in cases]
        assert True in bool_values
        assert False in bool_values

    def test_includes_all_enum_values(self, generator: CaseGenerator, multi_input_workflow: Workflow):
        """Should include all enum values."""
        cases = generator.generate_boundary(multi_input_workflow)
        enum_values = {c.inputs["severity"] for c in cases}
        assert enum_values == {"mild", "moderate", "severe"}

    def test_respects_range_boundaries(self, generator: CaseGenerator, simple_workflow: Workflow):
        """Generated boundary values should not exceed range."""
        cases = generator.generate_boundary(simple_workflow)
        for case in cases:
            assert 0 <= case.inputs["age"] <= 120


# -----------------------------------------------------------------------------
# Test: Comprehensive Case Generation
# -----------------------------------------------------------------------------

class TestComprehensiveGeneration:
    """Tests for comprehensive case generation."""

    def test_combines_boundary_and_random(self, generator: CaseGenerator, simple_workflow: Workflow):
        """Should include both boundary and random cases."""
        cases = generator.generate_comprehensive(simple_workflow, random_count=10)

        # Should have at least boundary cases
        assert len(cases) >= 5  # min, max, and threshold values

        # Should include boundary values
        ages = [c.inputs["age"] for c in cases]
        assert 0 in ages  # min
        assert 120 in ages  # max

    def test_deduplicates_cases(self, generator: CaseGenerator, simple_workflow: Workflow):
        """Should not include duplicate input combinations."""
        cases = generator.generate_comprehensive(simple_workflow, random_count=50)

        # Check for unique input combinations
        seen = set()
        for case in cases:
            key = str(sorted(case.inputs.items()))
            assert key not in seen, f"Duplicate inputs: {case.inputs}"
            seen.add(key)

    def test_unique_case_ids(self, generator: CaseGenerator, simple_workflow: Workflow):
        """All cases should have unique IDs."""
        cases = generator.generate_comprehensive(simple_workflow, random_count=20)
        ids = [c.id for c in cases]
        assert len(ids) == len(set(ids))


# -----------------------------------------------------------------------------
# Test: Edge Cases
# -----------------------------------------------------------------------------

class TestEdgeCases:
    """Tests for edge cases and special scenarios."""

    def test_workflow_no_range(self):
        """Should handle inputs without explicit range."""
        workflow = Workflow(
            id="no-range",
            metadata=WorkflowMetadata(name="No Range", description="", domain="test"),
            blocks=[
                InputBlock(id="i1", name="value", input_type=InputType.INT),
                OutputBlock(id="o1", value="done"),
            ],
            connections=[Connection(from_block="i1", to_block="o1")],
        )
        generator = CaseGenerator(seed=42)
        cases = generator.generate(workflow, count=10)

        # Should use default range (0-100)
        for case in cases:
            assert 0 <= case.inputs["value"] <= 100

    def test_workflow_no_inputs(self):
        """Should handle workflows with no inputs."""
        workflow = Workflow(
            id="no-inputs",
            metadata=WorkflowMetadata(name="No Inputs", description="", domain="test"),
            blocks=[OutputBlock(id="o1", value="always")],
            connections=[],
        )
        generator = CaseGenerator(seed=42)
        cases = generator.generate(workflow, count=5)

        # Should generate cases with empty inputs
        assert len(cases) == 5
        for case in cases:
            assert case.inputs == {}

    def test_date_input_generation(self):
        """Should generate valid date strings."""
        workflow = Workflow(
            id="date-workflow",
            metadata=WorkflowMetadata(name="Date Test", description="", domain="test"),
            blocks=[
                InputBlock(id="i1", name="birth_date", input_type=InputType.DATE),
                OutputBlock(id="o1", value="done"),
            ],
            connections=[Connection(from_block="i1", to_block="o1")],
        )
        generator = CaseGenerator(seed=42)
        cases = generator.generate(workflow, count=10)

        import re
        date_pattern = r"\d{4}-\d{2}-\d{2}"
        for case in cases:
            assert re.match(date_pattern, case.inputs["birth_date"])

    def test_enum_with_single_value(self):
        """Should handle enum with single value."""
        workflow = Workflow(
            id="single-enum",
            metadata=WorkflowMetadata(name="Single Enum", description="", domain="test"),
            blocks=[
                InputBlock(id="i1", name="status", input_type=InputType.ENUM, enum_values=["only"]),
                OutputBlock(id="o1", value="done"),
            ],
            connections=[Connection(from_block="i1", to_block="o1")],
        )
        generator = CaseGenerator(seed=42)
        cases = generator.generate(workflow, count=5)

        # Should always use the only available value
        for case in cases:
            assert case.inputs["status"] == "only"


# -----------------------------------------------------------------------------
# Test: Threshold Extraction
# -----------------------------------------------------------------------------

class TestThresholdExtraction:
    """Tests for extracting thresholds from conditions."""

    def test_extracts_simple_threshold(self, generator: CaseGenerator):
        """Should extract thresholds from simple conditions."""
        workflow = Workflow(
            id="threshold-test",
            metadata=WorkflowMetadata(name="Threshold", description="", domain="test"),
            blocks=[
                InputBlock(id="i1", name="score", input_type=InputType.INT, range=Range(min=0, max=100)),
                DecisionBlock(id="d1", condition="score >= 60"),
                OutputBlock(id="o1", value="pass"),
                OutputBlock(id="o2", value="fail"),
            ],
            connections=[
                Connection(from_block="i1", to_block="d1"),
                Connection(from_block="d1", to_block="o1", from_port=PortType.TRUE),
                Connection(from_block="d1", to_block="o2", from_port=PortType.FALSE),
            ],
        )

        cases = generator.generate_boundary(workflow)
        scores = [c.inputs["score"] for c in cases]

        # Should include values around threshold 60
        assert 59 in scores
        assert 60 in scores
        assert 61 in scores

    def test_extracts_float_threshold(self, generator: CaseGenerator):
        """Should extract float thresholds."""
        workflow = Workflow(
            id="float-threshold",
            metadata=WorkflowMetadata(name="Float Threshold", description="", domain="test"),
            blocks=[
                InputBlock(id="i1", name="temp", input_type=InputType.FLOAT, range=Range(min=35.0, max=42.0)),
                DecisionBlock(id="d1", condition="temp > 37.5"),
                OutputBlock(id="o1", value="fever"),
                OutputBlock(id="o2", value="normal"),
            ],
            connections=[
                Connection(from_block="i1", to_block="d1"),
                Connection(from_block="d1", to_block="o1", from_port=PortType.TRUE),
                Connection(from_block="d1", to_block="o2", from_port=PortType.FALSE),
            ],
        )

        cases = generator.generate_boundary(workflow)
        temps = [c.inputs["temp"] for c in cases]

        # Should include values around threshold 37.5
        assert any(abs(t - 37.4) < 0.01 for t in temps)
        assert any(abs(t - 37.5) < 0.01 for t in temps)
        assert any(abs(t - 37.6) < 0.01 for t in temps)
