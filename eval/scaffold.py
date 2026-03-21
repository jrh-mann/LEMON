"""Scaffold: swappable agent pipeline configuration.

The scaffold defines HOW the agent runs — system prompt, user message,
tool behavior, thinking budget. Swap scaffolds to measure improvements
without touching the harness.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from src.backend.tools.core import Tool, ToolParameter


# ---------------------------------------------------------------------------
# MockAskQuestion — replaces ask_question in eval mode
# ---------------------------------------------------------------------------


class MockAskQuestion(Tool):
    """Stub for ask_question that auto-answers without user interaction.

    In eval mode the model can't ask the user for clarification. This tool
    returns a canned response telling the model to proceed with its best
    interpretation.
    """

    name = "ask_question"
    description = (
        "Ask the user one or more clarification questions. "
        "(Eval mode: auto-answered — no user present.)"
    )
    parameters = [
        ToolParameter(
            name="questions",
            type="array",
            description="Array of questions.",
            required=True,
            items={"type": "object"},
        ),
    ]

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        """Return a canned response telling the model to use its best judgment."""
        questions = args.get("questions", [])
        return {
            "success": True,
            "action": "question_auto_answered",
            "message": (
                "No user is available for clarification (evaluation mode). "
                "Use your best judgment based on what you can see in the image. "
                "If a value is ambiguous, pick the most reasonable interpretation."
            ),
            "questions_received": len(questions) if isinstance(questions, list) else 0,
        }


# ---------------------------------------------------------------------------
# Scaffold configuration
# ---------------------------------------------------------------------------


@dataclass
class Scaffold:
    """Configuration for how the agent pipeline runs.

    Attributes:
        user_message: The initial message sent alongside the image.
        thinking_budget: Optional extended thinking token budget.
            None = no extended thinking.
        system_prompt_fn: Optional override for the system prompt builder.
            Receives the same kwargs as build_system_prompt(). If None,
            the default build_system_prompt() is used.
        refinement_messages: Follow-up messages sent after the initial
            extraction. Each triggers an additional orchestrator.respond()
            call with full tool access and conversation history.
    """

    user_message: str = (
        "Extract this workflow image into a structured workflow. "
        "Follow the Image-to-Workflow Protocol exactly."
    )
    # Default matches the frontend's thinking_budget=50_000.
    thinking_budget: Optional[int] = 50_000
    system_prompt_fn: Optional[Callable[..., str]] = field(default=None, repr=False)
    refinement_messages: List[str] = field(default_factory=list)


# Pre-built scaffold configurations for common experiments.

# Default scaffold matches the frontend exactly (thinking_budget=50k).
DEFAULT_SCAFFOLD = Scaffold()

# No-thinking scaffold for cost comparison experiments.
NO_THINKING_SCAFFOLD = Scaffold(
    thinking_budget=None,
)

# Refinement scaffold: after extraction, ask the model to review and simplify.
# Generic instruction — no workflow-specific content to avoid Goodharting.
REFINEMENT_SCAFFOLD = Scaffold(
    refinement_messages=[
        "Review the workflow you just built against the image. "
        "Remove any nodes that aren't decision points or meaningful actions "
        "— intermediate steps that just describe what happens next should be "
        "merged. Verify every edge matches the arrows in the image.",
    ],
)
