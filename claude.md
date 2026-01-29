NEVER create markdown files unless instructed

Work atomically, prior to every change define tests and criteria for their acceptance, once these are passed, commit that change.

Make minimal changes to the codebase, work in small, surgical ways, comment your code, to explain what each component does, do not introduce tech debt.

Fail loudly, do not have errors propagate, we are interested in knowing exactly what is going on at all times, if an error occurs it should be realised.

Work within the grand vision of the project, all components should be with reference to that.

## No Backwards Compatibility

This project is in active development with no production users or data. NEVER implement backwards compatibility:
- Do NOT add fallback code like `payload.get("new_key") or payload.get("old_key")`
- Do NOT support legacy field names alongside new ones
- Do NOT write migration code for old data formats
- When renaming fields, update ALL references to use the new name only
- Delete legacy code immediately, do not deprecate

If old code breaks, fix it to use the new approach. Clean breaks are better than compatibility debt.

## Adding New Tools to the Orchestrator

When adding new tools for the LLM to use, you MUST update ALL of these locations:

1. **Tool Implementation** (`src/backend/tools/`)
   - Create tool class inheriting from `Tool`
   - Define `name`, `description`, `parameters`
   - Implement `execute()` method

2. **Tool Registry** (`src/backend/tools/__init__.py`)
   - Add import for new tool
   - Add to `__all__` exports

3. **Orchestrator Factory** (`src/backend/agents/orchestrator_factory.py`)
   - Import the tool
   - Call `registry.register(YourTool())` in `build_orchestrator()`

4. **MCP Server** (`src/backend/mcp/server.py`)
   - Import the tool
   - Initialize tool instance in `build_mcp_server()`
   - Add `@server.tool()` decorated function that calls `your_tool.execute()`

5. **Orchestrator Config** (`src/backend/agents/orchestrator_config.py`)
   - Add tool schema to `tool_descriptions()` array
   - Follow Anthropic tool calling format with full parameter schemas
   - **CRITICAL**: Update system prompt to tell model WHEN to use the tool

6. **Frontend Types** (if needed)
   - Update TypeScript types if tool adds new fields to domain objects
   - Update transformation functions to preserve new fields

7. **Socket Events** (if needed)
   - Emit events in `src/backend/api/socket_chat.py` when tool completes
   - Add event listeners in `src/frontend/src/api/socket.ts`

## System Prompt Updates

The model will NOT use tools unless the system prompt explicitly tells it to:
- Add examples showing WHEN to use the tool
- Use imperative language: "ALWAYS call X when...", "WHENEVER you see Y, you MUST..."
- Provide concrete examples with real use cases
- Put critical instructions in dedicated sections with headers

## State Management Pitfalls

**Pass-by-Reference Bug**: When tools modify `session_state` dicts that are the SAME object as orchestrator state, DO NOT also append in orchestrator update methods. This creates duplicates.

Example of the bug:
```python
# In tool.execute()
session_state["workflow_analysis"]["inputs"].append(input_obj)  # Modifies orchestrator state

# In orchestrator._update_analysis_from_tool_result() - WRONG!
self.workflow_analysis["inputs"].append(input_obj)  # Duplicate append!
```

Solution: Since `session_state["workflow_analysis"]` IS `self.workflow_analysis`, the tool already modified it. Don't append again.

**MCP Pass-by-Value Bug**: When orchestrator uses MCP mode, `session_state` is passed **by value** (over HTTP) to the MCP server, not by reference. Tool modifications to `session_state` stay in MCP server memory and never sync back to orchestrator.

Example of the bug:
```python
# In orchestrator.run_tool() (MCP mode)
mcp_args = {
    **args,
    "session_state": {
        "workflow_analysis": self.workflow_analysis,  # Passed by value over HTTP!
    }
}
data = call_mcp_tool(tool_name, mcp_args)  # Tool modifies the copy, not original

# self.workflow_analysis is NEVER updated - changes lost!
```

Solution: Tools must return the modified state in their response, and orchestrator must sync it back:
```python
# In tool.execute()
workflow_analysis["inputs"].append(input_obj)
return {
    "success": True,
    "workflow_analysis": workflow_analysis,  # Return modified state
}

# In orchestrator._update_analysis_from_tool_result()
if "workflow_analysis" in result:
    self.workflow_analysis["inputs"] = result["workflow_analysis"]["inputs"]
```

This ensures state persists correctly in both direct and MCP modes.

## Testing Strategy

ALWAYS write integration tests that test the FULL flow:
1. Tool execution in isolation
2. Tool execution through `orchestrator.run_tool()`
3. Multiple sequential tool calls
4. State synchronization between tool and orchestrator

Use tests to validate hypotheses about bugs before attempting fixes.