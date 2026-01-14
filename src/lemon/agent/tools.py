"""Agent tools for the orchestrator.

This module defines the tools available to the orchestrator agent for
interacting with the workflow library, execution engine, and validation system.

Tools follow a consistent interface:
- Each tool has a name, description, and parameter schema
- Tools are executed with a dictionary of arguments
- Tools return a ToolResult with success status and data/error

The tool-based approach (inspired by KernelEvolve) allows structured
interaction without vector embeddings - the agent uses the tools to
grep/search its way through the library.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type, TYPE_CHECKING

if TYPE_CHECKING:
    from lemon.core.blocks import Workflow
    from lemon.storage.repository import SQLiteWorkflowRepository, InMemoryWorkflowRepository
    from lemon.search.service import SearchService
    from lemon.execution.executor import WorkflowExecutor
    from lemon.validation.session import ValidationSessionManager

    Repository = SQLiteWorkflowRepository | InMemoryWorkflowRepository


# -----------------------------------------------------------------------------
# Tool Result
# -----------------------------------------------------------------------------


@dataclass
class ToolResult:
    """Result from executing a tool."""
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {"success": self.success}
        if self.data is not None:
            result["data"] = self.data
        if self.error is not None:
            result["error"] = self.error
        return result


# -----------------------------------------------------------------------------
# Tool Base Class
# -----------------------------------------------------------------------------


@dataclass
class ToolParameter:
    """Description of a tool parameter."""
    name: str
    type: str  # "string", "number", "boolean", "array", "object"
    description: str
    required: bool = True
    enum: Optional[List[str]] = None


class Tool(ABC):
    """Base class for agent tools."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Tool name (used by agent to invoke)."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Tool description (helps agent understand when to use)."""
        pass

    @property
    @abstractmethod
    def parameters(self) -> List[ToolParameter]:
        """Tool parameters."""
        pass

    @abstractmethod
    def execute(self, args: Dict[str, Any]) -> ToolResult:
        """Execute the tool with given arguments."""
        pass

    def to_schema(self) -> Dict[str, Any]:
        """Convert to JSON schema for LLM function calling."""
        properties = {}
        required = []

        for param in self.parameters:
            prop = {"type": param.type, "description": param.description}
            if param.enum:
                prop["enum"] = param.enum
            # Arrays need an items schema
            if param.type == "array":
                prop["items"] = {"type": "string"}
            properties[param.name] = prop
            if param.required:
                required.append(param.name)

        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }


# -----------------------------------------------------------------------------
# Tool Registry
# -----------------------------------------------------------------------------


class ToolRegistry:
    """Registry of available tools."""

    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> List[Tool]:
        """Get all registered tools."""
        return list(self._tools.values())

    def get_schemas(self) -> List[Dict[str, Any]]:
        """Get schemas for all tools."""
        return [tool.to_schema() for tool in self._tools.values()]

    def execute(self, name: str, args: Dict[str, Any]) -> ToolResult:
        """Execute a tool by name."""
        tool = self.get(name)
        if tool is None:
            return ToolResult(success=False, error=f"Unknown tool: {name}")
        try:
            return tool.execute(args)
        except Exception as e:
            return ToolResult(success=False, error=str(e))


# -----------------------------------------------------------------------------
# Search Library Tool
# -----------------------------------------------------------------------------


class SearchLibraryTool(Tool):
    """Search the workflow library."""

    def __init__(self, search_service: "SearchService"):
        self.search_service = search_service

    @property
    def name(self) -> str:
        return "search_library"

    @property
    def description(self) -> str:
        return (
            "Search the workflow library by text, domain, tags, or validation status. "
            "Use this to find existing workflows that match criteria. "
            "Returns a list of workflow summaries."
        )

    @property
    def parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(
                name="text",
                type="string",
                description="Text to search in workflow names and descriptions",
                required=False,
            ),
            ToolParameter(
                name="domain",
                type="string",
                description="Filter by domain (e.g., 'nephrology', 'cardiology')",
                required=False,
            ),
            ToolParameter(
                name="tags",
                type="array",
                description="Filter by tags (workflows must have all specified tags)",
                required=False,
            ),
            ToolParameter(
                name="validated_only",
                type="boolean",
                description="Only return validated workflows (80%+ score, 10+ validations)",
                required=False,
            ),
            ToolParameter(
                name="input_name",
                type="string",
                description="Find workflows that have a specific input parameter name",
                required=False,
            ),
            ToolParameter(
                name="output_value",
                type="string",
                description="Find workflows that produce a specific output value",
                required=False,
            ),
        ]

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        from lemon.core.interfaces import WorkflowFilters

        try:
            # Handle special searches first
            if args.get("input_name"):
                results = self.search_service.find_by_input(args["input_name"])
                return ToolResult(
                    success=True,
                    data={"workflows": [r.model_dump() for r in results]},
                )

            if args.get("output_value"):
                results = self.search_service.find_by_output(args["output_value"])
                return ToolResult(
                    success=True,
                    data={"workflows": [r.model_dump() for r in results]},
                )

            if args.get("validated_only"):
                results = self.search_service.find_validated()
                return ToolResult(
                    success=True,
                    data={"workflows": [r.model_dump() for r in results]},
                )

            # Build filters using the correct field names
            filters = WorkflowFilters(
                name_contains=args.get("text"),
                domain=args.get("domain"),
                tags=args.get("tags"),
                min_validation=80.0 if args.get("validated_only") else None,
            )

            results = self.search_service.search(filters)
            return ToolResult(
                success=True,
                data={"workflows": [r.model_dump() for r in results]},
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))


# -----------------------------------------------------------------------------
# Get Workflow Details Tool
# -----------------------------------------------------------------------------


class GetWorkflowDetailsTool(Tool):
    """Get detailed information about a workflow."""

    def __init__(self, repository: "Repository"):
        self.repository = repository

    @property
    def name(self) -> str:
        return "get_workflow_details"

    @property
    def description(self) -> str:
        return (
            "Get detailed information about a specific workflow including "
            "all inputs, outputs, decision logic, and validation status. "
            "Use this after searching to understand a workflow before using it."
        )

    @property
    def parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(
                name="workflow_id",
                type="string",
                description="The ID of the workflow to retrieve",
                required=True,
            ),
        ]

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        workflow_id = args.get("workflow_id")
        if not workflow_id:
            return ToolResult(success=False, error="workflow_id is required")

        workflow = self.repository.get(workflow_id)
        if workflow is None:
            return ToolResult(success=False, error=f"Workflow not found: {workflow_id}")

        # Convert to detailed dict
        data = {
            "id": workflow.id,
            "metadata": {
                "name": workflow.metadata.name,
                "description": workflow.metadata.description,
                "domain": workflow.metadata.domain,
                "tags": workflow.metadata.tags,
                "validation_score": workflow.metadata.validation_score,
                "validation_count": workflow.metadata.validation_count,
                "is_validated": workflow.metadata.is_validated,
            },
            "inputs": [
                {
                    "name": b.name,
                    "type": b.input_type.value,
                    "range": {"min": b.range.min, "max": b.range.max} if b.range else None,
                    "enum_values": b.enum_values,
                    "description": b.description,
                }
                for b in workflow.input_blocks
            ],
            "outputs": [b.value for b in workflow.output_blocks],
            "decisions": [
                {"id": b.id, "condition": b.condition, "description": b.description}
                for b in workflow.decision_blocks
            ],
            "referenced_workflows": workflow.referenced_workflow_ids,
        }

        return ToolResult(success=True, data=data)


# -----------------------------------------------------------------------------
# Execute Workflow Tool
# -----------------------------------------------------------------------------


class ExecuteWorkflowTool(Tool):
    """Execute a workflow with given inputs."""

    def __init__(self, repository: "Repository", executor: "WorkflowExecutor"):
        self.repository = repository
        self.executor = executor

    @property
    def name(self) -> str:
        return "execute_workflow"

    @property
    def description(self) -> str:
        return (
            "Execute a workflow with specific input values. "
            "Returns the workflow output and execution trace. "
            "Use this to test a workflow or get results for a patient case."
        )

    @property
    def parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(
                name="workflow_id",
                type="string",
                description="The ID of the workflow to execute",
                required=True,
            ),
            ToolParameter(
                name="inputs",
                type="object",
                description="Input values as key-value pairs (e.g., {'age': 65, 'eGFR': 45})",
                required=True,
            ),
        ]

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        workflow_id = args.get("workflow_id")
        inputs = args.get("inputs", {})

        if not workflow_id:
            return ToolResult(success=False, error="workflow_id is required")

        workflow = self.repository.get(workflow_id)
        if workflow is None:
            return ToolResult(success=False, error=f"Workflow not found: {workflow_id}")

        # Validate inputs
        errors = self.executor.validate_inputs(workflow, inputs)
        if errors:
            return ToolResult(success=False, error=f"Invalid inputs: {'; '.join(errors)}")

        # Execute
        result = self.executor.execute(workflow, inputs)

        if result.success:
            return ToolResult(
                success=True,
                data={
                    "output": result.output,
                    "execution_path": result.path,
                },
            )
        else:
            return ToolResult(success=False, error=result.error)


# -----------------------------------------------------------------------------
# Start Validation Tool
# -----------------------------------------------------------------------------


class StartValidationTool(Tool):
    """Start a validation session for a workflow."""

    def __init__(self, session_manager: "ValidationSessionManager"):
        self.session_manager = session_manager

    @property
    def name(self) -> str:
        return "start_validation"

    @property
    def description(self) -> str:
        return (
            "Start a Tinder-style validation session for a workflow. "
            "Generates test cases that the user will validate one by one. "
            "Returns a session ID and the first case to validate."
        )

    @property
    def parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(
                name="workflow_id",
                type="string",
                description="The ID of the workflow to validate",
                required=True,
            ),
            ToolParameter(
                name="case_count",
                type="number",
                description="Number of test cases to generate (default: 20)",
                required=False,
            ),
            ToolParameter(
                name="strategy",
                type="string",
                description="Case generation strategy",
                required=False,
                enum=["random", "boundary", "comprehensive"],
            ),
        ]

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        workflow_id = args.get("workflow_id")
        case_count = int(args.get("case_count", 20))
        strategy = args.get("strategy", "comprehensive")

        if not workflow_id:
            return ToolResult(success=False, error="workflow_id is required")

        try:
            session_id = self.session_manager.start_session(
                workflow_id=workflow_id,
                case_count=case_count,
                strategy=strategy,
            )

            # Get first case
            case = self.session_manager.get_current_case(session_id)
            session = self.session_manager.get_session(session_id)

            return ToolResult(
                success=True,
                data={
                    "session_id": session_id,
                    "progress": session.progress,
                    "current_case": case.to_dict() if case else None,
                },
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))


# -----------------------------------------------------------------------------
# Submit Validation Tool
# -----------------------------------------------------------------------------


class SubmitValidationTool(Tool):
    """Submit a validation answer."""

    def __init__(self, session_manager: "ValidationSessionManager"):
        self.session_manager = session_manager

    @property
    def name(self) -> str:
        return "submit_validation"

    @property
    def description(self) -> str:
        return (
            "Submit the user's expected output for the current validation case. "
            "Compares with workflow output and records match/mismatch. "
            "Returns the result and next case (if any)."
        )

    @property
    def parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(
                name="session_id",
                type="string",
                description="The validation session ID",
                required=True,
            ),
            ToolParameter(
                name="answer",
                type="string",
                description="The user's expected output for the current case",
                required=True,
            ),
        ]

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        session_id = args.get("session_id")
        answer = args.get("answer")

        if not session_id:
            return ToolResult(success=False, error="session_id is required")
        if not answer:
            return ToolResult(success=False, error="answer is required")

        try:
            # Submit answer
            validation_answer = self.session_manager.submit_answer(session_id, answer)

            # Get session state
            session = self.session_manager.get_session(session_id)
            next_case = self.session_manager.get_current_case(session_id)
            score = self.session_manager.get_score(session_id)

            return ToolResult(
                success=True,
                data={
                    "matched": validation_answer.matched,
                    "user_answer": validation_answer.user_answer,
                    "workflow_output": validation_answer.workflow_output,
                    "progress": session.progress,
                    "current_score": score.to_dict(),
                    "next_case": next_case.to_dict() if next_case else None,
                    "session_complete": next_case is None,
                },
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))


# -----------------------------------------------------------------------------
# List Domains Tool
# -----------------------------------------------------------------------------


class ListDomainsTool(Tool):
    """List available domains in the library."""

    def __init__(self, search_service: "SearchService"):
        self.search_service = search_service

    @property
    def name(self) -> str:
        return "list_domains"

    @property
    def description(self) -> str:
        return (
            "List all domains that have workflows in the library. "
            "Use this to understand what medical specialties are covered."
        )

    @property
    def parameters(self) -> List[ToolParameter]:
        return []

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        try:
            domains = self.search_service.list_domains()
            return ToolResult(success=True, data={"domains": domains})
        except Exception as e:
            return ToolResult(success=False, error=str(e))


# -----------------------------------------------------------------------------
# Create Workflow Tool
# -----------------------------------------------------------------------------


class CreateWorkflowTool(Tool):
    """Create a new workflow from a specification."""

    def __init__(self, repository: "Repository"):
        self.repository = repository

    @property
    def name(self) -> str:
        return "create_workflow"

    @property
    def description(self) -> str:
        return (
            "Create a new workflow from a structured specification. "
            "The workflow will be saved to the library for validation. "
            "Use this after understanding user requirements through conversation."
        )

    @property
    def parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(
                name="name",
                type="string",
                description="Name of the workflow",
                required=True,
            ),
            ToolParameter(
                name="description",
                type="string",
                description="Description of what the workflow does",
                required=True,
            ),
            ToolParameter(
                name="domain",
                type="string",
                description="Medical domain (e.g., 'nephrology')",
                required=False,
            ),
            ToolParameter(
                name="tags",
                type="array",
                description="Tags for categorization",
                required=False,
            ),
            ToolParameter(
                name="inputs",
                type="array",
                description=(
                    "List of input specifications. Each input should have: "
                    "name, type (int/float/bool/string/enum/date), "
                    "and optionally range (for numeric) or enum_values (for enum)"
                ),
                required=True,
            ),
            ToolParameter(
                name="decisions",
                type="array",
                description=(
                    "List of decision nodes. Each decision should have: "
                    "id, condition (Python expression), and optionally description"
                ),
                required=True,
            ),
            ToolParameter(
                name="outputs",
                type="array",
                description="List of output values (strings)",
                required=True,
            ),
            ToolParameter(
                name="connections",
                type="array",
                description=(
                    "List of connections between blocks. Each connection should have: "
                    "from_block (block id), to_block (block id), "
                    "and optionally from_port ('true' or 'false' for decisions)"
                ),
                required=True,
            ),
        ]

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        from lemon.core.blocks import (
            Workflow, WorkflowMetadata, InputBlock, DecisionBlock, OutputBlock,
            Connection, InputType, Range, PortType, generate_id
        )

        try:
            # Parse inputs - handle both dict and string formats
            input_blocks = []
            for i, inp in enumerate(args.get("inputs", [])):
                # If model passed a string, try to parse it as a simple input
                if isinstance(inp, str):
                    input_blocks.append(InputBlock(
                        id=f"input{i}",
                        name=inp,
                        input_type=InputType.STRING,
                        description="",
                    ))
                    continue

                # Normal dict format
                input_type = InputType(inp.get("type", "string"))
                range_obj = None
                if "range" in inp and inp["range"] and isinstance(inp["range"], dict):
                    range_obj = Range(
                        min=inp["range"].get("min"),
                        max=inp["range"].get("max"),
                    )

                input_blocks.append(InputBlock(
                    id=inp.get("id", f"input{i}"),
                    name=inp.get("name", f"input{i}"),
                    input_type=input_type,
                    range=range_obj,
                    enum_values=inp.get("enum_values"),
                    description=inp.get("description", ""),
                ))

            # Parse decisions - handle both dict and string formats
            decision_blocks = []
            for i, dec in enumerate(args.get("decisions", [])):
                if isinstance(dec, str):
                    # Model passed just a condition string
                    decision_blocks.append(DecisionBlock(
                        id=f"d{i+1}",
                        condition=dec,
                        description="",
                    ))
                    continue

                decision_blocks.append(DecisionBlock(
                    id=dec.get("id", f"d{i+1}"),
                    condition=dec.get("condition", "True"),
                    description=dec.get("description", ""),
                ))

            # Parse outputs
            output_blocks = []
            for i, out in enumerate(args.get("outputs", [])):
                if isinstance(out, str):
                    output_blocks.append(OutputBlock(
                        id=f"output{i}",
                        value=out,
                    ))
                else:
                    output_blocks.append(OutputBlock(
                        id=out.get("id", f"output{i}"),
                        value=out["value"],
                        description=out.get("description", ""),
                    ))

            # Parse connections - handle various formats
            connections = []
            for conn in args.get("connections", []):
                if not isinstance(conn, dict):
                    continue  # Skip invalid connections

                from_block = conn.get("from_block") or conn.get("from")
                to_block = conn.get("to_block") or conn.get("to")

                if not from_block or not to_block:
                    continue  # Skip incomplete connections

                from_port = PortType.DEFAULT
                port_val = conn.get("from_port", "").lower()
                if port_val == "true" or port_val == "yes":
                    from_port = PortType.TRUE
                elif port_val == "false" or port_val == "no":
                    from_port = PortType.FALSE

                connections.append(Connection(
                    from_block=from_block,
                    to_block=to_block,
                    from_port=from_port,
                ))

            # Create workflow
            workflow_name = args.get("name") or "Untitled Workflow"
            workflow = Workflow(
                id=generate_id(),
                metadata=WorkflowMetadata(
                    name=workflow_name,
                    description=args.get("description", ""),
                    domain=args.get("domain"),
                    tags=args.get("tags") or [],
                ),
                blocks=input_blocks + decision_blocks + output_blocks,
                connections=connections,
            )

            # Save to repository
            self.repository.save(workflow)

            # Build node list for frontend (positions set by frontend autoLayout)
            nodes = []
            input_block_ids = set(b.id for b in input_blocks)

            # Track which nodes inputs connect to (Start will connect to these)
            input_targets = set()
            for conn in connections:
                if conn.from_block in input_block_ids:
                    input_targets.add(conn.to_block)

            # 1. Start node (visual entry point)
            nodes.append({
                "id": "start",
                "type": "start",
                "label": "Start",
                "x": 0, "y": 0,
            })

            # 2. Input nodes (hidden from canvas, shown in sidebar)
            for block in input_blocks:
                nodes.append({
                    "id": block.id,
                    "type": "input",
                    "label": block.name,
                    "x": 0, "y": 0,
                    "description": block.description,
                    "dataType": block.input_type.value,
                    "range": {"min": block.range.min, "max": block.range.max} if block.range else None,
                    "enumValues": block.enum_values,
                })

            # 3. Decision nodes
            for block in decision_blocks:
                nodes.append({
                    "id": block.id,
                    "type": "decision",
                    "label": block.description or block.condition,
                    "x": 0, "y": 0,
                    "condition": block.condition,
                })

            # 4. Output nodes
            for block in output_blocks:
                nodes.append({
                    "id": block.id,
                    "type": "output",
                    "label": block.value,
                    "x": 0, "y": 0,
                })

            # Build edges - Start connects to what inputs connected to
            edges = []

            for target_id in input_targets:
                edges.append({"from": "start", "to": target_id})

            for conn in connections:
                if conn.from_block in input_block_ids:
                    continue  # Skip input→X edges (replaced by start→X)

                edge = {"from": conn.from_block, "to": conn.to_block}
                if conn.from_port == PortType.TRUE:
                    edge["label"] = "Yes"
                elif conn.from_port == PortType.FALSE:
                    edge["label"] = "No"
                edges.append(edge)

            return ToolResult(
                success=True,
                data={
                    "workflow_id": workflow.id,
                    "name": workflow.metadata.name,
                    "description": workflow.metadata.description,
                    "domain": workflow.metadata.domain,
                    "tags": workflow.metadata.tags,
                    "nodes": nodes,
                    "edges": edges,
                    "message": f"Workflow '{workflow.metadata.name}' created successfully.",
                },
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))


# -----------------------------------------------------------------------------
# Factory Function
# -----------------------------------------------------------------------------


def create_tool_registry(
    repository: "Repository",
    search_service: "SearchService",
    executor: "WorkflowExecutor",
    session_manager: "ValidationSessionManager",
) -> ToolRegistry:
    """Create a tool registry with all standard tools."""
    registry = ToolRegistry()

    registry.register(SearchLibraryTool(search_service))
    registry.register(GetWorkflowDetailsTool(repository))
    registry.register(ExecuteWorkflowTool(repository, executor))
    registry.register(StartValidationTool(session_manager))
    registry.register(SubmitValidationTool(session_manager))
    registry.register(ListDomainsTool(search_service))
    registry.register(CreateWorkflowTool(repository))

    return registry
