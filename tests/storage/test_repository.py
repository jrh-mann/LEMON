"""Tests for workflow repository implementations.

Tests cover:
- SQLiteWorkflowRepository
- InMemoryWorkflowRepository
- All CRUD operations
- Filtering and search
"""

import pytest
from datetime import datetime

from lemon.core.blocks import (
    InputBlock,
    DecisionBlock,
    OutputBlock,
    WorkflowRefBlock,
    InputType,
    Range,
    Connection,
    PortType,
    Workflow,
    WorkflowMetadata,
)
from lemon.core.interfaces import WorkflowFilters
from lemon.storage.repository import SQLiteWorkflowRepository, InMemoryWorkflowRepository


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture(params=["sqlite", "memory"])
def repo(request):
    """Parameterized fixture that tests both repository implementations."""
    if request.param == "sqlite":
        return SQLiteWorkflowRepository(":memory:")
    else:
        return InMemoryWorkflowRepository()


@pytest.fixture
def sqlite_repo():
    """SQLite-specific repository for SQLite-only tests."""
    return SQLiteWorkflowRepository(":memory:")


@pytest.fixture
def sample_workflow():
    """Create a sample workflow for testing."""
    return Workflow(
        id="test-workflow-1",
        metadata=WorkflowMetadata(
            name="Age Check",
            description="Checks if user is adult",
            domain="testing",
            tags=["test", "age"],
        ),
        blocks=[
            InputBlock(id="input-age", name="age", input_type=InputType.INT, range=Range(min=0, max=120)),
            DecisionBlock(id="decision-1", condition="age >= 18"),
            OutputBlock(id="output-adult", value="adult"),
            OutputBlock(id="output-minor", value="minor"),
        ],
        connections=[
            Connection(from_block="input-age", to_block="decision-1"),
            Connection(from_block="decision-1", from_port=PortType.TRUE, to_block="output-adult"),
            Connection(from_block="decision-1", from_port=PortType.FALSE, to_block="output-minor"),
        ],
    )


@pytest.fixture
def another_workflow():
    """Create another sample workflow."""
    return Workflow(
        id="test-workflow-2",
        metadata=WorkflowMetadata(
            name="CKD Staging",
            description="Stages chronic kidney disease",
            domain="renal",
            tags=["kidney", "ckd"],
            validation_score=92.0,
            validation_count=50,
        ),
        blocks=[
            InputBlock(id="input-egfr", name="eGFR", input_type=InputType.FLOAT),
            OutputBlock(id="output-g1", value="G1"),
            OutputBlock(id="output-g5", value="G5"),
        ],
        connections=[],
    )


@pytest.fixture
def composed_workflow(sample_workflow, another_workflow, repo):
    """Create a workflow that references another workflow."""
    # First save the referenced workflow
    repo.save(another_workflow)

    return Workflow(
        id="composed-workflow",
        metadata=WorkflowMetadata(
            name="Full Assessment",
            domain="testing",
            tags=["composed"],
        ),
        blocks=[
            InputBlock(id="input-egfr", name="eGFR", input_type=InputType.FLOAT),
            WorkflowRefBlock(
                id="ref-ckd",
                ref_id="test-workflow-2",
                ref_name="CKD Staging",
                input_mapping={"eGFR": "eGFR"},
            ),
            OutputBlock(id="output-done", value="assessment complete"),
        ],
        connections=[],
    )


# -----------------------------------------------------------------------------
# Basic CRUD Tests
# -----------------------------------------------------------------------------


class TestRepositoryCRUD:
    """Test basic CRUD operations."""

    def test_save_and_retrieve(self, repo, sample_workflow):
        """Saved workflow can be retrieved by ID."""
        workflow_id = repo.save(sample_workflow)

        assert workflow_id == "test-workflow-1"

        retrieved = repo.get(workflow_id)
        assert retrieved is not None
        assert retrieved.id == sample_workflow.id
        assert retrieved.metadata.name == sample_workflow.metadata.name

    def test_get_nonexistent(self, repo):
        """Getting non-existent workflow returns None."""
        result = repo.get("nonexistent-id")
        assert result is None

    def test_exists(self, repo, sample_workflow):
        """Can check if workflow exists."""
        assert repo.exists("test-workflow-1") is False

        repo.save(sample_workflow)

        assert repo.exists("test-workflow-1") is True
        assert repo.exists("nonexistent") is False

    def test_delete(self, repo, sample_workflow):
        """Can delete a workflow."""
        repo.save(sample_workflow)
        assert repo.exists("test-workflow-1") is True

        result = repo.delete("test-workflow-1")
        assert result is True
        assert repo.exists("test-workflow-1") is False

    def test_delete_nonexistent(self, repo):
        """Deleting non-existent workflow returns False."""
        result = repo.delete("nonexistent")
        assert result is False

    def test_update_workflow(self, repo, sample_workflow):
        """Saving existing workflow updates it."""
        repo.save(sample_workflow)

        # Modify and save again
        sample_workflow.metadata.name = "Updated Name"
        sample_workflow.metadata.description = "Updated description"
        repo.save(sample_workflow)

        retrieved = repo.get("test-workflow-1")
        assert retrieved.metadata.name == "Updated Name"
        assert retrieved.metadata.description == "Updated description"

    def test_list_empty(self, repo):
        """Empty repository returns empty list."""
        result = repo.list()
        assert result == []

    def test_list_all(self, repo, sample_workflow, another_workflow):
        """Can list all workflows."""
        repo.save(sample_workflow)
        repo.save(another_workflow)

        result = repo.list()
        assert len(result) == 2

    def test_update_validation(self, repo, sample_workflow):
        """Can update validation score and count."""
        repo.save(sample_workflow)

        result = repo.update_validation("test-workflow-1", score=85.0, count=20)
        assert result is True

        retrieved = repo.get("test-workflow-1")
        assert retrieved.metadata.validation_score == 85.0
        assert retrieved.metadata.validation_count == 20

    def test_update_validation_nonexistent(self, repo):
        """Updating non-existent workflow returns False."""
        result = repo.update_validation("nonexistent", score=50.0, count=10)
        assert result is False


# -----------------------------------------------------------------------------
# Serialization Tests
# -----------------------------------------------------------------------------


class TestSerialization:
    """Test workflow serialization and deserialization."""

    def test_blocks_roundtrip(self, repo, sample_workflow):
        """All block types survive save/load."""
        repo.save(sample_workflow)
        retrieved = repo.get("test-workflow-1")

        assert len(retrieved.blocks) == len(sample_workflow.blocks)
        assert len(retrieved.input_blocks) == 1
        assert len(retrieved.decision_blocks) == 1
        assert len(retrieved.output_blocks) == 2

    def test_connections_roundtrip(self, repo, sample_workflow):
        """Connections survive save/load."""
        repo.save(sample_workflow)
        retrieved = repo.get("test-workflow-1")

        assert len(retrieved.connections) == 3

        # Check port types preserved
        decision_conns = retrieved.get_connections_from("decision-1")
        ports = {c.from_port for c in decision_conns}
        assert PortType.TRUE in ports
        assert PortType.FALSE in ports

    def test_metadata_roundtrip(self, repo, sample_workflow):
        """Metadata survives save/load."""
        repo.save(sample_workflow)
        retrieved = repo.get("test-workflow-1")

        assert retrieved.metadata.name == "Age Check"
        assert retrieved.metadata.description == "Checks if user is adult"
        assert retrieved.metadata.domain == "testing"
        assert retrieved.metadata.tags == ["test", "age"]

    def test_workflow_ref_block_roundtrip(self, repo, composed_workflow):
        """WorkflowRefBlock survives save/load."""
        repo.save(composed_workflow)
        retrieved = repo.get("composed-workflow")

        ref_blocks = retrieved.workflow_ref_blocks
        assert len(ref_blocks) == 1
        assert ref_blocks[0].ref_id == "test-workflow-2"
        assert ref_blocks[0].input_mapping == {"eGFR": "eGFR"}

    def test_timestamps_preserved(self, repo, sample_workflow):
        """Timestamps are preserved on save/load."""
        repo.save(sample_workflow)
        retrieved = repo.get("test-workflow-1")

        assert isinstance(retrieved.metadata.created_at, datetime)
        assert isinstance(retrieved.metadata.updated_at, datetime)


# -----------------------------------------------------------------------------
# Filtering Tests
# -----------------------------------------------------------------------------


class TestFiltering:
    """Test list filtering."""

    @pytest.fixture(autouse=True)
    def populate_repo(self, repo, sample_workflow, another_workflow):
        """Populate repository with test data."""
        repo.save(sample_workflow)
        repo.save(another_workflow)

    def test_filter_by_domain(self, repo):
        """Can filter by domain."""
        result = repo.list(WorkflowFilters(domain="testing"))
        assert len(result) == 1
        assert result[0].name == "Age Check"

        result = repo.list(WorkflowFilters(domain="renal"))
        assert len(result) == 1
        assert result[0].name == "CKD Staging"

    def test_filter_by_input_name(self, repo):
        """Can filter by input name."""
        result = repo.list(WorkflowFilters(has_input="age"))
        assert len(result) == 1
        assert result[0].name == "Age Check"

        result = repo.list(WorkflowFilters(has_input="eGFR"))
        assert len(result) == 1
        assert result[0].name == "CKD Staging"

    def test_filter_by_output_value(self, repo):
        """Can filter by output value."""
        result = repo.list(WorkflowFilters(has_output="adult"))
        assert len(result) == 1
        assert result[0].name == "Age Check"

        result = repo.list(WorkflowFilters(has_output="G1"))
        assert len(result) == 1
        assert result[0].name == "CKD Staging"

    def test_filter_by_min_validation(self, repo):
        """Can filter by minimum validation score."""
        result = repo.list(WorkflowFilters(min_validation=90.0))
        assert len(result) == 1
        assert result[0].name == "CKD Staging"

        result = repo.list(WorkflowFilters(min_validation=0.0))
        assert len(result) == 2

    def test_filter_by_tags(self, repo):
        """Can filter by tags."""
        result = repo.list(WorkflowFilters(tags=["kidney"]))
        assert len(result) == 1
        assert result[0].name == "CKD Staging"

        result = repo.list(WorkflowFilters(tags=["test"]))
        assert len(result) == 1
        assert result[0].name == "Age Check"

    def test_filter_by_name_contains(self, repo):
        """Can filter by name substring."""
        result = repo.list(WorkflowFilters(name_contains="Age"))
        assert len(result) == 1
        assert result[0].name == "Age Check"

        result = repo.list(WorkflowFilters(name_contains="CKD"))
        assert len(result) == 1
        assert result[0].name == "CKD Staging"

    def test_filter_by_is_validated(self, repo):
        """Can filter by validation status."""
        # CKD Staging has 92% score and 50 validations - is validated
        # Age Check has 0% score and 0 validations - not validated

        result = repo.list(WorkflowFilters(is_validated=True))
        assert len(result) == 1
        assert result[0].name == "CKD Staging"

        result = repo.list(WorkflowFilters(is_validated=False))
        assert len(result) == 1
        assert result[0].name == "Age Check"

    def test_combined_filters(self, repo):
        """Multiple filters AND together."""
        # Add another renal workflow
        another_renal = Workflow(
            id="test-3",
            metadata=WorkflowMetadata(name="AKI Check", domain="renal"),
            blocks=[OutputBlock(value="alert")],
        )
        repo.save(another_renal)

        # Filter by domain + validation
        result = repo.list(WorkflowFilters(domain="renal", min_validation=50.0))
        assert len(result) == 1
        assert result[0].name == "CKD Staging"

    def test_filter_limit_offset(self, repo):
        """Can paginate results."""
        result = repo.list(WorkflowFilters(limit=1))
        assert len(result) == 1

        result = repo.list(WorkflowFilters(limit=1, offset=1))
        assert len(result) == 1


# -----------------------------------------------------------------------------
# List Domains/Tags Tests
# -----------------------------------------------------------------------------


class TestListMetadata:
    """Test listing domains and tags."""

    @pytest.fixture(autouse=True)
    def populate_repo(self, repo, sample_workflow, another_workflow):
        """Populate repository with test data."""
        repo.save(sample_workflow)
        repo.save(another_workflow)

    def test_list_domains(self, repo):
        """Can list all domains."""
        domains = repo.list_domains()
        assert set(domains) == {"testing", "renal"}

    def test_list_tags(self, repo):
        """Can list all tags."""
        tags = repo.list_tags()
        assert set(tags) == {"test", "age", "kidney", "ckd"}


# -----------------------------------------------------------------------------
# Summary Tests
# -----------------------------------------------------------------------------


class TestWorkflowSummary:
    """Test WorkflowSummary generation."""

    def test_summary_includes_inputs(self, repo, sample_workflow):
        """Summary includes input names."""
        repo.save(sample_workflow)
        result = repo.list()
        assert len(result) == 1
        assert "age" in result[0].input_names

    def test_summary_includes_outputs(self, repo, sample_workflow):
        """Summary includes output values."""
        repo.save(sample_workflow)
        result = repo.list()
        assert len(result) == 1
        assert set(result[0].output_values) == {"adult", "minor"}

    def test_summary_confidence(self, repo, another_workflow):
        """Summary includes correct confidence level."""
        repo.save(another_workflow)
        result = repo.list()
        assert len(result) == 1
        # 50 validations = high confidence
        assert result[0].confidence == "high"

    def test_summary_is_validated(self, repo, another_workflow):
        """Summary includes is_validated flag."""
        repo.save(another_workflow)
        result = repo.list()
        assert len(result) == 1
        # 92% score + 50 validations = validated
        assert result[0].is_validated is True


# -----------------------------------------------------------------------------
# SQLite-Specific Tests
# -----------------------------------------------------------------------------


class TestSQLiteSpecific:
    """Tests specific to SQLite implementation."""

    def test_persistence(self, tmp_path):
        """Data persists across repository instances."""
        db_path = tmp_path / "test.db"

        # Create and save
        repo1 = SQLiteWorkflowRepository(db_path)
        workflow = Workflow(
            id="persist-test",
            metadata=WorkflowMetadata(name="Persist Test"),
            blocks=[OutputBlock(value="done")],
        )
        repo1.save(workflow)

        # New instance should see the data
        repo2 = SQLiteWorkflowRepository(db_path)
        retrieved = repo2.get("persist-test")
        assert retrieved is not None
        assert retrieved.metadata.name == "Persist Test"

    def test_foreign_key_cascade(self, sqlite_repo, sample_workflow):
        """Deleting workflow cascades to related tables."""
        sqlite_repo.save(sample_workflow)

        # Verify denormalized data exists
        with sqlite_repo._connection() as conn:
            inputs = conn.execute(
                "SELECT COUNT(*) as cnt FROM workflow_inputs WHERE workflow_id = ?",
                ("test-workflow-1",),
            ).fetchone()
            assert inputs["cnt"] > 0

        # Delete and verify cascade
        sqlite_repo.delete("test-workflow-1")

        with sqlite_repo._connection() as conn:
            inputs = conn.execute(
                "SELECT COUNT(*) as cnt FROM workflow_inputs WHERE workflow_id = ?",
                ("test-workflow-1",),
            ).fetchone()
            assert inputs["cnt"] == 0


# -----------------------------------------------------------------------------
# Edge Cases
# -----------------------------------------------------------------------------


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_empty_workflow(self, repo):
        """Can save workflow with no blocks."""
        workflow = Workflow(
            id="empty",
            metadata=WorkflowMetadata(name="Empty"),
            blocks=[],
            connections=[],
        )
        repo.save(workflow)
        retrieved = repo.get("empty")
        assert retrieved is not None
        assert len(retrieved.blocks) == 0

    def test_workflow_with_special_characters(self, repo):
        """Handles special characters in names."""
        workflow = Workflow(
            id="special",
            metadata=WorkflowMetadata(
                name="Test & \"Workflow\" <script>",
                description="It's a test with 'quotes'",
            ),
            blocks=[],
        )
        repo.save(workflow)
        retrieved = repo.get("special")
        assert retrieved.metadata.name == "Test & \"Workflow\" <script>"

    def test_filter_no_matches(self, repo, sample_workflow):
        """Filter with no matches returns empty list."""
        repo.save(sample_workflow)
        result = repo.list(WorkflowFilters(domain="nonexistent"))
        assert result == []

    def test_list_ordering(self, repo):
        """Results are ordered by updated_at descending."""
        # Save workflows in order
        for i in range(3):
            workflow = Workflow(
                id=f"workflow-{i}",
                metadata=WorkflowMetadata(name=f"Workflow {i}"),
                blocks=[],
            )
            repo.save(workflow)

        result = repo.list()
        # Most recently saved should be first
        assert result[0].name == "Workflow 2"
        assert result[2].name == "Workflow 0"
