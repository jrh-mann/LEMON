"""Workflow validation system for syntactic correctness."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple


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

    def validate(self, workflow: Dict[str, Any]) -> Tuple[bool, List[ValidationError]]:
        """
        Validate a workflow and return (is_valid, errors).

        Rules:
        1. All nodes must have: id, type, label, x, y
        2. Node types must be: start, process, decision, subprocess, or end
        3. All edge 'from' and 'to' must reference existing node IDs
        4. No duplicate node IDs
        5. No duplicate edge IDs
        6. Decision nodes must have at least 2 outgoing edges (true/false paths)
        7. Start nodes should have at least 1 outgoing edge
        8. End nodes should have 0 outgoing edges
        """
        errors: List[ValidationError] = []
        nodes = workflow.get("nodes", [])
        edges = workflow.get("edges", [])

        # Collect node IDs for validation
        node_ids: Set[str] = set()

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

        # Rules 6, 7, 8: Validate node-specific connection requirements
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
