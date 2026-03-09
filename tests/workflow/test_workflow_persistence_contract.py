from src.backend.workflow_persistence import (
    build_persisted_workflow_fields,
    merge_workflow_record_with_updates,
)


def test_build_persisted_workflow_fields_syncs_tree_and_output_type(create_test_workflow, session_state):
    nodes = [
        {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
        {"id": "end", "type": "end", "label": "Result", "x": 200, "y": 0, "output_value": "7"},
    ]
    edges = [{"id": "e1", "from": "start", "to": "end", "label": ""}]
    variables = [{"id": "var_age_number", "name": "age", "type": "number"}]
    outputs = [{"name": "Result", "type": "string", "description": "legacy"}]

    persisted = build_persisted_workflow_fields(
        nodes=nodes,
        edges=edges,
        variables=variables,
        outputs=outputs,
        output_type="number",
    )

    assert persisted["output_type"] == "number"
    assert persisted["outputs"] == [{"name": "Result", "type": "number", "description": "legacy"}]
    assert persisted["inputs"] == variables
    assert persisted["tree"]["start"]["id"] == "start"


def test_merge_workflow_record_with_updates_keeps_outputs_synced(create_test_workflow, workflow_store, test_user_id):
    workflow_id, _ = create_test_workflow(output_type="string")
    workflow_store.update_workflow(
        workflow_id,
        test_user_id,
        nodes=[
            {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
            {"id": "end", "type": "end", "label": "Answer", "x": 200, "y": 0, "output_value": "12"},
        ],
        outputs=[{"name": "Answer", "type": "string"}],
        tree={"stale": True},
        output_type="string",
    )
    record = workflow_store.get_workflow(workflow_id, test_user_id)
    assert record is not None

    persisted = merge_workflow_record_with_updates(
        record,
        output_type="number",
    )

    assert persisted["output_type"] == "number"
    assert persisted["outputs"] == [{"name": "Answer", "type": "number"}]
    assert persisted["tree"]["start"]["id"] == "start"
