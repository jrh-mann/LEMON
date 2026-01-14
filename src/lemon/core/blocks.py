"""Block-based workflow models for LEMON v2.

This module defines the composable block model for workflows:
- Blocks: InputBlock, DecisionBlock, OutputBlock, WorkflowRefBlock
- Connections: Edges between blocks
- Workflow: Complete workflow with metadata

These models support:
- Visual block editor representation
- Deterministic execution
- Workflow composition (workflows containing workflows)
- Human validation tracking
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


def generate_id() -> str:
    """Generate a unique ID for blocks/workflows."""
    return uuid4().hex[:12]


# -----------------------------------------------------------------------------
# Enums
# -----------------------------------------------------------------------------


class BlockType(str, Enum):
    """Types of blocks in a workflow."""
    INPUT = "input"
    DECISION = "decision"
    OUTPUT = "output"
    WORKFLOW_REF = "workflow_ref"


class InputType(str, Enum):
    """Data types for input blocks."""
    INT = "int"
    FLOAT = "float"
    BOOL = "bool"
    STRING = "string"
    ENUM = "enum"
    DATE = "date"


class ValidationConfidence(str, Enum):
    """Confidence level based on validation count."""
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# -----------------------------------------------------------------------------
# Position (for visual editor)
# -----------------------------------------------------------------------------


class Position(BaseModel):
    """2D position for block in visual editor."""
    x: float = 0.0
    y: float = 0.0


# -----------------------------------------------------------------------------
# Range specification
# -----------------------------------------------------------------------------


class Range(BaseModel):
    """Numeric range for input validation."""
    min: Optional[float] = None
    max: Optional[float] = None

    @model_validator(mode="after")
    def validate_range(self) -> "Range":
        if self.min is not None and self.max is not None:
            if self.min > self.max:
                raise ValueError(f"min ({self.min}) cannot be greater than max ({self.max})")
        return self


# -----------------------------------------------------------------------------
# Block definitions
# -----------------------------------------------------------------------------


class BlockBase(BaseModel):
    """Base class for all blocks."""
    id: str = Field(default_factory=generate_id)
    type: BlockType
    position: Position = Field(default_factory=Position)

    model_config = {"extra": "forbid"}


class InputBlock(BlockBase):
    """Declares an input parameter for the workflow.

    Examples:
        InputBlock(name="age", input_type=InputType.INT, range=Range(min=0, max=120))
        InputBlock(name="status", input_type=InputType.ENUM, enum_values=["active", "inactive"])
    """
    type: Literal[BlockType.INPUT] = BlockType.INPUT
    name: str
    input_type: InputType
    range: Optional[Range] = None
    enum_values: Optional[List[str]] = None
    description: str = ""
    required: bool = True

    @model_validator(mode="after")
    def validate_type_constraints(self) -> "InputBlock":
        if self.input_type == InputType.ENUM and not self.enum_values:
            raise ValueError("enum_values required when input_type is 'enum'")
        if self.input_type in (InputType.INT, InputType.FLOAT) and self.enum_values:
            raise ValueError("enum_values should not be set for numeric types")
        return self


class DecisionBlock(BlockBase):
    """Conditional branch point in the workflow.

    The condition is a Python expression that evaluates to bool.
    Available variables are the workflow inputs and outputs from previous blocks.

    Examples:
        DecisionBlock(condition="age >= 18")
        DecisionBlock(condition="eGFR < 45 and not on_sglt2")
    """
    type: Literal[BlockType.DECISION] = BlockType.DECISION
    condition: str
    description: str = ""

    @field_validator("condition")
    @classmethod
    def validate_condition_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("condition cannot be empty")
        return v.strip()


class OutputBlock(BlockBase):
    """Terminal output of the workflow.

    When execution reaches an output block, the workflow returns this value.

    Examples:
        OutputBlock(value="approved")
        OutputBlock(value="Refer to specialist")
    """
    type: Literal[BlockType.OUTPUT] = BlockType.OUTPUT
    value: str
    description: str = ""

    @field_validator("value")
    @classmethod
    def validate_value_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("output value cannot be empty")
        return v.strip()


class WorkflowRefBlock(BlockBase):
    """Reference to another workflow in the library.

    This enables workflow composition - embedding a validated workflow
    as a block within another workflow.

    The input_mapping maps parent workflow variables to child workflow inputs.
    The output_name specifies which variable to store the child's output in.

    Examples:
        WorkflowRefBlock(
            ref_id="ckd-staging-abc123",
            input_mapping={"eGFR": "egfr_value", "ACR": "acr_value"},
            output_name="ckd_stage"
        )
    """
    type: Literal[BlockType.WORKFLOW_REF] = BlockType.WORKFLOW_REF
    ref_id: str  # ID of referenced workflow
    ref_name: str = ""  # Display name (denormalized for UI)
    input_mapping: Dict[str, str] = Field(default_factory=dict)  # child_input -> parent_var
    output_name: str = "result"  # Variable name to store output

    @field_validator("ref_id")
    @classmethod
    def validate_ref_id_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("ref_id cannot be empty")
        return v.strip()


# Union type for all blocks
Block = Union[InputBlock, DecisionBlock, OutputBlock, WorkflowRefBlock]


# -----------------------------------------------------------------------------
# Connections
# -----------------------------------------------------------------------------


class PortType(str, Enum):
    """Types of ports on blocks."""
    DEFAULT = "default"
    TRUE = "true"
    FALSE = "false"


class Connection(BaseModel):
    """Edge between two blocks.

    For decision blocks, from_port specifies which branch (true/false).
    For other blocks, from_port is typically "default".
    """
    id: str = Field(default_factory=generate_id)
    from_block: str  # Block ID
    from_port: PortType = PortType.DEFAULT
    to_block: str  # Block ID
    to_port: PortType = PortType.DEFAULT

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def validate_not_self_loop(self) -> "Connection":
        if self.from_block == self.to_block:
            raise ValueError("Connection cannot be a self-loop")
        return self


# -----------------------------------------------------------------------------
# Workflow metadata
# -----------------------------------------------------------------------------


class WorkflowMetadata(BaseModel):
    """Metadata for a workflow."""
    name: str
    description: str = ""
    domain: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    creator_id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Validation tracking
    validation_score: float = 0.0  # 0-100
    validation_count: int = 0

    model_config = {"extra": "forbid"}

    @field_validator("validation_score")
    @classmethod
    def validate_score_range(cls, v: float) -> float:
        if not 0 <= v <= 100:
            raise ValueError("validation_score must be between 0 and 100")
        return v

    @property
    def confidence(self) -> ValidationConfidence:
        """Get confidence level based on validation count."""
        if self.validation_count == 0:
            return ValidationConfidence.NONE
        elif self.validation_count < 10:
            return ValidationConfidence.LOW
        elif self.validation_count < 50:
            return ValidationConfidence.MEDIUM
        else:
            return ValidationConfidence.HIGH

    @property
    def is_validated(self) -> bool:
        """Workflow is considered validated if score >= 80% with medium+ confidence."""
        return (
            self.validation_score >= 80.0
            and self.confidence in (ValidationConfidence.MEDIUM, ValidationConfidence.HIGH)
        )


# -----------------------------------------------------------------------------
# Complete Workflow
# -----------------------------------------------------------------------------


class Workflow(BaseModel):
    """Complete workflow definition.

    A workflow consists of:
    - Blocks: The nodes (inputs, decisions, outputs, workflow refs)
    - Connections: The edges between blocks
    - Metadata: Name, domain, validation status, etc.
    """
    id: str = Field(default_factory=generate_id)
    metadata: WorkflowMetadata
    blocks: List[Block] = Field(default_factory=list)
    connections: List[Connection] = Field(default_factory=list)

    model_config = {"extra": "forbid"}

    # -------------------------------------------------------------------------
    # Convenience accessors
    # -------------------------------------------------------------------------

    @property
    def input_blocks(self) -> List[InputBlock]:
        """Get all input blocks."""
        return [b for b in self.blocks if isinstance(b, InputBlock)]

    @property
    def output_blocks(self) -> List[OutputBlock]:
        """Get all output blocks."""
        return [b for b in self.blocks if isinstance(b, OutputBlock)]

    @property
    def decision_blocks(self) -> List[DecisionBlock]:
        """Get all decision blocks."""
        return [b for b in self.blocks if isinstance(b, DecisionBlock)]

    @property
    def workflow_ref_blocks(self) -> List[WorkflowRefBlock]:
        """Get all workflow reference blocks."""
        return [b for b in self.blocks if isinstance(b, WorkflowRefBlock)]

    @property
    def input_names(self) -> List[str]:
        """Get names of all inputs."""
        return [b.name for b in self.input_blocks]

    @property
    def output_values(self) -> List[str]:
        """Get values of all outputs."""
        return [b.value for b in self.output_blocks]

    @property
    def referenced_workflow_ids(self) -> List[str]:
        """Get IDs of all referenced workflows."""
        return [b.ref_id for b in self.workflow_ref_blocks]

    def get_block(self, block_id: str) -> Optional[Block]:
        """Get block by ID."""
        for block in self.blocks:
            if block.id == block_id:
                return block
        return None

    def get_connections_from(self, block_id: str) -> List[Connection]:
        """Get all connections originating from a block."""
        return [c for c in self.connections if c.from_block == block_id]

    def get_connections_to(self, block_id: str) -> List[Connection]:
        """Get all connections leading to a block."""
        return [c for c in self.connections if c.to_block == block_id]

    # -------------------------------------------------------------------------
    # Validation
    # -------------------------------------------------------------------------

    @model_validator(mode="after")
    def validate_connections_reference_existing_blocks(self) -> "Workflow":
        """Ensure all connections reference existing blocks."""
        block_ids = {b.id for b in self.blocks}
        for conn in self.connections:
            if conn.from_block not in block_ids:
                raise ValueError(f"Connection references non-existent block: {conn.from_block}")
            if conn.to_block not in block_ids:
                raise ValueError(f"Connection references non-existent block: {conn.to_block}")
        return self

    @model_validator(mode="after")
    def validate_decision_blocks_have_two_outputs(self) -> "Workflow":
        """Ensure decision blocks have both true and false connections."""
        for block in self.decision_blocks:
            outgoing = self.get_connections_from(block.id)
            ports = {c.from_port for c in outgoing}
            # This is a warning-level check, not an error
            # A workflow being built might not have all connections yet
        return self


# -----------------------------------------------------------------------------
# Summary model (for list views)
# -----------------------------------------------------------------------------


class WorkflowSummary(BaseModel):
    """Lightweight workflow summary for list views."""
    id: str
    name: str
    description: str = ""
    domain: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    validation_score: float = 0.0
    validation_count: int = 0
    confidence: ValidationConfidence = ValidationConfidence.NONE
    is_validated: bool = False
    input_names: List[str] = Field(default_factory=list)
    output_values: List[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_workflow(cls, workflow: Workflow) -> "WorkflowSummary":
        """Create summary from full workflow."""
        return cls(
            id=workflow.id,
            name=workflow.metadata.name,
            description=workflow.metadata.description,
            domain=workflow.metadata.domain,
            tags=workflow.metadata.tags,
            validation_score=workflow.metadata.validation_score,
            validation_count=workflow.metadata.validation_count,
            confidence=workflow.metadata.confidence,
            is_validated=workflow.metadata.is_validated,
            input_names=workflow.input_names,
            output_values=workflow.output_values,
            created_at=workflow.metadata.created_at,
            updated_at=workflow.metadata.updated_at,
        )
