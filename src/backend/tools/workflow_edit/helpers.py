"""Shared helpers for workflow edit tools.

Contains constants and validation functions for workflow nodes,
including subprocess (subflow) nodes that reference other workflows.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

def resolve_node_id(
    identifier: str,
    nodes: List[Dict[str, Any]],
) -> str:
    """Resolve a node identifier that may be a UUID or a label.

    Allows the LLM to reference nodes by human-readable label instead
    of opaque UUIDs.  If *identifier* already matches an existing node
    ID it is returned as-is.  Otherwise a case-insensitive label match
    is attempted.  Raises ValueError on zero or ambiguous matches.
    """
    # Direct ID match — fast path
    if any(n.get("id") == identifier for n in nodes):
        return identifier

    # Label match — case-insensitive
    normalised = identifier.strip().lower()
    matches = [
        n for n in nodes
        if n.get("label", "").strip().lower() == normalised
    ]
    if len(matches) == 1:
        return matches[0]["id"]
    if len(matches) > 1:
        ids = ", ".join(m["id"] for m in matches)
        raise ValueError(
            f"Ambiguous label '{identifier}' matches {len(matches)} nodes ({ids}). "
            f"Use the node ID to be specific."
        )
    # No match at all
    available = ", ".join(
        f"{n.get('id')}: {n.get('label')}" for n in nodes
    ) or "none"
    raise ValueError(
        f"Node not found: '{identifier}'. Available: {available}"
    )


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


def variable_ref_error(var_ref: Optional[str], session_state: Dict[str, Any]) -> Optional[str]:
    """Check if a variable reference is valid.
    
    Args:
        var_ref: Name of the variable being referenced
        session_state: Current session state with workflow_analysis
        
    Returns:
        Error message if variable not found, None if valid
    """
    if not var_ref:
        return None
    workflow_analysis = session_state.get("workflow_analysis", {})
    variables = workflow_analysis.get("variables", [])
    normalized_ref = var_ref.strip().lower()
    var_exists = any(
        var.get("name", "").strip().lower() == normalized_ref
        for var in variables
    )
    if var_exists:
        return None
    return f"Variable '{var_ref}' not found. Register it first with add_workflow_variable."


def get_subworkflow_output_type(
    subworkflow_id: str,
    session_state: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Get the output definition from a subworkflow.
    
    Used to infer the type of subprocess output variables.
    
    Args:
        subworkflow_id: ID of the subworkflow to query
        session_state: Current session state with workflow_store and user_id
        
    Returns:
        Output definition dict with 'name' and 'type', or None if not found
    """
    workflow_store = session_state.get("workflow_store")
    user_id = session_state.get("user_id")
    
    if not workflow_store or not user_id or not subworkflow_id:
        return None
    
    try:
        subworkflow = workflow_store.get_workflow(subworkflow_id, user_id)
        if subworkflow is None:
            return None
        
        # Get the first output (workflows typically have one primary output)
        outputs = subworkflow.outputs
        if outputs and len(outputs) > 0:
            output = outputs[0]
            return {
                "name": output.get("name", "output"),
                "type": output.get("type", "string"),  # Default to string if no type
                "description": output.get("description"),
            }
        
        # No outputs defined - return default
        return {
            "name": "output",
            "type": "string",
            "description": None,
        }
    except Exception:
        return None


def validate_subprocess_node(
    node: Dict[str, Any],
    session_state: Dict[str, Any],
    check_workflow_exists: bool = True,
) -> List[str]:
    """Validate subprocess node has required fields and valid references.
    
    Subprocess nodes reference other workflows (subflows) and must have:
    - subworkflow_id: ID of the workflow to execute
    - input_mapping: Dict mapping parent variables to subworkflow inputs
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
    
    # Validate input_mapping references existing parent variables
    if isinstance(input_mapping, dict):
        workflow_analysis = session_state.get("workflow_analysis", {})
        # Use unified variables list
        parent_variables = workflow_analysis.get("variables", [])
        parent_var_names = {var.get("name", "").strip().lower() for var in parent_variables}
        
        for parent_var_name in input_mapping.keys():
            if parent_var_name.strip().lower() not in parent_var_names:
                errors.append(
                    f"Subprocess node '{node_id}': input_mapping references "
                    f"non-existent parent variable '{parent_var_name}'"
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
                    else:
                        # Validate subworkflow has output type defined
                        outputs = subworkflow.outputs
                        if outputs and len(outputs) > 0:
                            first_output = outputs[0]
                            if not first_output.get("type"):
                                errors.append(
                                    f"Subprocess node '{node_id}': subworkflow '{subworkflow.name}' "
                                    f"does not have an output type defined. "
                                    f"Please update the subworkflow to specify output type."
                                )
                except Exception as e:
                    errors.append(
                        f"Subprocess node '{node_id}': failed to verify subworkflow_id "
                        f"'{subworkflow_id}': {str(e)}"
                    )
    
    return errors


def get_available_workflows_for_subflow(session_state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Get list of workflows available to use as subflows.
    
    Returns workflow summaries with id, name, variables (inputs), and outputs
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
        result = []
        for wf in workflows:
            # Get input variables from the workflow
            # The storage still uses 'inputs' field but we expose as 'variables'
            variables = wf.inputs if hasattr(wf, 'inputs') else []
            # Filter to only input-type variables for subflow mapping
            input_variables = [
                v for v in variables 
                if v.get("source", "input") == "input"
            ]
            
            result.append({
                "id": wf.id,
                "name": wf.name,
                "description": wf.description,
                "inputs": input_variables,  # For backwards compat in input_mapping
                "variables": variables,     # Full variable list
                "outputs": wf.outputs,
            })
        return result
    except Exception:
        return []
