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
- Input mapping translates parent variables to subworkflow inputs
- Subworkflow output is injected as a new derived variable in parent context
- Cycle detection prevents infinite recursion (A->B->A)

Variable System:
- The unified variable system uses 'variables' instead of 'inputs'
- Each variable has a 'source' field: 'input' (user-provided), 'subprocess' (derived), etc.
- For backwards compatibility, the interpreter accepts both 'variables' and legacy 'inputs'
"""

import json
import logging
import re
from typing import Dict, Any, List, Optional, Callable, TYPE_CHECKING
from dataclasses import dataclass, field
from .evaluator import evaluate_condition, EvaluationError
from .operators import execute_operator, OperatorError

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
        inputs: Optional[List[Dict[str, Any]]] = None,
        outputs: Optional[List[Dict[str, Any]]] = None,
        workflow_id: Optional[str] = None,
        call_stack: Optional[List[str]] = None,
        workflow_store: Optional["WorkflowStore"] = None,
        user_id: Optional[str] = None,
        variables: Optional[List[Dict[str, Any]]] = None,
        output_type: str = "string",
    ):
        """Initialize interpreter
        
        Args:
            tree: Workflow tree (must have 'start' key)
            inputs: DEPRECATED - List of input definitions. Use 'variables' instead.
            outputs: List of output definitions with name
            workflow_id: ID of this workflow (for cycle detection in subflows)
            call_stack: Stack of workflow IDs currently being executed (for cycle detection)
            workflow_store: Store for loading subworkflows (required for subprocess nodes)
            user_id: User ID for loading subworkflows (required for subprocess nodes)
            variables: List of variable definitions (unified system - replaces inputs)
            output_type: Workflow-level output type ('string', 'number', 'bool', 'json')
        """
        self.tree = tree
        
        # Unified variable system: prefer 'variables', fallback to 'inputs' for backwards compat
        # Variables include both user inputs (source='input') and derived values (source='subprocess')
        var_list = variables if variables is not None else (inputs or [])
        
        self.variables_schema = {var['id']: var for var in var_list}
        # Backwards compat alias
        self.inputs_schema = self.variables_schema
        
        self.outputs_schema = {out['name']: out for out in (outputs or [])}

        # Create mapping from variable names to IDs for condition evaluation
        # e.g., "Age" -> "var_age_int", "BMI" -> "var_bmi_float"
        # Also supports legacy "input_age_int" format
        # Handle variables without 'name' field by using ID as fallback
        self.name_to_id = {}
        for var in var_list:
            var_id = var.get('id', '')
            var_name = var.get('name')
            if var_name:
                self.name_to_id[var_name] = var_id
            # Also allow referencing by ID directly in templates
            if var_id:
                self.name_to_id[var_id] = var_id
        
        # Subflow support
        self.workflow_id = workflow_id
        self.call_stack = call_stack or []
        self.workflow_store = workflow_store
        self.user_id = user_id
        self.output_type = output_type
        
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

                if node_type in ('output', 'end'):
                    # Reached terminal node - success!
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

                elif node_type == 'calculation':
                    # Execute calculation and inject result as new variable
                    current = self._handle_calculation_node(current, context)

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
        
        # Get tree from subworkflow, rebuilding from nodes/edges if necessary
        # This handles workflows saved before tree computation was added to save endpoint
        sub_tree = subworkflow.tree
        if not sub_tree or 'start' not in sub_tree:
            from ..utils.flowchart import tree_from_flowchart
            sub_tree = tree_from_flowchart(subworkflow.nodes, subworkflow.edges)
            if not sub_tree or 'start' not in sub_tree:
                raise InterpreterError(
                    f"Subprocess node '{node_label}': subworkflow '{subworkflow.name}' "
                    f"has no start node. Ensure the subworkflow has a valid structure "
                    f"with a start node connected to other nodes."
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
            tree=sub_tree,  # Use rebuilt tree (handles empty stored tree)
            inputs=subworkflow.inputs,
            outputs=subworkflow.outputs,
            workflow_id=subworkflow_id,
            call_stack=new_call_stack,
            workflow_store=self.workflow_store,
            user_id=self.user_id,
            output_type=getattr(subworkflow, 'output_type', 'string'),
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

    def _handle_calculation_node(
        self,
        node: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Execute a calculation and inject its output as a new variable.
        
        Steps:
        1. Resolve operand values (from variables or literals)
        2. Execute the operator with resolved operands
        3. Inject result as new calculated variable in context
        4. Continue to next node
        
        Args:
            node: Calculation node with calculation.output, operator, operands
            context: Workflow execution context
            
        Returns:
            Next node to execute
            
        Raises:
            InterpreterError: If calculation fails
        """
        node_id = node.get('id', 'unknown')
        node_label = node.get('label', node_id)
        calculation = node.get('calculation')
        
        # Validate calculation exists
        if not calculation:
            raise InterpreterError(
                f"Calculation node '{node_label}' missing 'calculation' field"
            )
        
        output = calculation.get('output', {})
        operator_name = calculation.get('operator')
        operands = calculation.get('operands', [])
        
        # Validate required fields
        output_name = output.get('name') if isinstance(output, dict) else None
        if not output_name:
            raise InterpreterError(
                f"Calculation node '{node_label}' missing output.name"
            )
        if not operator_name:
            raise InterpreterError(
                f"Calculation node '{node_label}' missing operator"
            )
        if not operands:
            raise InterpreterError(
                f"Calculation node '{node_label}' missing operands"
            )
        
        # Resolve operand values
        resolved_operands = []
        for i, operand in enumerate(operands):
            kind = operand.get('kind')
            
            if kind == 'literal':
                value = operand.get('value')
                if value is None:
                    raise InterpreterError(
                        f"Calculation node '{node_label}': operand[{i}] has no value"
                    )
                resolved_operands.append(float(value))
                
            elif kind == 'variable':
                ref = operand.get('ref')
                if not ref:
                    raise InterpreterError(
                        f"Calculation node '{node_label}': operand[{i}] has no ref"
                    )
                
                # Look up variable value in context
                # ref can be either variable ID (var_weight_number) or variable name (Weight)
                value = None
                if ref in context:
                    value = context[ref]
                else:
                    # Try to resolve by name
                    var_id = self.name_to_id.get(ref)
                    if var_id and var_id in context:
                        value = context[var_id]
                
                if value is None:
                    raise InterpreterError(
                        f"Calculation node '{node_label}': operand[{i}] references "
                        f"variable '{ref}' which has no value in context"
                    )
                
                # Ensure numeric value
                if not isinstance(value, (int, float)):
                    raise InterpreterError(
                        f"Calculation node '{node_label}': operand[{i}] references "
                        f"variable '{ref}' with non-numeric value: {value}"
                    )
                
                resolved_operands.append(float(value))
            else:
                raise InterpreterError(
                    f"Calculation node '{node_label}': operand[{i}] has invalid kind '{kind}'"
                )
        
        # Execute the operator
        try:
            result = execute_operator(operator_name, resolved_operands)
        except OperatorError as e:
            raise InterpreterError(
                f"Calculation node '{node_label}' failed: {e}"
            )
        except ValueError as e:
            raise InterpreterError(
                f"Calculation node '{node_label}' failed: {e}"
            )
        
        # Inject result as new calculated variable in context
        self._inject_calculation_output(output_name, result, context)
        
        # Continue to next node
        children = node.get('children', [])
        if not children:
            raise InterpreterError(
                f"Calculation node '{node_label}' has no children. "
                f"Flow must continue after calculation or end explicitly."
            )
        
        return children[0]

    def _inject_calculation_output(
        self,
        output_name: str,
        output_value: float,
        context: Dict[str, Any]
    ) -> None:
        """Inject calculation output as a new derived variable in context.
        
        Args:
            output_name: Name of the output variable (e.g., "BMI")
            output_value: The calculated numeric value
            context: Workflow context (modified in place)
        """
        # Calculation output is always 'number' type
        output_type = "number"
        
        # Generate variable ID with calculated prefix
        variable_id = self._generate_variable_id(output_name, output_type, "calculated")
        
        # Add to name->id mapping for future condition evaluation
        self.name_to_id[output_name] = variable_id
        
        # Add to context
        context[variable_id] = output_value
        
        # Track in variables_schema for potential validation
        self.variables_schema[variable_id] = {
            "id": variable_id,
            "name": output_name,
            "type": output_type,
            "source": "calculated",  # Derived from calculation node
        }

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
        """Inject subflow output as a new derived variable in parent context.
        
        Dynamically registers the output as a new variable with source='subprocess'
        that can be used in subsequent decision nodes.
        
        Args:
            output_variable: Name of the variable (e.g., "CreditScore")
            output_value: The value returned by subworkflow
            context: Parent workflow context (modified in place)
        """
        # Infer type from output value
        output_type = self._infer_type(output_value)
        
        # Generate deterministic variable ID with subprocess prefix
        # Format: var_sub_{slug}_{type}
        variable_id = self._generate_variable_id(output_variable, output_type, "subprocess")
        
        # Add to name->id mapping for future condition evaluation
        self.name_to_id[output_variable] = variable_id
        
        # Add to context
        context[variable_id] = output_value
        
        # Track in variables_schema for potential validation
        self.variables_schema[variable_id] = {
            "id": variable_id,
            "name": output_variable,
            "type": output_type,
            "source": "subprocess",  # Derived from subprocess node
        }

    def _infer_type(self, value: Any) -> str:
        """Infer input type from value.
        
        Args:
            value: The value to analyze
            
        Returns:
            Type string: 'number', 'bool', 'string', or 'json'
            Note: Uses unified 'number' type for all numeric values
        """
        if isinstance(value, bool):
            return "bool"
        elif isinstance(value, (int, float)):
            # Unified numeric type - don't distinguish between int and float
            return "number"
        elif isinstance(value, str):
            return "string"
        elif isinstance(value, (dict, list)):
            return "json"
        else:
            return "string"  # Fallback

    def _generate_variable_id(self, name: str, var_type: str, source: str = "input") -> str:
        """Generate deterministic variable ID from name, type, and source.
        
        Follows the unified variable ID format:
        - Input variables: var_{slug}_{type}
        - Subprocess derived: var_sub_{slug}_{type}
        - Calculated: var_calc_{slug}_{type}
        - Constants: var_const_{slug}_{type}
        
Args:
            name: Variable name (e.g., "Credit Score")
            var_type: Variable type (e.g., "number", "string", "bool")
            source: Variable source ("input", "subprocess", "calculated", "constant")
            
        Returns:
            Variable ID (e.g., "var_credit_score_number", "var_sub_risk_number")
        """
        # Slugify: lowercase, replace non-alphanumeric with underscore
        slug = re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')
        
        if source == "input":
            return f"var_{slug}_{var_type}"
        else:
            # For derived variables, include abbreviated source prefix
            source_prefix = {
                "subprocess": "sub",
                "calculated": "calc",
                "constant": "const",
            }.get(source, source[:4])
            return f"var_{source_prefix}_{slug}_{var_type}"

    def _generate_input_id(self, name: str, input_type: str) -> str:
        """DEPRECATED: Use _generate_variable_id() instead.
        
        Kept for backwards compatibility. Generates legacy input_* format IDs.
        
Args:
            name: Input name (e.g., "Credit Score")
            input_type: Input type (e.g., "number")
            
        Returns:
            Legacy input ID (e.g., "input_credit_score_number")
        """
        # Slugify: lowercase, replace non-alphanumeric with underscore
        slug = re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')
        return f"input_{slug}_{input_type}"

    def _resolve_output_value(self, node: Dict[str, Any], context: Dict[str, Any]) -> Any:
        """Resolve output value from node configuration.
        
        Priority order:
        1. output_variable: Direct variable reference (preferred for number/bool)
           - Returns the raw value from the variable, preserving type
           - Example: output_variable="BMI" returns the numeric BMI value
        2. output_value: Static literal value
           - Cast to output_type (number, bool, json, string)
        3. output_template: String template with variable substitution
           - Only use for string outputs that need formatting
           - Example: "Patient BMI is {BMI}"
        4. label: Fallback (legacy support)
        
        Args:
            node: Output node with output_type, output_variable/value/template
            context: Execution context with variable values
            
        Returns:
            The resolved output value with appropriate type
        """
        output_type = self.output_type
        
        # Build lookup context: both variable IDs and friendly names
        friendly_context: Dict[str, Any] = {}
        for name, input_id in self.name_to_id.items():
            if input_id in context:
                friendly_context[name] = context[input_id]
        full_context = {**context, **friendly_context}
        
        # 1. Direct Variable Reference (preferred for number/bool)
        # Use output_variable to return a variable's raw value without string formatting
        if node.get('output_variable'):
            var_ref = node['output_variable']
            
            # Look up value by name or ID
            raw_value = None
            if var_ref in full_context:
                raw_value = full_context[var_ref]
            
            if raw_value is not None:
                # Return raw value, cast to declared output_type
                return self._cast_output_value(raw_value, output_type)
            else:
                # Variable not found - return error
                available_vars = list(friendly_context.keys())
                return (
                    f"Error: Variable '{var_ref}' not found in workflow context. "
                    f"Available variables: {available_vars}"
                )
        
        # 2. Static Literal Value
        if 'output_value' in node:
            val = node['output_value']
            return self._cast_output_value(val, output_type)

        # 3. String Template (use only for string outputs that need formatting)
        if node.get('output_template'):
            template = node['output_template']
            
            # For backwards compatibility: if template is a single variable like "{BMI}",
            # extract the raw value (same as output_variable behavior)
            stripped = template.strip()
            if (stripped.startswith('{') and stripped.endswith('}') and 
                stripped.count('{') == 1 and stripped.count('}') == 1):
                var_name = stripped[1:-1].strip()
                if var_name in full_context:
                    return self._cast_output_value(full_context[var_name], output_type)
            
            # Format template as string
            try:
                formatted = template.format(**full_context)
                return self._cast_output_value(formatted, output_type)
            except KeyError as e:
                missing_var = str(e).strip("'")
                available_vars = list(friendly_context.keys())
                return (
                    f"Error: Variable '{missing_var}' not found in workflow inputs. "
                    f"Available variables: {available_vars}"
                )
            except Exception as e:
                return f"Error formatting output: {str(e)}"

        # 4. Fallback to label (legacy support)
        label = node.get('label', '')
        if '{' in label and '}' in label:
            try:
                return label.format(**full_context)
            except KeyError as e:
                missing_var = str(e).strip("'")
                available_vars = list(friendly_context.keys())
                return (
                    f"Error: Variable '{missing_var}' not found in workflow inputs. "
                    f"Available variables: {available_vars}"
                )
            except Exception:
                return label
        return label

    def _cast_output_value(self, value: Any, output_type: str) -> Any:
        """Cast a value to the declared output type.
        
        Args:
            value: The value to cast (can be any type)
            output_type: Target type ('number', 'bool', 'json', 'string')
            
        Returns:
            The value cast to the appropriate type
            
        Note:
            - If value is already the correct type, returns as-is
            - For 'number': converts to float
            - For 'bool': converts to boolean
            - For 'json': parses string as JSON or returns dict/list as-is
            - For 'string': converts to string
        """
        try:
            if output_type == 'number':
                # If already numeric, return as-is
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    return float(value)
                # Try to parse string as number
                return float(value)
            elif output_type == 'bool':
                # If already bool, return as-is
                if isinstance(value, bool):
                    return value
                # Parse string as bool
                return str(value).lower() in ('true', '1', 'yes', 'on')
            elif output_type == 'json':
                # If already dict/list, return as-is
                if isinstance(value, (dict, list)):
                    return value
                # Try to parse string as JSON
                if isinstance(value, str):
                    return json.loads(value)
                return value
            else:
                # Default: string
                return str(value) if value is not None else ''
        except (ValueError, TypeError, json.JSONDecodeError) as e:
            # If casting fails, return original value with error context
            return f"Error casting to {output_type}: {str(e)}"

    def _validate_inputs(self, input_values: Dict[str, Any]) -> None:
        """Validate input values against variable schema.

        Args:
            input_values: Input values to validate (variable_id -> value)

        Raises:
            InterpreterError: If validation fails
        """
        # Check all required variables are present
        for var_id, schema in self.variables_schema.items():
            # Only validate input-source variables (user-provided)
            # Subprocess-derived and calculated variables are injected at runtime
            if schema.get('source') in ('subprocess', 'calculated'):
                continue
                
            if var_id not in input_values:
                raise InterpreterError(f"Missing required variable: {var_id}")

            value = input_values[var_id]
            var_type = schema['type']

            # Type validation
            if var_type == 'number':
                # Unified numeric type - accepts both int and float
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    raise InterpreterError(f"{var_id} must be number, got {type(value).__name__}")

            elif var_type == 'bool':
                if not isinstance(value, bool):
                    raise InterpreterError(f"{var_id} must be bool, got {type(value).__name__}")

            elif var_type in ('string', 'enum'):
                if not isinstance(value, str):
                    raise InterpreterError(f"{var_id} must be string, got {type(value).__name__}")

            # Range validation for numeric types
            if var_type == 'number' and 'range' in schema:
                range_spec = schema['range']
                if 'min' in range_spec and value < range_spec['min']:
                    raise InterpreterError(
                        f"Value error: {var_id}={value} below minimum {range_spec['min']}"
                    )
                if 'max' in range_spec and value > range_spec['max']:
                    raise InterpreterError(
                        f"Value error: {var_id}={value} exceeds maximum {range_spec['max']}"
                    )

            # Enum validation
            if var_type == 'enum' and 'enum_values' in schema:
                allowed = schema['enum_values']
                if value not in allowed:
                    raise InterpreterError(
                        f"Value error: {var_id} must be one of {allowed}, got '{value}'"
                    )

    def _handle_decision_node(self, node: Dict[str, Any], context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Handle decision node: evaluate structured condition and select branch.

        Decision nodes MUST have a 'condition' field with structured condition data:
        {
            "input_id": "input_age_int",   # The workflow input to compare
            "comparator": "gte",            # Comparison operator (eq, lt, gt, etc.)
            "value": 18,                    # Value to compare against
            "value2": null                  # Optional second value for range comparisons
        }

        Args:
            node: Decision node with 'condition' field
            context: Current variable context (input_id -> value)

        Returns:
            Next node to visit based on condition result (True/False branch)

        Raises:
            InterpreterError: If condition is missing or evaluation fails
        """
        node_id = node.get('id', 'unknown')
        node_label = node.get('label', node_id)
        condition = node.get('condition')

        # Validate condition exists
        if not condition:
            raise InterpreterError(
                f"Decision node '{node_label}' (id: {node_id}) has no condition. "
                f"Decision nodes must have a structured 'condition' field."
            )

        # Evaluate the structured condition against execution context
        try:
            result = evaluate_condition(condition, context)
        except EvaluationError as e:
            raise InterpreterError(
                f"Failed to evaluate condition at decision node '{node_label}' "
                f"(id: {node_id}): {e}"
            )
        except Exception as e:
            raise InterpreterError(
                f"Unexpected error evaluating condition at decision node '{node_label}' "
                f"(id: {node_id}): {e}"
            )

        # Convert result to boolean (should already be bool, but ensure)
        condition_result = bool(result)

        # Find matching child based on edge label (True/False)
        children = node.get('children', [])
        if not children:
            raise InterpreterError(f"Decision node '{node_label}' (id: {node_id}) has no children")

        # Try to match edge label
        next_node = self._find_branch(children, condition_result)

        if next_node is None:
            raise InterpreterError(
                f"No branch found for condition result {condition_result} "
                f"at decision node '{node_label}' (id: {node_id})"
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
        - "Yes", "True", "Y", "T", "1" → True branch
        - "No", "False", "N", "F", "0" → False branch
        - Empty or missing labels → Position-based fallback:
            - Position 0 (first child) = True branch
            - Position 1 (second child) = False branch
        """
        if len(children) == 0:
            return None
            
        if len(children) == 1:
            # Only one child - take it regardless of condition
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

        # Position-based fallback when edge labels are empty or missing:
        # Convention: first child (index 0) = True branch, second child (index 1) = False branch
        # This matches how edges are typically created: true edge first, false edge second
        if condition_result:
            # True condition → take first child (position 0)
            return children[0]
        else:
            # False condition → take second child (position 1)
            return children[1] if len(children) > 1 else children[0]
