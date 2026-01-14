"""Tests for agent tools."""

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
from lemon.agent.tools import (
    ToolRegistry,
    ToolResult,
    ToolParameter,
    SearchLibraryTool,
    GetWorkflowDetailsTool,
    ExecuteWorkflowTool,
    StartValidationTool,
    SubmitValidationTool,
    ListDomainsTool,
    CreateWorkflowTool,
    create_tool_registry,
)


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def repository() -> InMemoryWorkflowRepository:
    """Repository with test workflows."""
    repo = InMemoryWorkflowRepository()

    # Add test workflows
    workflows = [
        Workflow(
            id="ckd-staging",
            metadata=WorkflowMetadata(
                name="CKD Staging",
                description="Stage chronic kidney disease based on eGFR",
                domain="nephrology",
                tags=["ckd", "staging", "egfr"],
                validation_score=85.0,
                validation_count=20,
            ),
            blocks=[
                InputBlock(id="i1", name="eGFR", input_type=InputType.FLOAT, range=Range(min=0, max=200)),
                DecisionBlock(id="d1", condition="eGFR >= 90"),
                DecisionBlock(id="d2", condition="eGFR >= 60"),
                DecisionBlock(id="d3", condition="eGFR >= 30"),
                OutputBlock(id="o1", value="Stage 1"),
                OutputBlock(id="o2", value="Stage 2"),
                OutputBlock(id="o3", value="Stage 3"),
                OutputBlock(id="o4", value="Stage 4-5"),
            ],
            connections=[
                Connection(from_block="i1", to_block="d1"),
                Connection(from_block="d1", to_block="o1", from_port=PortType.TRUE),
                Connection(from_block="d1", to_block="d2", from_port=PortType.FALSE),
                Connection(from_block="d2", to_block="o2", from_port=PortType.TRUE),
                Connection(from_block="d2", to_block="d3", from_port=PortType.FALSE),
                Connection(from_block="d3", to_block="o3", from_port=PortType.TRUE),
                Connection(from_block="d3", to_block="o4", from_port=PortType.FALSE),
            ],
        ),
        Workflow(
            id="age-check",
            metadata=WorkflowMetadata(
                name="Age Classification",
                description="Classify by age",
                domain="general",
                tags=["age", "classification"],
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
def search_service(repository: InMemoryWorkflowRepository) -> SearchService:
    """Search service."""
    return SearchService(repository)


@pytest.fixture
def executor() -> WorkflowExecutor:
    """Workflow executor."""
    return WorkflowExecutor()


@pytest.fixture
def session_manager(
    repository: InMemoryWorkflowRepository,
    executor: WorkflowExecutor,
) -> ValidationSessionManager:
    """Validation session manager."""
    generator = CaseGenerator(seed=42)
    return ValidationSessionManager(repository, executor, generator)


@pytest.fixture
def tool_registry(
    repository: InMemoryWorkflowRepository,
    search_service: SearchService,
    executor: WorkflowExecutor,
    session_manager: ValidationSessionManager,
) -> ToolRegistry:
    """Tool registry with all tools."""
    return create_tool_registry(repository, search_service, executor, session_manager)


# -----------------------------------------------------------------------------
# Test: ToolResult
# -----------------------------------------------------------------------------

class TestToolResult:
    """Tests for ToolResult."""

    def test_success_result(self):
        """Should create success result."""
        result = ToolResult(success=True, data={"key": "value"})
        assert result.success is True
        assert result.data == {"key": "value"}
        assert result.error is None

    def test_error_result(self):
        """Should create error result."""
        result = ToolResult(success=False, error="Something went wrong")
        assert result.success is False
        assert result.data is None
        assert result.error == "Something went wrong"

    def test_to_dict(self):
        """Should convert to dictionary."""
        result = ToolResult(success=True, data={"foo": "bar"})
        d = result.to_dict()
        assert d["success"] is True
        assert d["data"] == {"foo": "bar"}


# -----------------------------------------------------------------------------
# Test: ToolRegistry
# -----------------------------------------------------------------------------

class TestToolRegistry:
    """Tests for ToolRegistry."""

    def test_register_and_get(self, search_service: SearchService):
        """Should register and retrieve tools."""
        registry = ToolRegistry()
        tool = SearchLibraryTool(search_service)

        registry.register(tool)
        retrieved = registry.get("search_library")

        assert retrieved is tool

    def test_list_tools(self, tool_registry: ToolRegistry):
        """Should list all registered tools."""
        tools = tool_registry.list_tools()
        names = {t.name for t in tools}

        assert "search_library" in names
        assert "get_workflow_details" in names
        assert "execute_workflow" in names
        assert "start_validation" in names

    def test_get_schemas(self, tool_registry: ToolRegistry):
        """Should get schemas for all tools."""
        schemas = tool_registry.get_schemas()

        assert len(schemas) > 0
        for schema in schemas:
            assert "name" in schema
            assert "description" in schema
            assert "parameters" in schema

    def test_execute_unknown_tool(self, tool_registry: ToolRegistry):
        """Should return error for unknown tool."""
        result = tool_registry.execute("nonexistent", {})

        assert result.success is False
        assert "Unknown tool" in result.error


# -----------------------------------------------------------------------------
# Test: SearchLibraryTool
# -----------------------------------------------------------------------------

class TestSearchLibraryTool:
    """Tests for SearchLibraryTool."""

    def test_search_by_domain(self, tool_registry: ToolRegistry):
        """Should search by domain."""
        result = tool_registry.execute("search_library", {"domain": "nephrology"})

        assert result.success is True
        workflows = result.data["workflows"]
        assert len(workflows) == 1
        assert workflows[0]["name"] == "CKD Staging"

    def test_search_by_text(self, tool_registry: ToolRegistry):
        """Should search by text in workflow name."""
        result = tool_registry.execute("search_library", {"text": "CKD"})

        assert result.success is True
        workflows = result.data["workflows"]
        assert any("CKD" in wf["name"] for wf in workflows)

    def test_search_validated_only(self, tool_registry: ToolRegistry):
        """Should filter to validated workflows."""
        result = tool_registry.execute("search_library", {"validated_only": True})

        assert result.success is True
        workflows = result.data["workflows"]
        assert len(workflows) == 1
        assert workflows[0]["is_validated"] is True

    def test_search_by_input_name(self, tool_registry: ToolRegistry):
        """Should find workflows by input name."""
        result = tool_registry.execute("search_library", {"input_name": "eGFR"})

        assert result.success is True
        workflows = result.data["workflows"]
        assert len(workflows) == 1
        assert workflows[0]["name"] == "CKD Staging"

    def test_tool_schema(self, search_service: SearchService):
        """Should generate correct schema."""
        tool = SearchLibraryTool(search_service)
        schema = tool.to_schema()

        assert schema["name"] == "search_library"
        assert "domain" in schema["parameters"]["properties"]
        assert "text" in schema["parameters"]["properties"]


# -----------------------------------------------------------------------------
# Test: GetWorkflowDetailsTool
# -----------------------------------------------------------------------------

class TestGetWorkflowDetailsTool:
    """Tests for GetWorkflowDetailsTool."""

    def test_get_existing_workflow(self, tool_registry: ToolRegistry):
        """Should get workflow details."""
        result = tool_registry.execute("get_workflow_details", {"workflow_id": "ckd-staging"})

        assert result.success is True
        data = result.data
        assert data["id"] == "ckd-staging"
        assert data["metadata"]["name"] == "CKD Staging"
        assert len(data["inputs"]) == 1
        assert data["inputs"][0]["name"] == "eGFR"

    def test_get_nonexistent_workflow(self, tool_registry: ToolRegistry):
        """Should return error for non-existent workflow."""
        result = tool_registry.execute("get_workflow_details", {"workflow_id": "nonexistent"})

        assert result.success is False
        assert "not found" in result.error.lower()

    def test_missing_workflow_id(self, tool_registry: ToolRegistry):
        """Should require workflow_id."""
        result = tool_registry.execute("get_workflow_details", {})

        assert result.success is False
        assert "required" in result.error.lower()


# -----------------------------------------------------------------------------
# Test: ExecuteWorkflowTool
# -----------------------------------------------------------------------------

class TestExecuteWorkflowTool:
    """Tests for ExecuteWorkflowTool."""

    def test_execute_workflow(self, tool_registry: ToolRegistry):
        """Should execute workflow with valid inputs."""
        result = tool_registry.execute("execute_workflow", {
            "workflow_id": "ckd-staging",
            "inputs": {"eGFR": 45},
        })

        assert result.success is True
        assert result.data["output"] == "Stage 3"

    def test_execute_with_invalid_inputs(self, tool_registry: ToolRegistry):
        """Should validate inputs."""
        result = tool_registry.execute("execute_workflow", {
            "workflow_id": "ckd-staging",
            "inputs": {"wrong_input": 45},
        })

        assert result.success is False
        assert "invalid" in result.error.lower() or "missing" in result.error.lower()

    def test_execute_nonexistent_workflow(self, tool_registry: ToolRegistry):
        """Should return error for non-existent workflow."""
        result = tool_registry.execute("execute_workflow", {
            "workflow_id": "nonexistent",
            "inputs": {},
        })

        assert result.success is False
        assert "not found" in result.error.lower()


# -----------------------------------------------------------------------------
# Test: StartValidationTool
# -----------------------------------------------------------------------------

class TestStartValidationTool:
    """Tests for StartValidationTool."""

    def test_start_validation(self, tool_registry: ToolRegistry):
        """Should start validation session."""
        result = tool_registry.execute("start_validation", {
            "workflow_id": "age-check",
            "case_count": 5,
            "strategy": "random",
        })

        assert result.success is True
        assert "session_id" in result.data
        assert result.data["progress"]["total"] == 5
        assert result.data["current_case"] is not None

    def test_start_validation_default_params(self, tool_registry: ToolRegistry):
        """Should use default parameters."""
        result = tool_registry.execute("start_validation", {
            "workflow_id": "age-check",
        })

        assert result.success is True
        assert result.data["session_id"] is not None

    def test_start_validation_nonexistent_workflow(self, tool_registry: ToolRegistry):
        """Should return error for non-existent workflow."""
        result = tool_registry.execute("start_validation", {
            "workflow_id": "nonexistent",
        })

        assert result.success is False
        assert "not found" in result.error.lower()


# -----------------------------------------------------------------------------
# Test: SubmitValidationTool
# -----------------------------------------------------------------------------

class TestSubmitValidationTool:
    """Tests for SubmitValidationTool."""

    def test_submit_validation(self, tool_registry: ToolRegistry):
        """Should submit validation answer."""
        # Start session first
        start_result = tool_registry.execute("start_validation", {
            "workflow_id": "age-check",
            "case_count": 2,
            "strategy": "random",
        })
        session_id = start_result.data["session_id"]

        # Submit answer
        result = tool_registry.execute("submit_validation", {
            "session_id": session_id,
            "answer": "Adult",
        })

        assert result.success is True
        assert "matched" in result.data
        assert "progress" in result.data
        assert "current_score" in result.data

    def test_submit_to_invalid_session(self, tool_registry: ToolRegistry):
        """Should return error for invalid session."""
        result = tool_registry.execute("submit_validation", {
            "session_id": "invalid",
            "answer": "Adult",
        })

        assert result.success is False


# -----------------------------------------------------------------------------
# Test: ListDomainsTool
# -----------------------------------------------------------------------------

class TestListDomainsTool:
    """Tests for ListDomainsTool."""

    def test_list_domains(self, tool_registry: ToolRegistry):
        """Should list available domains."""
        result = tool_registry.execute("list_domains", {})

        assert result.success is True
        domains = result.data["domains"]
        assert "nephrology" in domains
        assert "general" in domains


# -----------------------------------------------------------------------------
# Test: CreateWorkflowTool
# -----------------------------------------------------------------------------

class TestCreateWorkflowTool:
    """Tests for CreateWorkflowTool."""

    def test_create_simple_workflow(self, tool_registry: ToolRegistry):
        """Should create a workflow from specification."""
        result = tool_registry.execute("create_workflow", {
            "name": "Fever Check",
            "description": "Check if patient has fever",
            "domain": "general",
            "tags": ["fever", "temperature"],
            "inputs": [
                {
                    "id": "temp",
                    "name": "temperature",
                    "type": "float",
                    "range": {"min": 35.0, "max": 42.0},
                }
            ],
            "decisions": [
                {
                    "id": "fever_check",
                    "condition": "temperature >= 38.0",
                }
            ],
            "outputs": [
                {"id": "fever", "value": "Fever"},
                {"id": "normal", "value": "Normal"},
            ],
            "connections": [
                {"from_block": "temp", "to_block": "fever_check"},
                {"from_block": "fever_check", "to_block": "fever", "from_port": "true"},
                {"from_block": "fever_check", "to_block": "normal", "from_port": "false"},
            ],
        })

        assert result.success is True
        assert "workflow_id" in result.data
        assert result.data["name"] == "Fever Check"

    def test_create_workflow_with_string_outputs(self, tool_registry: ToolRegistry):
        """Should accept string array for outputs."""
        result = tool_registry.execute("create_workflow", {
            "name": "Simple Check",
            "description": "Simple workflow",
            "inputs": [
                {"name": "value", "type": "int"}
            ],
            "decisions": [
                {"id": "check", "condition": "value > 0"}
            ],
            "outputs": ["Positive", "Non-positive"],
            "connections": [
                {"from_block": "input0", "to_block": "check"},
                {"from_block": "check", "to_block": "output0", "from_port": "true"},
                {"from_block": "check", "to_block": "output1", "from_port": "false"},
            ],
        })

        assert result.success is True

    def test_create_workflow_with_invalid_type(self, tool_registry: ToolRegistry):
        """Should fail with invalid input type."""
        result = tool_registry.execute("create_workflow", {
            "name": "Invalid",
            "description": "Test",
            "inputs": [
                {"name": "value", "type": "invalid_type"}  # Invalid type
            ],
            "decisions": [],
            "outputs": ["Result"],
            "connections": [],
        })

        assert result.success is False
        assert "invalid" in result.error.lower() or "error" in result.error.lower()


# -----------------------------------------------------------------------------
# Test: Tool Schema Generation
# -----------------------------------------------------------------------------

class TestToolSchemas:
    """Tests for tool schema generation."""

    def test_all_tools_have_schemas(self, tool_registry: ToolRegistry):
        """All tools should have valid schemas."""
        for tool in tool_registry.list_tools():
            schema = tool.to_schema()

            assert "name" in schema
            assert "description" in schema
            assert "parameters" in schema
            assert "type" in schema["parameters"]
            assert schema["parameters"]["type"] == "object"

    def test_required_parameters_in_schema(self, tool_registry: ToolRegistry):
        """Required parameters should be listed."""
        details_tool = tool_registry.get("get_workflow_details")
        schema = details_tool.to_schema()

        assert "workflow_id" in schema["parameters"]["required"]
