"""MCP server for LEMON backend tools."""

from __future__ import annotations

import hmac
import logging
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings

from ..storage.workflows import WorkflowStore
from ..utils.logging import setup_logging
from ..utils.paths import lemon_data_dir
from ..tools import (
    AskQuestionTool,
    ViewImageTool,
    ExtractGuidanceTool,
    UpdatePlanTool,
    GetCurrentWorkflowTool,
    AddNodeTool,
    ModifyNodeTool,
    DeleteNodeTool,
    AddConnectionTool,
    DeleteConnectionTool,
    BatchEditWorkflowTool,
    HighlightNodeTool,
    AddWorkflowVariableTool,
    ListWorkflowVariablesTool,
    ModifyWorkflowVariableTool,
    RemoveWorkflowVariableTool,
    SetWorkflowOutputTool,
    ValidateWorkflowTool,
    ExecuteWorkflowTool,
    ListWorkflowsInLibrary,
    CreateWorkflowTool,
    SaveWorkflowToLibrary,
)
logger = logging.getLogger("backend.mcp")


class StaticTokenVerifier(TokenVerifier):
    def __init__(self, token: str, client_id: str, scopes: list[str]):
        self._token = token
        self._client_id = client_id
        self._scopes = scopes

    async def verify_token(self, token: str) -> AccessToken | None:
        if not hmac.compare_digest(token, self._token):
            return None
        return AccessToken(token=token, client_id=self._client_id, scopes=self._scopes)


def _auth_settings() -> tuple[AuthSettings | None, TokenVerifier | None]:
    token = os.environ.get("LEMON_MCP_AUTH_TOKEN", "").strip()
    if not token:
        return None, None
    issuer_url = os.environ.get("LEMON_MCP_ISSUER_URL", "http://127.0.0.1:8000").strip()
    resource_url = os.environ.get("LEMON_MCP_RESOURCE_URL", issuer_url).strip()
    scopes_raw = os.environ.get("LEMON_MCP_REQUIRED_SCOPES", "").strip()
    scopes = [scope.strip() for scope in scopes_raw.split(",") if scope.strip()]
    client_id = os.environ.get("LEMON_MCP_CLIENT_ID", "lemon-backend").strip()
    auth_settings = AuthSettings(
        issuer_url=issuer_url,
        resource_server_url=resource_url,
        required_scopes=scopes or None,
    )
    return auth_settings, StaticTokenVerifier(token=token, client_id=client_id, scopes=scopes)


def _repo_root() -> Path:
    return Path(__file__).parent.parent.parent.parent





def build_mcp_server(host: str | None = None, port: int | None = None) -> FastMCP:
    setup_logging()
    auth_settings, token_verifier = _auth_settings()
    if auth_settings and token_verifier:
        logger.info("MCP auth enabled")
    server = FastMCP(
        name="LEMON MCP",
        instructions="Analyze workflow images and return structured workflow data.",
        host=host or "127.0.0.1",
        port=port or 8000,
        json_response=True,
        stateless_http=True,
        auth=auth_settings,
        token_verifier=token_verifier,
    )
    view_image_tool = ViewImageTool()
    extract_guidance_tool = ExtractGuidanceTool()
    update_plan_tool = UpdatePlanTool()
    ask_question_tool = AskQuestionTool()

    # Workflow manipulation tools
    get_workflow_tool = GetCurrentWorkflowTool()
    add_node_tool = AddNodeTool()
    modify_node_tool = ModifyNodeTool()
    delete_node_tool = DeleteNodeTool()
    add_conn_tool = AddConnectionTool()
    delete_conn_tool = DeleteConnectionTool()
    batch_edit_tool = BatchEditWorkflowTool()
    highlight_tool = HighlightNodeTool()

    # Workflow variable management tools
    add_variable_tool = AddWorkflowVariableTool()
    list_variables_tool = ListWorkflowVariablesTool()
    modify_variable_tool = ModifyWorkflowVariableTool()
    remove_variable_tool = RemoveWorkflowVariableTool()
    set_output_tool = SetWorkflowOutputTool()
    validate_tool = ValidateWorkflowTool()
    execute_tool = ExecuteWorkflowTool()

    # Workflow library tools and shared WorkflowStore for MCP mode.
    # MCP can't receive the live object from the orchestrator's session_state,
    # so we create our own WorkflowStore instance here.
    _data_dir = lemon_data_dir(_repo_root())
    _workflow_store = WorkflowStore(_data_dir / "workflows.sqlite")
    list_library_tool = ListWorkflowsInLibrary()
    create_workflow_tool = CreateWorkflowTool()
    save_workflow_tool = SaveWorkflowToLibrary()

    @server.tool(
        name="view_image",
        description="Re-examine an uploaded workflow image. Pass filename when multiple images are uploaded.",
    )
    def view_image(
        filename: str | None = None,
        session_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return the uploaded image as a base64 content block."""
        state = dict(session_state or {})
        tool_args: dict[str, Any] = {}
        if filename:
            tool_args["filename"] = filename
        return view_image_tool.execute(tool_args, session_state=state)

    @server.tool(
        name="extract_guidance",
        description="Extract side information from an uploaded workflow image. Pass filename when multiple images are uploaded.",
    )
    def extract_guidance(
        filename: str | None = None,
        session_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Extract guidance (notes, legends, linked panels) from the image."""
        state = dict(session_state or {})
        tool_args: dict[str, Any] = {}
        if filename:
            tool_args["filename"] = filename
        return extract_guidance_tool.execute(tool_args, session_state=state)

    @server.tool(
        name="update_plan",
        description="Update the step-by-step plan shown to the user.",
    )
    def update_plan(
        items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Update plan checklist items."""
        return update_plan_tool.execute({"items": items})

    @server.tool(
        name="ask_question",
        description="Ask the user a clarification question with optional clickable options.",
    )
    def ask_question(
        question: str,
        options: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Ask the user a question with optional clickable choices."""
        args: dict[str, Any] = {"question": question}
        if options is not None:
            args["options"] = options
        return ask_question_tool.execute(args)

    @server.tool(name="get_current_workflow")
    def get_current_workflow(
        workflow_id: str,
        session_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Get the current workflow state for a given workflow_id."""
        state = dict(session_state or {})
        state.setdefault("workflow_store", _workflow_store)
        return get_workflow_tool.execute({"workflow_id": workflow_id}, session_state=state)

    @server.tool(name="add_node")
    def add_node(
        workflow_id: str,
        type: str,
        label: str,
        x: float | None = None,
        y: float | None = None,
        condition: dict[str, Any] | None = None,
        output_type: str | None = None,
        output_template: str | None = None,
        output_value: str | None = None,
        subworkflow_id: str | None = None,
        input_mapping: dict[str, str] | None = None,
        output_variable: str | None = None,
        calculation: dict[str, Any] | None = None,
        session_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Add a node to the specified workflow.
        
        Args:
            workflow_id: Target workflow ID
            type: Node type (start, process, decision, subprocess, calculation, end)
            label: Display text for the node
            x, y: Optional coordinates
            condition: For decision nodes - {input_id, comparator, value, value2?}
            output_type/template/value: For end nodes
            subworkflow_id/input_mapping/output_variable: For subprocess nodes
            calculation: For calculation nodes - {output, operator, operands}
        """
        args: dict[str, Any] = {"workflow_id": workflow_id, "type": type, "label": label}
        if x is not None:
            args["x"] = x
        if y is not None:
            args["y"] = y
        if condition is not None:
            args["condition"] = condition
        if output_type is not None:
            args["output_type"] = output_type
        if output_template is not None:
            args["output_template"] = output_template
        if output_value is not None:
            args["output_value"] = output_value
        if subworkflow_id is not None:
            args["subworkflow_id"] = subworkflow_id
        if input_mapping is not None:
            args["input_mapping"] = input_mapping
        if output_variable is not None:
            args["output_variable"] = output_variable
        if calculation is not None:
            args["calculation"] = calculation
        state = dict(session_state or {})
        state.setdefault("workflow_store", _workflow_store)
        return add_node_tool.execute(args, session_state=state)

    @server.tool(name="modify_node")
    def modify_node(
        workflow_id: str,
        node_id: str,
        label: str | None = None,
        type: str | None = None,
        x: float | None = None,
        y: float | None = None,
        condition: dict[str, Any] | None = None,
        output_type: str | None = None,
        output_template: str | None = None,
        output_value: str | None = None,
        subworkflow_id: str | None = None,
        input_mapping: dict[str, str] | None = None,
        output_variable: str | None = None,
        calculation: dict[str, Any] | None = None,
        session_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Modify a node in the specified workflow.
        
        Args:
            workflow_id: Target workflow ID
            node_id: ID of the node to modify
            label, type, x, y: Basic node properties
            condition: For decision nodes - {input_id, comparator, value, value2?}
            output_type/template/value: For end nodes
            subworkflow_id/input_mapping/output_variable: For subprocess nodes
            calculation: For calculation nodes - {output, operator, operands}
        """
        args: dict[str, Any] = {"workflow_id": workflow_id, "node_id": node_id}
        if label is not None:
            args["label"] = label
        if type is not None:
            args["type"] = type
        if x is not None:
            args["x"] = x
        if y is not None:
            args["y"] = y
        if condition is not None:
            args["condition"] = condition
        if output_type is not None:
            args["output_type"] = output_type
        if output_template is not None:
            args["output_template"] = output_template
        if output_value is not None:
            args["output_value"] = output_value
        if subworkflow_id is not None:
            args["subworkflow_id"] = subworkflow_id
        if input_mapping is not None:
            args["input_mapping"] = input_mapping
        if output_variable is not None:
            args["output_variable"] = output_variable
        if calculation is not None:
            args["calculation"] = calculation
        state = dict(session_state or {})
        state.setdefault("workflow_store", _workflow_store)
        return modify_node_tool.execute(args, session_state=state)

    @server.tool(name="delete_node")
    def delete_node(
        workflow_id: str,
        node_id: str,
        session_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Delete a node from the specified workflow."""
        state = dict(session_state or {})
        state.setdefault("workflow_store", _workflow_store)
        return delete_node_tool.execute(
            {"workflow_id": workflow_id, "node_id": node_id},
            session_state=state,
        )

    @server.tool(name="add_connection")
    def add_connection(
        workflow_id: str,
        from_node_id: str,
        to_node_id: str,
        label: str | None = None,
        session_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Add a connection between nodes in the specified workflow."""
        args: dict[str, Any] = {
            "workflow_id": workflow_id,
            "from_node_id": from_node_id,
            "to_node_id": to_node_id,
        }
        if label is not None:
            args["label"] = label
        state = dict(session_state or {})
        state.setdefault("workflow_store", _workflow_store)
        return add_conn_tool.execute(args, session_state=state)

    @server.tool(name="delete_connection")
    def delete_connection(
        workflow_id: str,
        from_node_id: str,
        to_node_id: str,
        session_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Delete a connection in the specified workflow."""
        state = dict(session_state or {})
        state.setdefault("workflow_store", _workflow_store)
        return delete_conn_tool.execute(
            {
                "workflow_id": workflow_id,
                "from_node_id": from_node_id,
                "to_node_id": to_node_id,
            },
            session_state=state,
        )

    @server.tool(name="batch_edit_workflow")
    def batch_edit_workflow(
        workflow_id: str,
        operations: list[dict[str, Any]],
        session_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Apply multiple operations to the specified workflow in a single batch."""
        state = dict(session_state or {})
        state.setdefault("workflow_store", _workflow_store)
        return batch_edit_tool.execute(
            {"workflow_id": workflow_id, "operations": operations},
            session_state=state,
        )

    @server.tool(name="highlight_node")
    def highlight_node(
        node_id: str,
        workflow_id: str | None = None,
    ) -> dict[str, Any]:
        """Highlight a node on the canvas to draw the user's attention to it."""
        return highlight_tool.execute(
            {"node_id": node_id, "workflow_id": workflow_id or ""},
        )

    @server.tool(name="add_workflow_variable")
    def add_workflow_variable(
        workflow_id: str,
        name: str,
        type: str,
        description: str | None = None,
        enum_values: list[str] | None = None,
        range_min: float | None = None,
        range_max: float | None = None,
        session_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Add a variable to the specified workflow."""
        args: dict[str, Any] = {"workflow_id": workflow_id, "name": name, "type": type}
        if description:
            args["description"] = description
        if enum_values:
            args["enum_values"] = enum_values
        if range_min is not None:
            args["range_min"] = range_min
        if range_max is not None:
            args["range_max"] = range_max
        state = dict(session_state or {})
        state.setdefault("workflow_store", _workflow_store)
        return add_variable_tool.execute(args, session_state=state)

    @server.tool(name="list_workflow_variables")
    def list_workflow_variables(
        workflow_id: str,
        session_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """List all variables in the specified workflow."""
        state = dict(session_state or {})
        state.setdefault("workflow_store", _workflow_store)
        return list_variables_tool.execute({"workflow_id": workflow_id}, session_state=state)

    @server.tool(name="remove_workflow_variable")
    def remove_workflow_variable(
        workflow_id: str,
        name: str,
        force: bool = False,
        session_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Remove a variable from the specified workflow."""
        args: dict[str, Any] = {"workflow_id": workflow_id, "name": name}
        if force:
            args["force"] = force
        state = dict(session_state or {})
        state.setdefault("workflow_store", _workflow_store)
        return remove_variable_tool.execute(args, session_state=state)

    @server.tool(name="modify_workflow_variable")
    def modify_workflow_variable(
        workflow_id: str,
        name: str,
        new_type: str | None = None,
        new_name: str | None = None,
        description: str | None = None,
        enum_values: list[str] | None = None,
        range_min: float | None = None,
        range_max: float | None = None,
        session_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Modify a variable in the specified workflow."""
        args: dict[str, Any] = {"workflow_id": workflow_id, "name": name}
        if new_type is not None:
            args["new_type"] = new_type
        if new_name is not None:
            args["new_name"] = new_name
        if description is not None:
            args["description"] = description
        if enum_values is not None:
            args["enum_values"] = enum_values
        if range_min is not None:
            args["range_min"] = range_min
        if range_max is not None:
            args["range_max"] = range_max
        state = dict(session_state or {})
        state.setdefault("workflow_store", _workflow_store)
        return modify_variable_tool.execute(args, session_state=state)

    @server.tool(name="set_workflow_output")
    def set_workflow_output(
        workflow_id: str,
        name: str,
        type: str,
        description: str | None = None,
        session_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Set the output configuration for the specified workflow."""
        args: dict[str, Any] = {"workflow_id": workflow_id, "name": name, "type": type}
        if description is not None:
            args["description"] = description
        state = dict(session_state or {})
        state.setdefault("workflow_store", _workflow_store)
        return set_output_tool.execute(args, session_state=state)

    @server.tool(name="validate_workflow")
    def validate_workflow(
        workflow_id: str,
        session_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Validate the specified workflow for errors."""
        state = dict(session_state or {})
        state.setdefault("workflow_store", _workflow_store)
        return validate_tool.execute({"workflow_id": workflow_id}, session_state=state)

    @server.tool(name="create_workflow")
    def create_workflow(
        name: str,
        output_type: str,
        description: str | None = None,
        domain: str | None = None,
        tags: list[str] | None = None,
        user_id: str | None = None,
        session_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new workflow in the library.
        
        Must be called before using any workflow editing tools.
        Returns the workflow_id to use for subsequent tool calls.
        """
        args: dict[str, Any] = {"name": name, "output_type": output_type}
        if description:
            args["description"] = description
        if domain:
            args["domain"] = domain
        if tags:
            args["tags"] = tags
        state = dict(session_state or {})
        state.setdefault("workflow_store", _workflow_store)
        # Use provided user_id or default for MCP mode
        state.setdefault("user_id", user_id or "mcp_user")
        return create_workflow_tool.execute(args, session_state=state)

    @server.tool(name="execute_workflow")
    def execute_workflow(
        workflow_id: str,
        input_values: dict[str, Any],
        session_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute the specified workflow with the given input values."""
        state = dict(session_state or {})
        state.setdefault("workflow_store", _workflow_store)
        return execute_tool.execute(
            {"workflow_id": workflow_id, "input_values": input_values},
            session_state=state,
        )

    @server.tool(name="list_workflows_in_library")
    def list_workflows_in_library(
        search_query: str | None = None,
        domain: str | None = None,
        limit: int = 50,
        session_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """List workflows in the user's library.
        
        Args:
            search_query: Optional text search in name/description
            domain: Optional domain filter
            limit: Max workflows to return
            session_state: Session context
        """
        args: dict[str, Any] = {}
        if search_query is not None:
            args["search_query"] = search_query
        if domain is not None:
            args["domain"] = domain
        args["limit"] = limit
        # Inject workflow_store so the tool can query the DB in MCP mode
        state = dict(session_state or {})
        state.setdefault("workflow_store", _workflow_store)
        return list_library_tool.execute(args, session_state=state)

    @server.tool(name="save_workflow_to_library")
    def save_workflow_to_library(
        workflow_id: str,
        name: str | None = None,
        description: str | None = None,
        domain: str | None = None,
        tags: list[str] | None = None,
        user_id: str | None = None,
        session_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Save a draft workflow to the user's permanent library.
        
        Drafts are workflows created by the LLM that haven't been saved yet.
        This tool publishes the draft to the user's library (is_draft=False).
        
        Args:
            workflow_id: The workflow to save
            name: Optional new name (updates existing if provided)
            description: Optional new description
            domain: Optional domain/category
            tags: Optional list of tags
            user_id: User ID for ownership (defaults to mcp_user in MCP mode)
            session_state: Session context
        """
        args: dict[str, Any] = {"workflow_id": workflow_id}
        if name is not None:
            args["name"] = name
        if description is not None:
            args["description"] = description
        if domain is not None:
            args["domain"] = domain
        if tags is not None:
            args["tags"] = tags
        state = dict(session_state or {})
        state.setdefault("workflow_store", _workflow_store)
        state.setdefault("user_id", user_id or "mcp_user")
        return save_workflow_tool.execute(args, session_state=state)

    return server


def _resolve_transport() -> str:
    raw = os.environ.get("MCP_TRANSPORT", "streamable-http").strip().lower()
    transport_map = {
        "stdio": "stdio",
        "sse": "sse",
        "streamable-http": "streamable-http",
        "http": "streamable-http",
        "streamable": "streamable-http",
    }
    transport = transport_map.get(raw)
    if not transport:
        raise ValueError(
            f"Unknown MCP_TRANSPORT '{raw}'. Use stdio, sse, or streamable-http."
        )
    return transport


def main() -> None:
    transport = _resolve_transport()
    host = os.environ.get("MCP_HOST") or "127.0.0.1"
    port = int(os.environ.get("MCP_PORT", "8000"))
    server = build_mcp_server(host=host, port=port)
    logger.info("Starting MCP server transport=%s host=%s port=%s", transport, host, port)
    server.run(transport=transport)


if __name__ == "__main__":
    main()
