"""Tests for modify_workflow_variable tool."""

import pytest

from src.backend.tools.workflow_input.modify import ModifyWorkflowVariableTool


class TestModifyWorkflowVariableTool:
    """Tests for the modify_workflow_variable tool."""

    @pytest.fixture
    def tool(self):
        return ModifyWorkflowVariableTool()

    @pytest.fixture
    def session_with_variables(self):
        """Session state with input and subprocess-derived variables."""
        return {
            "workflow_analysis": {
                "variables": [
                    {
                        "id": "var_patient_age_int",
                        "name": "Patient Age",
                        "type": "int",
                        "source": "input",
                        "range": {"min": 0, "max": 120},
                    },
                    {
                        "id": "var_sub_bmi_string",  # Wrong type - should be float
                        "name": "BMI",
                        "type": "string",
                        "source": "subprocess",
                        "subworkflow_id": "wf_bmi_calc",
                    },
                    {
                        "id": "var_status_enum",
                        "name": "Status",
                        "type": "enum",
                        "source": "input",
                        "enum_values": ["Active", "Inactive"],
                    },
                ],
                "outputs": [],
            }
        }

    def test_change_subprocess_variable_type_from_string_to_float(self, tool, session_with_variables):
        """Should change a subprocess output variable from string to float."""
        result = tool.execute(
            {"name": "BMI", "new_type": "number"},
            session_state=session_with_variables,
        )

        assert result["success"] is True
        assert "type" in result["message"]
        
        # Check the variable was updated
        var = result["variable"]
        assert var["type"] == "float"
        assert var["id"] == "var_sub_bmi_float"  # ID should change with type
        assert var["source"] == "subprocess"  # Source should remain unchanged
        
        # Check warning about ID change
        assert result["old_id"] == "var_sub_bmi_string"
        assert result["new_id"] == "var_sub_bmi_float"
        assert "warning" in result

    def test_change_subprocess_variable_type_to_integer(self, tool, session_with_variables):
        """Should change a subprocess output variable to integer type."""
        result = tool.execute(
            {"name": "BMI", "new_type": "integer"},
            session_state=session_with_variables,
        )

        assert result["success"] is True
        var = result["variable"]
        assert var["type"] == "int"
        assert var["id"] == "var_sub_bmi_int"

    def test_change_input_variable_type(self, tool, session_with_variables):
        """Should change an input variable's type."""
        result = tool.execute(
            {"name": "Patient Age", "new_type": "number"},
            session_state=session_with_variables,
        )

        assert result["success"] is True
        var = result["variable"]
        assert var["type"] == "float"
        assert var["id"] == "var_patient_age_float"
        assert var["source"] == "input"

    def test_rename_variable(self, tool, session_with_variables):
        """Should rename a variable."""
        result = tool.execute(
            {"name": "Patient Age", "new_name": "Age"},
            session_state=session_with_variables,
        )

        assert result["success"] is True
        var = result["variable"]
        assert var["name"] == "Age"
        assert var["id"] == "var_age_int"  # ID reflects new name

    def test_add_range_to_variable(self, tool, session_with_variables):
        """Should add range constraints to a numeric variable."""
        # First change BMI to float
        tool.execute(
            {"name": "BMI", "new_type": "number"},
            session_state=session_with_variables,
        )
        
        # Then add range
        result = tool.execute(
            {"name": "BMI", "range_min": 10.0, "range_max": 50.0},
            session_state=session_with_variables,
        )

        assert result["success"] is True
        var = result["variable"]
        assert var["range"]["min"] == 10.0
        assert var["range"]["max"] == 50.0

    def test_update_enum_values(self, tool, session_with_variables):
        """Should update enum values."""
        result = tool.execute(
            {"name": "Status", "enum_values": ["Active", "Inactive", "Pending"]},
            session_state=session_with_variables,
        )

        assert result["success"] is True
        var = result["variable"]
        assert var["enum_values"] == ["Active", "Inactive", "Pending"]

    def test_change_to_enum_requires_values(self, tool, session_with_variables):
        """Should fail when changing to enum without providing enum_values."""
        result = tool.execute(
            {"name": "Patient Age", "new_type": "enum"},
            session_state=session_with_variables,
        )

        assert result["success"] is False
        assert "enum_values" in result["error"]

    def test_range_only_valid_for_numeric_types(self, tool, session_with_variables):
        """Should fail when setting range on non-numeric type."""
        result = tool.execute(
            {"name": "Status", "range_min": 0, "range_max": 100},
            session_state=session_with_variables,
        )

        assert result["success"] is False
        assert "number" in result["error"].lower() or "numeric" in result["error"].lower()

    def test_variable_not_found(self, tool, session_with_variables):
        """Should fail with helpful error when variable not found."""
        result = tool.execute(
            {"name": "NonExistent", "new_type": "string"},
            session_state=session_with_variables,
        )

        assert result["success"] is False
        assert "not found" in result["error"]
        # Should list available variables
        assert "Patient Age" in result["error"] or "BMI" in result["error"]

    def test_case_insensitive_name_match(self, tool, session_with_variables):
        """Should match variable names case-insensitively."""
        result = tool.execute(
            {"name": "patient age", "new_type": "number"},
            session_state=session_with_variables,
        )

        assert result["success"] is True
        assert result["variable"]["name"] == "Patient Age"

    def test_no_changes_returns_success(self, tool, session_with_variables):
        """Should succeed with no changes if nothing to change."""
        result = tool.execute(
            {"name": "Patient Age"},  # No changes specified
            session_state=session_with_variables,
        )

        assert result["success"] is True
        assert "No changes" in result["message"]

    def test_invalid_type_rejected(self, tool, session_with_variables):
        """Should reject invalid type values."""
        result = tool.execute(
            {"name": "Patient Age", "new_type": "invalid_type"},
            session_state=session_with_variables,
        )

        assert result["success"] is False
        assert "Invalid type" in result["error"]

    def test_duplicate_name_rejected(self, tool, session_with_variables):
        """Should reject renaming to an existing variable name."""
        result = tool.execute(
            {"name": "Patient Age", "new_name": "BMI"},  # BMI already exists
            session_state=session_with_variables,
        )

        assert result["success"] is False
        assert "already exists" in result["error"]

    def test_workflow_analysis_updated_in_session(self, tool, session_with_variables):
        """Should return updated workflow_analysis for state sync."""
        result = tool.execute(
            {"name": "BMI", "new_type": "integer"},
            session_state=session_with_variables,
        )

        assert result["success"] is True
        assert "workflow_analysis" in result
        
        # Find BMI in the returned analysis
        variables = result["workflow_analysis"]["variables"]
        bmi_var = next((v for v in variables if v["name"] == "BMI"), None)
        assert bmi_var is not None
        assert bmi_var["type"] == "int"
        assert bmi_var["id"] == "var_sub_bmi_int"
