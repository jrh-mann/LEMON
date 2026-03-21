"""Event types for the LEMON event bus.

Constants used by EventBus subscribers to identify event categories.
"""

# Tool lifecycle events — emitted during orchestrator tool execution
TOOL_STARTED = "tool_started"
TOOL_COMPLETED = "tool_completed"
TOOL_BATCH_COMPLETE = "tool_batch_complete"

# Workflow state events — emitted when workflow data changes
WORKFLOW_UPDATED = "workflow_updated"
ANALYSIS_UPDATED = "analysis_updated"
WORKFLOW_SAVED = "workflow_saved"

# Chat/interaction events — emitted for UI-facing state changes
PLAN_UPDATED = "plan_updated"
QUESTION_ASKED = "question_asked"
NODE_HIGHLIGHTED = "node_highlighted"
