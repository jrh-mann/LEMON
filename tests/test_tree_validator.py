"""Unit tests for TreeValidator — validates subagent nested tree output."""

import pytest

from src.backend.validation.tree_validator import TreeValidator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_analysis(tree_start=None, variables=None):
    """Build a minimal analysis dict for testing."""
    analysis = {}
    if tree_start is not None:
        analysis["tree"] = {"start": tree_start}
    if variables is not None:
        analysis["variables"] = variables
    return analysis


def _valid_start_node(**overrides):
    """Return a minimal valid start node."""
    base = {
        "id": "start_1",
        "type": "start",
        "label": "Start",
        "children": [],
    }
    base.update(overrides)
    return base


def _valid_decision_node(**overrides):
    """Return a minimal valid decision node with true/false children."""
    base = {
        "id": "decision_1",
        "type": "decision",
        "label": "Age >= 18?",
        "condition": {"input_id": "age", "comparator": "gte"},
        "children": [
            {
                "id": "output_true",
                "type": "output",
                "label": "Approve",
                "edge_label": "true",
                "children": [],
            },
            {
                "id": "output_false",
                "type": "output",
                "label": "Reject",
                "edge_label": "false",
                "children": [],
            },
        ],
    }
    base.update(overrides)
    return base


def _valid_output_node(**overrides):
    """Return a minimal valid output (leaf) node."""
    base = {"id": "output_1", "type": "output", "label": "Done", "children": []}
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------

class TestTreeValidator:
    def setup_method(self):
        self.validator = TreeValidator()

    # --- Valid trees ---

    def test_valid_minimal_tree(self):
        """Start → Output: the simplest valid tree."""
        start = _valid_start_node(
            children=[_valid_output_node()]
        )
        ok, errors = self.validator.validate(_make_analysis(tree_start=start))
        assert ok is True
        assert errors == []

    def test_valid_tree_with_decision(self):
        """Start → Decision → (Action, Output)."""
        start = _valid_start_node(
            children=[_valid_decision_node()]
        )
        analysis = _make_analysis(
            tree_start=start,
            variables=[{"id": "age", "name": "age", "type": "number"}],
        )
        ok, errors = self.validator.validate(analysis)
        assert ok is True
        assert errors == []

    # --- TREE_MISSING ---

    def test_tree_missing_entirely(self):
        ok, errors = self.validator.validate({})
        assert ok is False
        assert any(e.code == "TREE_MISSING" for e in errors)

    def test_tree_empty_dict(self):
        ok, errors = self.validator.validate({"tree": {}})
        assert ok is False
        assert any(e.code == "TREE_MISSING" for e in errors)

    def test_tree_not_a_dict(self):
        ok, errors = self.validator.validate({"tree": "bad"})
        assert ok is False
        assert any(e.code == "TREE_MISSING" for e in errors)

    # --- TREE_MISSING_START ---

    def test_tree_missing_start(self):
        ok, errors = self.validator.validate({"tree": {"something": "else"}})
        assert ok is False
        assert any(e.code == "TREE_MISSING_START" for e in errors)

    def test_tree_start_empty(self):
        ok, errors = self.validator.validate({"tree": {"start": {}}})
        assert ok is False
        assert any(e.code == "TREE_MISSING_START" for e in errors)

    # --- TREE_START_TYPE ---

    def test_root_wrong_type(self):
        start = _valid_start_node(type="action")
        ok, errors = self.validator.validate(_make_analysis(tree_start=start))
        assert ok is False
        assert any(e.code == "TREE_START_TYPE" for e in errors)

    # --- INVALID_TREE_NODE_TYPE ---

    def test_invalid_node_type(self):
        bad_child = {"id": "x1", "type": "loop", "label": "Loop", "children": []}
        start = _valid_start_node(children=[bad_child])
        ok, errors = self.validator.validate(_make_analysis(tree_start=start))
        assert ok is False
        assert any(e.code == "INVALID_TREE_NODE_TYPE" for e in errors)

    # --- DUPLICATE_NODE_ID ---

    def test_duplicate_node_id(self):
        child = _valid_output_node(id="start_1")  # same ID as start
        start = _valid_start_node(children=[child])
        ok, errors = self.validator.validate(_make_analysis(tree_start=start))
        assert ok is False
        assert any(e.code == "DUPLICATE_NODE_ID" for e in errors)

    # --- MISSING_NODE_ID ---

    def test_missing_node_id_none(self):
        start = _valid_start_node(id=None)
        ok, errors = self.validator.validate(_make_analysis(tree_start=start))
        assert ok is False
        assert any(e.code == "MISSING_NODE_ID" for e in errors)

    def test_missing_node_id_empty(self):
        start = _valid_start_node(id="")
        ok, errors = self.validator.validate(_make_analysis(tree_start=start))
        assert ok is False
        assert any(e.code == "MISSING_NODE_ID" for e in errors)

    def test_missing_node_id_whitespace(self):
        start = _valid_start_node(id="   ")
        ok, errors = self.validator.validate(_make_analysis(tree_start=start))
        assert ok is False
        assert any(e.code == "MISSING_NODE_ID" for e in errors)

    # --- MISSING_NODE_LABEL ---

    def test_missing_node_label(self):
        start = _valid_start_node(label="")
        ok, errors = self.validator.validate(_make_analysis(tree_start=start))
        assert ok is False
        assert any(e.code == "MISSING_NODE_LABEL" for e in errors)

    def test_missing_node_label_none(self):
        start = _valid_start_node(label=None)
        ok, errors = self.validator.validate(_make_analysis(tree_start=start))
        assert ok is False
        assert any(e.code == "MISSING_NODE_LABEL" for e in errors)

    # --- DECISION_CHILDREN_COUNT ---

    def test_decision_zero_children(self):
        decision = _valid_decision_node(children=[])
        start = _valid_start_node(children=[decision])
        ok, errors = self.validator.validate(_make_analysis(tree_start=start))
        assert ok is False
        assert any(e.code == "DECISION_CHILDREN_COUNT" for e in errors)

    def test_decision_one_child(self):
        decision = _valid_decision_node(
            children=[{"id": "o1", "type": "output", "label": "Only child", "edge_label": "true", "children": []}]
        )
        start = _valid_start_node(children=[decision])
        ok, errors = self.validator.validate(_make_analysis(tree_start=start))
        assert ok is False
        assert any(e.code == "DECISION_CHILDREN_COUNT" for e in errors)

    def test_decision_three_children(self):
        decision = _valid_decision_node(
            children=[
                {"id": "o1", "type": "output", "label": "C1", "edge_label": "true", "children": []},
                {"id": "o2", "type": "output", "label": "C2", "edge_label": "false", "children": []},
                {"id": "o3", "type": "output", "label": "C3", "edge_label": "maybe", "children": []},
            ]
        )
        start = _valid_start_node(children=[decision])
        ok, errors = self.validator.validate(_make_analysis(tree_start=start))
        assert ok is False
        assert any(e.code == "DECISION_CHILDREN_COUNT" for e in errors)

    # --- DECISION_EDGE_LABELS ---

    def test_decision_wrong_edge_labels(self):
        decision = _valid_decision_node(
            children=[
                {"id": "o1", "type": "output", "label": "Yes", "edge_label": "yes", "children": []},
                {"id": "o2", "type": "output", "label": "No", "edge_label": "no", "children": []},
            ]
        )
        start = _valid_start_node(children=[decision])
        ok, errors = self.validator.validate(_make_analysis(tree_start=start))
        assert ok is False
        assert any(e.code == "DECISION_EDGE_LABELS" for e in errors)

    def test_decision_edge_labels_case_insensitive(self):
        """'True'/'False' (capitalised) should pass."""
        decision = _valid_decision_node(
            children=[
                {"id": "o1", "type": "output", "label": "Yes", "edge_label": "True", "children": []},
                {"id": "o2", "type": "output", "label": "No", "edge_label": "False", "children": []},
            ]
        )
        start = _valid_start_node(children=[decision])
        ok, errors = self.validator.validate(_make_analysis(tree_start=start))
        # Should NOT contain DECISION_EDGE_LABELS error
        assert not any(e.code == "DECISION_EDGE_LABELS" for e in errors)

    # --- DECISION_MISSING_CONDITION ---

    def test_decision_no_condition(self):
        decision = _valid_decision_node()
        del decision["condition"]
        start = _valid_start_node(children=[decision])
        ok, errors = self.validator.validate(_make_analysis(tree_start=start))
        assert ok is False
        assert any(e.code == "DECISION_MISSING_CONDITION" for e in errors)

    def test_decision_condition_missing_input_id(self):
        decision = _valid_decision_node(condition={"comparator": "gte"})
        start = _valid_start_node(children=[decision])
        ok, errors = self.validator.validate(_make_analysis(tree_start=start))
        assert ok is False
        assert any(e.code == "DECISION_MISSING_CONDITION" for e in errors)

    def test_decision_condition_missing_comparator(self):
        decision = _valid_decision_node(condition={"input_id": "age"})
        start = _valid_start_node(children=[decision])
        ok, errors = self.validator.validate(_make_analysis(tree_start=start))
        assert ok is False
        assert any(e.code == "DECISION_MISSING_CONDITION" for e in errors)

    # --- OUTPUT_HAS_CHILDREN ---

    def test_output_has_children(self):
        output = _valid_output_node(
            children=[{"id": "c1", "type": "output", "label": "Orphan", "children": []}]
        )
        start = _valid_start_node(children=[output])
        ok, errors = self.validator.validate(_make_analysis(tree_start=start))
        assert ok is False
        assert any(e.code == "OUTPUT_HAS_CHILDREN" for e in errors)

    # --- ACTION_MULTIPLE_CHILDREN ---

    def test_action_multiple_children(self):
        action = {
            "id": "act_1",
            "type": "action",
            "label": "Do thing",
            "children": [
                _valid_output_node(id="o1"),
                _valid_output_node(id="o2"),
            ],
        }
        start = _valid_start_node(children=[action])
        ok, errors = self.validator.validate(_make_analysis(tree_start=start))
        assert ok is False
        assert any(e.code == "ACTION_MULTIPLE_CHILDREN" for e in errors)

    def test_start_multiple_children(self):
        """Start node also limited to at most 1 child."""
        start = _valid_start_node(
            children=[
                _valid_output_node(id="o1"),
                _valid_output_node(id="o2"),
            ]
        )
        ok, errors = self.validator.validate(_make_analysis(tree_start=start))
        assert ok is False
        assert any(e.code == "ACTION_MULTIPLE_CHILDREN" for e in errors)

    # --- INVALID_INPUT_REFERENCE (soft check) ---

    def test_invalid_input_reference(self):
        """When variables are known, condition.input_id must reference one."""
        decision = _valid_decision_node()
        decision["condition"]["input_id"] = "nonexistent"
        start = _valid_start_node(children=[decision])
        analysis = _make_analysis(
            tree_start=start,
            variables=[{"id": "age", "name": "age", "type": "number"}],
        )
        ok, errors = self.validator.validate(analysis)
        assert ok is False
        assert any(e.code == "INVALID_INPUT_REFERENCE" for e in errors)

    def test_input_reference_skipped_when_no_variables(self):
        """When variables list is empty, INVALID_INPUT_REFERENCE is not raised."""
        decision = _valid_decision_node()
        decision["condition"]["input_id"] = "whatever"
        start = _valid_start_node(children=[decision])
        analysis = _make_analysis(tree_start=start, variables=[])
        ok, errors = self.validator.validate(analysis)
        # Should not have INVALID_INPUT_REFERENCE
        assert not any(e.code == "INVALID_INPUT_REFERENCE" for e in errors)

    def test_input_reference_matches_by_name(self):
        """input_id can match variable name (not just id)."""
        decision = _valid_decision_node()
        decision["condition"]["input_id"] = "customer_age"
        start = _valid_start_node(children=[decision])
        analysis = _make_analysis(
            tree_start=start,
            variables=[{"id": "input_customer_age_number", "name": "customer_age", "type": "number"}],
        )
        ok, errors = self.validator.validate(analysis)
        assert not any(e.code == "INVALID_INPUT_REFERENCE" for e in errors)

    # --- LEAF_NOT_OUTPUT ---

    def test_leaf_action_flagged(self):
        """An action node with no children should be flagged as LEAF_NOT_OUTPUT."""
        leaf_action = {"id": "act_1", "type": "action", "label": "Continue metformin", "children": []}
        start = _valid_start_node(children=[leaf_action])
        ok, errors = self.validator.validate(_make_analysis(tree_start=start))
        assert ok is False
        assert any(e.code == "LEAF_NOT_OUTPUT" for e in errors)

    def test_action_with_child_not_flagged(self):
        """An action node that has a child is NOT a leaf — no LEAF_NOT_OUTPUT."""
        action = {
            "id": "act_1",
            "type": "action",
            "label": "Do thing",
            "children": [_valid_output_node()],
        }
        start = _valid_start_node(children=[action])
        ok, errors = self.validator.validate(_make_analysis(tree_start=start))
        assert not any(e.code == "LEAF_NOT_OUTPUT" for e in errors)

    def test_output_leaf_not_flagged(self):
        """Output nodes that are leaves are correct — no LEAF_NOT_OUTPUT."""
        start = _valid_start_node(children=[_valid_output_node()])
        ok, errors = self.validator.validate(_make_analysis(tree_start=start))
        assert not any(e.code == "LEAF_NOT_OUTPUT" for e in errors)

    # --- Combined errors ---

    def test_multiple_errors(self):
        """A single tree can trigger many errors at once."""
        bad_decision = {
            "id": "",
            "type": "decision",
            "label": "",
            "children": [],
        }
        start = _valid_start_node(children=[bad_decision])
        ok, errors = self.validator.validate(_make_analysis(tree_start=start))
        assert ok is False
        codes = {e.code for e in errors}
        assert "MISSING_NODE_ID" in codes
        assert "MISSING_NODE_LABEL" in codes
        assert "DECISION_CHILDREN_COUNT" in codes
        assert "DECISION_MISSING_CONDITION" in codes

    # --- format_errors ---

    def test_format_errors_empty(self):
        assert TreeValidator.format_errors([]) == "No validation errors."

    def test_format_errors_renders_codes(self):
        from src.backend.validation.workflow_validator import ValidationError
        errors = [ValidationError(code="FOO", message="bar")]
        result = TreeValidator.format_errors(errors)
        assert "[FOO]" in result
        assert "bar" in result
