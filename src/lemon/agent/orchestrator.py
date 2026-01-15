"""Orchestrator agent for LEMON.

The orchestrator is the main AI-powered interface that helps users:
- Create workflows through natural language conversation
- Search and discover existing workflows
- Compose workflows from validated components
- Run Tinder-style validation sessions

The orchestrator uses a tool-based approach (inspired by KernelEvolve)
rather than vector embeddings, allowing structured interaction with the
workflow library.
"""

from __future__ import annotations

import json
import os
import httpx
from dataclasses import dataclass
from datetime import datetime, date
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from pathlib import Path


def json_serialize(obj: Any) -> str:
    """JSON serialize with datetime support."""
    def default(o):
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")
    return json.dumps(obj, default=default)

from lemon.agent.context import ConversationContext, MessageRole, ToolCall
from lemon.agent.tools import ToolRegistry, ToolResult
from typing import Callable

# Type for progress callback: (event_type, data) -> None
ProgressCallback = Callable[[str, dict], None]

# Load .env file
def load_env():
    """Load environment variables from .env file."""
    env_path = Path(__file__).parent.parent.parent.parent / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    os.environ.setdefault(key, value)

load_env()

if TYPE_CHECKING:
    pass


SYSTEM_PROMPT = """You are the LEMON Orchestrator, an AI assistant that helps clinicians create, discover, and validate clinical decision support workflows.

## Your Capabilities

You have access to tools to:
1. **Search the library** - Find existing validated workflows by domain, tags, inputs, or text search
2. **Get workflow details** - Understand a specific workflow's inputs, outputs, and logic
3. **Execute workflows** - Run a workflow with specific patient data to get a recommendation
4. **Start validation** - Begin a Tinder-style validation session where the user validates test cases
5. **Submit validation** - Record the user's expected output for each validation case
6. **Create workflows** - Build new workflows from specifications (which then need validation)
7. **List domains** - See what medical specialties have workflows available
8. **Edit workflows** - Modify existing workflows:
   - `get_current_workflow` - See the current state of a workflow
   - `add_block` - Add input, decision, output, or workflow_ref blocks
   - `update_block` - Modify a block's properties (label, condition, type)
   - `delete_block` - Remove a block and its connections
   - `connect_blocks` - Create edges between blocks
   - `disconnect_blocks` - Remove edges

## Editing Workflows

When the user has a workflow open and asks you to edit it, use the editing tools.
The current workflow ID will be provided in the context. Use this ID for all editing operations.

Examples of edit requests:
- "Add an input for patient age" → use `add_block` with the current workflow ID
- "Change the first decision to check if age > 70" → use `update_block`
- "Connect the age check to the high-risk output" → use `connect_blocks`
- "Delete the second decision" → use `delete_block`

Always use `get_current_workflow` first if you're unsure of the current state.

## Analyzing Flowchart Images

**IMPORTANT**: When you see a flowchart image, you MUST:
1. Actually READ the text visible in the image (node labels, decision questions, output names)
2. Extract the EXACT text from each box/shape - do NOT make up generic names like "input0" or "d1"
3. Use the actual clinical/medical terms shown in the flowchart

When analyzing an uploaded image, respond with EXACTLY this format:

### Inputs
| Name | Type | Description |
|------|------|-------------|
| eGFR | float | Kidney function measure |
| Age | int | Patient age in years |

### Outputs
- **Stage 1** — Normal kidney function
- **Stage 2** — Mildly reduced

---

**Clarifications:**

1. First question or ambiguity you need resolved
2. Second question (if any)

Or if none: "None — ready to proceed when you confirm."

IMPORTANT RULES:
- Do NOT show decision points or internal logic — save that for workflow creation
- Do NOT show "Key Considerations" — that's your internal reasoning
- ALWAYS include the clarifications section after a horizontal rule
- Use em-dashes (—) not hyphens for output descriptions
- Keep it clean and scannable
- If the user provided specific focus areas, silently incorporate them (don't echo them back)

### After User Confirms
Once the user confirms (says "yes", "correct", "continue", "looks good", etc.), call `create_workflow` with the full structure including decisions and connections.

### After Creating a Workflow
When `create_workflow` succeeds, respond with a brief, friendly confirmation like:

"Workflow created! I've built **[Name]** with [X] inputs, [Y] decision points, and [Z] possible outputs. It's now displayed on the canvas — you can click the nodes to inspect or edit them."

**IMPORTANT**: Do NOT include JSON, code blocks, or raw data in your response. The workflow is rendered visually on the canvas — the user doesn't need to see the technical structure.

### Block Types
- **Input blocks**: Data that enters the workflow. Infer the type:
  - `int` or `float` for numeric values (age, eGFR, blood pressure)
  - `bool` for yes/no inputs
  - `enum` for categorical choices (include possible values)
  - `string` for free text
- **Decision blocks**: Diamond shapes with yes/no branches. Condition must be valid Python (e.g., `eGFR >= 90`, `age > 65 and diabetes == True`)
- **Output blocks**: Final outcomes/recommendations (terminal nodes)

### Connection Rules
- Each decision has TWO outgoing connections: `from_port: "true"` (Yes) and `from_port: "false"` (No)
- Inputs connect to decisions or directly to outputs
- Follow arrows in the image to determine flow

### Example create_workflow call
```json
{
  "name": "CKD Staging",
  "description": "Stages chronic kidney disease based on eGFR",
  "inputs": [{"name": "eGFR", "type": "float", "range": {"min": 0, "max": 200}}],
  "decisions": [{"id": "d1", "condition": "eGFR >= 90", "description": "Normal function?"}],
  "outputs": ["Normal kidney function", "Reduced kidney function"],
  "connections": [
    {"from_block": "input0", "to_block": "d1"},
    {"from_block": "d1", "to_block": "output0", "from_port": "true"},
    {"from_block": "d1", "to_block": "output1", "from_port": "false"}
  ]
}
```

**CRITICAL FORMAT RULES:**
- inputs: MUST have `"name"` with a readable label extracted from the image (e.g., "Patient Age", "eGFR Value") - NEVER use generic names like "input0"
- decisions: MUST have `"description"` with the actual question/condition text from the image (e.g., "Is eGFR >= 90?") - this becomes the node label
- outputs: Strings with the actual outcome text from the image (e.g., "Refer to nephrologist", "Continue monitoring")
- connections: ALWAYS include connections based on the arrows in the image!
  - Follow the arrows in the flowchart to determine connections
  - Every decision should have both true and false paths
  - Every path should eventually lead to an output

**DO NOT** use placeholder names like "input0", "d1", "output0" as labels. Read the actual text from the flowchart image!

### Limitations
Supports: Linear/branching decision trees, numeric comparisons, boolean logic, multiple inputs/outputs
Does NOT support: Loops, parallel execution, external APIs, complex math formulas

## Philosophy

- **Validated workflows are trustworthy**: Workflows with high validation scores (80%+) and many validations (10+) have been verified by domain experts
- **Composition over creation**: When possible, compose new workflows from existing validated components
- **Human-in-the-loop validation**: New workflows need human validation before they're considered reliable
- **Transparency**: Always explain what a workflow does and its validation status

## Guidelines

1. When a user wants to create something, first search for existing workflows that might help
2. Explain validation scores and what they mean for trustworthiness
3. For complex requests, break them down into smaller, composable workflows
4. Always recommend validation for new or modified workflows
5. Be clear about limitations and when workflows shouldn't be used as sole decision makers

## Response Format

- Be concise but helpful
- When you successfully create a workflow, respond with: "I've created the workflow '[name]'. It's now ready for review."
- If you need clarification, ask specific questions about what's unclear
- For medical workflows, emphasize that these are decision support tools, not replacements for clinical judgment
"""


@dataclass
class OrchestratorResponse:
    """Response from the orchestrator."""
    message: str
    tool_calls: List[ToolCall]
    context_updates: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message": self.message,
            "tool_calls": [
                {
                    "tool_name": tc.tool_name,
                    "arguments": tc.arguments,
                    "result": tc.result,
                }
                for tc in self.tool_calls
            ],
            "context_updates": self.context_updates,
        }


class Orchestrator:
    """Main orchestrator agent.

    The orchestrator coordinates user interactions with the workflow system.
    It uses Azure OpenAI for natural language understanding and tool use.

    Usage:
        orchestrator = Orchestrator(tool_registry)
        response = orchestrator.process_message(context, "Find nephrology workflows")
    """

    def __init__(
        self,
        tool_registry: ToolRegistry,
    ):
        """Initialize orchestrator.

        Args:
            tool_registry: Registry of available tools.
        """
        self.tools = tool_registry

        # Azure OpenAI configuration from environment
        self.api_key = os.environ.get("API_KEY")
        self.endpoint = os.environ.get("ENDPOINT")
        self.deployment = os.environ.get("DEPLOYMENT_NAME", "gpt-5")

        # Check if we have valid Azure config
        self.has_llm = bool(self.api_key and self.endpoint)

    def get_system_prompt(self, current_workflow_id: Optional[str] = None) -> str:
        """Get the system prompt for the orchestrator.

        Args:
            current_workflow_id: ID of the workflow currently open in the editor.
        """
        prompt = SYSTEM_PROMPT

        if current_workflow_id:
            prompt += f"\n\n## Current Context\n\nThe user currently has workflow `{current_workflow_id}` open in the editor. When they ask you to edit the workflow, use this ID for all editing operations (add_block, update_block, delete_block, connect_blocks, disconnect_blocks)."

        return prompt

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        """Get schemas for all available tools."""
        return self.tools.get_schemas()

    def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> ToolResult:
        """Execute a tool directly.

        This bypasses natural language processing and directly invokes a tool.
        Useful for programmatic access or testing.

        Args:
            tool_name: Name of the tool to execute.
            arguments: Arguments for the tool.

        Returns:
            ToolResult with success status and data/error.
        """
        return self.tools.execute(tool_name, arguments)

    def _build_openai_tools(self) -> List[Dict[str, Any]]:
        """Convert tool schemas to OpenAI function calling format."""
        schemas = self.tools.get_schemas()
        openai_tools = []

        for schema in schemas:
            tool = {
                "type": "function",
                "function": {
                    "name": schema["name"],
                    "description": schema.get("description", ""),
                    "parameters": {
                        "type": "object",
                        "properties": schema.get("parameters", {}).get("properties", {}),
                        "required": schema.get("parameters", {}).get("required", []),
                    },
                },
            }
            openai_tools.append(tool)

        return openai_tools

    def _build_messages(
        self,
        context: ConversationContext,
        image: Optional[str] = None,
        current_workflow_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Build message history for OpenAI API.

        Args:
            context: Conversation context with message history.
            image: Optional base64 data URL for the current message (vision).
            current_workflow_id: ID of workflow currently open in editor.
        """
        messages = [{"role": "system", "content": self.get_system_prompt(current_workflow_id)}]

        for i, msg in enumerate(context.messages):
            if msg.role == MessageRole.USER:
                # Check if this is the last user message and we have an image
                is_last_user_msg = (i == len(context.messages) - 1)

                if is_last_user_msg and image:
                    # Multimodal message with image
                    messages.append({
                        "role": "user",
                        "content": [
                            {"type": "text", "text": msg.content},
                            {"type": "image_url", "image_url": {"url": image}},
                        ]
                    })
                else:
                    messages.append({"role": "user", "content": msg.content})
            elif msg.role == MessageRole.ASSISTANT:
                messages.append({"role": "assistant", "content": msg.content})

        return messages

    def _call_azure_openai(self, messages: List[Dict], tools: List[Dict]) -> Dict:
        """Call Azure OpenAI API."""
        headers = {
            "Content-Type": "application/json",
            "api-key": self.api_key,
        }

        payload = {
            "messages": messages,
            "max_completion_tokens": 64000,  # High limit for complex image analysis and workflow JSON
        }

        # Only include tools if we have them
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        with httpx.Client(timeout=600.0) as client:  # 10 minutes for image analysis
            response = client.post(
                self.endpoint,
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            return response.json()

    def process_message(
        self,
        context: ConversationContext,
        user_message: str,
        image: Optional[str] = None,
        current_workflow_id: Optional[str] = None,
        on_progress: Optional[ProgressCallback] = None,
    ) -> OrchestratorResponse:
        """Process a user message using Azure OpenAI with tools.

        Args:
            context: The conversation context.
            user_message: The user's message.
            image: Optional base64 data URL for vision analysis.
            current_workflow_id: ID of workflow currently open in editor (for editing context).
            on_progress: Optional callback for progress updates (event_type, data).
                         Events: 'thinking', 'tool_started', 'tool_completed'

        Returns:
            OrchestratorResponse with message, tool calls, and context updates.
        """
        # Add user message to context
        context.add_user_message(user_message)

        tool_calls_list = []
        context_updates = {}

        def emit_progress(event: str, data: dict):
            """Emit progress if callback provided."""
            if on_progress:
                on_progress(event, data)

        # If no LLM config, fall back to simple mode
        if not self.has_llm:
            return self._process_message_simple(context, user_message, tool_calls_list, context_updates)

        try:
            # Emit thinking status
            emit_progress('thinking', {'status': 'Analyzing your request...'})

            # Build messages and tools for OpenAI (pass image for vision and workflow context)
            messages = self._build_messages(context, image=image, current_workflow_id=current_workflow_id)
            tools = self._build_openai_tools()

            # If there's an image, indicate we're analyzing it
            if image:
                emit_progress('thinking', {'status': 'Analyzing image...'})

            # Call Azure OpenAI
            response = self._call_azure_openai(messages, tools)
            choice = response["choices"][0]
            message = choice["message"]

            # Process response - may need multiple rounds for tool calls
            while message.get("tool_calls"):
                # Add assistant message with tool calls
                messages.append(message)

                # Execute each tool call
                for tc in message["tool_calls"]:
                    func = tc["function"]
                    tool_name = func["name"]
                    try:
                        arguments = json.loads(func["arguments"])
                    except json.JSONDecodeError:
                        arguments = {}

                    # Emit tool started event
                    emit_progress('tool_started', {
                        'tool': tool_name,
                        'status': self._get_tool_status_message(tool_name),
                    })

                    # Execute the tool
                    result = self.execute_tool(tool_name, arguments)

                    # Emit tool completed event
                    emit_progress('tool_completed', {
                        'tool': tool_name,
                        'success': result.success,
                    })

                    tool_calls_list.append(ToolCall(
                        tool_name=tool_name,
                        arguments=arguments,
                        result=result.data if result.success else {"error": result.error},
                    ))

                    # Add tool result message (filter out large data like nodes/edges)
                    llm_result = result.data if result.success else {"error": result.error}
                    if isinstance(llm_result, dict):
                        # Remove frontend-only fields that the LLM doesn't need
                        llm_result = {k: v for k, v in llm_result.items() if k not in ("nodes", "edges")}

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": json_serialize(llm_result),
                    })

                # Emit thinking again before next LLM call
                emit_progress('thinking', {'status': 'Processing results...'})

                # Continue conversation
                response = self._call_azure_openai(messages, tools)
                choice = response["choices"][0]
                message = choice["message"]

            # Extract final text response
            final_text = message.get("content", "")

            # Add assistant response to context
            context.add_assistant_message(final_text, tool_calls_list)

            return OrchestratorResponse(
                message=final_text,
                tool_calls=tool_calls_list,
                context_updates=context_updates,
            )

        except Exception as e:
            error_msg = f"Error communicating with AI: {str(e)}"
            context.add_assistant_message(error_msg, [])
            return OrchestratorResponse(
                message=error_msg,
                tool_calls=[],
                context_updates={},
            )

    def _get_tool_status_message(self, tool_name: str) -> str:
        """Get a human-readable status message for a tool."""
        tool_messages = {
            'search_library': 'Searching workflow library...',
            'get_workflow': 'Loading workflow details...',
            'create_workflow': 'Creating workflow...',
            'execute_workflow': 'Running workflow...',
            'start_validation': 'Starting validation session...',
            'submit_validation': 'Recording validation...',
            'list_domains': 'Listing available domains...',
            'add_block': 'Adding block to workflow...',
            'update_block': 'Updating block...',
            'delete_block': 'Removing block...',
            'connect_blocks': 'Connecting blocks...',
            'disconnect_blocks': 'Disconnecting blocks...',
            'get_current_workflow': 'Getting current workflow state...',
        }
        return tool_messages.get(tool_name, f'Running {tool_name}...')

    def _process_message_simple(
        self,
        context: ConversationContext,
        user_message: str,
        tool_calls: List[ToolCall],
        context_updates: Dict[str, Any],
    ) -> OrchestratorResponse:
        """Fallback simple message processing without LLM.

        Used when no Anthropic API key is available.
        """
        message_lower = user_message.lower()
        response_message = ""

        # Check for validation session in progress
        if context.working.validation_session_id:
            result = self.execute_tool("submit_validation", {
                "session_id": context.working.validation_session_id,
                "answer": user_message,
            })

            tool_calls.append(ToolCall(
                tool_name="submit_validation",
                arguments={"session_id": context.working.validation_session_id, "answer": user_message},
                result=result.to_dict(),
            ))

            if result.success:
                data = result.data
                if data.get("matched"):
                    response_message = "Correct! Your answer matched the workflow output."
                else:
                    response_message = (
                        f"Mismatch. You said '{data.get('user_answer')}' "
                        f"but the workflow outputs '{data.get('workflow_output')}'."
                    )

                if data.get("session_complete"):
                    score = data.get("current_score", {})
                    response_message += (
                        f"\n\nValidation complete! Score: {score.get('score', 0):.1f}% "
                        f"({score.get('matches', 0)}/{score.get('total', 0)} matches)"
                    )
                    context_updates["validation_complete"] = True
                    context.clear_validation_session()
                else:
                    next_case = data.get("next_case")
                    if next_case:
                        response_message += f"\n\nNext case: {next_case.get('inputs')}"
            else:
                response_message = f"Error: {result.error}"

        # Search intent
        elif any(word in message_lower for word in ["find", "search", "show", "list"]):
            args = {}
            domains = ["nephrology", "cardiology", "diabetes", "ckd"]
            for domain in domains:
                if domain in message_lower:
                    args["domain"] = domain
                    break
            if "validated" in message_lower:
                args["validated_only"] = True
            if not args:
                args["text"] = user_message

            result = self.execute_tool("search_library", args)
            tool_calls.append(ToolCall(
                tool_name="search_library",
                arguments=args,
                result=result.to_dict(),
            ))

            if result.success:
                workflows = result.data.get("workflows", [])
                if workflows:
                    response_message = f"Found {len(workflows)} workflow(s):\n\n"
                    for wf in workflows[:5]:
                        score = wf.get("validation_score", 0)
                        count = wf.get("validation_count", 0)
                        status = "validated" if wf.get("is_validated") else f"{score:.0f}% ({count} validations)"
                        response_message += f"- **{wf.get('name')}** ({wf.get('id')}): {status}\n"
                else:
                    response_message = "No workflows found matching your criteria."
            else:
                response_message = f"Search failed: {result.error}"

        # Help intent
        elif any(word in message_lower for word in ["help", "how", "what can"]):
            response_message = (
                "I can help you with:\n\n"
                "- **Search**: Find workflows by domain, tags, or description\n"
                "- **Details**: Get full information about a workflow\n"
                "- **Execute**: Run a workflow with specific inputs\n"
                "- **Validate**: Start a validation session to verify a workflow\n"
                "- **Create**: Build a new workflow from specifications\n\n"
                "Try: 'Find nephrology workflows' or 'Show validated workflows'\n\n"
                "**Note**: Configure API_KEY and ENDPOINT in .env for full AI capabilities."
            )

        # Default
        else:
            response_message = (
                "I'm running in limited mode (no LLM configured). "
                "Check API_KEY and ENDPOINT in .env for full AI capabilities.\n\n"
                "Available commands:\n"
                "- 'Find [domain] workflows'\n"
                "- 'Show validated workflows'\n"
                "- 'Help'"
            )

        context.add_assistant_message(response_message, tool_calls)

        return OrchestratorResponse(
            message=response_message,
            tool_calls=tool_calls,
            context_updates=context_updates,
        )

