"""Converter for Miro board data to LEMON workflow format.

This module transforms Miro shapes and connectors into LEMON's
workflow representation (nodes, edges, variables).

Conventions:
- flow_chart_terminator (rounded rect) -> start/end nodes
- flow_chart_process (rectangle) -> process nodes
- flow_chart_decision (diamond) -> decision nodes
- flow_chart_predefined_process_2 -> subprocess nodes
- flow_chart_input_output (parallelogram) -> variable declarations

Decision conditions should follow: {variable} {operator} {value}
Connector labels should be: "Yes"/"No" or "True"/"False"
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from .miro_client import MiroConnector, MiroShape

logger = logging.getLogger("backend.miro_converter")

# Miro shape types to LEMON node types
# LEMON valid types: 'start', 'decision', 'calculation', 'end', 'subprocess'
# Note: 'process' is NOT a valid LEMON type - use 'calculation' instead
# Shape types are normalized to lowercase for matching
SHAPE_TYPE_MAP = {
    # Flowchart shapes (Miro API v2 format)
    "flow_chart_terminator": "terminator",  # Will be classified as 'start' or 'end' based on connections
    "flow_chart_process": "calculation",    # Process steps become calculations in LEMON
    "flow_chart_decision": "decision",
    "flow_chart_predefined_process": "subprocess",
    "flow_chart_predefined_process_2": "subprocess",
    "flow_chart_input_output": "input_declaration",  # Variable declarations, not rendered as nodes
    "flow_chart_document": "end",  # Document shape → output/end node
    # Basic shapes (fallback)
    "rectangle": "calculation",
    "round_rectangle": "terminator",
    "rhombus": "decision",
    "diamond": "decision",
    "parallelogram": "input_declaration",
    # Alternative naming patterns Miro might use
    "flowchart_terminator": "terminator",
    "flowchart_process": "calculation",
    "flowchart_decision": "decision",
    "flowchart_predefined_process": "subprocess",
    "flowchart_input_output": "input_declaration",
    "flowchart_document": "end",
    # Without underscores
    "flowchartterminator": "terminator",
    "flowchartprocess": "calculation",
    "flowchartdecision": "decision",
}

# Operators for parsing conditions
OPERATORS = ["==", "!=", ">=", "<=", ">", "<", "="]
OPERATOR_MAP = {
    "==": "eq",
    "=": "eq",
    "!=": "neq",
    ">": "gt",
    ">=": "gte",
    "<": "lt",
    "<=": "lte",
}

# Keywords that indicate start/end nodes
START_KEYWORDS = ["start", "begin", "entrada"]
END_KEYWORDS = ["end", "stop", "finish", "return", "output", "resultado", "salida"]


@dataclass
class ConversionWarning:
    """A warning generated during conversion."""

    code: str  # e.g., "unlabeled_connector", "unparseable_condition"
    message: str
    node_id: Optional[str] = None
    miro_item_id: Optional[str] = None
    fix_suggestion: Optional[str] = None


@dataclass
class AIInference:
    """An AI-inferred value for ambiguous content."""

    id: str
    type: str  # e.g., "condition", "node_type", "variable_type"
    miro_item_id: str
    original_text: str
    inferred: Dict[str, Any]
    confidence: str  # "high", "medium", "low"


@dataclass
class ConversionResult:
    """Result of converting a Miro board to LEMON format."""

    success: bool
    nodes: List[Dict[str, Any]] = field(default_factory=list)
    edges: List[Dict[str, Any]] = field(default_factory=list)
    variables: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[ConversionWarning] = field(default_factory=list)
    inferences: List[AIInference] = field(default_factory=list)
    error: Optional[str] = None

    # Metadata
    board_name: str = ""
    node_count: int = 0
    edge_count: int = 0
    variable_count: int = 0


class MiroConverter:
    """Converts Miro board items to LEMON workflow format."""

    def __init__(self):
        # Mapping from Miro item ID to LEMON node ID
        self._miro_to_lemon_id: Dict[str, str] = {}
        # Track detected variables
        self._variables: Dict[str, Dict[str, Any]] = {}
        # Warnings and inferences
        self._warnings: List[ConversionWarning] = []
        self._inferences: List[AIInference] = []

    def convert(
        self,
        shapes: List[MiroShape],
        connectors: List[MiroConnector],
        board_name: str = "Imported Workflow",
    ) -> ConversionResult:
        """Convert Miro shapes and connectors to LEMON format.

        Args:
            shapes: List of MiroShape objects
            connectors: List of MiroConnector objects
            board_name: Name of the board (for metadata)

        Returns:
            ConversionResult with nodes, edges, variables, warnings
        """
        # Reset state
        self._miro_to_lemon_id = {}
        self._variables = {}
        self._warnings = []
        self._inferences = []

        try:
            # Step 1: Convert shapes to nodes
            nodes = self._convert_shapes(shapes)

            # Step 2: Convert connectors to edges
            edges = self._convert_connectors(connectors)

            # Step 3: Detect start/end nodes from position and connections
            nodes = self._classify_terminator_nodes(nodes, edges)

            # Step 4: Extract variables from conditions and input declarations
            variables = list(self._variables.values())

            return ConversionResult(
                success=True,
                nodes=nodes,
                edges=edges,
                variables=variables,
                warnings=self._warnings,
                inferences=self._inferences,
                board_name=board_name,
                node_count=len(nodes),
                edge_count=len(edges),
                variable_count=len(variables),
            )

        except Exception as e:
            logger.exception("Conversion failed: %s", e)
            return ConversionResult(
                success=False,
                error=str(e),
                warnings=self._warnings,
                inferences=self._inferences,
            )

    def _convert_shapes(self, shapes: List[MiroShape]) -> List[Dict[str, Any]]:
        """Convert Miro shapes to LEMON nodes."""
        nodes = []

        for shape in shapes:
            node = self._shape_to_node(shape)
            if node:
                nodes.append(node)
                self._miro_to_lemon_id[shape.id] = node["id"]

        return nodes

    def _shape_to_node(self, shape: MiroShape) -> Optional[Dict[str, Any]]:
        """Convert a single Miro shape to a LEMON node.

        Args:
            shape: MiroShape object

        Returns:
            Node dictionary or None if shape should be skipped
        """
        # Normalize shape type for lookup (lowercase, handle variations)
        shape_type_raw = shape.shape_type
        shape_type_normalized = shape_type_raw.lower().replace("-", "_").replace(" ", "_")

        # Log the shape type for debugging
        logger.info(
            "Converting shape: miro_id=%s, raw_type='%s', normalized='%s', content='%s'",
            shape.id,
            shape_type_raw,
            shape_type_normalized,
            (shape.content[:50] + "...") if len(shape.content) > 50 else shape.content,
        )

        # Try exact match first, then normalized
        lemon_type = SHAPE_TYPE_MAP.get(shape_type_raw) or SHAPE_TYPE_MAP.get(shape_type_normalized)

        # Check for decision-related keywords in shape type if not found
        if not lemon_type:
            if "decision" in shape_type_normalized or "diamond" in shape_type_normalized or "rhombus" in shape_type_normalized:
                lemon_type = "decision"
                logger.info("Detected decision shape from keywords in type: %s", shape_type_raw)
            elif "terminator" in shape_type_normalized or "rounded" in shape_type_normalized:
                lemon_type = "terminator"
            elif "process" in shape_type_normalized or "rectangle" in shape_type_normalized:
                lemon_type = "calculation"

        if not lemon_type:
            # Unknown shape type - treat as calculation with warning
            self._warnings.append(
                ConversionWarning(
                    code="unknown_shape_type",
                    message=f"Unknown shape type '{shape.shape_type}'. Treating as calculation node.",
                    miro_item_id=shape.id,
                    fix_suggestion="Use standard flowchart shapes from Miro's shape library.",
                )
            )
            lemon_type = "calculation"

        logger.info("Shape %s mapped to LEMON type: %s", shape.id, lemon_type)

        # Clean up content (remove HTML tags)
        content = self._clean_content(shape.content)

        # Handle input declarations (not actual nodes)
        if lemon_type == "input_declaration":
            self._parse_input_declaration(content, shape.id)
            return None  # Don't create a node for input declarations

        # Generate node ID
        node_id = f"node_{uuid4().hex[:8]}"

        # Base node structure
        node: Dict[str, Any] = {
            "id": node_id,
            "type": lemon_type if lemon_type != "terminator" else "start",  # Default, will refine later
            "label": content or f"Node {node_id[-4:]}",
            "x": shape.x,
            "y": shape.y,
            "color": self._get_node_color(lemon_type),
            "_miro_id": shape.id,  # Track for debugging
            "_miro_type": shape.shape_type,
        }

        # Handle decision nodes - parse condition
        if lemon_type == "decision":
            condition = self._parse_condition(content, shape.id)
            if condition:
                node["condition"] = condition

        # Handle subprocess nodes
        elif lemon_type == "subprocess":
            subworkflow_info = self._parse_subprocess(content, shape.id)
            if subworkflow_info:
                node["subworkflow_name"] = subworkflow_info.get("name")
                # subworkflow_id will need to be resolved later

        return node

    def _convert_connectors(self, connectors: List[MiroConnector]) -> List[Dict[str, Any]]:
        """Convert Miro connectors to LEMON edges."""
        edges = []

        for connector in connectors:
            edge = self._connector_to_edge(connector)
            if edge:
                edges.append(edge)

        return edges

    def _connector_to_edge(self, connector: MiroConnector) -> Optional[Dict[str, Any]]:
        """Convert a single Miro connector to a LEMON edge.

        Args:
            connector: MiroConnector object

        Returns:
            Edge dictionary or None if connector is invalid
        """
        # Get LEMON node IDs
        from_id = self._miro_to_lemon_id.get(connector.start_item_id)
        to_id = self._miro_to_lemon_id.get(connector.end_item_id)

        if not from_id or not to_id:
            # Connector references unknown shapes (probably filtered out)
            return None

        # Parse label
        label = connector.caption.strip() if connector.caption else ""

        # Normalize common labels
        label_lower = label.lower()
        if label_lower in ("yes", "true", "si", "sí"):
            label = "true"
        elif label_lower in ("no", "false"):
            label = "false"

        edge_id = f"{from_id}->{to_id}"

        return {
            "id": edge_id,
            "from": from_id,
            "to": to_id,
            "label": label,
            "_miro_id": connector.id,
        }

    def _classify_terminator_nodes(
        self,
        nodes: List[Dict[str, Any]],
        edges: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Classify terminator nodes as start or end based on content and connections.

        Start nodes: have no incoming edges, or content contains "start"
        End nodes: have no outgoing edges, or content contains "end"
        """
        # Build connection maps
        incoming: Dict[str, int] = {n["id"]: 0 for n in nodes}
        outgoing: Dict[str, int] = {n["id"]: 0 for n in nodes}

        for edge in edges:
            from_id = edge.get("from")
            to_id = edge.get("to")
            if from_id in outgoing:
                outgoing[from_id] += 1
            if to_id in incoming:
                incoming[to_id] += 1

        for node in nodes:
            # Only classify terminator nodes (type == "start" is our placeholder)
            if node.get("_miro_type") not in ("flow_chart_terminator", "round_rectangle"):
                continue

            label_lower = node.get("label", "").lower()
            node_id = node["id"]

            # Check content for keywords
            is_start_keyword = any(kw in label_lower for kw in START_KEYWORDS)
            is_end_keyword = any(kw in label_lower for kw in END_KEYWORDS)

            # Check connections
            has_incoming = incoming.get(node_id, 0) > 0
            has_outgoing = outgoing.get(node_id, 0) > 0

            # Classify
            if is_start_keyword or (not has_incoming and has_outgoing):
                node["type"] = "start"
            elif is_end_keyword or (has_incoming and not has_outgoing):
                node["type"] = "end"
                # Try to extract output info
                self._parse_end_node(node)
            elif not has_incoming and not has_outgoing:
                # Orphan node - warn
                self._warnings.append(
                    ConversionWarning(
                        code="orphan_node",
                        message=f"Node '{node.get('label')}' has no connections.",
                        node_id=node_id,
                        miro_item_id=node.get("_miro_id"),
                        fix_suggestion="Connect this node to other nodes in Miro.",
                    )
                )
                node["type"] = "calculation"  # Default to calculation
            else:
                # Has both incoming and outgoing - unusual for terminator
                self._warnings.append(
                    ConversionWarning(
                        code="ambiguous_terminator",
                        message=f"Terminator node '{node.get('label')}' has both incoming and outgoing connections.",
                        node_id=node_id,
                        fix_suggestion="Terminators should be either start (no incoming) or end (no outgoing).",
                    )
                )
                node["type"] = "calculation"  # Treat as calculation

        return nodes

    def _parse_condition(
        self, text: str, miro_id: str
    ) -> Optional[Dict[str, Any]]:
        """Parse a condition from decision node text.

        Expected formats:
            - "age >= 18"
            - "status == 'active'"
            - "score > 80"

        Args:
            text: The text content of the decision node
            miro_id: Miro item ID for warnings

        Returns:
            Condition dict or None
        """
        if not text:
            self._warnings.append(
                ConversionWarning(
                    code="empty_condition",
                    message="Decision node has no condition text.",
                    miro_item_id=miro_id,
                    fix_suggestion="Add condition text like 'age >= 18' to the decision node.",
                )
            )
            return None

        # Try to parse structured condition
        for op in sorted(OPERATORS, key=len, reverse=True):
            if op in text:
                parts = text.split(op, 1)
                if len(parts) == 2:
                    var_name = parts[0].strip()
                    value = parts[1].strip().strip("'\"")

                    # Register variable
                    var_id = self._register_variable(var_name, miro_id)

                    # Try to infer value type
                    comparator = OPERATOR_MAP.get(op, "eq")
                    typed_value: Any = value

                    # Try numeric
                    try:
                        if "." in value:
                            typed_value = float(value)
                        else:
                            typed_value = int(value)
                    except ValueError:
                        # Keep as string
                        if value.lower() in ("true", "false"):
                            typed_value = value.lower() == "true"
                            comparator = "is_true" if typed_value else "is_false"

                    return {
                        "input_id": var_id,
                        "comparator": comparator,
                        "value": typed_value,
                    }

        # Could not parse - add inference
        inference_id = f"inf_{uuid4().hex[:8]}"
        self._inferences.append(
            AIInference(
                id=inference_id,
                type="condition",
                miro_item_id=miro_id,
                original_text=text,
                inferred={
                    "suggestion": f"Could not parse condition from: '{text}'",
                    "example": "Use format: variable_name >= value",
                },
                confidence="low",
            )
        )

        self._warnings.append(
            ConversionWarning(
                code="unparseable_condition",
                message=f"Could not parse condition: '{text}'",
                miro_item_id=miro_id,
                fix_suggestion="Use format: variable operator value (e.g., 'age >= 18')",
            )
        )

        return None

    def _parse_input_declaration(self, text: str, miro_id: str) -> None:
        """Parse variable declaration from input/output shape.

        Expected format: "INPUT: name (type)" or "name: type"
        """
        if not text:
            return

        # Try "INPUT: name (type)" format
        match = re.match(
            r"INPUT:\s*(\w+)\s*\((\w+)\)",
            text,
            re.IGNORECASE,
        )
        if match:
            name = match.group(1)
            var_type = match.group(2).lower()
            self._register_variable(name, miro_id, var_type=var_type, source="input")
            return

        # Try "name: type" format
        match = re.match(r"(\w+)\s*:\s*(\w+)", text)
        if match:
            name = match.group(1)
            var_type = match.group(2).lower()
            self._register_variable(name, miro_id, var_type=var_type, source="input")
            return

        # Just a name
        words = text.strip().split()
        if words:
            name = words[0]
            self._register_variable(name, miro_id, source="input")

    def _parse_subprocess(
        self, text: str, miro_id: str
    ) -> Optional[Dict[str, str]]:
        """Parse subprocess reference from text.

        Expected formats:
            - "CALL: WorkflowName"
            - "WorkflowName"
        """
        if not text:
            return None

        # Try "CALL: name" format
        match = re.match(r"CALL:\s*(.+)", text, re.IGNORECASE)
        if match:
            return {"name": match.group(1).strip()}

        # Just use the text as workflow name
        return {"name": text.strip()}

    def _parse_end_node(self, node: Dict[str, Any]) -> None:
        """Parse end node to extract output info."""
        label = node.get("label", "")

        # Try "RETURN: variable" format
        match = re.match(r"RETURN:\s*(\w+)", label, re.IGNORECASE)
        if match:
            node["output_variable"] = match.group(1)
            return

        # Try "END: description" format
        match = re.match(r"END:\s*(.+)", label, re.IGNORECASE)
        if match:
            node["output_template"] = match.group(1)

    def _register_variable(
        self,
        name: str,
        miro_id: str,
        var_type: str = "string",
        source: str = "input",
    ) -> str:
        """Register a variable and return its ID.

        Args:
            name: Variable name
            miro_id: Miro item ID where variable was found
            var_type: Variable type (string, number, bool, etc.)
            source: Variable source (input, subprocess, calculated)

        Returns:
            Variable ID
        """
        # Normalize name
        name_clean = re.sub(r"\W+", "_", name.lower()).strip("_")

        # Normalize type
        type_map = {
            "int": "number",
            "integer": "number",
            "float": "number",
            "decimal": "number",
            "num": "number",
            "str": "string",
            "text": "string",
            "boolean": "bool",
        }
        var_type = type_map.get(var_type.lower(), var_type.lower())
        if var_type not in ("string", "number", "bool", "date", "enum"):
            var_type = "string"

        var_id = f"var_{name_clean}_{var_type}"

        if var_id not in self._variables:
            self._variables[var_id] = {
                "id": var_id,
                "name": name,
                "type": var_type,
                "source": source,
                "description": f"Imported from Miro (item {miro_id})",
            }

        return var_id

    def _clean_content(self, content: str) -> str:
        """Clean HTML content from Miro shapes."""
        if not content:
            return ""

        # Log raw content for debugging
        logger.debug("Raw Miro content: %r", content[:200] if len(content) > 200 else content)

        # Decode HTML entities
        text = html.unescape(content)

        # Remove HTML tags
        text = re.sub(r"<[^>]+>", "", text)

        # Normalize whitespace
        text = " ".join(text.split())

        cleaned = text.strip()
        logger.debug("Cleaned content: %r", cleaned)

        return cleaned

    def _get_node_color(self, node_type: str) -> str:
        """Get default color for a node type (matching LEMON's color scheme)."""
        colors = {
            "start": "teal",
            "end": "green",
            "decision": "amber",
            "subprocess": "sky",
            "calculation": "purple",
            "terminator": "teal",  # Will be classified as start/end later
        }
        return colors.get(node_type, "teal")


def validate_miro_conventions(result: ConversionResult) -> List[ConversionWarning]:
    """Check if conversion result follows LEMON conventions.

    This adds additional warnings for common issues.
    """
    warnings = []

    # Check for unlabeled decision edges
    decision_node_ids = {
        n["id"] for n in result.nodes if n.get("type") == "decision"
    }

    for edge in result.edges:
        if edge.get("from") in decision_node_ids:
            if not edge.get("label"):
                warnings.append(
                    ConversionWarning(
                        code="unlabeled_decision_edge",
                        message=f"Decision edge {edge['id']} has no label.",
                        node_id=edge.get("from"),
                        fix_suggestion="Add 'Yes'/'No' labels to decision branches in Miro.",
                    )
                )

    # Check for missing start node
    start_nodes = [n for n in result.nodes if n.get("type") == "start"]
    if not start_nodes:
        warnings.append(
            ConversionWarning(
                code="missing_start_node",
                message="No start node found in the workflow.",
                fix_suggestion="Add a terminator shape with 'START' text at the beginning.",
            )
        )

    # Check for missing end node
    end_nodes = [n for n in result.nodes if n.get("type") == "end"]
    if not end_nodes:
        warnings.append(
            ConversionWarning(
                code="missing_end_node",
                message="No end node found in the workflow.",
                fix_suggestion="Add a terminator shape with 'END' text at the end.",
            )
        )

    return warnings
