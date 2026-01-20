NEVER create markdown files unless instructed

Work atomically, prior to every change define tests and criteria for their acceptance, once these are passed, commit that change.

Make minimal changes to the codebase, work in small, surgical ways, comment your code, to explain what each component does, do not introduce tech debt.

Fail loudly, do not have errors propagate, we are interested in knowing exactly what is going on at all times, if an error occurs it should be realised.

Work within the grand vision of the project, all components should be with reference to that.

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

## Testing Strategy

ALWAYS write integration tests that test the FULL flow:
1. Tool execution in isolation
2. Tool execution through `orchestrator.run_tool()`
3. Multiple sequential tool calls
4. State synchronization between tool and orchestrator

Use tests to validate hypotheses about bugs before attempting fixes.