from pathlib import Path


def test_workflow_browser_uses_shared_hydration_helper():
    content = Path("src/frontend/src/components/WorkflowBrowser.tsx").read_text(encoding="utf-8")
    assert "hydrateWorkflowDetail" in content
    assert "transform backend response to flowchart format" not in content.lower()


def test_validation_modal_uses_analysis_outputs_not_blocks():
    content = Path("src/frontend/src/components/Modals.tsx").read_text(encoding="utf-8")
    assert "currentAnalysis?.outputs" in content
    assert "currentWorkflow?.blocks" not in content


def test_transform_preserves_empty_labels():
    content = Path("src/frontend/src/utils/canvas/transform.ts").read_text(encoding="utf-8")
    assert "return ''" in content
    assert "return 'Node'" not in content


def test_workflow_store_persists_full_graph_not_just_edges():
    content = Path("src/frontend/src/stores/workflowStore.ts").read_text(encoding="utf-8")
    assert "persistWorkflowGraph" in content
    assert "nodes: flowchart.nodes" in content
    assert "edges: flowchart.edges" in content
