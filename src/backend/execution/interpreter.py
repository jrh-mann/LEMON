"""Workflow tree interpreter: executes workflows by walking the tree

Interprets workflow trees by:
1. Starting at the start node
2. Evaluating conditions at decision nodes
3. Following appropriate branches based on results
4. Tracking execution path
5. Returning output when reached
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from .parser import parse_condition
from .evaluator import evaluate


@dataclass
class ExecutionResult:
    """Result of workflow execution"""
    success: bool
    output: Optional[str] = None
    path: List[str] = None
    context: Dict[str, Any] = None
    error: Optional[str] = None

    def __post_init__(self):
        if self.path is None:
            self.path = []
        if self.context is None:
            self.context = {}


class InterpreterError(Exception):
    """Raised when interpreter encounters an error"""
    pass


class TreeInterpreter:
    """Interprets and executes workflow trees"""

    def __init__(self, tree: Dict[str, Any], inputs: List[Dict[str, Any]], outputs: List[Dict[str, Any]]):
        """Initialize interpreter

        Args:
            tree: Workflow tree (must have 'start' key)
            inputs: List of input definitions with id, name, type, range, enum_values
            outputs: List of output definitions with name
        """
        self.tree = tree
        self.inputs_schema = {inp['id']: inp for inp in inputs}
        self.outputs_schema = {out['name']: out for out in outputs}

        # Create mapping from input names to IDs for condition evaluation
        # e.g., "Age" -> "input_age_int", "BMI" -> "input_bmi_float"
        self.name_to_id = {inp['name']: inp['id'] for inp in inputs}

    def execute(self, input_values: Dict[str, Any]) -> ExecutionResult:
        """Execute workflow with given inputs

        Args:
            input_values: Dictionary mapping input IDs to values

        Returns:
            ExecutionResult with output, path, and context

        Example:
            >>> result = interpreter.execute({"input_age_int": 25})
            >>> result.success
            True
            >>> result.output
            'Adult'
        """
        # Validate inputs
        try:
            self._validate_inputs(input_values)
        except Exception as e:
            return ExecutionResult(
                success=False,
                error=str(e),
                context=input_values
            )

        # Get start node
        if 'start' not in self.tree:
            return ExecutionResult(
                success=False,
                error="Tree missing 'start' node"
            )

        start_node = self.tree['start']

        # Execute tree walk
        path = []
        context = input_values.copy()

        try:
            current = start_node
            while current:
                node_id = current.get('id', 'unknown')
                path.append(node_id)

                node_type = current.get('type')

                if node_type == 'output':
                    # Reached output node - success!
                    output_label = current.get('label', '')
                    return ExecutionResult(
                        success=True,
                        output=output_label,
                        path=path,
                        context=context
                    )

                elif node_type == 'decision':
                    # Evaluate condition and branch
                    current = self._handle_decision_node(current, context)

                elif node_type in ('start', 'action'):
                    # Pass through to first child
                    children = current.get('children', [])
                    if not children:
                        return ExecutionResult(
                            success=False,
                            error=f"Node '{node_id}' has no children",
                            path=path,
                            context=context
                        )
                    current = children[0]

                else:
                    return ExecutionResult(
                        success=False,
                        error=f"Unknown node type '{node_type}' at node '{node_id}'",
                        path=path,
                        context=context
                    )

            # Fell through without reaching output
            return ExecutionResult(
                success=False,
                error="No output node reached",
                path=path,
                context=context
            )

        except Exception as e:
            return ExecutionResult(
                success=False,
                error=f"Execution error: {str(e)}",
                path=path,
                context=context
            )

    def _validate_inputs(self, input_values: Dict[str, Any]) -> None:
        """Validate input values against schema

        Args:
            input_values: Input values to validate

        Raises:
            InterpreterError: If validation fails
        """
        # Check all required inputs are present
        for input_id, schema in self.inputs_schema.items():
            if input_id not in input_values:
                raise InterpreterError(f"Missing required input: {input_id}")

            value = input_values[input_id]
            input_type = schema['type']

            # Type validation
            if input_type == 'int':
                if not isinstance(value, int) or isinstance(value, bool):
                    raise InterpreterError(f"{input_id} must be int, got {type(value).__name__}")

            elif input_type == 'float':
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    raise InterpreterError(f"{input_id} must be float, got {type(value).__name__}")

            elif input_type == 'bool':
                if not isinstance(value, bool):
                    raise InterpreterError(f"{input_id} must be bool, got {type(value).__name__}")

            elif input_type in ('string', 'enum'):
                if not isinstance(value, str):
                    raise InterpreterError(f"{input_id} must be string, got {type(value).__name__}")

            # Range validation for numeric types
            if input_type in ('int', 'float') and 'range' in schema:
                range_spec = schema['range']
                if 'min' in range_spec and value < range_spec['min']:
                    raise InterpreterError(
                        f"Value error: {input_id}={value} below minimum {range_spec['min']}"
                    )
                if 'max' in range_spec and value > range_spec['max']:
                    raise InterpreterError(
                        f"Value error: {input_id}={value} exceeds maximum {range_spec['max']}"
                    )

            # Enum validation
            if input_type == 'enum' and 'enum_values' in schema:
                allowed = schema['enum_values']
                if value not in allowed:
                    raise InterpreterError(
                        f"Value error: {input_id} must be one of {allowed}, got '{value}'"
                    )

    def _handle_decision_node(self, node: Dict[str, Any], context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Handle decision node: evaluate condition and select branch

        Args:
            node: Decision node
            context: Current variable context (with input IDs as keys)

        Returns:
            Next node to visit, or None if no valid branch

        Raises:
            InterpreterError: If condition evaluation fails
        """
        condition_str = node.get('label', '')
        node_id = node.get('id', 'unknown')

        # Create evaluation context with simple names mapped to values
        # e.g., {"Age": 25, "BMI": 22.0} instead of {"input_age_int": 25, "input_bmi_float": 22.0}
        eval_context = {}
        for name, input_id in self.name_to_id.items():
            if input_id in context:
                eval_context[name] = context[input_id]

        # Parse and evaluate condition
        try:
            expr = parse_condition(condition_str)
            result = evaluate(expr, eval_context)
        except Exception as e:
            raise InterpreterError(f"Failed to evaluate condition '{condition_str}' at node '{node_id}': {e}")

        # Convert result to boolean
        condition_result = bool(result)

        # Find matching child based on edge label
        children = node.get('children', [])
        if not children:
            raise InterpreterError(f"Decision node '{node_id}' has no children")

        # Try to match edge label
        next_node = self._find_branch(children, condition_result)

        if next_node is None:
            raise InterpreterError(
                f"No branch found for condition '{condition_str}' = {condition_result} at node '{node_id}'"
            )

        return next_node

    def _find_branch(self, children: List[Dict[str, Any]], condition_result: bool) -> Optional[Dict[str, Any]]:
        """Find child node matching condition result

        Args:
            children: List of child nodes
            condition_result: Boolean result of condition

        Returns:
            Matching child node, or None if no match

        Edge label matching rules:
        - "Yes", "True", "Y", "T", "1" → True
        - "No", "False", "N", "F", "0" → False
        - Empty or missing label → first child (fallback)
        """
        if len(children) == 1:
            # Only one child - take it
            return children[0]

        # Define label mappings
        true_labels = {'yes', 'true', 'y', 't', '1'}
        false_labels = {'no', 'false', 'n', 'f', '0'}

        # Try to find matching edge label
        for child in children:
            edge_label = child.get('edge_label', '').lower().strip()

            if condition_result and edge_label in true_labels:
                return child
            elif not condition_result and edge_label in false_labels:
                return child

        # Fallback: return first child
        return children[0] if children else None
