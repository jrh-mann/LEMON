"""Shared workflow execution preparation helpers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..storage.workflows import WorkflowRecord
from ..utils.flowchart import tree_from_flowchart
from ..validation.workflow_validator import WorkflowValidator


_validator = WorkflowValidator()


def prepare_workflow_execution(
    *,
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
    variables: List[Dict[str, Any]],
) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[List[Any]]]:
    """Validate a workflow and build its execution tree."""
    workflow_for_validation = {
        "nodes": nodes,
        "edges": edges,
        "variables": variables,
    }
    is_valid, errors = _validator.validate(workflow_for_validation, strict=True)
    if not is_valid:
        return None, _validator.format_errors(errors), errors

    tree = tree_from_flowchart(nodes, edges)
    if not tree or "start" not in tree:
        return None, "Workflow has no start node.", None
    return tree, None, None


def prepare_record_execution(workflow: WorkflowRecord) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[List[Any]]]:
    """Prepare a stored workflow record for execution."""
    return prepare_workflow_execution(
        nodes=workflow.nodes,
        edges=workflow.edges,
        variables=workflow.inputs,
    )
