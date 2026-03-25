"""Tests for the Python code generator (python_compiler.py)."""

import ast
import pytest
from src.backend.execution.python_compiler import (
    PythonCodeGenerator,
    CompilationResult,
    CompilationError,
    VariableNameResolver,
    ConditionCompiler,
    compile_workflow_to_python,
)
from src.backend.execution.interpreter import TreeInterpreter
from src.backend.utils.flowchart import tree_from_flowchart


# --- VariableNameResolver Tests ---


class TestVariableNameResolver:
    """Tests for variable name resolution."""

    def test_simple_name_conversion(self):
        variables = [
            {"id": "var_patient_age_int", "name": "Patient Age", "type": "number"},
        ]
        resolver = VariableNameResolver(variables)
        assert resolver.resolve("var_patient_age_int") == "patient_age"

    def test_multiple_variables(self):
        variables = [
            {"id": "var_age_int", "name": "Age", "type": "number"},
            {"id": "var_income_float", "name": "Income", "type": "number"},
            {"id": "var_active_bool", "name": "Active", "type": "bool"},
        ]
        resolver = VariableNameResolver(variables)
        assert resolver.resolve("var_age_int") == "age"
        assert resolver.resolve("var_income_float") == "income"
        assert resolver.resolve("var_active_bool") == "active"

    def test_name_conflict_resolution(self):
        variables = [
            {"id": "var_age_int", "name": "Age", "type": "number"},
            {"id": "var_age_float", "name": "Age", "type": "number"},
        ]
        resolver = VariableNameResolver(variables)
        # Second 'age' gets a suffix
        assert resolver.resolve("var_age_int") == "age"
        assert resolver.resolve("var_age_float") == "age_2"

    def test_special_characters_removed(self):
        variables = [
            {"id": "var_test_string", "name": "Test@#$%Name!", "type": "string"},
        ]
        resolver = VariableNameResolver(variables)
        assert resolver.resolve("var_test_string") == "test_name"

    def test_leading_digit_prefixed(self):
        variables = [
            {"id": "var_123_string", "name": "123Test", "type": "string"},
        ]
        resolver = VariableNameResolver(variables)
        assert resolver.resolve("var_123_string") == "var_123test"

    def test_reserved_word_prefixed(self):
        variables = [
            {"id": "var_if_string", "name": "if", "type": "string"},
        ]
        resolver = VariableNameResolver(variables)
        assert resolver.resolve("var_if_string") == "var_if"

    def test_unknown_variable_raises(self):
        variables = []
        resolver = VariableNameResolver(variables)
        with pytest.raises(CompilationError, match="Unknown variable ID"):
            resolver.resolve("nonexistent_var")

    def test_get_type(self):
        variables = [
            {"id": "var_age_int", "name": "Age", "type": "number"},
            {"id": "var_price_float", "name": "Price", "type": "number"},
            {"id": "var_name_string", "name": "Name", "type": "string"},
        ]
        resolver = VariableNameResolver(variables)
        assert resolver.get_type("var_age_int") == "float"
        assert resolver.get_type("var_price_float") == "float"
        assert resolver.get_type("var_name_string") == "str"

    def test_get_friendly_name(self):
        variables = [
            {"id": "var_age_int", "name": "Patient Age", "type": "number"},
        ]
        resolver = VariableNameResolver(variables)
        assert resolver.get_friendly_name("var_age_int") == "Patient Age"


# --- ConditionCompiler Tests ---


class TestConditionCompiler:
    """Tests for condition compilation."""

    @pytest.fixture
    def resolver(self):
        variables = [
            {"id": "var_age_int", "name": "Age", "type": "number"},
            {"id": "var_name_string", "name": "Name", "type": "string"},
            {"id": "var_active_bool", "name": "Active", "type": "bool"},
            {"id": "var_price_float", "name": "Price", "type": "number"},
        ]
        return VariableNameResolver(variables)

    @pytest.fixture
    def compiler(self):
        return ConditionCompiler()

    # Numeric comparators
    def test_eq(self, compiler, resolver):
        condition = {"input_id": "var_age_int", "comparator": "eq", "value": 18}
        result = compiler.compile(condition, resolver)
        assert result == "age == 18"

    def test_neq(self, compiler, resolver):
        condition = {"input_id": "var_age_int", "comparator": "neq", "value": 0}
        result = compiler.compile(condition, resolver)
        assert result == "age != 0"

    def test_lt(self, compiler, resolver):
        condition = {"input_id": "var_age_int", "comparator": "lt", "value": 18}
        result = compiler.compile(condition, resolver)
        assert result == "age < 18"

    def test_lte(self, compiler, resolver):
        condition = {"input_id": "var_age_int", "comparator": "lte", "value": 65}
        result = compiler.compile(condition, resolver)
        assert result == "age <= 65"

    def test_gt(self, compiler, resolver):
        condition = {"input_id": "var_age_int", "comparator": "gt", "value": 21}
        result = compiler.compile(condition, resolver)
        assert result == "age > 21"

    def test_gte(self, compiler, resolver):
        condition = {"input_id": "var_age_int", "comparator": "gte", "value": 18}
        result = compiler.compile(condition, resolver)
        assert result == "age >= 18"

    def test_within_range(self, compiler, resolver):
        condition = {
            "input_id": "var_price_float",
            "comparator": "within_range",
            "value": 100,
            "value2": 500,
        }
        result = compiler.compile(condition, resolver)
        assert result == "100 <= price <= 500"

    # Boolean comparators
    def test_is_true(self, compiler, resolver):
        condition = {
            "input_id": "var_active_bool",
            "comparator": "is_true",
            "value": True,
        }
        result = compiler.compile(condition, resolver)
        assert result == "active is True"

    def test_is_false(self, compiler, resolver):
        condition = {
            "input_id": "var_active_bool",
            "comparator": "is_false",
            "value": False,
        }
        result = compiler.compile(condition, resolver)
        assert result == "active is False"

    # String comparators
    def test_str_eq(self, compiler, resolver):
        condition = {
            "input_id": "var_name_string",
            "comparator": "str_eq",
            "value": "John",
        }
        result = compiler.compile(condition, resolver)
        assert result == "name.lower() == 'John'.lower()"

    def test_str_contains(self, compiler, resolver):
        condition = {
            "input_id": "var_name_string",
            "comparator": "str_contains",
            "value": "@gmail",
        }
        result = compiler.compile(condition, resolver)
        assert result == "'@gmail'.lower() in name.lower()"

    def test_str_starts_with(self, compiler, resolver):
        condition = {
            "input_id": "var_name_string",
            "comparator": "str_starts_with",
            "value": "Dr.",
        }
        result = compiler.compile(condition, resolver)
        assert result == "name.lower().startswith('Dr.'.lower())"

    def test_str_ends_with(self, compiler, resolver):
        condition = {
            "input_id": "var_name_string",
            "comparator": "str_ends_with",
            "value": ".com",
        }
        result = compiler.compile(condition, resolver)
        assert result == "name.lower().endswith('.com'.lower())"

    # Error cases
    def test_missing_input_id(self, compiler, resolver):
        condition = {"comparator": "eq", "value": 5}
        with pytest.raises(CompilationError, match="missing 'input_id'"):
            compiler.compile(condition, resolver)

    def test_missing_comparator(self, compiler, resolver):
        condition = {"input_id": "var_age_int", "value": 5}
        with pytest.raises(CompilationError, match="missing 'comparator'"):
            compiler.compile(condition, resolver)

    def test_unknown_comparator(self, compiler, resolver):
        condition = {"input_id": "var_age_int", "comparator": "unknown_op", "value": 5}
        with pytest.raises(CompilationError, match="Unknown comparator"):
            compiler.compile(condition, resolver)

    # Compound condition tests
    def test_compound_and(self, compiler, resolver):
        condition = {
            "operator": "and",
            "conditions": [
                {"input_id": "var_age_int", "comparator": "gte", "value": 18},
                {"input_id": "var_active_bool", "comparator": "is_true", "value": True},
            ],
        }
        result = compiler.compile(condition, resolver)
        assert result == "(age >= 18 and active is True)"

    def test_compound_or(self, compiler, resolver):
        condition = {
            "operator": "or",
            "conditions": [
                {
                    "input_id": "var_name_string",
                    "comparator": "str_eq",
                    "value": "Admin",
                },
                {"input_id": "var_active_bool", "comparator": "is_true", "value": True},
            ],
        }
        result = compiler.compile(condition, resolver)
        assert result == "(name.lower() == 'Admin'.lower() or active is True)"

    def test_compound_three_conditions(self, compiler, resolver):
        condition = {
            "operator": "and",
            "conditions": [
                {"input_id": "var_age_int", "comparator": "gte", "value": 18},
                {"input_id": "var_age_int", "comparator": "lt", "value": 65},
                {"input_id": "var_active_bool", "comparator": "is_true", "value": True},
            ],
        }
        result = compiler.compile(condition, resolver)
        assert result == "(age >= 18 and age < 65 and active is True)"

    def test_compound_invalid_operator(self, compiler, resolver):
        condition = {
            "operator": "xor",
            "conditions": [
                {"input_id": "var_age_int", "comparator": "gte", "value": 18},
                {"input_id": "var_active_bool", "comparator": "is_true", "value": True},
            ],
        }
        with pytest.raises(CompilationError, match="must be 'and' or 'or'"):
            compiler.compile(condition, resolver)

    def test_compound_too_few_conditions(self, compiler, resolver):
        condition = {
            "operator": "and",
            "conditions": [
                {"input_id": "var_age_int", "comparator": "gte", "value": 18},
            ],
        }
        with pytest.raises(CompilationError, match="at least 2 items"):
            compiler.compile(condition, resolver)

    def test_compound_sub_condition_missing_input_id(self, compiler, resolver):
        condition = {
            "operator": "and",
            "conditions": [
                {"input_id": "var_age_int", "comparator": "gte", "value": 18},
                {"comparator": "is_true", "value": True},
            ],
        }
        with pytest.raises(CompilationError, match="missing 'input_id'"):
            compiler.compile(condition, resolver)


# --- PythonCodeGenerator Tests ---


class TestPythonCodeGenerator:
    """Tests for the main code generator."""

    def test_simple_workflow(self):
        """Test a simple start -> decision -> end workflow."""
        nodes = [
            {"id": "node_start", "type": "start", "label": "Start"},
            {
                "id": "node_decision",
                "type": "decision",
                "label": "Age Check",
                "condition": {
                    "input_id": "var_age_int",
                    "comparator": "gte",
                    "value": 18,
                },
            },
            {"id": "node_adult", "type": "end", "label": "Adult"},
            {"id": "node_minor", "type": "end", "label": "Minor"},
        ]
        edges = [
            {"from": "node_start", "to": "node_decision"},
            {"from": "node_decision", "to": "node_adult", "label": "true"},
            {"from": "node_decision", "to": "node_minor", "label": "false"},
        ]

        variables = [
            {"id": "var_age_int", "name": "Age", "type": "number", "source": "input"},
        ]

        generator = PythonCodeGenerator(
            nodes=nodes, edges=edges, variables=variables, workflow_name="Age Check"
        )
        result = generator.compile()

        assert result.success
        assert "def age_check(age: float)" in result.code
        assert "if age >= 18:" in result.code
        # Code uses single quotes for string literals
        assert "return 'Adult'" in result.code
        assert "return 'Minor'" in result.code

    def test_nested_decisions(self):
        """Test nested decision nodes."""
        nodes = [
            {"id": "node_start", "type": "start", "label": "Start"},
            {
                "id": "node_d1",
                "type": "decision",
                "label": "Check Age",
                "condition": {
                    "input_id": "var_age_int",
                    "comparator": "gte",
                    "value": 18,
                },
            },
            {
                "id": "node_d2",
                "type": "decision",
                "label": "Check Income",
                "condition": {
                    "input_id": "var_income_float",
                    "comparator": "gte",
                    "value": 50000,
                },
            },
            {"id": "node_approved", "type": "end", "label": "Approved"},
            {"id": "node_conditional", "type": "end", "label": "Conditional Approval"},
            {"id": "node_rejected", "type": "end", "label": "Rejected: Underage"},
        ]
        edges = [
            {"from": "node_start", "to": "node_d1"},
            {"from": "node_d1", "to": "node_d2", "label": "true"},
            {"from": "node_d1", "to": "node_rejected", "label": "false"},
            {"from": "node_d2", "to": "node_approved", "label": "true"},
            {"from": "node_d2", "to": "node_conditional", "label": "false"},
        ]
        variables = [
            {"id": "var_age_int", "name": "Age", "type": "number", "source": "input"},
            {
                "id": "var_income_float",
                "name": "Income",
                "type": "number",
                "source": "input",
            },
        ]

        generator = PythonCodeGenerator(
            nodes=nodes, edges=edges, variables=variables, workflow_name="Loan Approval"
        )
        result = generator.compile()

        assert result.success
        assert "def loan_approval(age: float, income: float)" in result.code
        assert "if age >= 18:" in result.code
        assert "if income >= 50000:" in result.code
        # Check indentation - nested if should be indented more
        lines = result.code.split("\n")
        income_line = [l for l in lines if "if income >= 50000" in l][0]
        assert income_line.startswith("        ")  # 8 spaces (2 levels)

    def test_output_template(self):
        """Test output node with template."""
        nodes = [
            {"id": "node_start", "type": "start", "label": "Start"},
            {
                "id": "node_end",
                "type": "end",
                "label": "Result",
                "output_template": "BMI is {BMI}",
            },
        ]
        edges = [{"from": "node_start", "to": "node_end"}]
        variables = [
            {"id": "var_bmi_float", "name": "BMI", "type": "number", "source": "input"},
        ]

        generator = PythonCodeGenerator(
            nodes=nodes, edges=edges, variables=variables, workflow_name="BMI Result"
        )
        result = generator.compile()

        assert result.success
        assert 'return f"BMI is {bmi}"' in result.code

    def test_empty_tree(self):
        """Test error handling for empty tree."""
        nodes = []
        edges = []
        variables = []

        generator = PythonCodeGenerator(nodes=nodes, edges=edges, variables=variables)
        result = generator.compile()

        assert not result.success
        assert "no nodes" in result.error

    def test_include_main_block(self):
        """Test including if __name__ == '__main__' block."""
        nodes = [
            {"id": "node_start", "type": "start", "label": "Start"},
            {"id": "node_end", "type": "end", "label": "Done"},
        ]
        edges = [{"from": "node_start", "to": "node_end"}]
        variables = [
            {"id": "var_age_int", "name": "Age", "type": "number", "source": "input"},
        ]

        # In compile_workflow_to_python, include_main logic is handled by setting include_main at compilation end
        # We need to test compile_workflow_to_python which has include_main
        result = compile_workflow_to_python(
            nodes=nodes, edges=edges, variables=variables, include_main=True
        )

        assert result.success
        assert 'if __name__ == "__main__":' in result.code
        assert "result = workflow(" in result.code

    def test_subprocess_warning(self):
        """Test that subprocess nodes generate warnings."""
        nodes = [
            {"id": "node_start", "type": "start", "label": "Start"},
            {
                "id": "node_sub",
                "type": "subprocess",
                "label": "Credit Check",
                "subworkflow_id": "wf_credit",
                "output_variable": "score",
            },
            {"id": "node_end", "type": "end", "label": "Complete"},
        ]
        edges = [
            {"from": "node_start", "to": "node_sub"},
            {"from": "node_sub", "to": "node_end"},
        ]
        variables = []

        generator = PythonCodeGenerator(nodes=nodes, edges=edges, variables=variables)
        result = generator.compile()

        assert result.success
        assert result.partial_failure is True
        assert len(result.warnings) > 0
        assert any("left as a comment" in w.lower() for w in result.warnings)
        assert "# Subprocess: Credit Check" in result.code
        assert "# TODO: Implement call to subworkflow 'wf_credit'" in result.code

    def test_compound_decision_workflow(self):
        """Test a workflow with a compound (AND) decision condition."""
        nodes = [
            {"id": "node_start", "type": "start", "label": "Start"},
            {
                "id": "node_decision",
                "type": "decision",
                "label": "Eligible?",
                "condition": {
                    "operator": "and",
                    "conditions": [
                        {"input_id": "var_age_int", "comparator": "gte", "value": 18},
                        {
                            "input_id": "var_active_bool",
                            "comparator": "is_true",
                            "value": True,
                        },
                    ],
                },
            },
            {"id": "node_yes", "type": "end", "label": "Approved"},
            {"id": "node_no", "type": "end", "label": "Rejected"},
        ]
        edges = [
            {"from": "node_start", "to": "node_decision"},
            {"from": "node_decision", "to": "node_yes", "label": "true"},
            {"from": "node_decision", "to": "node_no", "label": "false"},
        ]
        variables = [
            {"id": "var_age_int", "name": "Age", "type": "number", "source": "input"},
            {
                "id": "var_active_bool",
                "name": "Active",
                "type": "bool",
                "source": "input",
            },
        ]

        generator = PythonCodeGenerator(
            nodes=nodes, edges=edges, variables=variables, workflow_name="Eligibility"
        )
        result = generator.compile()

        assert result.success
        assert "(age >= 18 and active is True)" in result.code
        assert "return 'Approved'" in result.code
        assert "return 'Rejected'" in result.code


# --- compile_workflow_to_python Convenience Function Tests ---


class TestCompileWorkflowToPython:
    """Tests for the convenience function."""

    def test_basic_compilation(self):
        """Test compiling from nodes/edges format."""
        nodes = [
            {"id": "n1", "type": "start", "label": "Start", "x": 100, "y": 100},
            {
                "id": "n2",
                "type": "decision",
                "label": "Check",
                "x": 100,
                "y": 200,
                "condition": {
                    "input_id": "var_age_int",
                    "comparator": "gte",
                    "value": 18,
                },
            },
            {"id": "n3", "type": "end", "label": "Yes", "x": 50, "y": 300},
            {"id": "n4", "type": "end", "label": "No", "x": 150, "y": 300},
        ]
        edges = [
            {"from": "n1", "to": "n2", "label": ""},
            {"from": "n2", "to": "n3", "label": "true"},
            {"from": "n2", "to": "n4", "label": "false"},
        ]
        variables = [
            {"id": "var_age_int", "name": "Age", "type": "number", "source": "input"},
        ]

        result = compile_workflow_to_python(
            nodes=nodes,
            edges=edges,
            variables=variables,
            workflow_name="Test Workflow",
        )

        assert result.success
        assert "def test_workflow(age: float)" in result.code
        assert "if age >= 18:" in result.code

    def test_no_start_node(self):
        """Test handling when no start node exists.

        tree_from_flowchart picks any node as root if no start type exists,
        so this produces a valid but empty workflow.
        """
        nodes = [
            {"id": "n1", "type": "process", "label": "Process", "x": 100, "y": 100},
        ]
        edges = []
        variables = []

        result = compile_workflow_to_python(
            nodes=nodes,
            edges=edges,
            variables=variables,
        )

        # tree_from_flowchart uses first available node as root
        # which results in a workflow with pass (no continuation)
        assert result.success
        assert "pass" in result.code

    def test_empty_nodes(self):
        """Test error handling for empty nodes."""
        result = compile_workflow_to_python(
            nodes=[],
            edges=[],
            variables=[],
        )

        assert not result.success

    def test_end_node_output_variable_returns_computed_value(self):
        nodes = [
            {"id": "start", "type": "start", "label": "Start"},
            {
                "id": "calc",
                "type": "calculation",
                "label": "Add One",
                "calculation": {
                    "output": {"name": "Score"},
                    "operator": "add",
                    "operands": [
                        {"kind": "variable", "ref": "var_base_number"},
                        {"kind": "literal", "value": 1},
                    ],
                },
            },
            {
                "id": "end",
                "type": "end",
                "label": "Done",
                "output_variable": "Score",
                "output_type": "number",
            },
        ]
        edges = [
            {"from": "start", "to": "calc"},
            {"from": "calc", "to": "end"},
        ]
        variables = [
            {
                "id": "var_base_number",
                "name": "Base",
                "type": "number",
                "source": "input",
            }
        ]

        result = compile_workflow_to_python(
            nodes=nodes, edges=edges, variables=variables
        )

        assert result.success
        assert result.code is not None
        assert "return score" in result.code
        assert "return 'Done'" not in result.code

    def test_subprocess_mapping_uses_parent_values_not_literal_names(self):
        child_nodes = [
            {"id": "c_start", "type": "start", "label": "Start"},
            {
                "id": "c_end",
                "type": "end",
                "label": "Done",
                "output_variable": "Respiratory Rate",
                "output_type": "number",
            },
        ]
        child_edges = [{"from": "c_start", "to": "c_end"}]
        child_vars = [
            {
                "id": "var_rr_number",
                "name": "Respiratory Rate",
                "type": "number",
                "source": "input",
            }
        ]

        class Subflow:
            def __init__(self):
                self.nodes = child_nodes
                self.edges = child_edges
                self.inputs = child_vars
                self.outputs = [{"name": "result", "type": "number"}]

        root_nodes = [
            {"id": "start", "type": "start", "label": "Start"},
            {
                "id": "sub",
                "type": "subprocess",
                "label": "Child",
                "subworkflow_id": "wf_child",
                "input_mapping": {"Respiratory Rate": "Respiratory Rate"},
                "output_variable": "Child Result",
            },
            {
                "id": "end",
                "type": "end",
                "label": "Done",
                "output_variable": "Child Result",
                "output_type": "number",
            },
        ]
        root_edges = [
            {"from": "start", "to": "sub"},
            {"from": "sub", "to": "end"},
        ]
        root_vars = [
            {
                "id": "var_rr_number",
                "name": "Respiratory Rate",
                "type": "number",
                "source": "input",
            }
        ]

        result = compile_workflow_to_python(
            nodes=root_nodes,
            edges=root_edges,
            variables=root_vars,
            fetch_subworkflow=lambda workflow_id: (
                Subflow() if workflow_id == "wf_child" else None
            ),
        )

        assert result.success
        assert result.code is not None
        assert "respiratory_rate=respiratory_rate" in result.code
        assert "respiratory_rate='respiratory_rate'" not in result.code

    def test_compiled_subflow_matches_interpreter_output(self):
        child_nodes = [
            {"id": "c_start", "type": "start", "label": "Start"},
            {
                "id": "c_dec",
                "type": "decision",
                "label": "High?",
                "condition": {
                    "input_id": "var_score_number",
                    "comparator": "gte",
                    "value": 2,
                },
            },
            {
                "id": "c_high",
                "type": "end",
                "label": "High",
                "output_value": "high",
                "output_type": "string",
            },
            {
                "id": "c_low",
                "type": "end",
                "label": "Low",
                "output_value": "low",
                "output_type": "string",
            },
        ]
        child_edges = [
            {"from": "c_start", "to": "c_dec"},
            {"from": "c_dec", "to": "c_high", "label": "true"},
            {"from": "c_dec", "to": "c_low", "label": "false"},
        ]
        child_vars = [
            {
                "id": "var_score_number",
                "name": "Score",
                "type": "number",
                "source": "input",
            }
        ]

        class Subflow:
            def __init__(self):
                self.id = "wf_child"
                self.name = "Child"
                self.nodes = child_nodes
                self.edges = child_edges
                self.inputs = child_vars
                self.outputs = [{"name": "result", "type": "string"}]
                self.output_type = "string"
                self.tree = tree_from_flowchart(child_nodes, child_edges)

        root_nodes = [
            {"id": "start", "type": "start", "label": "Start"},
            {
                "id": "sub",
                "type": "subprocess",
                "label": "Child",
                "subworkflow_id": "wf_child",
                "input_mapping": {"Score": "Score"},
                "output_variable": "Child Result",
            },
            {
                "id": "end",
                "type": "end",
                "label": "Done",
                "output_variable": "Child Result",
                "output_type": "string",
            },
        ]
        root_edges = [
            {"from": "start", "to": "sub"},
            {"from": "sub", "to": "end"},
        ]
        root_vars = [
            {
                "id": "var_score_number",
                "name": "Score",
                "type": "number",
                "source": "input",
            }
        ]

        subflow = Subflow()
        root_tree = tree_from_flowchart(root_nodes, root_edges)
        interpreter = TreeInterpreter(
            tree=root_tree,
            variables=root_vars,
            outputs=[{"name": "result", "type": "string"}],
            workflow_id="wf_root",
            workflow_store=type(
                "Store",
                (),
                {
                    "get_workflow": staticmethod(
                        lambda workflow_id, user_id: (
                            subflow if workflow_id == "wf_child" else None
                        )
                    )
                },
            )(),
            user_id="user_1",
            output_type="string",
        )
        interpreted = interpreter.execute({"var_score_number": 3})

        compiled = compile_workflow_to_python(
            nodes=root_nodes,
            edges=root_edges,
            variables=root_vars,
            fetch_subworkflow=lambda workflow_id: (
                subflow if workflow_id == "wf_child" else None
            ),
            workflow_name="Parity Workflow",
        )

        assert interpreted.success
        assert compiled.success
        assert compiled.code is not None
        ast.parse(compiled.code)
        namespace = {}
        exec(compiled.code, namespace)
        python_result = namespace["parity_workflow"](3)

        assert python_result == interpreted.output == "high"

    def test_compiled_json_output_matches_interpreter(self):
        nodes = [
            {"id": "start", "type": "start", "label": "Start"},
            {
                "id": "end",
                "type": "end",
                "label": "Done",
                "output_value": {"severity": "high", "action": "icu"},
                "output_type": "json",
            },
        ]
        edges = [{"from": "start", "to": "end"}]
        tree = tree_from_flowchart(nodes, edges)
        interpreter = TreeInterpreter(
            tree=tree,
            variables=[],
            outputs=[{"name": "result", "type": "json"}],
            output_type="json",
        )
        interpreted = interpreter.execute({})

        compiled = compile_workflow_to_python(
            nodes=nodes,
            edges=edges,
            variables=[],
            workflow_name="Json Workflow",
        )

        assert interpreted.success
        assert compiled.success
        assert compiled.code is not None
        ast.parse(compiled.code)
        namespace = {}
        exec(compiled.code, namespace)
        python_result = namespace["json_workflow"]()

        assert (
            python_result == interpreted.output == {"severity": "high", "action": "icu"}
        )

    def test_unresolved_subprocess_mapping_produces_partial_failure_but_valid_python(
        self,
    ):
        child_nodes = [
            {"id": "c_start", "type": "start", "label": "Start"},
            {
                "id": "c_end",
                "type": "end",
                "label": "Done",
                "output_value": "ok",
                "output_type": "string",
            },
        ]
        child_edges = [{"from": "c_start", "to": "c_end"}]

        class Subflow:
            def __init__(self):
                self.nodes = child_nodes
                self.edges = child_edges
                self.inputs = [
                    {
                        "id": "var_known_number",
                        "name": "Known",
                        "type": "number",
                        "source": "input",
                    }
                ]
                self.outputs = [{"name": "result", "type": "string"}]

        root_nodes = [
            {"id": "start", "type": "start", "label": "Start"},
            {
                "id": "sub",
                "type": "subprocess",
                "label": "Child",
                "subworkflow_id": "wf_child",
                "input_mapping": {"Missing Parent": "Known"},
                "output_variable": "Child Result",
            },
            {
                "id": "end",
                "type": "end",
                "label": "Done",
                "output_variable": "Child Result",
                "output_type": "string",
            },
        ]
        root_edges = [{"from": "start", "to": "sub"}, {"from": "sub", "to": "end"}]

        compiled = compile_workflow_to_python(
            nodes=root_nodes,
            edges=root_edges,
            variables=[],
            fetch_subworkflow=lambda workflow_id: (
                Subflow() if workflow_id == "wf_child" else None
            ),
        )

        assert compiled.success
        assert compiled.partial_failure is True
        assert compiled.code is not None
        assert "known=None" in compiled.code
        ast.parse(compiled.code)

    def test_nested_subflow_export_has_single_import_block(self):
        grandchild_nodes = [
            {"id": "g_start", "type": "start", "label": "Start"},
            {
                "id": "g_end",
                "type": "end",
                "label": "Done",
                "output_value": "leaf",
                "output_type": "string",
            },
        ]
        grandchild_edges = [{"from": "g_start", "to": "g_end"}]

        child_nodes = [
            {"id": "c_start", "type": "start", "label": "Start"},
            {
                "id": "c_sub",
                "type": "subprocess",
                "label": "Grandchild",
                "subworkflow_id": "wf_grandchild",
                "input_mapping": {},
                "output_variable": "Leaf Result",
            },
            {
                "id": "c_end",
                "type": "end",
                "label": "Done",
                "output_variable": "Leaf Result",
                "output_type": "string",
            },
        ]
        child_edges = [
            {"from": "c_start", "to": "c_sub"},
            {"from": "c_sub", "to": "c_end"},
        ]

        class Workflow:
            def __init__(self, workflow_id, nodes, edges):
                self.id = workflow_id
                self.name = workflow_id
                self.nodes = nodes
                self.edges = edges
                self.inputs = []
                self.outputs = [{"name": "result", "type": "string"}]

        workflows = {
            "wf_child": Workflow("wf_child", child_nodes, child_edges),
            "wf_grandchild": Workflow(
                "wf_grandchild", grandchild_nodes, grandchild_edges
            ),
        }

        root_nodes = [
            {"id": "start", "type": "start", "label": "Start"},
            {
                "id": "sub",
                "type": "subprocess",
                "label": "Child",
                "subworkflow_id": "wf_child",
                "input_mapping": {},
                "output_variable": "Child Result",
            },
            {
                "id": "end",
                "type": "end",
                "label": "Done",
                "output_variable": "Child Result",
                "output_type": "string",
            },
        ]
        root_edges = [{"from": "start", "to": "sub"}, {"from": "sub", "to": "end"}]

        compiled = compile_workflow_to_python(
            nodes=root_nodes,
            edges=root_edges,
            variables=[],
            fetch_subworkflow=lambda workflow_id: workflows.get(workflow_id),
        )

        assert compiled.success
        assert compiled.code is not None
        assert (
            compiled.code.count(
                "from typing import Union, List, Dict, Any, Optional, Set, Callable"
            )
            == 1
        )
        assert compiled.code.count("import json") == 1
        ast.parse(compiled.code)

    def test_direct_subflow_cycle_generates_warning(self):
        class Workflow:
            def __init__(self, workflow_id, nodes):
                self.id = workflow_id
                self.name = workflow_id
                self.nodes = nodes
                self.edges = []
                self.inputs = []
                self.outputs = [{"name": "result", "type": "string"}]

        self_nodes = [
            {
                "id": "sub",
                "type": "subprocess",
                "label": "Self",
                "subworkflow_id": "wf_self",
                "input_mapping": {},
                "output_variable": "result",
            }
        ]
        workflow = Workflow("wf_self", self_nodes)

        compiled = compile_workflow_to_python(
            nodes=self_nodes,
            edges=[],
            variables=[],
            fetch_subworkflow=lambda workflow_id: (
                workflow if workflow_id == "wf_self" else None
            ),
        )

        assert compiled.success
        assert compiled.partial_failure is True
        assert any(
            "Recursive subflow cycle detected" in warning
            for warning in compiled.warnings
        )

    def test_indirect_subflow_cycle_generates_warning(self):
        class Workflow:
            def __init__(self, workflow_id, nodes):
                self.id = workflow_id
                self.name = workflow_id
                self.nodes = nodes
                self.edges = []
                self.inputs = []
                self.outputs = [{"name": "result", "type": "string"}]

        workflow_a = Workflow(
            "wf_a",
            [
                {
                    "id": "sub_a",
                    "type": "subprocess",
                    "label": "To B",
                    "subworkflow_id": "wf_b",
                    "input_mapping": {},
                    "output_variable": "result",
                }
            ],
        )
        workflow_b = Workflow(
            "wf_b",
            [
                {
                    "id": "sub_b",
                    "type": "subprocess",
                    "label": "To A",
                    "subworkflow_id": "wf_a",
                    "input_mapping": {},
                    "output_variable": "result",
                }
            ],
        )
        workflows = {"wf_a": workflow_a, "wf_b": workflow_b}

        compiled = compile_workflow_to_python(
            nodes=workflow_a.nodes,
            edges=[],
            variables=[],
            fetch_subworkflow=lambda workflow_id: workflows.get(workflow_id),
        )

        assert compiled.success
        assert compiled.partial_failure is True
        assert any(
            "wf_b -> wf_a -> wf_b" in warning or "wf_a -> wf_b -> wf_a" in warning
            for warning in compiled.warnings
        )


# --- DAG Compilation Tests ---


class TestDAGCompilation:
    """Tests for DAG-aware compilation (convergent branches)."""

    def test_diamond_dag_no_code_duplication(self):
        """Diamond DAG: decision branches converge on a shared end node.

        Expected output should have return ONCE after the if/else, not
        duplicated inside each branch.
        """
        nodes = [
            {"id": "start", "type": "start", "label": "Start"},
            {
                "id": "dec",
                "type": "decision",
                "label": "Check?",
                "condition": {"input_id": "var_x_bool", "comparator": "is_true"},
            },
            {"id": "a", "type": "process", "label": "Send Confirmation"},
            {"id": "b", "type": "process", "label": "Send Rejection"},
            {
                "id": "end",
                "type": "end",
                "label": "Complete",
                "output_value": "Done",
                "output_type": "string",
            },
        ]
        edges = [
            {"from": "start", "to": "dec"},
            {"from": "dec", "to": "a", "label": "true"},
            {"from": "dec", "to": "b", "label": "false"},
            {"from": "a", "to": "end"},
            {"from": "b", "to": "end"},
        ]
        variables = [
            {"id": "var_x_bool", "name": "X", "type": "bool", "source": "input"}
        ]

        result = compile_workflow_to_python(
            nodes=nodes, edges=edges, variables=variables
        )
        assert result.success

        # The return should appear exactly ONCE — after the if/else block
        assert result.code.count("return 'Done'") == 1

        # Process nodes should appear as print() calls
        assert "print('Send Confirmation')" in result.code
        assert "print('Send Rejection')" in result.code

    def test_process_nodes_generate_print(self):
        """Process nodes should emit print() statements."""
        nodes = [
            {"id": "start", "type": "start", "label": "Start"},
            {"id": "proc", "type": "process", "label": "Do Something"},
            {"id": "end", "type": "end", "label": "Done"},
        ]
        edges = [
            {"from": "start", "to": "proc"},
            {"from": "proc", "to": "end"},
        ]
        variables = []

        result = compile_workflow_to_python(
            nodes=nodes, edges=edges, variables=variables
        )
        assert result.success
        assert "print('Do Something')" in result.code

    def test_non_convergent_branches_return_independently(self):
        """When branches don't converge, each should return independently."""
        nodes = [
            {"id": "start", "type": "start", "label": "Start"},
            {
                "id": "dec",
                "type": "decision",
                "label": "Check?",
                "condition": {"input_id": "var_x_bool", "comparator": "is_true"},
            },
            {
                "id": "end_yes",
                "type": "end",
                "label": "Approved",
                "output_value": "Yes",
                "output_type": "string",
            },
            {
                "id": "end_no",
                "type": "end",
                "label": "Rejected",
                "output_value": "No",
                "output_type": "string",
            },
        ]
        edges = [
            {"from": "start", "to": "dec"},
            {"from": "dec", "to": "end_yes", "label": "true"},
            {"from": "dec", "to": "end_no", "label": "false"},
        ]
        variables = [
            {"id": "var_x_bool", "name": "X", "type": "bool", "source": "input"}
        ]

        result = compile_workflow_to_python(
            nodes=nodes, edges=edges, variables=variables
        )
        assert result.success
        assert "return 'Yes'" in result.code
        assert "return 'No'" in result.code

    def test_complex_dag_multiple_convergence_points(self):
        """Two sequential decisions, each with convergent branches.

        Start -> D1 -> A/B -> M -> D2 -> C/D -> End
        Both D1 and D2 have branches that converge.
        """
        nodes = [
            {"id": "start", "type": "start", "label": "Start"},
            {
                "id": "d1",
                "type": "decision",
                "label": "First?",
                "condition": {"input_id": "var_x_bool", "comparator": "is_true"},
            },
            {"id": "a", "type": "process", "label": "Path A"},
            {"id": "b", "type": "process", "label": "Path B"},
            {"id": "m", "type": "process", "label": "Middle"},
            {
                "id": "d2",
                "type": "decision",
                "label": "Second?",
                "condition": {"input_id": "var_y_bool", "comparator": "is_true"},
            },
            {"id": "c", "type": "process", "label": "Path C"},
            {"id": "d", "type": "process", "label": "Path D"},
            {
                "id": "end",
                "type": "end",
                "label": "Done",
                "output_value": "Complete",
                "output_type": "string",
            },
        ]
        edges = [
            {"from": "start", "to": "d1"},
            {"from": "d1", "to": "a", "label": "true"},
            {"from": "d1", "to": "b", "label": "false"},
            {"from": "a", "to": "m"},
            {"from": "b", "to": "m"},
            {"from": "m", "to": "d2"},
            {"from": "d2", "to": "c", "label": "true"},
            {"from": "d2", "to": "d", "label": "false"},
            {"from": "c", "to": "end"},
            {"from": "d", "to": "end"},
        ]
        variables = [
            {"id": "var_x_bool", "name": "X", "type": "bool", "source": "input"},
            {"id": "var_y_bool", "name": "Y", "type": "bool", "source": "input"},
        ]

        result = compile_workflow_to_python(
            nodes=nodes, edges=edges, variables=variables
        )
        assert result.success

        # Each node should be compiled exactly once
        assert result.code.count("print('Path A')") == 1
        assert result.code.count("print('Path B')") == 1
        assert result.code.count("print('Middle')") == 1
        assert result.code.count("print('Path C')") == 1
        assert result.code.count("print('Path D')") == 1
        assert result.code.count("return 'Complete'") == 1

    def test_three_path_convergence_handled_by_nesting(self):
        """When 3 paths converge on the same node via nested decisions,
        the post-dominator approach handles it through nested convergence
        — no helper extraction needed.

        Start -> D1 -> A -> D2 -> C/D -> Review -> End
                   \\-> B ---------> Review -> End
        Review has 3 incoming edges (B, C, D), but nested convergence
        resolves it: D1's IPDOM is Review, D2's branches stop before Review.
        """
        nodes = [
            {"id": "start", "type": "start", "label": "Start"},
            {
                "id": "d1",
                "type": "decision",
                "label": "First?",
                "condition": {"input_id": "var_x_bool", "comparator": "is_true"},
            },
            {"id": "a", "type": "process", "label": "Path A"},
            {"id": "b", "type": "process", "label": "Path B"},
            {
                "id": "d2",
                "type": "decision",
                "label": "Second?",
                "condition": {"input_id": "var_y_bool", "comparator": "is_true"},
            },
            {"id": "c", "type": "process", "label": "Path C"},
            {"id": "d", "type": "process", "label": "Path D"},
            {"id": "review", "type": "process", "label": "Standard Review"},
            {
                "id": "end",
                "type": "end",
                "label": "Done",
                "output_value": "Complete",
                "output_type": "string",
            },
        ]
        edges = [
            {"from": "start", "to": "d1"},
            {"from": "d1", "to": "a", "label": "true"},
            {"from": "d1", "to": "b", "label": "false"},
            {"from": "a", "to": "d2"},
            {"from": "d2", "to": "c", "label": "true"},
            {"from": "d2", "to": "d", "label": "false"},
            {"from": "b", "to": "review"},
            {"from": "c", "to": "review"},
            {"from": "d", "to": "review"},
            {"from": "review", "to": "end"},
        ]
        variables = [
            {"id": "var_x_bool", "name": "X", "type": "bool", "source": "input"},
            {"id": "var_y_bool", "name": "Y", "type": "bool", "source": "input"},
        ]

        result = compile_workflow_to_python(
            nodes=nodes, edges=edges, variables=variables
        )
        assert result.success

        # Each node compiled exactly once — post-dominator handles the 3-path convergence
        assert result.code.count("print('Standard Review')") == 1
        assert result.code.count("return 'Complete'") == 1
        assert result.code.count("print('Path A')") == 1
        assert result.code.count("print('Path B')") == 1
        assert result.code.count("print('Path C')") == 1
        assert result.code.count("print('Path D')") == 1

    def test_fixture_workflow_compiles_correctly(self):
        """Test the fixtures/workflow.json diamond DAG compiles correctly."""
        import json
        from pathlib import Path

        fixture_path = (
            Path(__file__).resolve().parent.parent.parent / "fixtures" / "workflow.json"
        )
        if not fixture_path.exists():
            pytest.skip("fixtures/workflow.json not found")

        with open(fixture_path) as f:
            data = json.load(f)

        result = compile_workflow_to_python(
            nodes=data["flowchart"]["nodes"],
            edges=data["flowchart"]["edges"],
            variables=data.get("variables", []),
            outputs=data.get("outputs"),
            include_main=True,
        )

        assert result.success

        # Process nodes should appear as print()
        assert "print('Send Confirmation')" in result.code
        assert "print('Send Rejection')" in result.code

        # Return should appear once (shared end node)
        assert result.code.count("return 'Complete'") == 1
