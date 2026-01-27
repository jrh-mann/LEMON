"""Workflow tree interpreter: executes workflows by walking the tree

Interprets workflow trees by:
1. Starting at the start node
2. Evaluating conditions at decision nodes
3. Following appropriate branches based on results
4. Executing subworkflows when subprocess nodes are encountered
5. Tracking execution path
6. Returning output when reached

Subflow Execution:
- Subprocess nodes reference other workflows by ID
- Input mapping translates parent inputs to subworkflow inputs
- Subworkflow output is injected as a new input variable in parent context
- Cycle detection prevents infinite recursion (A->B->A)
"""

import json
import logging
import re
from typing import Dict, Any, List, Optional, Callable, TYPE_CHECKING
from dataclasses import dataclass, field
from .parser import parse_condition
from .evaluator import evaluate

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ..storage.workflows import WorkflowStore


@dataclass
class ExecutionResult:
    """Result of workflow execution"""
    success: bool
    output: Optional[Any] = None
    path: Optional[List[str]] = None
    context: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    # Track subflow executions for debugging
    subflow_results: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self):
        if self.path is None:
            self.path = []
        if self.context is None:
            self.context = {}


class InterpreterError(Exception):
    """Raised when interpreter encounters an error"""
    pass


class SubflowCycleError(InterpreterError):
    """Raised when a circular subflow reference is detected"""
    pass


class TreeInterpreter:
    """Interprets and executes workflow trees with subflow support.
    
    Supports executing subprocess nodes that reference other workflows.
    When a subprocess node is encountered:
    1. The referenced workflow is loaded from workflow_store
    2. Parent inputs are mapped to subworkflow inputs via input_mapping
    3. The subworkflow is executed recursively
    4. The subworkflow's output is injected as a new input variable
    5. Execution continues to the next node
    
    Cycle detection prevents infinite recursion by tracking the call stack
    of workflow IDs being executed.
    """

    def __init__(
        self,
        tree: Dict[str, Any],
        inputs: List[Dict[str, Any]],
        outputs: List[Dict[str, Any]],
        workflow_id: Optional[str] = None,
        call_stack: Optional[List[str]] = None,
        workflow_store: Optional["WorkflowStore"] = None,
        user_id: Optional[str] = None,
    ):
        """Initialize interpreter
        
        Args:
            tree: Workflow tree (must have 'start' key)
            inputs: List of input definitions with id, name, type, range, enum_values
            outputs: List of output definitions with name
            workflow_id: ID of this workflow (for cycle detection in subflows)
            call_stack: Stack of workflow IDs currently being executed (for cycle detection)
            workflow_store: Store for loading subworkflows (required for subprocess nodes)
            user_id: User ID for loading subworkflows (required for subprocess nodes)
        """
        self.tree = tree
        self.inputs_schema = {inp['id']: inp for inp in inputs}
        self.outputs_schema = {out['name']: out for out in outputs}

        # Create mapping from input names to IDs for condition evaluation
        # e.g., "Age" -> "input_age_int", "BMI" -> "input_bmi_float"
        self.name_to_id = {inp['name']: inp['id'] for inp in inputs}
        
        # Subflow support
        self.workflow_id = workflow_id
        self.call_stack = call_stack or []
        self.workflow_store = workflow_store
        self.user_id = user_id
        
        # Track subflow execution results
        self.subflow_results: List[Dict[str, Any]] = []

    def execute(
        self,
        input_values: Dict[str, Any],
        on_step: Optional[Callable[[Dict[str, Any]], None]] = None
    ) -> ExecutionResult:
        """Execute workflow with given inputs
        
        Args:
            input_values: Dictionary mapping input IDs to values
            on_step: Optional callback called before each node is processed.
                     Receives dict with: node_id, node_type, node_label, step_index, context.
                     Used for visual execution feedback in the UI.
                     Callback exceptions are logged but do not stop execution.
            
        Returns:
            ExecutionResult with output, path, and context
            
        Example:
            >>> result = interpreter.execute({"input_age_int": 25})
            >>> result.success
            True
            >>> result.output
            'Adult'
            
            # With step callback for visualization:
            >>> def on_step(info): print(f"Executing: {info['node_label']}")
            >>> result = interpreter.execute({"input_age_int": 25}, on_step=on_step)
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
        step_index = 0  # Track step number for on_step callback

        try:
            current = start_node
            while current:
                node_id = current.get('id', 'unknown')
                node_type = current.get('type')
                node_label = current.get('label', node_id)
                
                # Call on_step callback before processing this node (for visual execution)
                if on_step is not None:
                    try:
                        on_step({
                            "node_id": node_id,
                            "node_type": node_type,
                            "node_label": node_label,
                            "step_index": step_index,
                            "context": context.copy(),  # Copy to prevent mutation
                        })
                    except Exception as e:
                        # Log callback errors but don't stop execution
                        logger.warning(f"on_step callback error at node '{node_id}': {e}")
                
                step_index += 1
                path.append(node_id)

                if node_type == 'output':
                    # Reached output node - success!
                    output_val = self._resolve_output_value(current, context)
                    return ExecutionResult(
                        success=True,
                        output=output_val,
                        path=path,
                        context=context,
                        subflow_results=self.subflow_results
                    )

                elif node_type == 'decision':
                    # Evaluate condition and branch
                    current = self._handle_decision_node(current, context)

                elif node_type == 'subprocess':
                    # Execute subworkflow and inject output as new input
                    current = self._handle_subprocess_node(current, context)

                elif node_type in ('start', 'action', 'process'):
                    # Pass through to first child
                    children = current.get('children', [])
                    if not children:
                        return ExecutionResult(
                            success=False,
                            error=f"Node '{node_id}' has no children",
                            path=path,
                            context=context,
                            subflow_results=self.subflow_results
                        )
                    current = children[0]

                else:
                    return ExecutionResult(
                        success=False,
                        error=f"Unknown node type '{node_type}' at node '{node_id}'",
                        path=path,
                        context=context,
                        subflow_results=self.subflow_results
                    )

            # Fell through without reaching output
            return ExecutionResult(
                success=False,
                error="No output node reached",
                path=path,
                context=context,
                subflow_results=self.subflow_results
            )

        except SubflowCycleError as e:
            # Propagate cycle errors with clear message
            return ExecutionResult(
                success=False,
                error=str(e),
                path=path,
                context=context,
                subflow_results=self.subflow_results
            )
        except Exception as e:
            return ExecutionResult(
                success=False,
                error=f"Execution error: {str(e)}",
                path=path,
                context=context,
                subflow_results=self.subflow_results
            )

    def _handle_subprocess_node(
        self,
        node: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Execute a subworkflow and inject its output as a new input variable.
        
        Steps:
        1. Detect cycles (prevent infinite recursion)
        2. Load subworkflow from WorkflowStore
        3. Map parent inputs to subworkflow inputs
        4. Create TreeInterpreter for subworkflow
        5. Execute subworkflow
        6. Inject output as new input in parent context
        7. Continue to next node
        
        Args:
            node: Subprocess node with subworkflow_id, input_mapping, output_variable
            context: Parent workflow execution context
            
        Returns:
            Next node to execute
            
        Raises:
            SubflowCycleError: If circular subflow reference detected
            InterpreterError: If subworkflow fails or configuration invalid
        """
        node_id = node.get('id', 'unknown')
        node_label = node.get('label', node_id)
        subworkflow_id = node.get('subworkflow_id')
        input_mapping = node.get('input_mapping', {})
        output_variable = node.get('output_variable')
        
        # Validate required fields
        if not subworkflow_id:
            raise InterpreterError(
                f"Subprocess node '{node_label}' missing subworkflow_id"
            )
        if not output_variable:
            raise InterpreterError(
                f"Subprocess node '{node_label}' missing output_variable"
            )
        if not isinstance(input_mapping, dict):
            raise InterpreterError(
                f"Subprocess node '{node_label}': input_mapping must be a dictionary"
            )
        
        # Cycle detection: Check if subworkflow is already in call stack
        if subworkflow_id in self.call_stack:
            cycle_path = self.call_stack + [subworkflow_id]
            raise SubflowCycleError(
                f"Circular subflow detected: {' -> '.join(cycle_path)}. "
                f"A workflow cannot call itself directly or indirectly."
            )
        
        # Verify we have workflow_store to load subworkflow
        if not self.workflow_store:
            raise InterpreterError(
                f"Subprocess node '{node_label}': workflow_store not available. "
                f"Cannot execute subflows without access to workflow storage."
            )
        if not self.user_id:
            raise InterpreterError(
                f"Subprocess node '{node_label}': user_id not available. "
                f"Cannot load subworkflows without user context."
            )
        
        # Load subworkflow
        subworkflow = self.workflow_store.get_workflow(subworkflow_id, self.user_id)
        if not subworkflow:
            raise InterpreterError(
                f"Subprocess node '{node_label}': subworkflow '{subworkflow_id}' not found"
            )
        
        # Map parent inputs to subworkflow inputs
        sub_input_values = self._map_inputs_to_subworkflow(
            input_mapping,
            context,
            subworkflow.inputs,
            node_label
        )
        
        # Build new call stack with current workflow
        new_call_stack = self.call_stack.copy()
        if self.workflow_id:
            new_call_stack.append(self.workflow_id)
        
        # Create interpreter for subworkflow
        sub_interpreter = TreeInterpreter(
            tree=subworkflow.tree,
            inputs=subworkflow.inputs,
            outputs=subworkflow.outputs,
            workflow_id=subworkflow_id,
            call_stack=new_call_stack,
            workflow_store=self.workflow_store,
            user_id=self.user_id,
        )
        
        # Execute subworkflow
        sub_result = sub_interpreter.execute(sub_input_values)
        
        # Record subflow execution for debugging
        self.subflow_results.append({
            "node_id": node_id,
            "subworkflow_id": subworkflow_id,
            "subworkflow_name": subworkflow.name,
            "input_mapping": input_mapping,
            "sub_inputs": sub_input_values,
            "output_variable": output_variable,
            "result": {
                "success": sub_result.success,
                "output": sub_result.output,
                "error": sub_result.error,
            }
        })
        
        # Propagate subworkflow errors to parent
        if not sub_result.success:
            raise InterpreterError(
                f"Subprocess node '{node_label}' failed: "
                f"Subworkflow '{subworkflow.name}' returned error: {sub_result.error}"
            )
        
        # Inject subworkflow output as new input variable in parent context
        self._inject_subflow_output(output_variable, sub_result.output, context)
        
        # Continue to next node
        children = node.get('children', [])
        if not children:
            raise InterpreterError(
                f"Subprocess node '{node_label}' has no children. "
                f"Flow must continue after subprocess or end explicitly."
            )
        
        return children[0]

    def _map_inputs_to_subworkflow(
        self,
        input_mapping: Dict[str, str],
        context: Dict[str, Any],
        sub_inputs: List[Dict[str, Any]],
        node_label: str,
    ) -> Dict[str, Any]:
        """Map parent workflow inputs to subworkflow input values.
        
        Args:
            input_mapping: Dict mapping parent input names to subworkflow input names
            context: Parent workflow execution context (input_id -> value)
            sub_inputs: Subworkflow input definitions
            node_label: Label of subprocess node for error messages
            
        Returns:
            Dict mapping subworkflow input IDs to values
            
        Raises:
            InterpreterError: If mapping fails (missing inputs, type mismatch)
        """
        # Build subworkflow name->id mapping
        sub_name_to_id = {inp['name']: inp['id'] for inp in sub_inputs}
        
        # Map values
        sub_input_values = {}
        
        for parent_name, sub_name in input_mapping.items():
            # Find parent input ID
            parent_id = self.name_to_id.get(parent_name)
            if not parent_id:
                raise InterpreterError(
                    f"Subprocess '{node_label}': input_mapping references "
                    f"non-existent parent input '{parent_name}'"
                )
            
            # Find subworkflow input ID
            sub_id = sub_name_to_id.get(sub_name)
            if not sub_id:
                raise InterpreterError(
                    f"Subprocess '{node_label}': input_mapping maps to "
                    f"non-existent subworkflow input '{sub_name}'"
                )
            
            # Get value from parent context
            if parent_id not in context:
                raise InterpreterError(
                    f"Subprocess '{node_label}': parent input '{parent_name}' "
                    f"has no value in context"
                )
            
            sub_input_values[sub_id] = context[parent_id]
        
        return sub_input_values

    def _inject_subflow_output(
        self,
        output_variable: str,
        output_value: Any,
        context: Dict[str, Any]
    ) -> None:
        """Inject subflow output as a new input variable in parent context.
        
        Dynamically registers the output as a new input that can be used
        in subsequent decision nodes.
        
        Args:
            output_variable: Name of the variable (e.g., "CreditScore")
            output_value: The value returned by subworkflow
            context: Parent workflow context (modified in place)
        """
        # Infer type from output value
        output_type = self._infer_type(output_value)
        
        # Generate deterministic input ID
        input_id = self._generate_input_id(output_variable, output_type)
        
        # Add to name->id mapping for future condition evaluation
        self.name_to_id[output_variable] = input_id
        
        # Add to context
        context[input_id] = output_value
        
        # Track in inputs_schema for potential validation
        self.inputs_schema[input_id] = {
            "id": input_id,
            "name": output_variable,
            "type": output_type,
            "source": "subflow",  # Mark as dynamically injected
        }

    def _infer_type(self, value: Any) -> str:
        """Infer input type from value.
        
        Args:
            value: The value to analyze
            
        Returns:
            Type string: 'int', 'float', 'bool', 'string', or 'json'
        """
        if isinstance(value, bool):
            return "bool"
        elif isinstance(value, int):
            return "int"
        elif isinstance(value, float):
            return "float"
        elif isinstance(value, str):
            return "string"
        elif isinstance(value, (dict, list)):
            return "json"
        else:
            return "string"  # Fallback

    def _generate_input_id(self, name: str, input_type: str) -> str:
        """Generate deterministic input ID from name and type.
        
        Follows the same pattern as deterministic_input_id in utils/analysis.py:
        input_{slug}_{type}
        
        Args:
            name: Input name (e.g., "Credit Score")
            input_type: Input type (e.g., "int")
            
        Returns:
            Input ID (e.g., "input_credit_score_int")
        """
        # Slugify: lowercase, replace non-alphanumeric with underscore
        slug = re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')
        return f"input_{slug}_{input_type}"

    def _resolve_output_value(self, node: Dict[str, Any], context: Dict[str, Any]) -> Any:
        """Resolve output value from node configuration.
        
        Supports:
        - output_template: Python f-string style template (e.g., "Result: {Age}")
        - output_value: Static value
        - output_type: Type casting (int, float, bool, json)
        - label: Fallback
        """
        output_type = node.get('output_type', 'string')
        
        # 1. Template (Dynamic)
        if node.get('output_template'):
            template = node['output_template']
            try:
                # Build user-friendly context (Name -> Value)
                friendly_context = {}
                for name, input_id in self.name_to_id.items():
                    if input_id in context:
                        friendly_context[name] = context[input_id]
                
                # Combine with raw ID context
                full_context = {**context, **friendly_context}
                
                # Safe format
                return template.format(**full_context)
            except Exception as e:
                return f"Error formatting output: {str(e)}"

        # 2. Static Value
        if 'output_value' in node:
            val = node['output_value']
            try:
                if output_type == 'int':
                    return int(val)
                elif output_type == 'float':
                    return float(val)
                elif output_type == 'bool':
                    return str(val).lower() in ('true', '1', 'yes', 'on')
                elif output_type == 'json':
                    if isinstance(val, str):
                        return json.loads(val)
                    return val
                return val
            except Exception as e:
                return f"Error casting output: {str(e)}"

        # 3. Fallback to label
        return node.get('label', '')

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
