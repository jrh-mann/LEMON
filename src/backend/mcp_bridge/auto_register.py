"""Auto-register Tool instances on a FastMCP server.

Generates wrapper functions with the correct Python type-annotated
signature so FastMCP can introspect them to produce MCP tool schemas.
This replaces ~550 lines of hand-written @server.tool() wrappers in
server.py.
"""

from __future__ import annotations

import inspect
import logging
from pathlib import Path
from typing import Any

from ..tools.core import Tool

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
# Type mapping: ToolParameter.type string → Python type for FastMCP
# ------------------------------------------------------------------ #

_TYPE_MAP: dict[str, type] = {
    "string": str,
    "number": float,
    "integer": int,
    "boolean": bool,
    "bool": bool,
    "object": dict,
    "array": list,
    "any": Any,  # type: ignore[dict-item]
}


def _to_python_type(type_str: str) -> type:
    return _TYPE_MAP.get(type_str, Any)  # type: ignore[return-value]


# ------------------------------------------------------------------ #
# Public API
# ------------------------------------------------------------------ #

def register_tool_on_server(
    server: Any,
    tool: Tool,
    workflow_store: Any,
    repo_root: Path,
) -> None:
    """Auto-register a single Tool instance as a FastMCP tool.

    Builds a wrapper function whose keyword-only parameters mirror
    ``tool.parameters``.  FastMCP reads the wrapper's ``__signature__``
    to generate the MCP input schema automatically.
    """
    # Build the wrapper closure bound to this specific tool instance.
    def _make_wrapper(t: Tool) -> Any:
        def wrapper(**kwargs: Any) -> dict[str, Any]:
            # Pop session_state (injected by orchestrator, not a real tool arg)
            session_state = kwargs.pop("session_state", None)
            state: dict[str, Any] = dict(session_state or {})

            # Inject shared resources the tool may need
            state.setdefault("workflow_store", workflow_store)
            state.setdefault("repo_root", repo_root)
            state.setdefault("user_id", state.get("user_id", "mcp_user"))

            # Only forward non-None args to avoid overwriting tool defaults
            args = {k: v for k, v in kwargs.items() if v is not None}
            return t.execute(args, session_state=state)

        # ----- Build a Python signature for FastMCP introspection -----
        sig_params: list[inspect.Parameter] = []
        for p in t.parameters:
            py_type = _to_python_type(p.type)
            if p.required:
                sig_params.append(
                    inspect.Parameter(
                        p.name,
                        inspect.Parameter.KEYWORD_ONLY,
                        annotation=py_type,
                    )
                )
            else:
                sig_params.append(
                    inspect.Parameter(
                        p.name,
                        inspect.Parameter.KEYWORD_ONLY,
                        default=None,
                        annotation=py_type | None,
                    )
                )

        # Always accept session_state as an optional dict
        sig_params.append(
            inspect.Parameter(
                "session_state",
                inspect.Parameter.KEYWORD_ONLY,
                default=None,
                annotation=dict | None,
            )
        )

        wrapper.__signature__ = inspect.Signature(sig_params)  # type: ignore[attr-defined]
        wrapper.__name__ = t.name
        wrapper.__doc__ = t.description
        return wrapper

    fn = _make_wrapper(tool)
    server.tool(name=tool.name, description=tool.description)(fn)
    logger.debug("Registered MCP tool: %s", tool.name)
