"""Tests for modify_workflow_variable tool.

All workflow tools now require workflow_id parameter - workflows must be created first
using create_workflow, then tools operate on them by ID with auto-save to database.
"""

import pytest
from src.backend.tools.workflow_input.modify import ModifyWorkflowVariableTool
from tests.conftest import make_session_with_workflow


class TestModifyWorkflowVariableTool:
    """Tests for the modify_workflow_variable tool."""

    @pytest.fixture
    def tool(self):
        return ModifyWorkflowVariableTool()

    @pytest.fixture
    def test_variables(self):
        """Base variables for tests."""
        return [
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
        ]

    def test_change_subprocess_variable_type_from_string_to_float(
        self, tool, workflow_store, test_user_id, test_variables
    ):
        """Should change a subprocess output variable from string to float."""
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, variables=test_variables
        )

        result = tool.execute(
            {"workflow_id": workflow_id, "name": "BMI", "new_type": "number"},
            session_state=session,
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

    def test_change_subprocess_variable_type_to_integer(
        self, tool, workflow_store, test_user_id, test_variables
    ):
        """Should change a subprocess output variable to integer type."""
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, variables=test_variables
        )

        result = tool.execute(
            {"workflow_id": workflow_id, "name": "BMI", "new_type": "integer"},
            session_state=session,
        )

        assert result["success"] is True
        var = result["variable"]
        assert var["type"] == "int"
        assert var["id"] == "var_sub_bmi_int"

    def test_change_input_variable_type(
        self, tool, workflow_store, test_user_id, test_variables
    ):
        """Should change an input variable's type."""
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, variables=test_variables
        )

        result = tool.execute(
            {"workflow_id": workflow_id, "name": "Patient Age", "new_type": "number"},
            session_state=session,
        )

        assert result["success"] is True
        var = result["variable"]
        assert var["type"] == "float"
        assert var["id"] == "var_patient_age_float"
        assert var["source"] == "input"

    def test_rename_variable(self, tool, workflow_store, test_user_id, test_variables):
        """Should rename a variable."""
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, variables=test_variables
        )

        result = tool.execute(
            {"workflow_id": workflow_id, "name": "Patient Age", "new_name": "Age"},
            session_state=session,
        )

        assert result["success"] is True
        var = result["variable"]
        assert var["name"] == "Age"
        assert var["id"] == "var_age_int"  # ID reflects new name

    def test_add_range_to_variable(self, tool, workflow_store, test_user_id, test_variables):
        """Should add range constraints to a numeric variable."""
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, variables=test_variables
        )

        # First change BMI to float
        tool.execute(
            {"workflow_id": workflow_id, "name": "BMI", "new_type": "number"},
            session_state=session,
        )
        
        # Then add range
        result = tool.execute(
            {"workflow_id": workflow_id, "name": "BMI", "range_min": 10.0, "range_max": 50.0},
            session_state=session,
        )

        assert result["success"] is True
        var = result["variable"]
        assert var["range"]["min"] == 10.0
        assert var["range"]["max"] == 50.0

    def test_update_enum_values(self, tool, workflow_store, test_user_id, test_variables):
        """Should update enum values."""
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, variables=test_variables
        )

        result = tool.execute(
            {"workflow_id": workflow_id, "name": "Status", "enum_values": ["Active", "Inactive", "Pending"]},
            session_state=session,
        )

        assert result["success"] is True
        var = result["variable"]
        assert var["enum_values"] == ["Active", "Inactive", "Pending"]

    def test_change_to_enum_requires_values(self, tool, workflow_store, test_user_id, test_variables):
        """Should fail when changing to enum without providing enum_values."""
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, variables=test_variables
        )

        result = tool.execute(
            {"workflow_id": workflow_id, "name": "Patient Age", "new_type": "enum"},
            session_state=session,
        )

        assert result["success"] is False
        assert "enum_values" in result["error"]

    def test_range_only_valid_for_numeric_types(self, tool, workflow_store, test_user_id, test_variables):
        """Should fail when setting range on non-numeric type."""
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, variables=test_variables
        )

        result = tool.execute(
            {"workflow_id": workflow_id, "name": "Status", "range_min": 0, "range_max": 100},
            session_state=session,
        )

        assert result["success"] is False
        assert "number" in result["error"].lower() or "numeric" in result["error"].lower()

    def test_variable_not_found(self, tool, workflow_store, test_user_id, test_variables):
        """Should fail with helpful error when variable not found."""
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, variables=test_variables
        )

        result = tool.execute(
            {"workflow_id": workflow_id, "name": "NonExistent", "new_type": "string"},
            session_state=session,
        )

        assert result["success"] is False
        assert "not found" in result["error"]
        # Should list available variables
        assert "Patient Age" in result["error"] or "BMI" in result["error"]

    def test_case_insensitive_name_match(self, tool, workflow_store, test_user_id, test_variables):
        """Should match variable names case-insensitively."""
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, variables=test_variables
        )

        result = tool.execute(
            {"workflow_id": workflow_id, "name": "patient age", "new_type": "number"},
            session_state=session,
        )

        assert result["success"] is True
        assert result["variable"]["name"] == "Patient Age"

    def test_no_changes_returns_success(self, tool, workflow_store, test_user_id, test_variables):
        """Should succeed with no changes if nothing to change."""
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, variables=test_variables
        )

        result = tool.execute(
            {"workflow_id": workflow_id, "name": "Patient Age"},  # No changes specified
            session_state=session,
        )

        assert result["success"] is True
        assert "No changes" in result["message"]

    def test_invalid_type_rejected(self, tool, workflow_store, test_user_id, test_variables):
        """Should reject invalid type values."""
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, variables=test_variables
        )

        result = tool.execute(
            {"workflow_id": workflow_id, "name": "Patient Age", "new_type": "invalid_type"},
            session_state=session,
        )

        assert result["success"] is False
        assert "Invalid type" in result["error"]

    def test_duplicate_name_rejected(self, tool, workflow_store, test_user_id, test_variables):
        """Should reject renaming to an existing variable name."""
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, variables=test_variables
        )

        result = tool.execute(
            {"workflow_id": workflow_id, "name": "Patient Age", "new_name": "BMI"},  # BMI already exists
            session_state=session,
        )

        assert result["success"] is False
        assert "already exists" in result["error"]

    def test_workflow_id_returns_in_result(self, tool, workflow_store, test_user_id, test_variables):
        """Should return workflow_id in result for state tracking."""
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, variables=test_variables
        )

        result = tool.execute(
            {"workflow_id": workflow_id, "name": "BMI", "new_type": "integer"},
            session_state=session,
        )

        assert result["success"] is True
        assert result["workflow_id"] == workflow_id
        
        # Verify update persisted by reloading from database
        record = workflow_store.get_workflow(workflow_id, test_user_id)
        bmi_var = next((v for v in record.inputs if v.get("name") == "BMI"), None)
        assert bmi_var is not None
        assert bmi_var["type"] == "int"
        assert bmi_var["id"] == "var_sub_bmi_int"
