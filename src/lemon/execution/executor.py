"""Deterministic workflow executor.

This module provides the execution engine for workflows. Execution is
deterministic - the same inputs always produce the same output.

The executor traverses the workflow graph:
1. Starts at input blocks, loading values from inputs
2. Follows connections through decision blocks
3. At each decision, evaluates the condition against current state
4. Continues until reaching an output block
5. Returns the output value

For WorkflowRefBlocks, the executor recursively executes the referenced
workflow and stores its output in the current state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, TYPE_CHECKING

from lemon.core.blocks import (
    Workflow,
    Block,
    InputBlock,
    DecisionBlock,
    OutputBlock,
    WorkflowRefBlock,
    BlockType,
    InputType,
    PortType,
)
from lemon.core.exceptions import (
    ExecutionError,
    MissingInputError,
    InputTypeError,
    CircularReferenceError,
)
from lemon.execution.conditions import ConditionEvaluator

if TYPE_CHECKING:
    from lemon.storage.repository import SQLiteWorkflowRepository, InMemoryWorkflowRepository
    Repository = SQLiteWorkflowRepository | InMemoryWorkflowRepository


@dataclass
class ExecutionResult:
    """Result of workflow execution."""
    output: Optional[str] = None
    path: List[str] = field(default_factory=list)
    error: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        """Whether execution succeeded."""
        return self.error is None and self.output is not None


@dataclass
class ExecutionTrace:
    """Detailed trace of workflow execution."""
    result: ExecutionResult
    steps: List[Dict[str, Any]] = field(default_factory=list)
    state_history: List[Dict[str, Any]] = field(default_factory=list)


class WorkflowExecutor:
    """Executes workflows deterministically.

    Usage:
        executor = WorkflowExecutor(repository)
        result = executor.execute(workflow, {"age": 25})
        if result.success:
            print(f"Output: {result.output}")
        else:
            print(f"Error: {result.error}")
    """

    def __init__(self, repository: Optional["Repository"] = None):
        """Initialize executor.

        Args:
            repository: Repository for resolving WorkflowRefBlocks.
                       Required if executing workflows with refs.
        """
        self.repository = repository
        self.condition_evaluator = ConditionEvaluator()

    def execute(
        self,
        workflow: Workflow,
        inputs: Dict[str, Any],
        _visited_refs: Optional[Set[str]] = None,
    ) -> ExecutionResult:
        """Execute a workflow with given inputs.

        Args:
            workflow: The workflow to execute.
            inputs: Dictionary of input name -> value.
            _visited_refs: Internal tracking for circular reference detection.

        Returns:
            ExecutionResult with output or error.
        """
        # Track visited workflow refs for circular dependency detection
        if _visited_refs is None:
            _visited_refs = set()

        if workflow.id in _visited_refs:
            return ExecutionResult(
                error=f"Circular reference detected: {workflow.id}",
            )
        _visited_refs.add(workflow.id)

        try:
            # Validate inputs
            validation_errors = self.validate_inputs(workflow, inputs)
            if validation_errors:
                return ExecutionResult(
                    error=f"Input validation failed: {'; '.join(validation_errors)}",
                )

            # Initialize execution state
            state = dict(inputs)
            path: List[str] = []

            # Find starting point (first non-input block)
            start_block = self._find_start_block(workflow)
            if start_block is None:
                # Workflow has only inputs - find first output
                if workflow.output_blocks:
                    return ExecutionResult(
                        output=workflow.output_blocks[0].value,
                        path=path,
                        context=state,
                    )
                return ExecutionResult(error="Workflow has no executable blocks")

            # Execute from start block
            current = start_block
            max_steps = 1000  # Prevent infinite loops

            for _ in range(max_steps):
                if current is None:
                    return ExecutionResult(error="Execution reached dead end")

                path.append(current.id)

                if isinstance(current, OutputBlock):
                    return ExecutionResult(
                        output=current.value,
                        path=path,
                        context=state,
                    )

                elif isinstance(current, DecisionBlock):
                    # Evaluate condition
                    try:
                        result = self.condition_evaluator.evaluate(
                            current.condition, state
                        )
                    except Exception as e:
                        return ExecutionResult(
                            error=f"Condition evaluation failed: {e}",
                            path=path,
                        )

                    # Follow appropriate branch
                    port = PortType.TRUE if result else PortType.FALSE
                    next_block = self._get_next_block(workflow, current.id, port)
                    current = next_block

                elif isinstance(current, WorkflowRefBlock):
                    # Execute referenced workflow
                    if self.repository is None:
                        return ExecutionResult(
                            error="Cannot execute workflow ref: no repository",
                            path=path,
                        )

                    ref_workflow = self.repository.get(current.ref_id)
                    if ref_workflow is None:
                        return ExecutionResult(
                            error=f"Referenced workflow not found: {current.ref_id}",
                            path=path,
                        )

                    # Map inputs
                    ref_inputs = {}
                    for child_input, parent_var in current.input_mapping.items():
                        if parent_var in state:
                            ref_inputs[child_input] = state[parent_var]
                        else:
                            return ExecutionResult(
                                error=f"Missing mapping source: {parent_var}",
                                path=path,
                            )

                    # Execute recursively
                    ref_result = self.execute(
                        ref_workflow, ref_inputs, _visited_refs.copy()
                    )
                    if not ref_result.success:
                        return ExecutionResult(
                            error=f"Referenced workflow failed: {ref_result.error}",
                            path=path,
                        )

                    # Store output in state
                    state[current.output_name] = ref_result.output

                    # Continue to next block
                    next_block = self._get_next_block(workflow, current.id)
                    current = next_block

                elif isinstance(current, InputBlock):
                    # Input blocks are just data - continue to next
                    next_block = self._get_next_block(workflow, current.id)
                    current = next_block

                else:
                    return ExecutionResult(
                        error=f"Unknown block type: {type(current).__name__}",
                        path=path,
                    )

            return ExecutionResult(error="Execution exceeded maximum steps")

        finally:
            _visited_refs.discard(workflow.id)

    def trace(
        self,
        workflow: Workflow,
        inputs: Dict[str, Any],
    ) -> ExecutionTrace:
        """Execute workflow with detailed tracing.

        Like execute(), but records every step for debugging.

        Args:
            workflow: The workflow to execute.
            inputs: Dictionary of input name -> value.

        Returns:
            ExecutionTrace with full step-by-step details.
        """
        steps: List[Dict[str, Any]] = []
        state_history: List[Dict[str, Any]] = []

        state = dict(inputs)
        state_history.append(dict(state))
        path: List[str] = []

        # Validate inputs
        validation_errors = self.validate_inputs(workflow, inputs)
        if validation_errors:
            return ExecutionTrace(
                result=ExecutionResult(
                    error=f"Input validation failed: {'; '.join(validation_errors)}",
                ),
                steps=steps,
                state_history=state_history,
            )

        # Find starting point
        start_block = self._find_start_block(workflow)
        if start_block is None:
            if workflow.output_blocks:
                return ExecutionTrace(
                    result=ExecutionResult(
                        output=workflow.output_blocks[0].value,
                        path=path,
                        context=state,
                    ),
                    steps=steps,
                    state_history=state_history,
                )
            return ExecutionTrace(
                result=ExecutionResult(error="Workflow has no executable blocks"),
                steps=steps,
                state_history=state_history,
            )

        current = start_block
        max_steps = 1000

        for step_num in range(max_steps):
            if current is None:
                return ExecutionTrace(
                    result=ExecutionResult(error="Execution reached dead end", path=path),
                    steps=steps,
                    state_history=state_history,
                )

            path.append(current.id)

            step_info = {
                "step": step_num,
                "block_id": current.id,
                "block_type": current.type.value if hasattr(current, 'type') else str(type(current)),
                "state_before": dict(state),
            }

            if isinstance(current, OutputBlock):
                step_info["action"] = "output"
                step_info["output"] = current.value
                steps.append(step_info)

                return ExecutionTrace(
                    result=ExecutionResult(
                        output=current.value,
                        path=path,
                        context=state,
                    ),
                    steps=steps,
                    state_history=state_history,
                )

            elif isinstance(current, DecisionBlock):
                step_info["action"] = "decision"
                step_info["condition"] = current.condition

                try:
                    result = self.condition_evaluator.evaluate(current.condition, state)
                    step_info["result"] = result
                    step_info["next_port"] = "true" if result else "false"
                except Exception as e:
                    step_info["error"] = str(e)
                    steps.append(step_info)
                    return ExecutionTrace(
                        result=ExecutionResult(
                            error=f"Condition evaluation failed: {e}",
                            path=path,
                        ),
                        steps=steps,
                        state_history=state_history,
                    )

                steps.append(step_info)
                port = PortType.TRUE if result else PortType.FALSE
                current = self._get_next_block(workflow, current.id, port)

            elif isinstance(current, WorkflowRefBlock):
                step_info["action"] = "workflow_ref"
                step_info["ref_id"] = current.ref_id
                # Simplified for tracing - actual execution handles refs
                steps.append(step_info)
                current = self._get_next_block(workflow, current.id)

            elif isinstance(current, InputBlock):
                step_info["action"] = "input"
                step_info["input_name"] = current.name
                step_info["input_value"] = state.get(current.name)
                steps.append(step_info)
                current = self._get_next_block(workflow, current.id)

            else:
                step_info["action"] = "unknown"
                steps.append(step_info)
                return ExecutionTrace(
                    result=ExecutionResult(
                        error=f"Unknown block type: {type(current).__name__}",
                        path=path,
                    ),
                    steps=steps,
                    state_history=state_history,
                )

            state_history.append(dict(state))

        return ExecutionTrace(
            result=ExecutionResult(error="Execution exceeded maximum steps", path=path),
            steps=steps,
            state_history=state_history,
        )

    def validate_inputs(
        self,
        workflow: Workflow,
        inputs: Dict[str, Any],
    ) -> List[str]:
        """Validate inputs against workflow schema.

        Checks:
        - All required inputs are present
        - Input types are correct
        - Values are within range (for numeric types)
        - Values are in allowed set (for enums)

        Args:
            workflow: The workflow to validate against.
            inputs: The inputs to validate.

        Returns:
            List of error messages. Empty if valid.
        """
        errors = []

        for input_block in workflow.input_blocks:
            name = input_block.name

            # Check required
            if input_block.required and name not in inputs:
                errors.append(f"Missing required input: {name}")
                continue

            if name not in inputs:
                continue

            value = inputs[name]

            # Check type
            if input_block.input_type == InputType.INT:
                if not isinstance(value, int) or isinstance(value, bool):
                    errors.append(f"Input '{name}' must be an integer, got {type(value).__name__}")
                    continue

                # Check range
                if input_block.range:
                    if input_block.range.min is not None and value < input_block.range.min:
                        errors.append(f"Input '{name}' value {value} below minimum {input_block.range.min}")
                    if input_block.range.max is not None and value > input_block.range.max:
                        errors.append(f"Input '{name}' value {value} above maximum {input_block.range.max}")

            elif input_block.input_type == InputType.FLOAT:
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    errors.append(f"Input '{name}' must be a number, got {type(value).__name__}")
                    continue

                # Check range
                if input_block.range:
                    if input_block.range.min is not None and value < input_block.range.min:
                        errors.append(f"Input '{name}' value {value} below minimum {input_block.range.min}")
                    if input_block.range.max is not None and value > input_block.range.max:
                        errors.append(f"Input '{name}' value {value} above maximum {input_block.range.max}")

            elif input_block.input_type == InputType.BOOL:
                if not isinstance(value, bool):
                    errors.append(f"Input '{name}' must be a boolean, got {type(value).__name__}")

            elif input_block.input_type == InputType.STRING:
                if not isinstance(value, str):
                    errors.append(f"Input '{name}' must be a string, got {type(value).__name__}")

            elif input_block.input_type == InputType.ENUM:
                if input_block.enum_values and value not in input_block.enum_values:
                    errors.append(
                        f"Input '{name}' value '{value}' not in allowed values: {input_block.enum_values}"
                    )

        return errors

    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------

    def _find_start_block(self, workflow: Workflow) -> Optional[Block]:
        """Find the first non-input block to start execution.

        The start block is the first block that:
        1. Has no incoming connections, OR
        2. Only has incoming connections from input blocks

        Returns:
            The starting block, or None if only inputs exist.
        """
        # Get blocks with incoming connections
        has_incoming = {c.to_block for c in workflow.connections}

        # Find blocks that are either not targeted, or only targeted by inputs
        input_ids = {b.id for b in workflow.input_blocks}

        for block in workflow.blocks:
            if isinstance(block, InputBlock):
                continue

            incoming = workflow.get_connections_to(block.id)
            # Check if all incoming are from inputs
            all_from_inputs = all(c.from_block in input_ids for c in incoming)

            if not incoming or all_from_inputs:
                return block

        return None

    def _get_next_block(
        self,
        workflow: Workflow,
        block_id: str,
        port: PortType = PortType.DEFAULT,
    ) -> Optional[Block]:
        """Get the next block following a connection.

        Args:
            workflow: The workflow.
            block_id: Current block ID.
            port: Which output port to follow (for decisions).

        Returns:
            The next block, or None if no connection.
        """
        connections = workflow.get_connections_from(block_id)

        # For decisions, match the port
        for conn in connections:
            if port == PortType.DEFAULT or conn.from_port == port:
                return workflow.get_block(conn.to_block)

        # If no matching port, try default
        if port != PortType.DEFAULT:
            for conn in connections:
                if conn.from_port == PortType.DEFAULT:
                    return workflow.get_block(conn.to_block)

        return None
