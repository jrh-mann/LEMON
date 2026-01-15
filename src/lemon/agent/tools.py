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


def sanitize_label(value: Any) -> str:
    """Ensure a value is a clean string label.

    Handles cases where the LLM passes:
    - Lists/arrays instead of strings
    - Nested structures
    - JSON-like strings
    - None values
    """
    if value is None:
        return ""

    if isinstance(value, str):
        # Clean up any JSON-like syntax that might be in the string
        cleaned = value.strip()
        # Remove surrounding brackets if they look like stringified arrays
        if cleaned.startswith('[') and cleaned.endswith(']'):
            try:
                import json
                parsed = json.loads(cleaned)
                if isinstance(parsed, list) and len(parsed) > 0:
                    return sanitize_label(parsed[0])
            except (json.JSONDecodeError, TypeError):
                pass  # Not valid JSON, use as-is
        return cleaned

    if isinstance(value, list):
        # Take first element if it's a list
        if len(value) > 0:
            return sanitize_label(value[0])
        return ""

    if isinstance(value, dict):
        # Try common keys for labels (prioritized order)
        for key in ['name', 'label', 'value', 'description', 'condition', 'title', 'text']:
            if key in value and value[key]:
                result = sanitize_label(value[key])
                if result:
                    return result
        # Fallback to id if available
        if 'id' in value and value['id']:
            return sanitize_label(value['id'])
        # Last resort: return generic label instead of stringified dict
        return "Node"

    # Convert anything else to string
    return str(value)


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
                    "List of input specifications. Each input MUST have: "
                    "name (HUMAN-READABLE label like 'Patient Age' or 'eGFR Value', NOT 'input0'), "
                    "type (int/float/bool/string/enum/date), "
                    "and optionally range (for numeric) or enum_values (for enum). "
                    "Example: {\"name\": \"Patient Age\", \"type\": \"int\", \"range\": {\"min\": 0, \"max\": 120}}"
                ),
                required=True,
            ),
            ToolParameter(
                name="decisions",
                type="array",
                description=(
                    "List of decision nodes. Each decision MUST have: "
                    "id (like 'd1'), condition (Python expression like 'age >= 65'), "
                    "and description (HUMAN-READABLE question like 'Is patient elderly?'). "
                    "The description is REQUIRED and shown as the node label. "
                    "Example: {\"id\": \"d1\", \"condition\": \"age >= 65\", \"description\": \"Is patient elderly?\"}"
                ),
                required=True,
            ),
            ToolParameter(
                name="outputs",
                type="array",
                description=(
                    "List of output values as HUMAN-READABLE strings describing outcomes. "
                    "Example: [\"High risk - refer to specialist\", \"Low risk - routine monitoring\"]"
                ),
                required=True,
            ),
            ToolParameter(
                name="connections",
                type="array",
                description=(
                    "List of connections between blocks (REQUIRED - workflows need connections!). "
                    "Each connection should have: from_block (block id like 'input0' or 'd1'), "
                    "to_block (block id), and from_port ('true' or 'false' for decision branches). "
                    "Example: [{\"from_block\": \"input0\", \"to_block\": \"d1\"}, "
                    "{\"from_block\": \"d1\", \"to_block\": \"output0\", \"from_port\": \"true\"}]"
                ),
                required=True,
            ),
        ]

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        from lemon.core.blocks import (
            Workflow, WorkflowMetadata, InputBlock, DecisionBlock, OutputBlock,
            Connection, InputType, Range, PortType, generate_id
        )
        import logging
        logger = logging.getLogger(__name__)

        try:
            # Log incoming arguments for debugging
            logger.info(f"create_workflow called with args: {args}")

            # Parse inputs - handle both dict and string formats
            input_blocks = []
            for i, inp in enumerate(args.get("inputs", [])):
                # If model passed a string, try to parse it as a simple input
                if isinstance(inp, str):
                    input_blocks.append(InputBlock(
                        id=f"input{i}",
                        name=sanitize_label(inp),
                        input_type=InputType.STRING,
                        description="",
                    ))
                    continue

                # Normal dict format
                input_type_str = inp.get("type", "string")
                if isinstance(input_type_str, list):
                    input_type_str = input_type_str[0] if input_type_str else "string"
                input_type = InputType(input_type_str)

                range_obj = None
                if "range" in inp and inp["range"] and isinstance(inp["range"], dict):
                    range_obj = Range(
                        min=inp["range"].get("min"),
                        max=inp["range"].get("max"),
                    )

                input_blocks.append(InputBlock(
                    id=sanitize_label(inp.get("id", f"input{i}")),
                    name=sanitize_label(inp.get("name", f"input{i}")),
                    input_type=input_type,
                    range=range_obj,
                    enum_values=inp.get("enum_values"),
                    description=sanitize_label(inp.get("description", "")),
                ))

            # Parse decisions - handle both dict and string formats
            decision_blocks = []
            for i, dec in enumerate(args.get("decisions", [])):
                if isinstance(dec, str):
                    # Model passed just a condition string
                    decision_blocks.append(DecisionBlock(
                        id=f"d{i+1}",
                        condition=sanitize_label(dec),
                        description="",
                    ))
                    continue

                decision_blocks.append(DecisionBlock(
                    id=sanitize_label(dec.get("id", f"d{i+1}")),
                    condition=sanitize_label(dec.get("condition", "True")),
                    description=sanitize_label(dec.get("description", "")),
                ))

            # Parse outputs
            output_blocks = []
            for i, out in enumerate(args.get("outputs", [])):
                if isinstance(out, str):
                    output_blocks.append(OutputBlock(
                        id=f"output{i}",
                        value=sanitize_label(out),
                    ))
                else:
                    output_blocks.append(OutputBlock(
                        id=sanitize_label(out.get("id", f"output{i}")),
                        value=sanitize_label(out.get("value", out)),
                        description=sanitize_label(out.get("description", "")),
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
            workflow_name = sanitize_label(args.get("name")) or "Untitled Workflow"
            workflow_description = sanitize_label(args.get("description", ""))
            workflow_domain = sanitize_label(args.get("domain")) if args.get("domain") else None
            workflow_tags = args.get("tags") or []
            if isinstance(workflow_tags, str):
                workflow_tags = [workflow_tags]
            workflow_tags = [sanitize_label(t) for t in workflow_tags]

            workflow = Workflow(
                id=generate_id(),
                metadata=WorkflowMetadata(
                    name=workflow_name,
                    description=workflow_description,
                    domain=workflow_domain,
                    tags=workflow_tags,
                ),
                blocks=input_blocks + decision_blocks + output_blocks,
                connections=connections,
            )

            # Save to repository
            self.repository.save(workflow)

            # Build node list for frontend
            # Frontend FlowNodeType: 'start' | 'process' | 'decision' | 'subprocess' | 'end'
            # Frontend FlowNodeColor: 'teal' | 'amber' | 'green' | 'slate' | 'rose' | 'sky'
            nodes = []
            input_block_ids = set(b.id for b in input_blocks)

            # Track which nodes inputs connect to (Start will connect to these)
            input_targets = set()
            for conn in connections:
                if conn.from_block in input_block_ids:
                    input_targets.add(conn.to_block)

            # Build initial nodes list (positions will be computed below)
            all_nodes = []

            # Start node (visual entry point)
            all_nodes.append({
                "id": "start",
                "type": "start",
                "label": "Start",
                "color": "teal",
            })

            # Input nodes as process blocks (teal)
            for block in input_blocks:
                all_nodes.append({
                    "id": block.id,
                    "type": "process",
                    "label": sanitize_label(block.name),
                    "color": "teal",
                })

            # Decision nodes (amber)
            for block in decision_blocks:
                label = block.description if block.description else block.condition
                all_nodes.append({
                    "id": block.id,
                    "type": "decision",
                    "label": sanitize_label(label),
                    "color": "amber",
                })

            # Output nodes as 'end' type (green)
            for block in output_blocks:
                all_nodes.append({
                    "id": block.id,
                    "type": "end",
                    "label": sanitize_label(block.value),
                    "color": "green",
                })

            # Build edges list first (needed for DAG layout)
            temp_edges = []
            for target_id in input_targets:
                temp_edges.append({"from": "start", "to": target_id})
            for conn in connections:
                if conn.from_block in input_block_ids:
                    continue
                temp_edges.append({"from": conn.from_block, "to": conn.to_block})

            # DAG Layout Algorithm (BFS-based level assignment)
            node_ids = {n["id"] for n in all_nodes}
            levels = {nid: 0 for nid in node_ids}

            # Propagate levels: for each edge from→to, to must be at least from+1
            for _ in range(len(all_nodes)):
                changed = False
                for edge in temp_edges:
                    from_id, to_id = edge["from"], edge["to"]
                    if from_id in levels and to_id in levels:
                        next_level = levels[from_id] + 1
                        if levels[to_id] < next_level:
                            levels[to_id] = next_level
                            changed = True
                if not changed:
                    break

            # Group nodes by level
            max_level = max(levels.values()) if levels else 0
            level_groups = [[] for _ in range(max_level + 1)]
            node_by_id = {n["id"]: n for n in all_nodes}
            for nid, lvl in levels.items():
                if nid in node_by_id:
                    level_groups[lvl].append(node_by_id[nid])

            # Build incoming edges map for sorting
            incoming = {nid: [] for nid in node_ids}
            for edge in temp_edges:
                if edge["to"] in incoming:
                    incoming[edge["to"]].append(edge["from"])

            # Sort nodes within each level to minimize edge crossings
            order_index = {}
            for level_idx, group in enumerate(level_groups):
                if level_idx == 0:
                    group.sort(key=lambda n: n.get("label", ""))
                else:
                    def sort_key(n):
                        parents = incoming.get(n["id"], [])
                        if not parents:
                            return 0
                        return sum(order_index.get(p, 0) for p in parents) / len(parents)
                    group.sort(key=sort_key)
                for idx, node in enumerate(group):
                    order_index[node["id"]] = idx

            # Position nodes using DAG layout
            spacing_x = 240
            spacing_y = 150
            padding_x = 120
            padding_y = 80

            max_group_size = max(len(g) for g in level_groups) if level_groups else 1
            canvas_width = max(1200, padding_x * 2 + (max_group_size - 1) * spacing_x)

            nodes = []
            for level_idx, group in enumerate(level_groups):
                group_width = (len(group) - 1) * spacing_x
                start_x = max(padding_x, (canvas_width - group_width) / 2)
                y = padding_y + level_idx * spacing_y
                for idx, node in enumerate(group):
                    x = start_x + idx * spacing_x
                    nodes.append({
                        **node,
                        "x": x,
                        "y": y,
                    })

            # Build edges - Start connects to what inputs connected to
            edges = []

            # If no connections provided, create a simple linear flow as fallback
            if not connections:
                # Start → first decision (or first output if no decisions)
                if decision_blocks:
                    edges.append({"from": "start", "to": decision_blocks[0].id})
                    # Chain decisions together
                    for i in range(len(decision_blocks) - 1):
                        edges.append({"from": decision_blocks[i].id, "to": decision_blocks[i+1].id, "label": "Yes"})
                    # Last decision → outputs
                    if output_blocks:
                        last_decision = decision_blocks[-1].id
                        edges.append({"from": last_decision, "to": output_blocks[0].id, "label": "Yes"})
                        if len(output_blocks) > 1:
                            edges.append({"from": last_decision, "to": output_blocks[1].id, "label": "No"})
                elif output_blocks:
                    edges.append({"from": "start", "to": output_blocks[0].id})
            else:
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

            # Return data for frontend (nodes/edges for canvas)
            # But keep LLM response simple - it doesn't need to see the full structure
            return ToolResult(
                success=True,
                data={
                    "workflow_id": workflow.id,
                    "name": workflow.metadata.name,
                    "description": workflow.metadata.description,
                    "domain": workflow.metadata.domain,
                    "tags": workflow.metadata.tags,
                    "input_count": len(input_blocks),
                    "decision_count": len(decision_blocks),
                    "output_count": len(output_blocks),
                    # Frontend-only data (not echoed to LLM in message)
                    "nodes": nodes,
                    "edges": edges,
                },
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))


# -----------------------------------------------------------------------------
# Get Current Workflow Tool (for editing)
# -----------------------------------------------------------------------------


class GetCurrentWorkflowTool(Tool):
    """Get the current state of a workflow for editing."""

    def __init__(self, repository: "Repository"):
        self.repository = repository

    @property
    def name(self) -> str:
        return "get_current_workflow"

    @property
    def description(self) -> str:
        return (
            "Get the current state of a workflow including all blocks and connections. "
            "Use this before making edits to understand the current structure. "
            "Returns the full workflow with nodes and edges for visualization."
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
        from lemon.core.blocks import PortType

        workflow_id = args.get("workflow_id")
        if not workflow_id:
            return ToolResult(success=False, error="workflow_id is required")

        workflow = self.repository.get(workflow_id)
        if workflow is None:
            return ToolResult(success=False, error=f"Workflow not found: {workflow_id}")

        # Build nodes list for frontend
        nodes = []

        # Start node
        nodes.append({
            "id": "start",
            "type": "start",
            "label": "Start",
            "x": 0, "y": 0,
        })

        # Input blocks
        for block in workflow.input_blocks:
            nodes.append({
                "id": block.id,
                "type": "input",
                "label": block.name,
                "x": block.position.x,
                "y": block.position.y,
                "description": block.description,
                "dataType": block.input_type.value,
                "range": {"min": block.range.min, "max": block.range.max} if block.range else None,
                "enumValues": block.enum_values,
            })

        # Decision blocks
        for block in workflow.decision_blocks:
            nodes.append({
                "id": block.id,
                "type": "decision",
                "label": block.description or block.condition,
                "x": block.position.x,
                "y": block.position.y,
                "condition": block.condition,
            })

        # Output blocks
        for block in workflow.output_blocks:
            nodes.append({
                "id": block.id,
                "type": "output",
                "label": block.value,
                "x": block.position.x,
                "y": block.position.y,
            })

        # Workflow ref blocks
        for block in workflow.workflow_ref_blocks:
            nodes.append({
                "id": block.id,
                "type": "workflow_ref",
                "label": block.ref_name or block.ref_id,
                "x": block.position.x,
                "y": block.position.y,
                "refId": block.ref_id,
                "inputMapping": block.input_mapping,
                "outputName": block.output_name,
            })

        # Build edges
        edges = []
        input_block_ids = {b.id for b in workflow.input_blocks}

        # Find what inputs connect to (Start will connect to these)
        input_targets = set()
        for conn in workflow.connections:
            if conn.from_block in input_block_ids:
                input_targets.add(conn.to_block)

        # Start connects to first decisions
        for target_id in input_targets:
            edges.append({"from": "start", "to": target_id})

        # Other connections
        for conn in workflow.connections:
            if conn.from_block in input_block_ids:
                continue  # Skip input connections (replaced by start)

            edge = {"from": conn.from_block, "to": conn.to_block, "id": conn.id}
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
            },
        )


# -----------------------------------------------------------------------------
# Add Block Tool
# -----------------------------------------------------------------------------


class AddBlockTool(Tool):
    """Add a new block to an existing workflow."""

    def __init__(self, repository: "Repository"):
        self.repository = repository

    @property
    def name(self) -> str:
        return "add_block"

    @property
    def description(self) -> str:
        return (
            "Add a new block to an existing workflow. "
            "Supports input, decision, output, and workflow_ref block types. "
            "Returns the created block and updated workflow state."
        )

    @property
    def parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(
                name="workflow_id",
                type="string",
                description="The ID of the workflow to modify",
                required=True,
            ),
            ToolParameter(
                name="block_type",
                type="string",
                description="Type of block to add",
                required=True,
                enum=["input", "decision", "output", "workflow_ref"],
            ),
            ToolParameter(
                name="label",
                type="string",
                description="Display label for the block (name for input, value for output, description for decision)",
                required=True,
            ),
            ToolParameter(
                name="condition",
                type="string",
                description="Python condition expression (required for decision blocks)",
                required=False,
            ),
            ToolParameter(
                name="data_type",
                type="string",
                description="Data type for input blocks",
                required=False,
                enum=["int", "float", "bool", "string", "enum", "date"],
            ),
            ToolParameter(
                name="enum_values",
                type="array",
                description="Possible values for enum input type",
                required=False,
            ),
            ToolParameter(
                name="range_min",
                type="number",
                description="Minimum value for numeric inputs",
                required=False,
            ),
            ToolParameter(
                name="range_max",
                type="number",
                description="Maximum value for numeric inputs",
                required=False,
            ),
            ToolParameter(
                name="ref_workflow_id",
                type="string",
                description="Referenced workflow ID (required for workflow_ref blocks)",
                required=False,
            ),
        ]

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        from lemon.core.blocks import (
            InputBlock, DecisionBlock, OutputBlock, WorkflowRefBlock,
            InputType, Range, generate_id
        )
        from datetime import datetime, timezone

        workflow_id = args.get("workflow_id")
        block_type = args.get("block_type")
        label = args.get("label")

        if not workflow_id:
            return ToolResult(success=False, error="workflow_id is required")
        if not block_type:
            return ToolResult(success=False, error="block_type is required")
        if not label:
            return ToolResult(success=False, error="label is required")

        workflow = self.repository.get(workflow_id)
        if workflow is None:
            return ToolResult(success=False, error=f"Workflow not found: {workflow_id}")

        # Create the block based on type
        block_id = generate_id()
        new_block = None
        node_data = {"id": block_id, "x": 0, "y": 0}

        try:
            if block_type == "input":
                data_type = args.get("data_type", "string")
                range_obj = None
                if args.get("range_min") is not None or args.get("range_max") is not None:
                    range_obj = Range(min=args.get("range_min"), max=args.get("range_max"))

                new_block = InputBlock(
                    id=block_id,
                    name=label,
                    input_type=InputType(data_type),
                    range=range_obj,
                    enum_values=args.get("enum_values"),
                    description="",
                )
                node_data.update({
                    "type": "input",
                    "label": label,
                    "dataType": data_type,
                    "range": {"min": range_obj.min, "max": range_obj.max} if range_obj else None,
                    "enumValues": args.get("enum_values"),
                })

            elif block_type == "decision":
                condition = args.get("condition")
                if not condition:
                    return ToolResult(success=False, error="condition is required for decision blocks")

                new_block = DecisionBlock(
                    id=block_id,
                    condition=condition,
                    description=label,
                )
                node_data.update({
                    "type": "decision",
                    "label": label,
                    "condition": condition,
                })

            elif block_type == "output":
                new_block = OutputBlock(
                    id=block_id,
                    value=label,
                    description="",
                )
                node_data.update({
                    "type": "output",
                    "label": label,
                })

            elif block_type == "workflow_ref":
                ref_id = args.get("ref_workflow_id")
                if not ref_id:
                    return ToolResult(success=False, error="ref_workflow_id is required for workflow_ref blocks")

                # Get referenced workflow name
                ref_workflow = self.repository.get(ref_id)
                ref_name = ref_workflow.metadata.name if ref_workflow else ref_id

                new_block = WorkflowRefBlock(
                    id=block_id,
                    ref_id=ref_id,
                    ref_name=ref_name,
                    output_name="result",
                )
                node_data.update({
                    "type": "workflow_ref",
                    "label": ref_name,
                    "refId": ref_id,
                })

            else:
                return ToolResult(success=False, error=f"Unknown block type: {block_type}")

            # Add block to workflow
            workflow.blocks.append(new_block)
            workflow.metadata.updated_at = datetime.now(timezone.utc)

            # Save updated workflow
            self.repository.save(workflow)

            return ToolResult(
                success=True,
                data={
                    "block_id": block_id,
                    "block_type": block_type,
                    "node": node_data,
                    "message": f"Added {block_type} block '{label}' to workflow",
                },
            )

        except Exception as e:
            return ToolResult(success=False, error=str(e))


# -----------------------------------------------------------------------------
# Update Block Tool
# -----------------------------------------------------------------------------


class UpdateBlockTool(Tool):
    """Update an existing block in a workflow."""

    def __init__(self, repository: "Repository"):
        self.repository = repository

    @property
    def name(self) -> str:
        return "update_block"

    @property
    def description(self) -> str:
        return (
            "Update properties of an existing block in a workflow. "
            "Can modify labels, conditions, data types, and other block-specific properties."
        )

    @property
    def parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(
                name="workflow_id",
                type="string",
                description="The ID of the workflow containing the block",
                required=True,
            ),
            ToolParameter(
                name="block_id",
                type="string",
                description="The ID of the block to update",
                required=True,
            ),
            ToolParameter(
                name="label",
                type="string",
                description="New label (name for input, value for output, description for decision)",
                required=False,
            ),
            ToolParameter(
                name="condition",
                type="string",
                description="New condition expression (for decision blocks)",
                required=False,
            ),
            ToolParameter(
                name="data_type",
                type="string",
                description="New data type (for input blocks)",
                required=False,
                enum=["int", "float", "bool", "string", "enum", "date"],
            ),
            ToolParameter(
                name="enum_values",
                type="array",
                description="New enum values (for enum input blocks)",
                required=False,
            ),
            ToolParameter(
                name="range_min",
                type="number",
                description="New minimum value (for numeric input blocks)",
                required=False,
            ),
            ToolParameter(
                name="range_max",
                type="number",
                description="New maximum value (for numeric input blocks)",
                required=False,
            ),
        ]

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        from lemon.core.blocks import InputBlock, DecisionBlock, OutputBlock, InputType, Range
        from datetime import datetime, timezone

        workflow_id = args.get("workflow_id")
        block_id = args.get("block_id")

        if not workflow_id:
            return ToolResult(success=False, error="workflow_id is required")
        if not block_id:
            return ToolResult(success=False, error="block_id is required")

        workflow = self.repository.get(workflow_id)
        if workflow is None:
            return ToolResult(success=False, error=f"Workflow not found: {workflow_id}")

        # Find the block
        block = workflow.get_block(block_id)
        if block is None:
            return ToolResult(success=False, error=f"Block not found: {block_id}")

        # Find block index for replacement
        block_index = None
        for i, b in enumerate(workflow.blocks):
            if b.id == block_id:
                block_index = i
                break

        node_data = {"id": block_id, "x": block.position.x, "y": block.position.y}

        try:
            if isinstance(block, InputBlock):
                # Update input block
                name = args.get("label", block.name)
                data_type = args.get("data_type", block.input_type.value)
                enum_values = args.get("enum_values", block.enum_values)

                range_obj = block.range
                if args.get("range_min") is not None or args.get("range_max") is not None:
                    range_obj = Range(
                        min=args.get("range_min", block.range.min if block.range else None),
                        max=args.get("range_max", block.range.max if block.range else None),
                    )

                updated_block = InputBlock(
                    id=block_id,
                    name=name,
                    input_type=InputType(data_type),
                    range=range_obj,
                    enum_values=enum_values,
                    description=block.description,
                    position=block.position,
                )
                workflow.blocks[block_index] = updated_block

                node_data.update({
                    "type": "input",
                    "label": name,
                    "dataType": data_type,
                    "range": {"min": range_obj.min, "max": range_obj.max} if range_obj else None,
                    "enumValues": enum_values,
                })

            elif isinstance(block, DecisionBlock):
                # Update decision block
                condition = args.get("condition", block.condition)
                description = args.get("label", block.description)

                updated_block = DecisionBlock(
                    id=block_id,
                    condition=condition,
                    description=description,
                    position=block.position,
                )
                workflow.blocks[block_index] = updated_block

                node_data.update({
                    "type": "decision",
                    "label": description or condition,
                    "condition": condition,
                })

            elif isinstance(block, OutputBlock):
                # Update output block
                value = args.get("label", block.value)

                updated_block = OutputBlock(
                    id=block_id,
                    value=value,
                    description=block.description,
                    position=block.position,
                )
                workflow.blocks[block_index] = updated_block

                node_data.update({
                    "type": "output",
                    "label": value,
                })

            else:
                return ToolResult(success=False, error=f"Cannot update block type: {block.type}")

            workflow.metadata.updated_at = datetime.now(timezone.utc)
            self.repository.save(workflow)

            return ToolResult(
                success=True,
                data={
                    "block_id": block_id,
                    "node": node_data,
                    "message": f"Updated block '{block_id}'",
                },
            )

        except Exception as e:
            return ToolResult(success=False, error=str(e))


# -----------------------------------------------------------------------------
# Delete Block Tool
# -----------------------------------------------------------------------------


class DeleteBlockTool(Tool):
    """Delete a block from a workflow."""

    def __init__(self, repository: "Repository"):
        self.repository = repository

    @property
    def name(self) -> str:
        return "delete_block"

    @property
    def description(self) -> str:
        return (
            "Delete a block from a workflow. "
            "Also removes all connections to and from the deleted block."
        )

    @property
    def parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(
                name="workflow_id",
                type="string",
                description="The ID of the workflow containing the block",
                required=True,
            ),
            ToolParameter(
                name="block_id",
                type="string",
                description="The ID of the block to delete",
                required=True,
            ),
        ]

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        from datetime import datetime, timezone

        workflow_id = args.get("workflow_id")
        block_id = args.get("block_id")

        if not workflow_id:
            return ToolResult(success=False, error="workflow_id is required")
        if not block_id:
            return ToolResult(success=False, error="block_id is required")

        workflow = self.repository.get(workflow_id)
        if workflow is None:
            return ToolResult(success=False, error=f"Workflow not found: {workflow_id}")

        # Find and remove the block
        block = workflow.get_block(block_id)
        if block is None:
            return ToolResult(success=False, error=f"Block not found: {block_id}")

        # Remove block
        workflow.blocks = [b for b in workflow.blocks if b.id != block_id]

        # Remove connections to/from this block
        removed_connections = []
        new_connections = []
        for conn in workflow.connections:
            if conn.from_block == block_id or conn.to_block == block_id:
                removed_connections.append(conn.id)
            else:
                new_connections.append(conn)
        workflow.connections = new_connections

        workflow.metadata.updated_at = datetime.now(timezone.utc)
        self.repository.save(workflow)

        return ToolResult(
            success=True,
            data={
                "deleted_block_id": block_id,
                "removed_connection_ids": removed_connections,
                "message": f"Deleted block '{block_id}' and {len(removed_connections)} connections",
            },
        )


# -----------------------------------------------------------------------------
# Connect Blocks Tool
# -----------------------------------------------------------------------------


class ConnectBlocksTool(Tool):
    """Create a connection between two blocks."""

    def __init__(self, repository: "Repository"):
        self.repository = repository

    @property
    def name(self) -> str:
        return "connect_blocks"

    @property
    def description(self) -> str:
        return (
            "Create a connection between two blocks in a workflow. "
            "For decision blocks, specify the port ('true' or 'false') to indicate which branch."
        )

    @property
    def parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(
                name="workflow_id",
                type="string",
                description="The ID of the workflow",
                required=True,
            ),
            ToolParameter(
                name="from_block_id",
                type="string",
                description="The ID of the source block",
                required=True,
            ),
            ToolParameter(
                name="to_block_id",
                type="string",
                description="The ID of the target block",
                required=True,
            ),
            ToolParameter(
                name="from_port",
                type="string",
                description="Port on source block: 'true', 'false', or 'default'",
                required=False,
                enum=["true", "false", "default"],
            ),
        ]

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        from lemon.core.blocks import Connection, PortType
        from datetime import datetime, timezone

        workflow_id = args.get("workflow_id")
        from_block_id = args.get("from_block_id")
        to_block_id = args.get("to_block_id")
        from_port = args.get("from_port", "default")

        if not workflow_id:
            return ToolResult(success=False, error="workflow_id is required")
        if not from_block_id:
            return ToolResult(success=False, error="from_block_id is required")
        if not to_block_id:
            return ToolResult(success=False, error="to_block_id is required")

        workflow = self.repository.get(workflow_id)
        if workflow is None:
            return ToolResult(success=False, error=f"Workflow not found: {workflow_id}")

        # Validate blocks exist
        from_block = workflow.get_block(from_block_id)
        to_block = workflow.get_block(to_block_id)

        if from_block is None:
            return ToolResult(success=False, error=f"Source block not found: {from_block_id}")
        if to_block is None:
            return ToolResult(success=False, error=f"Target block not found: {to_block_id}")

        # Check for self-loop
        if from_block_id == to_block_id:
            return ToolResult(success=False, error="Cannot connect a block to itself")

        # Check for duplicate connection
        port_type = PortType(from_port.lower()) if from_port else PortType.DEFAULT
        for conn in workflow.connections:
            if (conn.from_block == from_block_id and
                conn.to_block == to_block_id and
                conn.from_port == port_type):
                return ToolResult(success=False, error="Connection already exists")

        # Create connection
        connection = Connection(
            from_block=from_block_id,
            to_block=to_block_id,
            from_port=port_type,
        )
        workflow.connections.append(connection)

        workflow.metadata.updated_at = datetime.now(timezone.utc)
        self.repository.save(workflow)

        # Build edge data for frontend
        edge_data = {
            "id": connection.id,
            "from": from_block_id,
            "to": to_block_id,
        }
        if port_type == PortType.TRUE:
            edge_data["label"] = "Yes"
        elif port_type == PortType.FALSE:
            edge_data["label"] = "No"

        return ToolResult(
            success=True,
            data={
                "connection_id": connection.id,
                "edge": edge_data,
                "message": f"Connected '{from_block_id}' to '{to_block_id}'",
            },
        )


# -----------------------------------------------------------------------------
# Disconnect Blocks Tool
# -----------------------------------------------------------------------------


class DisconnectBlocksTool(Tool):
    """Remove a connection between two blocks."""

    def __init__(self, repository: "Repository"):
        self.repository = repository

    @property
    def name(self) -> str:
        return "disconnect_blocks"

    @property
    def description(self) -> str:
        return (
            "Remove a connection between two blocks in a workflow. "
            "Can specify blocks and port, or connection ID directly."
        )

    @property
    def parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(
                name="workflow_id",
                type="string",
                description="The ID of the workflow",
                required=True,
            ),
            ToolParameter(
                name="connection_id",
                type="string",
                description="The ID of the connection to remove (alternative to specifying blocks)",
                required=False,
            ),
            ToolParameter(
                name="from_block_id",
                type="string",
                description="The ID of the source block (used with to_block_id)",
                required=False,
            ),
            ToolParameter(
                name="to_block_id",
                type="string",
                description="The ID of the target block (used with from_block_id)",
                required=False,
            ),
            ToolParameter(
                name="from_port",
                type="string",
                description="Port on source block: 'true', 'false', or 'default'",
                required=False,
                enum=["true", "false", "default"],
            ),
        ]

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        from lemon.core.blocks import PortType
        from datetime import datetime, timezone

        workflow_id = args.get("workflow_id")
        connection_id = args.get("connection_id")
        from_block_id = args.get("from_block_id")
        to_block_id = args.get("to_block_id")
        from_port = args.get("from_port", "default")

        if not workflow_id:
            return ToolResult(success=False, error="workflow_id is required")

        workflow = self.repository.get(workflow_id)
        if workflow is None:
            return ToolResult(success=False, error=f"Workflow not found: {workflow_id}")

        removed_id = None

        if connection_id:
            # Remove by connection ID
            original_count = len(workflow.connections)
            workflow.connections = [c for c in workflow.connections if c.id != connection_id]
            if len(workflow.connections) == original_count:
                return ToolResult(success=False, error=f"Connection not found: {connection_id}")
            removed_id = connection_id

        elif from_block_id and to_block_id:
            # Remove by block IDs and port
            port_type = PortType(from_port.lower()) if from_port else PortType.DEFAULT
            original_count = len(workflow.connections)

            for conn in workflow.connections:
                if (conn.from_block == from_block_id and
                    conn.to_block == to_block_id and
                    conn.from_port == port_type):
                    removed_id = conn.id
                    break

            workflow.connections = [
                c for c in workflow.connections
                if not (c.from_block == from_block_id and
                       c.to_block == to_block_id and
                       c.from_port == port_type)
            ]

            if len(workflow.connections) == original_count:
                return ToolResult(success=False, error="Connection not found")

        else:
            return ToolResult(
                success=False,
                error="Either connection_id or both from_block_id and to_block_id are required"
            )

        workflow.metadata.updated_at = datetime.now(timezone.utc)
        self.repository.save(workflow)

        return ToolResult(
            success=True,
            data={
                "removed_connection_id": removed_id,
                "message": "Connection removed",
            },
        )


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

    # Search and discovery tools
    registry.register(SearchLibraryTool(search_service))
    registry.register(GetWorkflowDetailsTool(repository))
    registry.register(ListDomainsTool(search_service))

    # Execution tools
    registry.register(ExecuteWorkflowTool(repository, executor))

    # Validation tools
    registry.register(StartValidationTool(session_manager))
    registry.register(SubmitValidationTool(session_manager))

    # Workflow creation and editing tools
    registry.register(CreateWorkflowTool(repository))
    registry.register(GetCurrentWorkflowTool(repository))
    registry.register(AddBlockTool(repository))
    registry.register(UpdateBlockTool(repository))
    registry.register(DeleteBlockTool(repository))
    registry.register(ConnectBlocksTool(repository))
    registry.register(DisconnectBlocksTool(repository))

    return registry
