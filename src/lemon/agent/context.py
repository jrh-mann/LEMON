"""Conversation context management.

This module manages the state of conversations with the orchestrator,
including message history, active sessions, and working context.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4


def generate_conversation_id() -> str:
    """Generate a unique conversation ID."""
    return uuid4().hex[:16]


def generate_message_id() -> str:
    """Generate a unique message ID."""
    return uuid4().hex[:12]


class MessageRole(str, Enum):
    """Role of a message sender."""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


@dataclass
class ToolCall:
    """Record of a tool call made by the assistant."""
    tool_name: str
    arguments: Dict[str, Any]
    result: Optional[Dict[str, Any]] = None


@dataclass
class Message:
    """A message in the conversation."""
    id: str
    role: MessageRole
    content: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    tool_calls: List[ToolCall] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "role": self.role.value,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "tool_calls": [
                {
                    "tool_name": tc.tool_name,
                    "arguments": tc.arguments,
                    "result": tc.result,
                }
                for tc in self.tool_calls
            ],
        }


@dataclass
class WorkingContext:
    """Context about what the user is currently working on.

    This tracks the "working memory" of the conversation - what workflow
    is being discussed, any active validation session, etc.
    """
    current_workflow_id: Optional[str] = None
    current_workflow_name: Optional[str] = None
    validation_session_id: Optional[str] = None
    last_execution_result: Optional[Dict[str, Any]] = None
    draft_workflow: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "current_workflow_id": self.current_workflow_id,
            "current_workflow_name": self.current_workflow_name,
            "validation_session_id": self.validation_session_id,
            "has_draft": self.draft_workflow is not None,
        }


@dataclass
class ConversationContext:
    """Full context for a conversation with the orchestrator.

    This includes:
    - Message history
    - Working context (current workflow, validation session, etc.)
    - User preferences and session metadata
    """
    id: str = field(default_factory=generate_conversation_id)
    messages: List[Message] = field(default_factory=list)
    working: WorkingContext = field(default_factory=WorkingContext)
    user_id: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Configuration
    max_history_length: int = 50  # Maximum messages to keep

    def add_message(
        self,
        role: MessageRole,
        content: str,
        tool_calls: Optional[List[ToolCall]] = None,
    ) -> Message:
        """Add a message to the conversation."""
        message = Message(
            id=generate_message_id(),
            role=role,
            content=content,
            tool_calls=tool_calls or [],
        )
        self.messages.append(message)
        self.updated_at = datetime.now(timezone.utc)

        # Trim history if needed
        if len(self.messages) > self.max_history_length:
            # Keep system messages and most recent messages
            system_messages = [m for m in self.messages if m.role == MessageRole.SYSTEM]
            other_messages = [m for m in self.messages if m.role != MessageRole.SYSTEM]
            keep_count = self.max_history_length - len(system_messages)
            self.messages = system_messages + other_messages[-keep_count:]

        return message

    def add_user_message(self, content: str) -> Message:
        """Add a user message."""
        return self.add_message(MessageRole.USER, content)

    def add_assistant_message(
        self,
        content: str,
        tool_calls: Optional[List[ToolCall]] = None,
    ) -> Message:
        """Add an assistant message."""
        return self.add_message(MessageRole.ASSISTANT, content, tool_calls)

    def add_system_message(self, content: str) -> Message:
        """Add a system message."""
        return self.add_message(MessageRole.SYSTEM, content)

    def add_tool_result(self, tool_name: str, result: Dict[str, Any]) -> Message:
        """Add a tool result message."""
        content = f"Tool {tool_name} returned: {result}"
        return self.add_message(MessageRole.TOOL, content)

    def get_recent_messages(self, count: int = 10) -> List[Message]:
        """Get the most recent messages."""
        return self.messages[-count:]

    def get_messages_for_llm(self) -> List[Dict[str, Any]]:
        """Get messages formatted for LLM API.

        Returns messages in a format suitable for chat completion APIs.
        """
        result = []
        for msg in self.messages:
            entry = {
                "role": msg.role.value,
                "content": msg.content,
            }
            # Handle tool role mapping (some APIs use "function" instead)
            if msg.role == MessageRole.TOOL:
                entry["role"] = "assistant"  # Or "function" depending on API
            result.append(entry)
        return result

    def clear_history(self, keep_system: bool = True) -> None:
        """Clear conversation history."""
        if keep_system:
            self.messages = [m for m in self.messages if m.role == MessageRole.SYSTEM]
        else:
            self.messages = []
        self.updated_at = datetime.now(timezone.utc)

    def set_current_workflow(self, workflow_id: str, name: str) -> None:
        """Set the current workflow being discussed."""
        self.working.current_workflow_id = workflow_id
        self.working.current_workflow_name = name
        self.updated_at = datetime.now(timezone.utc)

    def set_validation_session(self, session_id: str) -> None:
        """Set the active validation session."""
        self.working.validation_session_id = session_id
        self.updated_at = datetime.now(timezone.utc)

    def clear_validation_session(self) -> None:
        """Clear the validation session."""
        self.working.validation_session_id = None
        self.updated_at = datetime.now(timezone.utc)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "message_count": len(self.messages),
            "working": self.working.to_dict(),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class ConversationStore:
    """In-memory store for conversation contexts."""

    def __init__(self):
        self._conversations: Dict[str, ConversationContext] = {}

    def create(self, user_id: Optional[str] = None) -> ConversationContext:
        """Create a new conversation."""
        context = ConversationContext(user_id=user_id)
        self._conversations[context.id] = context
        return context

    def get(self, conversation_id: str) -> Optional[ConversationContext]:
        """Get a conversation by ID."""
        return self._conversations.get(conversation_id)

    def delete(self, conversation_id: str) -> bool:
        """Delete a conversation."""
        if conversation_id in self._conversations:
            del self._conversations[conversation_id]
            return True
        return False

    def list_for_user(self, user_id: str) -> List[ConversationContext]:
        """List conversations for a user."""
        return [
            c for c in self._conversations.values()
            if c.user_id == user_id
        ]
