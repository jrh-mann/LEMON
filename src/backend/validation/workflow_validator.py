"""Workflow validation system for syntactic correctness."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

from src.backend.execution.parser import parse_condition, ParseError
from src.backend.execution.types import Variable, BinaryOp, UnaryOp


# Required fields for subprocess nodes
SUBPROCESS_REQUIRED_FIELDS = ["subworkflow_id", "input_mapping", "output_variable"]

# Valid comparators by variable type for structured conditions
VALID_COMPARATORS_BY_TYPE = {
    "int": {"eq", "neq", "lt", "lte", "gt", "gte", "within_range"},
    "float": {"eq", "neq", "lt", "lte", "gt", "gte", "within_range"},
    "bool": {"is_true", "is_false"},
    "string": {"str_eq", "str_neq", "str_contains", "str_starts_with", "str_ends_with"},
    "date": {"date_eq", "date_before", "date_after", "date_between"},
    "enum": {"enum_eq", "enum_neq"},
}

# Regex to extract template variables like {var_name}
TEMPLATE_VAR_PATTERN = re.compile(r'\{([^}]+)\}')


@dataclass
class ValidationError:
    """Represents a workflow validation error."""

    code: str
    message: str
    node_id: Optional[str] = None
    edge_id: Optional[str] = None


class WorkflowValidator:
    """Validates workflow structure for syntactic correctness."""

    VALID_NODE_TYPES = {"start", "process", "decision", "subprocess", "end"}
    REQUIRED_NODE_FIELDS = {"id", "type", "label", "x", "y"}

    def validate(
        self,
        workflow: Dict[str, Any],
        strict: bool = True
    ) -> Tuple[bool, List[ValidationError]]:
        """
        Validate a workflow and return (is_valid, errors).

        Args:
            workflow: The workflow to validate
            strict: If True, enforce complete workflow rules (decision branches, connections).
                   If False, only validate structure (useful for incremental edits).

        Rules (always enforced):
        1. All nodes must have: id, type, label, x, y
        2. Node types must be: start, process, decision, subprocess, or end
        3. All edge 'from' and 'to' must reference existing node IDs
        4. No duplicate node IDs
        5. No duplicate edge IDs
        6. Workflow must have at most 1 start node (no multiple start nodes)
        7. No self-loops (edges where from == to)
        8. No cycles (workflow must be a directed acyclic graph)

        Rules (strict mode only):
        9. Workflow must have at least 1 start node (if nodes exist)
        10. Decision nodes must have at least 2 outgoing edges (true/false paths)
        11. Start nodes should have at least 1 outgoing edge
        12. End nodes should have 0 outgoing edges
        13. Decision nodes must have all referenced variables registered as workflow variables
        """
        errors: List[ValidationError] = []
        nodes = workflow.get("nodes", [])
        edges = workflow.get("edges", [])

        # Collect node IDs for validation
        node_ids: Set[str] = set()

        # Collect registered variable names (if available)
        # Support both new 'variables' field and legacy 'inputs' field
        valid_var_names: Optional[Set[str]] = None
        workflow_variables = workflow.get("variables", []) or workflow.get("inputs", [])
        if workflow_variables:
            valid_var_names = {v.get("name") for v in workflow_variables if v.get("name")}
        
        # Backwards compat alias
        valid_input_names = valid_var_names
        workflow_inputs = workflow_variables

        # Rule 1 & 2: Validate node structure
        for node in nodes:
            node_id = node.get("id")

            # Check for required fields
            missing_fields = self.REQUIRED_NODE_FIELDS - set(node.keys())
            if missing_fields:
                errors.append(
                    ValidationError(
                        code="INCOMPLETE_NODE",
                        message=f"Node missing required fields: {node_id or 'unknown'}",
                        node_id=node_id,
                    )
                )
                continue

            # Validate node type
            node_type = node.get("type")
            if node_type not in self.VALID_NODE_TYPES:
                errors.append(
                    ValidationError(
                        code="INVALID_NODE_TYPE",
                        message=f"Invalid node type '{node_type}' for node {node_id}",
                        node_id=node_id,
                    )
                )

            # Rule 4: Check for duplicate IDs
            if node_id in node_ids:
                errors.append(
                    ValidationError(
                        code="DUPLICATE_NODE_ID",
                        message=f"Duplicate node ID: {node_id}",
                        node_id=node_id,
                    )
                )
            node_ids.add(node_id)

            # Validate subprocess nodes have required fields
            if node_type == "subprocess":
                subprocess_errors = self._validate_subprocess_node(node, valid_input_names)
                errors.extend(subprocess_errors)

            # Rule 9: Validate decision nodes have structured conditions
            if node_type == "decision":
                condition = node.get("condition")
                if condition:
                    # Validate structured condition
                    input_id = condition.get("input_id")
                    comparator = condition.get("comparator")
                    
                    if not input_id:
                        errors.append(
                            ValidationError(
                                code="MISSING_CONDITION_INPUT_ID",
                                message=f"Decision node '{node.get('label', node_id)}' has condition without input_id",
                                node_id=node_id,
                            )
                        )
                    elif workflow_variables:
                        # Check if input_id matches any registered variable's id
                        var_ids = [v.get("id") for v in workflow_variables if v.get("id")]
                        if input_id not in var_ids:
                            errors.append(
                                ValidationError(
                                    code="INVALID_CONDITION_INPUT_ID",
                                    message=f"Decision node '{node.get('label', node_id)}' references unknown variable id '{input_id}'",
                                    node_id=node_id,
                                )
                            )
                        else:
                            # Validate comparator is valid for the variable's type
                            matching_var = next(
                                (v for v in workflow_variables if v.get("id") == input_id),
                                None
                            )
                            if matching_var and comparator:
                                var_type = matching_var.get("type", "string")
                                valid_comparators = VALID_COMPARATORS_BY_TYPE.get(var_type, set())
                                if comparator not in valid_comparators:
                                    errors.append(
                                        ValidationError(
                                            code="INVALID_COMPARATOR_FOR_TYPE",
                                            message=(
                                                f"Decision node '{node.get('label', node_id)}': "
                                                f"comparator '{comparator}' is not valid for variable type '{var_type}'. "
                                                f"Valid comparators: {sorted(valid_comparators)}"
                                            ),
                                            node_id=node_id,
                                        )
                                    )
                    
                    if not comparator:
                        errors.append(
                            ValidationError(
                                code="MISSING_CONDITION_COMPARATOR",
                                message=f"Decision node '{node.get('label', node_id)}' has condition without comparator",
                                node_id=node_id,
                            )
                        )
                else:
                    # No structured condition - check legacy label-based condition
                    # This is still allowed for backwards compatibility
                    condition_str = node.get("label", "")
                    try:
                        expr = parse_condition(condition_str)
                        referenced_vars = self._get_variables(expr)

                        # Check if variables are registered (always enforced when variables exist)
                        if valid_var_names is not None:
                            for var in referenced_vars:
                                if var not in valid_var_names:
                                    errors.append(
                                        ValidationError(
                                            code="INVALID_INPUT_REF",
                                            message=f"Decision references unregistered variable: '{var}'",
                                            node_id=node_id,
                                        )
                                    )
                        # In strict mode, require all decision variables to be registered
                        elif strict and referenced_vars:
                            # No variables registered but decision uses variables
                            var_list = ", ".join(f"'{v}'" for v in sorted(referenced_vars))
                            errors.append(
                                ValidationError(
                                    code="DECISION_MISSING_INPUT",
                                    message=f"Decision node '{node.get('label', node_id)}' references variables {var_list} but no workflow variables are registered. Register variables using add_workflow_variable tool.",
                                    node_id=node_id,
                                )
                            )
                    except ParseError:
                        # Label is descriptive text, not a condition
                        # In strict mode, descriptive labels without structured conditions are allowed
                        # The decision logic is assumed to be handled programmatically
                        pass
                    except Exception:
                        pass
            
            # Validate end/output nodes have valid templates
            if node_type in ("end", "output"):
                template_errors = self._validate_output_template(
                    node, workflow_inputs, valid_input_names
                )
                errors.extend(template_errors)

        # Track edge connections
        edge_ids: Set[str] = set()
        outgoing_edges: Dict[str, List[str]] = {}  # node_id -> list of edge labels
        incoming_edges: Dict[str, int] = {}  # node_id -> count

        # Rule 3 & 5: Validate edges
        for edge in edges:
            edge_id = edge.get("id", f"{edge.get('from')}->{edge.get('to')}")
            from_id = edge.get("from")
            to_id = edge.get("to")

            # Check source node exists
            if from_id not in node_ids:
                errors.append(
                    ValidationError(
                        code="INVALID_EDGE_SOURCE",
                        message=f"Edge references non-existent source node: {from_id}",
                        edge_id=edge_id,
                    )
                )

            # Check target node exists
            if to_id not in node_ids:
                errors.append(
                    ValidationError(
                        code="INVALID_EDGE_TARGET",
                        message=f"Edge references non-existent target node: {to_id}",
                        edge_id=edge_id,
                    )
                )

            # Rule 5: Check for duplicate edge IDs
            if edge_id in edge_ids:
                errors.append(
                    ValidationError(
                        code="DUPLICATE_EDGE_ID",
                        message=f"Duplicate edge ID: {edge_id}",
                        edge_id=edge_id,
                    )
                )
            edge_ids.add(edge_id)

            # Track connections for later validation
            if from_id not in outgoing_edges:
                outgoing_edges[from_id] = []
            outgoing_edges[from_id].append(edge.get("label", ""))

            incoming_edges[to_id] = incoming_edges.get(to_id, 0) + 1

        # Rule 9: Validate start node count (always enforced for multiple, strict for zero)
        start_nodes = [n for n in nodes if n.get("type") == "start"]

        # Multiple start nodes is always invalid
        if len(start_nodes) > 1:
            start_labels = [n.get("label", n.get("id", "unknown")) for n in start_nodes]
            errors.append(
                ValidationError(
                    code="MULTIPLE_START_NODES",
                    message=f"Workflow has {len(start_nodes)} start nodes but must have exactly one. Found: {', '.join(start_labels)}",
                    node_id=None,
                )
            )

        # In strict mode, require at least one start node for non-empty workflows
        if strict and len(start_nodes) == 0 and len(nodes) > 0:
            errors.append(
                ValidationError(
                    code="NO_START_NODE",
                    message="Workflow has no start node. Add a start node to define the entry point.",
                    node_id=None,
                )
            )

        # Rule 10: Detect self-loops (always enforced)
        for edge in edges:
            from_id = edge.get("from")
            to_id = edge.get("to")
            edge_id = edge.get("id", f"{from_id}->{to_id}")

            if from_id == to_id and from_id in node_ids:
                # Get node label for better error message
                node_label = next(
                    (n.get("label", from_id) for n in nodes if n.get("id") == from_id),
                    from_id
                )
                errors.append(
                    ValidationError(
                        code="SELF_LOOP_DETECTED",
                        message=f"Self-loop detected on node '{node_label}'. Cycles are not allowed.",
                        node_id=from_id,
                    )
                )

        # Rule 11: Detect cycles using DFS (always enforced)
        cycle_errors = self._detect_cycles(nodes, edges)
        errors.extend(cycle_errors)

        # Rules 6, 7, 8, 11: Validate node-specific connection requirements and reachability (strict mode only)
        if strict:
            # Rule 11: Check for unreachable nodes
            # Find all start nodes
            start_node_ids = {n["id"] for n in nodes if n.get("type") == "start"}
            
            if start_node_ids:
                # Perform BFS traversal to find all reachable nodes
                reachable_ids = set(start_node_ids)
                queue = list(start_node_ids)
                
                # Build adjacency list for traversal
                # node_id -> list of target_ids
                adjacency_list: Dict[str, List[str]] = {}
                for edge in edges:
                    u, v = edge.get("from"), edge.get("to")
                    if u and v:
                        if u not in adjacency_list:
                            adjacency_list[u] = []
                        adjacency_list[u].append(v)
                
                while queue:
                    curr_id = queue.pop(0)
                    neighbors = adjacency_list.get(curr_id, [])
                    for neighbor_id in neighbors:
                        if neighbor_id not in reachable_ids:
                            reachable_ids.add(neighbor_id)
                            queue.append(neighbor_id)
                
                # Check for unreachable nodes
                all_node_ids = {n["id"] for n in nodes if n.get("id")}
                unreachable_ids = all_node_ids - reachable_ids
                
                if unreachable_ids:
                    # Sort for deterministic error ordering
                    for node_id in sorted(unreachable_ids):
                         # Get label for better message
                        node_label = next(
                            (n.get("label", node_id) for n in nodes if n.get("id") == node_id),
                            node_id
                        )
                        errors.append(
                            ValidationError(
                                code="UNREACHABLE_NODE",
                                message=f"Node '{node_label}' is not reachable from any start node",
                                node_id=node_id,
                            )
                        )

            for node in nodes:
                node_id = node.get("id")
                if not node_id:
                    continue

                node_type = node.get("type")
                node_label = node.get("label", node_id)
                outgoing = outgoing_edges.get(node_id, [])

                # Rule 6: Decision nodes must have 2+ outgoing edges
                if node_type == "decision":
                    if len(outgoing) < 2:
                        errors.append(
                            ValidationError(
                                code="DECISION_NEEDS_BRANCHES",
                                message=f"Decision node '{node_label}' must have at least 2 branches",
                                node_id=node_id,
                            )
                        )
                    # Check for true/false labels
                    labels = set(outgoing)
                    if "true" not in labels or "false" not in labels:
                        errors.append(
                            ValidationError(
                                code="DECISION_MISSING_LABELS",
                                message=f"Decision node '{node_label}' should have 'true' and 'false' branches",
                                node_id=node_id,
                            )
                        )

                # Rule 12: Process/Subprocess nodes must have outgoing edges
                if node_type in ("process", "subprocess") and len(outgoing) == 0:
                    errors.append(
                        ValidationError(
                            code="DEAD_END_NODE",
                            message=f"{node_type.capitalize()} node '{node_label}' has no outgoing connections. Flow must continue or end explicitly.",
                            node_id=node_id,
                        )
                    )

                # Rule 7: Start nodes should have outgoing edges (only if workflow has multiple nodes)
                if node_type == "start" and len(outgoing) == 0 and len(nodes) > 1:
                    errors.append(
                        ValidationError(
                            code="START_NO_OUTGOING",
                            message=f"Start node '{node_label}' has no outgoing connections",
                            node_id=node_id,
                        )
                    )

                # Rule 8: End nodes should have NO outgoing edges
                if node_type == "end" and len(outgoing) > 0:
                    errors.append(
                        ValidationError(
                            code="END_HAS_OUTGOING",
                            message=f"End node '{node_label}' should not have outgoing connections",
                            node_id=node_id,
                        )
                    )

        return (len(errors) == 0, errors)

    def _detect_cycles(
        self, nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]
    ) -> List[ValidationError]:
        """
        Detect cycles in the workflow graph using depth-first search.

        Uses three-color DFS algorithm:
        - WHITE (0): Not visited
        - GRAY (1): Currently being explored (in DFS stack)
        - BLACK (2): Completely explored

        A cycle exists if we encounter a GRAY node during exploration.

        Args:
            nodes: List of workflow nodes
            edges: List of workflow edges

        Returns:
            List of ValidationError objects for any cycles found
        """
        errors: List[ValidationError] = []

        # Build adjacency list for graph traversal
        # adjacency[node_id] = [list of target node IDs]
        adjacency: Dict[str, List[str]] = {}
        node_labels: Dict[str, str] = {}

        for node in nodes:
            node_id = node.get("id")
            if node_id:
                adjacency[node_id] = []
                node_labels[node_id] = node.get("label", node_id)

        for edge in edges:
            from_id = edge.get("from")
            to_id = edge.get("to")
            # Only add edges between valid nodes (already validated)
            if from_id in adjacency and to_id in adjacency:
                adjacency[from_id].append(to_id)

        # DFS state: WHITE=0 (not visited), GRAY=1 (in progress), BLACK=2 (done)
        WHITE, GRAY, BLACK = 0, 1, 2
        color: Dict[str, int] = {node_id: WHITE for node_id in adjacency}
        parent: Dict[str, Optional[str]] = {node_id: None for node_id in adjacency}

        def dfs_visit(node_id: str) -> Optional[List[str]]:
            """
            Visit a node during DFS.

            Returns:
                List of node IDs forming the cycle if one is detected, None otherwise
            """
            color[node_id] = GRAY

            for neighbor_id in adjacency[node_id]:
                if color[neighbor_id] == GRAY:
                    # Back edge found - cycle detected!
                    # Reconstruct the cycle path
                    cycle_path = [neighbor_id]
                    current = node_id
                    while current != neighbor_id and current is not None:
                        cycle_path.append(current)
                        current = parent.get(current)
                    cycle_path.append(neighbor_id)
                    cycle_path.reverse()
                    return cycle_path

                elif color[neighbor_id] == WHITE:
                    parent[neighbor_id] = node_id
                    cycle = dfs_visit(neighbor_id)
                    if cycle:
                        return cycle

            color[node_id] = BLACK
            return None

        # Run DFS from each unvisited node (handles disconnected components)
        for node_id in adjacency:
            if color[node_id] == WHITE:
                cycle_path = dfs_visit(node_id)
                if cycle_path:
                    # Format the cycle path for error message
                    cycle_labels = [node_labels.get(nid, nid) for nid in cycle_path]
                    cycle_str = " → ".join(cycle_labels)

                    errors.append(
                        ValidationError(
                            code="CYCLE_DETECTED",
                            message=f"Cycle detected in workflow: {cycle_str}. Workflows must be acyclic.",
                            node_id=cycle_path[0] if cycle_path else None,
                        )
                    )
                    # Report only the first cycle found
                    break

        return errors

    def _get_variables(self, expr: Any) -> Set[str]:
        """Extract all variable names from an expression tree."""
        variables = set()

        if isinstance(expr, Variable):
            variables.add(expr.name)
        elif isinstance(expr, UnaryOp):
            variables.update(self._get_variables(expr.operand))
        elif isinstance(expr, BinaryOp):
            variables.update(self._get_variables(expr.left))
            variables.update(self._get_variables(expr.right))

        return variables

    def _validate_subprocess_node(
        self,
        node: Dict[str, Any],
        valid_var_names: Optional[Set[str]],
    ) -> List[ValidationError]:
        """Validate subprocess node has required fields and valid references.
        
        Subprocess nodes reference other workflows (subflows) and must have:
        - subworkflow_id: ID of the workflow to execute
        - input_mapping: Dict mapping parent variables to subworkflow inputs  
        - output_variable: Name of variable to store subflow output
        
        Args:
            node: The subprocess node to validate
            valid_var_names: Set of valid variable names from parent workflow
            
        Returns:
            List of ValidationError objects for any issues found
        """
        errors = []
        node_id = node.get("id", "unknown")
        node_label = node.get("label", node_id)
        
        # Check required fields exist
        for field in SUBPROCESS_REQUIRED_FIELDS:
            if field not in node or node[field] is None:
                errors.append(
                    ValidationError(
                        code="SUBPROCESS_MISSING_FIELD",
                        message=f"Subprocess node '{node_label}' missing required field '{field}'",
                        node_id=node_id,
                    )
                )
        
        # Validate input_mapping is a dict
        input_mapping = node.get("input_mapping")
        if input_mapping is not None and not isinstance(input_mapping, dict):
            errors.append(
                ValidationError(
                    code="SUBPROCESS_INVALID_MAPPING",
                    message=f"Subprocess node '{node_label}': input_mapping must be a dictionary",
                    node_id=node_id,
                )
            )
        
        # Validate output_variable is a valid identifier
        output_var = node.get("output_variable")
        if output_var is not None:
            if not isinstance(output_var, str):
                errors.append(
                    ValidationError(
                        code="SUBPROCESS_INVALID_OUTPUT",
                        message=f"Subprocess node '{node_label}': output_variable must be a string",
                        node_id=node_id,
                    )
                )
            elif not output_var.replace("_", "").isalnum():
                errors.append(
                    ValidationError(
                        code="SUBPROCESS_INVALID_OUTPUT",
                        message=(
                            f"Subprocess node '{node_label}': output_variable must be "
                            f"alphanumeric with underscores, got '{output_var}'"
                        ),
                        node_id=node_id,
                    )
                )
        
        # Validate input_mapping references existing parent variables
        if isinstance(input_mapping, dict) and valid_var_names is not None:
            for parent_var_name in input_mapping.keys():
                if parent_var_name not in valid_var_names:
                    errors.append(
                        ValidationError(
                            code="SUBPROCESS_INVALID_INPUT_REF",
                            message=(
                                f"Subprocess node '{node_label}': input_mapping references "
                                f"non-existent parent variable '{parent_var_name}'"
                            ),
                            node_id=node_id,
                        )
                    )
        
        return errors

    def _validate_output_template(
        self,
        node: Dict[str, Any],
        workflow_variables: List[Dict[str, Any]],
        valid_var_names: Optional[Set[str]],
    ) -> List[ValidationError]:
        """Validate output/end node templates reference valid variables.
        
        Checks both output_template field and label field for {variable} syntax
        and ensures all referenced variables are registered workflow variables.
        
        Args:
            node: The end/output node to validate
            workflow_variables: List of workflow variable definitions
            valid_var_names: Set of valid variable names
            
        Returns:
            List of ValidationError objects for any issues found
        """
        errors = []
        node_id = node.get("id", "unknown")
        node_label = node.get("label", node_id)
        
        # Build set of valid variable names (variable names and variable IDs)
        valid_vars: Set[str] = set()
        if valid_var_names:
            valid_vars.update(valid_var_names)
        # Also allow referencing by variable ID (e.g., var_bmi_float)
        for var in workflow_variables:
            if var.get("id"):
                valid_vars.add(var["id"])
        
        # Check output_template field
        template = node.get("output_template", "")
        if template:
            template_vars = TEMPLATE_VAR_PATTERN.findall(template)
            for var in template_vars:
                if var not in valid_vars:
                    errors.append(
                        ValidationError(
                            code="INVALID_TEMPLATE_VARIABLE",
                            message=(
                                f"End node '{node_label}': template references unknown variable '{{{var}}}'. "
                                f"Available variables: {sorted(valid_var_names or [])}"
                            ),
                            node_id=node_id,
                        )
                    )
        
        # Also check label if it contains template syntax (users often put templates in labels)
        label = node.get("label", "")
        if '{' in label and '}' in label:
            label_vars = TEMPLATE_VAR_PATTERN.findall(label)
            for var in label_vars:
                if var not in valid_vars:
                    errors.append(
                        ValidationError(
                            code="INVALID_LABEL_VARIABLE",
                            message=(
                                f"End node '{node_label}': label references unknown variable '{{{var}}}'. "
                                f"Available variables: {sorted(valid_var_names or [])}"
                            ),
                            node_id=node_id,
                        )
                    )
        
        return errors

    def format_errors(self, errors: List[ValidationError]) -> str:
        """Format validation errors as a readable string."""
        if not errors:
            return ""

        lines = ["Workflow validation failed:"]
        for err in errors:
            location = ""
            if err.node_id:
                location = f" (node: {err.node_id})"
            elif err.edge_id:
                location = f" (edge: {err.edge_id})"
            lines.append(f"  • {err.message}{location}")

        return "\n".join(lines)
