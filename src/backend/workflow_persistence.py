"""Shared workflow persistence helpers.

Centralizes the canonical workflow save contract so websocket sync, routes,
and tools persist the same execution-critical fields together.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .storage.workflows import WorkflowRecord, WorkflowStore
from .utils.flowchart import tree_from_flowchart


def _infer_outputs_from_nodes(
    nodes: List[Dict[str, Any]],
    workflow_output_type: str = "string",
) -> List[Dict[str, Any]]:
    """Infer workflow outputs from end nodes using the workflow-level output_type."""
    outputs = []
    for node in nodes:
        if node.get("type") == "end":
            output_def = {
                "name": node.get("label", "output"),
                "type": workflow_output_type,
            }
            if node.get("output_template"):
                output_def["description"] = node.get("output_template")
            outputs.append(output_def)
    return outputs


def compute_synced_outputs(
    nodes: List[Dict[str, Any]],
    outputs: Optional[List[Dict[str, Any]]],
    output_type: str,
) -> List[Dict[str, Any]]:
    """Return outputs whose types match the workflow-level output_type."""
    if outputs:
        synced_outputs: List[Dict[str, Any]] = []
        for output in outputs:
            if isinstance(output, dict):
                synced_outputs.append({**output, "type": output_type})
        if synced_outputs:
            return synced_outputs
    return _infer_outputs_from_nodes(nodes, output_type)


def build_persisted_workflow_fields(
    *,
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
    variables: List[Dict[str, Any]],
    outputs: Optional[List[Dict[str, Any]]],
    output_type: Optional[str],
) -> Dict[str, Any]:
    """Build a persistence-ready workflow field set.

    The workflow-level output_type remains part of the canonical contract, but
    must stay synchronized with persisted outputs.
    """
    resolved_output_type = output_type or "string"
    synced_outputs = compute_synced_outputs(nodes, outputs, resolved_output_type)
    return {
        "nodes": nodes,
        "edges": edges,
        "inputs": variables,
        "outputs": synced_outputs,
        "output_type": resolved_output_type,
        "tree": tree_from_flowchart(nodes, edges),
    }


def merge_workflow_record_with_updates(
    record: WorkflowRecord,
    *,
    nodes: Optional[List[Dict[str, Any]]] = None,
    edges: Optional[List[Dict[str, Any]]] = None,
    variables: Optional[List[Dict[str, Any]]] = None,
    outputs: Optional[List[Dict[str, Any]]] = None,
    output_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Merge partial workflow updates into a canonical persisted field set."""
    resolved_nodes = record.nodes if nodes is None else nodes
    resolved_edges = record.edges if edges is None else edges
    resolved_variables = record.inputs if variables is None else variables
    resolved_output_type = record.output_type or "string"
    if output_type is not None:
        resolved_output_type = output_type
    resolved_outputs = record.outputs if outputs is None else outputs
    return build_persisted_workflow_fields(
        nodes=resolved_nodes,
        edges=resolved_edges,
        variables=resolved_variables,
        outputs=resolved_outputs,
        output_type=resolved_output_type,
    )


def persist_workflow_snapshot(
    workflow_store: WorkflowStore,
    *,
    workflow_id: str,
    user_id: str,
    name: str,
    description: str,
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
    variables: List[Dict[str, Any]],
    outputs: Optional[List[Dict[str, Any]]],
    output_type: Optional[str],
    is_draft: bool = True,
) -> Tuple[bool, Dict[str, Any]]:
    """Create or update a workflow with the full canonical snapshot."""
    persisted = build_persisted_workflow_fields(
        nodes=nodes,
        edges=edges,
        variables=variables,
        outputs=outputs,
        output_type=output_type,
    )
    existing = workflow_store.get_workflow(workflow_id, user_id)
    if existing is None:
        workflow_store.create_workflow(
            workflow_id=workflow_id,
            user_id=user_id,
            name=name,
            description=description,
            nodes=persisted["nodes"],
            edges=persisted["edges"],
            inputs=persisted["inputs"],
            outputs=persisted["outputs"],
            tree=persisted["tree"],
            output_type=persisted["output_type"],
            is_draft=is_draft,
        )
        return True, persisted
    workflow_store.update_workflow(
        workflow_id,
        user_id,
        nodes=persisted["nodes"],
        edges=persisted["edges"],
        inputs=persisted["inputs"],
        outputs=persisted["outputs"],
        tree=persisted["tree"],
        output_type=persisted["output_type"],
    )
    return False, persisted
