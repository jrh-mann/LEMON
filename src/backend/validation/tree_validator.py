"""Structural validator for subagent nested-tree analysis output.

Validates the tree structure returned by the subagent (inputs, outputs,
tree with decision/action/output nodes, doubts).  Catches structural
problems that JSON syntax validation misses — e.g. decision nodes with
the wrong number of children, output nodes that have children, missing
conditions, duplicate IDs, etc.
"""

from __future__ import annotations

from typing import Any, Dict, List, Set, Tuple

from .workflow_validator import ValidationError


# Valid node types in the subagent's nested tree representation.
# These differ from the orchestrator's flat workflow node types.
VALID_TREE_NODE_TYPES = {"start", "decision", "action", "output"}


class TreeValidator:
    """Validates the nested tree structure produced by the subagent."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate(
        self, analysis: Dict[str, Any]
    ) -> Tuple[bool, List[ValidationError]]:
        """Walk *analysis* and return ``(is_valid, errors)``.

        *analysis* is the full dict produced by the subagent after
        ``normalize_analysis()`` — it must contain at least a ``tree``
        key with a nested node structure.
        """
        errors: List[ValidationError] = []

        # --- top-level checks ---
        tree = analysis.get("tree")
        if not isinstance(tree, dict) or not tree:
            errors.append(
                ValidationError(
                    code="TREE_MISSING",
                    message="'tree' key must exist and be a non-empty dict.",
                )
            )
            return (False, errors)

        start = tree.get("start")
        if not isinstance(start, dict) or not start:
            errors.append(
                ValidationError(
                    code="TREE_MISSING_START",
                    message="'tree.start' must exist and be a non-empty dict.",
                )
            )
            return (False, errors)

        # --- recursive walk ---
        seen_ids: Set[str] = set()
        # Collect variable names for soft input-reference checks.
        variables = analysis.get("variables", [])
        var_names: Set[str] = set()
        if isinstance(variables, list):
            for v in variables:
                if isinstance(v, dict):
                    name = v.get("name")
                    vid = v.get("id")
                    if name:
                        var_names.add(name)
                    if vid:
                        var_names.add(vid)

        self._validate_node(start, errors, seen_ids, var_names, is_root=True)

        return (len(errors) == 0, errors)

    # ------------------------------------------------------------------
    # Formatting helper
    # ------------------------------------------------------------------

    @staticmethod
    def format_errors(errors: List[ValidationError]) -> str:
        """Return a human-readable bullet list of *errors*."""
        if not errors:
            return "No validation errors."
        lines = [f"- [{e.code}] {e.message}" for e in errors]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal recursive walk
    # ------------------------------------------------------------------

    def _validate_node(
        self,
        node: Any,
        errors: List[ValidationError],
        seen_ids: Set[str],
        var_names: Set[str],
        is_root: bool = False,
    ) -> None:
        """Validate a single node and recurse into its children."""
        if not isinstance(node, dict):
            return

        node_id = node.get("id")
        node_type = node.get("type")

        # --- MISSING_NODE_ID ---
        if not isinstance(node_id, str) or not node_id.strip():
            errors.append(
                ValidationError(
                    code="MISSING_NODE_ID",
                    message="Node is missing a non-empty string 'id'.",
                    node_id=str(node_id) if node_id is not None else None,
                )
            )
        else:
            # --- DUPLICATE_NODE_ID ---
            if node_id in seen_ids:
                errors.append(
                    ValidationError(
                        code="DUPLICATE_NODE_ID",
                        message=f"Duplicate node id '{node_id}'.",
                        node_id=node_id,
                    )
                )
            seen_ids.add(node_id)

        # --- MISSING_NODE_LABEL ---
        label = node.get("label")
        if not isinstance(label, str) or not label.strip():
            errors.append(
                ValidationError(
                    code="MISSING_NODE_LABEL",
                    message=f"Node '{node_id}' is missing a non-empty string 'label'.",
                    node_id=node_id if isinstance(node_id, str) else None,
                )
            )

        # --- TREE_START_TYPE (root only) ---
        if is_root and node_type != "start":
            errors.append(
                ValidationError(
                    code="TREE_START_TYPE",
                    message=f"Root node type must be 'start', got '{node_type}'.",
                    node_id=node_id if isinstance(node_id, str) else None,
                )
            )

        # --- INVALID_TREE_NODE_TYPE ---
        if node_type not in VALID_TREE_NODE_TYPES:
            errors.append(
                ValidationError(
                    code="INVALID_TREE_NODE_TYPE",
                    message=f"Invalid tree node type '{node_type}'. "
                    f"Must be one of {sorted(VALID_TREE_NODE_TYPES)}.",
                    node_id=node_id if isinstance(node_id, str) else None,
                )
            )

        children = node.get("children", [])
        if not isinstance(children, list):
            children = []

        # --- type-specific rules ---
        if node_type == "decision":
            self._validate_decision(node, children, errors, var_names)
        elif node_type == "output":
            self._validate_output(node, children, errors)
        elif node_type in ("action", "start"):
            self._validate_single_child(node, children, errors)

        # Recurse into children
        for child in children:
            self._validate_node(child, errors, seen_ids, var_names)

    # ------------------------------------------------------------------
    # Type-specific validators
    # ------------------------------------------------------------------

    def _validate_decision(
        self,
        node: Dict[str, Any],
        children: list,
        errors: List[ValidationError],
        var_names: Set[str],
    ) -> None:
        """Decision nodes must have exactly 2 children with true/false edge labels and a condition."""
        node_id = node.get("id")

        # --- DECISION_CHILDREN_COUNT ---
        if len(children) != 2:
            errors.append(
                ValidationError(
                    code="DECISION_CHILDREN_COUNT",
                    message=f"Decision node '{node_id}' must have exactly 2 children, "
                    f"got {len(children)}.",
                    node_id=node_id,
                )
            )

        # --- DECISION_EDGE_LABELS ---
        if len(children) == 2:
            edge_labels = set()
            for child in children:
                if isinstance(child, dict):
                    lbl = child.get("edge_label", "")
                    if isinstance(lbl, str):
                        edge_labels.add(lbl.strip().lower())
            if edge_labels != {"true", "false"}:
                errors.append(
                    ValidationError(
                        code="DECISION_EDGE_LABELS",
                        message=f"Decision node '{node_id}' children must have "
                        f"edge_label 'true' and 'false', got {sorted(edge_labels)}.",
                        node_id=node_id,
                    )
                )

        # --- DECISION_MISSING_CONDITION ---
        condition = node.get("condition")
        if not isinstance(condition, dict):
            errors.append(
                ValidationError(
                    code="DECISION_MISSING_CONDITION",
                    message=f"Decision node '{node_id}' must have a 'condition' dict "
                    f"with 'input_id' and 'comparator'.",
                    node_id=node_id,
                )
            )
        else:
            input_id = condition.get("input_id")
            comparator = condition.get("comparator")
            if not input_id or not comparator:
                errors.append(
                    ValidationError(
                        code="DECISION_MISSING_CONDITION",
                        message=f"Decision node '{node_id}' condition must have "
                        f"'input_id' and 'comparator'.",
                        node_id=node_id,
                    )
                )

            # --- INVALID_INPUT_REFERENCE (soft — only when variables are known) ---
            if var_names and isinstance(input_id, str) and input_id:
                if input_id not in var_names:
                    errors.append(
                        ValidationError(
                            code="INVALID_INPUT_REFERENCE",
                            message=f"Decision node '{node_id}' references input "
                            f"'{input_id}' which is not in the variables list.",
                            node_id=node_id,
                        )
                    )

    def _validate_output(
        self,
        node: Dict[str, Any],
        children: list,
        errors: List[ValidationError],
    ) -> None:
        """Output nodes must not have children."""
        node_id = node.get("id")
        if children:
            errors.append(
                ValidationError(
                    code="OUTPUT_HAS_CHILDREN",
                    message=f"Output node '{node_id}' must not have children, "
                    f"got {len(children)}.",
                    node_id=node_id,
                )
            )

    def _validate_single_child(
        self,
        node: Dict[str, Any],
        children: list,
        errors: List[ValidationError],
    ) -> None:
        """Action and start nodes must have at most 1 child."""
        node_id = node.get("id")
        if len(children) > 1:
            errors.append(
                ValidationError(
                    code="ACTION_MULTIPLE_CHILDREN",
                    message=f"Node '{node_id}' (type '{node.get('type')}') must have "
                    f"at most 1 child, got {len(children)}.",
                    node_id=node_id,
                )
            )
