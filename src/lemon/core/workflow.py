"""Domain models for workflow analysis and derived artifacts.

These models represent the *structured* workflow analysis produced by `WorkflowAnalyzer`
and consumed by code generation + test generation.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field


RangeValue = Union[float, str]


class PossibleValuesRange(BaseModel):
    type: Literal["range"] = "range"
    min: Optional[RangeValue] = None
    max: Optional[RangeValue] = None
    unit: Optional[str] = None


class PossibleValuesEnum(BaseModel):
    type: Literal["enum"] = "enum"
    values: List[Union[str, int, float, bool]] = Field(default_factory=list)
    unit: Optional[str] = None


class PossibleValuesUnbounded(BaseModel):
    type: Literal["unbounded"] = "unbounded"
    unit: Optional[str] = None


PossibleValues = Union[PossibleValuesRange, PossibleValuesEnum, PossibleValuesUnbounded]


class WorkflowInput(BaseModel):
    """Input as described by the workflow analysis prompt (raw analysis schema)."""

    name: str
    type: str = Field(description="numeric|text|boolean|categorical|date|etc")
    format: str = Field(description="integer|float|string|boolean|date_format|etc")
    possible_values: PossibleValues = Field(default_factory=PossibleValuesUnbounded)
    required_at: Optional[str] = None
    used_at: List[str] = Field(default_factory=list)
    description: str = ""
    constraints: str = ""


class DecisionBranch(BaseModel):
    condition: str
    outcome: str
    leads_to: str


class DecisionPoint(BaseModel):
    name: str
    description: str = ""
    condition: str = ""
    inputs_required: List[str] = Field(default_factory=list)
    branches: List[DecisionBranch] = Field(default_factory=list)


class WorkflowOutput(BaseModel):
    name: str
    type: str = "text"
    description: str = ""
    produced_by: List[str] = Field(default_factory=list)


class WorkflowPath(BaseModel):
    path_id: str
    description: str = ""
    required_inputs: List[str] = Field(default_factory=list)
    decision_sequence: List[str] = Field(default_factory=list)
    output: str


class AnalysisMeta(BaseModel):
    ambiguities: List[str] = Field(default_factory=list)
    questions: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class WorkflowAnalysis(BaseModel):
    """Full structured analysis of a workflow diagram."""

    workflow_description: str = ""
    domain: str = ""
    inputs: List[WorkflowInput] = Field(default_factory=list)
    decision_points: List[DecisionPoint] = Field(default_factory=list)
    outputs: List[WorkflowOutput] = Field(default_factory=list)
    workflow_paths: List[WorkflowPath] = Field(default_factory=list)
    analysis_meta: AnalysisMeta = Field(default_factory=AnalysisMeta)


# ---------------------------------------------------------------------------
# Derived “standardized inputs” schema used by existing pipeline artifacts
# ---------------------------------------------------------------------------


class StandardizedRange(BaseModel):
    min: Optional[RangeValue] = None
    max: Optional[RangeValue] = None
    value: Optional[RangeValue] = None


StandardizedInputType = Literal["Int", "Float", "str", "bool", "date"]


class StandardizedInput(BaseModel):
    """Normalized input schema saved to `workflow_inputs.json` in the current pipeline."""

    input_name: str
    input_type: StandardizedInputType
    range: Optional[Union[StandardizedRange, List[Union[str, int, float, bool]]]] = None
    description: str = ""


JsonDict = Dict[str, Any]
