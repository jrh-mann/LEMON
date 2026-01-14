"""Tests for orchestrator."""

import pytest
from lemon.core.blocks import (
    Workflow, WorkflowMetadata, InputBlock, DecisionBlock, OutputBlock,
    Connection, InputType, Range, PortType
)
from lemon.storage.repository import InMemoryWorkflowRepository
from lemon.search.service import SearchService
from lemon.execution.executor import WorkflowExecutor
from lemon.validation.session import ValidationSessionManager
from lemon.validation.case_generator import CaseGenerator
from lemon.agent.tools import create_tool_registry
from lemon.agent.context import ConversationContext
from lemon.agent.orchestrator import Orchestrator, SYSTEM_PROMPT


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def repository() -> InMemoryWorkflowRepository:
    """Repository with test workflows."""
    repo = InMemoryWorkflowRepository()

    workflows = [
        Workflow(
            id="ckd-staging",
            metadata=WorkflowMetadata(
                name="CKD Staging",
                description="Stage chronic kidney disease based on eGFR",
                domain="nephrology",
                tags=["ckd", "staging"],
                validation_score=85.0,
                validation_count=20,
            ),
            blocks=[
                InputBlock(id="i1", name="eGFR", input_type=InputType.FLOAT, range=Range(min=0, max=200)),
                DecisionBlock(id="d1", condition="eGFR >= 60"),
                OutputBlock(id="o1", value="Mild"),
                OutputBlock(id="o2", value="Moderate-Severe"),
            ],
            connections=[
                Connection(from_block="i1", to_block="d1"),
                Connection(from_block="d1", to_block="o1", from_port=PortType.TRUE),
                Connection(from_block="d1", to_block="o2", from_port=PortType.FALSE),
            ],
        ),
        Workflow(
            id="age-check",
            metadata=WorkflowMetadata(
                name="Age Classification",
                description="Classify by age",
                domain="general",
            ),
            blocks=[
                InputBlock(id="i1", name="age", input_type=InputType.INT, range=Range(min=0, max=120)),
                DecisionBlock(id="d1", condition="age >= 18"),
                OutputBlock(id="o1", value="Adult"),
                OutputBlock(id="o2", value="Minor"),
            ],
            connections=[
                Connection(from_block="i1", to_block="d1"),
                Connection(from_block="d1", to_block="o1", from_port=PortType.TRUE),
                Connection(from_block="d1", to_block="o2", from_port=PortType.FALSE),
            ],
        ),
    ]

    for wf in workflows:
        repo.save(wf)

    return repo


@pytest.fixture
def orchestrator(repository: InMemoryWorkflowRepository) -> Orchestrator:
    """Orchestrator with all tools."""
    search = SearchService(repository)
    executor = WorkflowExecutor()
    generator = CaseGenerator(seed=42)
    session_manager = ValidationSessionManager(repository, executor, generator)

    registry = create_tool_registry(repository, search, executor, session_manager)
    return Orchestrator(registry)


@pytest.fixture
def context() -> ConversationContext:
    """Fresh conversation context."""
    return ConversationContext()


# -----------------------------------------------------------------------------
# Test: Orchestrator Initialization
# -----------------------------------------------------------------------------

class TestOrchestratorInit:
    """Tests for orchestrator initialization."""

    def test_get_system_prompt(self, orchestrator: Orchestrator):
        """Should return system prompt."""
        prompt = orchestrator.get_system_prompt()

        assert "LEMON Orchestrator" in prompt
        assert "search" in prompt.lower()
        assert "validation" in prompt.lower()

    def test_get_tool_schemas(self, orchestrator: Orchestrator):
        """Should return tool schemas."""
        schemas = orchestrator.get_tool_schemas()

        assert len(schemas) > 0
        names = {s["name"] for s in schemas}
        assert "search_library" in names
        assert "execute_workflow" in names


# -----------------------------------------------------------------------------
# Test: Direct Tool Execution
# -----------------------------------------------------------------------------

class TestDirectToolExecution:
    """Tests for direct tool execution (bypassing NL processing)."""

    def test_execute_tool_success(self, orchestrator: Orchestrator):
        """Should execute tool directly."""
        result = orchestrator.execute_tool("list_domains", {})

        assert result.success is True
        assert "domains" in result.data

    def test_execute_tool_with_args(self, orchestrator: Orchestrator):
        """Should pass arguments to tool."""
        result = orchestrator.execute_tool("search_library", {"domain": "nephrology"})

        assert result.success is True
        workflows = result.data["workflows"]
        assert len(workflows) == 1

    def test_execute_unknown_tool(self, orchestrator: Orchestrator):
        """Should return error for unknown tool."""
        result = orchestrator.execute_tool("nonexistent", {})

        assert result.success is False
        assert "Unknown tool" in result.error


# -----------------------------------------------------------------------------
# Test: Message Processing (Rule-Based)
# -----------------------------------------------------------------------------

class TestMessageProcessing:
    """Tests for rule-based message processing."""

    def test_search_intent(self, orchestrator: Orchestrator, context: ConversationContext):
        """Should handle search intent."""
        response = orchestrator.process_message(context, "Find nephrology workflows")

        assert "CKD" in response.message or "nephrology" in response.message.lower()
        assert len(response.tool_calls) > 0
        assert response.tool_calls[0].tool_name == "search_library"

    def test_help_intent(self, orchestrator: Orchestrator, context: ConversationContext):
        """Should handle help intent."""
        response = orchestrator.process_message(context, "Help me")

        assert "search" in response.message.lower()
        assert "validate" in response.message.lower()

    def test_list_domains_intent(self, orchestrator: Orchestrator, context: ConversationContext):
        """Should handle domains intent."""
        response = orchestrator.process_message(context, "What domains are available?")

        assert len(response.tool_calls) > 0
        assert response.tool_calls[0].tool_name == "list_domains"

    def test_validate_intent_no_workflow(self, orchestrator: Orchestrator, context: ConversationContext):
        """Should ask for workflow when validating without context."""
        response = orchestrator.process_message(context, "Validate the workflow")

        assert "specify" in response.message.lower() or "which" in response.message.lower()

    def test_validate_intent_with_workflow(self, orchestrator: Orchestrator, context: ConversationContext):
        """Should start validation when workflow is set."""
        context.set_current_workflow("age-check", "Age Classification")

        response = orchestrator.process_message(context, "Validate this workflow")

        assert "validation" in response.message.lower()
        assert len(response.tool_calls) > 0
        assert response.tool_calls[0].tool_name == "start_validation"

    def test_default_response(self, orchestrator: Orchestrator, context: ConversationContext):
        """Should provide guidance for unclear messages."""
        response = orchestrator.process_message(context, "xyzzy")

        assert "try" in response.message.lower()

    def test_messages_added_to_context(self, orchestrator: Orchestrator, context: ConversationContext):
        """Should add messages to context."""
        orchestrator.process_message(context, "Hello")

        assert len(context.messages) == 2  # User message + assistant response
        assert context.messages[0].content == "Hello"


# -----------------------------------------------------------------------------
# Test: Validation Flow
# -----------------------------------------------------------------------------

class TestValidationFlow:
    """Tests for validation session flow."""

    def test_validation_session_flow(self, orchestrator: Orchestrator, context: ConversationContext):
        """Should handle validation session from start to answer."""
        # Set workflow and start validation
        context.set_current_workflow("age-check", "Age Classification")
        start_response = orchestrator.process_message(context, "Validate this workflow")

        assert context.working.validation_session_id is not None
        assert "validation_started" in start_response.context_updates

        # Submit an answer
        answer_response = orchestrator.process_message(context, "Adult")

        # Should have recorded match/mismatch
        assert "match" in answer_response.message.lower() or "mismatch" in answer_response.message.lower()


# -----------------------------------------------------------------------------
# Test: Context Updates
# -----------------------------------------------------------------------------

class TestContextUpdates:
    """Tests for context update tracking."""

    def test_validation_started_update(self, orchestrator: Orchestrator, context: ConversationContext):
        """Should indicate validation started in updates."""
        context.set_current_workflow("age-check", "Age Classification")
        response = orchestrator.process_message(context, "Validate this")

        assert response.context_updates.get("validation_started") is True

    def test_tool_calls_recorded(self, orchestrator: Orchestrator, context: ConversationContext):
        """Should record tool calls in response."""
        response = orchestrator.process_message(context, "List all domains")

        assert len(response.tool_calls) > 0
        assert response.tool_calls[0].result is not None


# -----------------------------------------------------------------------------
# Test: Response Format
# -----------------------------------------------------------------------------

class TestResponseFormat:
    """Tests for response formatting."""

    def test_response_to_dict(self, orchestrator: Orchestrator, context: ConversationContext):
        """Should convert response to dictionary."""
        response = orchestrator.process_message(context, "Help")
        d = response.to_dict()

        assert "message" in d
        assert "tool_calls" in d
        assert "context_updates" in d

    def test_search_results_formatted(self, orchestrator: Orchestrator, context: ConversationContext):
        """Should format search results nicely."""
        response = orchestrator.process_message(context, "Find nephrology workflows")

        assert "CKD Staging" in response.message
        # Should include workflow ID for reference
        assert "ckd-staging" in response.message


# -----------------------------------------------------------------------------
# Test: Async Chat (with LLM)
# -----------------------------------------------------------------------------

class TestAsyncChat:
    """Tests for async chat (falls back to rule-based without LLM)."""

    @pytest.mark.skip(reason="Requires pytest-asyncio")
    async def test_chat_without_llm(self, orchestrator: Orchestrator, context: ConversationContext):
        """Should fall back to rule-based without LLM."""
        response = await orchestrator.chat(context, "Help")

        # Should still work (falls back to process_message)
        assert "search" in response.message.lower()
