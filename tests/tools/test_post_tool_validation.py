"""Integration tests for post-tool workflow validation in the orchestrator.

Tests that the orchestrator hard-fails when a WORKFLOW_EDIT_TOOL produces
invalid workflow state (e.g. self-loops, duplicate node IDs, invalid
node types, bad edge references).
"""

import pytest

from src.backend.agents.orchestrator import Orchestrator, ToolResult
from src.backend.tools import ToolRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_orchestrator(**workflow_overrides) -> Orchestrator:
    """Create an Orchestrator with a given workflow state (no real tools needed)."""
    registry = ToolRegistry()
    orch = Orchestrator(registry)
    for k, v in workflow_overrides.items():
        orch.workflow[k] = v
    return orch


def _ok_result(tool_name: str = "add_node", **data_overrides) -> ToolResult:
    """A successful ToolResult stub."""
    data = {"success": True, **data_overrides}
    return ToolResult(tool=tool_name, data=data, success=True, message="OK")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPostToolValidation:
    """Tests for Orchestrator._post_tool_validate()."""

    def test_valid_workflow_passes(self):
        """A simple valid workflow should pass validation."""
        orch = _make_orchestrator(
            nodes=[
                {"id": "n1", "type": "start", "label": "Start", "x": 0, "y": 0},
                {"id": "n2", "type": "end", "label": "End", "x": 100, "y": 0},
            ],
            edges=[
                {"id": "e1", "from": "n1", "to": "n2", "label": ""},
            ],
        )
        result = _ok_result()
        validated = orch._post_tool_validate(result)
        assert validated.success is True
        assert validated is result  # same object — not replaced

    def test_empty_workflow_skips_validation(self):
        """When there are no nodes yet, validation is skipped."""
        orch = _make_orchestrator(nodes=[], edges=[])
        result = _ok_result()
        validated = orch._post_tool_validate(result)
        assert validated.success is True

    def test_self_loop_fails(self):
        """A self-loop edge should fail validation."""
        orch = _make_orchestrator(
            nodes=[
                {"id": "n1", "type": "start", "label": "Start", "x": 0, "y": 0},
            ],
            edges=[
                {"id": "e1", "from": "n1", "to": "n1", "label": ""},
            ],
        )
        result = _ok_result()
        validated = orch._post_tool_validate(result)
        assert validated.success is False
        assert "SELF_LOOP" in validated.error

    def test_duplicate_node_id_fails(self):
        """Duplicate node IDs should fail validation."""
        orch = _make_orchestrator(
            nodes=[
                {"id": "n1", "type": "start", "label": "Start", "x": 0, "y": 0},
                {"id": "n1", "type": "end", "label": "End", "x": 100, "y": 0},
            ],
            edges=[],
        )
        result = _ok_result()
        validated = orch._post_tool_validate(result)
        assert validated.success is False
        assert "DUPLICATE_NODE_ID" in validated.error

    def test_invalid_node_type_fails(self):
        """An invalid node type should fail validation."""
        orch = _make_orchestrator(
            nodes=[
                {"id": "n1", "type": "banana", "label": "Bad", "x": 0, "y": 0},
            ],
            edges=[],
        )
        result = _ok_result()
        validated = orch._post_tool_validate(result)
        assert validated.success is False
        assert "INVALID_NODE_TYPE" in validated.error

    def test_invalid_edge_reference_fails(self):
        """An edge referencing a non-existent node should fail."""
        orch = _make_orchestrator(
            nodes=[
                {"id": "n1", "type": "start", "label": "Start", "x": 0, "y": 0},
            ],
            edges=[
                {"id": "e1", "from": "n1", "to": "n_missing", "label": ""},
            ],
        )
        result = _ok_result()
        validated = orch._post_tool_validate(result)
        assert validated.success is False
        assert "INVALID_EDGE" in validated.error

    def test_cycle_detected_fails(self):
        """A cycle in the workflow graph should fail validation."""
        orch = _make_orchestrator(
            nodes=[
                {"id": "n1", "type": "start", "label": "Start", "x": 0, "y": 0},
                {"id": "n2", "type": "process", "label": "Step", "x": 100, "y": 0},
            ],
            edges=[
                {"id": "e1", "from": "n1", "to": "n2", "label": ""},
                {"id": "e2", "from": "n2", "to": "n1", "label": ""},
            ],
        )
        result = _ok_result()
        validated = orch._post_tool_validate(result)
        assert validated.success is False
        assert "CYCLE" in validated.error

    def test_failed_result_preserves_original_data(self):
        """When validation fails, the original result.data is preserved in the new result."""
        orch = _make_orchestrator(
            nodes=[
                {"id": "n1", "type": "start", "label": "Start", "x": 0, "y": 0},
            ],
            edges=[
                {"id": "e1", "from": "n1", "to": "n1", "label": ""},
            ],
        )
        original_data = {"success": True, "node": {"id": "n1"}}
        result = ToolResult(tool="add_node", data=original_data, success=True, message="OK")
        validated = orch._post_tool_validate(result)
        assert validated.success is False
        # Original data keys should still be accessible
        assert validated.data.get("node") == {"id": "n1"}

    def test_strict_rules_not_enforced(self):
        """Non-strict validation should NOT flag missing connections, dead ends, etc.

        An incomplete workflow (start node with no outgoing edge) is valid
        during incremental editing.
        """
        orch = _make_orchestrator(
            nodes=[
                {"id": "n1", "type": "start", "label": "Start", "x": 0, "y": 0},
                {"id": "n2", "type": "process", "label": "Step", "x": 100, "y": 0},
            ],
            edges=[],  # No connections — would fail strict mode
        )
        result = _ok_result()
        validated = orch._post_tool_validate(result)
        # Non-strict mode should pass despite no edges
        assert validated.success is True
