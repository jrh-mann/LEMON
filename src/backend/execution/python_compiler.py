"""Python code generator for LEMON workflows.

Transforms workflow trees (nodes, edges, variables) into clean,
executable Python functions with proper control flow.

Example output:
    def loan_approval(age: int, income: float, credit_score: str) -> str:
        if age < 18:
            return "Rejected: Underage"
        if income >= 50000:
            if credit_score.lower() == "good":
                return "Approved"
            else:
                return "Approved with conditions"
        else:
            return "Rejected: Insufficient income"
"""

from __future__ import annotations

import re
from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass, field


@dataclass
class CompilationResult:
    """Result of Python code generation."""
    success: bool
    code: Optional[str] = None
    error: Optional[str] = None
    warnings: List[str] = field(default_factory=list)


class CompilationError(Exception):
    """Raised when code generation fails."""
    pass


class VariableNameResolver:
    """Resolves workflow variable IDs to Python-safe identifiers.

    Maps IDs like 'var_patient_age_int' to clean Python names like 'patient_age'.
    Handles conflicts by adding numeric suffixes.
    """

    def __init__(self, variables: List[Dict[str, Any]]):
        """Initialize resolver with variable definitions.

        Args:
            variables: List of variable definitions with 'id', 'name', 'type' fields.
        """
        self.variables = variables
        self.id_to_var = {v['id']: v for v in variables}
        self.id_to_python: Dict[str, str] = {}
        self.used_names: Set[str] = set()

        # Build mappings
        for var in variables:
            var_id = var['id']
            python_name = self._to_python_name(var['name'])

            # Handle conflicts
            original_name = python_name
            counter = 2
            while python_name in self.used_names:
                python_name = f"{original_name}_{counter}"
                counter += 1

            self.id_to_python[var_id] = python_name
            self.used_names.add(python_name)

    def _to_python_name(self, name: str) -> str:
        """Convert a friendly name to a valid Python identifier.

        Args:
            name: Human-readable name like 'Patient Age'

        Returns:
            Python identifier like 'patient_age'
        """
        # Lowercase and replace non-alphanumeric with underscores
        slug = re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')

        # Ensure it doesn't start with a digit
        if slug and slug[0].isdigit():
            slug = f"var_{slug}"

        # Handle empty or reserved names
        if not slug or slug in {'if', 'else', 'for', 'while', 'return', 'def', 'class', 'import', 'from', 'and', 'or', 'not', 'in', 'is', 'True', 'False', 'None'}:
            slug = f"var_{slug}" if slug else "var"

        return slug

    def resolve(self, var_id: str) -> str:
        """Get Python name for a variable ID.

        Args:
            var_id: Variable ID like 'var_age_int'

        Returns:
            Python identifier like 'age'

        Raises:
            CompilationError: If variable ID not found
        """
        if var_id not in self.id_to_python:
            raise CompilationError(f"Unknown variable ID: {var_id}")
        return self.id_to_python[var_id]

    def get_type(self, var_id: str) -> str:
        """Get Python type hint for a variable.

        Args:
            var_id: Variable ID

        Returns:
            Python type hint string
        """
        if var_id not in self.id_to_var:
            return "Any"

        var_type = self.id_to_var[var_id].get('type', 'string')
        return TYPE_MAP.get(var_type, 'str')

    def get_friendly_name(self, var_id: str) -> str:
        """Get original friendly name for a variable.

        Args:
            var_id: Variable ID

        Returns:
            Friendly name like 'Patient Age'
        """
        if var_id not in self.id_to_var:
            return var_id
        return self.id_to_var[var_id].get('name', var_id)


# Type mapping from workflow types to Python type hints
TYPE_MAP = {
    'number': 'float',  # Unified numeric type maps to Python float
    'bool': 'bool',
    'string': 'str',
    'enum': 'str',
    'date': 'str',  # Dates as ISO strings for simplicity
    'json': 'dict',
}


# Maps calculation operators to Python expressions
# {operands} will be replaced with the appropriate operand expression(s)
OPERATOR_TO_PYTHON = {
    # Unary operators
    'negate': '-{0}',
    'abs': 'abs({0})',
    'sqrt': '({0}) ** 0.5',
    'square': '({0}) ** 2',
    'cube': '({0}) ** 3',
    'reciprocal': '1 / ({0})',
    'floor': 'int({0})',
    'ceil': 'int({0}) + (1 if {0} % 1 else 0)',
    'round': 'round({0})',
    'sign': '(1 if {0} > 0 else (-1 if {0} < 0 else 0))',
    'ln': 'math.log({0})',
    'log10': 'math.log10({0})',
    'exp': 'math.exp({0})',
    'sin': 'math.sin({0})',
    'cos': 'math.cos({0})',
    'tan': 'math.tan({0})',
    'asin': 'math.asin({0})',
    'acos': 'math.acos({0})',
    'atan': 'math.atan({0})',
    'degrees': 'math.degrees({0})',
    'radians': 'math.radians({0})',
    # Binary operators
    'subtract': '({0}) - ({1})',
    'divide': '({0}) / ({1})',
    'floor_divide': '({0}) // ({1})',
    'modulo': '({0}) % ({1})',
    'power': '({0}) ** ({1})',
    'log': 'math.log({0}, {1})',
    'atan2': 'math.atan2({0}, {1})',
    # Variadic operators (use special handling)
    'add': None,  # Special: sum of operands
    'multiply': None,  # Special: product of operands
    'min': None,  # Special: min()
    'max': None,  # Special: max()
    'sum': None,  # Special: sum()
    'average': None,  # Special: sum / len
    'hypot': None,  # Special: math.hypot()
    'geometric_mean': None,  # Special: statistics.geometric_mean()
    'harmonic_mean': None,  # Special: statistics.harmonic_mean()
    'variance': None,  # Special: statistics.variance()
    'std_dev': None,  # Special: statistics.stdev()
    'range': None,  # Special: max - min
}


class ConditionCompiler:
    """Compiles workflow DecisionConditions to Python boolean expressions.

    Supports all comparator types from evaluator.py.
    """

    # Maps comparators to Python expression templates
    # {var} = variable name, {val} = comparison value, {val2} = second value (for ranges)
    COMPARATOR_TEMPLATES = {
        # Numeric
        'eq': '{var} == {val}',
        'neq': '{var} != {val}',
        'lt': '{var} < {val}',
        'lte': '{var} <= {val}',
        'gt': '{var} > {val}',
        'gte': '{var} >= {val}',
        'within_range': '{val} <= {var} <= {val2}',
        # Boolean
        'is_true': '{var} is True',
        'is_false': '{var} is False',
        # String (case-insensitive)
        'str_eq': '{var}.lower() == {val}.lower()',
        'str_neq': '{var}.lower() != {val}.lower()',
        'str_contains': '{val}.lower() in {var}.lower()',
        'str_starts_with': '{var}.lower().startswith({val}.lower())',
        'str_ends_with': '{var}.lower().endswith({val}.lower())',
        # Date (assuming ISO format strings)
        'date_eq': '{var} == {val}',
        'date_before': '{var} < {val}',
        'date_after': '{var} > {val}',
        'date_between': '{val} <= {var} <= {val2}',
        # Enum (case-insensitive)
        'enum_eq': '{var}.lower() == {val}.lower()',
        'enum_neq': '{var}.lower() != {val}.lower()',
    }

    def compile(
        self,
        condition: Dict[str, Any],
        resolver: VariableNameResolver
    ) -> str:
        """Compile a DecisionCondition to a Python expression.

        Args:
            condition: DecisionCondition dict with input_id, comparator, value, value2
            resolver: Variable name resolver

        Returns:
            Python expression string like 'age >= 18'

        Raises:
            CompilationError: If condition is invalid
        """
        input_id = condition.get('input_id')
        comparator = condition.get('comparator')
        value = condition.get('value')
        value2 = condition.get('value2')

        if not input_id:
            raise CompilationError("Condition missing 'input_id'")
        if not comparator:
            raise CompilationError("Condition missing 'comparator'")
        if comparator not in self.COMPARATOR_TEMPLATES:
            raise CompilationError(f"Unknown comparator: '{comparator}'")

        # Get Python variable name
        var_name = resolver.resolve(input_id)

        # Format the value as Python literal
        val_str = self._format_value(value)
        val2_str = self._format_value(value2) if value2 is not None else None

        # Get template and fill in
        template = self.COMPARATOR_TEMPLATES[comparator]
        expr = template.format(var=var_name, val=val_str, val2=val2_str)

        return expr

    def _format_value(self, value: Any) -> str:
        """Format a value as a Python literal.

        Args:
            value: The value to format

        Returns:
            Python literal string
        """
        if value is None:
            return 'None'
        elif isinstance(value, bool):
            return 'True' if value else 'False'
        elif isinstance(value, str):
            # Escape quotes and use repr for safety
            return repr(value)
        elif isinstance(value, (int, float)):
            return str(value)
        else:
            return repr(value)


class PythonCodeGenerator:
    """Generates Python source code from LEMON workflow trees.

    Usage:
        generator = PythonCodeGenerator()
        result = generator.compile(tree, variables, outputs, "my_workflow")
        if result.success:
            print(result.code)
    """

    def __init__(self):
        """Initialize the generator."""
    def __init__(
        self,
        nodes: List[Dict[str, Any]],
        edges: List[Dict[str, Any]],
        variables: List[Dict[str, Any]],
        outputs: Optional[List[Dict[str, Any]]] = None,
        workflow_name: str = "workflow",
        include_main: bool = False,
        fetch_subworkflow: Optional[callable] = None,
        _processed_subflows: Optional[Set[str]] = None,
    ):
        """Initialize the compiler.

        Args:
            nodes: Workflow nodes
            edges: Workflow edges
            variables: Variable definitions
            outputs: Optional end node output definitions
            workflow_name: Name of the generated Python function
            include_main: Whether to include an if __name__ == '__main__' block
            fetch_subworkflow: Optional callback `(workflow_id) -> Workflow` for resolving subflows.
            _processed_subflows: Optional set of already processed subflow IDs to prevent infinite cycles.
        """
        self.nodes = {node.get('id'): node for node in nodes if node.get('id')}
        self.edges = edges
        self.variables = variables
        self.outputs = outputs
        self.workflow_name = self._to_function_name(workflow_name)
        self.include_main = include_main
        self.fetch_subworkflow = fetch_subworkflow
        self._processed_subflows = _processed_subflows or set()

        self.condition_compiler = ConditionCompiler()
        self._indent_level = 0
        self._lines: List[str] = []
        self._warnings: List[str] = []

    def compile(self) -> CompilationResult:
        """Compile the workflow to Python code.

        Returns:
            CompilationResult with generated code or errors.
        """
        try:
            # Reset state for this compilation run
            self._indent_level = 0
            self._lines = []
            self._warnings = []

            # Create resolver
            # Filter to only input-source variables for function parameters
            input_vars = [v for v in self.variables if v.get('source', 'input') == 'input']
            self.resolver = VariableNameResolver(self.variables)

            # First, check and compile any subflows as helper functions
            subflow_code_blocks = []
            
            if self.fetch_subworkflow:
                for node in self.nodes.values():
                    if node.get("type") == "subprocess":
                        sub_id = node.get("subworkflow_id")
                        if not sub_id or sub_id in self._processed_subflows:
                            continue
                            
                        self._processed_subflows.add(sub_id)
                        subflow_obj = self.fetch_subworkflow(sub_id)
                        
                        if subflow_obj:
                            sub_func_name = f"subflow_{sub_id.replace('-', '_')}"
                            
                            sub_compiler = PythonCodeGenerator(
                                nodes=subflow_obj.nodes,
                                edges=subflow_obj.edges,
                                variables=subflow_obj.inputs,
                                outputs=subflow_obj.outputs,
                                workflow_name=sub_func_name,
                                fetch_subworkflow=self.fetch_subworkflow,
                                _processed_subflows=self._processed_subflows,
                            )
                            # Compile subflow without imports/main block
                            sub_result = sub_compiler.compile()
                            if sub_result.success and sub_result.code:
                                subflow_code_blocks.append(sub_result.code)
                            self._warnings.extend(["Subflow: " + w for w in sub_result.warnings])
                        else:
                            self._warnings.append(f"Warning: Could not fetch subworkflow '{sub_id}'. Generated call will fail.")
            
            # --- Compile Root Workflow ---
            # Generate imports
            self._generate_imports(self.variables)
            self._add_line("")

            # Generate function signature
            self._generate_function_signature(self.workflow_name, input_vars)

            # Generate docstring
            self._indent_level += 1
            self._generate_docstring(self.workflow_name, input_vars, self.outputs)

            # Generate body
            start_nodes = [n for n in self.nodes.values() if n.get('type') == 'start']
            if not start_nodes:
                if not self.nodes:
                    raise CompilationError("Workflow has no nodes")
                # Fallback to first node if no explicit start node exists
                start_node = next(iter(self.nodes.values()))
            else:
                start_node = start_nodes[0]
            
            # The start node itself might have code, or merely act as a pointer. 
            # If it's literally a 'start' node, we visit its children. 
            # If it's a fallback node of a different type, we should visit IT directly.
            if start_node.get('type') == 'start':
                children = self._get_children(start_node)
                if not children:
                    self._add_line("pass  # Empty workflow")
                else:
                    self._visit_node(children[0])
            else:
                self._visit_node(start_node)
                
            self._indent_level -= 1
            
            # Generate main block
            if self.include_main:
                self._add_line("")
                self._generate_main_block(self.workflow_name, input_vars)
            
            # Append subflow helper functions to the start of the final string
            combined_code = "\n\n".join(subflow_code_blocks)
            if combined_code:
                combined_code += "\n\n"
            combined_code += "\n".join(self._lines)
            
            return CompilationResult(
                success=True,
                code=combined_code,
                warnings=self._warnings
            )
            
        except CompilationError as e:
            return CompilationResult(
                success=False,
                error=str(e),
                warnings=self._warnings
            )
        except Exception as e:
            return CompilationResult(
                success=False,
                error=f"Unexpected error: {str(e)}",
                warnings=self._warnings
            )

    def _to_function_name(self, name: str) -> str:
        """Convert workflow name to valid Python function name."""
        slug = re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')
        if slug and slug[0].isdigit():
            slug = f"workflow_{slug}"
        return slug or "workflow"

    def _generate_imports(self, variables: List[Dict[str, Any]]) -> None:
        """Generate necessary import statements."""
        imports = set()

        # Check if we need datetime for date types
        for var in variables:
            if var.get('type') == 'date':
                imports.add("from datetime import date")

        # Add typing import for type hints
        imports.add("from typing import Union, List, Dict, Any, Optional, Set, Callable")
        
        # Always include math for calculation support
        # (could be optimized to only include if calculations are present)
        imports.add("import math")
        imports.add("import statistics")
        imports.add("import re") # For _to_function_name and _compile_template
        imports.add("import json") # For _format_output_value

        for imp in sorted(imports):
            self._add_line(imp)

    def _generate_function_signature(
        self,
        func_name: str,
        input_vars: List[Dict[str, Any]]
    ) -> None:
        """Generate function definition with typed parameters."""
        params = []
        for var in input_vars:
            var_id = var['id']
            python_name = self.resolver.resolve(var_id)
            python_type = self.resolver.get_type(var_id)
            params.append(f"{python_name}: {python_type}")

        params_str = ", ".join(params)
        self._add_line(f"def {func_name}({params_str}) -> Union[str, int, float, bool]:")

    def _generate_docstring(
        self,
        workflow_name: str,
        input_vars: List[Dict[str, Any]],
        outputs: Optional[List[Dict[str, Any]]]
    ) -> None:
        """Generate Google-style docstring."""
        self._add_line('"""')
        self._add_line(f"{workflow_name}")
        self._add_line("")

        if input_vars:
            self._add_line("Args:")
            for var in input_vars:
                var_id = var['id']
                python_name = self.resolver.resolve(var_id)
                friendly_name = var.get('name', python_name)
                description = var.get('description', friendly_name)
                self._add_line(f"    {python_name}: {description}")
            self._add_line("")

        self._add_line("Returns:")
        if outputs:
            output_names = [o.get('name', 'result') for o in outputs]
            self._add_line(f"    Workflow output: {', '.join(output_names)}")
        else:
            self._add_line("    Workflow result")

        self._add_line('"""')

    def _generate_main_block(
        self,
        func_name: str,
        input_vars: List[Dict[str, Any]]
    ) -> None:
        """Generate if __name__ == "__main__" block with example usage."""
        self._add_line('if __name__ == "__main__":')
        self._indent_level += 1
        self._add_line("# Example usage")

# Generate example call with placeholder values
        example_args = []
        for var in input_vars:
            var_type = var.get('type', 'string')
            if var_type == 'number':
                example_args.append("0.0")
            elif var_type == 'bool':
                example_args.append("False")
            else:
                example_args.append('""')

        args_str = ", ".join(example_args)
        self._add_line(f"result = {func_name}({args_str})")
        self._add_line("print(f\"Result: {result}\")")
        self._indent_level -= 1

    def _get_children(self, node: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get children nodes for a given node."""
        node_id = node.get('id')
        if not node_id:
            return []
        
        children = []
        for edge in self.edges:
            if edge.get('source') == node_id:
                target_id = edge.get('target')
                if target_id in self.nodes:
                    child_node = self.nodes[target_id]
                    child_node['edge_label'] = edge.get('label', '') # Attach edge label for decision nodes
                    children.append(child_node)
        
        # Sort children to ensure consistent order (e.g., for decision branches)
        # This might need more sophisticated logic based on actual workflow editor behavior
        children.sort(key=lambda n: n.get('edge_label', '') + n.get('id', ''))
        return children

    def _visit_node(self, node: Dict[str, Any]) -> None:
        """Visit a node and generate appropriate code.

        Args:
            node: Tree node to visit
        """
        node_type = node.get('type')
        node_id = node.get('id', 'unknown')

        if node_type in ('output', 'end'):
            self._visit_end_node(node)

        elif node_type == 'decision':
            self._visit_decision_node(node)

        elif node_type == 'subprocess':
            self._visit_subprocess_node(node)

        elif node_type == 'calculation':
            self._visit_calculation_node(node)

        elif node_type in ('start', 'action', 'process'):
            # Pass-through nodes - continue to children
            children = self._get_children(node)
            if children:
                self._visit_node(children[0])
            else:
                self._warnings.append(f"Node '{node_id}' has no continuation")
                self._add_line(f"pass  # Node '{node_id}' has no continuation")

        else:
            self._warnings.append(f"Unknown node type '{node_type}' at '{node_id}'")
            self._add_line(f"pass  # Unknown node type: {node_type}")

    def _visit_end_node(self, node: Dict[str, Any]) -> None:
        """Generate return statement for end/output node."""
        output_value = self._resolve_output(node)
        self._add_line(f"return {output_value}")

    def _resolve_output(self, node: Dict[str, Any]) -> str:
        """Resolve output value from node to Python expression.

        Args:
            node: End/output node

        Returns:
            Python expression for the return value
        """
        # Priority: output_template > output_value > label

        if node.get('output_template'):
            template = node['output_template']
            # Convert {Variable} to {python_name} for f-string
            return self._compile_template(template)

        if 'output_value' in node:
            value = node['output_value']
            output_type = node.get('output_type', 'string')
            return self._format_output_value(value, output_type)

        # Fallback to label
        label = node.get('label', '')
        if '{' in label and '}' in label:
            return self._compile_template(label)
        return repr(label)

    def _compile_template(self, template: str) -> str:
        """Convert a template string to Python f-string.

        Converts {VariableName} to {python_name} format.

        Args:
            template: Template like "Result: {Age}"

        Returns:
            f-string like 'f"Result: {age}"'
        """
        # Find all {variable} references
        pattern = r'\{([^}]+)\}'

        def replace_var(match):
            var_name = match.group(1)
            # Try to find variable by friendly name
            for var_id, var in self.resolver.id_to_var.items():
                if var.get('name') == var_name:
                    return '{' + self.resolver.resolve(var_id) + '}'
            # Try by ID
            if var_name in self.resolver.id_to_python:
                return '{' + self.resolver.resolve(var_name) + '}'
# Keep as-is (will use local variable if exists)
            return '{' + var_name.lower().replace(' ', '_') + '}'

        converted = re.sub(pattern, replace_var, template)
        return f'f"{converted}"'

    def _format_output_value(self, value: Any, output_type: str) -> str:
        """Format static output value as Python literal."""
        if output_type == 'number':
            return str(float(value))
        elif output_type == 'bool':
            return 'True' if str(value).lower() in ('true', '1', 'yes') else 'False'
        elif output_type == 'json':
            import json
            return repr(json.loads(value) if isinstance(value, str) else value)
        else:
            return repr(str(value))

    def _visit_decision_node(self, node: Dict[str, Any]) -> None:
        """Generate if/else block for decision node."""
        condition = node.get('condition')
        children = self._get_children(node)
        node_label = node.get('label', node.get('id', 'decision'))

        if not condition:
            self._warnings.append(f"Decision node '{node_label}' has no condition")
            self._add_line(f"# WARNING: Decision '{node_label}' has no condition")
            if children:
                self._visit_node(children[0])
            return

        # Compile condition to Python expression
        try:
            condition_expr = self.condition_compiler.compile(condition, self.resolver)
        except CompilationError as e:
            # Provide helpful error message with available variable IDs
            available_vars = list(self.resolver.id_to_python.keys())
            input_id = condition.get('input_id', 'unknown')
            warning_msg = (
                f"Decision '{node_label}' references variable '{input_id}' "
                f"which is not defined. Available variables: {available_vars}"
            )
            self._warnings.append(warning_msg)
            self._add_line(f"# ERROR: {warning_msg}")
            self._add_line("pass  # Condition could not be compiled")
            return

        # Find true and false branches
        true_branch = None
        false_branch = None
        true_labels = {'yes', 'true', 'y', 't', '1'}
        false_labels = {'no', 'false', 'n', 'f', '0'}

        for child in children:
            edge_label = child.get('edge_label', '').lower().strip()
            if edge_label in true_labels:
                true_branch = child
            elif edge_label in false_labels:
                false_branch = child

        # Fallback: first child is true, second is false
        if true_branch is None and len(children) >= 1:
            true_branch = children[0]
        if false_branch is None and len(children) >= 2:
            false_branch = children[1]

        # Generate if block
        self._add_line(f"if {condition_expr}:")
        self._indent_level += 1
        if true_branch:
            self._visit_node(true_branch)
        else:
            self._add_line("pass")
        self._indent_level -= 1

        # Generate else block
        if false_branch:
            self._add_line("else:")
            self._indent_level += 1
            self._visit_node(false_branch)
            self._indent_level -= 1

    def _visit_subprocess_node(self, node: Dict[str, Any]) -> None:
        """Generate subprocess call.

        Requires self.fetch_subworkflow to be provided to recursively find 
        and compile subworkflows as helper functions.
        """
        node_label = node.get('label', node.get('id', 'subprocess'))
        subworkflow_id = node.get('subworkflow_id', 'unknown')
        output_variable = node.get('output_variable', 'result')
        input_mapping = node.get('input_mapping') or {}

        # 1. Output the function call
        python_var = re.sub(r'[^a-z0-9]+', '_', output_variable.lower()).strip('_')
        self._add_line(f"# Subprocess: {node_label}")
        
        # Determine the function name the subflow will be compiled into
        sub_func_name = f"subflow_{subworkflow_id.replace('-', '_')}"
        
        if self.fetch_subworkflow:
            # Map parent variables to the subflow's arguments
            kwargs = []
            for sub_in, parent_var_id in input_mapping.items():
                if parent_var_id in self.resolver.id_to_python:
                    arg_val = self.resolver.resolve(parent_var_id)
                else:
                    # If parent_var_id is not a known variable, assume it's a literal or a direct reference
                    # This might need more robust handling depending on how input_mapping is structured
                    arg_val = repr(parent_var_id) # Treat as literal string for now
                # Clean the sub_in arg name just in case
                clean_kwarg = re.sub(r'[^a-z0-9]+', '_', sub_in.lower()).strip('_')
                kwargs.append(f"{clean_kwarg}={arg_val}")
                
            kwargs_str = ", ".join(kwargs)
            self._add_line(f"{python_var} = {sub_func_name}({kwargs_str})")
        else:
            self._add_line(f"# TODO: Implement call to subworkflow '{subworkflow_id}'")
            self._add_line(f"{python_var} = None  # Placeholder for subprocess output")
            self._warnings.append(
                f"Subprocess '{node_label}' requires manual implementation. "
                f"Subworkflow ID: {subworkflow_id}"
            )

        # Continue to children
        children = self._get_children(node)
        if children:
            self._add_line("")
            self._visit_node(children[0])

    def _visit_calculation_node(self, node: Dict[str, Any]) -> None:
        """Generate calculation expression and assignment.
        
        Generates Python code like:
            bmi = weight / (height ** 2)
        """
        node_label = node.get('label', node.get('id', 'calculation'))
        calculation = node.get('calculation', {})
        
        output = calculation.get('output', {})
        operator_name = calculation.get('operator', 'add')
        operands = calculation.get('operands', [])
        
        output_name = output.get('name', 'result') if isinstance(output, dict) else 'result'
        python_var = re.sub(r'[^a-z0-9]+', '_', output_name.lower()).strip('_')
        
        # Resolve operand expressions
        operand_exprs = []
        for operand in operands:
            kind = operand.get('kind')
            if kind == 'literal':
                value = operand.get('value', 0)
                operand_exprs.append(str(float(value)))
            elif kind == 'variable':
                ref = operand.get('ref', '')
                # Try to resolve to Python variable name
                if ref in self.resolver.id_to_python:
                    operand_exprs.append(self.resolver.resolve(ref))
                else:
                    # Try by friendly name
                    for var_id, var in self.resolver.id_to_var.items():
                        if var.get('name') == ref:
                            operand_exprs.append(self.resolver.resolve(var_id))
                            break
                    else:
                        # Fallback to slugified name
                        slug = re.sub(r'[^a-z0-9]+', '_', ref.lower()).strip('_')
                        operand_exprs.append(slug)
        
        # Generate the calculation expression
        expr = self._compile_operator_expression(operator_name, operand_exprs)
        
        # Add comment with node label
        self._add_line(f"# Calculation: {node_label}")
        self._add_line(f"{python_var} = {expr}")
        
        # Register the output variable for later use
        # This allows subsequent decision nodes to reference it
        calc_var_id = f"var_calc_{python_var}_number"
        self.resolver.id_to_python[calc_var_id] = python_var
        self.resolver.id_to_var[calc_var_id] = {
            'id': calc_var_id,
            'name': output_name,
            'type': 'number',
            'source': 'calculated',
        }
        # Also map by name
        self.resolver.id_to_python[output_name] = python_var
        
        # Continue to children
        children = self._get_children(node)
        if children:
            self._add_line("")
            self._visit_node(children[0])
    
    def _compile_operator_expression(
        self,
        operator_name: str,
        operand_exprs: List[str]
    ) -> str:
        """Compile operator and operands to Python expression.
        
        Args:
            operator_name: Name of the operator (e.g., 'add', 'divide', 'sqrt')
            operand_exprs: List of Python expressions for operands
            
        Returns:
            Python expression string
        """
        # Check if we have a template for this operator
        template = OPERATOR_TO_PYTHON.get(operator_name)
        
        if template is not None:
            # Use template (for unary/binary operators)
            return template.format(*operand_exprs)
        
        # Handle variadic operators specially
        operands_str = ', '.join(operand_exprs)
        
        if operator_name in ('add', 'sum'):
            return f"({' + '.join(operand_exprs)})"
        elif operator_name == 'multiply':
            return f"({' * '.join(operand_exprs)})"
        elif operator_name == 'min':
            return f"min({operands_str})"
        elif operator_name == 'max':
            return f"max({operands_str})"
        elif operator_name == 'average':
            return f"(({' + '.join(operand_exprs)}) / {len(operand_exprs)})"
        elif operator_name == 'hypot':
            return f"math.hypot({operands_str})"
        elif operator_name == 'geometric_mean':
            return f"statistics.geometric_mean([{operands_str}])"
        elif operator_name == 'harmonic_mean':
            return f"statistics.harmonic_mean([{operands_str}])"
        elif operator_name == 'variance':
            return f"statistics.variance([{operands_str}])"
        elif operator_name == 'std_dev':
            return f"statistics.stdev([{operands_str}])"
        elif operator_name == 'range':
            return f"(max({operands_str}) - min({operands_str}))"
        else:
            # Unknown operator - generate error comment
            self._warnings.append(f"Unknown operator '{operator_name}'")
            return f"0  # Unknown operator: {operator_name}({operands_str})"

    def _add_line(self, line: str) -> None:
        """Add a line of code with current indentation."""
        if line:
            indent = "    " * self._indent_level
            self._lines.append(f"{indent}{line}")
        else:
            self._lines.append("")


def compile_workflow_to_python(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
    variables: List[Dict[str, Any]],
    outputs: Optional[List[Dict[str, Any]]] = None,
    workflow_name: str = "workflow",
    include_imports: bool = True,
    include_docstring: bool = True,
    include_main: bool = False,
    fetch_subworkflow: Optional[callable] = None,
) -> CompilationResult:
    """Helper function to compile a workflow to Python.

    Args:
        nodes: Workflow nodes
        edges: Workflow edges
        variables: Variable definitions
        outputs: Optional end node output definitions
        workflow_name: Name of the generated Python function
        include_imports: Whether to include typing imports at the top
        include_docstring: Whether to include docstring and parameter descriptions
        include_main: Whether to include an if __name__ == "__main__" block
        fetch_subworkflow: Optional callback `(workflow_id) -> Workflow` for resolving subflows.

    Returns:
        CompilationResult
    """
    generator = PythonCodeGenerator(
        nodes=nodes,
        edges=edges,
        variables=variables,
        outputs=outputs,
        workflow_name=workflow_name,
        include_main=include_main,
        fetch_subworkflow=fetch_subworkflow,
    )
    return generator.compile()
