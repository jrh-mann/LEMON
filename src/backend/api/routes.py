"""HTTP routes for the API server."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from flask import Flask, jsonify, request, make_response, g

from .common import utc_now
from .auth import (
    apply_login_rate_limit,
    clear_session_cookie,
    get_auth_config,
    get_session_from_request,
    hash_password,
    hash_session_token,
    issue_session,
    is_registration_allowed,
    note_login_failure,
    normalize_email,
    set_session_cookie,
    validate_email,
    validate_password,
    verify_password,
)
from .conversations import ConversationStore
from ..utils.uploads import save_uploaded_image
from ..utils.flowchart import tree_from_flowchart
from .response_utils import extract_flowchart, extract_tool_calls, summarize_response
from ..storage.auth import AuthStore, AuthUser
from ..storage.workflows import WorkflowStore
from ..validation.workflow_validator import WorkflowValidator

logger = logging.getLogger("backend.api")

# Workflow validator instance for save/update validation
_workflow_validator = WorkflowValidator()


def _infer_outputs_from_nodes(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Infer workflow outputs from end nodes that have output_type defined.
    
    When saving a workflow, we can automatically determine outputs by looking
    at end nodes. If an end node has output_type (and optionally output_value
    or output_template), we create an output definition from it.
    
    This allows subprocesses to properly determine the output type without
    requiring users to explicitly define outputs via a separate UI.
    
    Args:
        nodes: List of workflow nodes
        
    Returns:
        List of output definitions [{name, type, description?}]
    """
    outputs = []
    for node in nodes:
        if node.get("type") == "end" and node.get("output_type"):
            output_def = {
                "name": node.get("label", "output"),
                "type": node.get("output_type"),
            }
            # Include description from template if present
            if node.get("output_template"):
                output_def["description"] = node.get("output_template")
            outputs.append(output_def)
    return outputs


def register_routes(
    app: Flask,
    *,
    conversation_store: ConversationStore,
    repo_root: Path,
    auth_store: AuthStore,
    workflow_store: WorkflowStore,
) -> None:
    auth_config = get_auth_config()
    dummy_password_hash = hash_password("dummy-password", config=auth_config)
    allow_registration = is_registration_allowed()
    public_paths = {"/api/info", "/api/auth/login", "/api/auth/logout", "/api/auth/register"}

    @app.before_request
    def log_request() -> None:
        logger.info(
            "HTTP %s %s from %s",
            request.method,
            request.path,
            request.remote_addr,
        )

    @app.before_request
    def enforce_auth() -> Any:
        if request.method == "OPTIONS":
            return None
        if not request.path.startswith("/api/"):
            return None
        if request.path in public_paths:
            return None
        session_info = get_session_from_request(auth_store)
        if not session_info:
            return jsonify({"error": "Authentication required."}), 401
        session, user = session_info
        g.auth_session = session
        g.auth_user = user
        return None

    def serialize_user(user: AuthUser) -> Dict[str, str]:
        return {
            "id": user.id,
            "email": user.email,
            "name": user.name,
        }

    def _calculate_confidence(score: int, count: int) -> str:
        """Calculate validation confidence level based on score and count."""
        if count == 0:
            return "none"
        accuracy = score / count if count > 0 else 0
        if count < 3:
            return "low"
        if accuracy >= 0.9 and count >= 10:
            return "high"
        if accuracy >= 0.8:
            return "medium"
        return "low"

    @app.get("/api/info")
    def api_info() -> Any:
        return jsonify(
            {
                "name": "LEMON Backend",
                "version": "0.1",
                "endpoints": {
                    "chat": "/api/chat",
                    "workflows": "/api/workflows",
                    "search": "/api/search",
                },
            }
        )

    @app.post("/api/auth/register")
    def register_user() -> Any:
        if not allow_registration:
            return jsonify({"error": "Registration is disabled."}), 403
        payload = request.get_json(force=True, silent=True) or {}
        email = normalize_email(str(payload.get("email", "")))
        name = str(payload.get("name", "")).strip()
        password = str(payload.get("password", ""))
        remember = bool(payload.get("remember"))

        errors = []
        email_error = validate_email(email)
        if email_error:
            errors.append(email_error)
        if not name:
            errors.append("Name is required.")
        errors.extend(list(validate_password(password, auth_config)))
        if errors:
            return jsonify({"error": errors[0], "errors": errors}), 400

        user_id = f"user_{uuid4().hex}"
        password_hash = hash_password(password, config=auth_config)
        try:
            auth_store.create_user(user_id, email, name, password_hash)
        except sqlite3.IntegrityError:
            return jsonify({"error": "Email is already registered."}), 409

        token, expires_at = issue_session(
            auth_store,
            user_id=user_id,
            remember=remember,
            config=auth_config,
        )
        response = make_response(jsonify({"user": {"id": user_id, "email": email, "name": name}}), 201)
        set_session_cookie(response, token, expires_at, config=auth_config)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/auth/login")
    def login_user() -> Any:
        payload = request.get_json(force=True, silent=True) or {}
        email = normalize_email(str(payload.get("email", "")))
        password = str(payload.get("password", ""))
        remember = bool(payload.get("remember"))

        email_error = validate_email(email)
        if email_error:
            return jsonify({"error": email_error}), 400

        identifier = f"{request.remote_addr or 'unknown'}:{email}"
        rate_limit_response = apply_login_rate_limit(identifier)
        if rate_limit_response is not None:
            return rate_limit_response

        user = auth_store.get_user_by_email(email)
        if not user:
            verify_password(password, dummy_password_hash)
            note_login_failure(identifier)
            return jsonify({"error": "Invalid email or password."}), 401

        if not verify_password(password, user.password_hash):
            note_login_failure(identifier)
            return jsonify({"error": "Invalid email or password."}), 401

        auth_store.update_last_login(user.id)
        token, expires_at = issue_session(
            auth_store,
            user_id=user.id,
            remember=remember,
            config=auth_config,
        )
        response = make_response(jsonify({"user": serialize_user(user)}))
        set_session_cookie(response, token, expires_at, config=auth_config)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/auth/logout")
    def logout_user() -> Any:
        token = request.cookies.get("lemon_session")
        if token:
            token_hash = hash_session_token(token)
            auth_store.delete_session_by_token_hash(token_hash)
        response = make_response(jsonify({"success": True}))
        clear_session_cookie(response, config=auth_config)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/auth/me")
    def auth_me() -> Any:
        user = getattr(g, "auth_user", None)
        if not user:
            return jsonify({"error": "Authentication required."}), 401
        response = make_response(jsonify({"user": serialize_user(user)}))
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/chat")
    def chat() -> Any:
        payload = request.get_json(force=True, silent=True) or {}
        message = payload.get("message", "")
        conversation_id = payload.get("conversation_id")
        image_data = payload.get("image")

        if not isinstance(message, str) or not message.strip():
            return jsonify({"error": "message is required"}), 400

        convo = conversation_store.get_or_create(conversation_id)
        if isinstance(image_data, str) and image_data.strip():
            try:
                save_uploaded_image(image_data, repo_root=repo_root)
            except Exception as exc:
                logger.exception("Failed to save uploaded image")
                return jsonify({"error": f"Invalid image data: {exc}"}), 400

        executed_tools: list[dict[str, Any]] = []

        def on_tool_event(
            event: str,
            tool: str,
            args: Dict[str, Any],
            result: Optional[Dict[str, Any]],
        ) -> None:
            if event == "tool_start":
                executed_tools.append({"tool": tool, "arguments": args})

        response_text = convo.orchestrator.respond(
            message,
            has_image=bool(image_data),
            allow_tools=True,
            on_tool_event=on_tool_event,
        )
        tool_calls = extract_tool_calls(response_text, include_result=False)
        if not tool_calls and executed_tools:
            tool_calls = executed_tools
        response_summary = summarize_response(response_text)
        flowchart = extract_flowchart(response_text)
        convo.updated_at = utc_now()
        return jsonify(
            {
                "conversation_id": convo.id,
                "response": response_summary,
                "tool_calls": tool_calls,
                "flowchart": flowchart,
            }
        )

    @app.get("/api/chat/<conversation_id>")
    def get_conversation(conversation_id: str) -> Any:
        convo = conversation_store.get(conversation_id)
        if not convo:
            return jsonify({"error": "conversation not found"}), 404
        messages = []
        for idx, msg in enumerate(convo.orchestrator.history):
            role = msg.get("role", "assistant")
            content = msg.get("content", "")
            messages.append(
                {
                    "id": f"{conversation_id}_{idx}",
                    "role": role,
                    "content": content,
                    "timestamp": utc_now(),
                    "tool_calls": extract_tool_calls(content),
                }
            )
        return jsonify(
            {
                "id": convo.id,
                "messages": messages,
                "working": {},
                "created_at": convo.created_at,
                "updated_at": convo.updated_at,
            }
        )

    @app.get("/api/workflows")
    def list_workflows() -> Any:
        """List all workflows for the authenticated user."""
        user_id = g.auth_user.id
        limit = min(int(request.args.get("limit", 100)), 500)
        offset = max(int(request.args.get("offset", 0)), 0)

        workflows, total_count = workflow_store.list_workflows(
            user_id,
            limit=limit,
            offset=offset,
        )

        # Convert to WorkflowSummary format for frontend
        summaries = []
        for wf in workflows:
            # Extract input names and output values
            input_names = [inp.get("name", "") for inp in wf.inputs if isinstance(inp, dict)]
            output_values = [out.get("value", "") or out.get("name", "") for out in wf.outputs if isinstance(out, dict)]

            summaries.append({
                "id": wf.id,
                "name": wf.name,
                "description": wf.description,
                "domain": wf.domain,
                "tags": wf.tags,
                "validation_score": wf.validation_score,
                "validation_count": wf.validation_count,
                "confidence": _calculate_confidence(wf.validation_score, wf.validation_count),
                "is_validated": wf.is_validated,
                "input_names": input_names,
                "output_values": output_values,
                "created_at": wf.created_at,
                "updated_at": wf.updated_at,
            })

        return jsonify({"workflows": summaries, "count": total_count})

    @app.post("/api/workflows")
    def create_workflow() -> Any:
        """Save a new workflow for the authenticated user."""
        user_id = g.auth_user.id
        payload = request.get_json(force=True, silent=True) or {}

        # Extract workflow data from payload
        workflow_id = payload.get("id") or f"wf_{uuid4().hex}"
        name = payload.get("name") or "Untitled Workflow"
        description = payload.get("description") or ""
        domain = payload.get("domain")
        tags = payload.get("tags") or []

        # Extract workflow structure (nodes, edges, inputs, doubts)
        nodes = payload.get("nodes") or []
        edges = payload.get("edges") or []
        inputs = payload.get("inputs") or []
        doubts = payload.get("doubts") or []

        # ALWAYS compute tree from nodes/edges - don't rely on frontend
        # This ensures the tree structure is always valid and up-to-date
        tree = tree_from_flowchart(nodes, edges)
        
        # Infer outputs from end nodes if not explicitly provided
        # This allows subprocesses to properly determine output types
        outputs = payload.get("outputs") or []
        if not outputs:
            outputs = _infer_outputs_from_nodes(nodes)

        # Extract validation metadata
        validation_score = payload.get("validation_score") or 0
        validation_count = payload.get("validation_count") or 0
        is_validated = payload.get("is_validated") or False

        # Validate workflow structure before saving
        workflow_to_validate = {
            "nodes": nodes,
            "edges": edges,
            "inputs": inputs,
        }
        is_valid, validation_errors = _workflow_validator.validate(
            workflow_to_validate, strict=True
        )
        if not is_valid:
            error_message = _workflow_validator.format_errors(validation_errors)
            return jsonify({
                "error": "Workflow validation failed",
                "message": error_message,
                "validation_errors": [
                    {"code": e.code, "message": e.message, "node_id": e.node_id}
                    for e in validation_errors
                ],
            }), 400

        try:
            workflow_store.create_workflow(
                workflow_id=workflow_id,
                user_id=user_id,
                name=name,
                description=description,
                domain=domain,
                tags=tags,
                nodes=nodes,
                edges=edges,
                inputs=inputs,
                outputs=outputs,
                tree=tree,
                doubts=doubts,
                validation_score=validation_score,
                validation_count=validation_count,
                is_validated=is_validated,
            )
        except sqlite3.IntegrityError:
            # Workflow ID already exists, try updating instead
            success = workflow_store.update_workflow(
                workflow_id=workflow_id,
                user_id=user_id,
                name=name,
                description=description,
                domain=domain,
                tags=tags,
                nodes=nodes,
                edges=edges,
                inputs=inputs,
                outputs=outputs,
                tree=tree,
                doubts=doubts,
                validation_score=validation_score,
                validation_count=validation_count,
                is_validated=is_validated,
            )
            if not success:
                return jsonify({"error": "Failed to save workflow"}), 500

        response = {
            "workflow_id": workflow_id,
            "name": name,
            "description": description,
            "domain": domain,
            "tags": tags,
            "nodes": nodes,
            "edges": edges,
            "message": "Workflow saved successfully.",
        }
        return jsonify(response), 201

    @app.get("/api/workflows/<workflow_id>")
    def get_workflow(workflow_id: str) -> Any:
        """Get a specific workflow by ID."""
        user_id = g.auth_user.id
        workflow = workflow_store.get_workflow(workflow_id, user_id)

        if not workflow:
            return jsonify({"error": "Workflow not found"}), 404

        # Convert to full Workflow format with metadata
        response = {
            "id": workflow.id,
            "metadata": {
                "name": workflow.name,
                "description": workflow.description,
                "domain": workflow.domain,
                "tags": workflow.tags,
                "creator_id": workflow.user_id,
                "created_at": workflow.created_at,
                "updated_at": workflow.updated_at,
                "validation_score": workflow.validation_score,
                "validation_count": workflow.validation_count,
                "confidence": _calculate_confidence(workflow.validation_score, workflow.validation_count),
                "is_validated": workflow.is_validated,
            },
            "nodes": workflow.nodes,
            "edges": workflow.edges,
            "inputs": workflow.inputs,
            "outputs": workflow.outputs,
            "tree": workflow.tree,
            "doubts": workflow.doubts,
        }
        return jsonify(response)

    @app.delete("/api/workflows/<workflow_id>")
    def delete_workflow(workflow_id: str) -> Any:
        """Delete a workflow."""
        user_id = g.auth_user.id
        success = workflow_store.delete_workflow(workflow_id, user_id)

        if not success:
            return jsonify({"error": "Workflow not found or unauthorized"}), 404

        return jsonify({"message": "Workflow deleted successfully"}), 200

    @app.get("/api/search")
    def search_workflows() -> Any:
        """Search workflows with filters."""
        user_id = g.auth_user.id
        query = request.args.get("q")
        domain = request.args.get("domain")
        validated = request.args.get("validated")
        limit = min(int(request.args.get("limit", 100)), 500)
        offset = max(int(request.args.get("offset", 0)), 0)

        # Convert validated string to bool if provided
        validated_bool = None
        if validated is not None:
            validated_bool = validated.lower() in ("true", "1", "yes")

        workflows, total_count = workflow_store.search_workflows(
            user_id,
            query=query,
            domain=domain,
            validated=validated_bool,
            limit=limit,
            offset=offset,
        )

        # Convert to WorkflowSummary format
        summaries = []
        for wf in workflows:
            input_names = [inp.get("name", "") for inp in wf.inputs if isinstance(inp, dict)]
            output_values = [out.get("value", "") or out.get("name", "") for out in wf.outputs if isinstance(out, dict)]

            summaries.append({
                "id": wf.id,
                "name": wf.name,
                "description": wf.description,
                "domain": wf.domain,
                "tags": wf.tags,
                "validation_score": wf.validation_score,
                "validation_count": wf.validation_count,
                "confidence": _calculate_confidence(wf.validation_score, wf.validation_count),
                "is_validated": wf.is_validated,
                "input_names": input_names,
                "output_values": output_values,
                "created_at": wf.created_at,
                "updated_at": wf.updated_at,
            })

        return jsonify({"workflows": summaries, "count": total_count})

    @app.get("/api/domains")
    def list_domains() -> Any:
        """Get list of unique domains used in user's workflows."""
        user_id = g.auth_user.id
        domains = workflow_store.get_domains(user_id)
        return jsonify({"domains": domains})

    @app.post("/api/validate")
    def validate_workflow_endpoint() -> Any:
        """Validate a workflow structure before saving/exporting."""
        from ..validation.workflow_validator import WorkflowValidator

        payload = request.get_json(force=True, silent=True) or {}
        nodes = payload.get("nodes", [])
        edges = payload.get("edges", [])
        variables = payload.get("variables", [])

        validator = WorkflowValidator()
        workflow_to_validate = {
            "nodes": nodes,
            "edges": edges,
            "variables": variables,
        }

        # Use strict=True to check for unreachable nodes and complete structure
        is_valid, errors = validator.validate(workflow_to_validate, strict=True)

        if is_valid:
            return jsonify({
                "success": True,
                "valid": True,
                "message": "Workflow is valid. All nodes are reachable and connected correctly.",
            })
        else:
            error_message = validator.format_errors(errors)
            return jsonify({
                "success": True,
                "valid": False,
                "errors": [
                    {"code": e.code, "message": e.message, "node_id": e.node_id}
                    for e in errors
                ],
                "message": error_message,
            })

    @app.post("/api/execute/<workflow_id>")
    def execute_workflow(workflow_id: str) -> Any:
        """Execute a workflow with provided input values.
        
        Request body should contain input values keyed by input name:
        {
            "Age": 25,
            "Income": 50000.0,
            "Smoker": false
        }
        
        Supports subprocess nodes that reference other workflows.
        Subflow outputs are injected as new inputs for subsequent decisions.
        """
        from ..execution.interpreter import TreeInterpreter
        
        user_id = g.auth_user.id
        
        # Load the workflow
        workflow = workflow_store.get_workflow(workflow_id, user_id)
        if not workflow:
            return jsonify({
                "success": False,
                "error": f"Workflow '{workflow_id}' not found",
                "path": [],
                "context": {},
            }), 404
        
        # Validate workflow has tree structure
        if not workflow.tree or "start" not in workflow.tree:
            return jsonify({
                "success": False,
                "error": "Workflow has no execution tree. Build the workflow tree first.",
                "path": [],
                "context": {},
            }), 400
        
        # Get input values from request
        payload = request.get_json(force=True, silent=True) or {}
        
        # Convert input names to input IDs for the interpreter
        # User provides: {"Age": 25} -> interpreter needs: {"input_age_int": 25}
        name_to_id = {inp['name']: inp['id'] for inp in workflow.inputs}
        input_values = {}
        
        for inp in workflow.inputs:
            inp_name = inp.get('name')
            inp_id = inp.get('id')
            
            if inp_name in payload:
                input_values[inp_id] = payload[inp_name]
            elif inp_id in payload:
                # Also accept input IDs directly
                input_values[inp_id] = payload[inp_id]
        
        # Create interpreter with workflow_store for subflow support
        interpreter = TreeInterpreter(
            tree=workflow.tree,
            inputs=workflow.inputs,
            outputs=workflow.outputs,
            workflow_id=workflow_id,
            call_stack=[],
            workflow_store=workflow_store,
            user_id=user_id,
        )
        
        # Execute workflow
        result = interpreter.execute(input_values)
        
        # Build response
        response = {
            "success": result.success,
            "output": result.output,
            "path": result.path,
            "context": result.context,
            "error": result.error,
        }
        
        # Include subflow execution details if any
        if result.subflow_results:
            response["subflow_results"] = result.subflow_results
        
        return jsonify(response)

    @app.post("/api/validation/start")
    def start_validation() -> Any:
        return jsonify({"error": "Validation not implemented."}), 501

    @app.post("/api/validation/submit")
    def submit_validation() -> Any:
        return jsonify({"error": "Validation not implemented."}), 501

    @app.get("/api/validation/<session_id>")
    def validation_status(session_id: str) -> Any:
        return jsonify({"error": "Validation not implemented."}), 501
