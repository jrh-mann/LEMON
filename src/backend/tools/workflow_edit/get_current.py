"""Get current workflow tool."""

from __future__ import annotations

import copy
from typing import Any, Dict, List

from ..core import Tool, ToolParameter


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


def format_condition(condition: Dict[str, Any], inputs: List[Dict[str, Any]]) -> str:
    """Format a decision condition as a human-readable string.
    
    Args:
        condition: The condition dict with input_id, comparator, value, value2
        inputs: List of workflow input definitions (to get input name)
        
    Returns:
        Human-readable string like "Age >= 18" or "Name contains 'John'"
    """
    if not condition:
        return "(no condition)"
    
    input_id = condition.get("input_id", "?")
    comparator = condition.get("comparator", "?")
    value = condition.get("value")
    value2 = condition.get("value2")
    
    # Try to get human-readable input name
    input_name = input_id
    for inp in inputs:
        if inp.get("id") == input_id:
            input_name = inp.get("name", input_id)
            break
    
    # Get comparator symbol/label
    comp_label = COMPARATOR_LABELS.get(comparator, comparator)
    
    # Format based on comparator type
    if comparator in ("is_true", "is_false"):
        return f"{input_name} {comp_label}"
    elif comparator in ("within_range", "date_between"):
        return f"{input_name} {comp_label} [{value}, {value2}]"
    else:
        # Format value for display
        if isinstance(value, str):
            value_str = f"'{value}'"
        else:
            value_str = str(value)
        return f"{input_name} {comp_label} {value_str}"


class GetCurrentWorkflowTool(Tool):
    """Get the current workflow displayed on the canvas.
    
    Returns workflow structure including nodes, edges, and inputs.
    For decision nodes, includes structured condition information.
    For subprocess nodes, includes subworkflow reference information.
    """

    name = "get_current_workflow"
    description = "Get the current workflow displayed on the canvas as JSON (nodes and edges)."
    parameters: List[ToolParameter] = []

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        session_state = kwargs.get("session_state", {})
        raw_workflow = session_state.get("current_workflow", {"nodes": [], "edges": []})
        
        # Deep copy to avoid modifying orchestrator state when adding defaults for tool output
        workflow = {
            "nodes": [copy.deepcopy(n) for n in raw_workflow.get("nodes", [])],
            "edges": [copy.deepcopy(e) for e in raw_workflow.get("edges", [])]
        }
        
        # Merge inputs into workflow if available
        inputs = session_state.get("workflow_analysis", {}).get("inputs", [])
        if inputs:
            workflow["inputs"] = inputs

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
            input_ref_part = f" (input: {node['input_ref']})" if node.get("input_ref") else ""
            
            # Show decision condition
            condition_part = ""
            if node.get("type") == "decision":
                condition = node.get("condition")
                if condition:
                    condition_str = format_condition(condition, inputs)
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
            
            desc = f"- {node['id']}: \"{node['label']}\" (type: {node['type']}){input_ref_part}{condition_part}{output_part}{subprocess_part}"
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
            
        input_descriptions = []
        for inp in inputs:
            type_info = inp['type']
            if inp.get('range'):
                range_info = inp['range']
                if range_info.get('min') is not None and range_info.get('max') is not None:
                    type_info += f" [{range_info['min']}-{range_info['max']}]"
            if inp.get('enum_values'):
                type_info += f" [{', '.join(inp['enum_values'])}]"
            desc = f"- {inp['id']}: {inp['name']} ({type_info})"
            input_descriptions.append(desc)

        return {
            "success": True,
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
                "input_descriptions": (
                    "\n".join(input_descriptions) if input_descriptions else "No inputs"
                ),
            },
        }
