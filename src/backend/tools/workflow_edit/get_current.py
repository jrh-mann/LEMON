"""Get current workflow tool.

Multi-workflow architecture:
- Requires workflow_id parameter (workflow must exist in library)
- Loads workflow from database
- Read-only - does not save changes
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List

from ..core import Tool, ToolParameter
from .helpers import load_workflow_for_tool


# Human-readable labels for comparators
COMPARATOR_LABELS = {
    # Numeric
    "eq": "=",
    "neq": "≠",
    "lt": "<",
    "lte": "≤",
    "gt": ">",
    "gte": "≥",
    "within_range": "in range",
    # Boolean
    "is_true": "is true",
    "is_false": "is false",
    # String
    "str_eq": "equals",
    "str_neq": "not equals",
    "str_contains": "contains",
    "str_starts_with": "starts with",
    "str_ends_with": "ends with",
    # Date
    "date_eq": "=",
    "date_before": "before",
    "date_after": "after",
    "date_between": "between",
    # Enum
    "enum_eq": "=",
    "enum_neq": "≠",
}


def format_condition(condition: Dict[str, Any], variables: List[Dict[str, Any]]) -> str:
    """Format a decision condition as a human-readable string.
    
    Args:
        condition: The condition dict with input_id, comparator, value, value2
        variables: List of workflow variable definitions (to get variable name)
        
    Returns:
        Human-readable string like "Age >= 18" or "Name contains 'John'"
    """
    if not condition:
        return "(no condition)"
    
    input_id = condition.get("input_id", "?")
    comparator = condition.get("comparator", "?")
    value = condition.get("value")
    value2 = condition.get("value2")
    
    # Try to get human-readable variable name
    var_name = input_id
    for var in variables:
        if var.get("id") == input_id:
            var_name = var.get("name", input_id)
            break
    
    # Get comparator symbol/label
    comp_label = COMPARATOR_LABELS.get(comparator, comparator)
    
    # Format based on comparator type
    if comparator in ("is_true", "is_false"):
        return f"{var_name} {comp_label}"
    elif comparator in ("within_range", "date_between"):
        return f"{var_name} {comp_label} [{value}, {value2}]"
    else:
        # Format value for display
        if isinstance(value, str):
            value_str = f"'{value}'"
        else:
            value_str = str(value)
        return f"{var_name} {comp_label} {value_str}"


def format_variable_description(var: Dict[str, Any]) -> str:
    """Format a single variable for human-readable display.
    
    Args:
        var: Variable definition dict
        
    Returns:
        Formatted string like "- var_age_int: Age (int [0-120])"
    """
    type_info = var.get('type', 'unknown')
    
    # Add range info for numeric types
    if var.get('range'):
        range_info = var['range']
        if range_info.get('min') is not None and range_info.get('max') is not None:
            type_info += f" [{range_info['min']}-{range_info['max']}]"
        elif range_info.get('min') is not None:
            type_info += f" [min={range_info['min']}]"
        elif range_info.get('max') is not None:
            type_info += f" [max={range_info['max']}]"
    
    # Add enum values
    if var.get('enum_values'):
        type_info += f" [{', '.join(var['enum_values'])}]"
    
    # Add source info for derived variables
    source = var.get('source', 'input')
    source_info = ""
    if source != 'input':
        source_info = f" (source: {source})"
        if source == 'subprocess' and var.get('source_node_id'):
            source_info = f" (from: {var['source_node_id']})"
    
    return f"- {var['id']}: {var.get('name', '?')} ({type_info}){source_info}"


class GetCurrentWorkflowTool(Tool):
    """Get the current workflow from the database.
    
    Returns workflow structure including nodes, edges, and variables.
    For decision nodes, includes structured condition information.
    For subprocess nodes, includes subworkflow reference information.
    Variables are organized by source (inputs, subprocess outputs, etc).
    """

    name = "get_current_workflow"
    description = "Get a workflow from the library as JSON (nodes, edges, variables). Requires workflow_id."
    parameters: List[ToolParameter] = [
        ToolParameter(
            "workflow_id",
            "string",
            "ID of the workflow to retrieve (from create_workflow)",
            required=True,
        ),
    ]

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        session_state = kwargs.get("session_state", {})
        workflow_id = args.get("workflow_id")
        
        # Load workflow from database
        workflow_data, error = load_workflow_for_tool(workflow_id, session_state)
        if error:
            return error
        # Use the workflow_id from loaded data (handles fallback to current_workflow_id)
        workflow_id = workflow_data["workflow_id"]
        
        # Deep copy to avoid any issues
        workflow = {
            "nodes": [copy.deepcopy(n) for n in workflow_data.get("nodes", [])],
            "edges": [copy.deepcopy(e) for e in workflow_data.get("edges", [])],
        }
        
        # Get variables from loaded data
        variables = workflow_data.get("variables", [])
        if variables:
            workflow["variables"] = variables

        # Ensure output fields are present in the JSON data for 'end' nodes
        for node in workflow["nodes"]:
            if node.get("type") == "end":
                node.setdefault("output_type", "string")
                node.setdefault("output_template", "")
                node.setdefault("output_value", None)
            # Ensure decision nodes have condition field visible
            elif node.get("type") == "decision":
                node.setdefault("condition", None)
            # Ensure subprocess fields are present for 'subprocess' nodes
            elif node.get("type") == "subprocess":
                node.setdefault("subworkflow_id", None)
                node.setdefault("input_mapping", {})
                node.setdefault("output_variable", None)

        node_descriptions = []
        for node in workflow.get("nodes", []):
            # Show decision condition
            condition_part = ""
            if node.get("type") == "decision":
                condition = node.get("condition")
                if condition:
                    condition_str = format_condition(condition, variables)
                    condition_part = f" [Condition: {condition_str}]"
                else:
                    condition_part = " [Condition: NOT SET - node will fail at execution!]"
            
            output_part = ""
            if node.get("type") == "end":
                parts = []
                if node.get("output_type"):
                    parts.append(f"type={node['output_type']}")
                if node.get("output_template"):
                    parts.append(f"template='{node['output_template']}'")
                if node.get("output_value"):
                    parts.append(f"value={node['output_value']}")
                if parts:
                    output_part = f" [Output: {', '.join(parts)}]"
            
            # Show subprocess configuration
            subprocess_part = ""
            if node.get("type") == "subprocess":
                parts = []
                if node.get("subworkflow_id"):
                    parts.append(f"calls={node['subworkflow_id']}")
                if node.get("input_mapping"):
                    mapping_str = ", ".join(
                        f"{k}->{v}" for k, v in node['input_mapping'].items()
                    )
                    parts.append(f"maps=[{mapping_str}]")
                if node.get("output_variable"):
                    parts.append(f"output_as={node['output_variable']}")
                if parts:
                    subprocess_part = f" [Subflow: {', '.join(parts)}]"
            
            desc = f"- {node['id']}: \"{node['label']}\" (type: {node['type']}){condition_part}{output_part}{subprocess_part}"
            node_descriptions.append(desc)

        edge_descriptions = []
        for edge in workflow.get("edges", []):
            from_label = next(
                (n["label"] for n in workflow.get("nodes", []) if n["id"] == edge["from"]),
                "?",
            )
            to_label = next(
                (n["label"] for n in workflow.get("nodes", []) if n["id"] == edge["to"]),
                "?",
            )
            label_part = f" [{edge.get('label', '')}]" if edge.get("label") else ""
            desc = f"- {edge['from']} -> {edge['to']}: \"{from_label}\"{label_part} -> \"{to_label}\""
            edge_descriptions.append(desc)
        
        # Organize variables by source for clearer display
        input_vars = [v for v in variables if v.get('source', 'input') == 'input']
        derived_vars = [v for v in variables if v.get('source', 'input') != 'input']
        
        # Format input variables
        input_descriptions = []
        if input_vars:
            input_descriptions.append("User Inputs:")
            for var in input_vars:
                input_descriptions.append("  " + format_variable_description(var))
        
        # Format derived variables (subprocess outputs, calculated, etc)
        if derived_vars:
            if input_descriptions:
                input_descriptions.append("")  # Blank line separator
            input_descriptions.append("Derived Variables:")
            for var in derived_vars:
                input_descriptions.append("  " + format_variable_description(var))

        return {
            "success": True,
            "workflow_id": workflow_id,
            "name": workflow_data.get("name", ""),
            "output_type": workflow_data.get("output_type", "string"),
            "workflow": workflow,
            "node_count": len(workflow.get("nodes", [])),
            "edge_count": len(workflow.get("edges", [])),
            "summary": {
                "node_count": len(workflow.get("nodes", [])),
                "edge_count": len(workflow.get("edges", [])),
                "node_descriptions": (
                    "\n".join(node_descriptions) if node_descriptions else "No nodes"
                ),
                "edge_descriptions": (
                    "\n".join(edge_descriptions) if edge_descriptions else "No connections"
                ),
                "variable_descriptions": (
                    "\n".join(input_descriptions) if input_descriptions else "No variables"
                ),
                # Backwards compatibility alias
                "input_descriptions": (
                    "\n".join(input_descriptions) if input_descriptions else "No variables"
                ),
            },
        }
