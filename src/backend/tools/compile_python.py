"""Compile to Python tool — generates executable Python code from the workflow."""

from __future__ import annotations

from typing import Any, Dict

from ..execution.python_compiler import compile_workflow_to_python
from ..validation.workflow_validator import WorkflowValidator
from .core import Tool, ToolParameter


class CompilePythonTool(Tool):
    """Generate Python code from the current workflow.

    Takes the workflow nodes, edges, and variables from the canvas and
    generates clean, executable Python code with typed parameters,
    if statements for decisions, and return statements for outputs.
    """

    name = "compile_python"
    description = (
        "Generate Python code from the current workflow. Returns executable "
        "Python source code with typed function parameters for inputs, "
        "if/else statements for decision nodes, and return statements for "
        "outputs. Use this when the user asks to export, generate, or compile "
        "the workflow to Python."
    )
    parameters = [
        ToolParameter(
            "include_main",
            "boolean",
            "Whether to include an if __name__ == '__main__' block with example usage. Default: false",
            required=False,
        ),
        ToolParameter(
            "include_docstring",
            "boolean",
            "Whether to include a docstring with parameter descriptions. Default: true",
            required=False,
        ),
    ]

    def __init__(self) -> None:
        self.validator = WorkflowValidator()

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        session_state = kwargs.get("session_state", {})
        current_workflow = session_state.get("current_workflow", {})

        nodes = current_workflow.get("nodes", [])
        edges = current_workflow.get("edges", [])

        if not nodes:
            return {
                "success": False,
                "error": "No workflow on canvas. Build a workflow first.",
            }

        # Get workflow name and metadata
        metadata = current_workflow.get("metadata", {})
        workflow_name = metadata.get("name", "workflow")

        # Get variables and outputs from workflow analysis
        workflow_analysis = session_state.get("workflow_analysis", {})
        variables = workflow_analysis.get("variables", [])
        outputs = workflow_analysis.get("outputs", [])

        # Validate before compiling
        workflow_for_validation = {
            "nodes": nodes,
            "edges": edges,
            "variables": variables,
        }
        is_valid, errors = self.validator.validate(
            workflow_for_validation, strict=False,  # Use non-strict for compilation
        )
        if not is_valid:
            return {
                "success": False,
                "error": (
                    "Workflow validation failed — fix these before compiling:\n"
                    + self.validator.format_errors(errors)
                ),
            }

        # Get optional arguments
        include_main = args.get("include_main", False)
        include_docstring = args.get("include_docstring", True)

        # Compile to Python
        result = compile_workflow_to_python(
            nodes=nodes,
            edges=edges,
            variables=variables,
            outputs=outputs,
            workflow_name=workflow_name,
            include_imports=True,
            include_docstring=include_docstring,
            include_main=include_main,
        )

        if not result.success:
            return {
                "success": False,
                "error": result.error or "Compilation failed",
                "warnings": result.warnings,
            }

        return {
            "success": True,
            "code": result.code,
            "warnings": result.warnings,
            "message": f"Generated Python code for workflow '{workflow_name}'",
        }
