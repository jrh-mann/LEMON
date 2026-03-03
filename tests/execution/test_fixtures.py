"""Tests to validate the test fixtures themselves"""

import pytest
from .fixtures import (
    SIMPLE_AGE_WORKFLOW,
    CHOLESTEROL_RISK_WORKFLOW,
    MEDICATION_WORKFLOW,
    BMI_CLASSIFICATION_WORKFLOW,
    ELIGIBILITY_WORKFLOW,
    get_all_workflow_tests,
)


class TestFixtureValidity:
    """Validate that test fixtures follow the correct schema"""

    @pytest.mark.parametrize("workflow", [
        SIMPLE_AGE_WORKFLOW,
        CHOLESTEROL_RISK_WORKFLOW,
        MEDICATION_WORKFLOW,
        BMI_CLASSIFICATION_WORKFLOW,
        ELIGIBILITY_WORKFLOW,
    ])
    def test_workflow_has_required_keys(self, workflow):
        """Test that workflow has inputs, outputs, tree"""
        assert "inputs" in workflow
        assert "outputs" in workflow
        assert "tree" in workflow
        assert isinstance(workflow["inputs"], list)
        assert isinstance(workflow["outputs"], list)
        assert isinstance(workflow["tree"], dict)

    @pytest.mark.parametrize("workflow", [
        SIMPLE_AGE_WORKFLOW,
        CHOLESTEROL_RISK_WORKFLOW,
        MEDICATION_WORKFLOW,
        BMI_CLASSIFICATION_WORKFLOW,
        ELIGIBILITY_WORKFLOW,
    ])
    def test_tree_has_start_node(self, workflow):
        """Test that tree has a start node"""
        assert "start" in workflow["tree"]
        start = workflow["tree"]["start"]
        assert start["id"] == "start"
        assert start["type"] == "start"

    @pytest.mark.parametrize("workflow", [
        SIMPLE_AGE_WORKFLOW,
        CHOLESTEROL_RISK_WORKFLOW,
        MEDICATION_WORKFLOW,
        BMI_CLASSIFICATION_WORKFLOW,
        ELIGIBILITY_WORKFLOW,
    ])
    def test_all_nodes_have_required_fields(self, workflow):
        """Test that all nodes have id, type, label"""
        def check_node(node):
            assert "id" in node
            assert "type" in node
            assert "label" in node
            for child in node.get("children", []):
                check_node(child)

        check_node(workflow["tree"]["start"])

    @pytest.mark.parametrize("workflow", [
        SIMPLE_AGE_WORKFLOW,
        CHOLESTEROL_RISK_WORKFLOW,
        MEDICATION_WORKFLOW,
        BMI_CLASSIFICATION_WORKFLOW,
        ELIGIBILITY_WORKFLOW,
    ])
    def test_decision_nodes_have_children(self, workflow):
        """Test that decision nodes have children"""
        def check_node(node):
            if node["type"] == "decision":
                assert "children" in node
                assert len(node["children"]) > 0
            for child in node.get("children", []):
                check_node(child)

        check_node(workflow["tree"]["start"])

    @pytest.mark.parametrize("workflow", [
        SIMPLE_AGE_WORKFLOW,
        CHOLESTEROL_RISK_WORKFLOW,
        MEDICATION_WORKFLOW,
        BMI_CLASSIFICATION_WORKFLOW,
        ELIGIBILITY_WORKFLOW,
    ])
    def test_output_nodes_have_no_children(self, workflow):
        """Test that output nodes are leaf nodes"""
        def check_node(node):
            if node["type"] == "output":
                assert node.get("children", []) == []
            for child in node.get("children", []):
                check_node(child)

        check_node(workflow["tree"]["start"])

    @pytest.mark.parametrize("workflow", [
        SIMPLE_AGE_WORKFLOW,
        CHOLESTEROL_RISK_WORKFLOW,
        MEDICATION_WORKFLOW,
        BMI_CLASSIFICATION_WORKFLOW,
        ELIGIBILITY_WORKFLOW,
    ])
    def test_all_input_ids_are_valid(self, workflow):
        """Test that all input_ids reference actual inputs"""
        valid_ids = {inp["id"] for inp in workflow["inputs"]}

        def check_node(node):
            for input_id in node.get("input_ids", []):
                assert input_id in valid_ids, f"Invalid input_id: {input_id}"
            for child in node.get("children", []):
                check_node(child)

        check_node(workflow["tree"]["start"])

    @pytest.mark.parametrize("workflow", [
        SIMPLE_AGE_WORKFLOW,
        CHOLESTEROL_RISK_WORKFLOW,
        MEDICATION_WORKFLOW,
        BMI_CLASSIFICATION_WORKFLOW,
        ELIGIBILITY_WORKFLOW,
    ])
    def test_inputs_have_required_fields(self, workflow):
        """Test that inputs have id, name, type"""
        for inp in workflow["inputs"]:
            assert "id" in inp
            assert "name" in inp
            assert "type" in inp
            assert inp["type"] in ["number", "bool", "string", "enum", "date"]

    @pytest.mark.parametrize("workflow", [
        SIMPLE_AGE_WORKFLOW,
        CHOLESTEROL_RISK_WORKFLOW,
        MEDICATION_WORKFLOW,
        BMI_CLASSIFICATION_WORKFLOW,
        ELIGIBILITY_WORKFLOW,
    ])
    def test_enum_inputs_have_enum_values(self, workflow):
        """Test that enum type inputs have enum_values"""
        for inp in workflow["inputs"]:
            if inp["type"] == "enum":
                assert "enum_values" in inp
                assert isinstance(inp["enum_values"], list)
                assert len(inp["enum_values"]) > 0

    @pytest.mark.parametrize("workflow", [
        SIMPLE_AGE_WORKFLOW,
        CHOLESTEROL_RISK_WORKFLOW,
        MEDICATION_WORKFLOW,
        BMI_CLASSIFICATION_WORKFLOW,
        ELIGIBILITY_WORKFLOW,
    ])
    def test_workflow_has_at_least_one_output_node(self, workflow):
        """Test that workflow has at least one output node"""
        def count_outputs(node):
            count = 1 if node["type"] == "output" else 0
            for child in node.get("children", []):
                count += count_outputs(child)
            return count

        output_count = count_outputs(workflow["tree"]["start"])
        assert output_count > 0

    def test_get_all_workflow_tests_returns_valid_data(self):
        """Test that helper function returns correct structure"""
        tests = get_all_workflow_tests()
        assert len(tests) == 5
        for workflow, test_cases, name in tests:
            assert isinstance(workflow, dict)
            assert isinstance(test_cases, list)
            assert isinstance(name, str)
            assert len(test_cases) > 0


class TestFixtureTestCases:
    """Validate that test cases are well-formed"""

    @pytest.mark.parametrize("workflow,test_cases,name", get_all_workflow_tests())
    def test_test_cases_have_correct_structure(self, workflow, test_cases, name):
        """Test that each test case is a (inputs, expected_output, description) tuple"""
        for test_case in test_cases:
            assert len(test_case) == 3
            inputs, expected_output, description = test_case
            assert isinstance(inputs, dict)
            assert isinstance(expected_output, str)
            assert isinstance(description, str)

    @pytest.mark.parametrize("workflow,test_cases,name", get_all_workflow_tests())
    def test_test_cases_reference_valid_input_ids(self, workflow, test_cases, name):
        """Test that test case inputs use valid input IDs"""
        valid_ids = {inp["id"] for inp in workflow["inputs"]}
        for inputs, _, _ in test_cases:
            for input_id in inputs.keys():
                assert input_id in valid_ids, f"{name}: Invalid input_id '{input_id}'"

    @pytest.mark.parametrize("workflow,test_cases,name", get_all_workflow_tests())
    def test_test_cases_provide_all_required_inputs(self, workflow, test_cases, name):
        """Test that test cases provide all required inputs"""
        required_ids = {inp["id"] for inp in workflow["inputs"]}
        for inputs, _, description in test_cases:
            for required_id in required_ids:
                assert required_id in inputs, f"{name} - {description}: Missing input '{required_id}'"

    @pytest.mark.parametrize("workflow,test_cases,name", get_all_workflow_tests())
    def test_expected_outputs_are_valid(self, workflow, test_cases, name):
        """Test that expected outputs match workflow output names"""
        valid_outputs = {out["name"] for out in workflow["outputs"]}
        for _, expected_output, description in test_cases:
            assert expected_output in valid_outputs, \
                f"{name} - {description}: Invalid output '{expected_output}'"

    @pytest.mark.parametrize("workflow,test_cases,name", get_all_workflow_tests())
    def test_input_values_match_types(self, workflow, test_cases, name):
        """Test that input values have correct Python types"""
        input_types = {inp["id"]: inp["type"] for inp in workflow["inputs"]}

        for inputs, _, description in test_cases:
            for input_id, value in inputs.items():
                expected_type = input_types[input_id]

                if expected_type == "number":
                    assert isinstance(value, (int, float)), \
                        f"{name} - {description}: {input_id} should be number, got {type(value)}"
                elif expected_type == "bool":
                    assert isinstance(value, bool), \
                        f"{name} - {description}: {input_id} should be bool, got {type(value)}"
                elif expected_type in ("string", "enum"):
                    assert isinstance(value, str), \
                        f"{name} - {description}: {input_id} should be str, got {type(value)}"

    @pytest.mark.parametrize("workflow,test_cases,name", get_all_workflow_tests())
    def test_enum_values_are_valid(self, workflow, test_cases, name):
        """Test that enum input values are in allowed list"""
        enum_inputs = {
            inp["id"]: inp["enum_values"]
            for inp in workflow["inputs"]
            if inp["type"] == "enum"
        }

        for inputs, _, description in test_cases:
            for input_id, value in inputs.items():
                if input_id in enum_inputs:
                    allowed = enum_inputs[input_id]
                    assert value in allowed, \
                        f"{name} - {description}: {input_id}='{value}' not in {allowed}"

    @pytest.mark.parametrize("workflow,test_cases,name", get_all_workflow_tests())
    def test_numeric_values_in_range(self, workflow, test_cases, name):
        """Test that numeric values are within specified ranges"""
        input_ranges = {
            inp["id"]: inp.get("range")
            for inp in workflow["inputs"]
            if inp["type"] == "number"
        }

        for inputs, _, description in test_cases:
            for input_id, value in inputs.items():
                if input_id in input_ranges and input_ranges[input_id]:
                    range_spec = input_ranges[input_id]
                    if "min" in range_spec:
                        assert value >= range_spec["min"], \
                            f"{name} - {description}: {input_id}={value} below min {range_spec['min']}"
                    if "max" in range_spec:
                        assert value <= range_spec["max"], \
                            f"{name} - {description}: {input_id}={value} above max {range_spec['max']}"
