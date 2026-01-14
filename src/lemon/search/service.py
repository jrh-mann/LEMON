"""Search service for workflow library.

This module provides high-level search capabilities over the workflow library.
It wraps the repository with semantic search operations that the orchestrator
agent will use via tools.

The search service does NOT use vector embeddings - it uses structured queries.
The LLM orchestrator provides the semantic understanding layer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

from lemon.core.interfaces import WorkflowFilters

if TYPE_CHECKING:
    from lemon.core.blocks import WorkflowSummary
    from lemon.storage.repository import SQLiteWorkflowRepository, InMemoryWorkflowRepository

    Repository = SQLiteWorkflowRepository | InMemoryWorkflowRepository


class SearchService:
    """Service for searching the workflow library.

    This provides the search operations that the orchestrator agent uses.
    Each method maps to a tool the agent can call.

    Usage:
        search = SearchService(repository)
        results = search.search(WorkflowFilters(domain="renal"))
        domains = search.list_domains()
    """

    def __init__(self, repository: "Repository"):
        """Initialize with a workflow repository.

        Args:
            repository: The workflow repository to search over.
        """
        self.repository = repository

    # -------------------------------------------------------------------------
    # Basic Search
    # -------------------------------------------------------------------------

    def search(self, filters: Optional[WorkflowFilters] = None) -> List["WorkflowSummary"]:
        """Search workflows matching filters.

        This is the main search method. Filters are ANDed together.

        Args:
            filters: Search filters (domain, tags, inputs, outputs, validation, etc.)

        Returns:
            List of matching workflow summaries, ordered by updated_at desc.
        """
        return self.repository.list(filters)

    def search_by_text(self, query: str) -> List["WorkflowSummary"]:
        """Search workflows by text query.

        Searches workflow names for the query string.
        The LLM orchestrator can interpret natural language and call this
        with extracted keywords.

        Args:
            query: Text to search for in workflow names.

        Returns:
            Matching workflows.
        """
        return self.repository.list(WorkflowFilters(name_contains=query))

    # -------------------------------------------------------------------------
    # Domain and Tag Discovery
    # -------------------------------------------------------------------------

    def list_domains(self) -> List[str]:
        """Get all unique domains in the library.

        Returns:
            Sorted list of domain names.
        """
        return self.repository.list_domains()

    def list_tags(self) -> List[str]:
        """Get all unique tags in the library.

        Returns:
            Sorted list of tags.
        """
        return self.repository.list_tags()

    def list_by_domain(self, domain: str) -> List["WorkflowSummary"]:
        """List all workflows in a domain.

        Args:
            domain: Domain name to filter by.

        Returns:
            Workflows in that domain.
        """
        return self.repository.list(WorkflowFilters(domain=domain))

    def list_by_tag(self, tag: str) -> List["WorkflowSummary"]:
        """List all workflows with a specific tag.

        Args:
            tag: Tag to filter by.

        Returns:
            Workflows with that tag.
        """
        return self.repository.list(WorkflowFilters(tags=[tag]))

    # -------------------------------------------------------------------------
    # Input/Output Based Search
    # -------------------------------------------------------------------------

    def find_by_input(self, input_name: str) -> List["WorkflowSummary"]:
        """Find workflows that have a specific input.

        Useful for finding workflows that can consume a particular data point.

        Args:
            input_name: Name of the input to search for (e.g., "eGFR", "age").

        Returns:
            Workflows that have this input.
        """
        return self.repository.list(WorkflowFilters(has_input=input_name))

    def find_by_input_type(self, input_type: str) -> List["WorkflowSummary"]:
        """Find workflows that have inputs of a specific type.

        Args:
            input_type: Type to search for (e.g., "int", "float", "enum").

        Returns:
            Workflows that have inputs of this type.
        """
        return self.repository.list(WorkflowFilters(has_input_type=input_type))

    def find_by_output(self, output_value: str) -> List["WorkflowSummary"]:
        """Find workflows that produce a specific output.

        Useful for finding workflows that can provide a particular result.

        Args:
            output_value: Output value to search for (e.g., "approved", "G3a").

        Returns:
            Workflows that produce this output.
        """
        return self.repository.list(WorkflowFilters(has_output=output_value))

    # -------------------------------------------------------------------------
    # Composition Helpers
    # -------------------------------------------------------------------------

    def find_composable_for_inputs(
        self, required_inputs: List[str]
    ) -> List["WorkflowSummary"]:
        """Find workflows that could provide outputs to satisfy required inputs.

        Given a list of input names that a workflow needs, find other workflows
        whose outputs might satisfy those inputs.

        Note: This does a simple search - the orchestrator agent should verify
        that the outputs actually match the expected types/values.

        Args:
            required_inputs: List of input names needed.

        Returns:
            Workflows that produce outputs matching any of the input names.
        """
        results = []
        seen_ids = set()

        for input_name in required_inputs:
            # Search for workflows whose outputs match this input name
            # This is a heuristic - outputs like "ckd_stage" might feed input "ckd_stage"
            matches = self.repository.list(WorkflowFilters(has_output=input_name))
            for m in matches:
                if m.id not in seen_ids:
                    seen_ids.add(m.id)
                    results.append(m)

        return results

    def find_consumers_of_outputs(
        self, available_outputs: List[str]
    ) -> List["WorkflowSummary"]:
        """Find workflows that could consume the given outputs as inputs.

        Given outputs from a workflow, find other workflows that have inputs
        matching those output names.

        Args:
            available_outputs: List of output values/names available.

        Returns:
            Workflows that have inputs matching any of the output names.
        """
        results = []
        seen_ids = set()

        for output in available_outputs:
            matches = self.repository.list(WorkflowFilters(has_input=output))
            for m in matches:
                if m.id not in seen_ids:
                    seen_ids.add(m.id)
                    results.append(m)

        return results

    # -------------------------------------------------------------------------
    # Validation-Based Search
    # -------------------------------------------------------------------------

    def find_validated(self, min_score: float = 80.0) -> List["WorkflowSummary"]:
        """Find workflows with validation score above threshold.

        Args:
            min_score: Minimum validation score (0-100). Default 80.

        Returns:
            Validated workflows.
        """
        return self.repository.list(WorkflowFilters(min_validation=min_score))

    def find_unvalidated(self) -> List["WorkflowSummary"]:
        """Find workflows that haven't been validated.

        Returns:
            Workflows with validation_score < 80 or validation_count < 10.
        """
        return self.repository.list(WorkflowFilters(is_validated=False))

    def find_needs_validation(self) -> List["WorkflowSummary"]:
        """Find workflows that need more validation.

        Returns workflows that have some validation but haven't reached
        the threshold for being considered fully validated.

        Returns:
            Partially validated workflows.
        """
        return self.repository.list(
            WorkflowFilters(min_validation=1.0, is_validated=False)
        )

    # -------------------------------------------------------------------------
    # Combined Searches
    # -------------------------------------------------------------------------

    def find_validated_by_domain(
        self, domain: str, min_score: float = 80.0
    ) -> List["WorkflowSummary"]:
        """Find validated workflows in a specific domain.

        Args:
            domain: Domain to filter by.
            min_score: Minimum validation score.

        Returns:
            Validated workflows in the domain.
        """
        return self.repository.list(
            WorkflowFilters(domain=domain, min_validation=min_score)
        )

    def find_by_criteria(
        self,
        domain: Optional[str] = None,
        tags: Optional[List[str]] = None,
        has_input: Optional[str] = None,
        has_output: Optional[str] = None,
        min_validation: Optional[float] = None,
        name_contains: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List["WorkflowSummary"]:
        """Find workflows matching multiple criteria.

        This is the most flexible search method, allowing any combination
        of filters. All specified filters are ANDed together.

        Args:
            domain: Filter by domain.
            tags: Filter by any of these tags.
            has_input: Filter by input name.
            has_output: Filter by output value.
            min_validation: Minimum validation score.
            name_contains: Text search in name.
            limit: Maximum results to return.

        Returns:
            Matching workflows.
        """
        return self.repository.list(
            WorkflowFilters(
                domain=domain,
                tags=tags,
                has_input=has_input,
                has_output=has_output,
                min_validation=min_validation,
                name_contains=name_contains,
                limit=limit,
            )
        )

    # -------------------------------------------------------------------------
    # Statistics
    # -------------------------------------------------------------------------

    def count_all(self) -> int:
        """Count total workflows in library.

        Returns:
            Total workflow count.
        """
        return len(self.repository.list())

    def count_validated(self) -> int:
        """Count validated workflows.

        Returns:
            Count of workflows with is_validated=True.
        """
        return len(self.repository.list(WorkflowFilters(is_validated=True)))

    def count_by_domain(self) -> dict:
        """Count workflows per domain.

        Returns:
            Dict mapping domain name to count.
        """
        domains = self.list_domains()
        return {
            domain: len(self.list_by_domain(domain))
            for domain in domains
        }
