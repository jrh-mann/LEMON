"""Tests for SearchService.

Tests cover:
- Basic search operations
- Domain/tag listing
- Input/output based search
- Composition helpers
- Validation-based search
"""

import pytest

from lemon.core.blocks import (
    InputBlock,
    DecisionBlock,
    OutputBlock,
    WorkflowRefBlock,
    InputType,
    Range,
    Workflow,
    WorkflowMetadata,
)
from lemon.core.interfaces import WorkflowFilters
from lemon.storage.repository import InMemoryWorkflowRepository
from lemon.search.service import SearchService


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def repo():
    """Fresh in-memory repository."""
    return InMemoryWorkflowRepository()


@pytest.fixture
def search(repo):
    """Search service with fresh repository."""
    return SearchService(repo)


@pytest.fixture
def age_check_workflow():
    """Simple age checking workflow."""
    return Workflow(
        id="age-check",
        metadata=WorkflowMetadata(
            name="Age Check",
            description="Checks if user is adult",
            domain="testing",
            tags=["age", "validation"],
            validation_score=85.0,
            validation_count=30,
        ),
        blocks=[
            InputBlock(name="age", input_type=InputType.INT, range=Range(min=0, max=120)),
            OutputBlock(value="adult"),
            OutputBlock(value="minor"),
        ],
    )


@pytest.fixture
def ckd_staging_workflow():
    """CKD staging workflow."""
    return Workflow(
        id="ckd-staging",
        metadata=WorkflowMetadata(
            name="CKD Staging",
            description="Stages chronic kidney disease",
            domain="renal",
            tags=["kidney", "ckd", "staging"],
            validation_score=92.0,
            validation_count=50,
        ),
        blocks=[
            InputBlock(name="eGFR", input_type=InputType.FLOAT),
            InputBlock(name="ACR", input_type=InputType.FLOAT),
            OutputBlock(value="G1"),
            OutputBlock(value="G2"),
            OutputBlock(value="G3a"),
            OutputBlock(value="G3b"),
            OutputBlock(value="G4"),
            OutputBlock(value="G5"),
        ],
    )


@pytest.fixture
def diabetes_workflow():
    """Diabetes management workflow."""
    return Workflow(
        id="diabetes-mgmt",
        metadata=WorkflowMetadata(
            name="Diabetes Management",
            description="Manages diabetes patients",
            domain="diabetes",
            tags=["diabetes", "hba1c"],
            validation_score=40.0,
            validation_count=5,
        ),
        blocks=[
            InputBlock(name="HbA1c", input_type=InputType.FLOAT),
            InputBlock(name="age", input_type=InputType.INT),
            OutputBlock(value="controlled"),
            OutputBlock(value="uncontrolled"),
        ],
    )


@pytest.fixture
def populated_search(search, repo, age_check_workflow, ckd_staging_workflow, diabetes_workflow):
    """Search service with pre-populated test data."""
    repo.save(age_check_workflow)
    repo.save(ckd_staging_workflow)
    repo.save(diabetes_workflow)
    return search


# -----------------------------------------------------------------------------
# Basic Search Tests
# -----------------------------------------------------------------------------


class TestBasicSearch:
    """Tests for basic search operations."""

    def test_search_empty_repo(self, search):
        """Search on empty repo returns empty list."""
        result = search.search()
        assert result == []

    def test_search_all(self, populated_search):
        """Search with no filters returns all workflows."""
        result = populated_search.search()
        assert len(result) == 3

    def test_search_with_filters(self, populated_search):
        """Search respects filters."""
        result = populated_search.search(WorkflowFilters(domain="renal"))
        assert len(result) == 1
        assert result[0].name == "CKD Staging"

    def test_search_by_text(self, populated_search):
        """Can search by text in name."""
        result = populated_search.search_by_text("CKD")
        assert len(result) == 1
        assert result[0].name == "CKD Staging"

    def test_search_by_text_partial(self, populated_search):
        """Text search is partial match."""
        result = populated_search.search_by_text("age")
        # "Age Check" contains "age" in name
        # "Diabetes Management" contains "age" in "Management"
        assert len(result) == 2
        names = {r.name for r in result}
        assert "Age Check" in names

    def test_search_by_text_case_insensitive(self, populated_search):
        """Text search is case insensitive."""
        result = populated_search.search_by_text("ckd")
        assert len(result) == 1


# -----------------------------------------------------------------------------
# Domain and Tag Tests
# -----------------------------------------------------------------------------


class TestDomainAndTags:
    """Tests for domain and tag listing."""

    def test_list_domains_empty(self, search):
        """Empty repo has no domains."""
        assert search.list_domains() == []

    def test_list_domains(self, populated_search):
        """Lists all unique domains."""
        domains = populated_search.list_domains()
        assert set(domains) == {"testing", "renal", "diabetes"}

    def test_list_tags_empty(self, search):
        """Empty repo has no tags."""
        assert search.list_tags() == []

    def test_list_tags(self, populated_search):
        """Lists all unique tags."""
        tags = populated_search.list_tags()
        expected = {"age", "validation", "kidney", "ckd", "staging", "diabetes", "hba1c"}
        assert set(tags) == expected

    def test_list_by_domain(self, populated_search):
        """Can list workflows by domain."""
        result = populated_search.list_by_domain("renal")
        assert len(result) == 1
        assert result[0].name == "CKD Staging"

    def test_list_by_tag(self, populated_search):
        """Can list workflows by tag."""
        result = populated_search.list_by_tag("kidney")
        assert len(result) == 1
        assert result[0].name == "CKD Staging"


# -----------------------------------------------------------------------------
# Input/Output Search Tests
# -----------------------------------------------------------------------------


class TestInputOutputSearch:
    """Tests for input/output based search."""

    def test_find_by_input(self, populated_search):
        """Can find workflows by input name."""
        result = populated_search.find_by_input("eGFR")
        assert len(result) == 1
        assert result[0].name == "CKD Staging"

    def test_find_by_input_multiple_matches(self, populated_search):
        """Multiple workflows can match same input."""
        result = populated_search.find_by_input("age")
        assert len(result) == 2
        names = {r.name for r in result}
        assert names == {"Age Check", "Diabetes Management"}

    def test_find_by_input_no_match(self, populated_search):
        """No match returns empty list."""
        result = populated_search.find_by_input("nonexistent")
        assert result == []

    def test_find_by_input_type(self, populated_search):
        """Can find workflows by input type."""
        result = populated_search.find_by_input_type("float")
        assert len(result) == 2
        names = {r.name for r in result}
        assert names == {"CKD Staging", "Diabetes Management"}

    def test_find_by_output(self, populated_search):
        """Can find workflows by output value."""
        result = populated_search.find_by_output("G3a")
        assert len(result) == 1
        assert result[0].name == "CKD Staging"

    def test_find_by_output_shared(self, populated_search):
        """Multiple workflows can have same output."""
        # Both age check and diabetes could have similar outputs
        result = populated_search.find_by_output("adult")
        assert len(result) == 1
        assert result[0].name == "Age Check"


# -----------------------------------------------------------------------------
# Composition Helper Tests
# -----------------------------------------------------------------------------


class TestCompositionHelpers:
    """Tests for composition search helpers."""

    def test_find_composable_for_inputs(self, populated_search):
        """Find workflows that could provide required inputs."""
        # If we need "eGFR" as input, find workflows that output "eGFR"
        result = populated_search.find_composable_for_inputs(["eGFR"])
        # In this test data, no workflow outputs "eGFR" - they all use it as input
        assert result == []

    def test_find_consumers_of_outputs(self, populated_search):
        """Find workflows that could use our outputs."""
        # CKD staging outputs G1, G2, etc. - any workflows take those as inputs?
        result = populated_search.find_consumers_of_outputs(["G1", "G2"])
        # No workflows in test data have G1/G2 as inputs
        assert result == []

    def test_find_composable_deduplicates(self, repo, search):
        """Composable search deduplicates results."""
        # Create workflow that outputs multiple values
        workflow = Workflow(
            id="multi-out",
            metadata=WorkflowMetadata(name="Multi Output"),
            blocks=[
                OutputBlock(value="x"),
                OutputBlock(value="y"),
            ],
        )
        repo.save(workflow)

        # Search for both x and y - should only return workflow once
        result = search.find_composable_for_inputs(["x", "y"])
        # Multi-out outputs x and y, so it matches
        # But since we're looking for workflows whose outputs match our inputs,
        # and multi-out outputs x/y (not takes them as input), this is backwards
        # Actually the function searches for workflows that OUTPUT the required inputs
        assert len(result) == 1


# -----------------------------------------------------------------------------
# Validation Search Tests
# -----------------------------------------------------------------------------


class TestValidationSearch:
    """Tests for validation-based search."""

    def test_find_validated(self, populated_search):
        """Find validated workflows."""
        result = populated_search.find_validated()
        assert len(result) == 2
        names = {r.name for r in result}
        assert names == {"Age Check", "CKD Staging"}

    def test_find_validated_custom_threshold(self, populated_search):
        """Can use custom validation threshold."""
        result = populated_search.find_validated(min_score=90.0)
        assert len(result) == 1
        assert result[0].name == "CKD Staging"

    def test_find_unvalidated(self, populated_search):
        """Find unvalidated workflows."""
        result = populated_search.find_unvalidated()
        assert len(result) == 1
        assert result[0].name == "Diabetes Management"

    def test_find_needs_validation(self, populated_search):
        """Find workflows that need more validation."""
        result = populated_search.find_needs_validation()
        assert len(result) == 1
        assert result[0].name == "Diabetes Management"


# -----------------------------------------------------------------------------
# Combined Search Tests
# -----------------------------------------------------------------------------


class TestCombinedSearch:
    """Tests for combined criteria search."""

    def test_find_validated_by_domain(self, populated_search):
        """Find validated workflows in domain."""
        result = populated_search.find_validated_by_domain("renal")
        assert len(result) == 1
        assert result[0].name == "CKD Staging"

    def test_find_validated_by_domain_no_match(self, populated_search):
        """Returns empty when no validated workflows in domain."""
        result = populated_search.find_validated_by_domain("diabetes")
        assert result == []

    def test_find_by_criteria_multiple(self, populated_search):
        """Can combine multiple criteria."""
        result = populated_search.find_by_criteria(
            domain="renal",
            min_validation=80.0,
            has_input="eGFR",
        )
        assert len(result) == 1
        assert result[0].name == "CKD Staging"

    def test_find_by_criteria_with_limit(self, populated_search):
        """Limit parameter works."""
        result = populated_search.find_by_criteria(limit=1)
        assert len(result) == 1


# -----------------------------------------------------------------------------
# Statistics Tests
# -----------------------------------------------------------------------------


class TestStatistics:
    """Tests for statistics methods."""

    def test_count_all_empty(self, search):
        """Empty repo has zero count."""
        assert search.count_all() == 0

    def test_count_all(self, populated_search):
        """Counts all workflows."""
        assert populated_search.count_all() == 3

    def test_count_validated(self, populated_search):
        """Counts validated workflows."""
        assert populated_search.count_validated() == 2

    def test_count_by_domain(self, populated_search):
        """Counts workflows per domain."""
        counts = populated_search.count_by_domain()
        assert counts == {
            "testing": 1,
            "renal": 1,
            "diabetes": 1,
        }
