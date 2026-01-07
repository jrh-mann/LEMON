from __future__ import annotations

from src.lemon.core.workflow import WorkflowAnalysis


def test_workflow_analysis_model_validates(sample_workflow_analysis_dict):
    analysis = WorkflowAnalysis.model_validate(sample_workflow_analysis_dict)
    assert analysis.workflow_description == "Simple workflow"
    assert len(analysis.inputs) == 2
    assert analysis.inputs[0].name == "age"
