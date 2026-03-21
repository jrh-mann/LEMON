from src.backend.tools.workflow_input.modify import ModifyWorkflowVariableTool
from src.backend.tools.workflow_input.remove import RemoveWorkflowVariableTool
from tests.conftest import make_session_with_workflow


def test_variable_rename_updates_decision_and_calculation_refs(workflow_store, test_user_id):
    nodes = [
        {
            "id": "decision_1",
            "type": "decision",
            "label": "Adult?",
            "x": 0,
            "y": 0,
            "color": "amber",
            "condition": {"input_id": "var_patient_age_number", "comparator": "gte", "value": 18},
        },
        {
            "id": "calc_1",
            "type": "calculation",
            "label": "Age doubled",
            "x": 0,
            "y": 100,
            "color": "amber",
            "calculation": {
                "output": {"name": "age_doubled"},
                "operator": "multiply",
                "operands": [
                    {"kind": "variable", "ref": "var_patient_age_number"},
                    {"kind": "literal", "value": 2},
                ],
            },
        },
    ]
    variables = [{
        "id": "var_patient_age_number",
        "name": "Patient Age",
        "type": "number",
        "source": "input",
    }]
    workflow_id, session = make_session_with_workflow(
        workflow_store,
        test_user_id,
        nodes=nodes,
        variables=variables,
    )

    result = ModifyWorkflowVariableTool().execute(
        {"workflow_id": workflow_id, "name": "Patient Age", "new_name": "Age in Years"},
        session_state=session,
    )

    assert result["success"] is True
    assert result["new_id"] == "var_age_in_years_number"
    record = workflow_store.get_workflow(workflow_id, test_user_id)
    assert record is not None
    assert record.nodes[0]["condition"]["input_id"] == "var_age_in_years_number"
    assert record.nodes[1]["calculation"]["operands"][0]["ref"] == "var_age_in_years_number"


def test_variable_remove_rejects_calculation_references(workflow_store, test_user_id):
    nodes = [{
        "id": "calc_1",
        "type": "calculation",
        "label": "Age doubled",
        "x": 0,
        "y": 0,
        "color": "amber",
        "calculation": {
            "output": {"name": "age_doubled"},
            "operator": "multiply",
            "operands": [
                {"kind": "variable", "ref": "var_patient_age_number"},
                {"kind": "literal", "value": 2},
            ],
        },
    }]
    variables = [{
        "id": "var_patient_age_number",
        "name": "Patient Age",
        "type": "number",
        "source": "input",
    }]
    workflow_id, session = make_session_with_workflow(
        workflow_store,
        test_user_id,
        nodes=nodes,
        variables=variables,
    )

    result = RemoveWorkflowVariableTool().execute(
        {"workflow_id": workflow_id, "name": "Patient Age"},
        session_state=session,
    )

    assert result["success"] is False
    assert "calc_1" in result["referencing_nodes"]
    assert "Age doubled" in result["error"]
