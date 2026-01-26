"""Shared helpers for workflow edit tools.

Contains constants and validation functions for workflow nodes,
including subprocess (subflow) nodes that reference other workflows.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

NODE_COLOR_BY_TYPE = {
    "start": "teal",
    "decision": "amber",
    "end": "green",
    "subprocess": "rose",
    "process": "slate",
}

# Required fields for subprocess nodes that reference other workflows
SUBPROCESS_REQUIRED_FIELDS = ["subworkflow_id", "input_mapping", "output_variable"]


def get_node_color(node_type: str) -> str:
    """Get the default color for a node type."""
    return NODE_COLOR_BY_TYPE.get(node_type, "slate")


def input_ref_error(input_ref: Optional[str], session_state: Dict[str, Any]) -> Optional[str]:
    """Check if an input reference is valid.
    
    Args:
        input_ref: Name of the input being referenced
        session_state: Current session state with workflow_analysis
        
    Returns:
        Error message if input not found, None if valid
    """
    if not input_ref:
        return None
    workflow_analysis = session_state.get("workflow_analysis", {})
    inputs = workflow_analysis.get("inputs", [])
    normalized_ref = input_ref.strip().lower()
    input_exists = any(
        inp.get("name", "").strip().lower() == normalized_ref
        for inp in inputs
    )
    if input_exists:
        return None
    return f"Input '{input_ref}' not found. Register it first with add_workflow_input."


def validate_subprocess_node(
    node: Dict[str, Any],
    session_state: Dict[str, Any],
    check_workflow_exists: bool = True,
) -> List[str]:
    """Validate subprocess node has required fields and valid references.
    
    Subprocess nodes reference other workflows (subflows) and must have:
    - subworkflow_id: ID of the workflow to execute
    - input_mapping: Dict mapping parent inputs to subworkflow inputs
    - output_variable: Name of variable to store subflow output
    
    Args:
        node: The subprocess node to validate
        session_state: Current session state with workflow_store and user_id
        check_workflow_exists: If True, verify subworkflow_id exists in database
        
    Returns:
        List of error messages (empty if valid)
    """
    errors = []
    node_id = node.get("id", "unknown")
    
    # Check required fields exist
    for field in SUBPROCESS_REQUIRED_FIELDS:
        if field not in node or node[field] is None:
            errors.append(f"Subprocess node '{node_id}' missing required field '{field}'")
    
    # Validate input_mapping is a dict
    input_mapping = node.get("input_mapping")
    if input_mapping is not None and not isinstance(input_mapping, dict):
        errors.append(f"Subprocess node '{node_id}': input_mapping must be a dictionary")
    
    # Validate output_variable is a valid identifier
    output_var = node.get("output_variable")
    if output_var is not None:
        if not isinstance(output_var, str):
            errors.append(f"Subprocess node '{node_id}': output_variable must be a string")
        elif not output_var.replace("_", "").isalnum():
            errors.append(
                f"Subprocess node '{node_id}': output_variable must be alphanumeric "
                f"with underscores, got '{output_var}'"
            )
    
    # Validate input_mapping references existing parent inputs
    if isinstance(input_mapping, dict):
        workflow_analysis = session_state.get("workflow_analysis", {})
        parent_inputs = workflow_analysis.get("inputs", [])
        parent_input_names = {inp.get("name", "").strip().lower() for inp in parent_inputs}
        
        for parent_input_name in input_mapping.keys():
            if parent_input_name.strip().lower() not in parent_input_names:
                errors.append(
                    f"Subprocess node '{node_id}': input_mapping references "
                    f"non-existent parent input '{parent_input_name}'"
                )
    
    # Optionally validate subworkflow exists in database
    if check_workflow_exists:
        subworkflow_id = node.get("subworkflow_id")
        if subworkflow_id:
            workflow_store = session_state.get("workflow_store")
            user_id = session_state.get("user_id")
            
            if workflow_store and user_id:
                try:
                    subworkflow = workflow_store.get_workflow(subworkflow_id, user_id)
                    if subworkflow is None:
                        errors.append(
                            f"Subprocess node '{node_id}': subworkflow_id '{subworkflow_id}' "
                            f"not found in user's workflow library"
                        )
                except Exception as e:
                    errors.append(
                        f"Subprocess node '{node_id}': failed to verify subworkflow_id "
                        f"'{subworkflow_id}': {str(e)}"
                    )
    
    return errors


def get_available_workflows_for_subflow(session_state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Get list of workflows available to use as subflows.
    
    Returns workflow summaries with id, name, inputs, and outputs
    that can be used when configuring subprocess nodes.
    
    Args:
        session_state: Current session state with workflow_store and user_id
        
    Returns:
        List of workflow summaries, empty list if unavailable
    """
    workflow_store = session_state.get("workflow_store")
    user_id = session_state.get("user_id")
    
    if not workflow_store or not user_id:
        return []
    
    try:
        workflows, _ = workflow_store.list_workflows(user_id, limit=100, offset=0)
        return [
            {
                "id": wf.id,
                "name": wf.name,
                "description": wf.description,
                "inputs": wf.inputs,
                "outputs": wf.outputs,
            }
            for wf in workflows
        ]
    except Exception:
        return []

