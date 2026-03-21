"""Shared helpers for workflow edit tools.

Contains constants and validation functions for workflow nodes,
including subprocess (subflow) nodes that reference other workflows.

Also contains ``build_new_node`` which is the single source of truth for
creating a fully-configured workflow node from caller-supplied parameters.
Both ``AddNodeTool`` and ``BatchEditWorkflowTool`` delegate to it so that
validation logic (decision conditions, calculations, subprocess, end-node
output config) is never duplicated.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

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
    "calculation": "purple",
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
) -> Dict[str, Any]:
    """Get the output definition from a subworkflow.

    Used to infer the type of subprocess output variables.

    Args:
        subworkflow_id: ID of the subworkflow to query
        session_state: Current session state with workflow_store and user_id

    Returns:
        Output definition dict with 'name' and 'type', or dict with 'error' key on failure.
        For building workflows, uses the workflow's output_type field as fallback.
    """
    workflow_store = session_state.get("workflow_store")
    user_id = session_state.get("user_id")

    if not workflow_store or not user_id:
        return {"error": "No workflow_store or user_id in session — cannot look up subworkflow"}
    if not subworkflow_id:
        return {"error": "No subworkflow_id provided"}

    try:
        subworkflow = workflow_store.get_workflow(subworkflow_id, user_id)
        if subworkflow is None:
            return {"error": f"Subworkflow '{subworkflow_id}' not found in user's library"}

        # If subworkflow is still being built, use its declared output_type
        if getattr(subworkflow, "building", False):
            return {
                "name": "output",
                "type": subworkflow.output_type or "string",
                "description": None,
                "building": True,
            }

        # Get the first output (workflows typically have one primary output)
        outputs = subworkflow.outputs
        if outputs and len(outputs) > 0:
            output = outputs[0]
            return {
                "name": output.get("name", "output"),
                "type": output.get("type", "string"),
                "description": output.get("description"),
            }

        # No outputs defined — fall back to workflow's declared output_type
        return {
            "name": "output",
            "type": subworkflow.output_type or "string",
            "description": None,
        }
    except Exception as exc:
        return {"error": f"Failed to look up subworkflow '{subworkflow_id}': {exc}"}


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
                # List available variable names so the LLM can self-correct
                available = sorted(
                    var.get("name", "") for var in parent_variables if var.get("name")
                )
                errors.append(
                    f"Subprocess node '{node_id}': input_mapping references "
                    f"non-existent parent variable '{parent_var_name}'. "
                    f"Available variables: {available}"
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
                    elif getattr(subworkflow, "building", False):
                        # Subworkflow is still being built — valid reference, skip output check
                        pass
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
            # Storage uses 'inputs' field but we expose as 'variables'
            variables = wf.inputs if hasattr(wf, 'inputs') else []
            
            result.append({
                "id": wf.id,
                "name": wf.name,
                "description": wf.description,
                "variables": variables,     # Full variable list
                "outputs": wf.outputs,
            })
        return result
    except Exception:
        logger.exception("Failed to list workflows for subprocess node dropdown")
        return []


# ============================================================================
# Derived Variable Lifecycle Helpers
# ============================================================================
#
# These helpers determine what derived variables a node *should* produce,
# enabling ``modify_node`` to detect when variables need to be added,
# removed, or replaced after a node's configuration changes.
# ============================================================================


def derive_variables_for_node(
    node: Dict[str, Any],
    existing_variables: List[Dict[str, Any]],
    session_state: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Determine the derived variables a node should produce.

    Returns a list of variable dicts (may be empty) that the given node
    would auto-register.  This is a *pure query* — it does not mutate
    ``existing_variables``.

    Used by ``modify_node`` to compare before/after state and sync
    variable changes.

    Supports:
    * **calculation** nodes → one variable with ``source='calculated'``
    * **subprocess** nodes → one variable with ``source='subprocess'``
    """
    # Lazy imports to avoid circular deps at module level
    from ..workflow_input.add import generate_variable_id
    from ..workflow_input.helpers import normalize_variable_name

    node_type = node.get("type")
    node_id = node.get("id", "")
    label = node.get("label", "")
    result: List[Dict[str, Any]] = []

    # --- Calculation node: always produces a number variable ---
    if node_type == "calculation":
        calc = node.get("calculation")
        if calc:
            output_def = calc.get("output", {})
            output_name = output_def.get("name")
            if output_name:
                var_id = generate_variable_id(output_name, "number", "calculated")
                result.append({
                    "id": var_id,
                    "name": output_name,
                    "type": "number",
                    "source": "calculated",
                    "source_node_id": node_id,
                    "description": (
                        output_def.get("description")
                        or f"Calculated by '{label}'"
                    ),
                })

    # --- Subprocess node: infer type from subworkflow outputs ---
    elif node_type == "subprocess":
        output_variable = node.get("output_variable")
        subworkflow_id = node.get("subworkflow_id")
        if output_variable:
            output_info = get_subworkflow_output_type(
                subworkflow_id or "", session_state,
            )
            output_type_val = (
                output_info.get("type", "string") if output_info else "string"
            )
            output_desc = output_info.get("description") if output_info else None
            var_id = generate_variable_id(
                output_variable, output_type_val, "subprocess",
            )
            result.append({
                "id": var_id,
                "name": output_variable,
                "type": output_type_val,
                "source": "subprocess",
                "source_node_id": node_id,
                "subworkflow_id": subworkflow_id,
                "description": (
                    output_desc or f"Output from subprocess '{label}'"
                ),
            })

    return result


# ============================================================================
# Unified Node Builder
# ============================================================================
#
# ``build_new_node`` is the single source of truth for creating a new node
# dict from caller-supplied parameters.  Both ``AddNodeTool.execute()`` and
# the ``add_node`` branch inside ``BatchEditWorkflowTool.execute()`` delegate
# to it so that validation and construction logic is never duplicated.
# ============================================================================


def build_new_node(
    params: Dict[str, Any],
    variables: List[Dict[str, Any]],
    session_state: Dict[str, Any],
    *,
    node_id: Optional[str] = None,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Optional[str]]:
    """Build a fully-configured workflow node from raw parameters.

    This is the **single source of truth** for node construction.  It handles:

    * Basic fields (id, type, label, x, y, colour)
    * Decision condition validation (simple & compound)
    * Calculation validation + auto-register output variable
    * End-node output config (output_type, template, variable, value)
    * Subprocess field handling + auto-register output variable + validation
    * Pass-through of subprocess fields on non-subprocess node types

    Args:
        params: Dict with node parameters.  Expected keys mirror ``AddNodeTool``
            parameters: ``type`` (required), ``label`` (required), ``x``, ``y``,
            ``condition``, ``calculation``, ``output_type``, ``output_template``,
            ``output_variable``, ``output_value``, ``subworkflow_id``,
            ``input_mapping``.
        variables: Current list of workflow variable dicts.  **Not mutated** —
            any new variables are returned in the second element.
        session_state: Session state dict (used for subprocess validation).
        node_id: Pre-generated node ID.  If ``None`` a UUID-based ID is created.

    Returns:
        ``(new_node, new_variables, error_message)`` where:

        * ``new_node`` — the constructed node dict (empty dict on error).
        * ``new_variables`` — list of variable dicts to **append** to the
          workflow's variable list (may be empty).
        * ``error_message`` — ``None`` on success, or an error string on
          failure.  Callers decide how to surface the error (return dict vs
          raise ``ValueError``).
    """
    # Lazy imports to avoid circular deps at module level
    from .add_node import validate_decision_condition, validate_calculation
    from ..workflow_input.add import generate_variable_id
    from ..workflow_input.helpers import normalize_variable_name

    node_type: str = params["type"]
    label: str = params["label"]

    if node_id is None:
        node_id = f"node_{uuid.uuid4().hex[:8]}"

    # ------------------------------------------------------------------
    # 1. Decision condition validation
    # ------------------------------------------------------------------
    condition = params.get("condition")
    if node_type == "decision":
        if not condition:
            return {}, [], (
                f"Decision node '{label}' requires a 'condition' object. "
                "Provide: {variable: '<name>', comparator: '<comparator>', value: <value>}"
            )
        cond_err = validate_decision_condition(condition, variables)
        if cond_err:
            return {}, [], f"Invalid condition for decision node '{label}': {cond_err}"

    # ------------------------------------------------------------------
    # 2. Calculation validation
    # ------------------------------------------------------------------
    calculation = params.get("calculation")
    if node_type == "calculation":
        if not calculation:
            return {}, [], (
                f"Calculation node '{label}' requires a 'calculation' object. "
                "Provide: {output: {name: 'VarName'}, operator: 'add', operands: [...]}"
            )
        calc_err = validate_calculation(calculation, variables)
        if calc_err:
            return {}, [], f"Invalid calculation for node '{label}': {calc_err}"

    # ------------------------------------------------------------------
    # 3. Build the base node dict
    # ------------------------------------------------------------------
    new_node: Dict[str, Any] = {
        "id": node_id,
        "type": node_type,
        "label": label,
        "x": params.get("x", 0),
        "y": params.get("y", 0),
        "color": get_node_color(node_type),
    }

    new_variables: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # 4. Attach condition (decision or otherwise)
    # ------------------------------------------------------------------
    if condition:
        new_node["condition"] = condition

    # ------------------------------------------------------------------
    # 5. Attach calculation + auto-register output variable
    # ------------------------------------------------------------------
    if node_type == "calculation" and calculation:
        new_node["calculation"] = calculation

        output_def = calculation["output"]
        output_name = output_def["name"]
        output_desc = output_def.get("description")

        existing_var_names = [
            normalize_variable_name(v.get("name", "")) for v in variables
        ]
        if normalize_variable_name(output_name) not in existing_var_names:
            var_id = generate_variable_id(output_name, "number", "calculated")
            new_variables.append({
                "id": var_id,
                "name": output_name,
                "type": "number",           # Calculation output is always number
                "source": "calculated",      # Derived from calculation
                "source_node_id": node_id,   # Which node produces this
                "description": output_desc or f"Calculated by '{label}'",
            })
    elif calculation:
        # Allow calculation on other node types (unlikely but consistent)
        new_node["calculation"] = calculation

    # ------------------------------------------------------------------
    # 6. End-node output config
    # ------------------------------------------------------------------
    # Desugar unified `output` param into internal fields for end nodes.
    # Smart routing: template if contains {}, variable if name matches, else literal.
    if node_type == "end" and "output" in params:
        raw_output = params["output"]
        if isinstance(raw_output, str) and "{" in raw_output and "}" in raw_output:
            # Template string — e.g., "Your BMI is {BMI}"
            params["output_template"] = raw_output
        elif isinstance(raw_output, str):
            # Check if it matches a workflow variable name (case-insensitive)
            normalized = raw_output.strip().lower()
            matched_var = None
            for var in variables:
                if var.get("name", "").strip().lower() == normalized:
                    matched_var = var
                    break
            if matched_var:
                params["output_variable"] = raw_output
            else:
                # Plain string literal
                params["output_value"] = raw_output
        else:
            # Literal value (number, bool, etc.)
            params["output_value"] = raw_output

    if node_type == "end":
        new_node["output_type"] = params.get("output_type", "string")
        if params.get("output_variable"):
            new_node["output_variable"] = params["output_variable"]
        elif params.get("output_template"):
            new_node["output_template"] = params["output_template"]
        if params.get("output_value") is not None:
            new_node["output_value"] = params["output_value"]
    else:
        # Pass through output fields on non-end nodes (for type changes)
        if "output_type" in params:
            new_node["output_type"] = params["output_type"]
        if "output_variable" in params:
            new_node["output_variable"] = params["output_variable"]
        if "output_template" in params:
            new_node["output_template"] = params["output_template"]
        if "output_value" in params:
            new_node["output_value"] = params["output_value"]

    # ------------------------------------------------------------------
    # 7. Subprocess-specific fields
    # ------------------------------------------------------------------
    if node_type == "subprocess":
        subworkflow_id_param = params.get("subworkflow_id")
        input_mapping = params.get("input_mapping")
        output_variable = params.get("output_variable")

        if subworkflow_id_param:
            new_node["subworkflow_id"] = subworkflow_id_param
        if input_mapping is not None:
            new_node["input_mapping"] = input_mapping
        if output_variable:
            new_node["output_variable"] = output_variable

            # Auto-register output_variable as a derived variable
            existing_var_names = [
                normalize_variable_name(v.get("name", "")) for v in variables
            ]
            # Also check variables we're about to add (from calculation above)
            for nv in new_variables:
                existing_var_names.append(normalize_variable_name(nv.get("name", "")))

            if normalize_variable_name(output_variable) not in existing_var_names:
                # Infer type from subworkflow output definition
                output_info = get_subworkflow_output_type(
                    subworkflow_id_param or "", session_state,
                )
                # If subworkflow lookup failed, return the error to the LLM
                if "error" in output_info:
                    return {}, [], output_info["error"]
                output_type_val = output_info.get("type", "string")
                output_desc = output_info.get("description")

                var_id = generate_variable_id(
                    output_variable, output_type_val, "subprocess",
                )
                new_variables.append({
                    "id": var_id,
                    "name": output_variable,
                    "type": output_type_val,
                    "source": "subprocess",
                    "source_node_id": node_id,
                    "subworkflow_id": subworkflow_id_param,
                    "description": (
                        output_desc or f"Output from subprocess '{label}'"
                    ),
                })

        # Validate subprocess node (with new_variables merged)
        all_vars = list(variables) + new_variables
        mock_session = {
            **session_state,
            "workflow_analysis": {"variables": all_vars},
        }
        subprocess_errors = validate_subprocess_node(
            new_node, mock_session, check_workflow_exists=True,
        )
        if subprocess_errors:
            return {}, [], "\n".join(subprocess_errors)
    else:
        # Pass through subprocess fields on non-subprocess nodes (for type changes)
        if "subworkflow_id" in params:
            new_node["subworkflow_id"] = params["subworkflow_id"]
        if "input_mapping" in params:
            new_node["input_mapping"] = params["input_mapping"]
        if "output_variable" in params:
            new_node["output_variable"] = params["output_variable"]

    return new_node, new_variables, None


def build_modified_node(
    current_node: Dict[str, Any],
    updates: Dict[str, Any],
    variables: List[Dict[str, Any]],
    session_state: Dict[str, Any],
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[str], Optional[str]]:
    """Apply updates through the canonical node builder.

    Reuses ``build_new_node`` so add and modify paths produce the same node
    schema and derived-variable behavior.
    """
    merged = dict(current_node)
    merged.update(updates)
    if not merged.get("type"):
        return {}, [], [], "Modified node is missing type"
    if not merged.get("label"):
        return {}, [], [], "Modified node is missing label"

    rebuilt_node, rebuilt_variables, error = build_new_node(
        merged,
        variables,
        session_state,
        node_id=current_node.get("id"),
    )
    if error:
        return {}, [], [], error

    old_derived = derive_variables_for_node(current_node, variables, session_state)
    old_derived_ids = {
        v.get("id")
        for v in variables
        if v.get("source_node_id") == current_node.get("id") and v.get("id")
    }
    old_derived_ids.update(v["id"] for v in old_derived)
    new_derived_ids = {v["id"] for v in rebuilt_variables}
    removed_variable_ids = sorted(old_derived_ids - new_derived_ids)
    added_variables = [v for v in rebuilt_variables if v["id"] not in old_derived_ids]
    return rebuilt_node, added_variables, removed_variable_ids, None


# ============================================================================
# Workflow Load/Save Helpers for Multi-Workflow ID-Centric Architecture
# ============================================================================
#
# These helpers enable tools to load from DB, modify, and auto-save back.
# Every tool operation is self-contained:
# 1. Tool receives workflow_id parameter
# 2. Tool loads workflow from WorkflowStore database
# 3. Tool applies its changes to the workflow
# 4. Tool saves changes back to database immediately
# 5. Tool returns success with workflow_id for tracking
#
# This pattern ensures all changes persist automatically with no "Save" button.
# ============================================================================

_load_logger = logging.getLogger(__name__)


def _rederive_subprocess_variable_types(
    nodes: List[Dict[str, Any]],
    variables: List[Dict[str, Any]],
    session_state: Dict[str, Any],
    workflow_id: str,
) -> List[Dict[str, Any]]:
    """Re-derive subprocess variable types from their subworkflows.

    For each subprocess node, queries the subworkflow's current output type
    and updates the corresponding derived variable if it's stale. Persists
    changes to DB if any variable was updated.

    Args:
        nodes: Workflow node list (read-only)
        variables: Workflow variable list (may be replaced)
        session_state: Session state with workflow_store and user_id
        workflow_id: Parent workflow ID (for saving back)

    Returns:
        The (possibly updated) variables list.
    """
    from ..workflow_input.add import generate_variable_id

    # Build index: source_node_id → variable index for subprocess vars
    subprocess_var_idx: Dict[str, int] = {}
    for i, var in enumerate(variables):
        if var.get("source") == "subprocess" and var.get("source_node_id"):
            subprocess_var_idx[var["source_node_id"]] = i

    if not subprocess_var_idx:
        return variables  # No subprocess variables — nothing to re-derive

    dirty = False  # Track whether any variable was updated

    for node in nodes:
        if node.get("type") != "subprocess":
            continue
        node_id = node.get("id", "")
        if node_id not in subprocess_var_idx:
            continue
        subworkflow_id = node.get("subworkflow_id")
        if not subworkflow_id:
            continue  # Can't look up type without a subworkflow reference

        output_info = get_subworkflow_output_type(subworkflow_id, session_state)
        if output_info is None or "error" in output_info:
            continue  # Subworkflow not found or inaccessible — leave as-is

        current_type = output_info.get("type", "string")
        idx = subprocess_var_idx[node_id]
        existing_var = variables[idx]

        if existing_var.get("type") == current_type:
            continue  # Already up to date

        # Type changed — rebuild the variable with the new type and ID
        output_variable_name = existing_var.get("name", "")
        new_var_id = generate_variable_id(
            output_variable_name, current_type, "subprocess",
        )
        variables[idx] = {
            **existing_var,
            "id": new_var_id,
            "type": current_type,
        }
        dirty = True
        _load_logger.info(
            "Re-derived subprocess variable '%s' on node '%s': "
            "type %s -> %s (subworkflow %s)",
            output_variable_name, node_id,
            existing_var.get("type"), current_type, subworkflow_id,
        )

    # Persist updated variables to DB so the fix sticks across loads
    if dirty:
        save_workflow_changes(
            workflow_id, session_state, variables=variables,
        )

    return variables


def load_workflow_for_tool(
    workflow_id: str,
    session_state: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Load workflow from database for tool execution.

    Provides a standard way for tools to load a workflow by ID from the
    database. Returns the workflow data in a format ready for tool use.

    Args:
        workflow_id: ID of the workflow to load (e.g., "wf_abc123"). If None,
            falls back to session_state["current_workflow_id"].
        session_state: Session state containing workflow_store and user_id
        
    Returns:
        Tuple of (workflow_data, error_response):
        - On success: (workflow_data dict, None)
        - On failure: (None, error_response dict)
        
    The workflow_data dict contains:
        - nodes: List of node objects
        - edges: List of edge objects
        - variables: List of variable objects (unified format, stored as 'inputs')
        - outputs: List of output definitions
        - output_type: Declared output type for the workflow
        - name: Workflow name (for reference)
        - workflow_id: The ID (for convenience)
    """
    # Validate workflow_id is provided - fall back to current_workflow_id from session
    if not workflow_id:
        workflow_id = session_state.get("current_workflow_id")
        _load_logger.info(
            "load_workflow_for_tool: no workflow_id in args, fell back to current_workflow_id=%s",
            workflow_id,
        )

    if not workflow_id:
        _load_logger.warning(
            "load_workflow_for_tool: no workflow_id available (args=None, current_workflow_id=None)"
        )
        return None, {
            "success": False,
            "error": "workflow_id is required",
            "error_code": "MISSING_WORKFLOW_ID",
            "message": "You must provide a workflow_id. The workflow is created automatically when the canvas opens.",
        }
    
    # Get workflow_store and user_id from session
    workflow_store = session_state.get("workflow_store")
    user_id = session_state.get("user_id")
    
    if not workflow_store:
        return None, {
            "success": False,
            "error": "No workflow_store in session",
            "error_code": "NO_STORE",
            "message": "Unable to access workflow - storage not available.",
        }
    
    if not user_id:
        return None, {
            "success": False,
            "error": "No user_id in session",
            "error_code": "NO_USER",
            "message": "Unable to access workflow - user not authenticated.",
        }
    
    # Load workflow from database
    try:
        record = workflow_store.get_workflow(workflow_id, user_id)
    except Exception as e:
        return None, {
            "success": False,
            "error": f"Database error: {e}",
            "error_code": "DB_ERROR",
            "message": f"Failed to load workflow: {e}",
        }
    
    if record is None:
        _load_logger.warning(
            "load_workflow_for_tool: workflow_id=%s not found in DB for user_id=%s",
            workflow_id, user_id,
        )
        return None, {
            "success": False,
            "error": f"Workflow '{workflow_id}' not found",
            "error_code": "WORKFLOW_NOT_FOUND",
            "message": f"Workflow '{workflow_id}' not found. Check the ID or create a new workflow first.",
        }
    
    # Convert WorkflowRecord to tool-friendly dict format
    # Note: Storage uses 'inputs' but tools use 'variables' (unified format)
    variables = record.inputs
    nodes = record.nodes

    # --- Lazy re-derive subprocess variable types ---
    # When a subworkflow's output type changes (via set_workflow_output),
    # the parent workflow's derived subprocess variable becomes stale.
    # Re-derive on every load so tools always see the current type.
    variables = _rederive_subprocess_variable_types(
        nodes, variables, session_state, workflow_id,
    )

    workflow_data = {
        "workflow_id": workflow_id,
        "name": record.name,
        "nodes": nodes,
        "edges": record.edges,
        "variables": variables,
        "outputs": record.outputs,
        "output_type": record.output_type,
        "tree": record.tree,
        "doubts": record.doubts,
    }
    
    return workflow_data, None


def save_workflow_changes(
    workflow_id: str,
    session_state: Dict[str, Any],
    *,
    nodes: Optional[List[Dict[str, Any]]] = None,
    edges: Optional[List[Dict[str, Any]]] = None,
    variables: Optional[List[Dict[str, Any]]] = None,
    outputs: Optional[List[Dict[str, Any]]] = None,
    output_type: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Save workflow changes back to database.
    
    Auto-saves modified fields to the database. Only provided fields are updated.
    
    Args:
        workflow_id: ID of the workflow to update
        session_state: Session state containing workflow_store and user_id
        nodes: Updated list of nodes (optional)
        edges: Updated list of edges (optional)
        variables: Updated list of variables (optional, stored as 'inputs')
        outputs: Updated list of outputs (optional)
        output_type: Updated workflow-level output type (optional)
        
    Returns:
        None on success, or an error dict on failure.
        
    Note:
        Tools should call this after making any modifications to ensure
        changes persist to the database immediately.
    """
    # Get workflow_store and user_id from session
    workflow_store = session_state.get("workflow_store")
    user_id = session_state.get("user_id")
    
    if not workflow_store:
        return {
            "success": False,
            "error": "No workflow_store in session",
            "error_code": "NO_STORE",
            "message": "Unable to save workflow - storage not available.",
        }
    
    if not user_id:
        return {
            "success": False,
            "error": "No user_id in session",
            "error_code": "NO_USER",
            "message": "Unable to save workflow - user not authenticated.",
        }
    
    # Build update kwargs - only include provided fields
    update_kwargs: Dict[str, Any] = {}
    if nodes is not None:
        update_kwargs["nodes"] = nodes
    if edges is not None:
        update_kwargs["edges"] = edges
    if variables is not None:
        update_kwargs["inputs"] = variables  # Store as 'inputs' in database
    if outputs is not None:
        update_kwargs["outputs"] = outputs
    if output_type is not None:
        update_kwargs["output_type"] = output_type

    if nodes is not None or edges is not None:
        resolved_nodes = nodes
        resolved_edges = edges
        if resolved_nodes is None or resolved_edges is None:
            record = workflow_store.get_workflow(workflow_id, user_id)
            if record is None:
                return {
                    "success": False,
                    "error": f"Failed to load workflow '{workflow_id}' for tree sync",
                    "error_code": "WORKFLOW_NOT_FOUND",
                    "message": f"Workflow '{workflow_id}' not found or unauthorized.",
                }
            if resolved_nodes is None:
                resolved_nodes = record.nodes
            if resolved_edges is None:
                resolved_edges = record.edges

        from ...utils.flowchart import tree_from_flowchart

        update_kwargs["tree"] = tree_from_flowchart(
            resolved_nodes or [],
            resolved_edges or [],
        )
    
    # If nothing to update, return success
    if not update_kwargs:
        return None
    
    # Save to database
    try:
        success = workflow_store.update_workflow(workflow_id, user_id, **update_kwargs)
        if not success:
            return {
                "success": False,
                "error": f"Failed to update workflow '{workflow_id}'",
                "error_code": "UPDATE_FAILED",
                "message": f"Workflow '{workflow_id}' not found or unauthorized.",
            }
    except Exception as e:
        return {
            "success": False,
            "error": f"Database error: {e}",
            "error_code": "DB_ERROR",
            "message": f"Failed to save workflow: {e}",
        }
    
    return None  # Success
