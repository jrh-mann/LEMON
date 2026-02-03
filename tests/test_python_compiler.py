"""Tests for the Python code generator (python_compiler.py)."""

import pytest
from src.backend.execution.python_compiler import (
    PythonCodeGenerator,
    CompilationResult,
    CompilationError,
    VariableNameResolver,
    ConditionCompiler,
    compile_workflow_to_python,
)


# --- VariableNameResolver Tests ---


class TestVariableNameResolver:
    """Tests for variable name resolution."""

    def test_simple_name_conversion(self):
        variables = [
            {"id": "var_patient_age_int", "name": "Patient Age", "type": "int"},
        ]
        resolver = VariableNameResolver(variables)
        assert resolver.resolve("var_patient_age_int") == "patient_age"

    def test_multiple_variables(self):
        variables = [
            {"id": "var_age_int", "name": "Age", "type": "int"},
            {"id": "var_income_float", "name": "Income", "type": "float"},
            {"id": "var_active_bool", "name": "Active", "type": "bool"},
        ]
        resolver = VariableNameResolver(variables)
        assert resolver.resolve("var_age_int") == "age"
        assert resolver.resolve("var_income_float") == "income"
        assert resolver.resolve("var_active_bool") == "active"

    def test_name_conflict_resolution(self):
        variables = [
            {"id": "var_age_int", "name": "Age", "type": "int"},
            {"id": "var_age_float", "name": "Age", "type": "float"},
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
            {"id": "var_age_int", "name": "Age", "type": "int"},
            {"id": "var_price_float", "name": "Price", "type": "float"},
            {"id": "var_name_string", "name": "Name", "type": "string"},
        ]
        resolver = VariableNameResolver(variables)
        assert resolver.get_type("var_age_int") == "int"
        assert resolver.get_type("var_price_float") == "float"
        assert resolver.get_type("var_name_string") == "str"

    def test_get_friendly_name(self):
        variables = [
            {"id": "var_age_int", "name": "Patient Age", "type": "int"},
        ]
        resolver = VariableNameResolver(variables)
        assert resolver.get_friendly_name("var_age_int") == "Patient Age"


# --- ConditionCompiler Tests ---


class TestConditionCompiler:
    """Tests for condition compilation."""

    @pytest.fixture
    def resolver(self):
        variables = [
            {"id": "var_age_int", "name": "Age", "type": "int"},
            {"id": "var_name_string", "name": "Name", "type": "string"},
            {"id": "var_active_bool", "name": "Active", "type": "bool"},
            {"id": "var_price_float", "name": "Price", "type": "float"},
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
        condition = {"input_id": "var_active_bool", "comparator": "is_true", "value": True}
        result = compiler.compile(condition, resolver)
        assert result == "active is True"

    def test_is_false(self, compiler, resolver):
        condition = {"input_id": "var_active_bool", "comparator": "is_false", "value": False}
        result = compiler.compile(condition, resolver)
        assert result == "active is False"

    # String comparators
    def test_str_eq(self, compiler, resolver):
        condition = {"input_id": "var_name_string", "comparator": "str_eq", "value": "John"}
        result = compiler.compile(condition, resolver)
        assert result == "name.lower() == 'John'.lower()"

    def test_str_contains(self, compiler, resolver):
        condition = {"input_id": "var_name_string", "comparator": "str_contains", "value": "@gmail"}
        result = compiler.compile(condition, resolver)
        assert result == "'@gmail'.lower() in name.lower()"

    def test_str_starts_with(self, compiler, resolver):
        condition = {"input_id": "var_name_string", "comparator": "str_starts_with", "value": "Dr."}
        result = compiler.compile(condition, resolver)
        assert result == "name.lower().startswith('Dr.'.lower())"

    def test_str_ends_with(self, compiler, resolver):
        condition = {"input_id": "var_name_string", "comparator": "str_ends_with", "value": ".com"}
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


# --- PythonCodeGenerator Tests ---


class TestPythonCodeGenerator:
    """Tests for the main code generator."""

    def test_simple_workflow(self):
        """Test a simple start -> decision -> end workflow."""
        tree = {
            "start": {
                "id": "node_start",
                "type": "start",
                "label": "Start",
                "children": [
                    {
                        "id": "node_decision",
                        "type": "decision",
                        "label": "Age Check",
                        "condition": {
                            "input_id": "var_age_int",
                            "comparator": "gte",
                            "value": 18,
                        },
                        "children": [
                            {
                                "id": "node_adult",
                                "type": "end",
                                "label": "Adult",
                                "edge_label": "true",
                            },
                            {
                                "id": "node_minor",
                                "type": "end",
                                "label": "Minor",
                                "edge_label": "false",
                            },
                        ],
                    }
                ],
            }
        }
        variables = [
            {"id": "var_age_int", "name": "Age", "type": "int", "source": "input"},
        ]

        generator = PythonCodeGenerator()
        result = generator.compile(tree, variables, workflow_name="Age Check")

        assert result.success
        assert "def age_check(age: int)" in result.code
        assert "if age >= 18:" in result.code
        # Code uses single quotes for string literals
        assert "return 'Adult'" in result.code
        assert "return 'Minor'" in result.code

    def test_nested_decisions(self):
        """Test nested decision nodes."""
        tree = {
            "start": {
                "id": "node_start",
                "type": "start",
                "label": "Start",
                "children": [
                    {
                        "id": "node_d1",
                        "type": "decision",
                        "label": "Check Age",
                        "condition": {
                            "input_id": "var_age_int",
                            "comparator": "gte",
                            "value": 18,
                        },
                        "children": [
                            {
                                "id": "node_d2",
                                "type": "decision",
                                "label": "Check Income",
                                "edge_label": "true",
                                "condition": {
                                    "input_id": "var_income_float",
                                    "comparator": "gte",
                                    "value": 50000,
                                },
                                "children": [
                                    {
                                        "id": "node_approved",
                                        "type": "end",
                                        "label": "Approved",
                                        "edge_label": "true",
                                    },
                                    {
                                        "id": "node_conditional",
                                        "type": "end",
                                        "label": "Conditional Approval",
                                        "edge_label": "false",
                                    },
                                ],
                            },
                            {
                                "id": "node_rejected",
                                "type": "end",
                                "label": "Rejected: Underage",
                                "edge_label": "false",
                            },
                        ],
                    }
                ],
            }
        }
        variables = [
            {"id": "var_age_int", "name": "Age", "type": "int", "source": "input"},
            {"id": "var_income_float", "name": "Income", "type": "float", "source": "input"},
        ]

        generator = PythonCodeGenerator()
        result = generator.compile(tree, variables, workflow_name="Loan Approval")

        assert result.success
        assert "def loan_approval(age: int, income: float)" in result.code
        assert "if age >= 18:" in result.code
        assert "if income >= 50000:" in result.code
        # Check indentation - nested if should be indented more
        lines = result.code.split("\n")
        income_line = [l for l in lines if "if income >= 50000" in l][0]
        assert income_line.startswith("        ")  # 8 spaces (2 levels)

    def test_output_template(self):
        """Test output node with template."""
        tree = {
            "start": {
                "id": "node_start",
                "type": "start",
                "label": "Start",
                "children": [
                    {
                        "id": "node_end",
                        "type": "end",
                        "label": "Result",
                        "output_template": "BMI is {BMI}",
                    }
                ],
            }
        }
        variables = [
            {"id": "var_bmi_float", "name": "BMI", "type": "float", "source": "input"},
        ]

        generator = PythonCodeGenerator()
        result = generator.compile(tree, variables, workflow_name="BMI Result")

        assert result.success
        assert 'return f"BMI is {bmi}"' in result.code

    def test_empty_tree(self):
        """Test error handling for empty tree."""
        tree = {}
        variables = []

        generator = PythonCodeGenerator()
        result = generator.compile(tree, variables)

        assert not result.success
        assert "missing 'start'" in result.error

    def test_include_main_block(self):
        """Test including if __name__ == '__main__' block."""
        tree = {
            "start": {
                "id": "node_start",
                "type": "start",
                "label": "Start",
                "children": [
                    {
                        "id": "node_end",
                        "type": "end",
                        "label": "Done",
                    }
                ],
            }
        }
        variables = [
            {"id": "var_age_int", "name": "Age", "type": "int", "source": "input"},
        ]

        generator = PythonCodeGenerator()
        result = generator.compile(tree, variables, include_main=True)

        assert result.success
        assert 'if __name__ == "__main__":' in result.code
        assert "result = workflow(0)" in result.code

    def test_subprocess_warning(self):
        """Test that subprocess nodes generate warnings."""
        tree = {
            "start": {
                "id": "node_start",
                "type": "start",
                "label": "Start",
                "children": [
                    {
                        "id": "node_sub",
                        "type": "subprocess",
                        "label": "Credit Check",
                        "subworkflow_id": "wf_credit",
                        "output_variable": "score",
                        "children": [
                            {
                                "id": "node_end",
                                "type": "end",
                                "label": "Complete",
                            }
                        ],
                    }
                ],
            }
        }
        variables = []

        generator = PythonCodeGenerator()
        result = generator.compile(tree, variables)

        assert result.success
        assert len(result.warnings) > 0
        assert any("subprocess" in w.lower() for w in result.warnings)
        assert "# Subprocess: Credit Check" in result.code


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
            {"id": "var_age_int", "name": "Age", "type": "int", "source": "input"},
        ]

        result = compile_workflow_to_python(
            nodes=nodes,
            edges=edges,
            variables=variables,
            workflow_name="Test Workflow",
        )

        assert result.success
        assert "def test_workflow(age: int)" in result.code
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
