"""Tests for batch workflow executor.

Tests the BatchExecutor with:
1. Valid inputs — all patients execute successfully
2. Missing data skip — patients missing variables are SKIPPED
3. All-skip — every patient is missing data
4. Empty patient list — returns empty results
5. Invalid workflow — no tree raises ValueError
6. Mixed results — some succeed, some skip, some error
"""

import pytest

from src.backend.batch.executor import BatchExecutor, BatchResultRow


# =============================================================================
# MOCK WORKFLOW OBJECTS
# =============================================================================


class MockWorkflowRecord:
    """Minimal mock of WorkflowRecord with fields used by BatchExecutor."""

    def __init__(self, *, name, wf_id, tree, inputs, outputs):
        self.id = wf_id
        self.name = name
        self.tree = tree
        self.inputs = inputs
        self.outputs = outputs


# Simple age-check workflow: Age >= 18 → "Adult", else → "Minor"
SIMPLE_WORKFLOW = MockWorkflowRecord(
    wf_id="wf_test_age",
    name="Age Check",
    inputs=[
        {"id": "input_age_int", "name": "Age", "type": "int", "source": "input"},
    ],
    outputs=[
        {"name": "Adult", "type": "string"},
        {"name": "Minor", "type": "string"},
    ],
    tree={
        "start": {
            "id": "start",
            "type": "start",
            "label": "Start",
            "children": [
                {
                    "id": "age_check",
                    "type": "decision",
                    "label": "Age >= 18?",
                    "condition": {
                        "input_id": "input_age_int",
                        "comparator": "gte",
                        "value": 18,
                    },
                    "children": [
                        {
                            "id": "adult_out",
                            "type": "end",
                            "label": "Adult",
                            "edge_label": "Yes",
                        },
                        {
                            "id": "minor_out",
                            "type": "end",
                            "label": "Minor",
                            "edge_label": "No",
                        },
                    ],
                }
            ],
        }
    },
)

# Two-input workflow: Age + Gender
TWO_INPUT_WORKFLOW = MockWorkflowRecord(
    wf_id="wf_test_two",
    name="Two Input Check",
    inputs=[
        {"id": "input_age_int", "name": "Age", "type": "int", "source": "input"},
        {"id": "input_gender_string", "name": "Gender", "type": "string", "source": "input"},
    ],
    outputs=[
        {"name": "Pass", "type": "string"},
    ],
    tree={
        "start": {
            "id": "start",
            "type": "start",
            "label": "Start",
            "children": [
                {
                    "id": "age_check",
                    "type": "decision",
                    "label": "Age >= 18?",
                    "condition": {
                        "input_id": "input_age_int",
                        "comparator": "gte",
                        "value": 18,
                    },
                    "children": [
                        {
                            "id": "pass_out",
                            "type": "end",
                            "label": "Pass",
                            "edge_label": "Yes",
                        },
                        {
                            "id": "fail_out",
                            "type": "end",
                            "label": "Fail",
                            "edge_label": "No",
                        },
                    ],
                }
            ],
        }
    },
)

# No-tree workflow — should raise ValueError
NO_TREE_WORKFLOW = MockWorkflowRecord(
    wf_id="wf_no_tree",
    name="No Tree",
    inputs=[],
    outputs=[],
    tree={},
)


# =============================================================================
# TESTS
# =============================================================================


class TestBatchExecutorValidInputs:
    """Test batch execution with valid inputs for all patients."""

    def test_single_patient_adult(self):
        executor = BatchExecutor(SIMPLE_WORKFLOW)
        results = executor.execute_batch([
            {"emis_number": "100", "input_values": {"Age": 25}},
        ])
        assert len(results) == 1
        assert results[0].success is True
        assert results[0].status == "SUCCESS"
        assert results[0].output == "Adult"
        assert results[0].emis_number == "100"
        assert results[0].missing_variables == []

    def test_single_patient_minor(self):
        executor = BatchExecutor(SIMPLE_WORKFLOW)
        results = executor.execute_batch([
            {"emis_number": "200", "input_values": {"Age": 10}},
        ])
        assert len(results) == 1
        assert results[0].success is True
        assert results[0].output == "Minor"

    def test_multiple_patients(self):
        executor = BatchExecutor(SIMPLE_WORKFLOW)
        results = executor.execute_batch([
            {"emis_number": "1", "input_values": {"Age": 25}},
            {"emis_number": "2", "input_values": {"Age": 10}},
            {"emis_number": "3", "input_values": {"Age": 65}},
        ])
        assert len(results) == 3
        assert all(r.success for r in results)
        assert results[0].output == "Adult"
        assert results[1].output == "Minor"
        assert results[2].output == "Adult"

    def test_result_contains_path(self):
        executor = BatchExecutor(SIMPLE_WORKFLOW)
        results = executor.execute_batch([
            {"emis_number": "1", "input_values": {"Age": 25}},
        ])
        assert results[0].path is not None
        assert "start" in results[0].path


class TestBatchExecutorMissingData:
    """Test batch execution when patients are missing required variables."""

    def test_missing_single_variable(self):
        executor = BatchExecutor(SIMPLE_WORKFLOW)
        results = executor.execute_batch([
            {"emis_number": "1", "input_values": {}},
        ])
        assert len(results) == 1
        assert results[0].success is False
        assert results[0].status == "SKIPPED"
        assert "Age" in results[0].missing_variables

    def test_missing_one_of_two_variables(self):
        executor = BatchExecutor(TWO_INPUT_WORKFLOW)
        results = executor.execute_batch([
            {"emis_number": "1", "input_values": {"Age": 25}},
        ])
        assert len(results) == 1
        assert results[0].status == "SKIPPED"
        assert "Gender" in results[0].missing_variables
        assert "Age" not in results[0].missing_variables

    def test_mixed_valid_and_missing(self):
        """Some patients have data, some don't — batch should process both."""
        executor = BatchExecutor(SIMPLE_WORKFLOW)
        results = executor.execute_batch([
            {"emis_number": "1", "input_values": {"Age": 25}},
            {"emis_number": "2", "input_values": {}},
            {"emis_number": "3", "input_values": {"Age": 10}},
        ])
        assert len(results) == 3
        assert results[0].status == "SUCCESS"
        assert results[1].status == "SKIPPED"
        assert results[2].status == "SUCCESS"


class TestBatchExecutorAllSkip:
    """Test batch execution when every patient is missing data."""

    def test_all_patients_skipped(self):
        executor = BatchExecutor(SIMPLE_WORKFLOW)
        results = executor.execute_batch([
            {"emis_number": "1", "input_values": {}},
            {"emis_number": "2", "input_values": {}},
        ])
        assert len(results) == 2
        assert all(r.status == "SKIPPED" for r in results)
        assert all(not r.success for r in results)


class TestBatchExecutorEmptyList:
    """Test batch execution with no patients."""

    def test_empty_patient_list(self):
        executor = BatchExecutor(SIMPLE_WORKFLOW)
        results = executor.execute_batch([])
        assert results == []


class TestBatchExecutorInvalidWorkflow:
    """Test batch execution with a workflow that has no tree."""

    def test_no_tree_raises_error(self):
        executor = BatchExecutor(NO_TREE_WORKFLOW)
        with pytest.raises(ValueError, match="no execution tree"):
            executor.execute_batch([
                {"emis_number": "1", "input_values": {}},
            ])


class TestBatchResultRowSerialization:
    """Test that BatchResultRow serializes to dict correctly."""

    def test_to_dict(self):
        row = BatchResultRow(
            emis_number="42",
            success=True,
            output="Adult",
            path=["start", "age_check", "adult_out"],
            status="SUCCESS",
            error=None,
            missing_variables=[],
        )
        d = row.to_dict()
        assert d["emis_number"] == "42"
        assert d["success"] is True
        assert d["output"] == "Adult"
        assert d["status"] == "SUCCESS"
        assert d["error"] is None
        assert d["missing_variables"] == []

    def test_skipped_to_dict(self):
        row = BatchResultRow(
            emis_number="99",
            success=False,
            output=None,
            path=None,
            status="SKIPPED",
            error="Missing required variables: Age",
            missing_variables=["Age"],
        )
        d = row.to_dict()
        assert d["status"] == "SKIPPED"
        assert d["missing_variables"] == ["Age"]
