"""Shared helper functions for route handlers.

Extracted from the monolithic routes.py to eliminate duplication
and provide reusable utilities across route modules.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ...storage.workflows import WorkflowRecord


def _infer_outputs_from_nodes(
    nodes: List[Dict[str, Any]],
    workflow_output_type: str = "string",
) -> List[Dict[str, Any]]:
    """Infer workflow outputs from end nodes using the workflow-level output_type.

    When saving a workflow, we create output definitions from end nodes.
    The output type comes from the workflow-level output_type setting,
    not from per-node configuration.

    Args:
        nodes: List of workflow nodes
        workflow_output_type: Workflow-level output type (string, number, bool, json)

    Returns:
        List of output definitions [{name, type, description?}]
    """
    outputs = []
    for node in nodes:
        if node.get("type") == "end":
            output_def = {
                "name": node.get("label", "output"),
                "type": workflow_output_type,
            }
            # Include description from template if present
            if node.get("output_template"):
                output_def["description"] = node.get("output_template")
            outputs.append(output_def)
    return outputs


def _calculate_confidence(score: int, count: int) -> str:
    """Calculate validation confidence level based on score and count."""
    if count == 0:
        return "none"
    accuracy = score / count if count > 0 else 0
    if count < 3:
        return "low"
    if accuracy >= 0.9 and count >= 10:
        return "high"
    if accuracy >= 0.8:
        return "medium"
    return "low"


def serialize_workflow_summary(wf: WorkflowRecord) -> Dict[str, Any]:
    """Convert a WorkflowRecord to a WorkflowSummary dict for API responses.

    Eliminates the triplicated serialization code that was previously
    copy-pasted across list_workflows, search_workflows, and list_public_workflows.

    Args:
        wf: A WorkflowRecord from the storage layer.

    Returns:
        Dict matching the WorkflowSummary format expected by the frontend.
    """
    input_names = [
        inp.get("name", "") for inp in wf.inputs if isinstance(inp, dict)
    ]
    output_values = [
        out.get("value", "") or out.get("name", "")
        for out in wf.outputs
        if isinstance(out, dict)
    ]

    return {
        "id": wf.id,
        "name": wf.name,
        "description": wf.description,
        "domain": wf.domain,
        "tags": wf.tags,
        "validation_score": wf.validation_score,
        "validation_count": wf.validation_count,
        "confidence": _calculate_confidence(
            wf.validation_score, wf.validation_count
        ),
        "is_validated": wf.is_validated,
        "input_names": input_names,
        "output_values": output_values,
        "created_at": wf.created_at,
        "updated_at": wf.updated_at,
        "building": getattr(wf, "building", False),
        "is_draft": getattr(wf, "is_draft", False),
        "output_type": getattr(wf, "output_type", "string"),
    }
