from src.backend.tools.workflow_edit.batch_edit import BatchEditWorkflowTool
from src.backend.tools.workflow_edit.modify_node import ModifyNodeTool
from tests.conftest import make_session_with_workflow


def _calculation_node() -> dict:
    return {
        "id": "calc_1",
        "type": "calculation",
        "label": "Total",
        "x": 0,
        "y": 0,
        "color": "amber",
        "calculation": {
            "output": {"name": "old_total", "description": "Old total"},
            "operator": "add",
            "operands": [
                {"kind": "literal", "value": 1},
                {"kind": "literal", "value": 2},
            ],
        },
    }


def _variables() -> list[dict]:
    return [{
        "id": "var_old_total_number",
        "name": "old_total",
        "type": "number",
        "source": "calculated",
        "source_node_id": "calc_1",
        "description": "Old total",
    }]


def test_batch_modify_recomputes_derived_variables(workflow_store, test_user_id):
    workflow_id, session = make_session_with_workflow(
        workflow_store,
        test_user_id,
        nodes=[_calculation_node()],
        variables=_variables(),
    )
    tool = BatchEditWorkflowTool()

    result = tool.execute(
        {
            "workflow_id": workflow_id,
            "operations": [{
                "op": "modify_node",
                "node_id": "calc_1",
                "calculation": {
                    "output": {"name": "new_total", "description": "New total"},
                    "operator": "multiply",
                    "operands": [
                        {"kind": "literal", "value": 3},
                        {"kind": "literal", "value": 4},
                    ],
                },
            }],
        },
        session_state=session,
    )

    assert result["success"] is True
    record = workflow_store.get_workflow(workflow_id, test_user_id)
    assert record is not None
    assert record.inputs == [{
        "id": "var_calc_new_total_number",
        "name": "new_total",
        "type": "number",
        "source": "calculated",
        "source_node_id": "calc_1",
        "description": "New total",
    }]


def test_standalone_and_batch_modify_share_normalized_shape(workflow_store, test_user_id):
    workflow_id_one, session_one = make_session_with_workflow(
        workflow_store,
        test_user_id,
        nodes=[_calculation_node()],
        variables=_variables(),
    )
    workflow_id_two, session_two = make_session_with_workflow(
        workflow_store,
        test_user_id,
        nodes=[_calculation_node()],
        variables=_variables(),
    )

    modify_args = {
        "label": "Renamed Total",
        "x": 25,
        "y": 40,
        "calculation": {
            "output": {"name": "normalized_total", "description": "Normalized total"},
            "operator": "subtract",
            "operands": [
                {"kind": "literal", "value": 10},
                {"kind": "literal", "value": 6},
            ],
        },
    }

    modify_result = ModifyNodeTool().execute(
        {"workflow_id": workflow_id_one, "node_id": "calc_1", **modify_args},
        session_state=session_one,
    )
    batch_result = BatchEditWorkflowTool().execute(
        {
            "workflow_id": workflow_id_two,
            "operations": [{"op": "modify_node", "node_id": "calc_1", **modify_args}],
        },
        session_state=session_two,
    )

    assert modify_result["success"] is True
    assert batch_result["success"] is True

    record_one = workflow_store.get_workflow(workflow_id_one, test_user_id)
    record_two = workflow_store.get_workflow(workflow_id_two, test_user_id)
    assert record_one is not None
    assert record_two is not None
    assert record_one.nodes == record_two.nodes
    assert record_one.inputs == record_two.inputs


def test_batch_modify_rejects_unknown_fields(workflow_store, test_user_id):
    workflow_id, session = make_session_with_workflow(
        workflow_store,
        test_user_id,
        nodes=[_calculation_node()],
        variables=_variables(),
    )
    tool = BatchEditWorkflowTool()

    result = tool.execute(
        {
            "workflow_id": workflow_id,
            "operations": [{
                "op": "modify_node",
                "node_id": "calc_1",
                "totally_unknown": "value",
            }],
        },
        session_state=session,
    )

    assert result["success"] is False
    assert "does not allow fields" in result["error"]
